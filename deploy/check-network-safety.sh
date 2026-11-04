#!/bin/sh
# Pre-deploy guard: run on the Docker host before every Coolify deploy, start or restart of SIMOLA.
# Coolify creates each application's network WITHOUT a subnet, so the Docker daemon picks the range.
# This refuses (exit 1) unless no new network can land in a private range that may be routed on the
# intranet or LAN (172.16.0.0/12, 192.168.0.0/16): Docker's built-in pools are exactly those ranges.
#
# Ranges that must never appear on the host at all (for example the site intranet) are passed in
# SIMOLA_FORBIDDEN_NETS (comma-separated CIDRs). They are site-specific, so they are not stored here.
#   SIMOLA_FORBIDDEN_NETS=<cidr>[,<cidr>...] deploy/check-network-safety.sh
# Read-only: it creates, changes and restarts nothing.
set -eu

python3 - <<'EOF'
import ipaddress, json, os, subprocess, sys, time

PRIVATE = [ipaddress.ip_network("172.16.0.0/12"), ipaddress.ip_network("192.168.0.0/16")]
never = [ipaddress.ip_network(n.strip()) for n in os.environ.get("SIMOLA_FORBIDDEN_NETS", "").split(",") if n.strip()]
problems = []

# 1. Ranges that must never be used may not appear in any route or address on the host.
routes = subprocess.run(["ip", "-4", "route"], capture_output=True, text=True).stdout
addrs = subprocess.run(["ip", "-4", "-br", "addr"], capture_output=True, text=True).stdout
for line in (routes + addrs).splitlines():
    for tok in line.replace("/", " /").split():
        try:
            ip = ipaddress.ip_address(tok)
        except ValueError:
            continue
        for net in never:
            if ip in net:
                problems.append(f"forbidden range {net} in use on the host: {line.strip()}")

# 2. The daemon must have address pools, none overlapping a private or forbidden range.
path = "/etc/docker/daemon.json"
try:
    cfg = json.load(open(path))
except FileNotFoundError:
    cfg = {}
pools = cfg.get("default-address-pools") or []
if not pools:
    problems.append(f"{path} has no default-address-pools: Docker would use its built-in 172.17-31.x/16 pool")
for p in pools:
    base = ipaddress.ip_network(p["base"])
    for bad in PRIVATE + never:
        if base.overlaps(bad):
            problems.append(f"address pool {base} overlaps {bad}")

# 3. The pools must be in effect: dockerd started after daemon.json last changed.
pid = subprocess.run(["pidof", "dockerd"], capture_output=True, text=True).stdout.split()
if not pid:
    problems.append("dockerd is not running")
elif pools:
    elapsed = int(subprocess.run(["ps", "-o", "etimes=", "-p", pid[0]], capture_output=True, text=True).stdout)
    if os.path.getmtime(path) > time.time() - elapsed:
        problems.append(f"{path} changed after dockerd started: restart Docker for the pools to apply")

if problems:
    print("NETWORK SAFETY CHECK FAILED - do not deploy:")
    for p in problems:
        print("  -", p)
    sys.exit(1)
checked = f"; forbidden ranges absent: {', '.join(map(str, never))}" if never else ""
print("network safety check passed: new Docker networks come from", ", ".join(p["base"] for p in pools) + checked)
EOF
