# models.py

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class School(Base):
    __tablename__ = "schools"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    district_name: Mapped[str | None] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(100), default="America/New_York")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Student(Base):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)

    external_student_id: Mapped[str | None] = mapped_column(String(100))
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)

    grade: Mapped[str | None] = mapped_column(String(50))
    homeroom: Mapped[str | None] = mapped_column(String(100))

    has_iep: Mapped[bool] = mapped_column(Boolean, default=False)
    enl_level: Mapped[str | None] = mapped_column(String(50))
    enl_minutes_required: Mapped[int] = mapped_column(Integer, default=0)
    mtss_tier: Mapped[str | None] = mapped_column(String(50))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    services = relationship("StudentService", back_populates="student")


class StaffMember(Base):
    __tablename__ = "staff_members"

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)

    external_staff_id: Mapped[str | None] = mapped_column(String(100))
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)

    title: Mapped[str | None] = mapped_column(String(100))
    grade: Mapped[str | None] = mapped_column(String(50))
    homeroom: Mapped[str | None] = mapped_column(String(100))
    room: Mapped[str | None] = mapped_column(String(100))

    is_certified_sped: Mapped[bool] = mapped_column(Boolean, default=False)
    is_certified_enl: Mapped[bool] = mapped_column(Boolean, default=False)
    is_certified_slp: Mapped[bool] = mapped_column(Boolean, default=False)
    can_deliver_setss: Mapped[bool] = mapped_column(Boolean, default=False)

    max_students_per_group: Mapped[int] = mapped_column(Integer, default=30)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StudentService(Base):
    __tablename__ = "student_services"

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )

    service_type: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_area: Mapped[str | None] = mapped_column(String(100))

    minutes_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    sessions_per_week: Mapped[int | None] = mapped_column(Integer)

    is_pullout: Mapped[bool] = mapped_column(Boolean, default=True)
    preferred_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_members.id")
    )

    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    student = relationship("Student", back_populates="services")


class ScheduleRun(Base):
    __tablename__ = "schedule_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)

    school_year: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))

    status: Mapped[str] = mapped_column(String(50), default="draft")
    generated_by: Mapped[str | None] = mapped_column(String(255))

    summary_json: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)


class ScheduleEntry(Base):
    __tablename__ = "schedule_entries"

    id: Mapped[uuid.UUID] = uuid_pk()

    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schedule_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id"), nullable=False)
    staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_members.id"))

    day_of_week: Mapped[str] = mapped_column(String(20), nullable=False)
    period: Mapped[int] = mapped_column(Integer, nullable=False)

    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    room: Mapped[str | None] = mapped_column(String(100))

    service_type: Mapped[str | None] = mapped_column(String(100))
    is_pullout: Mapped[bool] = mapped_column(Boolean, default=False)
    is_flex_period: Mapped[bool] = mapped_column(Boolean, default=False)

    source: Mapped[str] = mapped_column(String(50), default="scheduler")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "student_id",
            "day_of_week",
            "period",
            name="uq_student_one_entry_per_slot",
        ),
        Index(
            "idx_schedule_student_slot",
            "run_id",
            "student_id",
            "day_of_week",
            "period",
        ),
        Index(
            "idx_schedule_teacher_slot",
            "run_id",
            "staff_id",
            "day_of_week",
            "period",
        ),
        Index("idx_schedule_run_student", "run_id", "student_id"),
        Index("idx_schedule_run_staff", "run_id", "staff_id"),
    )


class FlexGroup(Base):
    __tablename__ = "flex_groups"

    id: Mapped[uuid.UUID] = uuid_pk()

    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schedule_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[str | None] = mapped_column(String(50))
    focus_area: Mapped[str | None] = mapped_column(String(100))

    staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_members.id"))

    day_of_week: Mapped[str | None] = mapped_column(String(20))
    period: Mapped[int | None] = mapped_column(Integer)

    max_group_size: Mapped[int] = mapped_column(Integer, default=10)
    status: Mapped[str] = mapped_column(String(50), default="active")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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


class ComplianceFlag(Base):
    __tablename__ = "compliance_flags"

    id: Mapped[uuid.UUID] = uuid_pk()

    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schedule_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    student_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("students.id"))
    staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_members.id"))

    flag_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    legal_reference: Mapped[str | None] = mapped_column(Text)
    affected_period: Mapped[str | None] = mapped_column(String(100))

    status: Mapped[str] = mapped_column(String(50), default="open")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


class ManualAdjustment(Base):
    __tablename__ = "manual_adjustments"

    id: Mapped[uuid.UUID] = uuid_pk()

    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schedule_runs.id"), nullable=False)

    schedule_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schedule_entries.id")
    )

    changed_by: Mapped[str | None] = mapped_column(String(255))
    reason: Mapped[str | None] = mapped_column(Text)

    before_json: Mapped[dict | None] = mapped_column(JSONB)
    after_json: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = uuid_pk()

    school_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("schools.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(100))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    before_json: Mapped[dict | None] = mapped_column(JSONB)
    after_json: Mapped[dict | None] = mapped_column(JSONB)

    ip_address: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)