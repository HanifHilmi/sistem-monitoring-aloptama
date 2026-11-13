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
    ("GET", "/api/v1/systems/{code}/flags"): "public",  # note and author only for signed-in users
    ("GET", "/api/v1/systems/{code}/detections"): "public",  # suspect and rejected only for signed-in users
    ("GET", "/api/v1/systems/{code}/assets"): "public",  # serial and part numbers only for signed-in users
    ("GET", "/api/v1/systems/{code}/trace"): "viewer",
    (
        "GET",
        "/api/v1/systems/{code}/data-quality",
    ): "public",  # the suspect count only for signed-in users (D7)
    ("GET", "/api/v1/definitions"): "public",
    ("GET", "/api/v1/systems/{code}/reports/latest"): "public",  # METAR, MET REPORT and TAF (FR-RPT)
    ("GET", "/api/v1/systems/{code}/reports"): "public",
    ("GET", "/api/v1/systems/{code}/reports/search"): "public",
    # AWOS alarms are for signed-in users only; the public does not even see the count (OPEN-13).
    ("GET", "/api/v1/systems/{code}/alarms/active"): "viewer",
    ("GET", "/api/v1/systems/{code}/alarms"): "viewer",
    # CSV exports are for Viewers and Admins, and audited (FR-EXP-003).
    ("GET", "/api/v1/systems/{code}/exports/daily.csv"): "viewer",
    ("GET", "/api/v1/systems/{code}/exports/minutes.csv"): "viewer",
    ("GET", "/api/v1/systems/{code}/exports/alarms.csv"): "viewer",
    ("GET", "/api/v1/systems/{code}/exports/quality.csv"): "viewer",
    ("POST", "/api/v1/systems/{code}/exports/monthly-report"): "viewer",  # the monthly PDF (FR-EXP-001)
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
    ("GET", "/api/v1/admin/jobs"): "admin",
    ("POST", "/api/v1/admin/jobs"): "admin",
    ("GET", "/api/v1/admin/jobs/{job_id}"): "admin",
    ("POST", "/api/v1/admin/jobs/{job_id}/cancel"): "admin",
    ("GET", "/api/v1/admin/settings"): "admin",
    ("PUT", "/api/v1/admin/settings/{key}"): "admin",
    ("GET", "/api/v1/admin/mandatory-fields"): "admin",
    ("GET", "/api/v1/admin/mandatory-fields/{component_type}/preview"): "admin",
    ("PUT", "/api/v1/admin/mandatory-fields/{component_type}"): "admin",
    ("GET", "/api/v1/admin/components"): "admin",
    ("PATCH", "/api/v1/admin/components/{component_id}"): "admin",
    ("GET", "/api/v1/admin/flags"): "admin",
    ("GET", "/api/v1/admin/flags/preview"): "admin",
    ("POST", "/api/v1/admin/flags"): "admin",
    ("PATCH", "/api/v1/admin/flags/{flag_id}"): "admin",
    ("DELETE", "/api/v1/admin/flags/{flag_id}"): "admin",
    ("GET", "/api/v1/admin/rules"): "admin",
    ("GET", "/api/v1/admin/rules/history"): "admin",
    ("GET", "/api/v1/admin/rules/dry-run"): "admin",
    ("GET", "/api/v1/admin/rules/{rule_id}/versions"): "admin",
    ("POST", "/api/v1/admin/rules"): "admin",
    ("PUT", "/api/v1/admin/rules/{rule_id}"): "admin",
    ("DELETE", "/api/v1/admin/rules/{rule_id}"): "admin",
    ("GET", "/api/v1/admin/detections"): "admin",
    ("POST", "/api/v1/admin/detections/decide"): "admin",
    ("GET", "/api/v1/admin/station"): "admin",
    ("PUT", "/api/v1/admin/station"): "admin",
    ("PUT", "/api/v1/admin/sites/{slug}"): "admin",
    ("PUT", "/api/v1/admin/components/{component_id}/meta"): "admin",
    ("GET", "/api/v1/admin/components/{component_id}/calibrations"): "admin",
    ("POST", "/api/v1/admin/calibrations"): "admin",
    ("PATCH", "/api/v1/admin/calibrations/{cal_id}"): "admin",
    ("DELETE", "/api/v1/admin/calibrations/{cal_id}"): "admin",
    ("GET", "/api/v1/admin/alarm-names"): "admin",
    ("PUT", "/api/v1/admin/alarm-names/{name}"): "admin",
}

# Sample values for path parameters. The matrix test sends {} as every write's body, which is invalid or
# changes nothing, so no Admin call in it alters data.
PATH_VALUES = {
    "code": "WIDN-CAT3",
    "slug": "04",
    "component": "ATRH",
    "job_id": "1",
    "key": "grace_minutes",
    "component_type": "ATRH",
    "component_id": "2",
    "flag_id": "999999",  # no such flag: the Admin call answers 404 and removes nothing
    "rule_id": "999999",  # no such rule: nothing changes
    "cal_id": "999999",  # no such calibration: nothing is removed
    "name": "NoSuchAlarm",  # no such alarm name: nothing is re-mapped
}
