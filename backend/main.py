"""
main.py

CompliWise Scheduler Engine API (FastAPI). Run with `uvicorn main:app`.

Login is a server-side session cookie (POST /login). Every endpoint
declares which roles may call it (see the role groups below) and filters
every query by the caller's school, so schools never see each other's data.

Sections, in order: app setup, auth, first-run setup, CSV import, users,
students, student services, staff, schedules, schedule runs and
generation, compliance flags, flex groups, audit log.

Environment:
  DATABASE_URL    Postgres connection string (required)
  SESSION_SECRET  signs the session cookie (required)
  CORS_ORIGINS    comma-separated frontend origins (default http://localhost:5173)
  COOKIE_SECURE   "true" to send the cookie over HTTPS only
  SCHOOL_YEAR     label stored on schedule runs (default 2026-2027)
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import String, and_, cast, exists, func, or_
from sqlalchemy.orm import Session, aliased
from starlette.middleware.sessions import SessionMiddleware

import setup as setup_module
from auth_utils import hash_password, verify_password
from compliance import run_all_compliance_checks
from database_service import (
    DBAPIError,
    create_compliance_flags,
    create_flex_group_students,
    create_flex_groups,
    create_schedule_entries,
    create_schedule_run,
    create_staff_schedule_entries,
    delete_entity_many,
    get_staff,
    get_students,
)
from dmscheduler_db import (
    ComplianceFlag,
    FlexGroup,
    FlexGroupStudent,
    ScheduleEntry,
    StaffScheduleEntry,
    SessionLocal,
    School,
    StaffMember,
    ScheduleRun,
    Student,
    StudentService,
    User,
    AuditLog,
)
from import_csv_data import import_student_services, import_students, import_staff
from import_validation import validate_staff_csv, validate_students_csv, summarize_errors
from scheduler import schedule_iep_services_first, suggest_service_slots
from scheduling_core import PeriodConfig, day_index, format_range

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

load_dotenv()

app = FastAPI(title="CompliWise Scheduler Engine")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SESSION_SECRET"],
    session_cookie="compliwise_session",
    max_age=60 * 60 * 8,  # 8 hours, roughly a school day
    same_site="lax",
    https_only=os.getenv("COOKIE_SECURE", "false").lower() == "true",
)

# Schedule responses are megabytes of repetitive JSON; gzip cuts them ~15x.
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Shared dependencies / helpers
# ---------------------------------------------------------------------------

def get_db():
    """FastAPI dependency: one database session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The logged-in, active user from the session cookie, else 401."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")

    try:
        user_uuid = UUID(user_id)
    except ValueError:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Session no longer valid")

    user = db.query(User).filter(User.id == user_uuid).first()
    if not user or not user.is_active:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Session no longer valid")

    return user


# Role groups. Every endpoint below declares which roles may call it.
ADMIN = ("admin",)
MANAGERS = ("admin", "principal")          # build/edit schedules, student & staff records
ALL_STAFF = ("admin", "principal", "teacher", "aide")
VALID_ROLES = set(ALL_STAFF)


def require_roles(*roles: str):
    """
    Dependency factory: `user: User = Depends(require_roles(*MANAGERS))`
    logs the caller in (401 if not) and checks their role (403 if not
    allowed). Every query must ALSO filter by user.school_id -- the role
    check alone doesn't stop one school reading another's data.
    """
    allowed = set(roles)

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="Not allowed")
        return user

    return dependency


def _client_ip(request: Request) -> str | None:
    """Caller's IP address, for the audit log."""
    return request.client.host if request.client else None


def _parse_uuid(value: str, what: str = "Record") -> UUID:
    """Malformed ids are a 404, not a 500 from Postgres."""
    try:
        return UUID(str(value))
    except ValueError:
        raise HTTPException(status_code=404, detail=f"{what} not found")


# ---------------------------------------------------------------------------
# Pydantic models (request bodies)
# ---------------------------------------------------------------------------
class StaffUpdate(BaseModel):
    grade: str | None = None
    is_certified_sped: bool | None = None
    is_certified_enl: bool | None = None
    is_certified_slp: bool | None = None
    can_deliver_setss: bool | None = None

ALLOWED_STAFF_FIELDS = {
    "grade", "is_certified_sped", "is_certified_enl",
    "is_certified_slp", "can_deliver_setss"
}


class LoginRequest(BaseModel):
    email: str
    password: str

class SetupInitializeRequest(BaseModel):
    school_name: str
    district_name: str | None = None
    admin_email: EmailStr
    admin_password: str
    admin_full_name: str | None = None

class StudentUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    grade: str | None = None
    homeroom: str | None = None
    has_iep: bool | None = None
    mtss_tier: str | None = None

ALLOWED_STUDENT_FIELDS = {
    "first_name", "last_name", "grade", "homeroom", "has_iep", "mtss_tier",
}

class StaffCreate(BaseModel):
    # Ignored if sent: staff are always created in the caller's school.
    school_id: str | None = None
    first_name: str
    last_name: str
    external_staff_id: str | None = None
    title: str | None = None
    grade: str | None = None
    homeroom: str | None = None
    room: str | None = None
    is_certified_sped: bool
    is_certified_enl: bool
    is_certified_slp: bool
    can_deliver_setss: bool
    max_students_per_group: int


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    role: str  # "admin" | "principal" | "teacher" | "aide"
    staff_id: str | None = None  # optional — not every user needs a staff record

class ScheduleGenerationConfig(BaseModel):
    """Shape read by PeriodConfig.from_config() -- see scheduling_core.py."""
    grade_schedules: list[dict[str, Any]]                  # the master schedule, per grade
    block_policies: list[dict[str, Any]] = []              # optional overrides of the default rules
    pullout_constraints: dict[str, Any]
    specials_requirements: list[dict[str, Any]]

# Fields a manual edit may change on a schedule entry. Anything else
# (run_id, student_id, school_id, ...) is rejected rather than written.
ALLOWED_SCHEDULE_ENTRY_FIELDS = {
    "staff_id", "subject", "room", "day_of_week", "period_label",
    "start_minute", "end_minute", "service_type", "delivery",
    "block_subject", "is_flex_period", "status",
}
VALID_DELIVERIES = {"pullout", "push_in", "class"}

# Name given to runs that hold a whole-school schedule (vs. compliance-only runs).
FULL_SCHEDULE_RUN_NAME = "Full School Schedule"

# ScheduleRun.status values. A published run's entries can't be edited;
# only Reset (which wipes every run) removes it.
DRAFT = "draft"
PUBLISHED = "published"

# Background generation jobs by job id, kept in memory: status is lost on
# restart, and with several server processes a status poll may miss its job.
SCHEDULE_JOBS: dict[str, dict] = {}

# Index = the stage number scheduler.py passes to progress_callback.
SCHEDULE_STAGES = [
    "Placing mandated IEP/ENL/related services",
    "Assigning Specials teachers (PE/Music/Art)",
    "Building FLEX groups",
    "Filling homeroom blocks from the master schedule",
    "Running compliance validation",
    "Building schedule proposals",
    "Saving schedule to database",
]

# ---------------------------------------------------------------------------
# Root / meta
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    """Health check. Full endpoint list: /docs."""
    return {
        "message": "CompliWise Scheduler Engine is running",
        "endpoints": [
            "/students",
            "/staff",
            "/schedule",
            "/schedule/generate/start",
            "/save-schedule",
            "/compliance-flags",
            "/flex_groups",
        ],
    }


def _jsonable(data: dict) -> dict:
    """Coerces UUID/datetime values so a dict can be stored in a JSONB column."""
    result = {}
    for key, value in data.items():
        if isinstance(value, uuid.UUID):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


def _entry_time_fields(entry) -> dict:
    """Time/delivery fields shared by every endpoint that returns
    schedule entries. Rows saved before the master-schedule migration
    have no end_minute, so time_range is None for them."""
    has_times = entry.start_minute is not None and entry.end_minute is not None
    return {
        "start_minute": entry.start_minute,
        "end_minute": entry.end_minute,
        "time_range": format_range(entry.start_minute, entry.end_minute) if has_times else None,
        "delivery": entry.delivery,
        "block_subject": entry.block_subject,
        "room": entry.room,
    }


def _latest_full_run(db: Session, school_id) -> ScheduleRun | None:
    """The school's most recent whole-school schedule run, or None."""
    return (
        db.query(ScheduleRun)
        .filter(ScheduleRun.school_id == school_id)
        .filter(ScheduleRun.name == FULL_SCHEDULE_RUN_NAME)
        .order_by(ScheduleRun.created_at.desc())
        .first()
    )


def _current_run(db: Session, school_id) -> ScheduleRun | None:
    """The schedule staff should be working from: the most recently
    published full run, or the latest full run if none is published yet."""
    published = (
        db.query(ScheduleRun)
        .filter(ScheduleRun.school_id == school_id)
        .filter(ScheduleRun.name == FULL_SCHEDULE_RUN_NAME)
        .filter(ScheduleRun.status == PUBLISHED)
        .order_by(ScheduleRun.published_at.desc())
        .first()
    )
    return published or _latest_full_run(db, school_id)


def _run_period_config(run: ScheduleRun) -> PeriodConfig:
    """The master schedule a run was BUILT with. Checking a run against
    today's defaults instead would silently judge it by the wrong bell
    schedule, so a run without one is an error, not a fallback."""
    payload = (run.summary_json or {}).get("period_config")
    if not payload:
        raise HTTPException(
            status_code=409,
            detail=(
                "This schedule run was generated before master schedules were "
                "saved with runs. Regenerate the schedule first."
            ),
        )
    try:
        return PeriodConfig.from_config(payload)
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail=f"This run's saved master schedule is no longer valid: {error}",
        )


def _run_entries_as_dicts(db: Session, run_id) -> list[dict]:
    """A run's saved entries in the shape compliance.py / scheduler.py
    read. student_id is the DB UUID (str), matching students keyed by
    their "id"."""
    return [
        {
            "student_id": str(e.student_id),
            "day_of_week": e.day_of_week,
            "period": e.period,
            "start_minute": e.start_minute,
            "end_minute": e.end_minute,
            "subject": e.subject,
            "block_subject": e.block_subject,
            "teacher": e.teacher_name,
            "room": e.room,
            "service_type": e.service_type,
            "delivery": e.delivery,
            "is_pullout": e.is_pullout,
            "is_flex_period": e.is_flex_period,
            "grade": e.grade,
        }
        for e in db.query(ScheduleEntry).filter(ScheduleEntry.run_id == run_id).all()
    ]


def write_audit_log(
    db: Session,
    *,
    action: str,
    school_id=None,
    user_id=None,
    entity_type: str | None = None,
    entity_id=None,
    before: dict | None = None,
    after: dict | None = None,
    ip_address: str | None = None,
):
    """Writes one audit row. Deliberately never raises -- a broken audit
    write should never block the underlying action or roll back its commit."""
    try:
        db.add(AuditLog(
            school_id=school_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_json=before,
            after_json=after,
            ip_address=ip_address,
        ))
        db.commit()
    except Exception:
        db.rollback()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.post("/login")
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Check email/password and start a session. Every attempt is audit-logged."""
    user = db.query(User).filter(User.email == data.email).first()

    if not user or not verify_password(data.password, user.password_hash):
        write_audit_log(
            db,
            action="Login Failed",
            school_id=user.school_id if user else None,
            user_id=user.id if user else None,
            ip_address=request.client.host if request.client else None,
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    request.session.clear()
    request.session["user_id"] = str(user.id)

    write_audit_log(
        db,
        action="Login Success",
        school_id=user.school_id,
        user_id=user.id,
        ip_address=request.client.host if request.client else None,
    )

    return {
        "user_id": str(user.id),
        "role": user.role,
        "staff_id": str(user.staff_id) if user.staff_id else None,
    }


@app.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    """End the session."""
    user_id = request.session.get("user_id")
    request.session.clear()
    if user_id:
        write_audit_log(
            db,
            action="Logout",
            user_id=UUID(user_id),
            ip_address=request.client.host if request.client else None,
        )
    return {"success": True}


# ---------------------------------------------------------------------------
# First-run setup (open until an admin exists; see setup.py)
# ---------------------------------------------------------------------------

@app.get("/setup/status")
def get_setup_status(db: Session = Depends(get_db)):
    """Whether the database is reachable and setup has been completed."""
    connectable = setup_module.db_connectable(db)
    return {
        "database_connectable": connectable,
        "setup_complete": connectable and setup_module.admin_exists(db),
    }


@app.post("/setup/initialize")
def initialize_setup(payload: SetupInitializeRequest, request: Request, db: Session = Depends(get_db)):
    """
    Run migrations, create the school and its first admin, and log that
    admin in. Refused (409) once an admin exists.
    """
    try:
        setup_module.run_migrations()
    except setup_module.SetupError as error:
        raise HTTPException(status_code=503, detail=str(error))

    if setup_module.admin_exists(db):
        raise HTTPException(status_code=409, detail="Setup has already been completed.")

    try:
        school, admin = setup_module.create_school_and_admin(
            db,
            school_name=payload.school_name,
            district_name=payload.district_name,
            admin_email=payload.admin_email,
            admin_password=payload.admin_password,
            admin_full_name=payload.admin_full_name,
        )
    except setup_module.SetupError as error:
        raise HTTPException(status_code=400, detail=str(error))

    # Log the new admin straight in, so the wizard's next step (CSV
    # import) is an authenticated admin request like any other.
    request.session.clear()
    request.session["user_id"] = str(admin.id)
    write_audit_log(
        db,
        action="Setup Completed",
        school_id=school.id,
        user_id=admin.id,
        entity_type="School",
        entity_id=school.id,
        ip_address=_client_ip(request),
    )

    return {
        "school_id": str(school.id),
        "school_name": school.name,
        "admin_id": str(admin.id),
        "admin_email": admin.email,
    }


# ---------------------------------------------------------------------------
# CSV import: preview (validate only) and commit
# ---------------------------------------------------------------------------

def _save_upload(upload: UploadFile | None, folder: str, name: str) -> Path | None:
    """Write an uploaded file into `folder`; None when nothing was uploaded."""
    if upload is None:
        return None
    path = Path(folder) / name
    with path.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return path


def _validate_uploads(db: Session, school_id, students_path, staff_path):
    """Run import_validation on whichever files were uploaded."""
    reports = []
    if students_path:
        reports.append(validate_students_csv(db, school_id, students_path))
    if staff_path:
        reports.append(validate_staff_csv(db, school_id, staff_path))
    return reports


def _commit_import(db: Session, user: User, students_path, staff_path, request: Request) -> dict:
    """Import already-validated files into the user's school and audit-log the counts."""
    school = db.query(School).filter(School.id == user.school_id).first()
    if not school:
        raise HTTPException(status_code=400, detail="Your account isn't linked to a school.")

    result = {"students_imported": 0, "staff_imported": 0, "services_imported": 0}
    # Staff first, so service providers exist before students reference them.
    if staff_path:
        result["staff_imported"] = import_staff(db, school, csv_path=staff_path)
    if students_path:
        result["students_imported"] = import_students(db, school, csv_path=students_path)
        services = import_student_services(db, school, csv_path=students_path)
        result["services_imported"] = services["services_created"]
        result["services_already_present"] = services["services_already_present"]

    write_audit_log(
        db,
        action="CSV Import",
        school_id=school.id,
        user_id=user.id,
        entity_type="Import",
        after=result,
        ip_address=_client_ip(request),
    )
    return result


@app.post("/import/preview")
def preview_import(
    students_file: UploadFile | None = File(None),
    staff_file: UploadFile | None = File(None),
    user: User = Depends(require_roles(*ADMIN)),
    db: Session = Depends(get_db),
):
    """Validates the files row by row and reports new/updated counts.
    Writes nothing."""
    if students_file is None and staff_file is None:
        raise HTTPException(status_code=400, detail="Upload a students file, a staff file, or both.")

    with tempfile.TemporaryDirectory() as tmpdir:
        students_path = _save_upload(students_file, tmpdir, "students.csv")
        staff_path = _save_upload(staff_file, tmpdir, "staff.csv")
        reports = _validate_uploads(db, user.school_id, students_path, staff_path)

    return {
        "can_import": all(r.error_count == 0 for r in reports),
        "files": [r.as_dict() for r in reports],
    }


@app.post("/import/commit")
def commit_import(
    request: Request,
    students_file: UploadFile | None = File(None),
    staff_file: UploadFile | None = File(None),
    user: User = Depends(require_roles(*ADMIN)),
    db: Session = Depends(get_db),
):
    """Re-validates (the files are re-uploaded, so the server never trusts
    an earlier preview) and imports only if there are no errors."""
    if students_file is None and staff_file is None:
        raise HTTPException(status_code=400, detail="Upload a students file, a staff file, or both.")

    with tempfile.TemporaryDirectory() as tmpdir:
        students_path = _save_upload(students_file, tmpdir, "students.csv")
        staff_path = _save_upload(staff_file, tmpdir, "staff.csv")
        reports = _validate_uploads(db, user.school_id, students_path, staff_path)

        if any(r.error_count for r in reports):
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Import refused: fix the errors and upload again.",
                    "files": [r.as_dict() for r in reports],
                },
            )

        result = _commit_import(db, user, students_path, staff_path, request)

    result["warnings"] = sum(r.warning_count for r in reports)
    return result


@app.post("/setup/import-csv")
def setup_import_csv(
    request: Request,
    students_file: UploadFile | None = File(None),
    staff_file: UploadFile | None = File(None),
    user: User = Depends(require_roles(*ADMIN)),
    db: Session = Depends(get_db),
):
    """
    The setup wizard's import step. /setup/initialize logs the new admin
    in, so this is an ordinary admin-only request. Same validation as
    /import/commit, but errors come back as one string because the
    wizard shows `detail` as text.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        students_path = _save_upload(students_file, tmpdir, "students.csv")
        staff_path = _save_upload(staff_file, tmpdir, "staff.csv")
        if not students_path and not staff_path:
            return {"students_imported": 0, "staff_imported": 0}

        reports = _validate_uploads(db, user.school_id, students_path, staff_path)
        if any(r.error_count for r in reports):
            raise HTTPException(status_code=422, detail=summarize_errors(reports))

        return _commit_import(db, user, students_path, staff_path, request)


# ---------------------------------------------------------------------------
# Current user and admin
# ---------------------------------------------------------------------------

@app.get("/me")
def get_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The logged-in user, with their linked staff member if any."""
    staff = None

    if user.staff_id:
        staff = db.query(StaffMember).filter(StaffMember.id == user.staff_id).first()

    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "school_id": str(user.school_id),
        "staff_member": (
            {
                "id": str(staff.id),
                "first_name": staff.first_name,
                "last_name": staff.last_name,
            }
            if staff
            else None
        ),
    }


@app.post("/admin/users")
def add_user(
    payload: CreateUserRequest,
    admin: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin only: create a login in the admin's school, optionally linked to a staff member."""
    if admin.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can add users")

    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {sorted(VALID_ROLES)}")

    # Prevent duplicate accounts
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="A user with this email already exists")

    # If linking to a staff member, make sure it exists and isn't already claimed
    if payload.staff_id:
        staff = (
            db.query(StaffMember)
            .filter(
                StaffMember.id == _parse_uuid(payload.staff_id, "Staff member"),
                StaffMember.school_id == admin.school_id,
            )
            .first()
        )
        if not staff:
            raise HTTPException(status_code=404, detail="Staff member not found")

        already_linked = db.query(User).filter(User.staff_id == payload.staff_id).first()
        if already_linked:
            raise HTTPException(status_code=400, detail="This staff member already has a linked account")

    new_user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        staff_id=payload.staff_id,
        school_id=admin.school_id,  # scope new user to the admin's school
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {"id": str(new_user.id), "email": new_user.email, "role": new_user.role}


@app.get("/admin/staff/unassigned")
def get_unassigned_staff(
    admin: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin only: staff members with no login yet (for the Add User form)."""
    if admin.role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    linked_staff_ids = db.query(User.staff_id).filter(User.staff_id.isnot(None))
    unassigned = (
        db.query(StaffMember)
        .filter(StaffMember.school_id == admin.school_id)
        .filter(~StaffMember.id.in_(linked_staff_ids))
        .all()
    )
    return [
        {"id": str(s.id), "first_name": s.first_name, "last_name": s.last_name}
        for s in unassigned
    ]

# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

@app.get("/students")
def list_students(
    search: str | None = None,
    grade: int | None = None,
    iep: bool | None = None,
    mtss_tier: int | None = None,
    user: User = Depends(require_roles(*MANAGERS)),
):
    """The school's students with their services, optionally filtered."""
    try:
        students = get_students(
            search=search, grade=grade, iep=iep, mtss_tier=mtss_tier,
            school_id=user.school_id,
        )
        return {"students": students, "count": len(students)}

    except DBAPIError as error:
        raise HTTPException(status_code=500, detail=str(error))


@app.put("/students/{student_id}")
def update_student(
    student_id: str,
    student: StudentUpdate,
    request: Request,
    user: User = Depends(require_roles(*MANAGERS)),
):
    """Edit a student's basic fields; only fields sent are changed."""
    db = SessionLocal()

    try:
        db_student = (
            db.query(Student)
            .filter(Student.id == _parse_uuid(student_id, "Student"), Student.school_id == user.school_id)
            .first()
        )

        if not db_student:
            raise HTTPException(status_code=404, detail="Student not found")

        # exclude_unset: only fields the client actually sent. Plain
        # .dict() includes every unsent field as None and would wipe
        # grade/homeroom whenever someone edits just a name.
        changes = {
            key: value for key, value in student.dict(exclude_unset=True).items()
            if key in ALLOWED_STUDENT_FIELDS
        }
        before = _jsonable({key: getattr(db_student, key) for key in changes})
        for key, value in changes.items():
            setattr(db_student, key, value)

        db.commit()
        db.refresh(db_student)

        write_audit_log(
            db,
            action="Update Student",
            school_id=user.school_id,
            user_id=user.id,
            entity_type="Student",
            entity_id=db_student.id,
            before=before,
            after=_jsonable(changes),
            ip_address=_client_ip(request),
        )

        return {"student": db_student}

    finally:
        db.close()


@app.get("/students/{student_id}/schedule")
def get_student_schedule(student_id: str, user: User = Depends(require_roles(*ALL_STAFF))):
    """
    Every schedule entry for one student (by school student ID). Teachers
    and aides may only look up students they teach.
    """
    db = SessionLocal()

    try:
        query = db.query(ScheduleEntry).filter(
            ScheduleEntry.school_id == user.school_id,
            ScheduleEntry.student_external_id == student_id,
        )
        entries = query.all()

        # Teachers and aides only see students they actually serve.
        if user.role not in MANAGERS:
            if not user.staff_id or not any(e.staff_id == user.staff_id for e in entries):
                raise HTTPException(status_code=404, detail="Student not found")

        return [
            {
                "id": str(e.id),
                "day_of_week": e.day_of_week,
                "period": e.period,
                "period_label": e.period_label,
                "subject": e.subject,
                "teacher": e.teacher_name,
                "service_type": e.service_type,
                "is_pullout": e.is_pullout,
                "is_flex_period": e.is_flex_period,
                **_entry_time_fields(e),
            }
            for e in entries
        ]

    finally:
        db.close()


@app.get("/me/students")
def get_my_students(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Returns the teacher's classes grouped by day and time, so it answers
    "who's in my class right now" rather than just a flat student list.

    Entries are split around pull-outs (a student pulled 11:00-11:30
    has an ELA piece starting 11:30), so a class is every entry with
    the same day/subject/service/room whose times overlap -- not every
    entry with the same start time.
    """
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Not allowed")

    if not user.staff_id:
        raise HTTPException(status_code=400, detail="Teacher account is not linked to staff member")

    rows = (
        db.query(ScheduleEntry, Student)
        .join(Student, ScheduleEntry.student_id == Student.id)
        .filter(ScheduleEntry.staff_id == user.staff_id)
        .all()
    )

    def bounds(entry):
        start = entry.start_minute if entry.start_minute is not None else entry.period
        end = entry.end_minute if entry.end_minute is not None else start + 1
        return start, end

    buckets: dict = {}
    for entry, student in rows:
        key = (entry.day_of_week, entry.subject, entry.service_type, entry.room)
        buckets.setdefault(key, []).append((entry, student))

    classes: list = []
    for items in buckets.values():
        items.sort(key=lambda pair: bounds(pair[0])[0])
        current = None
        for entry, student in items:
            start, end = bounds(entry)
            if current is None or start >= current["end_minute"]:
                current = {
                    "day_of_week": entry.day_of_week,
                    "period": start,
                    "start_minute": start,
                    "end_minute": end,
                    "period_label": entry.period_label,
                    "subject": entry.subject,
                    "block_subject": entry.block_subject,
                    "service_type": entry.service_type,
                    "delivery": entry.delivery,
                    "room": entry.room,
                    "is_pullout": entry.is_pullout,
                    "is_flex_period": entry.is_flex_period,
                    "students": [],
                    "_ids": set(),
                }
                classes.append(current)
            current["end_minute"] = max(current["end_minute"], end)
            if student.id in current["_ids"]:
                continue
            current["_ids"].add(student.id)
            current["students"].append({
                "id": str(student.id),
                "first_name": student.first_name,
                "last_name": student.last_name,
                "grade": student.grade,
                "homeroom": student.homeroom,
                "has_iep": student.has_iep,
                "mtss_tier": student.mtss_tier,
                "enl_level": student.enl_level,
            })

    for c in classes:
        del c["_ids"]
        c["time_range"] = format_range(c["start_minute"], c["end_minute"])

    return sorted(
        classes,
        key=lambda c: (day_index(c["day_of_week"]), c["start_minute"]),
    )


# ---------------------------------------------------------------------------
# Pydantic models — Student Services
# ---------------------------------------------------------------------------

class StudentServiceCreate(BaseModel):
    service_type: str
    subject_area: str | None = None
    minutes_per_week: int = Field(gt=0)
    sessions_per_week: int | None = Field(default=None, gt=0)
    is_pullout: bool = True
    preferred_provider_id: str | None = None
    notes: str | None = None

class StudentServiceUpdate(BaseModel):
    service_type: str | None = None
    subject_area: str | None = None
    minutes_per_week: int | None = Field(default=None, gt=0)
    sessions_per_week: int | None = Field(default=None, gt=0)
    is_pullout: bool | None = None
    preferred_provider_id: str | None = None
    notes: str | None = None

ALLOWED_SERVICE_FIELDS = {
    "service_type", "subject_area", "minutes_per_week",
    "sessions_per_week", "is_pullout", "preferred_provider_id", "notes",
}


# ---------------------------------------------------------------------------
# Student Services
# ---------------------------------------------------------------------------

@app.post("/students/{student_id}/services")
def create_student_service(
    student_id: str,
    payload: StudentServiceCreate,
    request: Request,
    user: User = Depends(require_roles(*MANAGERS)),
):
    """Add a service requirement (e.g. 90 min/week of ENL) to a student."""
    db = SessionLocal()
    try:
        student = (
            db.query(Student)
            .filter(Student.id == _parse_uuid(student_id, "Student"), Student.school_id == user.school_id)
            .first()
        )
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        if payload.preferred_provider_id:
            provider = db.query(StaffMember).filter(
                StaffMember.id == _parse_uuid(payload.preferred_provider_id, "Preferred provider"),
                StaffMember.school_id == user.school_id,
            ).first()
            if not provider:
                raise HTTPException(status_code=404, detail="Preferred provider not found")

        service = StudentService(
            school_id=student.school_id,
            student_id=student.id,
            service_type=payload.service_type,
            subject_area=payload.subject_area,
            minutes_per_week=payload.minutes_per_week,
            sessions_per_week=payload.sessions_per_week,
            is_pullout=payload.is_pullout,
            preferred_provider_id=payload.preferred_provider_id,
            notes=payload.notes,
        )
        db.add(service)
        db.commit()
        db.refresh(service)

        write_audit_log(
            db,
            action="Create Student Service",
            school_id=user.school_id,
            user_id=user.id,
            entity_type="StudentService",
            entity_id=service.id,
            after=_jsonable({
                "student_id": str(student.id),
                "service_type": service.service_type,
                "minutes_per_week": service.minutes_per_week,
            }),
            ip_address=request.client.host if request.client else None,
        )

        return {
            "id": str(service.id),
            "student_id": str(service.student_id),
            "service_type": service.service_type,
            "subject_area": service.subject_area,
            "minutes_per_week": service.minutes_per_week,
            "sessions_per_week": service.sessions_per_week,
            "is_pullout": service.is_pullout,
            "preferred_provider_id": str(service.preferred_provider_id) if service.preferred_provider_id else None,
            "notes": service.notes,
        }
    finally:
        db.close()


@app.get("/students/{student_id}/services")
def list_student_services(student_id: str, user: User = Depends(require_roles(*MANAGERS))):
    """A student's service requirements."""
    db = SessionLocal()
    try:
        student = (
            db.query(Student)
            .filter(Student.id == _parse_uuid(student_id, "Student"), Student.school_id == user.school_id)
            .first()
        )
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        services = (
            db.query(StudentService)
            .filter(StudentService.student_id == student_id)
            .order_by(StudentService.service_type)
            .all()
        )

        return [
            {
                "id": str(s.id),
                "service_type": s.service_type,
                "subject_area": s.subject_area,
                "minutes_per_week": s.minutes_per_week,
                "sessions_per_week": s.sessions_per_week,
                "is_pullout": s.is_pullout,
                "preferred_provider_id": str(s.preferred_provider_id) if s.preferred_provider_id else None,
                "notes": s.notes,
            }
            for s in services
        ]
    finally:
        db.close()


@app.get("/students/{student_id}/services/{service_id}/suggestions")
def suggest_times_for_service(
    student_id: str,
    service_id: str,
    top_n: int = 5,
    user: User = Depends(require_roles(*MANAGERS)),
):
    """
    "When could this happen?" -- the best open times for one session of
    this service, ranked against the latest generated schedule. The
    student's own class time counts as free (that's what a pull-out
    replaces); providers' existing bookings count as busy.
    """
    if user.role not in ("admin", "principal"):
        raise HTTPException(status_code=403, detail="Not allowed")

    try:
        student_uuid, service_uuid = UUID(student_id), UUID(service_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Service not found")

    db = SessionLocal()
    try:
        service = (
            db.query(StudentService)
            .filter(
                StudentService.id == service_uuid,
                StudentService.student_id == student_uuid,
                StudentService.school_id == user.school_id,
            )
            .first()
        )
        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        run = _latest_full_run(db, user.school_id)
        if not run:
            raise HTTPException(status_code=409, detail="Generate a schedule first.")
        period_config = _run_period_config(run)
        entries = _run_entries_as_dicts(db, run.id)
    finally:
        db.close()

    try:
        students = get_students(school_id=user.school_id)
        staff = get_staff(school_id=user.school_id)
    except DBAPIError as error:
        raise HTTPException(status_code=500, detail=str(error))

    student = next((s for s in students if str(s.get("id")) == student_id), None)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    try:
        suggestions = suggest_service_slots(
            entries=entries,
            # entries carry the DB UUID as student_id; match it
            student={**student, "student_id": student_id},
            service={
                "service_type": service.service_type,
                "subject": service.service_type,
                "minutes": service.minutes_per_week,
                "sessions_per_week": service.sessions_per_week,
                "is_pullout": service.is_pullout,
                "subject_area": service.subject_area,
            },
            staff_members=staff,
            period_config=period_config,
            top_n=max(1, min(top_n, 20)),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    return {"run_id": str(run.id), "suggestions": suggestions}


@app.put("/students/{student_id}/services/{service_id}")
def update_student_service(
    student_id: str,
    service_id: str,
    payload: StudentServiceUpdate,
    request: Request,
    user: User = Depends(require_roles(*MANAGERS)),
):
    """Edit one of a student's service requirements."""
    db = SessionLocal()
    try:
        service = (
            db.query(StudentService)
            .filter(
                StudentService.id == _parse_uuid(service_id, "Service"),
                StudentService.student_id == _parse_uuid(student_id, "Service"),
                StudentService.school_id == user.school_id,
            )
            .first()
        )
        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        update_data = payload.dict(exclude_unset=True)
        before = _jsonable({
            field: getattr(service, field) for field in update_data if field in ALLOWED_SERVICE_FIELDS
        })

        for field, value in update_data.items():
            if field in ALLOWED_SERVICE_FIELDS:
                if field == "preferred_provider_id" and value:
                    provider = db.query(StaffMember).filter(
                        StaffMember.id == _parse_uuid(value, "Preferred provider"),
                        StaffMember.school_id == user.school_id,
                    ).first()
                    if not provider:
                        raise HTTPException(status_code=404, detail="Preferred provider not found")
                setattr(service, field, value)

        db.commit()
        db.refresh(service)

        write_audit_log(
            db,
            action="Update Student Service",
            school_id=user.school_id,
            user_id=user.id,
            entity_type="StudentService",
            entity_id=service.id,
            before=before,
            after=_jsonable(update_data),
            ip_address=request.client.host if request.client else None,
        )

        return {"success": True, "id": str(service.id)}
    finally:
        db.close()


@app.delete("/students/{student_id}/services/{service_id}")
def delete_student_service(
    student_id: str,
    service_id: str,
    request: Request,
    user: User = Depends(require_roles(*MANAGERS)),
):
    """Remove one of a student's service requirements."""
    db = SessionLocal()
    try:
        service = (
            db.query(StudentService)
            .filter(
                StudentService.id == _parse_uuid(service_id, "Service"),
                StudentService.student_id == _parse_uuid(student_id, "Service"),
                StudentService.school_id == user.school_id,
            )
            .first()
        )
        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        before = _jsonable({
            "service_type": service.service_type,
            "minutes_per_week": service.minutes_per_week,
        })

        db.delete(service)
        db.commit()

        write_audit_log(
            db,
            action="Delete Student Service",
            school_id=user.school_id,
            user_id=user.id,
            entity_type="StudentService",
            entity_id=service.id,
            before=before,
            ip_address=request.client.host if request.client else None,
        )

        return {"status": "deleted", "id": service_id}
    finally:
        db.close()

# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------

@app.get("/staff")
def list_staff(user: User = Depends(require_roles(*ALL_STAFF))):
    """The school's staff members."""
    try:
        staff = get_staff(school_id=user.school_id)
        return {"staff": staff, "count": len(staff)}

    except DBAPIError as error:
        raise HTTPException(status_code=500, detail=str(error))


@app.post("/staff")
def create_staff(
    staff: StaffCreate,
    request: Request,
    user: User = Depends(require_roles(*MANAGERS)),
    db: Session = Depends(get_db),
):
    """Add a staff member to the caller's school."""
    try:
        data = staff.dict(exclude={"school_id"})
        db_staff = StaffMember(**data, school_id=user.school_id)
        db.add(db_staff)
        db.commit()
        db.refresh(db_staff)

        write_audit_log(
            db,
            action="Create Staff",
            school_id=user.school_id,
            user_id=user.id,
            entity_type="StaffMember",
            entity_id=db_staff.id,
            after=_jsonable(data),
            ip_address=_client_ip(request),
        )

        return {
            "staff": {
                "id": str(db_staff.id),
                "school_id": str(db_staff.school_id),
                "external_staff_id": db_staff.external_staff_id,
                "first_name": db_staff.first_name,
                "last_name": db_staff.last_name,
                "title": db_staff.title,
                "grade": db_staff.grade,
                "homeroom": db_staff.homeroom,
                "room": db_staff.room,
                "is_certified_sped": db_staff.is_certified_sped,
                "is_certified_enl": db_staff.is_certified_enl,
                "is_certified_slp": db_staff.is_certified_slp,
                "can_deliver_setss": db_staff.can_deliver_setss,
                "max_students_per_group": db_staff.max_students_per_group,
                "created_at": db_staff.created_at.isoformat() if db_staff.created_at else None,
            }
        }

    except Exception:
        db.rollback()
        # Don't echo raw database errors (they can include other rows' data).
        raise HTTPException(status_code=400, detail="Couldn't create staff member. Check the fields and try again.")


@app.put("/staff/{staff_id}")
def update_staff(
    staff_id: str,
    payload: StaffUpdate,
    request: Request,
    user: User = Depends(require_roles(*MANAGERS)),
):
    """Edit a staff member's grade and certifications."""
    db = SessionLocal()
    try:
        staff = (
            db.query(StaffMember)
            .filter(StaffMember.id == _parse_uuid(staff_id, "Staff"), StaffMember.school_id == user.school_id)
            .first()
        )
        if not staff:
            raise HTTPException(status_code=404, detail="Staff not found")

        # exclude_unset: toggling one certification must not null out
        # grade (a known root cause of bad staff matching).
        changes = {
            field: value for field, value in payload.dict(exclude_unset=True).items()
            if field in ALLOWED_STAFF_FIELDS
        }
        before = _jsonable({field: getattr(staff, field) for field in changes})
        for field, value in changes.items():
            setattr(staff, field, value)

        db.commit()
        db.refresh(staff)

        write_audit_log(
            db,
            action="Update Staff",
            school_id=user.school_id,
            user_id=user.id,
            entity_type="StaffMember",
            entity_id=staff.id,
            before=before,
            after=_jsonable(changes),
            ip_address=_client_ip(request),
        )

        return {
            "id": str(staff.id),
            "first_name": staff.first_name,
            "last_name": staff.last_name,
            "title": staff.title,
            "grade": staff.grade,
            "is_certified_sped": staff.is_certified_sped,
            "is_certified_enl": staff.is_certified_enl,
            "is_certified_slp": staff.is_certified_slp,
            "can_deliver_setss": staff.can_deliver_setss,
            "homeroom": staff.homeroom,
        }
    finally:
        db.close()

# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

@app.get("/schedule")
def list_schedule_entries(run_id: str | None = None, user: User = Depends(require_roles(*ALL_STAFF))):
    """
    Student schedule entries for one run: `run_id`, or the school's
    current run when omitted (the latest published one, else the latest
    one; same default as /staff-schedule).

    Admins/principals get the whole school's entries. Teachers and aides
    get the entries they deliver, plus the pull-outs and push-ins (ENL,
    IEP and other services delivered by someone else) of students they
    teach in the same run, so they can see when a student leaves their
    class, or a provider joins it, and why. Other students' schedules
    stay hidden from them.

    A run is thousands of rows, so this selects only the columns it
    returns (ids cast to text in SQL) and hands back ready-made JSON,
    skipping ORM objects and FastAPI's generic encoder.
    """
    db = SessionLocal()

    try:
        if run_id:
            run_uuid = _parse_uuid(run_id, "Schedule run")
        else:
            run = _current_run(db, user.school_id)
            if not run:
                return []
            run_uuid = run.id

        query = (
            db.query(
                cast(ScheduleEntry.id, String),
                cast(ScheduleEntry.run_id, String),
                cast(Student.id, String),
                Student.first_name,
                Student.last_name,
                Student.grade,
                cast(StaffMember.id, String),
                StaffMember.first_name,
                StaffMember.last_name,
                ScheduleEntry.teacher_name,
                ScheduleEntry.day_of_week,
                ScheduleEntry.period,
                ScheduleEntry.period_label,
                ScheduleEntry.subject,
                ScheduleEntry.service_type,
                ScheduleEntry.is_pullout,
                ScheduleEntry.is_flex_period,
                ScheduleEntry.start_minute,
                ScheduleEntry.end_minute,
                ScheduleEntry.delivery,
                ScheduleEntry.block_subject,
                ScheduleEntry.room,
            )
            .join(Student, ScheduleEntry.student_id == Student.id)
            .outerjoin(StaffMember, ScheduleEntry.staff_id == StaffMember.id)
            .filter(ScheduleEntry.school_id == user.school_id)
            .filter(ScheduleEntry.run_id == run_uuid)
        )
        if user.role not in MANAGERS:
            if not user.staff_id:
                return []
            # "Students I teach" = students with one of my entries in the same run.
            mine = aliased(ScheduleEntry)
            my_student_in_run = exists().where(
                mine.run_id == ScheduleEntry.run_id,
                mine.student_id == ScheduleEntry.student_id,
                mine.staff_id == user.staff_id,
            )
            # Older rows have no `delivery`; is_pullout is the fallback.
            is_pullout = or_(
                ScheduleEntry.delivery == "pullout",
                and_(ScheduleEntry.delivery.is_(None), ScheduleEntry.is_pullout.is_(True)),
            )
            is_service = or_(is_pullout, ScheduleEntry.delivery == "push_in")
            query = query.filter(or_(
                ScheduleEntry.staff_id == user.staff_id,
                and_(is_service, my_student_in_run),
            ))

        rows = [
            {
                "id": entry_id,
                "run_id": entry_run_id,
                "student_id": student_id,
                "student_name": f"{student_first} {student_last}",
                "grade": grade,
                "staff_id": staff_id,
                "staff_name": f"{staff_first} {staff_last}" if staff_id else teacher_name,
                "day_of_week": day_of_week,
                "period": period,
                "period_label": period_label,
                "subject": subject,
                "service_type": service_type,
                "is_pullout": is_pullout_value,
                "is_flex_period": is_flex_period,
                # Same fields as _entry_time_fields(), from the selected columns.
                "start_minute": start_minute,
                "end_minute": end_minute,
                "time_range": (
                    format_range(start_minute, end_minute)
                    if start_minute is not None and end_minute is not None else None
                ),
                "delivery": delivery,
                "block_subject": block_subject,
                "room": room,
            }
            for (
                entry_id, entry_run_id, student_id, student_first, student_last, grade,
                staff_id, staff_first, staff_last, teacher_name, day_of_week, period,
                period_label, subject, service_type, is_pullout_value, is_flex_period,
                start_minute, end_minute, delivery, block_subject, room,
            ) in query.all()
        ]
        return JSONResponse(rows)
    finally:
        db.close()


@app.put("/schedule/{entry_id}")
def update_schedule_entry(
    entry_id: str,
    payload: dict,
    request: Request,
    user: User = Depends(require_roles(*MANAGERS)),
):
    """Manually edit one schedule entry (teacher, time, room, ...). Unknown fields are rejected."""
    unknown = set(payload) - ALLOWED_SCHEDULE_ENTRY_FIELDS
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"These fields can't be edited: {sorted(unknown)}",
        )

    db = SessionLocal()
    try:
        entry = (
            db.query(ScheduleEntry)
            .filter(ScheduleEntry.id == _parse_uuid(entry_id, "Entry"), ScheduleEntry.school_id == user.school_id)
            .first()
        )
        if not entry:
            raise HTTPException(status_code=404, detail="Not found")
        if db.query(ScheduleRun.status).filter(ScheduleRun.id == entry.run_id).scalar() == PUBLISHED:
            raise HTTPException(
                status_code=409,
                detail="This schedule is published and can't be edited. Generate a new draft to make changes.",
            )

        before = _jsonable({key: getattr(entry, key) for key in payload})

        if "delivery" in payload and payload["delivery"] not in VALID_DELIVERIES:
            raise HTTPException(
                status_code=400,
                detail=f"delivery must be one of {sorted(VALID_DELIVERIES)}",
            )

        for key, value in payload.items():
            if key == "staff_id":
                continue  # resolved below so teacher_name stays in sync
            setattr(entry, key, value)

        # Reassigning a teacher goes through staff_id; teacher_name is
        # derived from it so the two can never disagree.
        if "staff_id" in payload:
            if payload["staff_id"]:
                try:
                    staff_uuid = UUID(str(payload["staff_id"]))
                except ValueError:
                    raise HTTPException(status_code=400, detail="staff_id is not a valid id")
                staff = (
                    db.query(StaffMember)
                    .filter(StaffMember.id == staff_uuid, StaffMember.school_id == user.school_id)
                    .first()
                )
                if not staff:
                    raise HTTPException(status_code=404, detail="Staff member not found")
                entry.staff_id = staff.id
                entry.teacher_name = f"{staff.first_name} {staff.last_name}".strip()
            else:
                entry.staff_id = None
                entry.teacher_name = ""

        # is_pullout is derived from delivery, never set on its own.
        if "delivery" in payload:
            entry.is_pullout = payload["delivery"] == "pullout"
        # `period` is the start minute; keep the two in lockstep so the
        # (run, student, day, period) unique constraint stays meaningful.
        if "start_minute" in payload:
            entry.period = payload["start_minute"]

        db.commit()
        db.refresh(entry)

        write_audit_log(
            db,
            action="Update Schedule Entry",
            school_id=user.school_id,
            user_id=user.id,
            entity_type="ScheduleEntry",
            entity_id=entry.id,
            before=before,
            after=_jsonable(payload),
            ip_address=request.client.host if request.client else None,
        )

        return {"success": True, "id": str(entry.id)}
    
    finally:
        db.close()


@app.get("/staff-schedule")
def list_staff_schedule_entries(
    run_id: str | None = None,
    staff_id: str | None = None,
    user: User = Depends(require_roles(*ALL_STAFF)),
):
    """Saved teacher schedules: one row per teacher per class/session,
    including prep and lunch. Defaults to the current run (latest
    published, else latest). Teachers only ever get their own rows."""
    db = SessionLocal()
    try:
        if user.role not in ("admin", "principal"):
            if not user.staff_id:
                raise HTTPException(status_code=400, detail="Account is not linked to a staff member")
            staff_id = str(user.staff_id)

        try:
            if run_id:
                run_uuid = UUID(run_id)
            else:
                run = _current_run(db, user.school_id)
                if not run:
                    return []
                run_uuid = run.id
            staff_uuid = UUID(staff_id) if staff_id else None
        except ValueError:
            raise HTTPException(status_code=400, detail="run_id / staff_id is not a valid id")

        query = db.query(StaffScheduleEntry).filter(
            StaffScheduleEntry.run_id == run_uuid,
            StaffScheduleEntry.school_id == user.school_id,
        )
        if staff_uuid:
            query = query.filter(StaffScheduleEntry.staff_id == staff_uuid)

        entries = query.all()
        entries.sort(key=lambda e: (e.teacher_name or "", day_index(e.day_of_week), e.start_minute))

        return [
            {
                "id": str(e.id),
                "run_id": str(e.run_id),
                "staff_id": str(e.staff_id) if e.staff_id else None,
                "staff_name": e.teacher_name,
                "day_of_week": e.day_of_week,
                "period": e.period,
                "period_label": e.period_label,
                "subject": e.subject,
                "grade": e.grade,
                "service_type": e.service_type,
                "is_pullout": e.is_pullout,
                "is_flex_period": e.is_flex_period,
                "student_count": e.student_count,
                **_entry_time_fields(e),
            }
            for e in entries
        ]
    finally:
        db.close()


@app.get("/preview-priority")
def preview_priority(user: User = Depends(require_roles(*MANAGERS))):
    """Calculate student scheduling priority order. Does not save schedule changes."""
    try:
        students = get_students(school_id=user.school_id)
        staff = get_staff(school_id=user.school_id)
        school_year = os.getenv("SCHOOL_YEAR", "2026-2027")

        result = schedule_iep_services_first(
            students=students,
            staff_members=staff,
            school_year=school_year,
        )

        return {
            "success": True,
            "students_received": result["students_received"],
            "ranked_students": result["ranked_students"],
            "summary": result["summary"],
        }

    except DBAPIError as error:
        raise HTTPException(status_code=500, detail=str(error))


@app.get("/schedule/config-defaults")
def get_schedule_config_defaults(user: User = Depends(require_roles(*MANAGERS))):
    """
    Prefill for the Generate Schedule modal: the master schedule and
    rules from the most recent full run, so the principal doesn't
    re-enter them every time -- or the built-in defaults if there's no
    usable run yet.
    """
    db = SessionLocal()
    try:
        run = _latest_full_run(db, user.school_id)
        payload = (run.summary_json or {}).get("period_config") if run else None
    finally:
        db.close()

    if payload:
        try:
            # Round-tripped rather than returned as saved, so a run made
            # with weekday names comes back as cycle days (A-E).
            config = PeriodConfig.from_config(payload).to_config_payload()
            return {"source": "last_run", "run_id": str(run.id), "config": config}
        except ValueError as error:
            return {
                "source": "defaults",
                "warning": f"The last run's master schedule couldn't be loaded ({error}); showing defaults.",
                "config": PeriodConfig().to_config_payload(),
            }

    return {"source": "defaults", "config": PeriodConfig().to_config_payload()}


@app.get("/schedule-runs")
def list_schedule_runs(user: User = Depends(require_roles(*MANAGERS))):
    """The school's schedule runs, newest first, with entry counts and open critical flag counts."""
    db = SessionLocal()
    try:
        runs = (
            db.query(ScheduleRun)
            .filter(ScheduleRun.school_id == user.school_id)
            .order_by(ScheduleRun.created_at.desc())
            .all()
        )
        run_ids = [r.id for r in runs]

        entry_counts = dict(
            db.query(ScheduleEntry.run_id, func.count(ScheduleEntry.id))
            .filter(ScheduleEntry.run_id.in_(run_ids))
            .group_by(ScheduleEntry.run_id)
            .all()
        )

        critical_flag_counts = dict(
            db.query(ComplianceFlag.run_id, func.count(ComplianceFlag.id))
            .filter(
                ComplianceFlag.run_id.in_(run_ids),
                ComplianceFlag.severity == "critical",
                ComplianceFlag.status == "open",
            )
            .group_by(ComplianceFlag.run_id)
            .all()
        )

        return [
            {
                "id": str(r.id),
                "name": r.name,
                "school_year": r.school_year,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "summary": r.summary_json,
                "entry_count": entry_counts.get(r.id, 0),
                "open_critical_flags": critical_flag_counts.get(r.id, 0),
            }
            for r in runs
        ]
    finally:
        db.close()


@app.get("/schedule-runs/{run_id}")
def get_schedule_run(run_id: str, user: User = Depends(require_roles(*MANAGERS))):
    """One schedule run with its entries, compliance flags and summary (including its master schedule)."""
    db = SessionLocal()
    try:
        run = (
            db.query(ScheduleRun)
            .filter(ScheduleRun.id == _parse_uuid(run_id, "Schedule run"), ScheduleRun.school_id == user.school_id)
            .first()
        )
        if not run:
            raise HTTPException(status_code=404, detail="Schedule run not found")

        entries = (
            db.query(ScheduleEntry, Student, StaffMember)
            .join(Student, ScheduleEntry.student_id == Student.id)
            .outerjoin(StaffMember, ScheduleEntry.staff_id == StaffMember.id)
            .filter(ScheduleEntry.run_id == run.id)
            .all()
        )

        flags = db.query(ComplianceFlag).filter(ComplianceFlag.run_id == run.id).all()

        return {
            "id": str(run.id),
            "name": run.name,
            "status": run.status,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "summary": run.summary_json,
            "entries": [
                {
                    "id": str(entry.id),
                    "student_id": str(student.id),
                    "student_name": f"{student.first_name} {student.last_name}",
                    "grade": student.grade,
                    "staff_id": str(staff.id) if staff else None,
                    "staff_name": (f"{staff.first_name} {staff.last_name}" if staff else entry.teacher_name),
                    "day_of_week": entry.day_of_week,
                    "period": entry.period,
                    "period_label": entry.period_label,
                    "subject": entry.subject,
                    "service_type": entry.service_type,
                    "is_pullout": entry.is_pullout,
                    "is_flex_period": entry.is_flex_period,
                    **_entry_time_fields(entry),
                }
                for entry, student, staff in entries
            ],
            "compliance_flags": [
                {
                    "id": str(f.id),
                    "flag_type": f.flag_type,
                    "severity": f.severity,
                    "title": f.title,
                    "status": f.status,
                }
                for f in flags
            ],
        }
    finally:
        db.close()


def _run_summary(result: dict, period_config: PeriodConfig, critical_flags: list) -> dict:
    """What gets stored in ScheduleRun.summary_json. period_config is
    saved so the run can be re-checked against the master schedule it
    was built with, and so the modal can prefill from it."""
    return {
        "compliance_check_passed": len(critical_flags) == 0,
        "open_critical_flags": len(critical_flags),
        "status": "draft",
        "summary": result["summary"],
        "period_config": period_config.to_config_payload(),
        "service_placement_report": result["service_placement_report"],
    }


@app.post("/schedule-runs/{run_id}/publish")
def publish_schedule_run(run_id: str, request: Request, user: User = Depends(require_roles(*MANAGERS))):
    """
    Make a draft run permanent. It becomes the schedule teachers see and
    its entries can no longer be edited. There is no unpublish: to change
    it, generate and publish a new run (or Reset, which wipes every run).
    """
    db = SessionLocal()
    try:
        run = (
            db.query(ScheduleRun)
            .filter(ScheduleRun.id == _parse_uuid(run_id, "Schedule run"), ScheduleRun.school_id == user.school_id)
            .first()
        )
        if not run:
            raise HTTPException(status_code=404, detail="Schedule run not found")
        if run.status == PUBLISHED:
            raise HTTPException(status_code=409, detail="This schedule is already published.")

        before_status = run.status
        run.status = PUBLISHED
        run.published_at = datetime.utcnow()
        db.commit()

        write_audit_log(
            db,
            action="Publish Schedule",
            school_id=user.school_id,
            user_id=user.id,
            entity_type="ScheduleRun",
            entity_id=run.id,
            before={"status": before_status},
            after={"status": PUBLISHED},
            ip_address=_client_ip(request),
        )
        return {
            "id": str(run.id),
            "status": run.status,
            "published_at": run.published_at.isoformat(),
        }
    finally:
        db.close()


@app.post("/save-schedule")
def save_schedule(
    config: ScheduleGenerationConfig,
    request: Request,
    user: User = Depends(require_roles(*MANAGERS)),
):
    """
    Generate and save a full schedule in one request (blocks until done).
    The UI uses /schedule/generate/start instead, which reports progress.
    """
    try:
        period_config = PeriodConfig.from_config(config)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    school_id = user.school_id
    try:
        students = get_students(school_id=school_id)
        staff = get_staff(school_id=school_id)
        school_year = os.getenv("SCHOOL_YEAR", "2026-2027")

        result = schedule_iep_services_first(
            students=students,
            staff_members=staff,
            school_year=school_year,
            period_config=period_config,
        )

        schedule_entries = result["schedule_entries"]
        staff_schedule_entries = result["staff_schedule_entries"]
        compliance_flags = result["compliance_flags"]
        flex_groups = result["flex_groups"]
        flex_group_students = result["flex_group_students"]

        critical_flags = [f for f in compliance_flags if f.get("severity") == "critical"]

        schedule_run_id = create_schedule_run(
            school_year=school_year,
            name=FULL_SCHEDULE_RUN_NAME,
            summary=_run_summary(result, period_config, critical_flags),
            school_id=school_id,
        )

        create_schedule_entries(schedule_entries, run_id=schedule_run_id)
        create_staff_schedule_entries(staff_schedule_entries, run_id=schedule_run_id)
        create_compliance_flags(compliance_flags, run_id=schedule_run_id)
        create_flex_groups(flex_groups, run_id=schedule_run_id)
        create_flex_group_students(flex_group_students, run_id=schedule_run_id)

        db = SessionLocal()
        try:
            write_audit_log(
                db,
                action="Save Schedule",
                school_id=school_id,
                user_id=user.id,
                entity_type="ScheduleRun",
                entity_id=UUID(schedule_run_id),
                ip_address=_client_ip(request),
            )
        finally:
            db.close()

        return {
            "success": True,
            "summary": result["summary"],
            "saved": {
                "schedule_entries": len(schedule_entries),
                "staff_schedule_entries": len(staff_schedule_entries),
                "compliance_flags": len(compliance_flags),
                "flex_groups": len(flex_groups),
                "flex_group_students": len(flex_group_students),
                "schedule_runs": 1,
            },
            "schedule_run_id": schedule_run_id,
        }

    except DBAPIError as error:
        raise HTTPException(status_code=500, detail=str(error))


@app.post("/reset-generated-schedules")
def reset_generated_schedules(request: Request, user: User = Depends(require_roles(*ADMIN))):
    """Delete ALL of this school's generated schedule output, published
    runs included, for a clean regenerate. Student and staff records
    remain unchanged. Admin-only and audited: it's destructive."""
    school_id = user.school_id
    try:
        deleted_schedule_entries = delete_entity_many("ScheduleEntry", {}, school_id=school_id)
        deleted_compliance_flags = delete_entity_many("ComplianceFlag", {}, school_id=school_id)
        # Deleting flex groups cascades to their flex_group_students rows.
        deleted_flex_groups = delete_entity_many("FlexGroup", {}, school_id=school_id)
        deleted_flex_group_students = {"deleted": "cascaded with flex groups"}
        # Runs last; staff_schedule_entries cascade from them.
        deleted_schedule_runs = delete_entity_many("ScheduleRun", {}, school_id=school_id)

        db = SessionLocal()
        try:
            write_audit_log(
                db,
                action="Reset Generated Schedules",
                school_id=school_id,
                user_id=user.id,
                entity_type="ScheduleRun",
                after={"schedule_runs": deleted_schedule_runs.get("deleted")},
                ip_address=_client_ip(request),
            )
        finally:
            db.close()

        return {
            "success": True,
            "message": "Generated schedules reset successfully.",
            "deleted": {
                "schedule_entries": deleted_schedule_entries,
                "schedule_runs": deleted_schedule_runs,
                "compliance_flags": deleted_compliance_flags,
                "flex_groups": deleted_flex_groups,
                "flex_group_students": deleted_flex_group_students,
            },
        }

    except DBAPIError as error:
        raise HTTPException(status_code=500, detail=str(error))


def _run_schedule_job(job_id: str, config: ScheduleGenerationConfig, user_id=None, school_id=None):
    """Background thread body: generate and save a schedule, updating SCHEDULE_JOBS[job_id] as it goes."""
    def progress(stage_index: int, message: str | None = None):
        SCHEDULE_JOBS[job_id].update({
            "current_stage": stage_index,
            "stage_name": SCHEDULE_STAGES[stage_index],
            "percent": int(((stage_index + 1) / len(SCHEDULE_STAGES)) * 100),
            "message": message,
        })

    try:
        SCHEDULE_JOBS[job_id]["status"] = "running"
        try:
            period_config = PeriodConfig.from_config(config)
        except ValueError as error:
            SCHEDULE_JOBS[job_id].update({"status": "error", "error": str(error)})
            return

        # Log the config that will actually be used, so a field that
        # never reached the engine shows up here instead of silently.
        print(f"[schedule job {job_id}] master schedule: "
              f"grades={period_config.grades} "
              f"pullout_blocks={sorted(s for s, p in period_config.block_policies.items() if p['allow_pullout'])} "
              f"pushin_blocks={sorted(s for s, p in period_config.block_policies.items() if p['allow_pushin'])} "
              f"min_gap={period_config.min_gap_minutes} "
              f"max_pullouts={period_config.max_pullouts_per_day} "
              f"specials={period_config.specials_sessions_per_week}")
        
        students = get_students(school_id=school_id)
        staff = get_staff(school_id=school_id)
        school_year = os.getenv("SCHOOL_YEAR", "2026-2027")

        result = schedule_iep_services_first(
            students=students,
            staff_members=staff,
            school_year=school_year,
            period_config=period_config,
            progress_callback=progress,
        )
        schedule_entries = result["schedule_entries"]
        staff_schedule_entries = result["staff_schedule_entries"]
        compliance_flags = result["compliance_flags"]
        flex_groups = result["flex_groups"]
        flex_group_students = result["flex_group_students"]

        critical_flags = [f for f in compliance_flags if f.get("severity") == "critical"]

        schedule_run_id = create_schedule_run(
            school_year=school_year,
            name=FULL_SCHEDULE_RUN_NAME,
            summary=_run_summary(result, period_config, critical_flags),
            school_id=school_id,
        )

        progress(6, "Saving schedule to database")  # rows inherit the run's school
        create_schedule_entries(schedule_entries, run_id=schedule_run_id)
        create_staff_schedule_entries(staff_schedule_entries, run_id=schedule_run_id)
        create_compliance_flags(compliance_flags, run_id=schedule_run_id)
        create_flex_groups(flex_groups, run_id=schedule_run_id)
        create_flex_group_students(flex_group_students, run_id=schedule_run_id)

        SCHEDULE_JOBS[job_id].update({
            "status": "complete",
            "percent": 100,
            "result": {
                "success": True,
                "summary": result["summary"],
                "saved": {
                    "schedule_entries": len(schedule_entries),
                    "staff_schedule_entries": len(staff_schedule_entries),
                    "compliance_flags": len(compliance_flags),
                    "flex_groups": len(flex_groups),
                    "flex_group_students": len(flex_group_students),
                },
                "schedule_run_id": schedule_run_id,
            },
        })
        db = SessionLocal()
        try:
            write_audit_log(
                db,
                action="Genereate schedule completed",
                school_id=school_id,
                user_id=user_id,
                entity_type="ScheduleRun",
                entity_id=schedule_run_id,
                after={
                    "schedule_entries": len(schedule_entries),
                    "compliance_flags": len(compliance_flags),
                    "critical_flags": len(critical_flags),
                },
            )
        finally:
            db.close()

    except DBAPIError as error:
        SCHEDULE_JOBS[job_id].update({"status": "error", "error": str(error)})
    except Exception as error:  # catch-all so a bad thread doesn't die silently
        SCHEDULE_JOBS[job_id].update({"status": "error", "error": str(error)})


@app.post("/schedule/generate/start")
def start_schedule_generation(
    config: ScheduleGenerationConfig,
    request: Request,
    user: User = Depends(require_roles(*MANAGERS)),
):
    """Start generating a schedule in the background; poll /schedule/generate/status/{job_id}."""
    job_id = str(uuid.uuid4())
    SCHEDULE_JOBS[job_id] = {
        "status": "queued", "current_stage": -1, "stage_name": None,
        "percent": 0, "result": None, "error": None,
        "_school_id": str(user.school_id),  # never returned to clients
    }

    db = SessionLocal()
    try:
        write_audit_log(
            db,
            action="Generate Schedule Start",
            school_id=user.school_id,
            user_id=user.id,
            entity_type="ScheduleRun",
            after={"job_id": job_id},
            ip_address=request.client.host if request.client else None,
        )
    finally:
        db.close()

    thread = threading.Thread(
        target=_run_schedule_job,
        args=(job_id, config, user.id, user.school_id),
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id}


@app.get("/schedule/generate/status/{job_id}")
def get_schedule_generation_status(job_id: str, user: User = Depends(require_roles(*MANAGERS))):
    """Progress of a generation job started by the caller's school."""
    job = SCHEDULE_JOBS.get(job_id)
    if not job or job.get("_school_id") != str(user.school_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {k: v for k, v in job.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Compliance flags
# ---------------------------------------------------------------------------

@app.get("/compliance-flags")
def list_compliance_flags(user: User = Depends(require_roles(*MANAGERS))):
    """The school's open compliance flags."""
    db = SessionLocal()

    try:
        flags = (
            db.query(ComplianceFlag)
            .filter(ComplianceFlag.school_id == user.school_id, ComplianceFlag.status == "open")
            .all()
        )

        # get student names in one go
        student_ids = [f.student_id for f in flags if f.student_id]

        students = db.query(Student).filter(Student.id.in_(student_ids)).all()

        student_map = {str(s.id): f"{s.first_name} {s.last_name}" for s in students}

        # get schedule runs in one go, so people can tell which run a flag came from
        run_ids = [f.run_id for f in flags if f.run_id]

        runs = db.query(ScheduleRun).filter(ScheduleRun.id.in_(run_ids)).all()

        run_map = {
            str(r.id): {
                "name": r.name,
                "status": r.status,
                "school_year": r.school_year,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in runs
        }

        return [
            {
                "id": str(f.id),
                "run_id": str(f.run_id),
                "run": run_map.get(str(f.run_id)),
                "student_name": student_map.get(str(f.student_id), "Unknown Student"),
                "flag_type": f.flag_type,
                "severity": f.severity,
                "title": f.title,
                "description": f.description,
                "affected_period": f.affected_period,
                "status": f.status,
            }
            for f in flags
        ]

    finally:
        db.close()

@app.post("/run-compliance-check")
def run_compliance_check(user: User = Depends(require_roles(*MANAGERS))):
    """
    Re-runs every compliance check against the LATEST generated schedule
    (only that run's entries, judged by the master schedule that run was
    built with) plus overall staffing levels, and PERSISTS the resulting
    flags so they show up in /compliance-flags and the dashboard feed.
    Does not touch schedule_entries -- only reads them.
    """
    try:
        students = get_students(school_id=user.school_id)
        staff = get_staff(school_id=user.school_id)
        students_by_id = {s["id"]: s for s in students if s.get("id")}

        db = SessionLocal()
        try:
            run = _latest_full_run(db, user.school_id)
            if not run:
                raise HTTPException(status_code=409, detail="No generated schedule to check yet.")
            period_config = _run_period_config(run)
            entries = _run_entries_as_dicts(db, run.id)
        finally:
            db.close()

        try:
            flags = run_all_compliance_checks(
                entries=entries,
                students_by_id=students_by_id,
                period_config=period_config,
                students=students,
                staff_members=staff,
            )
        except ValueError as error:  # e.g. entries saved before the migration
            raise HTTPException(status_code=409, detail=str(error))

        critical_count = sum(1 for f in flags if f.get("severity") == "critical")
        warning_count = sum(1 for f in flags if f.get("severity") == "warning")

        school_year = os.getenv("SCHOOL_YEAR", "2026-2027")

        schedule_run_id = create_schedule_run(
            school_year=school_year,
            name="Compliance Check",
            school_id=user.school_id,
            summary={
                "compliance_check_passed": critical_count == 0,
                "open_critical_flags": critical_count,
                "status": "compliance_check",
                "checked_run_id": str(run.id),
            },
        )

        create_compliance_flags(flags, run_id=schedule_run_id)

        return {
            "success": True,
            "flags": flags,
            "summary": {
                "total_flags": len(flags),
                "critical": critical_count,
                "warnings": warning_count,
            },
            "checked_run_id": str(run.id),
            "schedule_run_id": schedule_run_id,
        }

    except DBAPIError as error:
        raise HTTPException(status_code=500, detail=str(error))


@app.patch("/compliance-flags/{flag_id}/resolve")
def resolve_compliance_flag(
    flag_id: UUID,
    request: Request,
    user: User = Depends(require_roles(*MANAGERS)),
):
    """Mark a compliance flag as resolved."""
    db = SessionLocal()
    try:
        flag = (
            db.query(ComplianceFlag)
            .filter(ComplianceFlag.id == flag_id, ComplianceFlag.school_id == user.school_id)
            .first()
        )
        if not flag:
            raise HTTPException(status_code=404, detail="Compliance flag not found")

        before_status = flag.status
        flag.status = "resolved"
        flag.resolved_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(flag)

        write_audit_log(
            db,
            action="Resolve Compliance Flag",
            school_id=user.school_id,
            user_id=user.id,
            entity_type="ComplianceFlag",
            entity_id=flag.id,
            before={"status": before_status},
            after={"status": flag.status, "resolved_at": flag.resolved_at.isoformat()},
            ip_address=request.client.host if request.client else None,
        )

        return {
            "id": str(flag.id),
            "status": flag.status,
            "resolved_at": flag.resolved_at.isoformat() if flag.resolved_at else None,
        }
    finally:
        db.close()
# ---------------------------------------------------------------------------
# FLEX groups
# ---------------------------------------------------------------------------

@app.get("/flex_groups")
def list_flex_groups(user: User = Depends(require_roles(*ALL_STAFF))):
    """Teachers and aides see only the FLEX groups they run."""
    db = SessionLocal()

    try:
        query = (
            db.query(FlexGroup, Student)
            .join(FlexGroupStudent, FlexGroupStudent.flex_group_id == FlexGroup.id)
            .join(Student, Student.id == FlexGroupStudent.student_id)
            .filter(FlexGroup.school_id == user.school_id)
        )
        if user.role not in MANAGERS:
            if not user.staff_id:
                return []
            query = query.filter(FlexGroup.staff_id == user.staff_id)
        rows = (
            query
        )

        return [
            {
                "id": str(fg.id),
                "name": fg.name,
                "tier": fg.tier,
                "focus_area": fg.focus_area,
                "staff_name": fg.teacher_name,
                "day_of_week": fg.day_of_week,
                "period": fg.period,
                "period_label": fg.period_label,
                "start_minute": fg.start_minute,
                "end_minute": fg.end_minute,
                "time_range": (
                    format_range(fg.start_minute, fg.end_minute)
                    if fg.start_minute is not None and fg.end_minute is not None else None
                ),
                "student_id": str(s.id),
                "student_name": f"{s.first_name} {s.last_name}".strip(),
            }
            for fg, s in rows
        ]

    finally:
        db.close()
# ---------------------------------------------------------------------------
# AUDIT LOG
# ---------------------------------------------------------------------------

@app.get("/audit-logs")
def list_audit_logs(
    action: str | None = None,
    entity_type: str | None = None,
    limit: int = 100,
    user: User = Depends(get_current_user),
):
    """Admin only: recent audit-log entries, optionally filtered by action or entity type."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Not allowed")

    db = SessionLocal()
    try:
        query = (
            db.query(AuditLog, User)
            .outerjoin(User, User.id == AuditLog.user_id)
            .filter(AuditLog.school_id == user.school_id)
        )

        if action:
            query = query.filter(AuditLog.action == action)
        if entity_type:
            query = query.filter(AuditLog.entity_type == entity_type)

        rows = (
            query.order_by(AuditLog.created_at.desc())
            .limit(min(limit, 500))
            .all()
        )

        return [
            {
                "id": str(log.id),
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": str(log.entity_id) if log.entity_id else None,
                "user_id": str(log.user_id) if log.user_id else None,
                "user_email": u.email if u else None,
                "user_name": u.full_name if u else None,
                "before_json": log.before_json,
                "after_json": log.after_json,
                "ip_address": log.ip_address,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log, u in rows
        ]
    finally:
        db.close()