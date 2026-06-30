# import_csv_data.py

import csv
import uuid
from pathlib import Path

from dmscheduler_db import (
    SessionLocal,
    School,
    Student,
    StaffMember,
    StudentService,
)


STUDENTS_CSV = "Student_export.csv"
STAFF_CSV = "StaffMember_export.csv"  # change to workers.csv if needed


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


def import_students(db, school):
    path = Path(STUDENTS_CSV)

    if not path.exists():
        print(f"Skipping students import. Missing file: {STUDENTS_CSV}")
        return

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


def import_staff(db, school):
    path = Path(STAFF_CSV)

    if not path.exists():
        print(f"Skipping staff import. Missing file: {STAFF_CSV}")
        return

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
            staff.grade = clean(row.get("grade") or row.get("Grade"))
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


def import_student_services(db, school):
    """
    Optional helper if your student CSV has simple service columns.

    Expected optional columns:
      service_type
      service_minutes
      service_sessions
      service_is_pullout

    For more complex IEP data, we should make a separate services.csv.
    """

    path = Path(STUDENTS_CSV)

    if not path.exists():
        return

    count = 0

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        for row in reader:
            external_student_id = clean(
                row.get("student_id")
                or row.get("id")
                or row.get("external_student_id")
            )

            service_type = clean(row.get("service_type"))
            minutes = to_int(row.get("service_minutes"), default=0)

            if not external_student_id or not service_type or minutes <= 0:
                continue

            student = db.query(Student).filter(
                Student.school_id == school.id,
                Student.external_student_id == external_student_id,
            ).first()

            if not student:
                continue

            existing = db.query(StudentService).filter(
                StudentService.school_id == school.id,
                StudentService.student_id == student.id,
                StudentService.service_type == service_type,
            ).first()

            if existing:
                service = existing
            else:
                service = StudentService(
                    id=uuid.uuid4(),
                    school_id=school.id,
                    student_id=student.id,
                    service_type=service_type,
                    minutes_per_week=minutes,
                )
                db.add(service)

            service.minutes_per_week = minutes
            service.sessions_per_week = to_int(
                row.get("service_sessions"),
                default=max(1, round(minutes / 30)),
            )
            service.is_pullout = yes_no(row.get("service_is_pullout") or "yes")

            count += 1

    db.commit()
    print(f"Imported/updated {count} student services.")


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