# Runbook: R1 checks (browser, security, load)

PRD §15.3–15.5. Unit and integration tests are in CI (`.github/workflows/ci.yml`); this page covers the checks that
need a running site. Everything here only **reads** from staging. Never commit the addresses you use: the
repository is public (NFR-SEC-010).

## Find staging's web container

Staging is behind Cloudflare Access, so the checks talk to its web container directly from the host:

```bash
web=$(docker ps --format '{{.Names}}' | grep '^web-<staging-app-uuid>' | head -1)
addr=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$web")
echo "http://$addr:8080"
```

The address changes with every deploy.

## Browser tests (§15.3)

Desktop 1440 px and phone 390 px, Indonesian and English; J1 (daily check) and the health page. R1 has no
accounts, so J2–J7 arrive with R2/R3.

```bash
cd frontend
npm run e2e                                    # sample data (what CI runs)
SIMOLA_E2E_URL=http://<address>:8080 npm run e2e  # staging, real data
```

Against a deployed site this also measures NFR-PERF-003 (largest contentful paint ≤ 2.5 s, initial JS ≤ 400 KB
gzip). It is measured from the host, so it leaves out the Cloudflare leg.

Playwright 1.62.1 uses the browser cached in `~/.cache/ms-playwright` (`chromium_headless_shell-1234`), so no
browser download is needed on this host.

## Security checks (§15.4)

```bash
python3 tools/security_check.py --web http://<address>:8080 \
    --public https://simola-staging.hilmihanif.my.id --containers <staging-app-uuid>
```

It checks security headers, that no route accepts writes (R1 has none), that every published API route is
covered, that public answers hold no IP address, file path, serial or infrastructure field, that the internal
pages are behind Access, and that no SIMOLA container publishes a port on the host. Exit code 1 on any failure.

The OWASP ZAP baseline scan runs in CI (`zap` job) against a throwaway stack on GitHub's runner and fails on any
High-risk alert; its report is kept as the `zap-report` artifact. Account checks (CSRF, sessions, lockout) arrive
with accounts in R2.

## Load test (§15.5)

20 virtual users, J1-style navigation, 1–3 s between pages, 5 minutes:

```bash
uvx --from 'locust>=2.30' locust -f tools/load/locustfile.py --headless -u 20 -r 2 -t 5m \
    --host http://<address>:8080 --csv /tmp/simola-load
```

It prints PASS/FAIL for NFR-PERF-001 (KPI and status p95 ≤ 1.0 s) and NFR-PERF-002 (31-day chart p95 ≤ 1.5 s,
≤ 500 KB) and exits 1 on a miss. The host also runs v2 production: run it at a quiet time and watch the load.

## Results

| Date (UTC) | Check | Result |
|---|---|---|
| 2026-11-04 | Browser, staging | 30 passed (2 skipped by design); LCP 0.88–0.95 s; initial JS 86.5 KB gzip |
| 2026-11-04 | Security, staging | All passed (36 checks) |
| 2026-11-04 | Load, staging | **Failed**: p95 1.9–3.5 s for KPI and status, 2.5 s for the 31-day chart; no errors in 4,777 requests. Cause: one API process; the 31-day chart reads ~44,600 rows per component and processes them in Python, which blocks every other request |
| 2026-11-05 | Load, staging (05bf3bc: faster charts, 2 API processes) | **Failed**: p95 0.56–1.3 s; 134 HTTP 500 of 9,922 requests: the database refused connections (pools asked for up to 30 of 22) |
| 2026-11-05 | Load, staging (66065ef: pools 17 of 22) | **Nearly passed**: 0 errors in 11,403 requests; every target met except the yearly matrix, p95 1.2 s (limit 1.0; 60 ms when idle). The host's 4 CPUs were saturated (load ≈ 4), the load generator included |
| 2026-11-05 | Browser, staging | 30 passed, twice in a row |
| 2026-11-05 | Security, staging | All passed |
| 2026-11-05 | CI (66065ef) | All 6 jobs green, including e2e and the ZAP baseline (no High-risk alert) |
| 2026-11-05 | Load, staging (189ec8c: yearly figures summed in the database) | **Passed**: every target met, 0 errors in 11,515 requests. p95: status 0.82 s, problems 0.80 s, KPIs 0.64/0.84 s (month/year), matrix 0.79/0.93 s (month/year), 31-day chart 1.10 s (limit 1.5), largest chart 90.8 KB. Thin margins: the 4 CPUs were saturated (load ≈ 3.9), the load generator included |
| 2026-11-05 | CI (189ec8c) | All 6 jobs green |
| 2026-11-05 | Browser, staging (eb484ae: menus, Dashboard, sensor views) | 74 passed (2 skipped by design); LCP 0.78–1.57 s; initial JS 92.4 KB gzip |
| 2026-11-05 | Security, staging (eb484ae) | All passed |
| 2026-11-05 | Load, staging (20fb06b: sensor views + dead-share fix) | **Nearly passed**: 0 errors in 10,638 requests; every target met except the yearly matrix, p95 1.10 s (limit 1.0; 24 ms when idle). KPIs 1 year 1.00 s, status 0.94 s, 31-day chart 1.20 s (limit 1.5), largest chart 103.5 KB. Cause: each 31-day chart is 0.17–0.44 s of Python work inside the API process's request loop, so quick requests wait behind it; the sensor views made charts slightly heavier. Host load ≈ 4.7 on 4 CPUs, the load generator included |
| 2026-11-05 | Load, staging (6494653: charts built on a thread) | **Passed**: every target met, 0 errors in 10,661 requests. p95: status 0.76 s, problems 0.82 s, KPIs 0.66/0.78 s (month/year), matrix 0.70/0.72 s (month/year), 31-day chart 1.30 s (limit 1.5), largest chart 103.9 KB. Host load ≈ 4.2 on 4 CPUs, the load generator included |
| 2026-11-05 | Recount, staging (SM-1 and SM-2) | Every figure matches: 12 months (2025-12 to 2026-11 up to the 5th) and all 340 completed days, 24 figures each (`tools/recount.py --daily`) |
