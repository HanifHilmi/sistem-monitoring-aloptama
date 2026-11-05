#!/bin/sh
# Tests for backup-now and backup-verify with stand-in pg_dump, pg_restore and psql (no database, no Docker).
# Run: sh deploy/backup/test.sh   (CI runs it with dash; the container's shell is busybox: busybox sh test.sh)
set -eu
here=$(cd "$(dirname "$0")" && pwd)
run_sh=${TEST_SH:-sh}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin"
export SIMOLA_BACKUP_LIB="$here/lib.sh" PGDATABASE=simola STUB_LOG="$work/psql.log" PATH="$work/bin:$PATH"

cat >"$work/bin/pg_dump" <<'EOF'
#!/bin/sh
[ "${STUB_DUMP_FAIL:-0}" = 1 ] && { echo "pg_dump: error: connection refused" >&2; exit 1; }
while [ $# -gt 0 ]; do [ "$1" = -f ] && { echo "dump of simola" >"$2"; exit 0; }; shift; done
exit 1
EOF
cat >"$work/bin/pg_restore" <<'EOF'
#!/bin/sh
case "$*" in
  *--list*) printf ';\n; Archive created\n1; 2615 2200 SCHEMA - public\n2; 1259 16385 TABLE public setting\n' ;;
  *) [ "${STUB_RESTORE_ERR:-0}" = 1 ] && echo "pg_restore: error: could not execute query" >&2; exit 0 ;;
esac
EOF
cat >"$work/bin/psql" <<'EOF'
#!/bin/sh
db=${PGDATABASE}
prev=""
for a in "$@"; do [ "$prev" = -d ] && db=$a; prev=$a; done
printf '[%s] %s\n' "$db" "$(echo "$*" | tr '\n' ' ')" >>"$STUB_LOG"
case "$*" in
  *"SELECT tablename"*) printf 'awos_cat3_minute\njob\nsetting\n' ;;
  *"information_schema.columns"*"awos_cat3_minute"*) echo time ;;
  *"information_schema.columns"*) ;;
  *"count(*)"*"\"setting\""*) if [ "$db" = simola_verify ] && [ "${STUB_DIFF:-0}" = 1 ]; then echo 3; else echo 4; fi ;;
  *"count(*)"*"\"job\""*) if [ "$db" = simola_verify ]; then echo 1; else echo 2; fi ;;
  *"count(*)"*) echo 1440 ;;
esac
exit 0
EOF
chmod +x "$work/bin/"*

pass=0
ok() { pass=$((pass + 1)); echo "ok $pass - $1"; }
no() { echo "not ok - $1"; echo "--- output"; cat "$work/out" 2>/dev/null || true; exit 1; }
now() { BACKUP_DIR="$work/$1" $run_sh "$here/backup-now" >"$work/out" 2>&1; }
verify() { d=$1; shift; BACKUP_DIR="$work/$d" $run_sh "$here/backup-verify" "$@" >"$work/out" 2>&1; }

# 1. A backup: dump, checksum, recorded as ok, nothing left over, nothing deleted.
now b1 || no "backup-now succeeds"
f=$(find "$work/b1" -name 'simola-*.dump')
[ -n "$f" ] && [ -f "$f.sha256" ] || no "dump and checksum written"
(cd "$work/b1" && sha256sum -c "$(basename "$f").sha256" >/dev/null) || no "checksum matches"
[ -z "$(find "$work/b1" -name '*.partial*')" ] || no "no partial file left"
grep -q "INSERT INTO backup_run" "$STUB_LOG" && grep "INSERT INTO backup_run" "$STUB_LOG" | grep -q " true, " || no "recorded as ok"
grep -q "no backup was deleted" "$work/out" || no "says nothing was deleted"
ok "backup-now writes a checked dump and records it"

# 2. pg_dump fails: no dump file, recorded as failed, non-zero exit.
: >"$STUB_LOG"
if STUB_DUMP_FAIL=1 now b2; then no "backup-now fails when pg_dump fails"; fi
[ -z "$(find "$work/b2" -name 'simola-*' 2>/dev/null)" ] || no "no file left after a failed dump"
grep "INSERT INTO backup_run" "$STUB_LOG" | grep -q " false, " || no "failure recorded"
ok "a failed dump leaves no file and is recorded"

# 3. The off-host copy fails: the local dump stays, the run is recorded as failed.
: >"$STUB_LOG"
if BACKUP_UPLOAD_CMD="false" now b3; then no "backup-now fails when the upload fails"; fi
[ -n "$(find "$work/b3" -name 'simola-*.dump')" ] || no "local dump kept"
grep -q "off-host copy FAILED" "$STUB_LOG" || no "upload failure recorded"
ok "a failed off-host copy keeps the local dump"

# 4. One run at a time.
mkdir -p "$work/b4"
(flock 9; sleep 3) 9>"$work/b4/.lock" &
sleep 1
if now b4; then no "a second run is refused"; fi
grep -q "another backup-now or backup-verify is running" "$work/out" || no "says why"
wait
ok "a second run at the same time is refused"

# 5. Verify: restores into the scratch database, compares, drops it.
: >"$STUB_LOG"
verify b1 || no "backup-verify passes"
grep -q "PASSED" "$work/out" || no "says PASSED"
grep -q "job .*ok (changes by itself)" "$work/out" || no "changing tables only need to be present"
grep -q "awos_cat3_minute (<cutoff)" "$work/out" || no "minute tables compared before the cutoff"
grep -q "CREATE DATABASE simola_verify" "$STUB_LOG" || no "scratch database created"
tail -n 1 "$STUB_LOG" | grep -q "DROP DATABASE IF EXISTS simola_verify" || no "scratch database dropped at the end"
! grep -q "^\[simola\] .*\(DROP\|CREATE\) DATABASE simola\b" "$STUB_LOG" || no "live database untouched"
ok "backup-verify restores into a scratch database and drops it"

# 6. A table that differs fails, and the scratch database is still dropped.
: >"$STUB_LOG"
if STUB_DIFF=1 verify b1; then no "a differing table fails"; fi
grep -q "setting .*FAIL: differs" "$work/out" || no "names the table"
tail -n 1 "$STUB_LOG" | grep -q "DROP DATABASE IF EXISTS simola_verify" || no "dropped after a failure"
ok "a differing table fails the check"

# 7. Restore errors fail the check.
if STUB_RESTORE_ERR=1 verify b1; then no "restore errors fail"; fi
grep -q "1 restore error" "$work/out" || no "counts the errors"
ok "restore errors fail the check"

# 8. A damaged file fails before anything is restored; no backup at all fails too.
f=$(find "$work/b1" -name 'simola-*.dump')
cp "$f" "$work/keep" && echo "x" >>"$f"
: >"$STUB_LOG"
if verify b1; then no "a damaged file fails"; fi
grep -q "does not match its checksum" "$work/out" || no "says the checksum differs"
! grep -q "CREATE DATABASE" "$STUB_LOG" || no "nothing restored from a damaged file"
mkdir -p "$work/empty"
if verify empty; then no "no backup fails"; fi
grep -q "no backup found" "$work/out" || no "says no backup was found"
ok "damaged or missing backups fail early"

echo "all $pass passed ($run_sh)"
