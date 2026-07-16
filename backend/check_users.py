from dmscheduler_db import SessionLocal, User

db = SessionLocal()
users = db.query(User).all()
for u in users:
    print(repr(u.email), u.role, u.password_hash[:20])
db.close()
