"""A1 exact-review local SQL runner. No auth keys, dotenv or cloud clients.

Reuses the existing identity/container/frozen-migration proofs. No startup,
provisioning, migration replay, gate opening, prepare worker or publication.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location('a1_existing_phase4', HERE.parent / 'gis_ui/phase4_local.py')
p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p
spec.loader.exec_module(p)
MIGRATION = REPO / 'green-area-backend/migrations/037_gis_publication_foundation.sql'
DATABASES = ('postgres', 'gis_t1_upgrade')


def reviewed_sql(path, review):
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if (review.get('independent_review') is not True or review.get('unresolved_high_critical') != 0
            or review.get('files') != {Path(path).name: digest}):
        raise RuntimeError('A1_EXACT_INDEPENDENT_REVIEW_REQUIRED')
    return raw, digest


def ledger_action(existing, digest):
    if existing is None:
        return 'apply'
    if existing == digest:
        return 'already_applied'
    raise RuntimeError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')


def verify_publication_state(state, digest):
    if state.get('activation_enabled') is not False or state.get('latest') not in (36, 37):
        raise RuntimeError('A1_LOCAL_CLOSED_GATE_BASELINE_REQUIRED')
    if state['latest'] == 37 and state.get('applied_sha') != digest:
        raise RuntimeError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')


class PublicationLocal(p.Phase4Local):
    def __init__(self, root):
        super().__init__(root)
        self.output = self.db.runtime.root / 'a1-publication-20261102'
        self.output.mkdir(exist_ok=True)

    def proof_a1(self):
        if p.m.fingerprint()['branch'] != 'feature/gis-data-management':
            raise RuntimeError('WRONG_BRANCH')
        self.check_frozen()
        self.attest()
        for db in DATABASES:
            self.db.proof(db, stage='gis')
            state = self.sql("SELECT jsonb_build_object('activation_enabled',activation_enabled,"
                "'latest',(SELECT max(version) FROM gis.schema_migrations),"
                "'applied_sha',(SELECT sha256 FROM gis.schema_migrations WHERE version=37)) FROM gis.environment", db, read_only=True)
            verify_publication_state(state, hashlib.sha256(MIGRATION.read_bytes()).hexdigest())
        return {'local_identity_proved': True, 'databases': list(DATABASES), 'activation_enabled': False}

    def preserve(self):
        self.proof_a1()
        result = self.baseline()
        for db in DATABASES:
            result[db]['gis_catalog'] = self.sql("SELECT jsonb_build_object(" + ','.join(
                "'" + t + "',(SELECT md5(COALESCE(string_agg(to_jsonb(x)::text,'|' ORDER BY id),'')) FROM gis."
                + t + ' x)' for t in ('datasets', 'editions', 'jobs', 'attempts', 'results', 'audit', 'receipts')) + ')', db, read_only=True)
            result[db]['old_functions'] = self.sql("SELECT to_jsonb(md5(string_agg(p.oid::text||pg_get_functiondef(p.oid),'|' ORDER BY p.oid))) "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname IN ('gis','public') AND p.prokind='f' AND p.proname NOT LIKE '%publication%'", db, role='postgres', read_only=True)
        return result

    def migrate_a1(self, review_path):
        self.proof_a1()
        review = json.loads(Path(review_path).read_text(encoding='utf-8'))
        raw, digest = reviewed_sql(MIGRATION, review)
        outcomes = {}
        for db in DATABASES:
            self.db.proof(db, stage='gis')
            existing = self.sql('SELECT to_jsonb(sha256) FROM gis.schema_migrations WHERE version=37', db, read_only=True)
            outcomes[db] = ledger_action(existing, digest)
            if outcomes[db] == 'already_applied':
                continue
            literal = p.m.t2.t1.literal
            body = ("BEGIN; SET LOCAL lock_timeout='5s'; SET LOCAL statement_timeout='60s';"
                + "SELECT set_config('gis.runtime_instance'," + literal(self.db.instance) + ',true);'
                + "SELECT set_config('gis.baseline_fingerprint'," + literal(p.m.t2.t1.legacy_fingerprint()) + ',true);'
                + raw.decode('utf-8-sig')
                + "\nSET LOCAL ROLE gis_owner; INSERT INTO gis.schema_migrations(version,sha256) VALUES(37,"
                + literal(digest) + '); RESET ROLE; COMMIT;')
            self.db.transport(db, body)
        result = {'sha256': digest, 'databases': outcomes, 'reviewer': review.get('reviewer'), 'forward_only': True}
        (self.output / 'migration-037.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('proof', 'migrate'))
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    args = parser.parse_args()
    local = PublicationLocal(args.runtime_dir)
    if args.action == 'migrate':
        if args.review is None:
            parser.error('--review is required')
        result = local.migrate_a1(args.review)
    else:
        result = local.proof_a1()
    print(json.dumps(result))


if __name__ == '__main__':
    main()
