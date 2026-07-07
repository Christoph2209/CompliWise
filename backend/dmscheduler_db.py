"""
dmscheduler_db.py

Database setup for CompliWise.

Creates tables for:
- Student
- StaffMember
- StudentService
- ScheduleRun
- ScheduleEntry
- ComplianceFlag
- FlexGroup
- FlexGroupStudent
- LegalRule
- ApprovalAction
- AuditLog
- User

Install:
    pip install sqlalchemy psycopg2-binary python-dotenv

.env example:
    DATABASE_URL=postgresql+psycopg2://username:password@localhost:5432/dmscheduler

Run:
    python dmscheduler_db.py
"""

import os
import uuid
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL, echo=False)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

class Base(DeclarativeBase):
    pass


def uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class School(Base):
    __tablename__ = "schools"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    district_name: Mapped[Optional[str]] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(100), default="America/New_York")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Student(Base):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)

    external_student_id: Mapped[Optional[str]] = mapped_column(String(100))

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)

    grade: Mapped[Optional[str]] = mapped_column(String(50))
    homeroom: Mapped[Optional[str]] = mapped_column(String(100))

    has_iep: Mapped[bool] = mapped_column(Boolean, default=False)
    enl_level: Mapped[Optional[str]] = mapped_column(String(50))
    enl_minutes_required: Mapped[int] = mapped_column(Integer, default=0)
    mtss_tier: Mapped[Optional[str]] = mapped_column(String(50))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    services = relationship("StudentService", back_populates="student")

    teachers = relationship(
        "StaffMember",
        secondary="student_teachers",
        back_populates="students"
    )
    
    __table_args__ = (
        Index("idx_students_school_grade", "school_id", "grade"),
        Index("idx_students_external_id", "school_id", "external_student_id"),
    )


class StaffMember(Base):
    __tablename__ = "staff_members"

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)

    external_staff_id: Mapped[Optional[str]] = mapped_column(String(100))

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)

    title: Mapped[Optional[str]] = mapped_column(String(100))
    grade: Mapped[Optional[str]] = mapped_column(String(50))
    homeroom: Mapped[Optional[str]] = mapped_column(String(100))
    room: Mapped[Optional[str]] = mapped_column(String(100))

    is_certified_sped: Mapped[bool] = mapped_column(Boolean, default=False)
    is_certified_enl: Mapped[bool] = mapped_column(Boolean, default=False)
    is_certified_slp: Mapped[bool] = mapped_column(Boolean, default=False)
    can_deliver_setss: Mapped[bool] = mapped_column(Boolean, default=False)

    max_students_per_group: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user = relationship(
        "User",
        back_populates="staff_member",
        uselist=False,
    )
    
    students = relationship(
        "Student",
        secondary="student_teachers",
        back_populates="teachers"
    )
    
    __table_args__ = (
        Index("idx_staff_school_title", "school_id", "title"),
        Index("idx_staff_school_grade", "school_id", "grade"),
    )
    
    


class StudentService(Base):
    """
    Normalized IEP / ESL / ENL / MTSS / related service requirements.
    This is better than keeping services only inside Student JSON.
    """

    __tablename__ = "student_services"

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )

    service_type: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_area: Mapped[Optional[str]] = mapped_column(String(100))

    minutes_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    sessions_per_week: Mapped[Optional[int]] = mapped_column(Integer)

    is_pullout: Mapped[bool] = mapped_column(Boolean, default=True)
    preferred_provider_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("staff_members.id")
    )

    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    student = relationship("Student", back_populates="services")

    __table_args__ = (
        Index("idx_student_services_student", "student_id"),
        Index("idx_student_services_type", "school_id", "service_type"),
    )


class ScheduleRun(Base):
    """
    One generated schedule version.

    Example:
        Run 1 = draft
        Run 2 = draft
        Run 3 = published
    """

    __tablename__ = "schedule_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)

    school_year: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255))

    status: Mapped[str] = mapped_column(String(50), default="draft")
    generated_by: Mapped[Optional[str]] = mapped_column(String(255))

    summary_json: Mapped[Optional[dict]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    entries = relationship("ScheduleEntry", back_populates="schedule_run")


class ScheduleEntry(Base):
    """
    Actual student schedule row.

    One row per:
        student + day + period + schedule_run
    """

    __tablename__ = "schedule_entries"

    id: Mapped[uuid.UUID] = uuid_pk()

    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schedule_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id"), nullable=False)
    staff_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("staff_members.id"))

    staff_member = relationship(
        "StaffMember"
    )

    student = relationship(
        "Student"
    )
    
    # Helpful denormalized display/search fields
    student_external_id: Mapped[Optional[str]] = mapped_column(String(100))
    student_name: Mapped[Optional[str]] = mapped_column(String(255))
    grade: Mapped[Optional[str]] = mapped_column(String(50))

    teacher_name: Mapped[Optional[str]] = mapped_column(String(255))

    day_of_week: Mapped[str] = mapped_column(String(20), nullable=False)
    period: Mapped[int] = mapped_column(Integer, nullable=False)

    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    room: Mapped[Optional[str]] = mapped_column(String(100))

    service_type: Mapped[Optional[str]] = mapped_column(String(100))
    is_pullout: Mapped[bool] = mapped_column(Boolean, default=False)
    is_flex_period: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[str] = mapped_column(String(50), default="draft")
    source: Mapped[str] = mapped_column(String(50), default="scheduler")


    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    schedule_run = relationship("ScheduleRun", back_populates="entries")
    
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "student_id",
            "day_of_week",
            "period",
            name="uq_student_one_entry_per_slot_per_run",
        ),
        Index("idx_schedule_student_slot", "run_id", "student_id", "day_of_week", "period"),
        Index("idx_schedule_teacher_slot", "run_id", "staff_id", "day_of_week", "period"),
        Index("idx_schedule_run_student", "run_id", "student_id"),
        Index("idx_schedule_run_staff", "run_id", "staff_id"),
        Index("idx_schedule_run_grade", "run_id", "grade"),
    )


class ComplianceFlag(Base):
    __tablename__ = "compliance_flags"

    id: Mapped[uuid.UUID] = uuid_pk()

    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schedule_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("students.id"))
    staff_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("staff_members.id"))

    student_external_id: Mapped[Optional[str]] = mapped_column(String(100))
    teacher_name: Mapped[Optional[str]] = mapped_column(String(255))

    flag_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    legal_reference: Mapped[Optional[str]] = mapped_column(Text)
    affected_period: Mapped[Optional[str]] = mapped_column(String(100))

    status: Mapped[str] = mapped_column(String(50), default="open")


    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class FlexGroup(Base):
    __tablename__ = "flex_groups"

    id: Mapped[uuid.UUID] = uuid_pk()

    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schedule_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[Optional[str]] = mapped_column(String(50))
    focus_area: Mapped[Optional[str]] = mapped_column(String(100))

    staff_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("staff_members.id"))
    teacher_name: Mapped[Optional[str]] = mapped_column(String(255))

    day_of_week: Mapped[Optional[str]] = mapped_column(String(20))
    period: Mapped[Optional[int]] = mapped_column(Integer)

    max_group_size: Mapped[int] = mapped_column(Integer, default=10)
    status: Mapped[str] = mapped_column(String(50), default="active")
    

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    students = relationship("FlexGroupStudent", back_populates="flex_group")


class FlexGroupStudent(Base):
    __tablename__ = "flex_group_students"

    id: Mapped[uuid.UUID] = uuid_pk()

    flex_group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("flex_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )

    flex_group = relationship("FlexGroup", back_populates="students")

    __table_args__ = (
        UniqueConstraint("flex_group_id", "student_id", name="uq_flex_group_student"),
    )


class LegalRule(Base):
    __tablename__ = "legal_rules"

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("schools.id"))

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(100), nullable=False)

    description: Mapped[Optional[str]] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(50), default="warning")

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rule_json: Mapped[Optional[dict]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ApprovalAction(Base):
    __tablename__ = "approval_actions"

    id: Mapped[uuid.UUID] = uuid_pk()

    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schedule_runs.id"), nullable=False)

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))
    user_name: Mapped[Optional[str]] = mapped_column(String(255))

    action: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()

    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id"),
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    full_name: Mapped[Optional[str]] = mapped_column(String(255))

    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    staff_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("staff_members.id"),
        unique=True,
        nullable=True,
    )

    staff_member = relationship(
        "StaffMember",
        back_populates="user",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = uuid_pk()

    school_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("schools.id"))
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))

    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(String(100))
    entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))

    before_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    after_json: Mapped[Optional[dict]] = mapped_column(JSONB)

    ip_address: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StudentTeacher(Base):
    __tablename__ = "student_teachers"

    id: Mapped[uuid.UUID] = uuid_pk()

    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False
    )

    staff_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="CASCADE"),
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "staff_id",
            name="uq_student_teacher"
        ),
    )