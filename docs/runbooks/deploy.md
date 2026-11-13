# Runbook: deploy SIMOLA with Coolify

Every step below changes shared infrastructure. Do each one only with the Product Owner's go-ahead.

**Rules:** SIMOLA is deployed only by Coolify (UI or Coolify API/MCP); never `docker compose up` or `docker run` by hand on the
server. The compose file declares no networks of its own; Coolify creates one network per application **without a
subnet**, so its range comes from the Docker daemon. Docker's built-in pools are 172.17–31.x/16 and 192.168.x/20, which
can hijack intranet routes: do H-0 before the first deploy.

## One-time host preparation (PRD §12.9)

0. **Docker address pools (H-0):** in `/etc/docker/daemon.json` add
   `"default-address-pools": [{"base": "10.0.0.0/16", "size": 24}]` (keep the existing keys), then restart Docker at a
   quiet time (`sudo systemctl restart docker`; every container on the host restarts). Only networks created afterwards
   use the new range. Before every deploy, start or restart run `deploy/check-network-safety.sh` on the host (with
   the site's intranet ranges in `SIMOLA_FORBIDDEN_NETS`, never written in this repository) and do not continue unless
   it passes; after the deploy, check `ip route` shows no new 172.16.0.0/12 or 192.168.0.0/16 route.
1. **Read-only CDP shares (H-1):** the shares must refuse writes from this host: either the CDP's share permissions
   give the mount's account read access only, or the host mounts them `ro` (add `ro` to the two CIFS lines in
   `/etc/fstab`, `sudo systemctl daemon-reload`, then `sudo mount -o remount,ro /mnt/<cdp1-share-mount>` and the same
   for CDP2; `findmnt -t cifs` then shows `ro`). Keep `x-systemd.automount`, so a share that is down at boot is
   mounted when it comes back.

   SIMOLA binds the folder that holds both mounts (`SIMOLA_CDP_ROOT`, here `/mnt`) with the shares' folder names in
   `SIMOLA_CDP1_DIR` and `SIMOLA_CDP2_DIR`. Docker then checks only that local folder when it creates the worker, so a
   CDP that is off the network cannot block a deploy. The worker sees the whole folder read-only, so keep nothing
   else of value in it. Because the binding passes on mounts the host makes later, Docker cannot force the shares
   read-only inside the container; the read-only shares (and the worker's own user, which has no write permission
   on them) are what keep SIMOLA from writing.
2. **Data directories (H-2):**
   ```bash
   sudo mkdir -p /var/lib/simola/{production,staging}/{pg,backups}
   ```
3. **Cloudflare (H-3):**
   - In the tunnel's *Public hostnames*, `simola.hilmihanif.my.id` and `simola-staging.hilmihanif.my.id` both point to
     the same origin (Traefik on the host).
   - *Access → Applications* protects all of `simola-staging.hilmihanif.my.id` (NFR-SEC-008).
   - Production has no Access policy since the switch on 2026-11-11: the dashboards are public, and SIMOLA's own
     sign-in protects the Viewer and Admin areas. An Access policy on `/admin*` and `/api/v1/admin*` is an optional
     second lock (decision D4, [accounts.md](accounts.md)).
   - The old hostname `rhf-monitoring.hilmihanif.my.id` answers 404 since v2 stopped; its redirect to SIMOLA is
     still to do ([cutover.md](cutover.md), section 3).

## Create the Coolify applications

For each of **simola-staging** (branch `staging`) and **simola-production** (branch `main`):

1. *New resource → Public/Private repository → Docker Compose*, compose file `/docker-compose.yml`.
2. Set the domain on the **web** service only, port 8080: `https://simola-staging.hilmihanif.my.id` (or the production one).
3. Turn **off** "auto deploy on push". Deploy from Coolify (UI or API) only once CI is green for that commit. A CI
   deploy job is prepared in `.github/workflows/ci.yml` but not switched on.
4. Environment variables: copy `.env.example` and set real values.
   - Production: `SIMOLA_ENVIRONMENT=production`, `SIMOLA_PG_DATA_DIR=/var/lib/simola/production/pg`, `SIMOLA_BACKUP_DIR=/var/lib/simola/production/backups`.
   - Staging: smaller memory limits.
   - Backups run only on request in both ([backup-restore.md](backup-restore.md)); there is no schedule to set.
   - `SIMOLA_API_WORKERS` (default 2) sets the API's worker processes; give `SIMOLA_API_MEM` about 150 MB per process plus 100 MB (512m for 2). One process cannot meet NFR-PERF-001/002 under load.
   - Use different passwords per environment, generated with `openssl rand -hex 24` (hex only: `/`, `+` or `@` would break the database URL).
5. Deploy. Startup order is `db` → `migrate` (exits 0) → `api`, `worker`, `backup` → `web`.

## Before every deploy

```bash
SIMOLA_FORBIDDEN_NETS=<intranet ranges> deploy/check-network-safety.sh   # must pass
ip route                                                           # note the routes, to compare afterwards
timeout 5 stat /mnt/<cdp1-share-mount> /mnt/<cdp2-share-mount>     # both shares answer
```

No deploys on 30–31 December: the year's last figures are checked on 1–2 January.

## Verify after every deploy

```bash
curl -fsS https://simola.hilmihanif.my.id/health                   # production: {"status":"ok"}
ip route                                                           # no new 172.16.0.0/12 or 192.168.0.0/16 route
docker ps -a --format '{{.Names}} {{.Status}}' | grep <app-uuid>  # all healthy, migrate exited
ss -ltn | grep 5432                                                # SIMOLA's db must NOT appear
docker exec <worker-container> ls /mnt/cdp/<cdp1-share-folder>/oneminute | tail -1  # today's file; same for CDP2
```

A CDP that is off the network does not stop a deploy: the worker starts, marks that CDP unavailable and reads its
missed minutes from the files once the share answers again.

On first deploy, load history ([history.md](history.md)) and create the first Admin ([accounts.md](accounts.md)).

## When the build fails

- **`npm run build` fails with "Cannot find native binding" (`@rolldown/binding-linux-x64-musl`):** `npm ci` skipped
  rolldown's optional native package without failing (an npm bug with optional dependencies), and Docker cached that
  incomplete step, so a plain redeploy failed the same way; a **force rebuild** (no build cache) fixed it. Seen on
  production on 2026-11-13; the running site was not affected, because Coolify replaces the containers only after a
  successful build. Since then the web Dockerfile loads that package right after `npm ci`, so a bad install fails at
  the `npm ci` step and is not cached: a plain redeploy retries it.

## Rollback

Redeploy the previous commit in Coolify. Migrations are backward-compatible for one release (NFR-OPS-002). Data directories are untouched by deploys.
