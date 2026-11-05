# Backup sidecar: the database image (same pg_dump version as the server) plus the backup commands.
# Backups run only on request (backup-now; backup-verify checks a backup restores): the container just waits.
# The scripts are baked in because Coolify does not keep repository files on disk for bind mounts.
FROM timescale/timescaledb:2.30.2-pg17
COPY lib.sh idle.sh /opt/simola/
COPY backup-now backup-verify /usr/local/bin/
RUN chmod 0755 /usr/local/bin/backup-now /usr/local/bin/backup-verify
ENTRYPOINT ["/bin/sh", "/opt/simola/idle.sh"]
