"""Who is asking, and may they (FR-AUTH-002, FR-AUTH-005, PRD §11.6).

- Session: the `simola_session` cookie (HttpOnly, Secure, SameSite=Lax) names a server-side session.
- CSRF: double submit. `simola_csrf` is a readable cookie; every POST, PUT, PATCH and DELETE must repeat its
  value in the `X-CSRF-Token` header. A page on another site can send the cookie but cannot read it.
- Roles: `require("viewer")` or `require("admin")` on a router or route. The server decides; the UI only hides.
"""

from __future__ import annotations

import ipaddress
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal

from fastapi import Request, Response

from simola.api.deps import ApiError
from simola.auth import sessions
from simola.auth.sessions import LIFETIME, Principal
from simola.core.db import get_engine

SESSION_COOKIE = "simola_session"
CSRF_COOKIE = "simola_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Signed-in users who still have a temporary password may only do this much (FR-AUTH-003).
PASSWORD_CHANGE_PATHS = frozenset({"/api/v1/auth/me", "/api/v1/auth/password", "/api/v1/auth/logout"})
Role = Literal["viewer", "admin"]


def client_ip(request: Request) -> str | None:
    """The browser's address: Cloudflare's header, else the first X-Forwarded-For hop, else the peer.

    Used for the audit log and the per-address sign-in limit only; account lockout does not depend on it.
    """
    for candidate in (
        request.headers.get("cf-connecting-ip"),
        (request.headers.get("x-forwarded-for") or "").split(",")[0],
        request.client.host if request.client else None,
    ):
        if candidate:
            try:
                return str(ipaddress.ip_address(candidate.strip()))
            except ValueError:
                continue
    return None


async def principal(request: Request) -> Principal | None:
    """The signed-in user, looked up once per request on its own short connection."""
    if hasattr(request.state, "principal"):
        cached: Principal | None = request.state.principal
        return cached
    token = request.cookies.get(SESSION_COOKIE)
    found = None
    if token:
        async with get_engine().begin() as conn:
            found = await sessions.lookup(conn, token, datetime.now(UTC))
    request.state.principal = found
    return found


def require(role: Role, *, allow_password_change: bool = False) -> Callable[[Request], Awaitable[Principal]]:
    async def dependency(request: Request) -> Principal:
        user = await principal(request)
        if user is None:
            raise ApiError(401, "not_authenticated", "sign in first")
        if user.must_change_password and not allow_password_change:
            if request.url.path not in PASSWORD_CHANGE_PATHS:
                raise ApiError(403, "password_change_required", "choose a new password first")
        if role == "admin" and not user.is_admin:
            raise ApiError(403, "forbidden", "Admins only")
        return user

    return dependency


require_viewer = require("viewer")
require_admin = require("admin")
# Changing one's password must work while it is still the temporary one.
require_signed_in = require("viewer", allow_password_change=True)


async def csrf(request: Request) -> None:
    """Rejects a state-changing request whose header does not repeat the CSRF cookie."""
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE) or ""
    header = request.headers.get(CSRF_HEADER) or ""
    if not cookie or not secrets.compare_digest(cookie, header):
        raise ApiError(403, "csrf_failed", "missing or wrong CSRF token; reload the page")


def _cookie(response: Response, name: str, value: str, *, http_only: bool) -> None:
    response.set_cookie(
        name,
        value,
        max_age=int(LIFETIME.total_seconds()),
        path="/",
        secure=True,
        httponly=http_only,
        samesite="lax",
    )


def ensure_csrf_cookie(request: Request, response: Response) -> None:
    if not request.cookies.get(CSRF_COOKIE):
        _cookie(response, CSRF_COOKIE, secrets.token_urlsafe(24), http_only=False)


def start_session(response: Response, token: str) -> None:
    _cookie(response, SESSION_COOKIE, token, http_only=True)
    # A fresh CSRF token with every sign-in.
    _cookie(response, CSRF_COOKIE, secrets.token_urlsafe(24), http_only=False)


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
