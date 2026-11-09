# SIMOLA permission matrix (R3.6, PRD §5.4 and §15.4)

Every API route, the least role it needs, and the PRD §5.4 capability it serves. Public means anyone, without
signing in; Viewer means any signed-in user (Viewer or Admin); Admin means Admins only.

The matrix is enforced, not only written down:

- `backend/tests/permissions.py` holds the same table for the tests. `tests/unit/test_permissions.py` fails
  when a route is missing from it, and when this page and that table disagree, so neither can drift.
- `tests/integration/test_accounts.py` calls every route as the public, a Viewer and an Admin and checks the
  answer (401 without a session, 403 for a Viewer on an Admin route).
- `tools/security_check.py` repeats the public and signed-out checks against a running site (staging).

Routes marked Public still shape their answer by role where §5.4 says so: serial and part numbers (assets),
suspect detections (detections, data-quality), and flag notes and authors are only in a signed-in user's answer.
The public sees the number of active AWOS alarms in the Problems panel, never the list or its message text.

One detail beyond §5.4: a component's **figure change trace** (FR-AUD-003) is open to Viewers, as decided in the R2
design (§4, R2.5). It lists only the audit entries that changed that component's figures in a period; the
audit log itself stays Admin-only.

| PRD §5.4 capability | Route | Least role |
|---|---|---|
| Health checks for the platform | `GET /health` | Public |
|  | `GET /ready` | Public |
| Sign in and out; who is signed in | `GET /api/v1/auth/me` | Public |
|  | `POST /api/v1/auth/login` | Public |
|  | `POST /api/v1/auth/logout` | Public |
| Change one's own password | `POST /api/v1/auth/password` | Viewer |
| View dashboards, KPIs, charts, status, Problems panel (incl. the number of active AWOS alarms) | `GET /api/v1/settings/display` | Public |
|  | `GET /api/v1/systems` | Public |
|  | `GET /api/v1/systems/{code}` | Public |
|  | `GET /api/v1/systems/{code}/kpis` | Public |
|  | `GET /api/v1/systems/{code}/status` | Public |
|  | `GET /api/v1/systems/{code}/problems` | Public |
|  | `GET /api/v1/systems/{code}/history` | Public |
|  | `GET /api/v1/systems/{code}/calendar` | Public |
|  | `GET /api/v1/systems/{code}/sites/{slug}/components/{component}/series` | Public |
|  | `GET /api/v1/systems/{code}/matrix` | Public |
|  | `GET /api/v1/systems/{code}/outages` | Public |
|  | `GET /api/v1/systems/{code}/minutes` | Public |
|  | `GET /api/v1/definitions` | Public |
| View confirmed flags and detections; data-quality summary (suspects only signed in) | `GET /api/v1/systems/{code}/flags` | Public |
|  | `GET /api/v1/systems/{code}/detections` | Public |
|  | `GET /api/v1/systems/{code}/data-quality` | Public |
| View METAR / MET REPORT / TAF | `GET /api/v1/systems/{code}/reports/latest` | Public |
|  | `GET /api/v1/systems/{code}/reports` | Public |
|  | `GET /api/v1/systems/{code}/reports/search` | Public |
| View asset metadata and calibration status (serial and part numbers only signed in) | `GET /api/v1/systems/{code}/assets` | Public |
| View AWOS alarm list, history and message text | `GET /api/v1/systems/{code}/alarms/active` | Viewer |
|  | `GET /api/v1/systems/{code}/alarms` | Viewer |
| View infrastructure details (health internals, ingestion diagnostics) | `GET /api/v1/internal/health` | Viewer |
| View a component's figure change trace (FR-AUD-003; R2 design: Viewer) | `GET /api/v1/systems/{code}/trace` | Viewer |
| Export monthly PDF and CSV | `GET /api/v1/systems/{code}/exports/daily.csv` | Viewer |
|  | `GET /api/v1/systems/{code}/exports/minutes.csv` | Viewer |
|  | `GET /api/v1/systems/{code}/exports/alarms.csv` | Viewer |
|  | `GET /api/v1/systems/{code}/exports/quality.csv` | Viewer |
|  | `POST /api/v1/systems/{code}/exports/monthly-report` | Viewer |
| Confirm/reject detections; create/remove manual flags | `GET /api/v1/admin/flags` | Admin |
|  | `GET /api/v1/admin/flags/preview` | Admin |
|  | `POST /api/v1/admin/flags` | Admin |
|  | `PATCH /api/v1/admin/flags/{flag_id}` | Admin |
|  | `DELETE /api/v1/admin/flags/{flag_id}` | Admin |
|  | `GET /api/v1/admin/detections` | Admin |
|  | `POST /api/v1/admin/detections/decide` | Admin |
| Edit validity rules, mandatory fields, thresholds, settings | `GET /api/v1/admin/settings` | Admin |
|  | `PUT /api/v1/admin/settings/{key}` | Admin |
|  | `GET /api/v1/admin/mandatory-fields` | Admin |
|  | `GET /api/v1/admin/mandatory-fields/{component_type}/preview` | Admin |
|  | `PUT /api/v1/admin/mandatory-fields/{component_type}` | Admin |
|  | `GET /api/v1/admin/rules` | Admin |
|  | `GET /api/v1/admin/rules/history` | Admin |
|  | `GET /api/v1/admin/rules/dry-run` | Admin |
|  | `GET /api/v1/admin/rules/{rule_id}/versions` | Admin |
|  | `POST /api/v1/admin/rules` | Admin |
|  | `PUT /api/v1/admin/rules/{rule_id}` | Admin |
|  | `DELETE /api/v1/admin/rules/{rule_id}` | Admin |
| Edit registry, metadata, calibration records, alarm mapping | `GET /api/v1/admin/components` | Admin |
|  | `PATCH /api/v1/admin/components/{component_id}` | Admin |
|  | `GET /api/v1/admin/station` | Admin |
|  | `PUT /api/v1/admin/station` | Admin |
|  | `PUT /api/v1/admin/sites/{slug}` | Admin |
|  | `PUT /api/v1/admin/components/{component_id}/meta` | Admin |
|  | `GET /api/v1/admin/components/{component_id}/calibrations` | Admin |
|  | `POST /api/v1/admin/calibrations` | Admin |
|  | `PATCH /api/v1/admin/calibrations/{cal_id}` | Admin |
|  | `DELETE /api/v1/admin/calibrations/{cal_id}` | Admin |
|  | `GET /api/v1/admin/alarm-names` | Admin |
|  | `PUT /api/v1/admin/alarm-names/{name}` | Admin |
| Start reprocess / recompute jobs | `GET /api/v1/admin/jobs` | Admin |
|  | `POST /api/v1/admin/jobs` | Admin |
|  | `GET /api/v1/admin/jobs/{job_id}` | Admin |
|  | `POST /api/v1/admin/jobs/{job_id}/cancel` | Admin |
| Manage user accounts | `GET /api/v1/admin/users` | Admin |
|  | `POST /api/v1/admin/users` | Admin |
|  | `PATCH /api/v1/admin/users/{user_id}` | Admin |
|  | `POST /api/v1/admin/users/{user_id}/reset-password` | Admin |
| View audit log | `GET /api/v1/admin/audit` | Admin |
