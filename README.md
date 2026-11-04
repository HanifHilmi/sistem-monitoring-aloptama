# SIMOLA — Sistem Monitoring ALOPTAMA

Self-hosted monitoring for the station's ALOPTAMA observing systems. It starts with the AWOS CAT.III at
Raja Haji Fisabilillah Airport (WIDN) and is designed to add Tambelan CAT.I, AWS and ARG later.

Requirements: [`PRD.md`](PRD.md) (approved v1.0). Decisions: [`QUESTIONS.md`](QUESTIONS.md).

**Status: release R1 (foundation and trustworthy figures), in development.**

## What R1 does

- Reads the 1-minute files of **both** CDPs, stores them per CDP, and merges them per minute (CDP1 preferred).
- Re-scans recent files, so late and day-rollover minutes are not lost.
- Records **data flow** per CDP and minute. SLA = minutes in which at least one CDP produced data.
- Probes the CDPs over TCP every 15 s. Reachability is informational only and never feeds SLA.
- Computes availability for components (mandatory fields), DCP, sites, OLA and pooled availability. One engine feeds every screen, with no 100 % cap.
- Public dashboards: overview, system page, site pages, calendar, history, sensor charts, Problems panel. Indonesian and English.
- Infrastructure details (addresses, paths) appear only on `/internal/health`, which is protected by Cloudflare Access until accounts arrive in R2.

## Layout

| Path | Contents |
|---|---|
| `backend/` | Python 3.13: FastAPI API (`simola.api`), worker (`simola.worker`), CLI (`simola`), SQL migrations |
| `frontend/` | Vue 3 + TypeScript + Tailwind + ECharts single-page app, served by unprivileged nginx |
| `deploy/backup/` | Nightly `pg_dump` script used by the `backup` service |
| `tools/recount.py` | Independent recount of monthly figures from the CDP files (acceptance check SM-1) |
| `docs/runbooks/` | Operator procedures: deploy, history load, backups and restore, cutover |
| `docker-compose.yml` | Services: `db`, `migrate`, `api`, `worker`, `web`, `backup` |

## Development

```bash
# Backend (needs a TimescaleDB for integration tests)
cd backend
uv sync
uv run ruff check simola tests && uv run mypy
SIMOLA_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@127.0.0.1:55432/simola_test uv run pytest

# Frontend
cd frontend
npm ci
npm run lint && npm run typecheck && npm run check:i18n && npm test
npm run dev        # proxies /api to http://127.0.0.1:8000
```

Operator commands (inside the `worker` container, or with `uv run` locally):

```text
simola migrate                                  # applies migrations; creates/updates the app DB role
simola load-history                             # enqueue reprocess from coverage start to today
simola reprocess --from 2026-10-01 --to 2026-10-31
simola recompute --from 2026-01-01 --to 2026-10-31
simola jobs / simola cancel <id>
simola import-legacy-probes --csv v2_probes.csv # at cutover (FR-ING-014)
```

## Repository rules

This repository is public (NFR-SEC-010):

- Never commit secrets, credentials, internal IP addresses, internal hostnames or account names. Configuration comes from environment variables; see [`.env.example`](.env.example).
- `ASSESSMENT.md` and `private/` are git-ignored on purpose.
- Applied migrations are immutable. Add a new numbered file instead.
- All times are UTC.
