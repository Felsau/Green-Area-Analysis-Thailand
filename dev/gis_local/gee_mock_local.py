"""Exact-reviewed A6.2 local operator. No service/Google keys in worker code."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
s = importlib.util.spec_from_file_location('a62_existing_local', HERE.parent / 'gis_worker/remediation_local.py')
m = importlib.util.module_from_spec(s)
sys.modules[s.name] = m
s.loader.exec_module(m)
MIGRATION = REPO / 'green-area-backend/migrations/043_gis_gee_mock_candidates.sql'
DATABASES = ('postgres', 'gis_t1_upgrade')


class GeeMockLocal(m.Local):
    def __init__(self, root):
        super().__init__(root)
        self.output = self.db.runtime.root / 'a6-2-gee-mock'
        self.output.mkdir(exist_ok=True)

    def proof_a62(self):
        self.check_frozen()
        self.attest()
        for db in DATABASES:
            self.db.proof(db, stage='gis')
            value = self.sql("SELECT jsonb_build_object('gate',(SELECT activation_enabled FROM gis.environment),"
                "'ledger',(SELECT jsonb_agg(to_jsonb(t) ORDER BY version) FROM gis.schema_migrations t))", db, read_only=True)
            ledger = value['ledger']
            if value['gate'] is not False or [x['version'] for x in ledger] not in (list(range(27, 43)), list(range(27, 44))):
                raise RuntimeError('A62_LOCAL_CLOSED_GATE_BASELINE_REQUIRED')
            for row in ledger:
                path = next((REPO / 'green-area-backend/migrations').glob(f"{row['version']:03d}_*.sql"))
                if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
                    raise RuntimeError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')
        return {'local_only': True, 'broad_gate_closed': True, 'ledger_source_match': True}

    def reviewed(self, review_path):
        raw = MIGRATION.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        value = json.loads(Path(review_path).read_text(encoding='utf-8'))
        if (value.get('independent_review') is not True or value.get('unresolved_high_critical') != 0
            or value.get('files') != {MIGRATION.name: sha}):
            raise RuntimeError('A62_EXACT_INDEPENDENT_REVIEW_REQUIRED')
        if set(value.get('source_files', {})) != {'green-area-backend/gis_worker/gee_mock_queue.py', 'dev/gis_local/gee_mock_local.py'}:
            raise RuntimeError('A62_EXACT_SOURCE_REVIEW_REQUIRED')
        for rel, expected in value.get('source_files', {}).items():
            if rel not in ('green-area-backend/gis_worker/gee_mock_queue.py', 'dev/gis_local/gee_mock_local.py'):
                raise RuntimeError('A62_REVIEW_SCOPE_INVALID')
            if hashlib.sha256((REPO / rel).read_bytes()).hexdigest() != expected:
                raise RuntimeError('A62_REVIEW_SOURCE_CHANGED')
        return raw, sha

    def migrate_a62(self, review_path, *, rollback_probe=False):
        self.proof_a62()
        raw, sha = self.reviewed(review_path)
        result = {}
        quote = m.t2.t1.literal
        for db in DATABASES:
            self.db.proof(db, stage='gis')
            old = self.sql('SELECT to_jsonb(sha256) FROM gis.schema_migrations WHERE version=43', db, read_only=True)
            if old:
                if old != sha:
                    raise RuntimeError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')
                result[db] = 'already_applied'
                continue
            # All proof/checksum decisions precede any DDL. No UPDATE of ledger.
            body = ("BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='60s';"
                + "SELECT set_config('gis.runtime_instance'," + quote(self.db.instance) + ',true);'
                + "SELECT set_config('gis.baseline_fingerprint'," + quote(m.t2.t1.legacy_fingerprint()) + ',true);'
                + raw.decode('utf-8-sig'))
            body += ('\nROLLBACK;' if rollback_probe else '\nSET LOCAL ROLE gis_owner;INSERT INTO gis.schema_migrations(version,sha256) VALUES(43,' + quote(sha) + ');RESET ROLE;COMMIT;')
            self.db.transport(db, body)
            result[db] = 'rolled_back_probe' if rollback_probe else 'applied'
        record = {'sha256': sha, 'databases': result, 'forward_only': True, 'rollback_probe': rollback_probe}
        (self.output / ('probe.json' if rollback_probe else 'migration-043.json')).write_text(json.dumps(record, indent=2), encoding='utf-8')
        return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('proof', 'probe', 'migrate'))
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    args = parser.parse_args()
    local = GeeMockLocal(args.runtime_dir)
    print(json.dumps(local.proof_a62() if args.action == 'proof' else local.migrate_a62(args.review, rollback_probe=args.action == 'probe')))
