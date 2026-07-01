from backend.dmscheduler_db import SessionLocal, User
from argon2 import PasswordHasher
import uuid

ph = PasswordHasher()

db = SessionLocal()

user = User(
    id=uuid.uuid4(),
    school_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),  # must be UUID, not string
    email="chris@school.com",
    full_name="me",
    role="admin",
    password_hash=ph.hash("password123")
)

db.add(user)
db.commit()
db.close()

print("User created successfully")