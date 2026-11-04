# Runbook: backups and restore (NFR-BAK-001..004)

## What is backed up

The `backup` service runs `pg_dump -Fc` every night at `SIMOLA_BACKUP_HOUR_UTC` (default 18:00 UTC = 01:00 WIB). Dumps go into `SIMOLA_BACKUP_DIR`:

| Folder | Kept |
|---|---|
| `daily/` | last 7 |
| `weekly/` | Sunday copies, last 4 |
| `monthly/` | 1st-of-month copies, last 12 |

Each run is recorded in `backup_run` and shown on `/internal/health`. Problems are raised when a backup is more than 26 h old (`SIMOLA_BACKUP_EXPECTED=true`).

**Off-host copy (OPEN-01, still open):** the destination must be free or already owned. Once chosen, set `SIMOLA_BACKUP_UPLOAD_CMD`. The command receives the dump path as `$1`. Example with an rclone remote:

```text
SIMOLA_BACKUP_UPLOAD_CMD=rclone copy "$1" simola-offsite:simola/
```

The stock TimescaleDB image does not contain rclone. Adding the off-host copy is a small follow-up once the destination is decided.

Observation history can also be rebuilt from the CDP files ([history.md](history.md)). Flags, rules, users and audit (R2+) exist **only** in backups.

## Restore (quarterly drill into staging; RTO ≤ 4 h)

1. Stop `api`, `worker` and `backup` in the target environment. Keep `db` running.
2. Recreate the database and restore. TimescaleDB needs the pre/post-restore calls:
   ```bash
   docker exec -i <db> psql -U simola_owner -d postgres -c "DROP DATABASE simola WITH (FORCE)" -c "CREATE DATABASE simola"
   docker exec -i <db> psql -U simola_owner -d simola -c "CREATE EXTENSION IF NOT EXISTS timescaledb" -c "SELECT timescaledb_pre_restore()"
   docker exec -i <db> pg_restore -U simola_owner -d simola --no-owner --no-privileges < simola-YYYYMMDDTHHMMZ.dump
   docker exec -i <db> psql -U simola_owner -d simola -c "SELECT timescaledb_post_restore()"
   ```
   The target must use the same owner role name (`POSTGRES_USER`). Otherwise TimescaleDB's background jobs
   (compression policies) are not restored: the drill on 2026-11-04 showed `role ... does not exist` for `bgw_job`.
3. Redeploy, so `migrate` re-applies role grants (privileges are not restored), then start the services.
4. Check `/ready`, `/internal/health`, and one month's figures with `tools/recount.py`.
5. Record the drill date and duration (PRD NFR-BAK-002).
