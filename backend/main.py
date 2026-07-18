"""CompliWise Scheduler Engine API."""
from __future__ import annotations
import os
from uuid import UUID
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
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
    StaffMember,
    Student,
    User,
)
from datetime import datetime, timezone
from scheduler import DAYS, schedule_iep_services_first
from scheduling_core import PeriodConfig
# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

load_dotenv()

app = FastAPI(title="CompliWise Scheduler Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# NOTE: single-process, in-memory "session" placeholder. Fine for local/dev
# use, but should be replaced with real session/token auth before this goes
# anywhere multi-user or multi-worker.
CURRENT_USER = None


# ---------------------------------------------------------------------------
# Shared dependencies / helpers
# ---------------------------------------------------------------------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def get_current_user(db: Session = Depends(get_db)) -> User:
    if CURRENT_USER is None:
        raise HTTPException(status_code=401, detail="Not logged in")

    user = db.query(User).filter(User.id == CURRENT_USER).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str
    password: str


class StudentUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    grade: int | None = None
    homeroom: str | None = None
    has_iep: bool | None = None
    mtss_tier: int | None = None

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


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    global CURRENT_USER

    user = db.query(User).filter(User.email == data.email).first()

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    CURRENT_USER = user.id

    return {
        "user_id": str(user.id),
        "role": user.role,
        "staff_id": str(user.staff_id) if user.staff_id else None,
    }


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

        for key, value in student.dict().items():
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
                "subject": e.subject,
                "teacher": e.teacher_name,
                "service_type": e.service_type,
                "is_pullout": e.is_pullout,
                "is_flex_period": e.is_flex_period,
            }
            for e in entries
        ]

    finally:
        db.close()


@app.get("/me/students")
def get_my_students(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Returns the teacher's classes grouped by day/period, so it answers
    "who's in my class this period" rather than just a flat student list.
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

    # Group entries into classes keyed by (day, period, subject, service_type)
    # so students who share the same slot/class show up together, the same
    # way staff_schedule is built during generation.
    classes: dict = {}

    for entry, student in rows:
        key = (entry.day_of_week, entry.period, entry.subject, entry.service_type)

        if key not in classes:
            classes[key] = {
                "day_of_week": entry.day_of_week,
                "period": entry.period,
                "subject": entry.subject,
                "service_type": entry.service_type,
                "is_pullout": entry.is_pullout,
                "is_flex_period": entry.is_flex_period,
                "students": [],
            }

        classes[key]["students"].append({
            "id": str(student.id),
            "first_name": student.first_name,
            "last_name": student.last_name,
            "grade": student.grade,
            "homeroom": student.homeroom,
            "has_iep": student.has_iep,
            "mtss_tier": student.mtss_tier,
        })

    return sorted(
        classes.values(),
        key=lambda c: (DAYS.index(c["day_of_week"]), c["period"]),
    )


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
            "subject": e.subject,
            "student_name": e.student_name,
            "service_type": e.service_type,
            "is_pullout": e.is_pullout,
            "is_flex_period": e.is_flex_period,
        }
        for e in entries
    ]


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

@app.get("/schedule")
def list_schedule_entries():
    db = SessionLocal()

    try:
        results = (
            db.query(ScheduleEntry, Student, StaffMember)
            .join(Student, ScheduleEntry.student_id == Student.id)
            .outerjoin(StaffMember, ScheduleEntry.staff_id == StaffMember.id)
            .all()
        )

        return [
            {
                "id": str(entry.id),
                "student_id": str(student.id),
                "student_name": f"{student.first_name} {student.last_name}",
                "grade": student.grade,
                "staff_id": str(staff.id) if staff else None,
                "staff_name": (f"{staff.first_name} {staff.last_name}" if staff else entry.teacher_name),
                "day_of_week": entry.day_of_week,
                "period": entry.period,
                "subject": entry.subject,
                "service_type": entry.service_type,
                "is_pullout": entry.is_pullout,
                "is_flex_period": entry.is_flex_period,
            }
            for entry, student, staff in results
        ]

    finally:
        db.close()


@app.put("/schedule/{entry_id}")
def update_schedule_entry(entry_id: str, payload: dict):
    db = SessionLocal()

    try:
        entry = db.query(ScheduleEntry).filter(ScheduleEntry.id == entry_id).first()

        if not entry:
            raise HTTPException(status_code=404, detail="Not found")

        for key, value in payload.items():
            setattr(entry, key, value)

        db.commit()
        db.refresh(entry)

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


@app.post("/save-schedule")
def save_schedule():
    """Generate schedules and store them in the scheduler database."""
    try:
        students = get_students()
        staff = get_staff()
        school_year = os.getenv("SCHOOL_YEAR", "2026-2027")

        result = schedule_iep_services_first(
            students=students,
            staff_members=staff,
            school_year=school_year,
        )

        schedule_entries = result["schedule_entries"]
        compliance_flags = result["compliance_flags"]
        flex_groups = result["flex_groups"]
        flex_group_students = result["flex_group_students"]

        critical_flags = [f for f in compliance_flags if f.get("severity") == "critical"]

        schedule_run_id = create_schedule_run(
            school_year=school_year,
            name="Full School Schedule",
            summary={
                "compliance_check_passed": len(critical_flags) == 0,
                "open_critical_flags": len(critical_flags),
                "status": "draft",
                "summary": result["summary"],
            },
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

        return [
            {
                "id": str(f.id),
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
    Runs every compliance check against the CURRENTLY SAVED schedule
    plus overall staffing levels, and PERSISTS the resulting flags
    to the database so they show up in /compliance-flags and the
    dashboard feed. Does not touch schedule_entries -- only reads them.
    """
    try:
        students = get_students()
        staff = get_staff()
        period_config = PeriodConfig()

        students_by_id = {s["id"]: s for s in students if s.get("id")}

        db = SessionLocal()
        try:
            saved_entries = db.query(ScheduleEntry).all()
        finally:
            db.close()

        entries = [
            {
                "student_id": str(e.student_id),
                "day_of_week": e.day_of_week,
                "period": e.period,
                "subject": e.subject,
                "teacher": e.teacher_name,
                "service_type": e.service_type,
                "is_pullout": e.is_pullout,
                "is_flex_period": e.is_flex_period,
            }
            for e in saved_entries
        ]

        staff_schedule: dict = {}
        for entry in entries:
            teacher = entry["teacher"]
            if not teacher:
                continue
            student = students_by_id.get(entry["student_id"], {})
            student_name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip()

            staff_schedule.setdefault(teacher, {}) \
                          .setdefault(entry["day_of_week"], {}) \
                          .setdefault(entry["period"], [])

            blocks = staff_schedule[teacher][entry["day_of_week"]][entry["period"]]
            block = next(
                (b for b in blocks if b["subject"] == entry["subject"] and b["service_type"] == entry["service_type"]),
                None,
            )
            if block is None:
                block = {
                    "subject": entry["subject"],
                    "service_type": entry["service_type"],
                    "is_pullout": entry["is_pullout"],
                    "students": [],
                }
                blocks.append(block)
            block["students"].append({"student_id": entry["student_id"], "student_name": student_name})

        flags = run_all_compliance_checks(
            entries=entries,
            staff_schedule=staff_schedule,
            students_by_id=students_by_id,
            period_config=period_config,
            students=students,
            staff_members=staff,
        )

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
            "schedule_run_id": schedule_run_id,
        }

    except (DBConfigError, DBAPIError) as error:
        raise HTTPException(status_code=500, detail=str(error))
    

@app.patch("/compliance-flags/{flag_id}/resolve")
def resolve_compliance_flag(flag_id: UUID):
    db = SessionLocal()

    try:
        flag = db.query(ComplianceFlag).filter(ComplianceFlag.id == flag_id).first()
        if not flag:
            raise HTTPException(status_code=404, detail="Compliance flag not found")

        flag.status = "resolved"
        flag.resolved_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(flag)

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
                "student_id": str(s.id),
                "student_name": f"{s.first_name} {s.last_name}".strip(),
            }
            for fg, s in rows
        ]

    finally:
        db.close()