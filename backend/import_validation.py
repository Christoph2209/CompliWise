"""
import_validation.py

Checks student and staff CSVs row by row BEFORE anything is written, so
a school sees every problem in its file up front instead of discovering
half-imported data later. Nothing here touches the database except
read-only lookups to report which rows are new and which update an
existing record.

Severity levels:
  error   -- the row can't be imported safely (missing ID, bad JSON...).
             A file with any error is refused as a whole.
  warning -- the row will import, but someone should look at it
             (placeholder IEP minutes, unrecognized yes/no value...).

Column names are matched the same way import_csv_data.py reads them, so
a file that passes validation imports exactly as previewed.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from compliwise_db import StaffMember, Student
from import_csv_data import DEFAULT_SESSION_MINUTES, FREQ_PATTERN
from scheduling_core import canonical_service_type

# Same aliases import_csv_data.py accepts, first match wins.
STUDENT_ID_COLUMNS = ("student_id", "id", "external_student_id")
STAFF_ID_COLUMNS = ("staff_id", "worker_id", "id", "external_staff_id")
FIRST_NAME_COLUMNS = ("first_name", "First Name")
LAST_NAME_COLUMNS = ("last_name", "Last Name")

YES_NO_VALUES = {"yes", "y", "true", "1", "t", "no", "n", "false", "0", "f", ""}
VALID_GRADES = {"PK", "K", *(str(n) for n in range(0, 13))}
VALID_MTSS = {"", "1", "2", "3", "tier_1", "tier_2", "tier_3", "tier 1", "tier 2", "tier 3"}

MAX_ROWS = 20_000  # far beyond any single school; guards against huge uploads


@dataclass
class Issue:
    """One problem found in an uploaded file."""

    row: Optional[int]  # spreadsheet row number (header = row 1); None = whole file
    severity: str       # "error" | "warning"
    field: Optional[str]
    message: str

    def as_dict(self) -> dict:
        return {"row": self.row, "severity": self.severity, "field": self.field, "message": self.message}


@dataclass
class FileReport:
    """
    Validation result for one uploaded file ("students" or "staff"): row
    counts, how many rows are new vs. updates, and every Issue found.
    as_dict() is what the import preview endpoint returns to the UI.
    """

    file: str
    rows_read: int = 0
    new_records: int = 0
    updated_records: int = 0
    services_found: int = 0
    issues: list[Issue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def add(self, row, severity, field_name, message):
        self.issues.append(Issue(row, severity, field_name, message))

    def as_dict(self) -> dict:
        result = {
            "file": self.file,
            "rows_read": self.rows_read,
            "new_records": self.new_records,
            "updated_records": self.updated_records,
            "errors": self.error_count,
            "warnings": self.warning_count,
            "issues": [i.as_dict() for i in self.issues],
        }
        if self.file == "students":
            result["services_found"] = self.services_found
        return result


def _first(row: dict, columns: Iterable[str]) -> str:
    """The first non-blank value among `columns` (header aliases), stripped; "" if none."""
    for column in columns:
        value = row.get(column)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return ""


def _has_any_column(headers: list[str], columns: Iterable[str]) -> bool:
    return any(c in headers for c in columns)


def _read_rows(path: Path, report: FileReport) -> tuple[list[str], list[dict]]:
    """
    Read the CSV into (headers, rows) with header names stripped. Encoding,
    CSV-format and size problems are added to `report` as file-level errors
    and return empty rows.
    """
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            headers = [h.strip() for h in (reader.fieldnames or [])]
            rows = []
            for row in reader:
                rows.append({(k or "").strip(): v for k, v in row.items()})
                if len(rows) > MAX_ROWS:
                    report.add(None, "error", None, f"File has more than {MAX_ROWS:,} rows.")
                    return headers, []
            return headers, rows
    except UnicodeDecodeError:
        report.add(None, "error", None,
                   "File isn't UTF-8 text. In Excel, use Save As > 'CSV UTF-8 (Comma delimited)'.")
    except csv.Error as error:
        report.add(None, "error", None, f"Couldn't read the file as CSV: {error}")
    return [], []


def _check_required_headers(headers, report, id_columns, kind):
    """Record an error and return False unless the file has an ID, first-name and last-name column."""
    if not headers:
        if not report.issues:
            report.add(None, "error", None, "File is empty or has no header row.")
        return False
    missing = []
    if not _has_any_column(headers, id_columns):
        missing.append(f"an ID column ({' / '.join(id_columns)})")
    if not _has_any_column(headers, FIRST_NAME_COLUMNS):
        missing.append("first_name")
    if not _has_any_column(headers, LAST_NAME_COLUMNS):
        missing.append("last_name")
    if missing:
        report.add(None, "error", None,
                   f"The {kind} file is missing required column(s): {', '.join(missing)}.")
        return False
    return True


def _check_yes_no(row, row_num, report, columns, field_name):
    """Warn when a yes/no column holds something the importer will read as "no"."""
    raw = _first(row, columns)
    if raw.lower() not in YES_NO_VALUES:
        report.add(row_num, "warning", field_name,
                   f"'{raw}' isn't a recognized yes/no value; it will be treated as 'no'.")


def validate_students_csv(db, school_id, path: Path) -> FileReport:
    """
    Check a students CSV for this school. Errors: missing/duplicate IDs,
    missing names, bad ENL minutes, unreadable iep_services. Warnings:
    unrecognized grade, MTSS tier or yes/no values, and service entries
    that will import with assumed defaults.
    """
    report = FileReport(file="students")
    headers, rows = _read_rows(path, report)
    if not _check_required_headers(headers, report, STUDENT_ID_COLUMNS, "students"):
        return report

    existing_ids = {
        sid for (sid,) in db.query(Student.external_student_id)
        .filter(Student.school_id == school_id, Student.external_student_id.isnot(None))
    }
    seen: dict[str, int] = {}

    for index, row in enumerate(rows):
        row_num = index + 2
        if not any((v or "").strip() for v in row.values()):
            continue  # blank line
        report.rows_read += 1

        student_id = _first(row, STUDENT_ID_COLUMNS)
        if not student_id:
            report.add(row_num, "error", "student_id",
                       "Missing student ID. Every row needs one so re-imports update instead of duplicating.")
        elif student_id in seen:
            report.add(row_num, "error", "student_id",
                       f"Student ID {student_id} also appears on row {seen[student_id]}.")
        else:
            seen[student_id] = row_num
            if student_id in existing_ids:
                report.updated_records += 1
            else:
                report.new_records += 1

        if not _first(row, FIRST_NAME_COLUMNS):
            report.add(row_num, "error", "first_name", "Missing first name.")
        if not _first(row, LAST_NAME_COLUMNS):
            report.add(row_num, "error", "last_name", "Missing last name.")

        grade = _first(row, ("grade", "Grade"))
        if grade and grade.upper() not in VALID_GRADES:
            report.add(row_num, "warning", "grade", f"Unrecognized grade '{grade}'.")

        _check_yes_no(row, row_num, report, ("has_iep", "IEP"), "has_iep")

        mtss = _first(row, ("mtss_tier", "MTSS Tier"))
        if mtss.lower() not in VALID_MTSS:
            report.add(row_num, "warning", "mtss_tier", f"Unrecognized MTSS tier '{mtss}'.")

        enl_minutes = _first(row, ("enl_minutes_required", "ENL Minutes"))
        if enl_minutes:
            try:
                if float(enl_minutes) < 0:
                    raise ValueError
            except ValueError:
                report.add(row_num, "error", "enl_minutes_required",
                           f"ENL minutes must be a number of 0 or more (got '{enl_minutes}').")

        _validate_services(row, row_num, report)

    if report.rows_read == 0 and report.error_count == 0:
        report.add(None, "error", None, "The students file has a header but no student rows.")
    return report


def _validate_services(row, row_num, report):
    """Check the iep_services JSON column of one student row."""
    raw = (row.get("iep_services") or "").strip()
    if not raw or raw == "[]":
        return
    try:
        services = json.loads(raw)
    except json.JSONDecodeError:
        report.add(row_num, "error", "iep_services",
                   "iep_services isn't valid JSON, so this student's services can't be read.")
        return
    if not isinstance(services, list):
        report.add(row_num, "error", "iep_services", "iep_services must be a JSON list.")
        return

    has_iep = _first(row, ("has_iep", "IEP")).lower() in {"yes", "y", "true", "1", "t"}
    if services and not has_iep:
        report.add(row_num, "warning", "has_iep",
                   "Student has IEP services listed but has_iep is not 'yes'.")

    for position, svc in enumerate(services, start=1):
        if not isinstance(svc, dict) or not svc.get("service_type"):
            report.add(row_num, "error", "iep_services",
                       f"Service #{position} has no service_type.")
            continue
        report.services_found += 1
        # Same name mapping as the importer, so legacy "SETSS" isn't flagged.
        service_type = canonical_service_type(svc["service_type"])
        frequency = svc.get("frequency")
        if not frequency or not FREQ_PATTERN.search(str(frequency)):
            report.add(row_num, "warning", "iep_services",
                       f"{service_type}: frequency '{frequency or ''}' not understood "
                       "(expected like '2x/week'); 1 session/week will be assumed.")
        if service_type not in DEFAULT_SESSION_MINUTES:
            report.add(row_num, "warning", "iep_services",
                       f"{service_type}: unfamiliar service type; a 30-minute session length will be assumed.")


def validate_staff_csv(db, school_id, path: Path) -> FileReport:
    """
    Check a staff CSV for this school. Errors: missing/duplicate IDs and
    missing names. Warnings: unrecognized yes/no values in the certification
    columns and invalid group sizes.
    """
    report = FileReport(file="staff")
    headers, rows = _read_rows(path, report)
    if not _check_required_headers(headers, report, STAFF_ID_COLUMNS, "staff"):
        return report

    existing_ids = {
        sid for (sid,) in db.query(StaffMember.external_staff_id)
        .filter(StaffMember.school_id == school_id, StaffMember.external_staff_id.isnot(None))
    }
    seen: dict[str, int] = {}

    for index, row in enumerate(rows):
        row_num = index + 2
        if not any((v or "").strip() for v in row.values()):
            continue
        report.rows_read += 1

        staff_id = _first(row, STAFF_ID_COLUMNS)
        if not staff_id:
            report.add(row_num, "error", "staff_id", "Missing staff ID.")
        elif staff_id in seen:
            report.add(row_num, "error", "staff_id",
                       f"Staff ID {staff_id} also appears on row {seen[staff_id]}.")
        else:
            seen[staff_id] = row_num
            if staff_id in existing_ids:
                report.updated_records += 1
            else:
                report.new_records += 1

        if not _first(row, FIRST_NAME_COLUMNS):
            report.add(row_num, "error", "first_name", "Missing first name.")
        if not _first(row, LAST_NAME_COLUMNS):
            report.add(row_num, "error", "last_name", "Missing last name.")

        for columns, name in (
            (("is_certified_sped", "SPED Certified"), "is_certified_sped"),
            (("is_certified_enl", "ENL Certified"), "is_certified_enl"),
            (("is_certified_slp", "SLP Certified"), "is_certified_slp"),
            (("can_deliver_setss", "Can Deliver Resource Room", "Can Deliver SETSS"), "can_deliver_setss"),
        ):
            _check_yes_no(row, row_num, report, columns, name)

        group_size = _first(row, ("max_students_per_group", "Max Group Size"))
        if group_size:
            try:
                if int(float(group_size)) < 1:
                    raise ValueError
            except ValueError:
                report.add(row_num, "warning", "max_students_per_group",
                           f"'{group_size}' isn't a valid group size; 30 will be used.")

    if report.rows_read == 0 and report.error_count == 0:
        report.add(None, "error", None, "The staff file has a header but no staff rows.")
    return report


def summarize_errors(reports: list[FileReport], limit: int = 5) -> str:
    """One readable sentence for UIs that only show a string (the setup wizard)."""
    errors = [(r.file, i) for r in reports for i in r.issues if i.severity == "error"]
    if not errors:
        return ""
    parts = []
    for file_name, issue in errors[:limit]:
        where = f"{file_name} row {issue.row}" if issue.row else f"{file_name} file"
        parts.append(f"{where}: {issue.message}")
    more = f" (+{len(errors) - limit} more)" if len(errors) > limit else ""
    return f"Import refused, {len(errors)} problem(s) found. " + " | ".join(parts) + more
