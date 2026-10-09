"""
Password changes: non-admins need an admin's approval, admins don't.
Same throwaway-database requirement as test_security_and_import.py.
"""
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
from compliwise_db import PasswordChangeRequest, SessionLocal, School, User  # noqa: E402

OLD = "pw12345678"
NEW = "brand-new-pass-42"


def _school(name):
    db = SessionLocal()
    try:
        school = School(id=uuid.uuid4(), name=name)
        db.add(school)
        db.flush()
        suffix = uuid.uuid4().hex[:6]
        emails = {}
        for role in ("admin", "teacher", "aide"):
            email = f"{role}-{suffix}@{name.lower().replace(' ', '')}.test"
            db.add(User(school_id=school.id, email=email, password_hash=hash_password(OLD), role=role))
            emails[role] = email
        db.commit()
        return emails
    finally:
        db.close()


def _login(email, password, expect=200):
    client = TestClient(main.app)
    r = client.post("/login", json={"email": email, "password": password})
    assert r.status_code == expect, r.text
    return client


def test_teacher_change_waits_for_admin_approval():
    users = _school("Approval School")
    teacher = _login(users["teacher"], OLD)
    admin = _login(users["admin"], OLD)

    info = teacher.get("/me/password-change-request").json()
    assert info == {"requires_approval": True, "request": None}

    # Wrong current password, short and unchanged passwords are refused.
    assert teacher.post("/me/password", json={"current_password": "nope", "new_password": NEW}).status_code == 400
    assert teacher.post("/me/password", json={"current_password": OLD, "new_password": "short"}).status_code == 400
    assert teacher.post("/me/password", json={"current_password": OLD, "new_password": OLD}).status_code == 400

    r = teacher.post("/me/password", json={"current_password": OLD, "new_password": NEW})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"
    assert "hash" not in r.text

    # Nothing has changed yet: the old password still works, the new one doesn't.
    _login(users["teacher"], OLD)
    _login(users["teacher"], NEW, expect=401)

    # Teachers can't see or act on the queue.
    assert teacher.get("/admin/password-change-requests").status_code == 403
    pending = admin.get("/admin/password-change-requests").json()
    mine = [p for p in pending if p["user"]["email"] == users["teacher"]]
    assert len(mine) == 1
    assert teacher.post(f"/admin/password-change-requests/{mine[0]['id']}/approve").status_code == 403

    r = admin.post(f"/admin/password-change-requests/{mine[0]['id']}/approve", json={"note": "ok"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    # Approved: new password works, old one doesn't, and the old session is over.
    _login(users["teacher"], NEW)
    _login(users["teacher"], OLD, expect=401)
    assert teacher.get("/me").status_code == 401

    # Can't approve twice; the stored hash is wiped once decided.
    assert admin.post(f"/admin/password-change-requests/{mine[0]['id']}/approve").status_code == 409
    db = SessionLocal()
    try:
        assert db.get(PasswordChangeRequest, uuid.UUID(mine[0]["id"])).new_password_hash is None
    finally:
        db.close()


def test_reject_and_cancel_keep_the_old_password():
    users = _school("Reject School")
    aide = _login(users["aide"], OLD)
    admin = _login(users["admin"], OLD)

    first = aide.post("/me/password", json={"current_password": OLD, "new_password": NEW}).json()["request"]
    # A second request replaces the first instead of stacking up.
    second = aide.post("/me/password", json={"current_password": OLD, "new_password": NEW + "x"}).json()["request"]
    pending_ids = {p["id"] for p in admin.get("/admin/password-change-requests").json()}
    assert second["id"] in pending_ids and first["id"] not in pending_ids

    r = admin.post(f"/admin/password-change-requests/{second['id']}/reject", json={"note": "Call the office"})
    assert r.status_code == 200
    latest = aide.get("/me/password-change-request").json()["request"]
    assert latest["status"] == "rejected" and latest["review_note"] == "Call the office"
    _login(users["aide"], OLD)
    assert aide.get("/me").status_code == 200  # rejection doesn't sign anyone out

    aide.post("/me/password", json={"current_password": OLD, "new_password": NEW})
    assert aide.delete("/me/password-change-request").status_code == 200
    assert aide.delete("/me/password-change-request").status_code == 404
    _login(users["aide"], OLD)


def test_admins_cannot_review_another_schools_requests():
    a = _school("School A")
    b = _school("School B")
    teacher_a = _login(a["teacher"], OLD)
    admin_b = _login(b["admin"], OLD)

    req = teacher_a.post("/me/password", json={"current_password": OLD, "new_password": NEW}).json()["request"]
    assert all(p["id"] != req["id"] for p in admin_b.get("/admin/password-change-requests").json())
    assert admin_b.post(f"/admin/password-change-requests/{req['id']}/approve").status_code == 404
    _login(a["teacher"], OLD)


def test_admin_changes_own_password_directly():
    users = _school("Admin School")
    admin = _login(users["admin"], OLD)
    other_tab = _login(users["admin"], OLD)

    assert admin.get("/me/password-change-request").json()["requires_approval"] is False
    r = admin.post("/me/password", json={"current_password": OLD, "new_password": NEW})
    assert r.status_code == 200 and r.json() == {"status": "changed"}

    assert admin.get("/me").status_code == 200       # this session carries on
    assert other_tab.get("/me").status_code == 401   # every other session ends
    _login(users["admin"], NEW)
    _login(users["admin"], OLD, expect=401)
