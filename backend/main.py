import os


from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi import HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from dmscheduler_db import SessionLocal
from dmscheduler_db import ScheduleEntry, Student, StaffMember, ComplianceFlag, FlexGroup, ScheduleRun, FlexGroupStudent

from database_service import (
    DBAPIError,
    DBConfigError,
    create_compliance_flags,
    create_schedule_entries,
    create_schedule_run,
    get_staff,
    get_students,
    create_flex_groups,
    delete_entity_many,
    create_flex_group_students,
)
from scheduler import schedule_iep_services_first

load_dotenv()

app = FastAPI(title="CompliWise Scheduler Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from sqlalchemy.orm import Session
from pydantic import BaseModel
from dmscheduler_db import SessionLocal

class StudentUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    grade: int | None = None
    homeroom: str | None = None
    has_iep: bool | None = None
    mtss_tier: int | None = None
    
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

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

@app.get("/students")
def list_students(
    search: str | None = None,
    grade: int | None = None,
    iep: bool | None = None,
    mtss_tier: int | None = None
):

    try:

        students = get_students(
            search=search,
            grade=grade,
            iep=iep,
            mtss_tier=mtss_tier
        )

        return {
            "students": students,
            "count": len(students)
        }


    except (DBConfigError, DBAPIError) as error:

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )
@app.get("/staff")
def list_staff():
    try:
        staff = get_staff()
        return {"staff": staff, "count": len(staff)}
    except (DBConfigError, DBAPIError) as error:
        raise HTTPException(status_code=500, detail=str(error))

@app.get("/schedule")
def list_schedule_entries():
    db = SessionLocal()

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
            "staff_name": (
                f"{staff.first_name} {staff.last_name}"
                if staff else entry.teacher_name
            ),

            "day_of_week": entry.day_of_week,
            "period": entry.period,
            "subject": entry.subject,
            "service_type": entry.service_type,
            "is_pullout": entry.is_pullout,
            "is_flex_period": entry.is_flex_period,
        }
        for entry, student, staff in results
    ]
@app.get("/compliance-flags")
def list_compliance_flags():
    db = SessionLocal()

    flags = (
        db.query(ComplianceFlag)
        .all()
    )

    # get student names in one go
    student_ids = [f.student_id for f in flags if f.student_id]

    students = (
        db.query(Student)
        .filter(Student.id.in_(student_ids))
        .all()
    )

    student_map = {
        str(s.id): f"{s.first_name} {s.last_name}"
        for s in students
    }

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


@app.get("/students/{student_id}/schedule")
def get_student_schedule(student_id: str):

    db = SessionLocal()

    entries = (
        db.query(ScheduleEntry)
        .filter(
            ScheduleEntry.student_external_id == student_id
        )
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



@app.get("/preview-priority")
def preview_priority():
    """
    Calculates student scheduling priority order.
    Does not save schedule changes.
    """
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
    
from dmscheduler_db import ScheduleEntry, SessionLocal

@app.put("/schedule/{entry_id}")
def update_schedule_entry(entry_id: str, payload: dict):
    db = SessionLocal()

    try:
        entry = db.query(ScheduleEntry).filter(
            ScheduleEntry.id == entry_id
        ).first()

        if not entry:
            raise HTTPException(status_code=404, detail="Not found")

        for key, value in payload.items():
            setattr(entry, key, value)

        db.commit()
        db.refresh(entry)

        return {"success": True, "id": str(entry.id)}

    finally:
        db.close()

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

@app.post("/generate-schedule")
def generate_schedule_preview():
    """
    Generates schedule payloads from Base44 data but does NOT save them.
    Use this first so you can inspect the output safely.
    """
    try:
        students = get_students()
        staff = get_staff()
        school_year = os.getenv("SCHOOL_YEAR", "2026-2027")

        return schedule_iep_services_first(
            students=students,
            staff_members=staff,
            school_year=school_year,
        )

    except (DBConfigError, DBAPIError) as error:
        raise HTTPException(status_code=500, detail=str(error))

@app.post("/save-schedule")
def save_schedule():
    """
    Generates schedules and stores them in the scheduler database.
    """

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

        critical_flags = [
            f for f in compliance_flags
            if f.get("severity") == "critical"
            ]
        schedule_run_id = create_schedule_run(
            school_year=school_year,
            name="Full School Schedule",
            summary={
                "compliance_check_passed": len(critical_flags) == 0,
                "open_critical_flags": len(critical_flags),
                "status": "draft",
                "summary": result["summary"],
            }
        )

        saved_entries = create_schedule_entries(schedule_entries, run_id=schedule_run_id)
        saved_flags = create_compliance_flags(compliance_flags, run_id=schedule_run_id)
        saved_flex_groups = create_flex_groups(flex_groups, run_id=schedule_run_id)
        saved_flex_group_students = create_flex_group_students(flex_group_students, run_id=schedule_run_id)

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
    """
    Deletes generated schedule output records.
    Student and staff records remain unchanged.
    """

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
            }
        }

    except (DBConfigError, DBAPIError) as error:
        raise HTTPException(status_code=500, detail=str(error))