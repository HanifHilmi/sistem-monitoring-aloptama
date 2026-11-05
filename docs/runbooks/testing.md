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
