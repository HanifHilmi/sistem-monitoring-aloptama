"""Admin area API (FR-ADM-001): accounts (FR-AUTH-007) and the audit log (FR-AUD-002).

Every route needs an Admin; every change needs the CSRF header and is audited in the same transaction.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.api.deps import ApiError, parse_instant
from simola.api.security import client_ip, csrf, require_admin
from simola.auth import audit, passwords, sessions
from simola.auth.sessions import Principal
from simola.core.db import get_engine

router = APIRouter(
    prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin), Depends(csrf)]
)

USERNAME = r"^[a-z0-9][a-z0-9._-]{2,31}$"
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
USER_COLUMNS = """id, username, display_name, email, role, active,
    CASE WHEN locked_until > now() THEN locked_until END AS locked_until,
    must_change_password AS password_temporary, last_login_at, created_at"""


class NewUser(BaseModel):
    username: str = Field(pattern=USERNAME)
    display_name: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=200, pattern=EMAIL)
    role: Literal["viewer", "admin"]


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=200, pattern=EMAIL)
    role: Literal["viewer", "admin"] | None = None
    active: bool | None = None


async def _user(conn: AsyncConnection, user_id: int, *, lock: bool = False) -> dict[str, Any]:
    row = (
        (
            await conn.execute(
                text(f"SELECT {USER_COLUMNS} FROM app_user WHERE id = :id{' FOR UPDATE' if lock else ''}"),
                {"id": user_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ApiError(404, "user_not_found", "no such user")
    return dict(row)


# ------------------------------------------------------------------------------------------ users


@router.get("/users")
async def list_users() -> list[dict[str, Any]]:
    async with get_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(f"SELECT {USER_COLUMNS} FROM app_user ORDER BY active DESC, display_name")
            )
        ).mappings()
        return [dict(r) for r in rows]


@router.post("/users", status_code=201)
async def create_user(
    body: NewUser, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    temporary = passwords.temporary_password()
    password_hash = await asyncio.to_thread(passwords.hash_password, temporary)
    email = body.email or None
    try:
        async with get_engine().begin() as conn:
            user_id = await conn.scalar(
                text("""
                INSERT INTO app_user (username, display_name, email, role, password_hash, must_change_password,
                                      created_by)
                VALUES (:u, :n, :e, :r, :h, true, :by) RETURNING id
            """),
                {
                    "u": body.username,
                    "n": body.display_name.strip(),
                    "e": email,
                    "r": body.role,
                    "h": password_hash,
                    "by": admin.username,
                },
            )
            await audit.record(
                conn,
                "user_created",
                actor=admin.username,
                entity_type="user",
                entity_id=body.username,
                after={
                    "username": body.username,
                    "display_name": body.display_name.strip(),
                    "email": email,
                    "role": body.role,
                    "active": True,
                },
                source_ip=client_ip(request),
            )
            user = await _user(conn, int(user_id))
    except IntegrityError as exc:
        raise ApiError(409, "username_taken", "this username is already used") from exc
    return {"user": user, "temporary_password": temporary}


@router.patch("/users/{user_id}")
async def update_user(
    user_id: int, body: UserPatch, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if "email" in changes:
        changes["email"] = changes["email"] or None
    if "display_name" in changes:
        changes["display_name"] = changes["display_name"].strip()
    async with get_engine().begin() as conn:
        # Lock every active Admin row: two Admins demoting each other at once must not leave none.
        await conn.execute(text("SELECT id FROM app_user WHERE role = 'admin' AND active FOR UPDATE"))
        current = await _user(conn, user_id, lock=True)
        after_state = {**current, **changes}
        losing_admin = (
            current["role"] == "admin"
            and current["active"]
            and not (after_state["role"] == "admin" and after_state["active"])
        )
        if losing_admin and user_id == admin.id:
            raise ApiError(409, "own_account", "you can't deactivate or demote your own account")
        if losing_admin:
            others = await conn.scalar(
                text("SELECT count(*) FROM app_user WHERE role = 'admin' AND active AND id <> :id"),
                {"id": user_id},
            )
            if not others:
                raise ApiError(409, "last_admin", "SIMOLA needs at least one active Admin")
        before, after = audit.diff(current, {k: after_state[k] for k in changes})
        if after:
            sets = ", ".join(f"{k} = :{k}" for k in after)
            await conn.execute(text(f"UPDATE app_user SET {sets} WHERE id = :id"), {**after, "id": user_id})
            if after.get("active") is False:
                await sessions.end_all(conn, user_id)
            await audit.record(
                conn,
                "user_updated",
                actor=admin.username,
                entity_type="user",
                entity_id=current["username"],
                before=before,
                after=after,
                source_ip=client_ip(request),
            )
        return await _user(conn, user_id)


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: int, request: Request, admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """A temporary password, shown once; the user is signed out everywhere and must change it at sign-in."""
    temporary = passwords.temporary_password()
    password_hash = await asyncio.to_thread(passwords.hash_password, temporary)
    async with get_engine().begin() as conn:
        current = await _user(conn, user_id, lock=True)
        await conn.execute(
            text("""
            UPDATE app_user SET password_hash = :h, must_change_password = true, locked_until = NULL,
                   failures_reset_at = now(), password_changed_at = now()
            WHERE id = :id
        """),
            {"h": password_hash, "id": user_id},
        )
        await sessions.end_all(conn, user_id)
        await audit.record(
            conn,
            "password_reset",
            actor=admin.username,
            entity_type="user",
            entity_id=current["username"],
            source_ip=client_ip(request),
        )
        user = await _user(conn, user_id)
    return {"user": user, "temporary_password": temporary}


# ------------------------------------------------------------------------------------------ audit

AUDIT_COLUMNS = "id, time, actor, action, entity_type, entity_id, before, after, source_ip"
CSV_LIMIT = 100_000


def _audit_filter(
    from_: str | None, to: str | None, actor: str | None, action: str | None, entity_type: str | None
) -> tuple[str, dict[str, Any]]:
    where: list[str] = ["true"]
    params: dict[str, Any] = {}
    if from_:
        where.append("time >= :from_")
        params["from_"] = parse_instant(from_, "from")
    if to:
        where.append("time < :to")
        params["to"] = parse_instant(to, "to")
    for name, value in (("actor", actor), ("action", action), ("entity_type", entity_type)):
        if value:
            where.append(f"{name} = :{name}")
            params[name] = value
    return " AND ".join(where), params


def _csv_cell(value: Any) -> str:
    """A cell a spreadsheet will not run as a formula."""
    if value is None:
        return ""
    s = json.dumps(value, ensure_ascii=False) if isinstance(value, dict | list) else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


@router.get("/audit", response_model=None)
async def audit_log(
    request: Request,
    admin: Principal = Depends(require_admin),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    before: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    format: Literal["json", "csv"] = "json",
) -> dict[str, Any] | Response:
    where, params = _audit_filter(from_, to, actor, action, entity_type)
    if format == "csv":
        async with get_engine().begin() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            f"SELECT {AUDIT_COLUMNS} FROM audit_event WHERE {where} ORDER BY id LIMIT {CSV_LIMIT}"
                        ),
                        params,
                    )
                )
                .mappings()
                .all()
            )
            await audit.record(
                conn,
                "audit_exported",
                actor=admin.username,
                entity_type="audit",
                after={"rows": len(rows), "filter": {k: str(v) for k, v in params.items()}},
                source_ip=client_ip(request),
            )
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(AUDIT_COLUMNS.split(", "))
        for r in rows:
            writer.writerow([_csv_cell(r[c]) for c in AUDIT_COLUMNS.split(", ")])
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%MZ")
        return Response(
            out.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="simola-audit-{stamp}.csv"'},
        )
    if before:
        where += " AND id < :before"
        params["before"] = before
    async with get_engine().connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        f"SELECT {AUDIT_COLUMNS} FROM audit_event WHERE {where} ORDER BY id DESC LIMIT :lim"
                    ),
                    {**params, "lim": limit + 1},
                )
            )
            .mappings()
            .all()
        )
        actors = (
            await conn.execute(text("SELECT DISTINCT actor FROM audit_event WHERE actor IS NOT NULL"))
        ).scalars()
        actions = (await conn.execute(text("SELECT DISTINCT action FROM audit_event"))).scalars()
        events = [dict(r) for r in rows[:limit]]
        return {
            "events": events,
            "next_before": events[-1]["id"] if len(rows) > limit else None,
            "actors": sorted(actors),
            "actions": sorted(actions),
        }
