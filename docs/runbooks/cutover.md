# Runbook: R1 cutover from v2 (PRD §14.5–14.8)

Every step that changes Coolify, Cloudflare, a database or the host needs the Product Owner's go-ahead.

**Status (2026-11-13):** the switch was made on 2026-11-11. Sections A, B and 1–3 are done, except:
- A.8 and A.9: the first Admin account and switching on the 14 rules are the Product Owner's own steps, still to do;
- 3.4: the redirect of the old hostname is deferred (it answers 404 since v2 stopped);
- 3.5: telling the users.

v2 is stopped, its auto-deploy is off, and its final dump is kept on the host. Still ahead: the December recount
(1–2 January) and, after 30 stable days and only with approval, the decommission below.

## Timeline

| When | What |
|---|---|
| Until 30 Nov | UAT on staging and fixes. Done on 11 Nov: U1–U5 and U7–U10 passed; U6 is reviewed by the Product Owner instead of the station head |
| 11 Nov | Prepare production (A), with no domain |
| As soon as production checks out | Go/no-go (B), switch (sections 1–3), then stop v2. The one-month run alongside v2 is waived: v2 is a reference only and its figures are not compared (Product Owner, 2026-11-04 and 2026-11-11) |
| 1–2 Jan | Recount December on production: SM-1 and SM-2 for every day |

Preconditions for the switch:
- R1 is accepted (B);
- `tools/recount.py` matches on production for every month since coverage start (SM-1) and every completed day
  is complete (SM-2);
- the R1 UAT scenarios are signed off.

## A. Prepare production (not public yet)

Production is the Coolify application `simola-production` (branch `main`). It has no domain until the switch, so it
is reachable only from the host (the web container's address, as for staging's checks).

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
6. **Records:** load the station's installation dates and December 2025 calibrations with `simola import-records`
   in production's worker ([admin.md](admin.md), "Loading many records at once"): `--dry-run` first, then for real,
   with `--actor records-import`. The facts, as loaded on staging on 2026-11-06:
   - installed on 23 Dec 2025: every component at runway 04 (DCP included); 24 Dec 2025: every component at 22
     and middle;
   - every sensor (not the DCPs): calibrated 27 Dec 2025 (the work ran 27–28 Dec; the first day, so it is never
     shown late), performed by "BMKG (Direktorat Instrumentasi dan Kalibrasi)", 12-month interval (due
     27 Dec 2026), certificate validated 31 Dec 2025, note "Calibration work 27–28 Dec 2025.".

   The dry run must report 21 components and 18 calibrations. Then add by hand (Admin → Registry, Calibration)
   anything recorded on staging since then, such as January's calibrations.
7. **Backup** (the Product Owner asks for it): `backup-now`, then `backup-verify` in production's `backup` container;
   it must end with `PASSED` ([backup-restore.md](backup-restore.md)).
8. **First Admin:** `simola create-admin` in production's worker ([accounts.md](accounts.md)), then the other
   accounts in Admin → Users.
9. **Rules:** `simola propose-rules` in production's worker (every proposal starts switched off; 33 on 2026-11-11),
   then in Admin → Rules approve the same rules as on staging, with the same values. On staging, these 14 are
   switched on (2026-11-11); every other proposal stays off:

   | Sensor | Field | Rule | Sites | Values |
   |---|---|---|---|---|
   | ANEM | WD | stuck | all | 60 min, ignore 0 |
   | ANEM | WS | stuck | all | 360 min, ignore 0 |
   | ATRH | DEWP | stuck | all | 60 min |
   | ATRH | RH | stuck | all | 360 min, ignore 97, 98, 99, 100 |
   | ATRH | TEMP | stuck | all | 60 min |
   | BARO | DA | stuck | all | 810 min |
   | BARO | QNH | stuck | all | 360 min |
   | CEL | LR1 | stuck | all | 540 min, ignore 0 |
   | PWX | RA | stuck | all | 1440 min, ignore 0 |
   | RAIN | RA | stuck | middle | 1440 min, ignore 0 |
   | RVR | ALS | stuck | all | 720 min |
   | RVR | RVR | stuck | all | 60 min |
   | RVR | VIS | stuck | all | 60 min |
   | SOLR | SOL | stuck | all | 720 min, ignore 0 |
10. **No domain yet:** the tunnel route for `simola.hilmihanif.my.id` already exists without Access, so giving the
   `web` service that domain makes the site public at once. Leave the domain empty until the switch (section 3).

## B. Go/no-go (Product Owner)

- UAT U1, U2, U8 and U10 signed off.
- Production prepared (A): history loaded, records imported, `backup-verify` passed, and the recount exact: SM-1
  for every month since coverage start; SM-2: for every completed day, stored minutes = minutes present in either
  CDP file (`tools/recount.py ... --daily`, [history.md](history.md), Verify).
- The decision is recorded in the PRD revision history, together with the changes since v1.1:
  - backups run only on request (replaces the nightly backup of NFR-BAK-001 and SM-5);
  - the v2 figure comparison of §14.5 was dropped; v2 is a reference only;
  - load-test margins on this host (31-day chart p95 1.30 s of 1.5 s, with the load generator on the same 4 CPUs);
  - the CDP shares are read-only at the source (the CDPs refuse writes);
  - U6: the Product Owner reviewed the monthly PDF instead of the station head; staging had no Viewer account
    (2026-11-11);
  - production was prepared in November instead of early January, and the one-month run alongside v2 (§14.5)
    was waived: the switch follows as soon as production checks out, and v2 is stopped after it (2026-11-11).

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
2. Optional second lock (decision D4, [accounts.md](accounts.md)): a Cloudflare Access policy on `/admin*` and
   `/api/v1/admin*` only. The public pages need none; SIMOLA's sign-in protects the Viewer and Admin areas.
3. In Coolify, set the `web` service's domain to `http://simola.hilmihanif.my.id:8080` and redeploy (run the
   network check first, as for every deploy). The site is public as soon as the deploy finishes.
4. Add a Cloudflare redirect rule: `rhf-monitoring.hilmihanif.my.id/*` → `https://simola.hilmihanif.my.id/$1`
   (301). Old v2 paths such as `/cat3/runway/04` are mapped by the SPA router.
5. Announce the change to users.
6. Take a final read-only `pg_dump` of v2's database (kept for the decommission archive), then stop v2 in Coolify
   (stop, not delete), after sections 1–2 have read its probe samples. The stop removes v2's containers and its
   network; its images, configuration and data folder stay untouched for 30 days. Then turn off v2's auto-deploy in
   Coolify, so a push to v2's repository cannot start it again (done 2026-11-11).

After the switch, staging keeps running: R2 and R3 are verified there before they reach production (PRD §14.6).

## Rollback (within 30 days)

Start v2 again in Coolify (its containers were removed, so this runs a new deployment; run the network check first,
as for every deploy) and remove the redirect rule. v2's data is untouched (its own backfill can fill the days it was
stopped), and SIMOLA keeps ingesting in the background. Its auto-deploy stays off.

## Decommission v2 (after 30 stable days, only with explicit approval)

1. Archive the final `pg_dump` from the switch off-host.
2. Remove v2 in Coolify.
3. Delete v2's data directory only after the archive has been restored successfully once.
