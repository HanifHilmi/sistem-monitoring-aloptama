"""PRD §5.4 as a table: the least role each API route needs (FR-AUTH-005).

tests/unit/test_permissions.py fails when a route is missing here, so a new route cannot ship unclassified;
tests/integration/test_accounts.py calls every route as public, Viewer and Admin and checks the answers.
"""

from __future__ import annotations

from typing import Literal

Need = Literal["public", "viewer", "admin"]

MATRIX: dict[tuple[str, str], Need] = {
    ("GET", "/health"): "public",
    ("GET", "/ready"): "public",
    ("GET", "/api/v1/settings/display"): "public",
    ("GET", "/api/v1/systems"): "public",
    ("GET", "/api/v1/systems/{code}"): "public",
    ("GET", "/api/v1/systems/{code}/kpis"): "public",
    ("GET", "/api/v1/systems/{code}/status"): "public",
    ("GET", "/api/v1/systems/{code}/problems"): "public",
    ("GET", "/api/v1/systems/{code}/history"): "public",
    ("GET", "/api/v1/systems/{code}/calendar"): "public",
    ("GET", "/api/v1/systems/{code}/sites/{slug}/components/{component}/series"): "public",
    ("GET", "/api/v1/systems/{code}/matrix"): "public",
    ("GET", "/api/v1/systems/{code}/outages"): "public",
    ("GET", "/api/v1/systems/{code}/minutes"): "public",
    ("GET", "/api/v1/auth/me"): "public",  # null when nobody is signed in
    ("POST", "/api/v1/auth/login"): "public",
    ("POST", "/api/v1/auth/logout"): "public",
    ("POST", "/api/v1/auth/password"): "viewer",
    ("GET", "/api/v1/internal/health"): "viewer",
    ("GET", "/api/v1/admin/users"): "admin",
    ("POST", "/api/v1/admin/users"): "admin",
    ("PATCH", "/api/v1/admin/users/{user_id}"): "admin",
    ("POST", "/api/v1/admin/users/{user_id}/reset-password"): "admin",
    ("GET", "/api/v1/admin/audit"): "admin",
}

# Sample values for path parameters.
PATH_VALUES = {"code": "WIDN-CAT3", "slug": "04", "component": "ATRH"}
