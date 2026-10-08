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
from scheduling_core import get_student_services  # noqa: E402
from compliwise_db import SessionLocal, School, Student, StudentService, User  # noqa: E402

DATA = BACKEND.parent / "data"
STUDENTS_CSV = (DATA / "Student_export_base.csv").read_bytes()
STAFF_CSV = (DATA / "StaffMember_base.csv").read_bytes()
ROSTER_XLSX = (DATA / "Middle_School_Compliance_Roster_v3.xlsx").read_bytes()
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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


def test_compliance_roster_workbook_import():
    school, users = _make_school_with_users("Iota School")
    admin = _login(_client(), users["admin"], "pw12345678")

    def roster():
        return {"students_file": ("roster.xlsx", io.BytesIO(ROSTER_XLSX), XLSX_TYPE)}

    r = admin.post("/import/preview", files=roster())
    assert r.status_code == 200, r.text
    report = r.json()["files"][0]
    assert r.json()["can_import"] is True
    assert (report["rows_read"], report["new_records"], report["services_found"]) == (240, 240, 340)
    # Blank placement cells are reported against the workbook's own row numbers.
    assert {i["row"] for i in report["issues"] if i["row"]} == {34, 194, 195}

    r = admin.post("/import/commit", files=roster())
    assert r.status_code == 200, r.text
    assert (r.json()["students_imported"], r.json()["services_imported"]) == (240, 340)

    students = {s["student_id"]: s for s in admin.get("/students").json()["students"]}

    def services_of(student_id):
        return {(s["service_type"], s["subject_area"]): s for s in students[student_id]["iep_services"]}

    # MS1001: ICT in all four subjects, "2X30 group of3" Speech, "1X30 group3"
    # Counseling, ENL "Transitioning".
    first = students["MS1001"]
    assert first["grade"] == "6" and first["has_iep"] is True
    assert (first["enl_level"], first["enl_minutes_required"]) == ("transitioning", 180)
    services = services_of("MS1001")
    assert set(services) == {
        ("ICT", "ELA"), ("ICT", "Math"), ("ICT", "Science"), ("ICT", "Social Studies"),
        ("Speech", None), ("Counseling", None),
    }
    speech = services[("Speech", None)]
    assert (speech["sessions_per_week"], speech["minutes_per_week"]) == (2, 60)
    assert speech["notes"] == "Group size: 3"  # real minutes, so no verification warning
    assert services[("ICT", "ELA")]["is_pullout"] is False

    # "5Xweek" has no session length, so it keeps the placeholder warning.
    assert "NEEDS VERIFICATION" in services_of("MS1004")[("Resource Room", None)]["notes"]
    # All Gen Education, no services: not an IEP student.
    assert students["MS1006"]["has_iep"] is False and students["MS1006"]["iep_services"] == []
    # Special classes are recorded per subject but aren't sessions to schedule.
    assert ("12:1+1", "ELA") in services_of("MS1020")
    assert ("12:1", "ELA") in services_of("MS1228")
    scheduled = {s["service_type"] for s in get_student_services(students["MS1020"])}
    # ICT is co-teaching in the student's class, never a pull-out, even
    # when a stored row says otherwise.
    ict = get_student_services({"services": [{"service_type": "ICT", "minutes": 150, "is_pullout": True}]})
    assert ict[0]["is_pullout"] is False
    assert "12:1+1" not in scheduled and "Speech" in scheduled

    # Re-importing the workbook duplicates nothing.
    r = admin.post("/import/commit", files=roster())
    assert r.json()["services_imported"] == 0
    db = SessionLocal()
    assert db.query(Student).filter(Student.school_id == school).count() == 240
    assert db.query(StudentService).filter(StudentService.school_id == school).count() == 340
    db.close()


def test_setup_import_takes_a_single_unlabelled_file():
    school, users = _make_school_with_users("Kappa School")
    admin = _login(_client(), users["admin"], "pw12345678")

    # One workbook, not labelled students or staff: its columns decide.
    r = admin.post("/setup/import-csv", files=[("files", ("roster.xlsx", io.BytesIO(ROSTER_XLSX), XLSX_TYPE))])
    assert r.status_code == 200, r.text
    assert (r.json()["students_imported"], r.json()["staff_imported"]) == (240, 0)

    # Two files in either order, one of each kind.
    r = admin.post("/setup/import-csv", files=[
        ("files", ("staff.csv", io.BytesIO(STAFF_CSV), "text/csv")),
        ("files", ("students.csv", io.BytesIO(STUDENTS_CSV), "text/csv")),
    ])
    assert r.status_code == 200, r.text
    assert r.json()["students_imported"] == 300 and r.json()["staff_imported"] > 0

    r = admin.post("/setup/import-csv", files=[("files", ("x.csv", io.BytesIO(b"name,grade\nAna,3\n"), "text/csv"))])
    assert r.status_code == 422 and "students or staff" in r.json()["detail"]
    r = admin.post("/setup/import-csv", files=[
        ("files", ("a.xlsx", io.BytesIO(ROSTER_XLSX), XLSX_TYPE)),
        ("files", ("b.csv", io.BytesIO(STUDENTS_CSV), "text/csv")),
    ])
    assert r.status_code == 422 and "Two students files" in r.json()["detail"]


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

    # A teacher sees their own entries plus the pull-outs and push-ins of
    # students they teach (delivered by ENL/IEP providers), and nothing else.
    all_entries = admin_a.get("/schedule").json()

    def is_pullout(e):
        return e["delivery"] == "pullout" or (e["delivery"] is None and e["is_pullout"])

    def is_service(e):
        return is_pullout(e) or e["delivery"] == "push_in"

    # The demo CSV has ICT services; none may be scheduled as a pull-out.
    assert not any(e["service_type"] == "ICT" and is_pullout(e) for e in all_entries)
    db = SessionLocal()
    assert db.query(StudentService).filter(
        StudentService.school_id == school_a, StudentService.service_type == "ICT",
        StudentService.is_pullout.is_(False),
    ).count() > 0
    db.close()

    pullout = next(
        p for p in all_entries
        if is_pullout(p) and any(
            e["student_id"] == p["student_id"] and e["staff_id"]
            and e["staff_id"] != p["staff_id"] and not is_pullout(e)
            for e in all_entries
        )
    )
    some_staff_id = next(
        e["staff_id"] for e in all_entries
        if e["student_id"] == pullout["student_id"] and e["staff_id"]
        and e["staff_id"] != pullout["staff_id"] and not is_pullout(e)
    )
    db = SessionLocal()
    teacher = db.query(User).filter(User.email == users_a["teacher"]).first()
    teacher.staff_id = uuid.UUID(some_staff_id)
    db.commit()
    db.close()
    mine = teacher_a.get("/schedule").json()
    my_students = {e["student_id"] for e in mine if e["staff_id"] == some_staff_id}
    assert pullout["id"] in {e["id"] for e in mine}
    assert all(
        e["staff_id"] == some_staff_id or (is_service(e) and e["student_id"] in my_students)
        for e in mine
    )
    assert len(mine) < len(all_entries)
    assert admin_b.get("/compliance-flags").json() == []

    # Without run_id, /schedule returns only the latest run, not every run.
    assert admin_a.post("/save-schedule", json=config).status_code == 200
    runs_a = admin_a.get("/schedule-runs").json()
    assert len(runs_a) == 2
    latest = admin_a.get("/schedule").json()
    assert {e["run_id"] for e in latest} == {runs_a[0]["id"]}
    assert len(latest) == runs_a[0]["entry_count"]

    # School B's reset can't touch school A's schedules.
    assert admin_b.post("/reset-generated-schedules").status_code == 200
    assert len(admin_a.get("/schedule-runs").json()) == 2
    assert admin_a.post("/reset-generated-schedules").status_code == 200
    assert admin_a.get("/schedule-runs").json() == []


def test_published_schedule_is_permanent():
    _, users_a = _make_school_with_users("Zeta School")
    _, users_b = _make_school_with_users("Eta School")
    admin_a = _login(_client(), users_a["admin"], "pw12345678")
    principal_a = _login(_client(), users_a["principal"], "pw12345678")
    teacher_a = _login(_client(), users_a["teacher"], "pw12345678")
    admin_b = _login(_client(), users_b["admin"], "pw12345678")

    assert admin_a.post("/import/commit", files=_files(STUDENTS_CSV, STAFF_CSV)).status_code == 200
    config = admin_a.get("/schedule/config-defaults").json()["config"]
    assert admin_a.post("/save-schedule", json=config).status_code == 200
    run = admin_a.get("/schedule-runs").json()[0]
    assert run["status"] == "draft"

    # Only managers of the same school can publish.
    assert teacher_a.post(f"/schedule-runs/{run['id']}/publish").status_code == 403
    assert admin_b.post(f"/schedule-runs/{run['id']}/publish").status_code == 404
    r = principal_a.post(f"/schedule-runs/{run['id']}/publish")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"
    assert admin_a.post(f"/schedule-runs/{run['id']}/publish").status_code == 409
    published = admin_a.get("/schedule-runs").json()[0]
    assert published["status"] == "published" and published["published_at"]

    # Published entries are locked.
    entry = admin_a.get("/schedule", params={"run_id": run["id"]}).json()[0]
    r = admin_a.put(f"/schedule/{entry['id']}", json={"room": "Gym"})
    assert r.status_code == 409, r.text

    # A newer draft doesn't replace the published schedule as the default...
    assert admin_a.post("/save-schedule", json=config).status_code == 200
    runs = admin_a.get("/schedule-runs").json()
    draft = runs[0]
    assert draft["status"] == "draft" and draft["id"] != run["id"]
    assert {e["run_id"] for e in admin_a.get("/schedule").json()} == {run["id"]}
    staff_id = entry["staff_id"]
    db = SessionLocal()
    teacher = db.query(User).filter(User.email == users_a["teacher"]).first()
    teacher.staff_id = uuid.UUID(staff_id)
    db.commit()
    db.close()
    assert {e["run_id"] for e in teacher_a.get("/staff-schedule").json()} == {run["id"]}
    # ...but drafts stay editable.
    draft_entry = admin_a.get("/schedule", params={"run_id": draft["id"]}).json()[0]
    assert admin_a.put(f"/schedule/{draft_entry['id']}", json={"room": "Gym"}).status_code == 200

    # Reset wipes everything, published runs included.
    assert admin_a.post("/reset-generated-schedules").status_code == 200
    assert admin_a.get("/schedule-runs").json() == []
    assert admin_a.get("/schedule").json() == []


def test_edited_iep_service_drives_the_schedule():
    _, users = _make_school_with_users("Theta School")
    admin = _login(_client(), users["admin"], "pw12345678")
    assert admin.post("/import/commit", files=_files(STUDENTS_CSV, STAFF_CSV)).status_code == 200

    students = admin.get("/students").json()["students"]
    student, service = next(
        (s, svc) for s in students for svc in s["iep_services"]
        if svc["service_type"] == "Speech"
    )
    assert service["id"] and service["minutes_per_week"] and "sessions_per_week" in service

    url = f"/students/{student['id']}/services/{service['id']}"
    assert admin.put(url, json={"minutes_per_week": 0}).status_code == 422
    assert admin.put(url, json={"sessions_per_week": 0}).status_code == 422
    # 4 sessions of 20 minutes.
    r = admin.put(url, json={"sessions_per_week": 4, "minutes_per_week": 80})
    assert r.status_code == 200, r.text

    saved = next(
        svc for s in admin.get("/students").json()["students"] if s["id"] == student["id"]
        for svc in s["iep_services"] if svc["id"] == service["id"]
    )
    assert (saved["sessions_per_week"], saved["minutes_per_week"]) == (4, 80)

    config = admin.get("/schedule/config-defaults").json()["config"]
    assert admin.post("/save-schedule", json=config).status_code == 200
    sessions = [
        e for e in admin.get("/schedule").json()
        if e["student_id"] == student["id"] and e["service_type"] == "Speech"
    ]
    assert len(sessions) == 4
    assert all(e["end_minute"] - e["start_minute"] == 20 for e in sessions)
