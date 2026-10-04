"""
End-to-end checks for login, roles, school isolation and CSV import.
Needs a THROWAWAY Postgres database (it creates schools and users):

    DATABASE_URL=postgresql+psycopg2://user:pass@localhost/compliwise_test \
    SESSION_SECRET=test python -m pytest backend/tests -q
    (run `alembic upgrade head` against that database first)
"""
import io
import os
import sys
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from auth_utils import hash_password  # noqa: E402
from dmscheduler_db import SessionLocal, School, Student, StudentService, User  # noqa: E402

DATA = BACKEND.parent / "data"
STUDENTS_CSV = (DATA / "Student_export.csv").read_bytes()
STAFF_CSV = (DATA / "StaffMember_export.csv").read_bytes()


def _client():
    return TestClient(main.app)


def _login(client, email, password):
    r = client.post("/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return client


def _files(students=None, staff=None):
    files = {}
    if students is not None:
        files["students_file"] = ("students.csv", io.BytesIO(students), "text/csv")
    if staff is not None:
        files["staff_file"] = ("staff.csv", io.BytesIO(staff), "text/csv")
    return files


def _make_school_with_users(name):
    db = SessionLocal()
    try:
        school = School(id=uuid.uuid4(), name=name)
        db.add(school)
        db.flush()
        suffix = uuid.uuid4().hex[:6]
        users = {}
        for role in ("admin", "principal", "teacher"):
            email = f"{role}-{suffix}@{name.lower().replace(' ', '')}.test"
            db.add(User(school_id=school.id, email=email, password_hash=hash_password("pw12345678"), role=role))
            users[role] = email
        db.commit()
        return school.id, users
    finally:
        db.close()


# ---------------------------------------------------------------------------

def test_setup_wizard_flow_and_import_lockdown():
    db = SessionLocal()
    already = db.query(User).filter(User.role == "admin").first() is not None
    db.close()

    client = _client()
    if not already:
        r = client.post("/setup/initialize", json={
            "school_name": "Wizard School", "admin_email": "wizard@example.com",
            "admin_password": "pw12345678",
        })
        assert r.status_code == 200, r.text
        # The wizard's next call works because initialize logged the admin in.
        r = client.post("/setup/import-csv", files=_files(STUDENTS_CSV, STAFF_CSV))
        assert r.status_code == 200, r.text
        assert r.json()["students_imported"] == 300

    # A stranger with no session can no longer import.
    r = _client().post("/setup/import-csv", files=_files(STUDENTS_CSV))
    assert r.status_code == 401


def test_every_private_endpoint_needs_login():
    client = _client()
    fake = str(uuid.uuid4())
    checks = [
        ("get", "/students"), ("put", f"/students/{fake}"), ("get", "/students/X/schedule"),
        ("get", "/staff"), ("post", "/staff"), ("put", f"/staff/{fake}"),
        ("get", "/schedule"), ("get", "/preview-priority"), ("post", "/save-schedule"),
        ("post", "/reset-generated-schedules"), ("get", "/compliance-flags"),
        ("get", "/flex_groups"), ("post", "/import/preview"), ("post", "/import/commit"),
        ("get", "/audit-logs"), ("get", "/schedule-runs"),
    ]
    for method, path in checks:
        r = getattr(client, method)(path, json={}) if method in ("put", "post") else client.get(path)
        assert r.status_code == 401, (method, path, r.status_code)


def test_school_isolation_roles_and_import():
    school_a, users_a = _make_school_with_users("Alpha School")
    school_b, users_b = _make_school_with_users("Beta School")

    admin_a = _login(_client(), users_a["admin"], "pw12345678")
    admin_b = _login(_client(), users_b["admin"], "pw12345678")
    teacher_a = _login(_client(), users_a["teacher"], "pw12345678")

    # Preview writes nothing and reports counts.
    r = admin_a.post("/import/preview", files=_files(STUDENTS_CSV, STAFF_CSV))
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["can_import"] is True
    students_report = next(f for f in preview["files"] if f["file"] == "students")
    assert students_report["new_records"] == 300
    assert admin_a.get("/students").json()["count"] == 0

    # Commit into school A only.
    r = admin_a.post("/import/commit", files=_files(STUDENTS_CSV, STAFF_CSV))
    assert r.status_code == 200, r.text
    first_services = r.json()["services_imported"]
    assert r.json()["students_imported"] == 300 and first_services > 0

    # Re-import is an update, not a duplicate -- students OR services.
    r = admin_a.post("/import/commit", files=_files(STUDENTS_CSV))
    assert r.json()["services_imported"] == 0
    db = SessionLocal()
    assert db.query(Student).filter(Student.school_id == school_a).count() == 300
    assert db.query(StudentService).filter(StudentService.school_id == school_a).count() == first_services
    some_student = db.query(Student).filter(Student.school_id == school_a).first()
    db.close()

    # School B sees none of school A's data.
    assert admin_b.get("/students").json()["count"] == 0
    assert admin_b.get("/staff").json()["count"] == 0
    r = admin_b.put(f"/students/{some_student.id}", json={"first_name": "Hacked"})
    assert r.status_code == 404
    assert admin_b.get(f"/students/{some_student.id}/services").status_code == 404

    # Teachers can't edit students or IEP services.
    assert teacher_a.put(f"/students/{some_student.id}", json={"first_name": "X"}).status_code == 403
    r = teacher_a.post(f"/students/{some_student.id}/services",
                       json={"service_type": "OT", "minutes_per_week": 60})
    assert r.status_code == 403

    # The admin's edit works and is audited.
    r = admin_a.put(f"/students/{some_student.id}", json={"homeroom": "Room 999"})
    assert r.status_code == 200
    actions = [row["action"] for row in admin_a.get("/audit-logs").json()]
    assert "Update Student" in actions and "CSV Import" in actions
    assert not any(row["action"] == "CSV Import" for row in admin_b.get("/audit-logs").json())

    # Staff created by school B land in school B even if school A's id is sent.
    r = admin_b.post("/staff", json={
        "school_id": str(school_a), "first_name": "Bea", "last_name": "Tester",
        "is_certified_sped": False, "is_certified_enl": False, "is_certified_slp": False,
        "can_deliver_setss": False, "max_students_per_group": 5,
    })
    assert r.status_code == 200, r.text
    assert r.json()["staff"]["school_id"] == str(school_b)


def test_bad_csv_is_refused_with_row_numbers():
    _, users = _make_school_with_users("Gamma School")
    admin = _login(_client(), users["admin"], "pw12345678")

    bad = (
        "student_id,first_name,last_name,grade,has_iep,enl_minutes_required,iep_services\n"
        "S1,Ana,Lee,3,yes,0,\"[{\"\"service_type\"\":\"\"OT\"\",\"\"frequency\"\":\"\"2x/week\"\"}]\"\n"
        "S1,Dup,Row,3,no,0,[]\n"
        ",No,Id,4,no,0,[]\n"
        "S4,Bad,Minutes,4,no,lots,[]\n"
        "S5,Bad,Json,5,yes,0,{not json\n"
    ).encode()
    r = admin.post("/import/preview", files=_files(bad))
    report = r.json()["files"][0]
    assert r.json()["can_import"] is False
    rows_with_errors = {i["row"] for i in report["issues"] if i["severity"] == "error"}
    assert rows_with_errors == {3, 4, 5, 6}

    r = admin.post("/import/commit", files=_files(bad))
    assert r.status_code == 422
    assert admin.get("/students").json()["count"] == 0  # nothing written

    missing_cols = b"name,grade\nAna,3\n"
    r = admin.post("/import/preview", files=_files(missing_cols))
    assert "missing required column" in r.json()["files"][0]["issues"][0]["message"]


def test_schedule_generation_stays_inside_one_school():
    school_a, users_a = _make_school_with_users("Delta School")
    _, users_b = _make_school_with_users("Epsilon School")
    admin_a = _login(_client(), users_a["admin"], "pw12345678")
    admin_b = _login(_client(), users_b["admin"], "pw12345678")
    teacher_a = _login(_client(), users_a["teacher"], "pw12345678")

    assert admin_a.post("/import/commit", files=_files(STUDENTS_CSV, STAFF_CSV)).status_code == 200
    config = admin_a.get("/schedule/config-defaults").json()["config"]

    assert teacher_a.post("/save-schedule", json=config).status_code == 403
    r = admin_a.post("/save-schedule", json=config)
    assert r.status_code == 200, r.text
    assert r.json()["saved"]["schedule_entries"] > 0

    runs_a = admin_a.get("/schedule-runs").json()
    assert len(runs_a) == 1
    assert admin_b.get("/schedule-runs").json() == []
    assert admin_b.get(f"/schedule-runs/{runs_a[0]['id']}").status_code == 404
    assert admin_b.get("/schedule").json() == []

    # A teacher linked to a staff member sees only their own entries.
    all_entries = admin_a.get("/schedule").json()
    some_staff_id = next(e["staff_id"] for e in all_entries if e["staff_id"])
    db = SessionLocal()
    teacher = db.query(User).filter(User.email == users_a["teacher"]).first()
    teacher.staff_id = uuid.UUID(some_staff_id)
    db.commit()
    db.close()
    mine = teacher_a.get("/schedule").json()
    assert mine and all(e["staff_id"] == some_staff_id for e in mine)
    assert len(mine) < len(all_entries)
    assert admin_b.get("/compliance-flags").json() == []

    # School B's reset can't touch school A's schedules.
    assert admin_b.post("/reset-generated-schedules").status_code == 200
    assert len(admin_a.get("/schedule-runs").json()) == 1
    assert admin_a.post("/reset-generated-schedules").status_code == 200
    assert admin_a.get("/schedule-runs").json() == []
