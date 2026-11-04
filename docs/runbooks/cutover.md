# Runbook: R1 cutover from v2 (PRD §14.5–14.8)

Preconditions:
- R1 is accepted;
- the one-month parallel run is complete;
- `tools/recount.py` matches for the comparison month and two historical months;
- the R1 UAT scenarios are signed off.

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

1. Confirm the latest backup and restore drill.
2. In Cloudflare Access, remove the policy covering all of `simola.hilmihanif.my.id`. Keep the `/internal/*` policies until R2.
3. Add a Cloudflare redirect rule: `rhf-monitoring.hilmihanif.my.id/*` → `https://simola.hilmihanif.my.id/$1` (301). Old v2 paths such as `/cat3/runway/04` are mapped by the SPA router.
4. Announce the change to users.

## Rollback (within 30 days)

Remove the redirect rule. v2 is still running unchanged, and SIMOLA keeps ingesting in the background.

## Decommission v2 (after 30 stable days, only with explicit approval)

1. Archive a final read-only `pg_dump` of v2 off-host.
2. Stop v2 in Coolify.
3. Delete v2's data directory only after the archive has been restored successfully once.
