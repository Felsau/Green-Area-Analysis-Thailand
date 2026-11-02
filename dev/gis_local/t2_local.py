"""T2 local runner: exact T0 ownership, forward-only SQL, in-memory local keys.

No legacy app import or dotenv/credential-file load. Use backend .venv Python.
Local generated development keys are extracted only after live target proof and
never printed/written. Production settings and a database URL are not accepted.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import logging
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location("t2_database_t1", HERE / "t1_database.py")
t1 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = t1
spec.loader.exec_module(t1)
BACKEND = REPO / "green-area-backend"


class LocalT2:
    def __init__(self, root: Path):
        self.db = t1.LocalDatabase(root)
        self.directory = self.db.runtime.root / "t2"
        self.directory.mkdir(exist_ok=True)

    def attest(self):
        items = self.db.runtime.verify_containers()
        if any(item["status"] != "running" or item["health"] != "healthy" for item in items.values()):
            raise t1.SafetyError("T2_ALL_LOCAL_CONTAINERS_MUST_BE_HEALTHY")
        proof = self.db.proof("postgres", stage="gis")
        return {**proof, "baseline_fingerprint": t1.legacy_fingerprint(), "containers_healthy": True}

    def migrate(self, review_path: Path):
        self.attest()
        path = REPO / "green-area-backend/migrations/030_gis_api_reads.sql"
        content = path.read_bytes()
        checksum = t1.sha(content)
        review = json.loads(review_path.read_text(encoding="utf-8"))
        if (review.get("independent_review") is not True or review.get("unresolved_high_critical") != 0
                or review.get("files") != {path.name: checksum}):
            raise t1.SafetyError("T2_CHECKSUM_BOUND_REVIEW_REQUIRED")
        for database in ("postgres", "gis_t1_upgrade"):
            self.db.proof(database, stage="gis")
            old = self.db.transport(database, "BEGIN;SET LOCAL ROLE gis_owner;SELECT sha256 FROM gis.schema_migrations WHERE version=30;ROLLBACK;").stdout.strip()
            if old:
                if old != checksum:
                    raise t1.SafetyError("T2_APPLIED_CHECKSUM_DRIFT")
                continue
            sql = ("BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='60s';\n"
                + "SELECT set_config('gis.runtime_instance'," + t1.literal(self.db.instance) + ",true);\n"
                + "SELECT set_config('gis.baseline_fingerprint'," + t1.literal(t1.legacy_fingerprint()) + ",true);\n"
                + content.decode("utf-8-sig") + "\nSET LOCAL ROLE gis_owner;INSERT INTO gis.schema_migrations(version,sha256) VALUES(30,"
                + t1.literal(checksum) + ");RESET ROLE;COMMIT;")
            self.db.transport(database, sql)
        result = {"version": 30, "sha256": checksum, "databases": ["postgres", "gis_t1_upgrade"], "local_only": True}
        self.write("migration-030.json", result)
        return result

    def write(self, name, value):
        (self.directory / name).write_text(json.dumps(value, indent=2, ensure_ascii=False)+"\n", encoding="utf-8", newline="\n")

    def local_keys(self):
        self.attest()
        item = self.db.runtime.metadata("gateway")
        # Read only this verified container's generated T0 config, never a host
        # .env/home/credential file. Data remains inside this Python process.
        raw = self.db.runtime.docker(["exec", item["id"], "cat", "/home/kong/kong.yml"])
        keys = re.findall(r'^\s+- key: ("[^"\r\n]+")\s*$', raw, re.MULTILINE)
        if len(keys) != 2:
            raise t1.SafetyError("T2_LOCAL_KEYS_UNAVAILABLE")
        return tuple(json.loads(value) for value in keys)

    def client(self, key):
        self.attest()
        from supabase import create_client, ClientOptions
        import httpx
        transport = httpx.Client(trust_env=False, follow_redirects=False, timeout=5)
        return create_client("http://127.0.0.1:55421", key,
            ClientOptions(auto_refresh_token=False, persist_session=False,
                httpx_client=transport, postgrest_client_timeout=5))

    def runtime(self, *, activation=False):
        self.attest()
        if str(BACKEND) not in sys.path:
            sys.path.insert(0, str(BACKEND))
        from gis_runtime import GISRuntime, LocalGISSettings
        anon, service = self.local_keys()
        return GISRuntime(LocalGISSettings(enabled=True, runtime_instance=self.db.instance,
            baseline_fingerprint=t1.legacy_fingerprint(), sandbox_activation_enabled=activation),
            attest=self.attest, clients=lambda url: (self.client(anon), self.client(service)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("resume", "stop", "proof", "migrate", "serve"))
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    args = parser.parse_args()
    for name in ("httpx", "httpcore", "supabase_auth", "postgrest"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    local = LocalT2(args.runtime_dir)
    if args.action == "resume":
        result = local.db.resume()
    elif args.action == "stop":
        result = local.db.runtime.stop()
    elif args.action == "migrate":
        if args.review is None:
            raise t1.SafetyError("T2_REVIEW_REQUIRED")
        result = local.migrate(args.review)
    elif args.action == "serve":
        runtime = local.runtime()
        runtime.require_ready()
        from gis_app import create_app
        import uvicorn
        uvicorn.run(create_app(runtime), host="127.0.0.1", port=55422, access_log=False)
        return
    else:
        result = local.attest()
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Deliberately no exception string/traceback: SDK errors can include data.
        print(json.dumps({"ok": False, "code": "T2_LOCAL_OPERATION_FAILED"}))
        sys.exit(1)
