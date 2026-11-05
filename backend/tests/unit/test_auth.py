"""Passwords, temporary passwords, client addresses, CSV cells and audit diffs (FR-AUTH-003/004, FR-AUD)."""

from __future__ import annotations

import re

import pytest
from starlette.requests import Request

from simola.api.routers.admin import _csv_cell
from simola.api.security import client_ip
from simola.auth import audit, passwords, sessions


def test_hash_and_verify() -> None:
    h = passwords.hash_password("stasiun-cuaca-2026")
    assert h.startswith("$argon2id$")
    assert passwords.verify_password(h, "stasiun-cuaca-2026")
    assert not passwords.verify_password(h, "stasiun-cuaca-2027")
    assert not passwords.needs_rehash(h)


def test_unknown_user_or_bad_hash_never_verifies() -> None:
    assert not passwords.verify_password(None, "anything-at-all")
    assert not passwords.verify_password("not-a-hash", "anything-at-all")
    h = passwords.hash_password("x" * 20)
    assert not passwords.verify_password(h, "x" * (passwords.MAX_LENGTH + 1))


@pytest.mark.parametrize(
    ("password", "username", "problem"),
    [
        ("short-pass1", "andi", "too_short"),
        ("andi-sang-teknisi", "andi", "contains_username"),
        ("ANDI-sang-teknisi", "andi", "contains_username"),
        ("password1234", "budi", "weak_password"),
        ("Indonesia1945", "budi", "weak_password"),
        ("qwertyuiopqw", "budi", "weak_password"),
        ("aaaaaaaaaaaaaa", "budi", "weak_password"),
        ("abababababab", "budi", "weak_password"),
        ("x" * (passwords.MAX_LENGTH + 1), "budi", "too_long"),
        ("stasiun-cuaca-2026", "budi", None),
        ("correct horse battery", "budi", None),
    ],
)
def test_password_rules(password: str, username: str, problem: str | None) -> None:
    assert passwords.policy_problem(password, username) == problem


def test_temporary_passwords_are_readable_and_pass_the_rules() -> None:
    seen = {passwords.temporary_password() for _ in range(200)}
    assert len(seen) == 200
    for p in seen:
        assert re.fullmatch(r"[a-hjkmnp-z2-9]{4}(-[a-hjkmnp-z2-9]{4}){3}", p), p
        assert passwords.policy_problem(p, "joko") is None


def _request(headers: dict[str, str], peer: str | None = "10.9.8.7") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": (peer, 1234) if peer else None,
        }
    )


def test_client_address_prefers_cloudflare_then_forwarded_then_peer() -> None:
    assert client_ip(_request({"CF-Connecting-IP": "198.51.100.7", "X-Forwarded-For": "203.0.113.1"})) == (
        "198.51.100.7"
    )
    assert client_ip(_request({"X-Forwarded-For": "203.0.113.1, 192.0.2.2"})) == "203.0.113.1"
    assert client_ip(_request({})) == "10.9.8.7"
    assert client_ip(_request({"CF-Connecting-IP": "not-an-address"})) == "10.9.8.7"
    assert client_ip(_request({}, peer=None)) is None


@pytest.mark.parametrize(
    ("value", "cell"),
    [
        (None, ""),
        ("andi", "andi"),
        ("=HYPERLINK(1)", "'=HYPERLINK(1)"),
        ("+1", "'+1"),
        ("-1", "'-1"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ({"role": "admin"}, '{"role": "admin"}'),
    ],
)
def test_csv_cells_never_run_as_formulas(value: object, cell: str) -> None:
    assert _csv_cell(value) == cell


def test_audit_diff_keeps_only_changes() -> None:
    before, after = audit.diff(
        {"role": "viewer", "active": True, "email": None}, {"role": "admin", "active": True, "email": None}
    )
    assert (before, after) == ({"role": "viewer"}, {"role": "admin"})


def test_session_tokens_are_stored_as_hashes() -> None:
    h = sessions.token_hash("abc")
    assert len(h) == 32 and h == sessions.token_hash("abc") and h != sessions.token_hash("abd")
