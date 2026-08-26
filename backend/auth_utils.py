"""
auth_utils.py

Shared password hashing utilities.

Split out from main.py so other modules (setup.py in particular) can hash
and verify passwords without importing the FastAPI app itself -- importing
main.py from setup.py would create a circular import, since main.py needs
to import setup.py to expose the /setup/* endpoints.

main.py should import from here instead of defining its own pwd_context.
"""

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)