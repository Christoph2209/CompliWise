from dmscheduler_db import SessionLocal, User, School
from argon2 import PasswordHasher
import uuid

ph = PasswordHasher()
db = SessionLocal()

# 1. Create a school first
school = School(
    id=uuid.uuid4(),
    name="Test School",
    district_name="Test District"
)

db.add(school)
db.flush()  # gets school.id without committing

# 2. Create user linked to that school
user = User(
    id=uuid.uuid4(),
    school_id=school.id,
    email="a",
    full_name="me",
    role="admin",
    password_hash=ph.hash("password123")
)

db.add(user)
db.commit()
db.close()

print("School + User created successfully")