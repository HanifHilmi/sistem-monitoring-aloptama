# Runbook: R1 cutover from v2 (PRD §14.5–14.8)

Every step that changes Coolify, Cloudflare, a database or the host needs the Product Owner's go-ahead.

## Timeline

| When | What |
|---|---|
| Until 30 Nov | UAT on staging (U1, U2, U8, U10) and fixes |
| 1–31 Dec | Live month on staging, alongside v2. v2 is a reference only: its figures are not compared (Product Owner, 2026-11-04) |
| 1–2 Jan | Verify December on staging: SM-1 recount and SM-2 completeness for every day |
| Early Jan | Prepare production (A), go/no-go (B), then switch (sections 1–3) |

Preconditions for the switch:
- R1 is accepted (B);
- the one-month live run is complete;
- `tools/recount.py` matches for December and two historical months, on staging and on production;
- every December day is complete (SM-2);
- the R1 UAT scenarios are signed off.

## A. Prepare production (not public yet)

Production is the Coolify application `simola-production` (branch `main`). It stays behind Cloudflare Access with no
public route until the switch.

1. **Host folders:** `/var/lib/simola/production/pg` and `/var/lib/simola/production/backups` must exist
   ([deploy.md](deploy.md), H-2).
2. **Settings** in Coolify (compare with staging's):
   - `SIMOLA_CDP_ROOT`, `SIMOLA_CDP1_DIR`, `SIMOLA_CDP2_DIR`: the same values as staging (deploy.md, H-1);
   - `SIMOLA_API_MEM=512m` for the two API processes (about 300 MB under the 20-user load test);
   - delete the settings SIMOLA no longer reads: `SIMOLA_CDP1_SHARE`, `SIMOLA_CDP2_SHARE`, `SIMOLA_BACKUP_ENABLED`,
     `SIMOLA_BACKUP_EXPECTED`, `SIMOLA_BACKUP_HOUR_UTC`, `SIMOLA_BACKUP_RUN_ON_START` (and their preview copies);
   - keep production's own passwords, `SIMOLA_ENVIRONMENT=production` and the data folders above; no domain yet.
3. **Deploy:** run `deploy/check-network-safety.sh` and check both shares answer, deploy in Coolify, then verify as
   in [deploy.md](deploy.md): every container healthy, a 10.0.x network, no new 172.16.0.0/12 or 192.168.0.0/16
   route, no port published on the host, the shares read-only in the worker, both CDPs ingesting.
4. **History:** `simola load-history` in the production worker, then `simola jobs` until the job is `done`
   ([history.md](history.md); about 21 minutes for 316 days on staging). Run it at a quiet time: it shares the
   host's 4 CPUs with staging and v2.
5. **Recount** production against the files for December and two historical months (history.md, Verify): every
   figure must match.
6. **Backup:** `backup-now`, then `backup-verify` in production's `backup` container; it must end with `PASSED`
   ([backup-restore.md](backup-restore.md)).
7. **Access before the domain:** in Cloudflare Access, protect all of `simola.hilmihanif.my.id` first. Only then
   set the `web` service's domain in Coolify (`http://simola.hilmihanif.my.id:8080`), redeploy, and check that every
   path answers 302 to the Access login.

## B. Go/no-go (Product Owner)

- UAT U1, U2, U8 and U10 signed off.
- December on staging: SM-1 recount exact; SM-2: for every completed day, stored minutes = minutes present in
  either CDP file. `tools/recount.py` compares monthly figures today; a per-day comparison is to be added before
  January.
- Production prepared (A): history loaded, recount exact, `backup-verify` passed.
- The decision is recorded in the PRD revision history, together with the changes since v1.1:
  - backups run only on request (replaces the nightly backup of NFR-BAK-001 and SM-5);
  - the v2 figure comparison of §14.5 was dropped; v2 is a reference only;
  - load-test margins on this host (31-day chart p95 1.30 s of 1.5 s, with the load generator on the same 4 CPUs);
  - the CDP shares are read-only at the source (the CDPs refuse writes).

## 1. Export v2 live probe samples (read-only)

Run on the host against v2's database container. Minute-aligned rows are v2 backfill (file presence), not probes; the import skips them anyway.

```bash
docker exec -e PGOPTIONS='-c default_transaction_read_only=on' <v2-db-container> \
  psql -U <v2-user> -d <v2-db> -X -c "\copy (
    SELECT to_char(c.time AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') AS time,
           n.name AS cdp, c.reachable, c.rtt_ms
    FROM cdp_connectivity c JOIN cdp_nodes n ON n.id = c.cdp_id
    WHERE c.time >= '2026-08-14' AND c.time <> date_trunc('minute', c.time)
    ORDER BY c.time) TO STDOUT WITH CSV HEADER" > v2_probes.csv
```

## 2. Import into SIMOLA (FR-ING-014)

```bash
docker cp v2_probes.csv <simola-worker>:/tmp/v2_probes.csv
docker exec <simola-worker> simola import-legacy-probes --csv /tmp/v2_probes.csv
```

SIMOLA's own probe minutes are never overwritten. Affected days are recomputed automatically.

## 3. Switch

1. Back up production again and check that the backup restores ([backup-restore.md](backup-restore.md)): in the
   production `backup` container run `backup-now`, then `backup-verify`; it must end with `PASSED`.
2. In Cloudflare Access, remove the policy covering all of `simola.hilmihanif.my.id`. Keep the `/internal/*` policies until R2.
3. Add a Cloudflare redirect rule: `rhf-monitoring.hilmihanif.my.id/*` → `https://simola.hilmihanif.my.id/$1` (301). Old v2 paths such as `/cat3/runway/04` are mapped by the SPA router.
4. Announce the change to users.

After the switch, staging keeps running: R2 and R3 are verified there before they reach production (PRD §14.6).

## Rollback (within 30 days)

Remove the redirect rule. v2 is still running unchanged, and SIMOLA keeps ingesting in the background.

## Decommission v2 (after 30 stable days, only with explicit approval)

1. Archive a final read-only `pg_dump` of v2 off-host.
2. Stop v2 in Coolify.
3. Delete v2's data directory only after the archive has been restored successfully once.
