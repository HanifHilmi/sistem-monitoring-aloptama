"""Sign in, sign out, who am I, change password (FR-AUTH-001..004, docs/design/r2.md §4.1).

Lockout: 5 failed sign-ins for a username within 15 minutes lock it for 15 minutes. A username that does not
exist behaves the same way (same messages, same timing, same lock), so nothing reveals which accounts exist.
An address with 20 failures in 15 minutes is refused until they age out.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from simola.api.deps import ApiError
from simola.api.security import (
    SESSION_COOKIE,
    clear_session,
    client_ip,
    csrf,
    ensure_csrf_cookie,
    principal,
    require_signed_in,
    start_session,
)
from simola.auth import audit, passwords, sessions
from simola.auth.sessions import Principal
from simola.core.db import get_engine

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

WINDOW = timedelta(minutes=15)
FAILURES_TO_LOCK = 5
LOCK_FOR = timedelta(minutes=15)
ADDRESS_LIMIT = 20


class LoginBody(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=passwords.MAX_LENGTH)


class PasswordBody(BaseModel):
    current_password: str = Field(max_length=passwords.MAX_LENGTH)
    new_password: str = Field(max_length=passwords.MAX_LENGTH)


@router.get("/me")
async def me(request: Request) -> JSONResponse:
    """The signed-in user, or null for a visitor. Not 401: browsers log every 401 as an error, and every
    public page asks. Also hands out the CSRF cookie the sign-in form needs."""
    user = await principal(request)
    response = JSONResponse(user.public() if user else None)
    ensure_csrf_cookie(request, response)
    return response


async def _failures(conn: AsyncConnection, column: str, value: str, since: datetime) -> int:
    assert column in ("entity_id", "source_ip")
    return int(
        await conn.scalar(
            text(
                f"SELECT count(*) FROM audit_event WHERE action = 'login_failed' AND {column} = :v AND time > :t"
            ),
            {"v": value, "t": since},
        )
        or 0
    )


@router.post("/login", dependencies=[Depends(csrf)])
async def login(body: LoginBody, request: Request) -> JSONResponse:
    now = datetime.now(UTC)
    ip = client_ip(request)
    username = body.username.strip().lower()
    refused: ApiError | None = None  # raised after the transaction commits, so failures are recorded
    user: Principal | None = None
    token = ""
    async with get_engine().begin() as conn:
        if ip and await _failures(conn, "source_ip", ip, now - WINDOW) >= ADDRESS_LIMIT:
            raise ApiError(429, "too_many_attempts", "too many failed sign-ins from this address")
        row = (
            (
                await conn.execute(
                    text("""
            SELECT id, username, display_name, role, active, password_hash, must_change_password,
                   locked_until, failures_reset_at
            FROM app_user WHERE username = :u FOR UPDATE
        """),
                    {"u": username},
                )
            )
            .mappings()
            .first()
        )
        account = row if row is not None and row["active"] else None
        since = max(now - WINDOW, account["failures_reset_at"]) if account else now - WINDOW
        if account:
            locked = account["locked_until"] is not None and account["locked_until"] > now
        else:
            locked = await _failures(conn, "entity_id", username, since) >= FAILURES_TO_LOCK

        async def failed(reason: str) -> None:
            await audit.record(
                conn,
                "login_failed",
                actor=None,
                entity_type="user",
                entity_id=username,
                after={"reason": reason},
                source_ip=ip,
            )

        if locked:
            await failed("locked")
            refused = ApiError(423, "account_locked", "too many failed sign-ins; try again later")
        elif not await asyncio.to_thread(
            passwords.verify_password, account["password_hash"] if account else None, body.password
        ):
            await failed("password")
            if account and await _failures(conn, "entity_id", username, since) >= FAILURES_TO_LOCK:
                until = now + LOCK_FOR
                await conn.execute(
                    text("UPDATE app_user SET locked_until = :until WHERE id = :id"),
                    {"until": until, "id": account["id"]},
                )
                await audit.record(
                    conn,
                    "account_locked",
                    actor=None,
                    entity_type="user",
                    entity_id=username,
                    after={"locked_until": until.isoformat()},
                    source_ip=ip,
                )
            refused = ApiError(401, "invalid_credentials", "username or password is wrong")
        elif account:
            params: dict[str, Any] = {"id": account["id"], "now": now}
            rehash = ""
            if passwords.needs_rehash(account["password_hash"]):
                params["hash"] = await asyncio.to_thread(passwords.hash_password, body.password)
                rehash = ", password_hash = :hash"
            await conn.execute(
                text(
                    "UPDATE app_user SET last_login_at = :now, locked_until = NULL, failures_reset_at = :now"
                    f"{rehash} WHERE id = :id"
                ),
                params,
            )
            token = await sessions.create(conn, account["id"], now, ip, request.headers.get("user-agent"))
            await audit.record(
                conn, "login_ok", actor=account["username"], entity_type="session", source_ip=ip
            )
            user = Principal(
                id=account["id"],
                username=account["username"],
                display_name=account["display_name"],
                role=account["role"],
                must_change_password=account["must_change_password"],
            )
    if refused or user is None:
        raise refused or ApiError(401, "invalid_credentials", "username or password is wrong")
    response = JSONResponse(user.public())
    start_session(response, token)
    return response


@router.post("/logout", status_code=204, dependencies=[Depends(csrf)])
async def logout(request: Request) -> Response:
    user = await principal(request)
    async with get_engine().begin() as conn:
        await sessions.end(conn, request.cookies.get(SESSION_COOKIE))
        if user:
            await audit.record(
                conn, "logout", actor=user.username, entity_type="session", source_ip=client_ip(request)
            )
    response = Response(status_code=204)
    clear_session(response)
    return response


@router.post("/password", dependencies=[Depends(csrf)])
async def change_password(
    body: PasswordBody,
    request: Request,
    user: Principal = Depends(require_signed_in),
) -> dict[str, Any]:
    """Change one's own password; the user's other sessions are signed out."""
    async with get_engine().begin() as conn:
        current_hash = await conn.scalar(
            text("SELECT password_hash FROM app_user WHERE id = :id FOR UPDATE"), {"id": user.id}
        )
        if not await asyncio.to_thread(passwords.verify_password, current_hash, body.current_password):
            raise ApiError(400, "wrong_password", "the current password is wrong")
        problem = passwords.policy_problem(body.new_password, user.username)
        if problem:
            raise ApiError(400, problem, "the new password does not meet the rules")
        if body.new_password == body.current_password:
            raise ApiError(400, "same_password", "choose a password different from the current one")
        new_hash = await asyncio.to_thread(passwords.hash_password, body.new_password)
        await conn.execute(
            text("""
            UPDATE app_user SET password_hash = :h, must_change_password = false, password_changed_at = now()
            WHERE id = :id
        """),
            {"h": new_hash, "id": user.id},
        )
        await sessions.end_all(conn, user.id, keep_token=request.cookies.get(SESSION_COOKIE))
        await audit.record(
            conn,
            "password_changed",
            actor=user.username,
            entity_type="user",
            entity_id=user.username,
            source_ip=client_ip(request),
        )
    return {**user.public(), "must_change_password": False}
