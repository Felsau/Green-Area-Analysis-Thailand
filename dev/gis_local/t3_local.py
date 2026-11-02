"""T3 local runner: Migration 031 execution and local testing runner."""
from __future__ import annotations
import argparse
import importlib.util
import json
import logging
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location("t3_local_t2", HERE / "t2_local.py")
t2 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = t2
spec.loader.exec_module(t2)
t1 = t2.t1
BACKEND = REPO / "green-area-backend"


class LocalT3(t2.LocalT2):
    def __init__(self, root: Path):
        super().__init__(root)
        self.directory = self.db.runtime.root / "t3"
        self.directory.mkdir(exist_ok=True)

    def migrate_031(self, review_path: Path):
        self.attest()
        path = REPO / "green-area-backend/migrations/031_gis_native_v2.sql"
        content = path.read_bytes()
        checksum = t1.sha(content)
        review = json.loads(review_path.read_text(encoding="utf-8"))
        if (review.get("independent_review") is not True or review.get("unresolved_high_critical") != 0
                or review.get("files") != {path.name: checksum}):
            raise t1.SafetyError("T3_CHECKSUM_BOUND_REVIEW_REQUIRED")
        for database in ("postgres", "gis_t1_upgrade"):
            self.db.proof(database, stage="gis")
            old = self.db.transport(database, "BEGIN;SET LOCAL ROLE gis_owner;SELECT sha256 FROM gis.schema_migrations WHERE version=31;ROLLBACK;").stdout.strip()
            if old:
                if old == checksum:
                    continue
                raise t1.SafetyError("T3_APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED")
            sql = ("BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='60s';\n"
                + "SELECT set_config('gis.runtime_instance'," + t1.literal(self.db.instance) + ",true);\n"
                + "SELECT set_config('gis.baseline_fingerprint'," + t1.literal(t1.legacy_fingerprint()) + ",true);\n"
                + content.decode("utf-8-sig") + "\nSET LOCAL ROLE gis_owner;INSERT INTO gis.schema_migrations(version,sha256) VALUES(31,"
                + t1.literal(checksum) + ");RESET ROLE;COMMIT;")
            self.db.transport(database, sql)
        result = {"version": 31, "sha256": checksum, "databases": ["postgres", "gis_t1_upgrade"], "local_only": True}
        self.write("migration-031.json", result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("migrate", "proof", "resume", "stop"))
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    args = parser.parse_args()
    for name in ("httpx", "httpcore", "supabase_auth", "postgrest"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    local = LocalT3(args.runtime_dir)
    if args.action == "migrate":
        if args.review is None:
            raise t1.SafetyError("T3_REVIEW_REQUIRED")
        result = local.migrate_031(args.review)
    elif args.action == "proof":
        result = local.attest()
    elif args.action == "resume":
        result = local.db.resume()
    elif args.action == "stop":
        result = local.db.runtime.stop()
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "code": "T3_LOCAL_OPERATION_FAILED", "error": str(exc)}))
        sys.exit(1)
