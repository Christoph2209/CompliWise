"""
database_service.py

Reads and writes for the scheduling pipeline, kept out of main.py.

The read helpers (get_students, get_staff) turn ORM rows into the plain
dicts the scheduler works with. The create_* helpers do the reverse: they
take the scheduler's output for one run and save it as ScheduleEntry,
StaffScheduleEntry, ComplianceFlag and FlexGroup rows. The scheduler
refers to students by their external ID and to teachers by name, so the
save step maps those back to database rows (see _build_*_index).

Every function opens and closes its own session, and every write is
scoped to one school: either the school that owns run_id, or school_id.
"""

import logging
import uuid
from typing import Any, Dict, List

from dmscheduler_db import (
    SessionLocal,
    School,
    Student,
    StaffMember,
    StudentService,
    ScheduleRun,
    ScheduleEntry,
    StaffScheduleEntry,
    ComplianceFlag,
    FlexGroup,
    FlexGroupStudent,
)

logger = logging.getLogger(__name__)


class DBAPIError(RuntimeError):
    """A save/load failed for a reason the API should report (bad run, wrong school)."""


def _resolve_school(db, school_id=None, run_id=None):
    """
    Which school a write belongs to. Preference order:
      1. the school that owns run_id (so a run's rows can never be
         written under a different school),
      2. an explicit school_id.
    Raises DBAPIError when neither is given, rather than guessing a school.
    """
    if run_id is not None:
        run = db.query(ScheduleRun).filter(ScheduleRun.id == uuid.UUID(str(run_id))).first()
        if not run:
            raise DBAPIError(f"Schedule run {run_id} not found")
        if school_id is not None and str(run.school_id) != str(school_id):
            raise DBAPIError("Schedule run belongs to a different school")
        return db.query(School).filter(School.id == run.school_id).first()

    if school_id is not None:
        school = db.query(School).filter(School.id == uuid.UUID(str(school_id))).first()
        if not school:
            raise DBAPIError(f"School {school_id} not found")
        return school

    raise DBAPIError("A school_id or run_id is required")


def get_students(
    active_only: bool = False,
    search: str | None = None,
    grade: int | None = None,
    iep: bool | None = None,
    mtss_tier: int | None = None,
    school_id=None,
) -> List[Dict[str, Any]]:
    """
    Students as scheduler-ready dicts, each with its `services` list.

    Optional filters: name search, grade, IEP status and MTSS tier.
    school_id should always be passed; None returns every school's
    students. active_only is accepted for API compatibility but ignored
    (there is no inactive status yet).
    """

    db = SessionLocal()

    try:
        query = db.query(Student)
        if school_id is not None:
            query = query.filter(Student.school_id == uuid.UUID(str(school_id)))

        if search:
            query = query.filter(
                (Student.first_name.ilike(f"%{search}%")) |
                (Student.last_name.ilike(f"%{search}%"))
            )
        if grade:
            query = query.filter(Student.grade == grade)
        if iep is not None:
            query = query.filter(Student.has_iep == iep)
        if mtss_tier:
            query = query.filter(Student.mtss_tier == mtss_tier)

        students = query.all()
        student_ids = [s.id for s in students]

        # Pull every StudentService row for these students in one query
        # and group by student_id, rather than N+1 querying per student.
        services_by_student: dict = {}
        if student_ids:
            service_rows = (
                db.query(StudentService)
                .filter(StudentService.student_id.in_(student_ids))
                # Stable order, so the editor's rows don't shuffle on reload.
                .order_by(StudentService.created_at, StudentService.id)
                .all()
            )
            for svc in service_rows:
                services_by_student.setdefault(svc.student_id, []).append({
                    "id": str(svc.id),
                    "subject": svc.subject_area or svc.service_type,
                    "service_type": svc.service_type,
                    "minutes": svc.minutes_per_week,
                    "minutes_per_week": svc.minutes_per_week,
                    "sessions_per_week": svc.sessions_per_week,
                    "notes": svc.notes,
                    "is_pullout": svc.is_pullout,
                    # Which class a push-in goes into (e.g. Resource Room "Math").
                    # Without it the engine falls back to the service's
                    # default push-in subjects.
                    "subject_area": svc.subject_area,
                })

        return [
            {
                "id": str(student.id),
                "student_id": student.external_student_id or str(student.id),
                "first_name": student.first_name,
                "last_name": student.last_name,
                "grade": student.grade,
                "homeroom": student.homeroom,
                "has_iep": student.has_iep,
                "enl_level": student.enl_level,
                "enl_minutes_required": student.enl_minutes_required,
                "mtss_tier": student.mtss_tier,
                "status": "active",
                "services": services_by_student.get(student.id, []),
                "iep_services": services_by_student.get(student.id, []),
            }
            for student in students
        ]

    finally:
        db.close()


def get_staff(active_only: bool = False, school_id=None) -> List[Dict[str, Any]]:
    """Staff as scheduler-ready dicts. school_id should always be passed (see get_students)."""
    db = SessionLocal()

    try:
        query = db.query(StaffMember)
        if school_id is not None:
            query = query.filter(StaffMember.school_id == uuid.UUID(str(school_id)))
        staff_members = query.all()

        return [
            {
                "id": str(staff.id),
                "staff_id": staff.external_staff_id or str(staff.id),
                "first_name": staff.first_name,
                "last_name": staff.last_name,
                "title": staff.title,
                "grade": staff.grade,
                "homeroom": staff.homeroom or staff.room,  # use whichever is populated
                "room": staff.room or staff.homeroom,
                "is_certified_sped": staff.is_certified_sped,
                "is_certified_enl": staff.is_certified_enl,
                "is_certified_slp": staff.is_certified_slp,
                "can_deliver_setss": staff.can_deliver_setss,
                "max_students_per_group": staff.max_students_per_group,
                "status": "active",
            }
            for staff in staff_members
        ]

    finally:
        db.close()


def create_schedule_run(
    school_year: str = "2026-2027",
    name: str = "Generated Schedule",
    summary: Dict[str, Any] | None = None,
    school_id=None,
) -> str:
    """Create an empty draft ScheduleRun for the school and return its id."""
    db = SessionLocal()

    try:
        school = _resolve_school(db, school_id=school_id)

        run = ScheduleRun(
            id=uuid.uuid4(),
            school_id=school.id,
            school_year=school_year,
            name=name,
            status="draft",
            generated_by="scheduler-engine",
            summary_json=summary or {},
        )

        db.add(run)
        db.commit()
        db.refresh(run)

        return str(run.id)

    finally:
        db.close()


def _build_student_index(db, school_id=None) -> Dict[str, "Student"]:
    """Maps both external_student_id and str(UUID) to Student rows, so the
    scheduler's student ids (external id when there is one, else the UUID)
    resolve with one dict lookup instead of a query per row."""
    index: Dict[str, Student] = {}
    query = db.query(Student)
    if school_id is not None:
        query = query.filter(Student.school_id == school_id)
    for student in query.all():
        if student.external_student_id:
            index[student.external_student_id] = student
        index[str(student.id)] = student
    return index


def _build_staff_index(db, school_id=None) -> Dict[str, "StaffMember"]:
    """Maps 'First Last' to StaffMember. The scheduler identifies teachers by
    this display name, so this is how its output is linked back to staff rows."""
    index: Dict[str, StaffMember] = {}
    query = db.query(StaffMember)
    if school_id is not None:
        query = query.filter(StaffMember.school_id == school_id)
    for staff in query.all():
        full_name = f"{staff.first_name} {staff.last_name}".strip()
        index[full_name] = staff
    return index


def _optional_int(value):
    return int(value) if value is not None else None


def create_flex_group_students(
    flex_group_students: List[Dict[str, Any]],
    run_id: str,
) -> Dict[str, Any]:
    """
    Save the run's flex group memberships. Must run after create_flex_groups,
    since each row is matched to a saved group by (name, day, start minute).
    Rows whose student or group can't be found are skipped and logged.
    """
    if not flex_group_students:
        return {"saved_count": 0, "run_id": run_id}

    db = SessionLocal()
    try:
        run_uuid = uuid.UUID(run_id)
        school = _resolve_school(db, run_id=run_id)

        flex_groups_in_run = (
            db.query(FlexGroup)
            .filter(FlexGroup.run_id == run_uuid)
            .all()
        )
        # period is the block's start minute on both sides of this match
        flex_group_index = {
            (fg.name, fg.day_of_week, fg.period): fg.id
            for fg in flex_groups_in_run
        }

        student_index = _build_student_index(db, school.id)

        rows = []
        seen = set()  # guard against duplicates within this batch
        unmatched = 0

        for row in flex_group_students:
            student = student_index.get(str(row.get("student_id")))
            flex_group_id = flex_group_index.get((
                row.get("group_name"),
                row.get("day_of_week"),
                row.get("period"),
            ))
            if not student or not flex_group_id:
                unmatched += 1
                continue

            dedup_key = (flex_group_id, student.id)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            rows.append(FlexGroupStudent(
                id=uuid.uuid4(),
                flex_group_id=flex_group_id,
                student_id=student.id,
            ))

        if unmatched:
            logger.warning(
                "create_flex_group_students: %d row(s) in run %s matched no student "
                "or no saved FLEX group and were NOT saved", unmatched, run_id,
            )

        db.add_all(rows)
        db.commit()
        return {"saved_count": len(rows), "skipped_count": unmatched, "run_id": run_id}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_schedule_entries(
    entries: List[Dict[str, Any]],
    run_id: str | None = None,
    school_id=None,
) -> Any:
    """
    Save the scheduler's per-student entries for a run (creating a run if
    run_id is None). Entries whose student can't be matched are skipped and
    logged; an unknown teacher name is kept with staff_id left empty.
    """
    if not entries:
        return []

    db = SessionLocal()

    try:
        if run_id is None:
            run_id = create_schedule_run(
                school_year="2026-2027",
                name="Generated Schedule",
                summary={"schedule_entries_created": len(entries)},
                school_id=school_id,
            )

        school = _resolve_school(db, school_id=school_id, run_id=run_id)

        run_uuid = uuid.UUID(run_id)

        student_index = _build_student_index(db, school.id)
        staff_index = _build_staff_index(db, school.id)

        rows = []
        unmatched_students = set()

        for entry in entries:
            student = student_index.get(str(entry.get("student_id")))

            if not student:
                unmatched_students.add(str(entry.get("student_id")))
                continue

            teacher_name = entry.get("teacher") or ""
            staff = staff_index.get(teacher_name) if teacher_name else None

            rows.append(ScheduleEntry(
                id=uuid.uuid4(),
                school_id=school.id,
                run_id=run_uuid,

                student_id=student.id,
                staff_id=staff.id if staff else None,

                student_external_id=student.external_student_id,
                student_name=f"{student.first_name} {student.last_name}".strip(),
                grade=student.grade,

                teacher_name=teacher_name,

                day_of_week=entry.get("day_of_week"),
                period=int(entry.get("period")),           # == start_minute
                period_label=entry.get("period_label") or None,

                # master-schedule time model
                start_minute=_optional_int(entry.get("start_minute")),
                end_minute=_optional_int(entry.get("end_minute")),
                delivery=entry.get("delivery"),
                block_subject=entry.get("block_subject"),

                subject=entry.get("subject") or "General Education",
                room=entry.get("room") or "",

                service_type=entry.get("service_type"),
                is_pullout=bool(entry.get("is_pullout")),
                is_flex_period=bool(entry.get("is_flex_period")),

                status="draft",
                source="scheduler",
            ))

        if unmatched_students:
            logger.warning(
                "create_schedule_entries: %d student id(s) in run %s matched no Student "
                "row; their entries were NOT saved: %s",
                len(unmatched_students), run_id, sorted(unmatched_students)[:10],
            )

        db.add_all(rows)
        db.commit()

        return {
            "saved_count": len(rows),
            "skipped_count": len(entries) - len(rows),
            "run_id": run_id,
        }

    finally:
        db.close()


def create_staff_schedule_entries(
    entries: List[Dict[str, Any]],
    run_id: str,
) -> Dict[str, Any]:
    """Saves the scheduler's staff_schedule_entries (one row per teacher
    per class/session) for a run."""
    if not entries:
        return {"saved_count": 0, "run_id": run_id}

    db = SessionLocal()

    try:
        school = _resolve_school(db, run_id=run_id)
        run_uuid = uuid.UUID(run_id)
        staff_index = _build_staff_index(db, school.id)

        rows = []
        unmatched_staff = set()

        for entry in entries:
            teacher_name = entry.get("teacher") or ""
            staff = staff_index.get(teacher_name)

            if not staff:
                # Still saved, by name -- same as a ScheduleEntry whose
                # teacher matches no StaffMember row.
                unmatched_staff.add(teacher_name)

            rows.append(StaffScheduleEntry(
                id=uuid.uuid4(),
                school_id=school.id,
                run_id=run_uuid,

                staff_id=staff.id if staff else None,
                teacher_name=teacher_name,

                day_of_week=entry.get("day_of_week"),
                period=int(entry.get("period")),           # == start_minute
                period_label=entry.get("period_label") or None,
                start_minute=int(entry.get("start_minute")),
                end_minute=int(entry.get("end_minute")),

                subject=entry.get("subject") or "General Education",
                block_subject=entry.get("block_subject"),
                room=entry.get("room") or "",
                grade=entry.get("grade"),

                service_type=entry.get("service_type"),
                delivery=entry.get("delivery"),
                is_pullout=bool(entry.get("is_pullout")),
                is_flex_period=bool(entry.get("is_flex_period")),

                student_count=int(entry.get("student_count") or 0),
            ))

        if unmatched_staff:
            logger.warning(
                "create_staff_schedule_entries: %d teacher name(s) in run %s matched no "
                "StaffMember row; their rows were saved without a staff_id: %s",
                len(unmatched_staff), run_id, sorted(unmatched_staff)[:10],
            )

        db.add_all(rows)
        db.commit()

        return {"saved_count": len(rows), "run_id": run_id}

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_compliance_flags(
    flags: List[Dict[str, Any]],
    run_id: str | None = None,
    school_id=None,
) -> Any:
    """Save the compliance flags for a run (creating a run if run_id is None)."""
    if not flags:
        return []

    db = SessionLocal()

    try:
        if run_id is None:
            run_id = create_schedule_run(
                school_year="2026-2027",
                name="Generated Schedule Flags",
                summary={"compliance_flags_created": len(flags)},
                school_id=school_id,
            )

        school = _resolve_school(db, school_id=school_id, run_id=run_id)
        student_index = _build_student_index(db, school.id)

        run_uuid = uuid.UUID(run_id)

        rows = []

        for flag in flags:
            student = None
            if flag.get("student_id") and flag.get("student_id") != "multiple":
                student = student_index.get(str(flag.get("student_id")))

            rows.append(ComplianceFlag(
                id=uuid.uuid4(),
                school_id=school.id,
                run_id=run_uuid,

                student_id=student.id if student else None,
                student_external_id=flag.get("student_id"),

                flag_type=flag.get("flag_type") or "general",
                severity=flag.get("severity") or "warning",

                title=flag.get("title") or "Compliance Flag",
                description=flag.get("description"),
                legal_reference=flag.get("legal_reference"),
                affected_period=flag.get("affected_period"),

                status=flag.get("status") or "open",
            ))

        db.add_all(rows)
        db.commit()

        return {
            "saved_count": len(rows),
            "run_id": run_id,
        }

    finally:
        db.close()


def create_flex_groups(
    groups: List[Dict[str, Any]],
    run_id: str | None = None,
    school_id=None,
) -> Any:
    """Save the flex groups for a run (creating a run if run_id is None)."""
    if not groups:
        return []

    db = SessionLocal()

    try:
        if run_id is None:
            run_id = create_schedule_run(
                school_year="2026-2027",
                name="Generated Flex Groups",
                summary={"flex_groups_created": len(groups)},
                school_id=school_id,
            )

        school = _resolve_school(db, school_id=school_id, run_id=run_id)
        staff_index = _build_staff_index(db, school.id)

        run_uuid = uuid.UUID(run_id)

        saved = []

        for group in groups:
            teacher_name = group.get("teacher") or ""
            staff = staff_index.get(teacher_name) if teacher_name else None

            flex_group = FlexGroup(
                id=uuid.uuid4(),
                school_id=school.id,
                run_id=run_uuid,

                name=group.get("name") or "Flex Group",
                tier=group.get("tier"),
                focus_area=group.get("focus_area"),

                staff_id=staff.id if staff else None,
                teacher_name=teacher_name,

                day_of_week=group.get("day_of_week"),
                period=_optional_int(group.get("period")),   # == start_minute
                period_label=group.get("period_label") or None,
                start_minute=_optional_int(group.get("start_minute")),
                end_minute=_optional_int(group.get("end_minute")),

                max_group_size=int(group.get("max_group_size") or 10),
                status=group.get("status") or "active",
            )

            db.add(flex_group)
            saved.append(flex_group)

        db.commit()

        return {
            "saved_count": len(saved),
            "run_id": run_id,
        }

    finally:
        db.close()


def delete_entity_many(entity_name: str, query: dict, school_id=None):
    """
    Delete every row of entity_name ("ScheduleEntry", "ComplianceFlag",
    "FlexGroup" or "ScheduleRun") belonging to school_id. `query` is
    unused and kept for the existing call sites. school_id is required.
    """
    db = SessionLocal()

    try:
        model_map = {
            "ScheduleEntry": ScheduleEntry,
            "ComplianceFlag": ComplianceFlag,
            "FlexGroup": FlexGroup,
            "ScheduleRun": ScheduleRun,
        }

        model = model_map.get(entity_name)

        if not model:
            return {
                "deleted": 0,
                "message": f"No local delete mapping for {entity_name}",
            }

        if school_id is None:
            raise DBAPIError("delete_entity_many requires school_id")
        q = db.query(model).filter(model.school_id == uuid.UUID(str(school_id)))
        deleted = q.delete(synchronize_session=False)
        db.commit()

        return {
            "deleted": deleted,
            "entity": entity_name,
        }

    finally:
        db.close()