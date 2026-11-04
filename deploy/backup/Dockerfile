# Backup sidecar: the database image (same pg_dump version as the server) plus the backup script.
# The script is baked in because Coolify does not keep repository files on disk for bind mounts.
FROM timescale/timescaledb:2.30.2-pg17
COPY backup.sh /opt/simola/backup.sh
ENTRYPOINT ["/bin/sh", "/opt/simola/backup.sh"]
