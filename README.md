# SIMOLA — Sistem Monitoring ALOPTAMA

Self-hosted monitoring for the station's ALOPTAMA observing systems. It covers the AWOS CAT.III at Raja Haji
Fisabilillah Airport (WIDN) and is designed to add Tambelan CAT.I, AWS and ARG later.

**Status:** the MVP (releases R1–R3) is complete and has been the station's monitoring site since 2026-11-11, at
<https://simola.hilmihanif.my.id>. It replaced `monitoring-aloptama-v2`, which is stopped. The next phase in the
roadmap is AWOS CAT.I Tambelan (PRD §17.2).

Requirements: [`PRD.md`](PRD.md) (approved; v1.4). Decisions: [`QUESTIONS.md`](QUESTIONS.md).

## What SIMOLA does

- **Ingestion.** Reads the 1-minute files of both CDPs, keeps each CDP's rows, and merges them per minute (CDP1
  preferred). Re-scans recent files so late minutes are not lost, probes the CDPs every 15 s, and also reads the
  AWOS alarm logs and the METAR, MET REPORT and TAF logs. History since 24 December 2025 is loaded from the files.
- **Figures.** SLA (minutes in which at least one CDP produced data), per-CDP uptime and reachability, and
  availability per sensor, DCP, site, OLA and pooled. One engine feeds every screen, the exports and the PDF.
  Figures are exact minute counts, never capped at 100 %.
- **Data quality.** Validity rules (range, stuck, spike) raise suspect detections; an Admin confirms or rejects
  them, and can flag bad minutes by hand. Confirmed detections and flags take minutes out of the figures, and
  every change is recomputed and audited.
- **Records.** Station, site and sensor records, in-service periods and calibrations with due dates.
- **Screens.** Dashboard, a board per system (month by day), site pages, sensor charts, a minute drill-down,
  outage breakdowns, the Problems panel, a health page, alarms, reports, data quality and the definitions of every
  figure. Indonesian and English; system, site, sensor and parameter names and aviation weather terms stay in
  English in both.
- **Exports.** CSV files (daily figures, minutes, alarms, data quality) and a monthly PDF report in either language.
- **Accounts.** Local accounts with Viewer and Admin roles, sign-in protection, and an audit log nobody can edit.

### Who sees what (PRD §5.4)

| Role | Sees |
|---|---|
| Public (no account) | Dashboards, figures, sensor charts, METAR / MET REPORT / TAF, definitions, data-quality summary. No AWOS alarms (not even their count), addresses, serial numbers or suspect detections |
| Viewer (station head) | Also AWOS alarms, the health page, serial and part numbers, suspect detections, CSV exports and the monthly PDF |
| Admin (technicians) | Also the Admin area: users, audit log, jobs, settings, mandatory fields, records and calibration, flags, validity rules, review queue, alarm mapping |

The server checks the role on every request; the full route list is in
[docs/design/permissions.md](docs/design/permissions.md).

## Layout

| Path | Contents |
|---|---|
| `backend/` | Python 3.13: FastAPI API (`simola.api`), worker (`simola.worker`), CLI (`simola`), PDF report (`simola.report`), SQL migrations |
| `frontend/` | Vue 3 + TypeScript + Tailwind + ECharts single-page app, served by unprivileged nginx |
| `deploy/backup/` | On-request backup commands (`backup-now`, `backup-verify`) in the `backup` service |
| `deploy/check-network-safety.sh` | Run before every deploy: refuses Docker networks that would overlap the intranet |
| `tools/recount.py` | Independent recount of the figures from the CDP files (acceptance checks SM-1 and SM-2) |
| `tools/security_check.py` | Security checks against a running site (headers, permissions, leaks, exposed ports) |
| `tools/load/` | Load test (Locust) for the performance targets |
| `docs/runbooks/` | Operator procedures (below) |
| `docs/design/` | Release designs (R2, R3) and the permission matrix |
| `docker-compose.yml` | Services: `db`, `migrate`, `api`, `worker`, `web`, `backup` |

## Documentation

| Document | For |
|---|---|
| [deploy.md](docs/runbooks/deploy.md) | Deploying with Coolify, host preparation, checks before and after every deploy |
| [accounts.md](docs/runbooks/accounts.md) | Roles, the first Admin, everyday account work, lockouts, the audit log, Cloudflare Access |
| [admin.md](docs/runbooks/admin.md) | Admin work: jobs, settings, mandatory fields, records, calibration, flags, rules, review, alarms, reports, exports |
| [history.md](docs/runbooks/history.md) | Loading, reprocessing and recounting history |
| [backup-restore.md](docs/runbooks/backup-restore.md) | Backups on request, the restore drill, a full restore |
| [testing.md](docs/runbooks/testing.md) | Browser, language, security and load checks against a running site, with past results |
| [cutover.md](docs/runbooks/cutover.md) | The switch from v2 (done 2026-11-11), rollback and the decommission of v2 |
| [design/r2.md](docs/design/r2.md), [design/r3.md](docs/design/r3.md) | How R2 and R3 were designed and decided |
| [design/permissions.md](docs/design/permissions.md) | Every API route and the least role it needs |

## Development

Unit tests and checks run locally. Integration tests (they need TimescaleDB) run in GitHub Actions CI, which also
runs the browser tests, the ZAP scans and a backup-and-restore check.
**Never start the stack with `docker compose up` or `docker run` on the server; deploy only through Coolify**
([docs/runbooks/deploy.md](docs/runbooks/deploy.md)).

```bash
# Backend
cd backend
uv sync
uv run ruff check simola tests && uv run mypy simola && uv run pytest tests/unit

# Frontend
cd frontend
npm ci
npm run lint && npm run typecheck && npm run check:i18n && npm test
npm run e2e          # browser tests on sample data

# Look at the UI with generated sample data (no backend, no Docker) on http://127.0.0.1:5173
npm run dev:sample
```

Sample-data mode (`VITE_MOCK=1`) answers every `/api/v1` call in the browser with deterministic,
made-up figures. It is only for design and tests and is never part of a production build.

Operator commands (in the Coolify terminal of the `worker` container):

```text
simola migrate                                  # applies migrations; creates/updates the app DB role
simola create-admin --username <name> --display-name "<Full name>"   # first Admin; --reset for a locked-out one
simola load-history                             # enqueue reprocess from coverage start to today
simola reprocess --from 2026-10-01 --to 2026-10-31
simola recompute --from 2026-01-01 --to 2026-10-31
simola jobs / simola cancel <id>
simola propose-rules                            # validity rules proposed from the history, all switched off
simola import-records <file.json|-> --actor <name> [--dry-run]   # sensor records and calibrations, audited
simola import-legacy-probes --csv v2_probes.csv # v2's probe samples (used once, at the switch)
```

Backups (in the `backup` container): `backup-now`, `backup-verify` ([backup-restore.md](docs/runbooks/backup-restore.md)).

## Repository rules

This repository is public (NFR-SEC-010):

- Never commit secrets, credentials, internal IP addresses, internal hostnames or account names. Configuration comes from environment variables; see [`.env.example`](.env.example).
- `ASSESSMENT.md` and `private/` are git-ignored on purpose.
- Applied migrations are immutable. Add a new numbered file instead.
- All times are UTC.
