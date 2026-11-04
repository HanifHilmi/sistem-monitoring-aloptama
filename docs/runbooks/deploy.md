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
1. **Read-only CDP shares (H-1):** add `ro` to the two CIFS lines in `/etc/fstab`, then remount (`sudo umount /mnt/<cdp1-share-mount> && sudo mount /mnt/<cdp1-share-mount>`, and the same for CDP2). Check with `mount | grep cdp`: it must show `ro`.
2. **Data directories (H-2):**
   ```bash
   sudo mkdir -p /var/lib/simola/{production,staging}/{pg,backups}
   ```
3. **Cloudflare (H-3):**
   - In the tunnel's *Public hostnames*, add `simola.hilmihanif.my.id` and `simola-staging.hilmihanif.my.id`, both pointing to the same origin as the existing site (Traefik on the host).
   - In *Access → Applications*, protect:
     - all of `simola-staging.hilmihanif.my.id`;
     - all of `simola.hilmihanif.my.id` until cutover;
     - after cutover and until R2, only `simola.hilmihanif.my.id/internal/*` and `simola.hilmihanif.my.id/api/v1/internal/*`.

## Create the Coolify applications

For each of **simola-staging** (branch `staging`) and **simola-production** (branch `main`):

1. *New resource → Public/Private repository → Docker Compose*, compose file `/docker-compose.yml`.
2. Set the domain on the **web** service only, port 8080: `https://simola-staging.hilmihanif.my.id` (or the production one).
3. Turn **off** "auto deploy on push". CI triggers deploys after all checks pass (`.github/workflows/ci.yml`).
4. Environment variables: copy `.env.example` and set real values.
   - Production: `SIMOLA_ENVIRONMENT=production`, `SIMOLA_PG_DATA_DIR=/var/lib/simola/production/pg`, `SIMOLA_BACKUP_DIR=/var/lib/simola/production/backups`, `SIMOLA_BACKUP_ENABLED=true`, `SIMOLA_BACKUP_EXPECTED=true`.
   - Staging: smaller memory limits, `SIMOLA_BACKUP_ENABLED=false`.
   - Use different passwords per environment, generated with `openssl rand -hex 24` (hex only: `/`, `+` or `@` would break the database URL).
5. Deploy. Startup order is `db` → `migrate` (exits 0) → `api`, `worker`, `backup` → `web`.

## Verify after every deploy

```bash
curl -fsS https://simola-staging.hilmihanif.my.id/health          # {"status":"ok"}
docker ps --format '{{.Names}} {{.Status}}' | grep simola          # all healthy, migrate exited
ss -ltn | grep 5432                                                # SIMOLA's db must NOT appear
```

On first deploy, load history: see [history.md](history.md).

## Rollback

Redeploy the previous commit in Coolify. Migrations are backward-compatible for one release (NFR-OPS-002). Data directories are untouched by deploys.
