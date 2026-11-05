"""Server-side sessions (FR-AUTH-002, PRD §11.6).

The browser holds a random token in an HttpOnly cookie; the database holds only its SHA-256. A session ends
after 8 h without use or 7 days after sign-in, whichever comes first, and at sign-out.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

IDLE = timedelta(hours=8)
LIFETIME = timedelta(days=7)
TOUCH_EVERY = timedelta(minutes=1)  # last_seen_at is refreshed at most this often


@dataclass(frozen=True)
class Principal:
    """The signed-in user of a request."""

    id: int
    username: str
    display_name: str
    role: str
    must_change_password: bool

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "must_change_password": self.must_change_password,
        }


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


async def create(
    conn: AsyncConnection, user_id: int, now: datetime, source_ip: str | None, user_agent: str | None
) -> str:
    token = secrets.token_urlsafe(32)
    await conn.execute(
        text("""
        INSERT INTO user_session (token_hash, user_id, created_at, last_seen_at, expires_at, source_ip, user_agent)
        VALUES (:h, :u, :now, :now, :exp, :ip, :ua)
    """),
        {
            "h": token_hash(token),
            "u": user_id,
            "now": now,
            "exp": now + LIFETIME,
            "ip": source_ip,
            "ua": (user_agent or "")[:300] or None,
        },
    )
    # Housekeeping: expired sessions of anyone go when someone signs in.
    await conn.execute(
        text("DELETE FROM user_session WHERE expires_at < :now OR last_seen_at < :idle"),
        {"now": now, "idle": now - IDLE},
    )
    return token


async def lookup(conn: AsyncConnection, token: str | None, now: datetime) -> Principal | None:
    """The active user behind a session token, or None. Refreshes the idle timer."""
    if not token or len(token) > 100:
        return None
    h = token_hash(token)
    row = (
        (
            await conn.execute(
                text("""
        SELECT u.id, u.username, u.display_name, u.role, u.must_change_password, u.active,
               s.last_seen_at, s.expires_at
        FROM user_session s JOIN app_user u ON u.id = s.user_id
        WHERE s.token_hash = :h
    """),
                {"h": h},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    if not row["active"] or row["expires_at"] <= now or row["last_seen_at"] <= now - IDLE:
        await conn.execute(text("DELETE FROM user_session WHERE token_hash = :h"), {"h": h})
        return None
    if now - row["last_seen_at"] >= TOUCH_EVERY:
        await conn.execute(
            text("UPDATE user_session SET last_seen_at = :now WHERE token_hash = :h"), {"now": now, "h": h}
        )
    return Principal(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        role=row["role"],
        must_change_password=row["must_change_password"],
    )


async def end(conn: AsyncConnection, token: str | None) -> None:
    if token:
        await conn.execute(text("DELETE FROM user_session WHERE token_hash = :h"), {"h": token_hash(token)})


async def end_all(conn: AsyncConnection, user_id: int, keep_token: str | None = None) -> None:
    """Signs a user out everywhere (password change keeps the current session; reset and deactivation don't)."""
    if keep_token:
        await conn.execute(
            text("DELETE FROM user_session WHERE user_id = :u AND token_hash <> :h"),
            {"u": user_id, "h": token_hash(keep_token)},
        )
    else:
        await conn.execute(text("DELETE FROM user_session WHERE user_id = :u"), {"u": user_id})
