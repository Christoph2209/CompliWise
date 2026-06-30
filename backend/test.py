# test_db.py

from database_service import get_students, get_staff

print(f"Students: {len(get_students())}")
print(f"Staff: {len(get_staff())}")