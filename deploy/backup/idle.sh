#!/bin/sh
# The backup container waits for someone to ask. Backups never run on a schedule (Product Owner, 2026-11-04):
# run backup-now to back up and backup-verify to check that a backup restores (docs/runbooks/backup-restore.md).
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup: ready; backups run only on request (backup-now, backup-verify)"
trap 'exit 0' TERM INT
while true; do
  sleep 86400 &
  wait $!
done
