"""Every API route is classified in tests/permissions.py (FR-AUTH-005)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from tests.permissions import MATRIX


def test_every_route_has_a_permission_entry() -> None:
    os.environ.setdefault("SIMOLA_DATABASE_URL", "postgresql+asyncpg://unused:unused@localhost:1/unused")
    from simola.api.app import create_app

    paths = create_app().openapi()["paths"]
    published = {(m.upper(), p) for p, ops in paths.items() for m in ops}
    assert published - set(MATRIX) == set(), "classify the new routes in tests/permissions.py"
    assert set(MATRIX) - published == set(), "tests/permissions.py lists routes that no longer exist"


def test_the_documented_matrix_matches() -> None:
    """docs/design/permissions.md (PRD §15.4) lists the same routes with the same least role."""
    doc = Path(__file__).resolve().parents[3] / "docs" / "design" / "permissions.md"
    rows = re.findall(r"^\|[^|]*\| `([A-Z]+) (\S+)` \| (Public|Viewer|Admin) \|$", doc.read_text(), re.M)
    documented = {(m, p): need.lower() for m, p, need in rows}
    assert len(documented) == len(rows), "a route is listed twice in docs/design/permissions.md"
    assert documented == MATRIX
