"""Operator for migration 050 (LDD report audit) on the local T0.

  probe    050 + rolled-back lifecycle on both local databases; the ledger stays at 49.
  migrate  050 for real, only after a matching probe and an approval file you write.
  proof    read-only ledger and gate check.

Uses the attested local operator from gee_dashboard_local for runtime proof and SQL
transport. Nothing here reaches Google or Cloud. Output: <runtime root>/upload-050/.
"""
import argparse
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('upload_050_dashboard', HERE / 'gee_dashboard_local.py')
d = importlib.util.module_from_spec(spec); sys.modules[spec.name] = d; spec.loader.exec_module(d)
MIGRATION = d.REPO / 'green-area-backend/migrations/050_gis_ldd_report_audit.sql'
LIFECYCLE = HERE / 'upload_050_lifecycle.sql'
APPROVAL = 'local_apply_050_after_rollback_probe'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AuditLocal(d.DashboardLocal):
    def __init__(self, root):
        super().__init__(root)
        self.output = self.db.runtime.root / 'upload-050'
        self.output.mkdir(exist_ok=True)

    def run_050(self, *, probe):
        self.proof(allow=(49,) if probe else (49, 50))
        sha = digest(MIGRATION)
        q = d._t1().literal
        prior = {db: self.sql('SELECT to_jsonb(sha256) FROM gis.schema_migrations WHERE version=50', db, read_only=True)
            for db in d.DATABASES}
        if any(old is not None and old != sha for old in prior.values()):
            raise RuntimeError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')
        results = {}
        for db, old in prior.items():
            if old is not None:
                results[db] = 'already_applied'
                continue
            self.db.proof(db, stage='gis')
            body = "BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='60s';"
            body += "SELECT set_config('gis.runtime_instance'," + q(self.db.instance) + ",true);"
            body += "SELECT set_config('gis.baseline_fingerprint'," + q(d._t1().legacy_fingerprint()) + ",true);"
            body += MIGRATION.read_text(encoding='utf-8')
            body += "\nSET LOCAL ROLE gis_owner;INSERT INTO gis.schema_migrations(version,sha256) VALUES(50," + q(sha) + ");RESET ROLE;"
            if probe:
                body += self._prelude(db) + LIFECYCLE.read_text(encoding='utf-8') + "\nSET CONSTRAINTS ALL IMMEDIATE;ROLLBACK;"
            else:
                body += "COMMIT;"
            self.db.transport(db, body)
            results[db] = 'rolled_back_lifecycle' if probe else 'applied'
        record = {'sha256': sha, 'lifecycle_sha256': digest(LIFECYCLE), 'runtime_instance': self.db.instance, 'databases': results}
        (self.output / ('probe.json' if probe else 'migration-050.json')).write_text(json.dumps(record, indent=2), encoding='utf-8')
        return record

    def migrate_050(self, approval):
        sha = digest(MIGRATION)
        value = json.loads(Path(approval).read_text(encoding='utf-8'))
        if value != {'approval': APPROVAL, 'migration_sha256': sha}:
            raise RuntimeError('MIGRATION_050_APPROVAL_REQUIRED')
        probe = json.loads((self.output / 'probe.json').read_text(encoding='utf-8'))
        if (probe.get('sha256') != sha or probe.get('lifecycle_sha256') != digest(LIFECYCLE)
                or probe.get('runtime_instance') != self.db.instance
                or probe.get('databases') != {db: 'rolled_back_lifecycle' for db in d.DATABASES}):
            raise RuntimeError('MIGRATION_050_PROBE_REQUIRED')
        return self.run_050(probe=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('proof', 'probe', 'migrate'))
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--approval', type=Path)
    args = parser.parse_args()
    for name in ('httpx', 'httpcore', 'postgrest', 'supabase_auth', 'gotrue'):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    local = AuditLocal(args.runtime_dir)
    if args.action == 'proof':
        value = local.proof(allow=(49, 50))
    elif args.action == 'probe':
        value = local.run_050(probe=True)
    else:
        value = local.migrate_050(args.approval)
    print(json.dumps(value))
