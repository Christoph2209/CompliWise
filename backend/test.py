# test_db.py

from db_client import get_students, get_staff

print(f"Students: {len(get_students())}")
print(f"Staff: {len(get_staff())}")