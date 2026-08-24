"""
setup.py

First-run setup for CompliWise.

Handles the three things a fresh install needs before it's usable:
  1. Running Alembic migrations against a brand-new database
  2. Creating the School row and the first admin User
  3. (via main.py's /setup/import-csv, using import_students/import_staff
     from import_csv_data.py) importing starter student/staff data

Everything here is written to be safe to call more than once:
  - run_migrations() just runs `alembic upgrade head`, which is a no-op
    if the DB is already at head.
  - create_school_and_admin() refuses to run if an admin already exists,
    so re-hitting /setup/initialize after setup is done fails loudly
    instead of creating a second admin or a duplicate school.

NOTE on security: /setup/* endpoints in main.py are intentionally
unauthenticated, since there's no user to authenticate as before setup
has run. admin_exists() is what gates them closed afterward. This is a
known-narrow trust model (same family of issue as the CURRENT_USER
global-state auth gap already tracked) -- once real session/token auth
is in place, /setup/import-csv in particular should additionally require
an authenticated admin, not just "no admin yet vs. admin exists".
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth_utils import hash_password
from dmscheduler_db import School, User

BACKEND_DIR = Path(__file__).resolve().parent
ALEMBIC_INI_PATH = BACKEND_DIR / "alembic.ini"


class SetupError(Exception):
    """Raised for any setup-flow failure the API layer should surface as a clean HTTP error."""


def db_connectable(db: Session) -> bool:
    """
    True if Postgres itself is reachable -- independent of whether our
    schema has been migrated yet. A missing `users` table (fresh volume,
    migrations never run) still counts as "connectable"; only a real
    connection failure (container still starting, wrong host/port,
    credentials wrong, etc.) returns False. This is deliberately schema-
    agnostic: a bare `SELECT 1` works even against an empty database.
    """
    try:
        db.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        db.rollback()
        return False


def admin_exists(db: Session) -> bool:
    """
    False both when there's genuinely no admin yet AND when the `users`
    table doesn't exist yet (fresh/unmigrated schema). Both cases mean
    "setup still needs to run" to every caller of this function, so
    they're treated the same rather than the second one raising.
    """
    try:
        return db.query(User).filter(User.role == "admin").first() is not None
    except SQLAlchemyError:
        db.rollback()
        return False


def is_setup_complete(db: Session) -> bool:
    return db_connectable(db) and admin_exists(db)


def run_migrations() -> None:
    if not ALEMBIC_INI_PATH.exists():
        raise SetupError(
            f"alembic.ini not found at {ALEMBIC_INI_PATH}. Setup expects it "
            "next to main.py -- update ALEMBIC_INI_PATH in setup.py if your "
            "backend layout differs."
        )

    cfg = Config(str(ALEMBIC_INI_PATH))
    try:
        command.upgrade(cfg, "head")
    except Exception as error:  # alembic surfaces a mix of exception types
        raise SetupError(f"Migration failed: {error}") from error


def create_school_and_admin(
    db: Session,
    *,
    school_name: str,
    district_name: Optional[str],
    admin_email: str,
    admin_password: str,
    admin_full_name: Optional[str],
) -> tuple[School, User]:
    if admin_exists(db):
        raise SetupError("Setup has already been completed -- an admin account already exists.")

    existing_email = db.query(User).filter(User.email == admin_email).first()
    if existing_email:
        raise SetupError("A user with this email already exists.")

    school = db.query(School).filter(School.name == school_name).first()
    if not school:
        school = School(
            id=uuid.uuid4(),
            name=school_name,
            district_name=district_name,
        )
        db.add(school)
        db.flush()  # populate school.id without committing yet

    admin = User(
        id=uuid.uuid4(),
        school_id=school.id,
        email=admin_email,
        password_hash=hash_password(admin_password),
        full_name=admin_full_name,
        role="admin",
        is_active=True,
    )
    db.add(admin)

    db.commit()
    db.refresh(school)
    db.refresh(admin)

    return school, admin