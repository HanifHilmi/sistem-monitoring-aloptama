# Shared by backup-now and backup-verify. The PG* variables (host, user, password, database) come from the
# container's environment (docker-compose.yml, service "backup").
BACKUP_DIR=${BACKUP_DIR:-/backups}

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

fail() {
  log "FAILED: $*" >&2
  exit 1
}

sql_literal() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/''/g")"; }

human() { # bytes -> "123.4 MB"
  awk -v b="$1" 'BEGIN { split("B KB MB GB TB", u); i = 1; while (b >= 1024 && i < 5) { b /= 1024; i++ }
    if (i == 1) printf "%d %s", b, u[i]; else printf "%.1f %s", b, u[i] }'
}

# One backup or check at a time; the lock is released when the process ends, however it ends.
take_lock() {
  mkdir -p "$BACKUP_DIR"
  exec 9>"$BACKUP_DIR/.lock"
  flock -n 9 || fail "another backup-now or backup-verify is running"
}
