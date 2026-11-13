#!/usr/bin/env bash
# Tests install_migrations.py (migrations 027-052) on one throwaway postgres:17 container
# at a time. No port is published and no real database or credential is involved: the
# passwords are random and live only for this run. Nothing is written under docs/.
#
# The container is a plain postgres:17 with test-only stand-ins for what Supabase
# provides (empty_db_baseline.sql). Scenarios: two runs, an upgrade from 048 to 052,
# checksum drift (file and ledger), identity mismatch, host guard, installer lock,
# ledger gap, a failing migration and its rollback, a database that is not ready.
#
# Usage: dev/gis_install/test_pg17.sh
set -euo pipefail

export MSYS_NO_PATHCONV=1   # Git Bash on Windows would rewrite /var/run/postgresql
PY="${PYTHON:-$(command -v python3 || command -v python)}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

CONTAINER=pgtest
IMAGE=postgres:17
LABEL=gis-install-test=1
MIGRATIONS=green-area-backend/migrations
INSTALLER=dev/gis_install/install_migrations.py
WORK="$(mktemp -d)"
command -v cygpath >/dev/null && WORK="$(cygpath -m "$WORK")"   # a path python.exe can also open
RUNS="$WORK/runs.txt"
FIRST=27
LAST=52
COUNT=26
ADMIN_USER=bootstrap_admin

ADMIN_PASSWORD="$(openssl rand -hex 24)"
SECRET_PART="$(openssl rand -hex 16)"
# Characters that must be URL-encoded, so that decoding is exercised too.
PASSWORD="W2@x/$SECRET_PART"
export POSTGRES_PASSWORD="$ADMIN_PASSWORD"
export GIS_INSTALL_DATABASE_URL="postgresql://postgres:W2%40x%2F$SECRET_PART@127.0.0.1:5432/postgres"
export GIS_INSTALL_PSQL="docker run --rm -i --network container:$CONTAINER -e PGHOST -e PGPORT -e PGUSER -e PGPASSWORD -e PGDATABASE -e PGSSLMODE $IMAGE psql"
export GIS_CLUSTER_NAME=pgtestlocalcontainer
GIS_RUNTIME_INSTANCE="$(openssl rand -hex 16)"
export GIS_RUNTIME_INSTANCE
# The same definition as the sandbox: the concatenated bytes of 000-026.
GIS_BASELINE_FINGERPRINT="$(for n in $(seq -f '%03g' 0 26); do cat "$MIGRATIONS/$n"_*.sql; done | sha256sum | cut -d' ' -f1)"
export GIS_BASELINE_FINGERPRINT

remove_container() {
  local label
  label="$(docker inspect --format '{{index .Config.Labels "gis-install-test"}}' "$CONTAINER" 2>/dev/null || true)"
  if [ "$label" = "1" ]; then
    docker rm -f "$CONTAINER" >/dev/null
  elif docker inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "a container named $CONTAINER exists that this test did not create: remove it yourself" >&2
    exit 1
  fi
}
cleanup() { remove_container || true; rm -rf "$WORK"; }
trap cleanup EXIT

admin() { docker exec -i "$CONTAINER" psql -X -q -v ON_ERROR_STOP=1 -h /var/run/postgresql -U "$ADMIN_USER" -d postgres "$@"; }
scalar() { admin -At -c "$1"; }

wait_ready() {
  # TCP only comes up once initialisation has finished and the real server started.
  for _ in $(seq 1 90); do
    if [ "$(docker inspect --format '{{.State.Running}}' "$CONTAINER")" != "true" ]; then
      docker logs "$CONTAINER" 2>&1 | tail -n 20 >&2
      echo "the container stopped during startup" >&2
      exit 1
    fi
    docker exec "$CONTAINER" pg_isready -q -h 127.0.0.1 -U postgres && return 0
    sleep 1
  done
  echo "the container did not become ready" >&2
  exit 1
}

# A blank cluster whose `postgres` is not a superuser, as on the real project.
start_blank() {
  remove_container
  ADMIN_USER=bootstrap_admin
  docker run -d --name "$CONTAINER" --label "$LABEL" -e POSTGRES_USER="$ADMIN_USER" \
    -e POSTGRES_PASSWORD -e POSTGRES_DB=postgres "$IMAGE" >/dev/null
  wait_ready
  printf "CREATE ROLE postgres LOGIN CREATEROLE CREATEDB NOSUPERUSER PASSWORD '%s';\nALTER DATABASE postgres OWNER TO postgres;\n" \
    "$PASSWORD" | admin
}

load_legacy() {
  for n in $(seq -f '%03g' 0 26); do
    PGPASSWORD="$PASSWORD" docker exec -i -e PGPASSWORD "$CONTAINER" \
      psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -U postgres -d postgres \
      < "$(echo "$MIGRATIONS/$n"_*.sql)" >/dev/null 2>"$WORK/legacy.err" || { cat "$WORK/legacy.err" >&2; exit 1; }
  done
}

install() { "$PY" "$INSTALLER" "$@"; }
ledger() { scalar "SELECT version,sha256,applied_at FROM gis.schema_migrations ORDER BY version"; }
versions() { scalar "SELECT string_agg(version::text,',' ORDER BY version) FROM gis.schema_migrations"; }

check() { # check <description> <actual> <expected>
  if [ "$2" != "$3" ]; then
    echo "FAIL  $1: expected [$3], got [$2]" | tee -a "$RUNS" >&2
    exit 1
  fi
  echo "PASS  $1" | tee -a "$RUNS"
}

# Runs the installer expecting it to refuse, and checks the reason it gives.
expect_refusal() { # expect_refusal <description> <reason> [installer args]
  local description="$1" reason="$2"
  shift 2
  if install "$@" >"$WORK/refusal.log" 2>&1; then
    check "$description: installer refused" "exit 0" "exit non-zero"
  fi
  cat "$WORK/refusal.log" >>"$WORK/all.log"
  check "$description: reason is reported" "$(grep -c -- "$reason" "$WORK/refusal.log")" "1"
}

copy_migrations() { rm -rf "$WORK/m"; mkdir "$WORK/m"; cp "$MIGRATIONS"/0{27..52}_*.sql "$WORK/m/"; }

# Warnings mean a GRANT or REVOKE had no effect, so what they leave behind is checked.
check_boundary() {
  check "no client role can use schema gis" "$(scalar "SELECT count(*) FROM unnest(ARRAY['anon','authenticated','service_role','authenticator']) r WHERE has_schema_privilege(r,'gis','USAGE') OR has_schema_privilege(r,'gis','CREATE')")" "0"
  check "PUBLIC, anon and authenticated cannot execute any GIS function" "$(scalar "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE (n.nspname='gis' OR (n.nspname='public' AND p.proname LIKE 'gis\_%')) AND (has_function_privilege('anon',p.oid,'EXECUTE') OR has_function_privilege('authenticated',p.oid,'EXECUTE') OR EXISTS(SELECT 1 FROM aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a WHERE a.grantee=0))")" "0"
  check "client roles cannot reach any gis table" "$(scalar "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace, unnest(ARRAY['anon','authenticated','service_role']) r WHERE n.nspname='gis' AND c.relkind IN ('r','v','m') AND has_table_privilege(r,c.oid,'SELECT,INSERT,UPDATE,DELETE')")" "0"
  check "gis_owner kept no CREATE on schema public" "$(scalar "SELECT has_schema_privilege('gis_owner','public','CREATE')")" "f"
}

run_twice() { # run_twice <file for the gis_readiness() result>
  local out="$1"
  check "the migrator is not a superuser" "$(scalar "SELECT rolsuper FROM pg_roles WHERE rolname='postgres'")" "f"
  check "no gis schema before the first run" "$(scalar "SELECT to_regnamespace('gis') IS NULL")" "t"

  echo "--- run 1 ---" | tee -a "$RUNS"
  install --readiness-out "$WORK/readiness-run1.json" 2>&1 | tee "$WORK/run1.log" | tee -a "$RUNS"
  ledger >"$WORK/ledger1.txt"
  check "run 1 applied all $COUNT" "$(tail -n1 "$WORK/run1.log")" "done      installed through 052: applied $COUNT, skipped 0"

  echo "--- run 2 ---" | tee -a "$RUNS"
  install --readiness-out "$out" 2>&1 | tee "$WORK/run2.log" | tee -a "$RUNS"
  ledger >"$WORK/ledger2.txt"
  check "run 2 applied nothing" "$(tail -n1 "$WORK/run2.log")" "done      installed through 052: applied 0, skipped $COUNT"
  check "ledger is identical after run 2, applied_at included" "$(sha256sum <"$WORK/ledger2.txt")" "$(sha256sum <"$WORK/ledger1.txt")"
  check "both gis_readiness() files were written" "$([ -s "$out" ] && [ -s "$WORK/readiness-run1.json" ] && echo yes)" "yes"
  check "gis_readiness() is identical after run 2" "$(sha256sum <"$out")" "$(sha256sum <"$WORK/readiness-run1.json")"
  check "ledger holds exactly 27 to 52" "$(versions)" "$(seq -s, $FIRST $LAST)"
  check "gis_native_worker has the boundary 032 requires" \
    "$(scalar "SELECT rolcanlogin OR rolsuper OR rolinherit FROM pg_roles WHERE rolname='gis_native_worker'")" "f"
  "$PY" - "$out" <<'PY' | tee -a "$RUNS"
import json, os, sys
value = json.load(open(sys.argv[1]))
assert value["cluster_name"] == os.environ["GIS_CLUSTER_NAME"], value["cluster_name"]
assert value["mode"] == "cloud", value["mode"]
assert value["migration_versions"] == list(range(27, 53)), value["migration_versions"]
print(f"PASS  gis_readiness(): cluster_name={value['cluster_name']} mode={value['mode']}")
PY
  check_boundary
  cat "$WORK/run1.log" "$WORK/run2.log" >>"$WORK/all.log"
}

{
  echo "W2 installer test. Throwaway containers only; project ref is fake."
  echo "commit under test: $(git rev-parse --short HEAD)"
  echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >"$RUNS"

fresh() { start_blank; admin < dev/gis_install/empty_db_baseline.sql; load_legacy; }

echo "=== postgres:17: blank database, run twice ===" | tee -a "$RUNS"
start_blank
admin < dev/gis_install/empty_db_baseline.sql
load_legacy
scalar "SELECT 'server: '||version()" | tee -a "$RUNS"
run_twice "$WORK/readiness.json"

echo "=== postgres:17: refusals on the installed database ===" | tee -a "$RUNS"
copy_migrations
echo "-- changed" >>"$WORK/m/028_gis_queue.sql"
expect_refusal "changed file" "checksum drift" --migrations-dir "$WORK/m"
ledger >"$WORK/ledger3.txt"
check "ledger unchanged after the drift refusal" "$(sha256sum <"$WORK/ledger3.txt")" "$(sha256sum <"$WORK/ledger1.txt")"
GIS_RUNTIME_INSTANCE="$(openssl rand -hex 16)" expect_refusal "different identity" "different identity"
GIS_INSTALL_DATABASE_URL="postgresql://postgres:unused@db.abcdefghijklmnopqrst.supabase.co:5432/postgres"   expect_refusal "hosted host" "never accepted"
GIS_INSTALL_DATABASE_URL="postgresql://postgres:unused@db.abcdefghijklmnopqrst.supabase.co:5432/postgres"   expect_refusal "hosted host even with the remote flag" "never accepted" --allow-remote-host
GIS_INSTALL_DATABASE_URL="postgresql://postgres:unused@db.example.org:5432/postgres"   expect_refusal "non-local host" "non-local host" --lock-timeout 5s
# Holds the same advisory lock from another session: the installer must fail fast.
LOCK_ID="$("$PY" -c "import re,sys;print(re.search(r'LOCK_ID = (\d+)',open('$INSTALLER').read()).group(1))")"
(printf 'SELECT pg_advisory_lock(%s);
SELECT pg_sleep(40);
' "$LOCK_ID" | admin >/dev/null 2>&1) &
sleep 3
expect_refusal "concurrent run" "another installer run"
wait
scalar "DELETE FROM gis.schema_migrations WHERE version=28" >/dev/null
expect_refusal "ledger gap" "ledger gap: 028"

echo "=== postgres:17: a tampered ledger checksum is drift ===" | tee -a "$RUNS"
fresh
install >/dev/null 2>&1
scalar "UPDATE gis.schema_migrations SET sha256=repeat('0',64) WHERE version=40" >/dev/null
expect_refusal "ledger sha256 tampered" "migration 040 checksum drift"
rc=0; install >/dev/null 2>&1 || rc=$?
check "tampered ledger: installer exit code is non-zero (got $rc)" "$([ "$rc" -ne 0 ] && echo nonzero)" "nonzero"

echo "=== postgres:17: upgrade from 048 to 052 ===" | tee -a "$RUNS"
fresh
install --up-to 48 2>&1 | tee "$WORK/up1.log" | tee -a "$RUNS"
check "first stage applied 22" "$(tail -n1 "$WORK/up1.log")" "done      installed through 048: applied 22, skipped 0"
check "ledger holds exactly 27 to 48" "$(versions)" "$(seq -s, 27 48)"
install --readiness-out "$WORK/readiness-up.json" 2>&1 | tee "$WORK/up2.log" | tee -a "$RUNS"
cat "$WORK/up1.log" "$WORK/up2.log" >>"$WORK/all.log"
check "upgrade applied 049-052 and skipped 027-048" "$(tail -n1 "$WORK/up2.log")" "done      installed through 052: applied 4, skipped 22"
check "049 to 052 were applied, in order" "$(grep -c '^applied   0\(49\|5[012]\)_' "$WORK/up2.log")" "4"
check "027 to 048 were skipped" "$(grep -c '^skip      0\(2[7-9]\|3[0-9]\|4[0-8]\)_' "$WORK/up2.log")" "22"
check "ledger holds exactly 27 to 52" "$(versions)" "$(seq -s, $FIRST $LAST)"
install 2>&1 | tee "$WORK/up3.log" >>"$WORK/all.log"
check "re-run after the upgrade applied 0" "$(tail -n1 "$WORK/up3.log")" "done      installed through 052: applied 0, skipped $COUNT"
check_boundary

echo "=== postgres:17: a failing migration stops the run and rolls back ===" | tee -a "$RUNS"
fresh
copy_migrations
{
  echo "CREATE TABLE public.w2_rollback_marker(id int);"
  echo "SELECT 1/0;"
} >>"$WORK/m/029_gis_transactions.sql"
expect_refusal "failing 029" "division by zero" --migrations-dir "$WORK/m"
check "only the migrations before it are recorded" "$(versions)" "27,28"
check "the failing file's work was rolled back" "$(scalar "SELECT to_regclass('public.w2_rollback_marker') IS NULL")" "t"
install 2>&1 | tee "$WORK/resume.log" >>"$WORK/all.log"
check "re-run resumes from 029" "$(tail -n1 "$WORK/resume.log")" "done      installed through 052: applied 24, skipped 2"

echo "=== postgres:17: a database that is not ready is refused ===" | tee -a "$RUNS"
start_blank
expect_refusal "no baseline" "the database is not ready"
check "nothing was written" "$(scalar "SELECT to_regnamespace('gis') IS NULL AND NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='gis_native_worker')")" "t"

LEAKS="$(cat "$WORK/all.log" "$RUNS" "$WORK"/readiness*.json | grep -c -e "$SECRET_PART" -e "$ADMIN_PASSWORD" || true)"
check "no password in any log or evidence file" "$LEAKS" "0"
echo "ALL PASSED" | tee -a "$RUNS"
