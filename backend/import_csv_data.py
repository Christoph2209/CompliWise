# import_csv_data.py

import csv
import json
import re
import uuid
from pathlib import Path
from typing import Optional, Union

from dmscheduler_db import (
    SessionLocal,
    School,
    Student,
    StaffMember,
    StudentService,
)


STUDENTS_CSV = "./data/Student_export.csv"
STAFF_CSV = "./data/StaffMember_export.csv"  # change to workers.csv if needed

PathLike = Union[str, Path]


DEFAULT_SESSION_MINUTES = {
    "OT": 30,
    "PT": 30,
    "Speech": 30,
    "Counseling": 30,
    "SETSS": 30,
    "Psych": 30,
}

FREQ_PATTERN = re.compile(r"(\d+)\s*x")


def yes_no(value):
    if value is None:
        return False

    return str(value).strip().lower() in {
        "yes", "y", "true", "1", "t"
    }


def clean(value, default=None):
    if value is None:
        return default

    value = str(value).strip()

    if value == "":
        return default

    return value


def to_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


_GRADE_NUMBER_RE = re.compile(r"grade\s*(\d+)", re.IGNORECASE)


def parse_grade_from_notes(notes) -> Optional[str]:
    """
    Some exports (e.g. the demo StaffMember CSV) have no dedicated grade
    column -- the grade lives inside a free-text `notes` field instead,
    mixed in with unrelated notes like "ICT support para" or "1:1 para
    for IEP student". This pulls a grade out ONLY when the text clearly
    encodes one, and returns None otherwise rather than guessing.

    "Kindergarten"       -> "K"
    "Grade 1"             -> "1"
    "Grade 3 ICT"         -> "3"   (the "ICT" co-teaching detail is not
                                     a grade and isn't captured here --
                                     there's no StaffMember field for it
                                     today; flagging separately)
    "ICT support para"    -> None
    "1:1 para for IEP student" -> None
    ""                    -> None
    """
    text = clean(notes)
    if not text:
        return None

    if "kindergarten" in text.lower():
        return "K"

    match = _GRADE_NUMBER_RE.search(text)
    if match:
        return match.group(1)

    return None


def get_or_create_school(db, name="Demo School"):
    school = db.query(School).filter(School.name == name).first()

    if school:
        return school

    school = School(
        id=uuid.uuid4(),
        name=name,
        district_name="Demo District",
        timezone="America/New_York",
    )

    db.add(school)
    db.commit()
    db.refresh(school)

    return school


def import_students(db, school, csv_path: Optional[PathLike] = None) -> int:
    """
    Import/update students from a CSV.

    csv_path defaults to the STUDENTS_CSV module constant (the original
    CLI behavior). The setup wizard passes an explicit path to an
    uploaded file instead.

    Returns the number of rows imported/updated.
    """
    path = Path(csv_path) if csv_path is not None else Path(STUDENTS_CSV)

    if not path.exists():
        print(f"Skipping students import. Missing file: {path}")
        return 0

    count = 0

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        for row in reader:
            external_student_id = clean(
                row.get("student_id")
                or row.get("id")
                or row.get("external_student_id")
            )

            first_name = clean(row.get("first_name") or row.get("First Name"), "")
            last_name = clean(row.get("last_name") or row.get("Last Name"), "")

            if not external_student_id and not first_name and not last_name:
                continue

            existing = None

            if external_student_id:
                existing = db.query(Student).filter(
                    Student.school_id == school.id,
                    Student.external_student_id == external_student_id,
                ).first()

            if existing:
                student = existing
            else:
                student = Student(
                    id=uuid.uuid4(),
                    school_id=school.id,
                    external_student_id=external_student_id,
                    first_name=first_name or "Unknown",
                    last_name=last_name or "Student",
                )

                db.add(student)

            student.first_name = first_name or student.first_name
            student.last_name = last_name or student.last_name
            student.grade = clean(row.get("grade") or row.get("Grade"))
            student.homeroom = clean(row.get("homeroom") or row.get("Homeroom"))

            student.has_iep = yes_no(row.get("has_iep") or row.get("IEP"))
            student.enl_level = clean(row.get("enl_level") or row.get("ENL Level"))
            student.enl_minutes_required = to_int(
                row.get("enl_minutes_required")
                or row.get("ENL Minutes")
                or 0
            )
            student.mtss_tier = clean(row.get("mtss_tier") or row.get("MTSS Tier"))

            count += 1

    db.commit()
    print(f"Imported/updated {count} students.")
    return count


def import_staff(db, school, csv_path: Optional[PathLike] = None) -> int:
    """
    Import/update staff from a CSV.

    csv_path defaults to the STAFF_CSV module constant (the original CLI
    behavior). The setup wizard passes an explicit path to an uploaded
    file instead.

    Returns the number of rows imported/updated.
    """
    path = Path(csv_path) if csv_path is not None else Path(STAFF_CSV)

    if not path.exists():
        print(f"Skipping staff import. Missing file: {path}")
        return 0

    count = 0

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        for row in reader:
            external_staff_id = clean(
                row.get("staff_id")
                or row.get("worker_id")
                or row.get("id")
                or row.get("external_staff_id")
            )

            first_name = clean(row.get("first_name") or row.get("First Name"), "")
            last_name = clean(row.get("last_name") or row.get("Last Name"), "")

            if not external_staff_id and not first_name and not last_name:
                continue

            existing = None

            if external_staff_id:
                existing = db.query(StaffMember).filter(
                    StaffMember.school_id == school.id,
                    StaffMember.external_staff_id == external_staff_id,
                ).first()

            if existing:
                staff = existing
            else:
                staff = StaffMember(
                    id=uuid.uuid4(),
                    school_id=school.id,
                    external_staff_id=external_staff_id,
                    first_name=first_name or "Unknown",
                    last_name=last_name or "Staff",
                )

                db.add(staff)

            staff.first_name = first_name or staff.first_name
            staff.last_name = last_name or staff.last_name

            staff.title = clean(row.get("title") or row.get("Title"))
            staff.grade = (
                clean(row.get("grade") or row.get("Grade"))
                or parse_grade_from_notes(row.get("notes") or row.get("Notes"))
            )
            staff.homeroom = clean(row.get("homeroom") or row.get("Homeroom"))
            staff.room = clean(row.get("room") or row.get("Room"))

            staff.is_certified_sped = yes_no(
                row.get("is_certified_sped")
                or row.get("SPED Certified")
            )
            staff.is_certified_enl = yes_no(
                row.get("is_certified_enl")
                or row.get("ENL Certified")
            )
            staff.is_certified_slp = yes_no(
                row.get("is_certified_slp")
                or row.get("SLP Certified")
            )
            staff.can_deliver_setss = yes_no(
                row.get("can_deliver_setss")
                or row.get("Can Deliver SETSS")
            )

            staff.max_students_per_group = to_int(
                row.get("max_students_per_group")
                or row.get("Max Group Size")
                or 30,
                default=30,
            )

            count += 1

    db.commit()
    print(f"Imported/updated {count} staff members.")
    return count


def _parse_sessions_per_week(frequency: str | None) -> int | None:
    if not frequency:
        return None
    match = FREQ_PATTERN.search(frequency)
    return int(match.group(1)) if match else None


def import_student_services(db, school, csv_path):
    """
    Parses the `iep_services` JSON column from the student export CSV
    and creates one StudentService row per service entry.

    IMPORTANT: the source data has no minutes_per_week, only a
    frequency string ("2x/week"). This import fills minutes_per_week
    with a placeholder default and flags every row as unverified --
    these numbers must be reviewed against actual IEP paperwork before
    they're trusted for compliance checks.
    """
    created = 0
    skipped_no_student = 0
    skipped_bad_json = 0

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            external_id = row.get("student_id")
            if not external_id:
                continue

            student = (
                db.query(Student)
                .filter(
                    Student.school_id == school.id,
                    Student.external_student_id == external_id,
                )
                .first()
            )
            if not student:
                skipped_no_student += 1
                continue

            raw_services = row.get("iep_services") or "[]"
            try:
                services = json.loads(raw_services)
            except json.JSONDecodeError:
                skipped_bad_json += 1
                continue

            for svc in services:
                service_type = svc.get("service_type")
                if not service_type:
                    continue

                frequency = svc.get("frequency")
                sessions_per_week = _parse_sessions_per_week(frequency)
                group_size = svc.get("group_size")
                provider = svc.get("provider")

                minutes_per_session = DEFAULT_SESSION_MINUTES.get(service_type, 30)
                minutes_per_week = (
                    minutes_per_session * sessions_per_week
                    if sessions_per_week
                    else minutes_per_session
                )

                note_parts = [
                    "⚠️ NEEDS VERIFICATION — minutes are a placeholder default, "
                    "confirm against actual IEP documentation."
                ]
                if provider:
                    note_parts.append(f"Provider on file: {provider}")
                if group_size:
                    note_parts.append(f"Group size: {group_size}")

                db.add(StudentService(
                    school_id=school.id,
                    student_id=student.id,
                    service_type=service_type,
                    subject_area=None,
                    minutes_per_week=minutes_per_week,
                    sessions_per_week=sessions_per_week,
                    is_pullout=True,
                    preferred_provider_id=None,
                    notes=" | ".join(note_parts),
                ))
                created += 1

    db.commit()
    return {
        "services_created": created,
        "students_not_found": skipped_no_student,
        "rows_with_bad_json": skipped_bad_json,
    }


def main():
    db = SessionLocal()

    try:
        school = get_or_create_school(db, name="Demo School")

        import_students(db, school)
        import_staff(db, school)
        import_student_services(db, school)

        print("CSV import complete.")

    finally:
        db.close()


if __name__ == "__main__":
    main()