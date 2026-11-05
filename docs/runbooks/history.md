# Runbook: load, reprocess and verify history

All commands run inside the worker container. In Coolify use *Terminal → worker*, or on the host:
`docker exec -it <worker-container> <command>`.

## First load (FR-ING-011)

```bash
simola load-history          # enqueues one reprocess job: coverage start (2025-12-24) .. today
simola jobs                  # watch progress; newest days are loaded first
```

The job rebuilds every day from both CDPs' files and stores the daily rollups. It is idempotent: running it again changes nothing.

## Reprocess a range (e.g. after a share outage)

```bash
simola reprocess --from 2026-11-02 --to 2026-11-03
```

- Rows missing from an **existing** file are removed.
- A **missing** file is skipped without deleting anything.
- Only one reprocess job can be queued or running at a time.

## Recompute figures only

```bash
simola recompute --from 2026-01-01 --to 2026-10-31
```

## Verify (acceptance SM-1 / SM-2)

From a machine that can read the shares and reach the API:

```bash
python3 tools/recount.py --cdp1 /mnt/<cdp1-share-mount> --cdp2 /mnt/<cdp2-share-mount> \
    --api https://simola.hilmihanif.my.id --month 2026-09 --month 2026-10 --daily
```

Every figure must match exactly (exit code 0). The script shares no code with SIMOLA. It compares 24 figures (SLA,
each CDP's data flow, every component) per month (SM-1) and, with `--daily`, for every completed UTC day (SM-2:
each day's stored minutes equal the minutes present in either CDP file); a day that differs is named, ready for
`simola reprocess`. Today is left out because its file is still growing. Through the Access-protected hostname it
needs an Access session; on the host, use the web container's address instead (`http://<address>:8080`).

## After the reader fix of 2026-11-05

Present weather was cut to 6 characters ("VCTS DZ" stored as "VCTS D") and the lightning text to 32. The reader
now takes present weather at its full 10 characters and the lightning text to the end of the line. Rows already
stored keep the cut text until their days are reprocessed:

```bash
simola load-history          # rebuilds every day from the files; figures do not change
```
