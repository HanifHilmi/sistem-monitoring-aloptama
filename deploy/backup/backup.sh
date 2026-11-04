#!/bin/sh
# SIMOLA nightly backup (PRD NFR-BAK-001..004, §12.8).
# - pg_dump custom format into /backups/daily, copied to weekly (Sundays) and monthly (1st of month)
# - retention: BACKUP_KEEP_DAILY / _WEEKLY / _MONTHLY files per directory
# - optional off-host copy: BACKUP_UPLOAD_CMD is run with the dump path as $1 (destination: OPEN-01)
# - every run is recorded in the backup_run table, which feeds the health page and Problems panel
set -eu

BACKUP_DIR=/backups
: "${BACKUP_ENABLED:=false}" "${BACKUP_HOUR_UTC:=18}" "${BACKUP_RUN_ON_START:=false}"
: "${BACKUP_KEEP_DAILY:=7}" "${BACKUP_KEEP_WEEKLY:=4}" "${BACKUP_KEEP_MONTHLY:=12}" "${BACKUP_UPLOAD_CMD:=}"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup: $*"; }

sql_literal() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/''/g")"; }

record() { # started ok size file message
  psql -X -q -v ON_ERROR_STOP=1 -c "INSERT INTO backup_run (started_at, finished_at, ok, size_bytes, file_name, message)
    VALUES ('$1', now(), $2, $3, $(sql_literal "$4"), $(sql_literal "$5"))" || log "could not record result"
}

prune() { # dir keep
  ls -1t "$1"/*.dump 2>/dev/null | tail -n +"$(($2 + 1))" | while read -r f; do rm -f -- "$f"; done
}

run_backup() {
  started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  name="simola-$(date -u +%Y%m%dT%H%MZ).dump"
  mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly" "$BACKUP_DIR/monthly"
  tmp="$BACKUP_DIR/daily/.$name.partial"
  if ! pg_dump -Fc -Z 6 -f "$tmp"; then
    rm -f "$tmp"; log "pg_dump failed"; record "$started" false NULL "$name" "pg_dump failed"; return 1
  fi
  mv "$tmp" "$BACKUP_DIR/daily/$name"
  size=$(wc -c < "$BACKUP_DIR/daily/$name")
  [ "$(date -u +%u)" = "7" ] && cp "$BACKUP_DIR/daily/$name" "$BACKUP_DIR/weekly/$name"
  [ "$(date -u +%d)" = "01" ] && cp "$BACKUP_DIR/daily/$name" "$BACKUP_DIR/monthly/$name"
  prune "$BACKUP_DIR/daily" "$BACKUP_KEEP_DAILY"
  prune "$BACKUP_DIR/weekly" "$BACKUP_KEEP_WEEKLY"
  prune "$BACKUP_DIR/monthly" "$BACKUP_KEEP_MONTHLY"
  msg="local copy only (off-host destination not configured)"
  if [ -n "$BACKUP_UPLOAD_CMD" ]; then
    if sh -c "$BACKUP_UPLOAD_CMD \"\$1\"" upload "$BACKUP_DIR/daily/$name"; then
      msg="uploaded off-host"
    else
      log "upload failed"; record "$started" false "$size" "$name" "dump ok, off-host upload FAILED"; return 1
    fi
  fi
  record "$started" true "$size" "$name" "$msg"
  log "ok $name ($size bytes) - $msg"
}

seconds_until_next_run() {
  now=$(date -u +%s)
  target=$(date -u -d "$(date -u +%Y-%m-%d) ${BACKUP_HOUR_UTC}:00:00" +%s 2>/dev/null || echo 0)
  [ "$target" -le "$now" ] && target=$((target + 86400))
  echo $((target - now))
}

if [ "$BACKUP_ENABLED" != "true" ]; then
  log "disabled (SIMOLA_BACKUP_ENABLED is not true); idling"
  while true; do sleep 86400; done
fi

[ "$BACKUP_RUN_ON_START" = "true" ] && { run_backup || true; }
while true; do
  wait_s=$(seconds_until_next_run)
  log "next run in ${wait_s}s"
  sleep "$wait_s"
  run_backup || true
done
