#!/usr/bin/env python3
"""Security checks against a running SIMOLA site (PRD §15.4, SM-6; R2.1 accounts). Standard library only.

    python3 tools/security_check.py --web http://<web-container-address>:8080 \
        [--public https://<public-hostname>] [--containers <coolify-app-uuid>]

Checks (each prints PASS or FAIL; the exit code is 1 on any FAIL):
  headers   security headers on the page and the API, no server version, no open CORS (NFR-SEC-003)
  writes    the only state-changing routes are the known account ones, and every write without a session
            and CSRF token is refused (SM-6, FR-AUTH-002)
  routes    every route the API publishes is covered here, so a new route cannot skip these checks
  accounts  without a session, Viewer and Admin routes answer 401; the CSRF cookie is Secure and
            SameSite=Lax (FR-AUTH-002, FR-AUTH-005)
  leaks     public responses hold no IP address, file path, serial number or infrastructure field
            (FR-AUTH-006, SM-6); only signed-in Viewers and Admins see /api/v1/internal/*
  access    with --public: internal and Admin pages never answer with data; the Admin area stays behind
            the Cloudflare Access login (decision D4)
  exposure  with --containers: no SIMOLA container publishes a port on the host (NFR-SEC-001)

Never commit the addresses you pass in: the repository is public (NFR-SEC-010).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

IPV4 = re.compile(r"(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\d.])")
HOST_PATH = re.compile(
    r"(?<![\w.])/(?:mnt|var|home|srv|etc|opt|data|root|tmp|usr)/|^[A-Za-z]:\\|\\\\[\w.-]+\\"
)
SECRET_KEYS = {"password", "passwd", "secret", "token", "api_key", "apikey", "dsn", "database_url"}
INFRA_KEYS = {
    "address",
    "addresses",
    "ip",
    "ip_address",
    "host",
    "hostname",
    "path",
    "paths",
    "share",
    "serial",
    "serial_number",
    "part_number",
    "last_error",
    "file_name",
    "probe_method",
}
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
# Viewer and Admin. Alarm messages can name the station's equipment and network: never for the public (OPEN-13).
INTERNAL_ROUTES = (
    "/api/v1/internal/health",
    "/api/v1/systems/{code}/trace",
    "/api/v1/systems/{code}/alarms/active",
    "/api/v1/systems/{code}/alarms",
)
ADMIN_ROUTES = (
    "/api/v1/admin/users",
    "/api/v1/admin/users/{user_id}",
    "/api/v1/admin/users/{user_id}/reset-password",
    "/api/v1/admin/audit",
    "/api/v1/admin/jobs",
    "/api/v1/admin/jobs/{job_id}",
    "/api/v1/admin/jobs/{job_id}/cancel",
    "/api/v1/admin/settings",
    "/api/v1/admin/settings/{key}",
    "/api/v1/admin/mandatory-fields",
    "/api/v1/admin/mandatory-fields/{component_type}",
    "/api/v1/admin/mandatory-fields/{component_type}/preview",
    "/api/v1/admin/components",
    "/api/v1/admin/components/{component_id}",
    "/api/v1/admin/flags",
    "/api/v1/admin/flags/preview",
    "/api/v1/admin/flags/{flag_id}",
    "/api/v1/admin/rules",
    "/api/v1/admin/rules/history",
    "/api/v1/admin/rules/dry-run",
    "/api/v1/admin/rules/{rule_id}",
    "/api/v1/admin/rules/{rule_id}/versions",
    "/api/v1/admin/detections",
    "/api/v1/admin/detections/decide",
    "/api/v1/admin/station",
    "/api/v1/admin/sites/{slug}",
    "/api/v1/admin/components/{component_id}/meta",
    "/api/v1/admin/components/{component_id}/calibrations",
    "/api/v1/admin/calibrations",
    "/api/v1/admin/calibrations/{cal_id}",
    "/api/v1/admin/alarm-names",
    "/api/v1/admin/alarm-names/{name}",
)
AUTH_ROUTES = ("/api/v1/auth/me", "/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/auth/password")
# Every state-changing route the API may publish; a new one fails the check until it is reviewed here.
KNOWN_WRITES = {
    "POST /api/v1/auth/login",
    "POST /api/v1/auth/logout",
    "POST /api/v1/auth/password",
    "POST /api/v1/admin/users",
    "PATCH /api/v1/admin/users/{user_id}",
    "POST /api/v1/admin/users/{user_id}/reset-password",
    "POST /api/v1/admin/jobs",
    "POST /api/v1/admin/jobs/{job_id}/cancel",
    "PUT /api/v1/admin/settings/{key}",
    "PUT /api/v1/admin/mandatory-fields/{component_type}",
    "PATCH /api/v1/admin/components/{component_id}",
    "POST /api/v1/admin/flags",
    "PATCH /api/v1/admin/flags/{flag_id}",
    "DELETE /api/v1/admin/flags/{flag_id}",
    "POST /api/v1/admin/rules",
    "PUT /api/v1/admin/rules/{rule_id}",
    "DELETE /api/v1/admin/rules/{rule_id}",
    "POST /api/v1/admin/detections/decide",
    "PUT /api/v1/admin/station",
    "PUT /api/v1/admin/sites/{slug}",
    "PUT /api/v1/admin/components/{component_id}/meta",
    "POST /api/v1/admin/calibrations",
    "PATCH /api/v1/admin/calibrations/{cal_id}",
    "DELETE /api/v1/admin/calibrations/{cal_id}",
    "PUT /api/v1/admin/alarm-names/{name}",
}
# Routes that exist inside the containers but are not public API routes.
NON_PUBLIC = {"/health", "/ready"}

failures: list[str] = []


def report(ok: bool, check: str, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {check:<9} {detail}")
    if not ok:
        failures.append(f"{check}: {detail}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def http(method: str, url: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise SystemExit(f"only http(s) URLs are checked: {url}")
    data = b"{}" if method in WRITE_METHODS else None
    req = urllib.request.Request(  # noqa: S310 - scheme checked above
        url, data=data, method=method, headers={"Accept": "application/json", **(headers or {})}
    )
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with _opener.open(req, timeout=60) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def get_json(base: str, path: str, params: dict[str, Any] | None = None) -> Any:
    url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
    status, _, body = http("GET", url)
    if status != 200:
        raise SystemExit(f"GET {path} answered {status}")
    return json.loads(body)


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def public_routes(web: str) -> list[tuple[str, str, dict[str, Any]]]:
    """(template, concrete path, query) for every public route, with real identifiers from the API."""
    code = get_json(web, "/api/v1/systems")[0]["code"]
    system = get_json(web, f"/api/v1/systems/{code}")
    site = system["sites"][0]
    component = next(c["type"] for c in site["components"] if not c["is_dcp"])
    cdp = system["cdps"][0]["code"]
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    month = now.replace(day=1, hour=0, minute=0)
    next_month = (month + timedelta(days=32)).replace(day=1)
    year = month.replace(month=1)
    day = (now - timedelta(days=1)).date().isoformat()
    ids = {"code": code, "slug": site["slug"], "component": component}
    templates: list[tuple[str, dict[str, Any]]] = [
        ("/api/v1/settings/display", {}),
        ("/api/v1/systems", {}),
        ("/api/v1/systems/{code}", {}),
        ("/api/v1/systems/{code}/kpis", {"from": iso(month), "to": iso(next_month)}),
        ("/api/v1/systems/{code}/status", {}),
        ("/api/v1/systems/{code}/problems", {}),
        ("/api/v1/systems/{code}/history", {"from": iso(year), "to": iso(next_month), "bucket": "month"}),
        ("/api/v1/systems/{code}/calendar", {"year": now.year, "metric": "sla"}),
        ("/api/v1/systems/{code}/calendar", {"year": now.year, "metric": f"cdp:{cdp}"}),
        (
            "/api/v1/systems/{code}/sites/{slug}/components/{component}/series",
            {"from": iso(now - timedelta(hours=3)), "to": iso(now)},
        ),
        ("/api/v1/systems/{code}/matrix", {"from": iso(month), "to": iso(next_month), "bucket": "day"}),
        ("/api/v1/systems/{code}/minutes", {"day": day, "scope": "sla"}),
        ("/api/v1/systems/{code}/minutes", {"day": day, "scope": f"cdp:{cdp}"}),
        ("/api/v1/systems/{code}/minutes", {"day": day, "scope": f"component:{site['slug']}:{component}"}),
    ]
    month_q = {"from": iso(month), "to": iso(next_month)}
    outage_scopes = [
        "sla",
        f"cdp:{cdp}",
        "ola",
        f"site:{site['slug']}",
        f"component:{site['slug']}:{component}",
    ]
    templates += [("/api/v1/systems/{code}/outages", {**month_q, "scope": s}) for s in outage_scopes]
    templates += [
        ("/api/v1/systems/{code}/flags", month_q),
        ("/api/v1/systems/{code}/flags", {**month_q, "scope": f"component:{site['slug']}:{component}"}),
        ("/api/v1/systems/{code}/detections", month_q),
        ("/api/v1/systems/{code}/detections", {**month_q, "scope": f"component:{site['slug']}:{component}"}),
        ("/api/v1/systems/{code}/assets", {}),  # serial and part numbers must not reach the public
    ]
    return [(t, t.format(**ids), q) for t, q in templates]


def walk(value: Any, where: str = "") -> Iterator[tuple[str, str | None, Any]]:
    """Every (location, key, value) in a JSON document."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield f"{where}.{k}", str(k), v
            yield from walk(v, f"{where}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from walk(v, f"{where}[{i}]")
    else:
        yield where, None, value


def leaks_in(doc: Any) -> list[str]:
    found = []
    for where, key, value in walk(doc):
        if key is not None:
            k = key.lower()
            if k in INFRA_KEYS or k in SECRET_KEYS or k.endswith(("_address", "_ip", "_path", "_serial")):
                found.append(f"field {where}")
        elif isinstance(value, str):
            if IPV4.search(value):
                found.append(f"IP address in {where}")
            if HOST_PATH.search(value):
                found.append(f"file path in {where}")
    return found


def check_headers(web: str) -> None:
    _, h, _ = http("GET", web + "/", {"Accept": "text/html"})
    csp = h.get("content-security-policy", "")
    report(
        "default-src 'self'" in csp and "frame-ancestors 'none'" in csp,
        "headers",
        "page: Content-Security-Policy with default-src 'self' and frame-ancestors 'none'",
    )
    for name, want in (
        ("x-content-type-options", "nosniff"),
        ("referrer-policy", ""),
        ("permissions-policy", ""),
        ("strict-transport-security", "max-age="),
    ):
        report(want in h.get(name, "") and name in h, "headers", f"page: {name}")
    server = h.get("server", "")
    report(
        not re.search(r"\d", server), "headers", f"page: server header has no version ({server or 'none'})"
    )

    status, h, _ = http("GET", web + "/api/v1/systems", {"Origin": "https://example.invalid"})
    report(status == 200 and h.get("content-type", "").startswith("application/json"), "headers", "api: JSON")
    report("no-store" in h.get("cache-control", ""), "headers", "api: Cache-Control no-store")
    report(h.get("x-content-type-options") == "nosniff", "headers", "api: X-Content-Type-Options nosniff")
    acao = h.get("access-control-allow-origin")
    report(acao is None, "headers", f"api: no cross-origin access ({acao or 'none'})")


def check_routes_and_writes(web: str, routes: list[tuple[str, str, dict[str, Any]]]) -> None:
    status, _, body = http("GET", web + "/api/v1/openapi.json")
    covered = {t for t, _, _ in routes} | set(INTERNAL_ROUTES) | set(ADMIN_ROUTES) | set(AUTH_ROUTES)
    if status == 200:
        spec = json.loads(body)
        published = set(spec.get("paths", {}))
        missing = sorted(published - covered - NON_PUBLIC)
        report(
            not missing,
            "routes",
            "every published route is covered" + (f"; not covered: {missing}" if missing else ""),
        )
        writes = sorted(
            f"{m.upper()} {p}"
            for p, ops in spec.get("paths", {}).items()
            for m in ops
            if m.upper() in WRITE_METHODS
        )
        unknown = sorted(set(writes) - KNOWN_WRITES)
        report(
            not unknown,
            "writes",
            f"{len(writes)} state-changing routes, all reviewed" + (f"; new: {unknown}" if unknown else ""),
        )
    else:
        print(
            f"note  routes    OpenAPI document not served ({status}; normal in production): route list not compared"
        )

    ids = {
        "{user_id}": "1",
        "{job_id}": "1",
        "{key}": "grace_minutes",
        "{component_type}": "ATRH",
        "{component_id}": "2",
        "{flag_id}": "1",
        "{rule_id}": "1",
        "{cal_id}": "1",
        "{name}": "NoSuchAlarm",
        "{slug}": "04",
        "{code}": "WIDN-CAT3",
    }
    extra = []
    for p in (*INTERNAL_ROUTES, *ADMIN_ROUTES, *AUTH_ROUTES):
        for k, v in ids.items():
            p = p.replace(k, v)
        extra.append(p)
    paths = sorted({p for _, p, _ in routes} | set(extra))
    bad = []
    for path in paths:
        for method in WRITE_METHODS:
            status, _, _ = http(method, web + path)
            if status not in (401, 403, 404, 405):
                bad.append(f"{method} {path} -> {status}")
    report(
        not bad,
        "writes",
        f"{len(paths) * len(WRITE_METHODS)} write attempts without a session or CSRF token refused"
        + (f"; accepted: {bad}" if bad else ""),
    )

    status, h, _ = http("GET", web + "/ready")
    report(
        not h.get("content-type", "").startswith("application/json"),
        "writes",
        "readiness probe stays inside the container network",
    )


def check_accounts(web: str) -> None:
    """Without a session nothing above public is served; the CSRF cookie cannot travel in clear or cross-site."""
    for path in (*INTERNAL_ROUTES, "/api/v1/admin/users", "/api/v1/admin/audit"):
        path = path.replace("{code}", "WIDN-CAT3")
        status, _, body = http("GET", web + path)
        code = json.loads(body).get("code") if body.startswith(b"{") else None
        report(status == 401, "accounts", f"GET {path} without a session -> {status} {code or ''}".rstrip())
    status, h, body = http("GET", web + "/api/v1/auth/me")
    report(
        status == 200 and body.strip() == b"null",
        "accounts",
        f"GET /api/v1/auth/me without a session -> {status} null",
    )
    cookie = h.get("set-cookie", "")
    flags = cookie.lower()
    report(
        cookie.startswith("simola_csrf=") and "secure" in flags and "samesite=lax" in flags,
        "accounts",
        "CSRF cookie is Secure and SameSite=Lax",
    )


def check_leaks(web: str, routes: list[tuple[str, str, dict[str, Any]]]) -> None:
    for _, path, query in routes:
        url = web + path + ("?" + urllib.parse.urlencode(query) if query else "")
        status, _, body = http("GET", url)
        if status != 200:
            report(False, "leaks", f"GET {path} answered {status}")
            continue
        found = leaks_in(json.loads(body))
        extra = ",".join(f"{k}={v}" for k, v in query.items() if k in ("metric", "scope", "bucket"))
        shown = f"{path}?{extra}" if extra else path
        report(not found, "leaks", shown + (f": {found[:5]}" if found else ""))


def check_access(public: str) -> None:
    for path in ("/internal/health", *INTERNAL_ROUTES, "/admin", "/api/v1/admin/users"):
        status, h, body = http("GET", public + path)
        location = h.get("location", "")
        host = urllib.parse.urlparse(location).hostname or ""
        guarded = (status in (301, 302, 303, 307) and host.endswith("cloudflareaccess.com")) or status in (
            401,
            403,
        )
        if path.startswith(("/admin", "/api/v1/admin")):
            # The Admin area keeps Cloudflare Access as a second lock in front of SIMOLA's sign-in (D4): the
            # answer must come from Cloudflare (its login redirect, or its own 403 for this script's User-Agent),
            # never from SIMOLA.
            from_cloudflare = h.get("server", "").lower() == "cloudflare" and b"urn:simola" not in body
            guarded = (status in (301, 302, 303, 307) and host.endswith("cloudflareaccess.com")) or (
                status == 403 and from_cloudflare
            )
        report(guarded, "access", f"{path} -> {status}{' (Access login)' if guarded and location else ''}")
    status, h, _ = http("GET", public + "/")
    print(
        f"note  access    / -> {status} {urllib.parse.urlparse(h.get('location', '')).hostname or ''}".rstrip()
    )


def check_exposure(app: str) -> None:
    docker = shutil.which("docker")
    if docker is None:
        raise SystemExit("docker is not on PATH (needed for --containers)")
    fmt = "{{.Names}}\t{{.Ports}}"
    # Fixed argument list, no shell.
    out = (
        subprocess.run(  # noqa: S603
            [docker, "ps", "--filter", f"name={app}", "--format", fmt],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .splitlines()
    )
    report(bool(out), "exposure", f"{len(out)} running containers found")
    for line in out:
        name, _, ports = line.partition("\t")
        service = name.split("-", 1)[0]
        report(
            "->" not in ports,
            "exposure",
            f"{service}: no port published on the host" + (f" ({ports})" if "->" in ports else ""),
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--web", required=True, help="base URL of the web container, e.g. http://<address>:8080")
    ap.add_argument("--public", help="public https URL of the same site (checks Cloudflare Access)")
    ap.add_argument("--containers", help="Coolify application UUID; checks its containers publish no port")
    args = ap.parse_args()
    web = args.web.rstrip("/")

    routes = public_routes(web)
    check_headers(web)
    check_routes_and_writes(web, routes)
    check_accounts(web)
    check_leaks(web, routes)
    if args.public:
        check_access(args.public.rstrip("/"))
    if args.containers:
        check_exposure(args.containers)

    print(f"\n{'FAILED' if failures else 'PASSED'}: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
