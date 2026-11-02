"""T1 local-only database harness. Never imports app config or reads credentials.

Transport is docker exec into the exact T0-owned container, not a host/DSN.
Original migrations run once on a proven empty application baseline only.
New migrations require a checksum-bound independent review record.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MIGRATIONS = REPO / "green-area-backend/migrations"
spec = importlib.util.spec_from_file_location("gis_t1_t0_runtime", HERE / "manage.py")
runtime_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime_module
spec.loader.exec_module(runtime_module)
SafetyError = runtime_module.guard.SafetyError
DATABASES = frozenset({"postgres", "gis_t1_upgrade"})


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sources(start=0, end=26) -> list[Path]:
    result = []
    for number in range(start, end + 1):
        matches = list(MIGRATIONS.glob(f"{number:03}_*.sql"))
        if len(matches) != 1:
            raise SafetyError("MIGRATION_SEQUENCE_REJECTED")
        result.append(matches[0])
    return result


def legacy_fingerprint() -> str:
    return sha(b"".join(path.read_bytes() for path in sources()))


def atomic_body(sql: str) -> str:
    # Historical outer transactions only. Bare BEGIN inside DO/PLpgsql is retained.
    return re.sub(r"(?m)^(?:BEGIN;|COMMIT;)\s*$", "", sql)


class LocalDatabase:
    def __init__(self, runtime_dir: Path):
        self.runtime = runtime_module.LocalRuntime(runtime_dir)
        self.instance = self.runtime.owner()["instance"]
        self.evidence_dir = self.runtime.root / "t1"
        self.container = ""

    def transport(self, database: str, sql: str, *, check=True, timeout=90):
        if database not in DATABASES or not re.fullmatch(r"[0-9a-f]{64}", self.container):
            raise SafetyError("DATABASE_TRANSPORT_NOT_PROVED")
        args = self.runtime.base + ["exec", "-i", self.container, "psql", "-X", "-qAt",
            "-U", "postgres", "-d", database, "-v", "ON_ERROR_STOP=1", "-v", "VERBOSITY=verbose"]
        result = subprocess.run(args, input=sql, text=True, encoding="utf-8",
            capture_output=True, timeout=timeout, cwd=self.runtime.root, env=self.runtime.env)
        if check and result.returncode:
            # Inputs are repository SQL/synthetic values only. No env or credentials.
            raise SafetyError("LOCAL_SQL_FAILED: " + result.stderr[-2500:])
        return result

    def proof(self, database="postgres", *, stage="any") -> dict:
        if database not in DATABASES:
            raise SafetyError("DATABASE_NOT_ALLOWLISTED")
        containers = self.runtime.verify_containers()
        if containers["db"]["status"] != "running" or containers["db"]["health"] != "healthy":
            raise SafetyError("DATABASE_NOT_HEALTHY")
        self.container = containers["db"]["id"]
        value = self.transport(database, """
SELECT jsonb_build_object('database',current_database(),'cluster',current_setting('cluster_name'),
 'version',current_setting('server_version_num')::int,'migrator',current_user,
 'create_database',r.rolcreatedb,'create_role',r.rolcreaterole,
 'auth',to_regclass('auth.users') IS NOT NULL,'uid',to_regprocedure('auth.uid()') IS NOT NULL,
 'gis',to_regnamespace('gis') IS NOT NULL,
 'application_tables',(SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='public' AND c.relkind IN ('r','p')),
 'auth_users',(SELECT count(*) FROM auth.users),
 'legacy_functions',to_regprocedure('public.handle_new_user()') IS NOT NULL
   OR to_regprocedure('public.set_profiles_updated_at()') IS NOT NULL,
 'legacy_auth_trigger',EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='auth.users'::regclass
   AND tgname='on_auth_user_created')) FROM pg_roles r WHERE r.rolname=current_user;
""").stdout.strip()
        proof = json.loads(value)
        if (proof["database"] != database or proof["cluster"] != "green-area-gis-t0"
                or proof["version"] < 150000 or not proof["auth"] or not proof["uid"]
                or proof["migrator"] != "postgres" or not proof["create_database"]
                or not proof["create_role"]):
            raise SafetyError("LOCAL_DATABASE_IDENTITY_REJECTED")
        if stage == "empty" and (proof["application_tables"] or proof["gis"] or proof["auth_users"]
                or proof["legacy_functions"] or proof["legacy_auth_trigger"]):
            raise SafetyError("EMPTY_BASELINE_REQUIRED_NO_LEGACY_REPLAY")
        if stage in {"baseline", "gis"}:
            marker = self.evidence_dir / f"{database}-baseline.json"
            if not marker.is_file():
                raise SafetyError("LOCAL_BASELINE_CHECKPOINT_REQUIRED")
            data = json.loads(marker.read_text(encoding="utf-8"))
            if (data.get("instance") != self.instance or data.get("container") != self.container
                    or data.get("fingerprint") != legacy_fingerprint() or data.get("completed") is not True):
                raise SafetyError("BASELINE_CHECKPOINT_REJECTED")
        if stage == "gis":
            if not proof["gis"]:
                raise SafetyError("GIS_SCHEMA_REQUIRED")
            env = json.loads(self.transport(database, "BEGIN; SET LOCAL ROLE gis_owner; SELECT row_to_json(e) FROM gis.environment e; ROLLBACK;").stdout)
            if (env.get("runtime_instance") != self.instance or env.get("database_name") != database
                    or env.get("cluster_name") != proof["cluster"] or env.get("mode") != "local_synthetic"
                    or env.get("baseline_fingerprint") != legacy_fingerprint()):
                raise SafetyError("GIS_DATABASE_MARKER_REJECTED")
        return {**proof, "instance": self.instance, "container": self.container, "stage": stage}

    def query(self, database: str, sql: str, *, stage="gis", check=True, timeout=90):
        self.proof(database, stage=stage)
        return self.transport(database, sql, check=check, timeout=timeout)

    def write_json(self, name: str, data: object):
        self.evidence_dir.mkdir(exist_ok=True)
        path = self.evidence_dir / name
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def resume(self):
        # T0 start's final check intentionally rejects application schemas. Resume
        # existing owned containers without Compose/env-file loading instead.
        items = self.runtime.verify_containers()
        self.runtime.docker(["start", items["db"]["id"]], quiet=True)
        self.runtime.wait_healthy("db")
        for service in ("auth", "rest", "gateway"):
            self.runtime.docker(["start", items[service]["id"]], quiet=True)
            self.runtime.wait_healthy(service)
        return self.proof("postgres", stage="gis")

    def clone_empty(self):
        self.proof("postgres", stage="empty")
        exists = self.transport("postgres", "SELECT count(*) FROM pg_database WHERE datname='gis_t1_upgrade';").stdout.strip()
        if exists != "0":
            raise SafetyError("UPGRADE_DATABASE_ALREADY_EXISTS_NO_OVERWRITE")
        self.transport("postgres", "CREATE DATABASE gis_t1_upgrade TEMPLATE template0;")
        self.transport("gis_t1_upgrade", "COMMENT ON DATABASE gis_t1_upgrade IS " + literal("gis-t1:" + self.instance) + ";")
        return self.restore_empty()

    def restore_empty(self):
        # Explicit recovery of ONLY an owned, entirely uninitialised test DB.
        self.proof("postgres", stage="empty")
        target = json.loads(self.transport("gis_t1_upgrade", """
SELECT jsonb_build_object('database',current_database(),'cluster',current_setting('cluster_name'),
 'comment',(SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()),
 'auth',to_regnamespace('auth') IS NOT NULL,'gis',to_regnamespace('gis') IS NOT NULL,
 'tables',(SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public' AND c.relkind IN ('r','p')));
""").stdout)
        if (target["database"] != "gis_t1_upgrade" or target["cluster"] != "green-area-gis-t0"
                or target["comment"] != "gis-t1:" + self.instance
                or target["auth"] or target["gis"] or target["tables"]):
            raise SafetyError("VENDOR_RESTORE_REQUIRES_OWNED_EMPTY_TARGET")
        # Supabase pg_cron/pg_net hold template DB sessions. Do not terminate them.
        # Copy only credential-free vendor Auth schema definitions, no rows.
        # template0 already supplies public; there are no source public app objects.
        dump = subprocess.run(self.runtime.base + ["exec", self.container, "pg_dump", "-U", "postgres",
            "-d", "postgres", "--schema-only", "--schema=auth", "--no-owner", "--no-acl"],
            env=self.runtime.env, cwd=self.runtime.root, text=True, encoding="utf-8", capture_output=True, timeout=60)
        if dump.returncode:
            raise SafetyError("LOCAL_VENDOR_SCHEMA_DUMP_FAILED")
        self.proof("postgres", stage="empty")
        self.transport("gis_t1_upgrade", "BEGIN;\n" + dump.stdout
            + "\nGRANT USAGE ON SCHEMA auth TO anon,authenticated,service_role;"
            + "\nGRANT EXECUTE ON FUNCTION auth.uid(),auth.role(),auth.jwt() TO anon,authenticated,service_role;\nCOMMIT;")
        return self.proof("gis_t1_upgrade", stage="empty")

    def baseline(self, database: str):
        proof = self.proof(database, stage="empty")
        path = self.evidence_dir / f"{database}-baseline.json"
        if path.exists():
            raise SafetyError("BASELINE_CHECKPOINT_EXISTS_NO_REPLAY")
        state = {"instance": self.instance, "container": self.container,
            "fingerprint": legacy_fingerprint(), "completed": False, "applied": [], "proof": proof}
        # Local clone must retain its independently verified ownership comment.
        if database != "postgres":
            comment = self.transport(database, "SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database();").stdout.strip()
            if comment != "gis-t1:" + self.instance:
                raise SafetyError("UPGRADE_DATABASE_OWNER_MARKER_REJECTED")
        self.write_json(path.name, state)
        # Whole baseline is atomic. No partial resume/destructive replay on failure.
        body = "\n".join(atomic_body(p.read_text(encoding="utf-8-sig")) for p in sources())
        self.proof(database, stage="empty")
        self.transport(database, "BEGIN; SET LOCAL lock_timeout='5s'; SET LOCAL statement_timeout='60s';\n" + body + "\nCOMMIT;", timeout=120)
        state["applied"] = [{"version": int(p.name[:3]), "sha256": sha(p.read_bytes())} for p in sources()]
        state["completed"] = True
        self.write_json(path.name, state)
        return self.proof(database, stage="baseline")

    def migrate(self, database: str, review_path: Path):
        self.proof(database, stage="baseline")
        review = json.loads(review_path.read_text(encoding="utf-8"))
        files = sources(27, 29)
        reviewed_bytes = {p.name: p.read_bytes() for p in files}
        expected = {name: sha(data) for name, data in reviewed_bytes.items()}
        if (review.get("independent_review") is not True or review.get("unresolved_high_critical") != 0
                or review.get("files") != expected):
            raise SafetyError("CHECKSUM_BOUND_INDEPENDENT_REVIEW_REQUIRED")
        current = self.proof(database, stage="baseline")
        if current["gis"]:
            self.proof(database, stage="gis")
            if self.transport(database, "BEGIN; SET LOCAL ROLE gis_owner; SELECT to_regclass('gis.schema_migrations') IS NOT NULL; ROLLBACK;").stdout.strip() != "t":
                raise SafetyError("UNIDENTIFIED_EXISTING_GIS_SCHEMA")
        applied = []
        for path in files:
            self.proof(database, stage="baseline")
            version, checksum = int(path.name[:3]), expected[path.name]
            exists = self.transport(database, "SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='gis' AND c.relname='schema_migrations');").stdout.strip() == "t"
            if exists:
                previous = self.transport(database, f"BEGIN; SET LOCAL ROLE gis_owner; SELECT sha256 FROM gis.schema_migrations WHERE version={version}; ROLLBACK;").stdout.strip()
                if previous:
                    if previous != checksum:
                        raise SafetyError("APPLIED_MIGRATION_CHECKSUM_DRIFT")
                    applied.append({"version": version, "status": "already_applied_checksum_verified"})
                    continue
            settings = ("SELECT set_config('gis.runtime_instance'," + literal(self.instance) + ",true);\n"
                "SELECT set_config('gis.baseline_fingerprint'," + literal(legacy_fingerprint()) + ",true);\n")
            sql = ("BEGIN; SET LOCAL lock_timeout='5s'; SET LOCAL statement_timeout='60s';\n" + settings
                + reviewed_bytes[path.name].decode("utf-8-sig") + f"\nSET LOCAL ROLE gis_owner;\nINSERT INTO gis.schema_migrations(version,sha256) VALUES ({version},{literal(checksum)});\nRESET ROLE; COMMIT;")
            self.transport(database, sql)
            applied.append({"version": version, "status": "applied", "sha256": checksum})
        result = {"proof": self.proof(database, stage="gis"), "migrations": applied, "review": review_path.name}
        self.write_json(f"{database}-gis-migrations.json", result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("proof", "resume", "stop", "clone-empty", "restore-empty", "baseline", "migrate"))
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--database", choices=sorted(DATABASES), default="postgres")
    parser.add_argument("--review", type=Path)
    args = parser.parse_args()
    db = LocalDatabase(args.runtime_dir)
    if args.action == "proof":
        result = db.proof(args.database)
    elif args.action == "resume":
        result = db.resume()
    elif args.action == "stop":
        result = db.runtime.stop()
    elif args.action == "clone-empty":
        result = db.clone_empty()
    elif args.action == "restore-empty":
        result = db.restore_empty()
    elif args.action == "baseline":
        result = db.baseline(args.database)
    else:
        if args.review is None:
            raise SafetyError("REVIEW_RECORD_REQUIRED")
        result = db.migrate(args.database, args.review)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (SafetyError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        sys.exit(1)
