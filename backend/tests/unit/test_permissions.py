"""Every API route is classified in tests/permissions.py (FR-AUTH-005)."""

from __future__ import annotations

import os

from tests.permissions import MATRIX


def test_every_route_has_a_permission_entry() -> None:
    os.environ.setdefault("SIMOLA_DATABASE_URL", "postgresql+asyncpg://unused:unused@localhost:1/unused")
    from simola.api.app import create_app

    paths = create_app().openapi()["paths"]
    published = {(m.upper(), p) for p, ops in paths.items() for m in ops}
    assert published - set(MATRIX) == set(), "classify the new routes in tests/permissions.py"
    assert set(MATRIX) - published == set(), "tests/permissions.py lists routes that no longer exist"
