import os
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

BASE44_BASE_URL = os.getenv("BASE44_BASE_URL", "https://compli-sched.base44.app/api")
BASE44_API_KEY = os.getenv("BASE44_API_KEY")


class Base44ConfigError(RuntimeError):
    pass


class Base44APIError(RuntimeError):
    pass


def _headers() -> Dict[str, str]:
    """
    Base44 uses an api_key header, not Bearer auth.
    """
    if not BASE44_API_KEY:
        raise Base44ConfigError(
            "BASE44_API_KEY is missing. Create a .env file from .env.example."
        )

    return {
        "api_key": BASE44_API_KEY,
        "Content-Type": "application/json",
    }


def _url(entity_name: str, suffix: str = "") -> str:
    suffix = suffix.strip("/")
    if suffix:
        return f"{BASE44_BASE_URL}/entities/{entity_name}/{suffix}"
    return f"{BASE44_BASE_URL}/entities/{entity_name}"


def list_entity(
    entity_name: str,
    limit: int = 500,
    skip: int = 0,
    query: Optional[Dict[str, Any]] = None,
    sort_by: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Generic Base44 list call.

    Base44 supports:
      GET /entities/{Entity}
      q=<json filter>
      limit=<number>
      skip=<number>
      sort_by=<field>
    """
    params: Dict[str, Any] = {
        "limit": limit,
        "skip": skip,
    }

    if query is not None:
        import json

        params["q"] = json.dumps(query)

    if sort_by:
        params["sort_by"] = sort_by

    response = requests.get(
        _url(entity_name),
        headers=_headers(),
        params=params,
        timeout=30,
    )

    if not response.ok:
        raise Base44APIError(
            f"Base44 GET {entity_name} failed: "
            f"{response.status_code} {response.text}"
        )

    data = response.json()

    # Base44 usually returns a raw list, but this keeps it safe if it wraps later.
    if isinstance(data, list):
        return data

    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
        return data["data"]

    raise Base44APIError(f"Unexpected Base44 response for {entity_name}: {data}")


def create_entity(entity_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.post(
        _url(entity_name),
        headers=_headers(),
        json=payload,
        timeout=30,
    )

    if not response.ok:
        raise Base44APIError(
            f"Base44 POST {entity_name} failed: "
            f"{response.status_code} {response.text}"
        )

    return response.json()

def delete_entity_many(entity_name: str, query: dict):
    """
    Deletes multiple records from a Base44 entity.

    WARNING:
    Passing {} deletes all records in that entity.
    """
    response = requests.delete(
        _url(entity_name),
        headers=_headers(),
        json=query,
        timeout=60,
    )

    if not response.ok:
        raise Base44APIError(
            f"Base44 DELETE {entity_name} failed: "
            f"{response.status_code} {response.text}"
        )

    return response.json()

def bulk_create_entity(entity_name: str, payloads: List[Dict[str, Any]]) -> Any:
    if not payloads:
        return []

    response = requests.post(
        _url(entity_name, "bulk"),
        headers=_headers(),
        json=payloads,
        timeout=60,
    )

    if not response.ok:
        raise Base44APIError(
            f"Base44 bulk POST {entity_name} failed: "
            f"{response.status_code} {response.text}"
        )

    return response.json()


def get_students(
    active_only: bool = False,
    search: str | None = None,
    grade: int | None = None,
    iep: bool | None = None,
    mtss_tier: int | None = None
) -> List[Dict[str, Any]]:

    db = SessionLocal()

    try:

        query = db.query(Student)


        if search:
            query = query.filter(
                (Student.first_name.ilike(f"%{search}%")) |
                (Student.last_name.ilike(f"%{search}%"))
            )


        if grade:
            query = query.filter(
                Student.grade == grade
            )


        if iep is not None:
            query = query.filter(
                Student.has_iep == iep
            )


        if mtss_tier:
            query = query.filter(
                Student.mtss_tier == mtss_tier
            )


        students = query.all()


        return [
            {
                "id": str(student.id),
                "student_id": student.external_student_id or str(student.id),
                "first_name": student.first_name,
                "last_name": student.last_name,
                "grade": student.grade,
                "homeroom": student.homeroom,
                "has_iep": student.has_iep,
                "enl_level": student.enl_level,
                "enl_minutes_required": student.enl_minutes_required,
                "mtss_tier": student.mtss_tier,
                "status": "active",
            }
            for student in students
        ]

    finally:
        db.close()


def get_staff(active_only: bool = False) -> List[Dict[str, Any]]:
    query = {"status": "active"} if active_only else None
    return list_entity("StaffMember", query=query, limit=1000)

def create_flex_groups(groups):
    return bulk_create_entity("FlexGroup", groups)

def get_schedule_entries() -> List[Dict[str, Any]]:
    return list_entity("ScheduleEntry", limit=5000)


def get_flex_groups(active_only: bool = True) -> List[Dict[str, Any]]:
    query = {"status": "active"} if active_only else None
    return list_entity("FlexGroup", query=query, limit=1000)


def create_schedule_proposal(payload: Dict[str, Any]) -> Dict[str, Any]:
    return create_entity("ScheduleProposal", payload)


def create_schedule_entries(entries: List[Dict[str, Any]]) -> Any:
    return bulk_create_entity("ScheduleEntry", entries)


def create_compliance_flags(flags: List[Dict[str, Any]]) -> Any:
    return bulk_create_entity("ComplianceFlag", flags)
