"""Password hashing and rules (FR-AUTH-003).

- Argon2id with argon2-cffi's defaults (RFC 9106 low-memory profile: 64 MiB, 3 passes, 4 lanes).
- At least 12 characters, not containing the username, not a known common password or an obvious pattern.
- Temporary passwords from an Admin's new account or reset: 4 groups of 4 unambiguous characters.
"""

from __future__ import annotations

import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 12
MAX_LENGTH = 256  # hashing a huge input is a cheap way to burn CPU

_hasher = PasswordHasher()
# Verifying against this when the username is unknown keeps the response time the same (no enumeration).
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

# Passwords of 12+ characters that appear high in public breach lists, plus SIMOLA-specific guesses.
COMMON = frozenset(
    {
        "123456789012",
        "1234567890ab",
        "1234567890qw",
        "12345678910a",
        "000000000000",
        "111111111111",
        "123123123123",
        "abc123abc123",
        "qwertyuiop12",
        "qwertyuiop123",
        "qwerty123456",
        "1qaz2wsx3edc",
        "1q2w3e4r5t6y",
        "asdfghjkl123",
        "zxcvbnm12345",
        "password1234",
        "password12345",
        "password123!",
        "passwordpassword",
        "iloveyou1234",
        "admin1234567",
        "administrator",
        "letmein12345",
        "welcome12345",
        "welcome2026!",
        "changeme1234",
        "sunshine1234",
        "football1234",
        "baseball1234",
        "superman1234",
        "katasandi123",
        "katasandi1234",
        "rahasia12345",
        "indonesia123",
        "indonesia1945",
        "bismillah123",
        "jakarta12345",
        "bmkg12345678",
        "simola123456",
        "simolasimola",
        "aloptama1234",
        "awoscat3widn",
    }
)
_KEYBOARD_ROWS = ("1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-effort check; with no hash (unknown user) it still spends the same time and fails."""
    if len(password) > MAX_LENGTH:
        return False
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def _pattern(p: str) -> bool:
    low = p.lower()
    if len(set(low)) <= 3:  # "aaaaaaaaaaaa", "abababababab"
        return True
    stripped = re.sub(r"[^a-z0-9]", "", low)
    return any(stripped and stripped in (row * 3) for row in _KEYBOARD_ROWS)


def policy_problem(password: str, username: str) -> str | None:
    """None when the password may be used, else a stable code the UI translates."""
    if len(password) < MIN_LENGTH:
        return "too_short"
    if len(password) > MAX_LENGTH:
        return "too_long"
    if username and username.lower() in password.lower():
        return "contains_username"
    if password.lower() in COMMON or _pattern(password):
        return "weak_password"
    return None


_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i


def temporary_password() -> str:
    """e.g. 'k7mq-3xpt-9wdh-4nvz': 19 characters, about 79 bits, easy to read out by phone."""
    return "-".join("".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(4))
