# database_service.py

import uuid
from typing import Any, Dict, List

from dmscheduler_db import (
    SessionLocal,
    School,
    Student,
    StaffMember,
    ScheduleRun,
    ScheduleEntry,
    ComplianceFlag,
    FlexGroup,
    FlexGroupStudent,
)


class DBConfigError(RuntimeError):
    pass


class DBAPIError(RuntimeError):
    pass


def get_default_school(db):
    school = db.query(School).first()

    if not school:
        school = School(
            id=uuid.uuid4(),
            name="Demo School",
            district_name="Demo District",
        )
        db.add(school)
        db.commit()
        db.refresh(school)

    return school



def get_students(
    active_only: bool = False,
    search: str | None = None,
    grade: int | None = None,
    iep: bool | None = None,
    mtss_tier: int | None = None
) -> List[Dict[str, Any]]:

    db = SessionLocal()

    try:

        query = db.query(Student)


        if search:
            query = query.filter(
                (Student.first_name.ilike(f"%{search}%")) |
                (Student.last_name.ilike(f"%{search}%"))
            )


        if grade:
            query = query.filter(
                Student.grade == grade
            )


        if iep is not None:
            query = query.filter(
                Student.has_iep == iep
            )


        if mtss_tier:
            query = query.filter(
                Student.mtss_tier == mtss_tier
            )


        students = query.all()


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
            }
            for student in students
        ]

    finally:
        db.close()

def get_staff(active_only: bool = False) -> List[Dict[str, Any]]:
    db = SessionLocal()

    try:
        staff_members = db.query(StaffMember).all()

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
) -> str:
    db = SessionLocal()

    try:
        school = get_default_school(db)

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


def _find_student_by_scheduler_id(db, student_id: str):
    student = db.query(Student).filter(
        Student.external_student_id == student_id
    ).first()

    if student:
        return student

    try:
        return db.query(Student).filter(
            Student.id == uuid.UUID(student_id)
        ).first()
    except Exception:
        return None


def _find_staff_by_name(db, teacher_name: str):
    if not teacher_name:
        return None

    staff_members = db.query(StaffMember).all()

    for staff in staff_members:
        full_name = f"{staff.first_name} {staff.last_name}".strip()
        if full_name == teacher_name:
            return staff

    return None

def create_flex_group_students(
    flex_group_students: List[Dict[str, Any]],
    run_id: str,
) -> Dict[str, Any]:
    if not flex_group_students:
        return {"saved_count": 0, "run_id": run_id}

    db = SessionLocal()
    try:
        run_uuid = uuid.UUID(run_id)

        # Build a lookup of (name, day_of_week, period) -> FlexGroup.id
        # for all flex groups that belong to this run.
        flex_groups_in_run = (
            db.query(FlexGroup)
            .filter(FlexGroup.run_id == run_uuid)
            .all()
        )
        flex_group_index = {
            (fg.name, fg.day_of_week, fg.period): fg.id
            for fg in flex_groups_in_run
        }

        saved = []
        seen = set()  # guard against duplicates within this batch

        for row in flex_group_students:
            student = _find_student_by_scheduler_id(
                db, str(row.get("student_id"))
            )
            if not student:
                continue

            flex_group_id = flex_group_index.get((
                row.get("group_name"),
                row.get("day_of_week"),
                row.get("period"),
            ))
            if not flex_group_id:
                continue  # no matching flex group saved for this run

            dedup_key = (flex_group_id, student.id)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            db.add(FlexGroupStudent(
                id=uuid.uuid4(),
                flex_group_id=flex_group_id,
                student_id=student.id,
            ))
            saved.append(dedup_key)

        db.commit()
        return {"saved_count": len(saved), "run_id": run_id}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def create_schedule_entries(
    entries: List[Dict[str, Any]],
    run_id: str | None = None,
) -> Any:
    if not entries:
        return []

    db = SessionLocal()

    try:
        school = get_default_school(db)

        if run_id is None:
            run_id = create_schedule_run(
                school_year="2026-2027",
                name="Generated Schedule",
                summary={"schedule_entries_created": len(entries)},
            )

        run_uuid = uuid.UUID(run_id)

        saved = []

        for entry in entries:
            student = _find_student_by_scheduler_id(
                db,
                str(entry.get("student_id")),
            )

            if not student:
                continue

            teacher_name = entry.get("teacher") or ""
            staff = _find_staff_by_name(db, teacher_name)

            schedule_entry = ScheduleEntry(
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
                period=int(entry.get("period")),

                subject=entry.get("subject") or "General Education",
                room=entry.get("room") or "",

                service_type=entry.get("service_type"),
                is_pullout=bool(entry.get("is_pullout")),
                is_flex_period=bool(entry.get("is_flex_period")),

                status="draft",
                source="scheduler",
            )

            db.add(schedule_entry)
            saved.append(schedule_entry)

        db.commit()

        return {
            "saved_count": len(saved),
            "run_id": run_id,
        }

    finally:
        db.close()


def create_compliance_flags(
    flags: List[Dict[str, Any]],
    run_id: str | None = None,
) -> Any:
    if not flags:
        return []

    db = SessionLocal()

    try:
        school = get_default_school(db)

        if run_id is None:
            run_id = create_schedule_run(
                school_year="2026-2027",
                name="Generated Schedule Flags",
                summary={"compliance_flags_created": len(flags)},
            )

        run_uuid = uuid.UUID(run_id)

        saved = []

        for flag in flags:
            student = None

            if flag.get("student_id") and flag.get("student_id") != "multiple":
                student = _find_student_by_scheduler_id(
                    db,
                    str(flag.get("student_id")),
                )

            compliance_flag = ComplianceFlag(
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
            )

            db.add(compliance_flag)
            saved.append(compliance_flag)

        db.commit()

        return {
            "saved_count": len(saved),
            "run_id": run_id,
        }

    finally:
        db.close()


def create_flex_groups(
    groups: List[Dict[str, Any]],
    run_id: str | None = None,
) -> Any:
    if not groups:
        return []

    db = SessionLocal()

    try:
        school = get_default_school(db)

        if run_id is None:
            run_id = create_schedule_run(
                school_year="2026-2027",
                name="Generated Flex Groups",
                summary={"flex_groups_created": len(groups)},
            )

        run_uuid = uuid.UUID(run_id)

        saved = []

        for group in groups:
            teacher_name = group.get("teacher") or ""
            staff = _find_staff_by_name(db, teacher_name)

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
                period=int(group.get("period")) if group.get("period") else None,

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


def get_schedule_entries() -> List[Dict[str, Any]]:
    db = SessionLocal()

    try:
        entries = db.query(ScheduleEntry).all()

        return [
            {
                "id": str(entry.id),
                "run_id": str(entry.run_id),
                "student_id": entry.student_external_id or str(entry.student_id),
                "student_name": entry.student_name,
                "grade": entry.grade,
                "day_of_week": entry.day_of_week,
                "period": entry.period,
                "subject": entry.subject,
                "teacher": entry.teacher_name,
                "room": entry.room,
                "service_type": entry.service_type,
                "is_pullout": entry.is_pullout,
                "is_flex_period": entry.is_flex_period,
                "status": entry.status,
            }
            for entry in entries
        ]

    finally:
        db.close()


def get_flex_groups(active_only: bool = True) -> List[Dict[str, Any]]:
    db = SessionLocal()

    try:
        query = db.query(FlexGroup)

        if active_only:
            query = query.filter(FlexGroup.status == "active")

        groups = query.all()

        return [
            {
                "id": str(group.id),
                "run_id": str(group.run_id),
                "name": group.name,
                "tier": group.tier,
                "focus_area": group.focus_area,
                "teacher": group.teacher_name,
                "day_of_week": group.day_of_week,
                "period": group.period,
                "max_group_size": group.max_group_size,
                "status": group.status,
            }
            for group in groups
        ]

    finally:
        db.close()


def create_schedule_proposal(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Kept only so old app.py imports do not break.
    Long term, replace ScheduleProposal with ScheduleRun.
    """
    run_id = create_schedule_run(
        school_year=payload.get("school_year", "2026-2027"),
        name=payload.get("student_name", "Generated Schedule"),
        summary=payload,
    )

    return {
        "id": run_id,
        "status": "draft",
        "message": "Stored as ScheduleRun instead of Base44 ScheduleProposal.",
    }


def delete_entity_many(entity_name: str, query: dict):
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

        deleted = db.query(model).delete()
        db.commit()

        return {
            "deleted": deleted,
            "entity": entity_name,
        }

    finally:
        db.close()