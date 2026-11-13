#!/usr/bin/env python3
"""Install GIS migrations 027-052 on an external PostgreSQL database (W2).

Required environment:
  GIS_INSTALL_DATABASE_URL   postgresql://user:password@host:port/postgres
  GIS_RUNTIME_INSTANCE       32 lowercase hex characters
  GIS_BASELINE_FINGERPRINT   64 lowercase hex characters
  GIS_CLUSTER_NAME           the project ref, 20 lowercase letters

Optional environment:
  GIS_INSTALL_PSQL           command that runs psql, if it is not on PATH
  GIS_INSTALL_ALLOW_REMOTE_HOST=1   same as --allow-remote-host
  GIS_INSTALL_LOCK_TIMEOUT / GIS_INSTALL_STATEMENT_TIMEOUT
                             same as --lock-timeout / --statement-timeout

Only a local host (localhost, 127.0.0.1, ::1) is accepted unless --allow-remote-host
is given. A *.supabase.co or *.supabase.com host is refused in every case.
A session-level advisory lock is held for the whole run, so a second run against the
same database fails at once instead of interleaving with this one.

The identity values are never generated here: the backend must be given the same
ones, and migrations 030+ compare them with what 027 stored.

What is already applied is read from gis.schema_migrations. An applied version is
skipped only if its recorded sha256 matches the file. Each migration runs in one
transaction together with its ledger row, so a failure rolls that file back, stops
the run, and a re-run resumes from the same place.

The database must already hold the Supabase objects and legacy migrations 000-026
(see preflight). Versions above 052 are never read or applied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from urllib.parse import parse_qsl, quote, unquote, urlsplit

REPO = Path(__file__).resolve().parents[2]
DEFAULT_MIGRATIONS = REPO / "green-area-backend/migrations"
FIRST, LAST = 27, 52
VERSIONS = range(FIRST, LAST + 1)
MODE = "cloud"
DATABASES = {"postgres", "gis_t1_upgrade"}
HOSTED_SUFFIXES = (".supabase.co", ".supabase.com")
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
LOCK_ID = 7305271052027048  # fixed key for pg_try_advisory_lock; one installer per database
TIMEOUT_RE = r"[0-9]+(ms|s|min)"
REQUIRED_ROLES = ("postgres", "anon", "authenticated", "service_role", "authenticator")
REQUIRED_TABLES = ("auth.users", "public.profiles", "public.provinces", "public.districts")
URL_OPTIONS = {"sslmode": "PGSSLMODE", "sslrootcert": "PGSSLROOTCERT",
               "connect_timeout": "PGCONNECT_TIMEOUT"}
PSQL_TIMEOUT = 300

# Same role definition and collision test as dev/gis_worker/identity_probe.sql.
# No migration creates this role, 031 revokes from it and 032 requires it.
NATIVE_WORKER_SQL = """
BEGIN;
SET LOCAL lock_timeout='{lock_timeout}';
DO $role$
DECLARE r record;
BEGIN
 SELECT * INTO r FROM pg_roles WHERE rolname='gis_native_worker';
 IF FOUND THEN
  IF r.rolsuper OR r.rolbypassrls OR r.rolcanlogin OR r.rolcreatedb OR r.rolcreaterole
   OR r.rolreplication OR r.rolinherit
   OR shobj_description(r.oid,'pg_authid') IS DISTINCT FROM 'gis-t3-native-worker-v1'
   OR EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles a ON a.oid=m.member
      WHERE (m.roleid=r.oid AND a.rolname NOT IN ('postgres','authenticator')) OR m.member=r.oid) THEN
   RAISE EXCEPTION 'GIS_NATIVE_WORKER_ROLE_COLLISION'; END IF;
 ELSE
  CREATE ROLE gis_native_worker NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB
    NOCREATEROLE NOREPLICATION NOINHERIT;
  COMMENT ON ROLE gis_native_worker IS 'gis-t3-native-worker-v1';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_auth_members
    WHERE roleid='gis_native_worker'::regrole AND member='authenticator'::regrole) THEN
  GRANT gis_native_worker TO authenticator WITH INHERIT FALSE, SET TRUE;
 END IF;
END $role$;
COMMIT;
"""


class InstallError(Exception):
    """Printed as is. Must never carry a connection string or a password."""


def log(message: str) -> None:
    print(message, flush=True)


class Target:
    """The parsed connection, handed to psql only through PG* environment variables."""

    def __init__(self, url: str, psql: list[str]):
        # urllib's own errors can quote the URL, so none of them are passed on.
        try:
            parts = urlsplit(url)
            host, port = parts.hostname, parts.port or 5432
            user, password = parts.username, parts.password
        except ValueError:
            raise InstallError("GIS_INSTALL_DATABASE_URL is not a valid URL") from None
        if parts.scheme not in ("postgresql", "postgres") or not host or "," in parts.netloc:
            raise InstallError("GIS_INSTALL_DATABASE_URL must be postgresql://user:password@host:port/database "
                               "with a single host")
        if not user:
            raise InstallError("GIS_INSTALL_DATABASE_URL must name a user")
        self.host, self.port = host, port
        self.database = unquote(parts.path.lstrip("/"))
        self.user = unquote(user)
        self.secrets = [s for s in (url, parts.netloc, password, unquote(password or ""),
                                    quote(unquote(password or ""), safe="")) if s]
        self.psql = psql
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith("PG") and k != "GIS_INSTALL_DATABASE_URL"}
        self.env.update(PGHOST=host, PGPORT=str(port), PGUSER=self.user, PGDATABASE=self.database)
        if password is not None:
            self.env["PGPASSWORD"] = unquote(password)
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if key not in URL_OPTIONS:
                raise InstallError(f"unsupported connection option {key!r}: "
                                   f"only {', '.join(sorted(URL_OPTIONS))} are accepted")
            self.env[URL_OPTIONS[key]] = value

    def scrub(self, text: str) -> str:
        for secret in sorted(self.secrets, key=len, reverse=True):
            text = text.replace(secret, "***")
        return text

    def run(self, sql: str, *, stage: str) -> str:
        """Run SQL from stdin. ON_ERROR_STOP ends the session, which rolls back an open transaction."""
        args = self.psql + ["-X", "-w", "-qAt", "-v", "ON_ERROR_STOP=1"]
        try:
            result = subprocess.run(args, input=sql, text=True, encoding="utf-8", capture_output=True,
                                    env=self.env, timeout=PSQL_TIMEOUT)
        except FileNotFoundError:
            raise InstallError("psql was not found: install a PostgreSQL client "
                               "or set GIS_INSTALL_PSQL") from None
        except subprocess.TimeoutExpired:
            raise InstallError(f"{stage}: psql timed out after {PSQL_TIMEOUT}s") from None
        if result.returncode:
            detail = self.scrub(result.stderr.strip()[-2000:]) or "(no error output)"
            raise InstallError(f"{stage}: psql exited {result.returncode}\n{detail}")
        # A statement that had no effect is only a warning, and for a REVOKE that matters.
        for line in result.stderr.splitlines():
            if line.startswith("WARNING:"):
                log(f"warning   {stage}: {self.scrub(line)}")
        return result.stdout.strip()


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def require_env(name: str, pattern: str | None = None, shape: str = "") -> str:
    value = os.environ.get(name, "")
    if not value:
        raise InstallError(f"{name} is not set")
    if pattern and not re.fullmatch(pattern, value):
        raise InstallError(f"{name} must be {shape}")
    return value


def migration_files(directory: Path, versions=VERSIONS) -> dict[int, tuple[Path, bytes, str]]:
    """Exactly one file per version. Bytes are read once, so what is hashed is what runs."""
    found = {}
    for version in versions:
        matches = sorted(directory.glob(f"{version:03d}_*.sql"))
        if len(matches) != 1:
            raise InstallError(f"expected one file for migration {version:03d} in {directory}, "
                               f"found {len(matches)}")
        data = matches[0].read_bytes()
        found[version] = (matches[0], data, hashlib.sha256(data).hexdigest())
    return found


def preflight(target: Target) -> None:
    """Report what is missing before anything is written."""
    checks = " UNION ALL ".join(
        [f"SELECT {sql_literal('table ' + t)} WHERE to_regclass({sql_literal(t)}) IS NULL" for t in REQUIRED_TABLES]
        + [f"SELECT {sql_literal('role ' + r)} WHERE NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname={sql_literal(r)})"
           for r in REQUIRED_ROLES]
        + ["SELECT 'function auth.uid()' WHERE to_regprocedure('auth.uid()') IS NULL",
           "SELECT 'PostgreSQL 17 or newer' WHERE current_setting('server_version_num')::int < 170000",
           "SELECT 'connecting as the postgres role' WHERE current_user<>'postgres'"])
    missing = target.run(checks + ";", stage="preflight").splitlines()
    if missing:
        raise InstallError("the database is not ready, missing: " + "; ".join(missing))
    # Read-only diagnostics. Neither stops the run, but each predicts a later failure.
    warnings = target.run(
        "SELECT 'postgres is not in pg_read_all_data: 027 line 67 revokes on schema gis before it "
        "assumes gis_owner and a non-superuser gets permission denied without it'"
        " WHERE NOT pg_has_role(current_user,'pg_read_all_data','MEMBER')"
        " UNION ALL SELECT 'postgres cannot SET ROLE service_role: gis_readiness() is only "
        "executable by service_role, so the final check will fail'"
        " WHERE to_regrole('service_role') IS NOT NULL AND NOT pg_has_role(current_user,'service_role','SET');",
        stage="preflight warnings").splitlines()
    for line in warnings:
        log(f"warning   preflight: {line}")


def read_state(target: Target, instance: str, fingerprint: str, cluster: str) -> dict[int, str]:
    """Return the ledger, or {} if GIS was never installed. Stops on anything unidentified."""
    exists = target.run(
        "SELECT to_regnamespace('gis') IS NOT NULL,"
        " EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace"
        "  WHERE n.nspname='gis' AND c.relname='schema_migrations');", stage="read ledger")
    if exists == "f|f":
        return {}
    if exists != "t|t":
        raise InstallError("schema gis exists without gis.schema_migrations: refusing to touch it")
    stored = target.run(
        "BEGIN; SET LOCAL ROLE gis_owner;"
        " SELECT runtime_instance||'|'||baseline_fingerprint||'|'||cluster_name||'|'||mode"
        "  FROM gis.environment WHERE singleton;"
        " SELECT version||'|'||sha256 FROM gis.schema_migrations ORDER BY version;"
        " ROLLBACK;", stage="read ledger").splitlines()
    declared = "|".join((instance, fingerprint, cluster, MODE))
    if not stored or stored[0] != declared:
        raise InstallError("this database was installed with a different identity: GIS_RUNTIME_INSTANCE, "
                           "GIS_BASELINE_FINGERPRINT and GIS_CLUSTER_NAME must match gis.environment")
    ledger = {}
    for row in stored[1:]:
        version, checksum = row.split("|")
        ledger[int(version)] = checksum
    return ledger


def check_ledger(ledger: dict[int, str], files: dict, versions=VERSIONS) -> list[int]:
    """Validate everything already recorded, then return the versions still to apply."""
    for version in versions:
        if version in ledger and ledger[version] != files[version][2]:
            raise InstallError(f"migration {version:03d} checksum drift: ledger has {ledger[version]}, "
                               f"file is {files[version][2]}")
    pending = [v for v in versions if v not in ledger]
    for version in pending:
        later = [v for v in versions if v > version and v in ledger]
        if later:
            raise InstallError(f"ledger gap: {version:03d} is missing but {later[0]:03d} is recorded")
    return pending


def apply_migration(target: Target, version: int, path: Path, data: bytes, checksum: str,
                    instance: str, fingerprint: str, cluster: str,
                    lock_timeout: str, statement_timeout: str) -> None:
    sql = "\n".join((
        "BEGIN;",
        f"SET LOCAL lock_timeout='{lock_timeout}';",
        f"SET LOCAL statement_timeout='{statement_timeout}';",
        f"SELECT set_config('gis.runtime_instance',{sql_literal(instance)},true);",
        f"SELECT set_config('gis.baseline_fingerprint',{sql_literal(fingerprint)},true);",
        f"SELECT set_config('gis.cluster_name',{sql_literal(cluster)},true);",
        f"SELECT set_config('gis.mode',{sql_literal(MODE)},true);",
        data.decode("utf-8-sig"),
        "SET LOCAL ROLE gis_owner;",
        f"INSERT INTO gis.schema_migrations(version,sha256) VALUES ({version},{sql_literal(checksum)});",
        "RESET ROLE;",
        "COMMIT;",
        "",
    ))
    try:
        target.run(sql, stage=f"migration {path.name}")
    except InstallError as error:
        raise InstallError(f"{error}\nThis migration was rolled back and not recorded. "
                           "Earlier migrations stay applied; a re-run resumes here.") from None


def readiness(target: Target, instance: str, fingerprint: str, cluster: str, versions=VERSIONS) -> dict:
    """gis_readiness() is executable only by service_role, as PostgREST calls it."""
    raw = target.run("BEGIN; SET LOCAL ROLE service_role; SELECT public.gis_readiness(); ROLLBACK;",
                     stage="gis_readiness()")
    value = json.loads(raw)
    expected = {"cluster_name": cluster, "mode": MODE, "runtime_instance": instance,
                "baseline_fingerprint": fingerprint}
    wrong = [k for k, v in expected.items() if value.get(k) != v]
    if wrong:
        raise InstallError("gis_readiness() disagrees with the declaration on: " + ", ".join(wrong))
    absent = [v for v in versions if v not in value.get("migration_versions", [])]
    if absent:
        raise InstallError(f"gis_readiness() does not list migrations: {absent}")
    return value


class AdvisoryLock:
    """Holds pg_try_advisory_lock on one open psql session until released."""

    def __init__(self, target: Target):
        args = target.psql + ["-X", "-w", "-qAt", "-v", "ON_ERROR_STOP=1"]
        try:
            self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, env=target.env, text=True, encoding="utf-8")
        except FileNotFoundError:
            raise InstallError("psql was not found: install a PostgreSQL client "
                               "or set GIS_INSTALL_PSQL") from None
        try:
            self.proc.stdin.write(f"SELECT pg_try_advisory_lock({LOCK_ID});\n")
            self.proc.stdin.flush()
            answer = self.proc.stdout.readline().strip()
        except OSError:
            answer = ""
        if answer != "t":
            self.release()
            raise InstallError("could not take the installer lock: " + (
                "another installer run is using this database" if answer == "f"
                else "the lock session failed to start"))

    def release(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()


def is_hosted(host: str) -> bool:
    return host.lower().rstrip(".").endswith(HOSTED_SUFFIXES)


def is_local(host: str) -> bool:
    return host.lower() in LOCAL_HOSTS or host.startswith("/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Install GIS migrations 027-052 on an external database.",
                                     epilog="Configuration comes from the environment: see the module docstring.")
    parser.add_argument("--readiness-out", type=Path, help="write the gis_readiness() result to this file")
    parser.add_argument("--allow-remote-host", action="store_true",
                        default=os.environ.get("GIS_INSTALL_ALLOW_REMOTE_HOST") == "1",
                        help="permit a host other than localhost/127.0.0.1/::1; "
                             "*.supabase.co and *.supabase.com stay refused")
    parser.add_argument("--lock-timeout", default=os.environ.get("GIS_INSTALL_LOCK_TIMEOUT", "5s"),
                        help="lock_timeout for each migration transaction (default 5s)")
    parser.add_argument("--statement-timeout", default=os.environ.get("GIS_INSTALL_STATEMENT_TIMEOUT", "120s"),
                        help="statement_timeout for each migration transaction (default 120s)")
    parser.add_argument("--up-to", type=int, default=LAST, metavar="N",
                        help=f"install only through migration N ({FIRST}-{LAST}, default {LAST}); "
                             "for testing an upgrade")
    parser.add_argument("--migrations-dir", type=Path, default=DEFAULT_MIGRATIONS,
                        help="directory holding the migration files (default: the repository's)")
    args = parser.parse_args()

    url = require_env("GIS_INSTALL_DATABASE_URL")
    instance = require_env("GIS_RUNTIME_INSTANCE", r"[0-9a-f]{32}", "32 lowercase hex characters")
    fingerprint = require_env("GIS_BASELINE_FINGERPRINT", r"[0-9a-f]{64}", "64 lowercase hex characters")
    cluster = require_env("GIS_CLUSTER_NAME", r"[a-z]{20}", "exactly 20 lowercase letters")
    psql = shlex.split(os.environ.get("GIS_INSTALL_PSQL") or "psql")

    target = Target(url, psql)
    if target.database not in DATABASES:
        raise InstallError(f"the database must be named one of {sorted(DATABASES)}: migration 027 refuses others")
    if is_hosted(target.host):
        raise InstallError(f"refusing {target.host}: a hosted Supabase database is never accepted by this installer")
    if not is_local(target.host) and not args.allow_remote_host:
        raise InstallError(f"refusing non-local host {target.host}: only localhost, 127.0.0.1 and ::1 are "
                           "accepted unless --allow-remote-host (or GIS_INSTALL_ALLOW_REMOTE_HOST=1) is given")
    for name, value in (("--lock-timeout", args.lock_timeout), ("--statement-timeout", args.statement_timeout)):
        if not re.fullmatch(TIMEOUT_RE, value):
            raise InstallError(f"{name} must look like 500ms, 5s or 2min")
    if not FIRST <= args.up_to <= LAST:
        raise InstallError(f"--up-to must be between {FIRST} and {LAST}")
    last = args.up_to
    versions = range(FIRST, last + 1)

    log(f"target    {target.host}:{target.port}/{target.database} as {target.user}")
    log(f"declared  cluster_name={cluster} mode={MODE}")
    files = migration_files(args.migrations_dir, versions)
    preflight(target)
    lock = AdvisoryLock(target)
    try:
        ledger = read_state(target, instance, fingerprint, cluster)
        pending = check_ledger(ledger, files, versions)
        beyond = sorted(v for v in ledger if v > last)
        if beyond:
            log(f"note      versions above {last:03d} are recorded and left alone: {beyond}")

        # Nothing is written before the ledger has been accepted.
        target.run(NATIVE_WORKER_SQL.replace("{lock_timeout}", args.lock_timeout), stage="role gis_native_worker")
        log("role      gis_native_worker ready")

        applied = 0
        for version in versions:
            path, data, checksum = files[version]
            if version in ledger:
                log(f"skip      {path.name} already applied, sha256 verified")
                continue
            apply_migration(target, version, path, data, checksum, instance, fingerprint, cluster,
                            args.lock_timeout, args.statement_timeout)
            applied += 1
            log(f"applied   {path.name} sha256={checksum}")

        value = readiness(target, instance, fingerprint, cluster, versions)
    finally:
        lock.release()
    if args.readiness_out:
        args.readiness_out.parent.mkdir(parents=True, exist_ok=True)
        args.readiness_out.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        log(f"evidence  gis_readiness() written to {args.readiness_out}")
    log(f"readiness cluster_name={value['cluster_name']} mode={value['mode']} "
        f"migrations={value['migration_versions']}")
    log(f"done      installed through {last:03d}: applied {applied}, skipped {len(versions) - applied}")


if __name__ == "__main__":
    try:
        main()
    except InstallError as error:
        print(f"FAILED    {error}", file=sys.stderr, flush=True)
        sys.exit(1)
