"""Accounts, sessions, lockout, the audit log and the permission matrix against a real database (R2.1)."""

from __future__ import annotations

import itertools
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from simola.api.app import create_app
from simola.auth import passwords
from simola.core.config import get_settings
from simola.migrations.runner import ensure_app_role
from tests.integration.conftest import LEAK_PROBE_ADDRESS
from tests.permissions import MATRIX, PATH_VALUES

pytestmark = pytest.mark.integration

PW = "stasiun-cuaca-2026"
_addresses = (f"198.51.100.{n}" for n in itertools.count(10))  # RFC 5737; one per browser keeps limits apart


class Browser:
    """One browser: its own cookies and address. Writes carry the CSRF header unless told otherwise."""

    def __init__(self, address: str | None = None) -> None:
        self.c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()),
            base_url="https://testserver",
            headers={"cf-connecting-ip": address or next(_addresses)},
        )

    async def __aenter__(self) -> Browser:
        await self.c.get("/api/v1/auth/me")  # picks up the CSRF cookie, like the app on startup
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.c.aclose()

    async def get(self, path: str, **kw: Any) -> httpx.Response:
        return await self.c.get(path, **kw)

    async def send(self, method: str, path: str, json: Any = None, *, csrf: bool = True) -> httpx.Response:
        headers = {"x-csrf-token": self.c.cookies.get("simola_csrf", "")} if csrf else {}
        return await self.c.request(method, path, json=json, headers=headers)

    async def login(self, username: str, password: str = PW) -> httpx.Response:
        return await self.send("POST", "/api/v1/auth/login", {"username": username, "password": password})


async def _add_user(engine: AsyncEngine, username: str, role: str, *, must_change: bool = False) -> int:
    async with engine.begin() as conn:
        return int(
            await conn.scalar(
                text("""
            INSERT INTO app_user (username, display_name, role, password_hash, must_change_password, created_by)
            VALUES (:u, :n, :r, :h, :m, 'test') RETURNING id
        """),
                {
                    "u": username,
                    "n": username.title(),
                    "r": role,
                    "h": passwords.hash_password(PW),
                    "m": must_change,
                },
            )
        )


@pytest.fixture(scope="module")
async def people(engine: AsyncEngine) -> dict[str, int]:
    return {
        "admin": await _add_user(engine, "t-admin", "admin"),
        "viewer": await _add_user(engine, "t-viewer", "viewer"),
    }


async def test_csrf_cookie_comes_first_and_writes_need_its_header(people: dict[str, int]) -> None:
    async with Browser() as b:
        r = await b.get("/api/v1/auth/me")
        assert r.status_code == 200 and r.json() is None  # a visitor: nobody signed in
        assert b.c.cookies.get("simola_csrf")
        r = await b.send("POST", "/api/v1/auth/login", {"username": "t-admin", "password": PW}, csrf=False)
        assert r.status_code == 403 and r.json()["code"] == "csrf_failed"


async def test_sign_in_sets_safe_cookies_and_sign_out_kills_a_copied_one(people: dict[str, int]) -> None:
    async with Browser() as b:
        r = await b.login("t-admin")
        assert r.status_code == 200 and r.json()["role"] == "admin"
        cookie = next(h for h in r.headers.get_list("set-cookie") if h.startswith("simola_session="))
        assert "HttpOnly" in cookie and "Secure" in cookie and "samesite=lax" in cookie.lower()
        assert (await b.get("/api/v1/auth/me")).json()["username"] == "t-admin"
        stolen = b.c.cookies.get("simola_session")
        assert (await b.send("POST", "/api/v1/auth/logout")).status_code == 204
    async with Browser() as thief:
        thief.c.cookies.set("simola_session", stolen or "", domain="testserver")
        assert (await thief.get("/api/v1/auth/me")).json() is None


async def test_a_wrong_password_and_an_unknown_user_look_the_same(people: dict[str, int]) -> None:
    async with Browser() as b:
        known = await b.login("t-viewer", "wrong-password-1")
        unknown = await b.login("nobody-here", "wrong-password-1")
    assert known.status_code == unknown.status_code == 401
    assert known.json() == unknown.json()


async def test_five_failures_lock_a_username_whether_it_exists_or_not(
    engine: AsyncEngine, people: dict[str, int]
) -> None:
    await _add_user(engine, "t-lockme", "viewer")
    async with Browser() as b:
        for name in ("t-lockme", "ghost-user"):
            for _ in range(5):
                assert (await b.login(name, "wrong-password-1")).status_code == 401
            r = await b.login(name, PW)
            assert r.status_code == 423 and r.json()["code"] == "account_locked"
    async with Browser() as admin:
        await admin.login("t-admin")
        users = {u["username"]: u for u in (await admin.get("/api/v1/admin/users")).json()}
        assert users["t-lockme"]["locked_until"] is not None
        actions = [
            e["action"] for e in (await admin.get("/api/v1/admin/audit?entity_type=user")).json()["events"]
        ]
        assert "account_locked" in actions


async def test_twenty_failures_from_one_address_are_refused(people: dict[str, int]) -> None:
    async with Browser() as b:
        for i in range(20):
            assert (await b.login(f"someone-{i}", "wrong-password-1")).status_code == 401
        r = await b.login("t-admin")
        assert r.status_code == 429 and r.json()["code"] == "too_many_attempts"
    async with Browser() as elsewhere:
        assert (await elsewhere.login("t-admin")).status_code == 200


async def test_new_account_temporary_password_change_and_reset(people: dict[str, int]) -> None:
    async with Browser() as admin:
        await admin.login("t-admin")
        r = await admin.send(
            "POST", "/api/v1/admin/users", {"username": "t-joko", "display_name": "Joko", "role": "viewer"}
        )
        assert r.status_code == 201
        user_id, temporary = r.json()["user"]["id"], r.json()["temporary_password"]
        assert r.json()["user"]["password_temporary"] is True
        dup = await admin.send(
            "POST", "/api/v1/admin/users", {"username": "t-joko", "display_name": "Joko", "role": "viewer"}
        )
        assert dup.status_code == 409 and dup.json()["code"] == "username_taken"

        async with Browser() as joko, Browser() as joko_phone:
            assert (await joko.login("t-joko", temporary)).json()["must_change_password"] is True
            await joko_phone.login("t-joko", temporary)
            r = await joko.get("/api/v1/internal/health")
            assert r.status_code == 403 and r.json()["code"] == "password_change_required"
            weak = await joko.send(
                "POST",
                "/api/v1/auth/password",
                {"current_password": temporary, "new_password": "password1234"},
            )
            assert weak.status_code == 400 and weak.json()["code"] == "weak_password"
            ok = await joko.send(
                "POST",
                "/api/v1/auth/password",
                {"current_password": temporary, "new_password": "hujan-deras-di-runway"},
            )
            assert ok.status_code == 200 and ok.json()["must_change_password"] is False
            health = await joko.get("/api/v1/internal/health")
            assert health.status_code == 200 and LEAK_PROBE_ADDRESS in health.text  # Viewer-level details
            assert (await joko_phone.get("/api/v1/auth/me")).json() is None  # other sessions signed out

            reset = await admin.send("POST", f"/api/v1/admin/users/{user_id}/reset-password")
            assert reset.status_code == 200
            assert (await joko.get("/api/v1/auth/me")).json() is None  # signed out everywhere
            assert (await joko.login("t-joko", "hujan-deras-di-runway")).status_code == 401
            assert (await joko.login("t-joko", reset.json()["temporary_password"])).json()[
                "must_change_password"
            ]


async def test_admins_cannot_lock_themselves_out(people: dict[str, int]) -> None:
    async with Browser() as admin, Browser() as viewer:
        await admin.login("t-admin")
        await viewer.login("t-viewer")
        own = await admin.send("PATCH", f"/api/v1/admin/users/{people['admin']}", {"role": "viewer"})
        assert own.status_code == 409 and own.json()["code"] == "own_account"
        assert (
            await admin.send("PATCH", f"/api/v1/admin/users/{people['admin']}", {"active": False})
        ).status_code == 409
        assert (await viewer.get("/api/v1/admin/users")).status_code == 403
        bad = await admin.send(
            "POST", "/api/v1/admin/users", {"username": "X!", "display_name": "x", "role": "viewer"}
        )
        assert bad.status_code == 422


async def test_audit_log_can_be_read_and_exported_but_never_changed(
    engine: AsyncEngine, people: dict[str, int]
) -> None:
    async with Browser() as admin:
        await admin.login("t-admin")
        page = (await admin.get("/api/v1/admin/audit?action=login_ok&limit=2")).json()
        assert len(page["events"]) == 2 and page["next_before"] is not None
        assert {"login_ok", "login_failed"} <= set(page["actions"])
        older = (await admin.get(f"/api/v1/admin/audit?action=login_ok&before={page['next_before']}")).json()
        assert all(e["id"] < page["next_before"] for e in older["events"])
        csv = await admin.get("/api/v1/admin/audit?format=csv")
        assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
        assert csv.text.splitlines()[0] == "id,time,actor,action,entity_type,entity_id,before,after,source_ip"
        latest = (await admin.get("/api/v1/admin/audit?limit=1")).json()["events"][0]
        assert latest["action"] == "audit_exported" and latest["actor"] == "t-admin"

    for statement in (
        "UPDATE audit_event SET actor = 'x'",
        "DELETE FROM audit_event",
        "TRUNCATE audit_event",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            async with engine.begin() as conn:
                await conn.execute(text(statement))

    await ensure_app_role(get_settings().asyncpg_dsn, "simola_app_test", "app-role-password-for-tests")
    async with engine.connect() as conn:
        rights = (
            await conn.execute(
                text("""
            SELECT has_table_privilege('simola_app_test', 'audit_event', 'INSERT'),
                   has_table_privilege('simola_app_test', 'audit_event', 'UPDATE'),
                   has_table_privilege('simola_app_test', 'audit_event', 'DELETE'),
                   has_table_privilege('simola_app_test', 'app_user', 'UPDATE')
        """)
            )
        ).one()
    assert tuple(rights) == (True, False, False, True)


async def test_every_route_answers_each_role_as_the_prd_says(
    engine: AsyncEngine, people: dict[str, int]
) -> None:
    """FR-AUTH-005: every route called as public, Viewer and Admin, checked against PRD §5.4."""
    target = await _add_user(engine, "t-target", "viewer")
    values = {**PATH_VALUES, "user_id": str(target)}
    async with Browser() as public, Browser() as viewer, Browser() as admin:
        assert (await viewer.login("t-viewer")).status_code == 200
        assert (await admin.login("t-admin")).status_code == 200
        wrong = []
        for (method, path), need in sorted(MATRIX.items()):
            if path == "/api/v1/auth/logout":
                continue  # would sign the test's browsers out; covered above
            url = path.format(**values)
            for role, browser in (("public", public), ("viewer", viewer), ("admin", admin)):
                r = await browser.send(method, url, {} if method != "GET" else None)
                allowed = need == "public" or (need == "viewer" and role != "public") or role == "admin"
                if allowed and r.status_code in (401, 403):
                    wrong.append(f"{role} {method} {path}: refused {r.status_code}")
                if not allowed and r.status_code != (401 if role == "public" else 403):
                    wrong.append(f"{role} {method} {path}: expected refusal, got {r.status_code}")
        assert wrong == []
