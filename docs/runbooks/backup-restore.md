# Runbook: backups and restore (NFR-BAK-001..004)

Backups run **only when someone asks** (Product Owner, 2026-11-04): there is no schedule, and SIMOLA never
deletes a backup. Both commands run in the `backup` container: in Coolify open the application's *Terminal*,
choose the `backup` container and type the command, or on the host run `docker exec <backup-container> <command>`.

## Back up now

```bash
backup-now
```

- Writes `SIMOLA_BACKUP_DIR/simola-<UTC time>.dump` (`pg_dump` custom format) and a `.sha256` next to it, after
  checking that the dump reads back.
- Records the run in `backup_run`; `/internal/health` lists recent runs.
- Prints the size, how many backups the folder holds and their total size. Old backups stay until someone removes
  them by hand (`rm` on the host in the folder above).
- Only one `backup-now` or `backup-verify` runs at a time.

## Check that a backup restores (restore drill)

```bash
backup-verify                       # the newest backup
backup-verify simola-<time>.dump    # a given one
```

It restores the backup into a scratch database `simola_verify` on the same server, compares it with the live
database and drops the scratch database again. **The live database is not touched.** It passes (`PASSED`) when:

- the restore reports no error and every live table is in the backup;
- the reference tables (registry, settings) are equal;
- the minute and daily tables are equal for everything older than two days before the backup was written (newer
  rows may have changed since; a reprocess of old days after the backup also shows up as a difference);
- tables that change by themselves (jobs, heartbeats, backup runs, ingest status, rollup marks) are present.

The server needs free disk for one more copy of the database while it runs. CI runs both commands against a
throwaway stack on every push (job `zap`), and `deploy/backup/test.sh` tests their failure paths.

**Off-host copy (OPEN-01, still open):** the destination must be free or already owned. Once chosen, set
`SIMOLA_BACKUP_UPLOAD_CMD`; `backup-now` runs it with the dump's path as `$1` and records a failed copy. Example
with an rclone remote:

```text
SIMOLA_BACKUP_UPLOAD_CMD=rclone copy "$1" simola-offsite:simola/
```

The stock TimescaleDB image does not contain rclone. Adding the off-host copy is a small follow-up once the
destination is decided.

Observation history can also be rebuilt from the CDP files ([history.md](history.md)). Flags, rules, users and
audit (R2+) exist **only** in backups.

## Full restore into an environment (replaces its database; RTO ≤ 4 h)

1. Stop `api`, `worker` and `backup` in the target environment. Keep `db` running.
2. Recreate the database and restore. TimescaleDB needs the pre/post-restore calls:
   ```bash
   docker exec -i <db> psql -U simola_owner -d postgres -c "DROP DATABASE simola WITH (FORCE)" -c "CREATE DATABASE simola"
   docker exec -i <db> psql -U simola_owner -d simola -c "CREATE EXTENSION IF NOT EXISTS timescaledb" -c "SELECT timescaledb_pre_restore()"
   docker exec -i <db> pg_restore -U simola_owner -d simola --no-owner --no-privileges < simola-YYYYMMDDTHHMMSSZ.dump
   docker exec -i <db> psql -U simola_owner -d simola -c "SELECT timescaledb_post_restore()"
   ```
   The target must use the same owner role name (`POSTGRES_USER`). Otherwise TimescaleDB's background jobs
   (compression policies) are not restored: the drill on 2026-11-04 showed `role ... does not exist` for `bgw_job`.
3. Redeploy, so `migrate` re-applies role grants (privileges are not restored), then start the services.
4. Check `/ready`, `/internal/health`, and one month's figures with `tools/recount.py`.
5. Record the drill date and duration (PRD NFR-BAK-002).
