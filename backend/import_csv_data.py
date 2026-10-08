"""
import_csv_data.py

Loads students, staff and IEP services from CSV exports or Excel
workbooks into the database.

Two callers use this module:
  * The setup wizard (setup.py / main.py) calls import_students,
    import_staff and import_student_services with the path of an uploaded
    file, after import_validation.py has checked it.
  * Running it directly from the repo root:
        python backend/import_csv_data.py
            imports the demo CSVs in data/ into a "Demo School".
        python backend/import_csv_data.py path/to/file.xlsx
            imports that one file (.csv or .xlsx). Whether it holds
            students or staff is read from its columns; --kind and
            --school override the defaults.

Imports are upserts keyed on the external ID column (student_id /
staff_id), so re-running the same file updates rows instead of
duplicating them. Column names are matched loosely: both the snake_case
export headers and friendlier spreadsheet headers ("First Name") work.
A students file may also be a compliance roster, with a column per
subject placement and per related service (see roster_file.py).
"""

import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Optional, Union

from compliwise_db import (
    SessionLocal,
    School,
    Student,
    StaffMember,
    StudentService,
)
from roster_file import ENL_WEEKLY_MINUTES, read_table, roster_enl_level, roster_services
from scheduling_core import canonical_service_type, service_is_pullout


# Default files for the command-line import. Relative paths, so run the
# script from the repo root.
STUDENTS_CSV = "./data/Student_export_base.csv"
STAFF_CSV = "./data/StaffMember_base.csv"
DEMO_SCHOOL_NAME = "Demo School"

# Columns that tell a students file from a staff file when one file is
# imported from the command line. Both kinds of export have a bare "id".
STUDENT_ONLY_COLUMNS = {"student_id", "student id", "external_student_id"}
STAFF_ONLY_COLUMNS = {"staff_id", "staff id", "worker_id", "external_staff_id", "title"}

PathLike = Union[str, Path]


# The CSV only gives a frequency ("2x/week"), not minutes, so each service
# gets this placeholder length per session until staff verify the IEP.
DEFAULT_SESSION_MINUTES = {
    "OT": 30,
    "PT": 30,
    "Speech": 30,
    "Counseling": 30,
    "Resource Room": 30,
    "Psych": 30,
}

# Pulls the session count out of frequency strings like "2x/week".
FREQ_PATTERN = re.compile(r"(\d+)\s*x")
# "daily" means once every school day.
DAILY_SESSIONS_PER_WEEK = 5


def yes_no(value):
    """Read a CSV yes/no cell as a bool. Blank or unrecognized means False."""
    if value is None:
        return False

    return str(value).strip().lower() in {
        "yes", "y", "true", "1", "t"
    }


def clean(value, default=None):
    """Strip a CSV cell; return `default` when it is missing or blank."""
    if value is None:
        return default

    value = str(value).strip()

    if value == "":
        return default

    return value


def to_int(value, default=0):
    """Parse a CSV cell as an int (accepts "30" or "30.0"), else `default`."""
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
    """Return the school with this name, creating it if needed (CLI import only)."""
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
    Import/update students from a CSV or Excel file.

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

    for _, row in read_table(path)[1]:
        # Prefer the school's own student number; fall back to the
        # export's row id so the upsert still has a stable key.
        external_student_id = clean(
            row.get("student_id")
            or row.get("Student ID")
            or row.get("id")
            or row.get("external_student_id")
        )

        first_name = clean(row.get("first_name") or row.get("First Name"), "")
        last_name = clean(row.get("last_name") or row.get("Last Name"), "")

        # Skip fully blank rows (e.g. trailing lines from Excel).
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

        # A compliance roster has no homeroom or MTSS column. Leave
        # what's on file alone rather than blanking it on re-import.
        if "homeroom" in row or "Homeroom" in row:
            student.homeroom = clean(row.get("homeroom") or row.get("Homeroom"))
        if "mtss_tier" in row or "MTSS Tier" in row:
            student.mtss_tier = clean(row.get("mtss_tier") or row.get("MTSS Tier"))

        # A roster has no IEP column either: any special class placement
        # or related service on the row means the student has an IEP.
        student.has_iep = (
            yes_no(row.get("has_iep") or row.get("IEP"))
            or bool(roster_services(row)[0])
        )

        roster_level = roster_enl_level(row)
        student.enl_level = (
            clean(row.get("enl_level") or row.get("ENL Level")) or roster_level
        )
        enl_minutes = clean(row.get("enl_minutes_required") or row.get("ENL Minutes"))
        if enl_minutes is None and roster_level:
            # The roster gives only the level; use that level's mandated minutes.
            student.enl_minutes_required = ENL_WEEKLY_MINUTES.get(roster_level, 0)
        else:
            student.enl_minutes_required = to_int(enl_minutes or 0)

        count += 1

    db.commit()
    print(f"Imported/updated {count} students.")
    return count


def import_staff(db, school, csv_path: Optional[PathLike] = None) -> int:
    """
    Import/update staff from a CSV or Excel file.

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

    for _, row in read_table(path)[1]:
        external_staff_id = clean(
            row.get("staff_id")
            or row.get("Staff ID")
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
            or row.get("Can Deliver Resource Room")
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
    """"2x/week" -> 2, "daily" -> 5. None when the frequency is missing
    or unparseable."""
    if not frequency:
        return None
    match = FREQ_PATTERN.search(str(frequency))
    if match:
        return int(match.group(1))
    if "daily" in str(frequency).lower():
        return DAILY_SESSIONS_PER_WEEK
    return None


def import_student_services(db, school, csv_path):
    """
    Creates one StudentService row per service a students file lists,
    either in the `iep_services` JSON column of a CSV export or in the
    per-service columns of a compliance roster.

    IMPORTANT: a CSV export has no minutes_per_week, only a frequency
    string ("2x/week"). Those services get a placeholder default and a
    NEEDS VERIFICATION note -- the numbers must be reviewed against
    actual IEP paperwork before they're trusted for compliance checks.
    A roster cell like "2X30" states the minutes, so it isn't flagged.

    Students must already exist (run import_students first); rows whose
    student_id isn't found are counted and skipped. Returns a dict of
    counts for the setup wizard to display.
    """
    created = 0
    already_present = 0
    skipped_no_student = 0
    skipped_bad_json = 0

    for _, row in read_table(csv_path)[1]:
        external_id = clean(row.get("student_id") or row.get("Student ID"))
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
        if not isinstance(services, list):
            services = []
        # A compliance roster lists services in their own columns instead.
        services = services + roster_services(row)[0]

        # Re-importing the same file must not duplicate services.
        # A service type the student already has is left alone: its
        # minutes may have been verified/edited by staff since, and
        # the CSV only carries placeholder minutes. Class placements
        # are one row per subject, so those are matched on both.
        on_file = (
            db.query(StudentService.service_type, StudentService.subject_area)
            .filter(StudentService.student_id == student.id)
            .all()
        )
        existing_types = {service_type for (service_type, _) in on_file}
        existing_placements = {tuple(pair) for pair in on_file}

        for svc in services:
            service_type = (
                canonical_service_type(svc.get("service_type"))
                if isinstance(svc, dict)
                else None
            )
            if not service_type:
                continue
            subject_area = clean(svc.get("subject_area"))
            if subject_area:
                duplicate = (service_type, subject_area) in existing_placements
            else:
                duplicate = service_type in existing_types
            if duplicate:
                already_present += 1
                continue
            existing_types.add(service_type)
            existing_placements.add((service_type, subject_area))

            frequency = svc.get("frequency")
            sessions_per_week = (
                to_int(svc.get("sessions_per_week"), 0)
                or _parse_sessions_per_week(frequency)
            )
            group_size = svc.get("group_size")
            provider = svc.get("provider")

            # A roster states the session length ("2X30"); a CSV export
            # doesn't, so those get a placeholder to be verified.
            stated_minutes = to_int(svc.get("minutes_per_session"), 0)
            minutes_per_session = stated_minutes or DEFAULT_SESSION_MINUTES.get(service_type, 30)
            minutes_per_week = (
                minutes_per_session * sessions_per_week
                if sessions_per_week
                else minutes_per_session
            )

            note_parts = []
            if not stated_minutes:
                note_parts.append(
                    "⚠️ NEEDS VERIFICATION — minutes are a placeholder default, "
                    "confirm against actual IEP documentation."
                )
            if svc.get("note"):
                note_parts.append(str(svc["note"]))
            if provider:
                note_parts.append(f"Provider on file: {provider}")
            if group_size:
                note_parts.append(f"Group size: {group_size}")

            db.add(StudentService(
                school_id=school.id,
                student_id=student.id,
                service_type=service_type,
                subject_area=subject_area,
                minutes_per_week=minutes_per_week,
                sessions_per_week=sessions_per_week,
                is_pullout=service_is_pullout(service_type, svc.get("is_pullout", True)),
                preferred_provider_id=None,
                notes=" | ".join(note_parts) or None,
            ))
            created += 1

    db.commit()
    return {
        "services_created": created,
        "services_already_present": already_present,
        "students_not_found": skipped_no_student,
        "rows_with_bad_json": skipped_bad_json,
    }


def detect_file_kind(path: PathLike) -> Optional[str]:
    """"students" or "staff", judged from the file's column names; None
    when they don't settle it."""
    headers = {h.lower() for h in read_table(path)[0]}
    is_students = bool(headers & STUDENT_ONLY_COLUMNS)
    is_staff = bool(headers & STAFF_ONLY_COLUMNS)
    if is_students == is_staff:
        return None
    return "students" if is_students else "staff"


def import_file(db, school, path: PathLike, kind: Optional[str] = None) -> dict:
    """
    Import one students or staff file (.csv or .xlsx) into `school`.

    The file is checked with import_validation first, exactly as the
    app's import page does, and nothing is written if it has errors.
    `kind` is "students" or "staff"; None reads it from the columns.

    Returns {"kind", "report", "imported", "services"}: `report` is the
    validation FileReport, `imported` is None when the file was refused,
    and `services` is import_student_services' counts (students only).
    """
    # Imported here because import_validation imports this module.
    from import_validation import validate_staff_csv, validate_students_csv

    path = Path(path)
    kind = kind or detect_file_kind(path)
    if kind not in ("students", "staff"):
        raise ValueError(
            f"Can't tell whether {path.name} holds students or staff. "
            "Say which with --kind students or --kind staff."
        )

    validate = validate_students_csv if kind == "students" else validate_staff_csv
    report = validate(db, school.id, path)
    result = {"kind": kind, "report": report, "imported": None, "services": None}
    if report.error_count:
        return result

    if kind == "students":
        result["imported"] = import_students(db, school, csv_path=path)
        result["services"] = import_student_services(db, school, csv_path=path)
    else:
        result["imported"] = import_staff(db, school, csv_path=path)
    return result


def _import_single_file(db, args) -> int:
    """The command line's one-file import. Returns the process exit code."""
    path = Path(args.file)
    if not path.is_file():
        print(f"File not found: {path}")
        return 1

    if args.school:
        school = db.query(School).filter(School.name == args.school).first()
        if not school:
            names = ", ".join(sorted(name for (name,) in db.query(School.name))) or "none yet"
            print(f"No school named '{args.school}'. Schools on file: {names}.")
            return 1
    else:
        school = get_or_create_school(db, name=DEMO_SCHOOL_NAME)

    try:
        result = import_file(db, school, path, kind=args.kind)
    except ValueError as error:
        print(error)
        return 1

    report = result["report"]
    for issue in report.issues:
        where = f"row {issue.row}" if issue.row else "file"
        print(f"  {issue.severity.upper()} ({where}): {issue.message}")
    if report.error_count:
        print(f"Import refused: {report.error_count} error(s) in {path.name}. Nothing was imported.")
        return 1

    services = result["services"]
    if services:
        print(f"Created {services['services_created']} services "
              f"({services['services_already_present']} already on file).")
    print(f"Imported {path.name} into {school.name} with {report.warning_count} warning(s).")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """
    Command-line entry point. With no arguments, imports the demo CSVs
    into "Demo School"; with a file, imports just that .csv or .xlsx.
    """
    parser = argparse.ArgumentParser(
        description="Import students or staff from a CSV or Excel (.xlsx) file."
    )
    parser.add_argument(
        "file", nargs="?",
        help="a single .csv or .xlsx file to import (omit to import the demo CSVs in data/)",
    )
    parser.add_argument(
        "--kind", choices=("students", "staff"),
        help="what the file holds (default: worked out from its columns)",
    )
    parser.add_argument(
        "--school",
        help=f"name of an existing school to import into (default: \"{DEMO_SCHOOL_NAME}\", created if missing)",
    )
    args = parser.parse_args(argv)

    db = SessionLocal()

    try:
        if args.file:
            return _import_single_file(db, args)

        school = get_or_create_school(db, name=DEMO_SCHOOL_NAME)

        import_students(db, school)
        import_staff(db, school)
        import_student_services(db, school, csv_path=STUDENTS_CSV)

        print("CSV import complete.")
        return 0

    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
