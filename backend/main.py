"""CompliWise Scheduler Engine API."""
from __future__ import annotations

from typing import Any, Optional
import os
import setup as setup_module
import uuid
import threading
import shutil
import tempfile

from pathlib import Path
from fastapi import File, UploadFile, Request
from import_csv_data import import_student_services, import_students, import_staff
from uuid import UUID
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
from auth_utils import hash_password, verify_password
from compliance import run_all_compliance_checks, check_staff_coverage
from database_service import (
    DBAPIError,
    DBConfigError,
    create_compliance_flags,
    create_flex_group_students,
    create_flex_groups,
    create_schedule_entries,
    create_schedule_run,
    delete_entity_many,
    get_staff,
    get_students,
)
from dmscheduler_db import (
    ComplianceFlag,
    FlexGroup,
    FlexGroupStudent,
    ScheduleEntry,
    SessionLocal,
    School,
    StaffMember,
    ScheduleRun,
    Student,
    StudentService,
    User,
    AuditLog,
)
from datetime import datetime, timezone
from scheduler import DAYS, schedule_iep_services_first, suggest_service_slots
from scheduling_core import PeriodConfig, format_range
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
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")

    user = db.query(User).filter(User.id == UUID(user_id)).first()
    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Session no longer valid")

    return user


# ---------------------------------------------------------------------------
# Pydantic models
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
    school_id: str
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

FULL_SCHEDULE_RUN_NAME = "Full School Schedule"
    
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
    return {
        "message": "CompliWise Scheduler Engine is running",
        "endpoints": [
            "/students",
            "/staff",
            "/schedule",
            "/generate-schedule",
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


def _latest_full_run(db: Session) -> ScheduleRun | None:
    return (
        db.query(ScheduleRun)
        .filter(ScheduleRun.name == FULL_SCHEDULE_RUN_NAME)
        .order_by(ScheduleRun.created_at.desc())
        .first()
    )


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

@app.get("/setup/status")
def get_setup_status(db: Session = Depends(get_db)):
    connectable = setup_module.db_connectable(db)
    return {
        "database_connectable": connectable,
        "setup_complete": connectable and setup_module.admin_exists(db),
    }


@app.post("/setup/initialize")
def initialize_setup(payload: SetupInitializeRequest, db: Session = Depends(get_db)):
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

    return {
        "school_id": str(school.id),
        "school_name": school.name,
        "admin_id": str(admin.id),
        "admin_email": admin.email,
    }


@app.post("/setup/import-csv")
def setup_import_csv(
    students_file: UploadFile | None = File(None),
    staff_file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    if not setup_module.admin_exists(db):
        raise HTTPException(status_code=403, detail="Complete admin setup before importing data.")

    school = db.query(School).first()
    if not school:
        raise HTTPException(status_code=400, detail="No school found — run /setup/initialize first.")

    result = {"students_imported": 0, "staff_imported": 0}

    with tempfile.TemporaryDirectory() as tmpdir:
        if students_file is not None:
            students_path = Path(tmpdir) / "students.csv"
            with students_path.open("wb") as f:
                shutil.copyfileobj(students_file.file, f)
            result["students_imported"] = import_students(db, school, csv_path=students_path)

            service_result = import_student_services(db, school, csv_path=students_path)
            result["services_imported"] = service_result["services_created"]
        if staff_file is not None:
            staff_path = Path(tmpdir) / "staff.csv"
            with staff_path.open("wb") as f:
                shutil.copyfileobj(staff_file.file, f)
            result["staff_imported"] = import_staff(db, school, csv_path=staff_path)

    return result

@app.get("/me")
def get_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
    
# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

@app.post("/admin/users")
def add_user(
    payload: CreateUserRequest,
    admin: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if admin.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can add users")

    # Prevent duplicate accounts
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="A user with this email already exists")

    # If linking to a staff member, make sure it exists and isn't already claimed
    if payload.staff_id:
        staff = db.query(StaffMember).filter(StaffMember.id == payload.staff_id).first()
        if not staff:
            raise HTTPException(status_code=404, detail="Staff member not found")

        already_linked = db.query(User).filter(User.staff_id == payload.staff_id).first()
        if already_linked:
            raise HTTPException(status_code=400, detail="This staff member already has a linked account")

    new_user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),  # use whatever your auth module uses
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
    user=Depends(get_current_user),
):
    try:
        students = get_students(search=search, grade=grade, iep=iep, mtss_tier=mtss_tier)
        return {"students": students, "count": len(students)}

    except (DBConfigError, DBAPIError) as error:
        raise HTTPException(status_code=500, detail=str(error))


@app.put("/students/{student_id}")
def update_student(student_id: str, student: StudentUpdate):
    db = SessionLocal()

    try:
        db_student = db.query(Student).filter(Student.id == student_id).first()

        if not db_student:
            raise HTTPException(status_code=404, detail="Student not found")

        # exclude_unset: only fields the client actually sent. Plain
        # .dict() includes every unsent field as None and would wipe
        # grade/homeroom whenever someone edits just a name.
        for key, value in student.dict(exclude_unset=True).items():
            if key in ALLOWED_STUDENT_FIELDS:
                setattr(db_student, key, value)

        db.commit()
        db.refresh(db_student)

        return {"student": db_student}

    finally:
        db.close()


@app.get("/students/{student_id}/schedule")
def get_student_schedule(student_id: str):
    db = SessionLocal()

    try:
        entries = (
            db.query(ScheduleEntry)
            .filter(ScheduleEntry.student_external_id == student_id)
            .all()
        )

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
        key=lambda c: (DAYS.index(c["day_of_week"]), c["start_minute"]),
    )


# ---------------------------------------------------------------------------
# Pydantic models — Student Services
# ---------------------------------------------------------------------------

class StudentServiceCreate(BaseModel):
    service_type: str
    subject_area: str | None = None
    minutes_per_week: int
    sessions_per_week: int | None = None
    is_pullout: bool = True
    preferred_provider_id: str | None = None
    notes: str | None = None

class StudentServiceUpdate(BaseModel):
    service_type: str | None = None
    subject_area: str | None = None
    minutes_per_week: int | None = None
    sessions_per_week: int | None = None
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
    user: User = Depends(get_current_user),
):
    db = SessionLocal()
    try:
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        if payload.preferred_provider_id:
            provider = db.query(StaffMember).filter(
                StaffMember.id == payload.preferred_provider_id
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
def list_student_services(student_id: str, user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        student = db.query(Student).filter(Student.id == student_id).first()
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
    user: User = Depends(get_current_user),
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
            .filter(StudentService.id == service_uuid, StudentService.student_id == student_uuid)
            .first()
        )
        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        run = _latest_full_run(db)
        if not run:
            raise HTTPException(status_code=409, detail="Generate a schedule first.")
        period_config = _run_period_config(run)
        entries = _run_entries_as_dicts(db, run.id)
    finally:
        db.close()

    try:
        students = get_students()
        staff = get_staff()
    except (DBConfigError, DBAPIError) as error:
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
    user: User = Depends(get_current_user),
):
    db = SessionLocal()
    try:
        service = (
            db.query(StudentService)
            .filter(StudentService.id == service_id, StudentService.student_id == student_id)
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
    user: User = Depends(get_current_user),
):
    db = SessionLocal()
    try:
        service = (
            db.query(StudentService)
            .filter(StudentService.id == service_id, StudentService.student_id == student_id)
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
def list_staff():
    try:
        staff = get_staff()
        return {"staff": staff, "count": len(staff)}

    except (DBConfigError, DBAPIError) as error:
        raise HTTPException(status_code=500, detail=str(error))

@app.post("/staff")
def create_staff(staff: StaffCreate, db: Session = Depends(get_db)):
    try:
        db_staff = StaffMember(**staff.dict())
        db.add(db_staff)
        db.commit()
        db.refresh(db_staff)

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

    except Exception as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error))

@app.put("/staff/{staff_id}")
def update_staff(staff_id: str, payload: StaffUpdate):
    db = SessionLocal()
    try:
        staff = db.query(StaffMember).filter(StaffMember.id == staff_id).first()
        if not staff:
            raise HTTPException(status_code=404, detail="Staff not found")

        # exclude_unset: toggling one certification must not null out
        # grade (a known root cause of bad staff matching).
        for field, value in payload.dict(exclude_unset=True).items():
            if field in ALLOWED_STAFF_FIELDS:
                setattr(staff, field, value)

        db.commit()
        db.refresh(staff)

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

@app.get("/my-schedule")
def my_schedule(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Not allowed")

    if not user.staff_id:
        raise HTTPException(status_code=400, detail="Teacher account is not linked")

    entries = db.query(ScheduleEntry).filter(ScheduleEntry.staff_id == user.staff_id).all()

    return [
        {
            "id": str(e.id),
            "day_of_week": e.day_of_week,
            "period": e.period,
            "period_label": e.period_label,
            "subject": e.subject,
            "student_name": e.student_name,
            "service_type": e.service_type,
            "is_pullout": e.is_pullout,
            "is_flex_period": e.is_flex_period,
            **_entry_time_fields(e),
        }
        for e in entries
    ]


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

@app.get("/schedule")
def list_schedule_entries(run_id: str | None = None):
    db = SessionLocal()

    try:
        query = (
            db.query(ScheduleEntry, Student, StaffMember)
            .join(Student, ScheduleEntry.student_id == Student.id)
            .outerjoin(StaffMember, ScheduleEntry.staff_id == StaffMember.id)

        )
        if run_id:
            query = query.filter(ScheduleEntry.run_id == run_id)

        results = query.all()

        return [
            {
                "id": str(entry.id),
                "run_id": str(entry.run_id),
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
            for entry, student, staff in results
        ]
    finally:
        db.close()


@app.put("/schedule/{entry_id}")
def update_schedule_entry(
    entry_id: str,
    payload: dict,
    request: Request,
    user: User = Depends(get_current_user),
):
    unknown = set(payload) - ALLOWED_SCHEDULE_ENTRY_FIELDS
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"These fields can't be edited: {sorted(unknown)}",
        )

    db = SessionLocal()
    try:
        entry = db.query(ScheduleEntry).filter(ScheduleEntry.id == entry_id).first()
        if not entry:
            raise HTTPException(status_code=404, detail="Not found")

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
                staff = db.query(StaffMember).filter(StaffMember.id == staff_uuid).first()
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


@app.get("/preview-priority")
def preview_priority():
    """Calculate student scheduling priority order. Does not save schedule changes."""
    try:
        students = get_students()
        staff = get_staff()
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

    except (DBConfigError, DBAPIError) as error:
        raise HTTPException(status_code=500, detail=str(error))


@app.get("/schedule/config-defaults")
def get_schedule_config_defaults(user: User = Depends(get_current_user)):
    """
    Prefill for the Generate Schedule modal: the master schedule and
    rules from the most recent full run, so the principal doesn't
    re-enter them every time -- or the built-in defaults if there's no
    usable run yet.
    """
    db = SessionLocal()
    try:
        run = _latest_full_run(db)
        payload = (run.summary_json or {}).get("period_config") if run else None
    finally:
        db.close()

    if payload:
        try:
            PeriodConfig.from_config(payload)  # still valid under today's rules?
            return {"source": "last_run", "run_id": str(run.id), "config": payload}
        except ValueError as error:
            return {
                "source": "defaults",
                "warning": f"The last run's master schedule couldn't be loaded ({error}); showing defaults.",
                "config": PeriodConfig().to_config_payload(),
            }

    return {"source": "defaults", "config": PeriodConfig().to_config_payload()}


@app.get("/schedule-runs")
def list_schedule_runs(user: User = Depends(get_current_user)):
    if user.role not in ("admin", "principal"):
        raise HTTPException(status_code=403, detail="Not allowed")

    db = SessionLocal()
    try:
        runs = db.query(ScheduleRun).order_by(ScheduleRun.created_at.desc()).all()
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
def get_schedule_run(run_id: str, user: User = Depends(get_current_user)):
    if user.role not in ("admin", "principal"):
        raise HTTPException(status_code=403, detail="Not allowed")

    db = SessionLocal()
    try:
        run = db.query(ScheduleRun).filter(ScheduleRun.id == run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Schedule run not found")

        entries = (
            db.query(ScheduleEntry, Student, StaffMember)
            .join(Student, ScheduleEntry.student_id == Student.id)
            .outerjoin(StaffMember, ScheduleEntry.staff_id == StaffMember.id)
            .filter(ScheduleEntry.run_id == run_id)
            .all()
        )

        flags = db.query(ComplianceFlag).filter(ComplianceFlag.run_id == run_id).all()

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


@app.post("/save-schedule")
def save_schedule(config: ScheduleGenerationConfig):
    try:
        period_config = PeriodConfig.from_config(config)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    try:
        students = get_students()
        staff = get_staff()
        school_year = os.getenv("SCHOOL_YEAR", "2026-2027")

        result = schedule_iep_services_first(
            students=students,
            staff_members=staff,
            school_year=school_year,
            period_config=period_config,
        )

        schedule_entries = result["schedule_entries"]
        compliance_flags = result["compliance_flags"]
        flex_groups = result["flex_groups"]
        flex_group_students = result["flex_group_students"]

        critical_flags = [f for f in compliance_flags if f.get("severity") == "critical"]

        schedule_run_id = create_schedule_run(
            school_year=school_year,
            name=FULL_SCHEDULE_RUN_NAME,
            summary=_run_summary(result, period_config, critical_flags),
        )

        create_schedule_entries(schedule_entries, run_id=schedule_run_id)
        create_compliance_flags(compliance_flags, run_id=schedule_run_id)
        create_flex_groups(flex_groups, run_id=schedule_run_id)
        create_flex_group_students(flex_group_students, run_id=schedule_run_id)

        return {
            "success": True,
            "summary": result["summary"],
            "saved": {
                "schedule_entries": len(schedule_entries),
                "compliance_flags": len(compliance_flags),
                "flex_groups": len(flex_groups),
                "flex_group_students": len(flex_group_students),
                "schedule_runs": 1,
            },
            "schedule_run_id": schedule_run_id,
        }

    except (DBConfigError, DBAPIError) as error:
        raise HTTPException(status_code=500, detail=str(error))


@app.post("/reset-generated-schedules")
def reset_generated_schedules():
    """Delete generated schedule output records. Student and staff records remain unchanged."""
    try:
        deleted_schedule_entries = delete_entity_many("ScheduleEntry", {})
        deleted_schedule_runs = delete_entity_many("ScheduleRun", {})
        deleted_compliance_flags = delete_entity_many("ComplianceFlag", {})
        deleted_flex_groups = delete_entity_many("FlexGroup", {})
        deleted_flex_group_students = delete_entity_many("FlexGroupStudent", {})

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

    except (DBConfigError, DBAPIError) as error:
        raise HTTPException(status_code=500, detail=str(error))

def _run_schedule_job(job_id: str, config: ScheduleGenerationConfig, user_id=None, school_id=None):
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
        
        students = get_students()
        staff = get_staff()
        school_year = os.getenv("SCHOOL_YEAR", "2026-2027")

        result = schedule_iep_services_first(
            students=students,
            staff_members=staff,
            school_year=school_year,
            period_config=period_config,
            progress_callback=progress,
        )
        schedule_entries = result["schedule_entries"]
        compliance_flags = result["compliance_flags"]
        flex_groups = result["flex_groups"]
        flex_group_students = result["flex_group_students"]

        critical_flags = [f for f in compliance_flags if f.get("severity") == "critical"]

        schedule_run_id = create_schedule_run(
            school_year=school_year,
            name=FULL_SCHEDULE_RUN_NAME,
            summary=_run_summary(result, period_config, critical_flags),
        )

        progress(6, "Saving schedule to database")
        create_schedule_entries(schedule_entries, run_id=schedule_run_id)
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

    except (DBConfigError, DBAPIError) as error:
        SCHEDULE_JOBS[job_id].update({"status": "error", "error": str(error)})
    except Exception as error:  # catch-all so a bad thread doesn't die silently
        SCHEDULE_JOBS[job_id].update({"status": "error", "error": str(error)})


@app.post("/schedule/generate/start")
def start_schedule_generation(
    config: ScheduleGenerationConfig,
    request: Request,
    user: User = Depends(get_current_user),
):
    job_id = str(uuid.uuid4())
    SCHEDULE_JOBS[job_id] = {
        "status": "queued", "current_stage": -1, "stage_name": None,
        "percent": 0, "result": None, "error": None,
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
def get_schedule_generation_status(job_id: str, user: User = Depends(get_current_user)):
    job = SCHEDULE_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
# ---------------------------------------------------------------------------
# Compliance flags
# ---------------------------------------------------------------------------

@app.get("/compliance-flags")
def list_compliance_flags():
    db = SessionLocal()

    try:
        flags = db.query(ComplianceFlag).filter(ComplianceFlag.status == "open").all()

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
def run_compliance_check(user: User = Depends(get_current_user)):
    """
    Re-runs every compliance check against the LATEST generated schedule
    (only that run's entries, judged by the master schedule that run was
    built with) plus overall staffing levels, and PERSISTS the resulting
    flags so they show up in /compliance-flags and the dashboard feed.
    Does not touch schedule_entries -- only reads them.
    """
    try:
        students = get_students()
        staff = get_staff()
        students_by_id = {s["id"]: s for s in students if s.get("id")}

        db = SessionLocal()
        try:
            run = _latest_full_run(db)
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

    except (DBConfigError, DBAPIError) as error:
        raise HTTPException(status_code=500, detail=str(error))
    

@app.patch("/compliance-flags/{flag_id}/resolve")
def resolve_compliance_flag(
    flag_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
):
    db = SessionLocal()
    try:
        flag = db.query(ComplianceFlag).filter(ComplianceFlag.id == flag_id).first()
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
def list_flex_groups():
    db = SessionLocal()

    try:
        rows = (
            db.query(FlexGroup, Student)
            .join(FlexGroupStudent, FlexGroupStudent.flex_group_id == FlexGroup.id)
            .join(Student, Student.id == FlexGroupStudent.student_id)
            .all()
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
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Not allowed")

    db = SessionLocal()
    try:
        query = db.query(AuditLog, User).outerjoin(User, User.id == AuditLog.user_id)

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