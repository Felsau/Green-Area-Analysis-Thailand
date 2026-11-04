"""A6.4b reviewed local operator; no Google SDK/auth/cloud operations."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from uuid import uuid4

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('a64b_local_base', HERE / 'gee_mock_local.py')
p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p
spec.loader.exec_module(p)
REPO = p.REPO
sys.path.insert(0, str(REPO / 'green-area-backend'))
from gis_worker.gee_live_contracts import registered_input, queue_report
from gis_worker.gee_live_injected import fixture, InjectedSDK, InjectedTransport
from gis_worker.gee_live_bridge import InjectedBridge
from datetime import date

MIGRATION = REPO / 'green-area-backend/migrations/044_gis_live_foundation.sql'
SENSITIVE = ('green-area-backend/gis_worker/gee_live_contracts.py',
    'green-area-backend/gis_worker/gee_live_bridge.py', 'green-area-backend/gis_worker/gee_live_worker.py',
    'dev/gis_local/gee_live_local.py')


class LiveLocal(p.GeeMockLocal):
    def __init__(self, root):
        super().__init__(root)
        self.output = self.db.runtime.root / 'a6-4b-live-foundation'
        self.output.mkdir(exist_ok=True)

    def proof(self):
        self.check_frozen()
        self.attest()
        for db in p.DATABASES:
            self.db.proof(db, stage='gis')
            state = self.sql("SELECT jsonb_build_object('gate',(SELECT activation_enabled FROM gis.environment),"
                "'ledger',(SELECT jsonb_agg(to_jsonb(t) ORDER BY version) FROM gis.schema_migrations t))", db, read_only=True)
            if state['gate'] is not False or [r['version'] for r in state['ledger']] not in (list(range(27,44)), list(range(27,45))):
                raise RuntimeError('A64B_CLOSED_LOCAL_BASELINE_REQUIRED')
            for row in state['ledger']:
                path = next((REPO / 'green-area-backend/migrations').glob(f"{row['version']:03d}_*.sql"))
                if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
                    raise RuntimeError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')
        return {'local_only': True, 'broad_gate_closed': True, 'ledger_source_match': True}

    def reviewed(self, path):
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        expected = {MIGRATION.name: hashlib.sha256(MIGRATION.read_bytes()).hexdigest()}
        source = {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in SENSITIVE}
        if (value.get('independent_review') is not True or value.get('unresolved_high_critical') != 0
            or value.get('files') != expected or value.get('source_files') != source):
            raise RuntimeError('A64B_EXACT_REVIEW_REQUIRED')
        return expected[MIGRATION.name]

    def migrate(self, review, *, probe=False):
        self.proof()
        sha = self.reviewed(review)
        quote = p.m.t2.t1.literal
        result = {}
        for db in p.DATABASES:
            self.db.proof(db, stage='gis')
            old = self.sql('SELECT to_jsonb(sha256) FROM gis.schema_migrations WHERE version=44', db, read_only=True)
            if old is not None:
                if old != sha:
                    raise RuntimeError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')
                result[db] = 'already_applied'
                continue
            body = ("BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='60s';"
                + 'SELECT set_config(\'gis.runtime_instance\',' + quote(self.db.instance) + ',true);'
                + 'SELECT set_config(\'gis.baseline_fingerprint\',' + quote(p.m.t2.t1.legacy_fingerprint()) + ',true);'
                + MIGRATION.read_text(encoding='utf-8'))
            if probe:
                # Exercise new lifecycle and existing deferred triggers INSIDE the
                # rollback, not only parse DDL. This is not a JWT authority test.
                request, geometry, raw = fixture(uuid4().hex[:12])
                value = registered_input(request, geometry)
                output = InjectedBridge(sdk=InjectedSDK(), transport=InjectedTransport(raw), authorization=lambda: request.project, as_of=date(2026,1,1)).compute(request, geometry)
                # Construct report at SQL time from actual claim, preserving its
                # lease/input hashes. Content/canonical are still real validators.
                template = queue_report({'input_hash':'0'*64,'input_revision':1,'semantic_request_sha256':request.request_hash()},output)
                body += "SET LOCAL ROLE gis_owner;DO $probe$ DECLARE input uuid; actor uuid; created jsonb; claimed jsonb; completed jsonb; report jsonb; BEGIN "
                body += "SELECT user_id INTO actor FROM gis.officers LIMIT 1;IF actor IS NULL THEN RAISE EXCEPTION 'LOCAL_SYNTHETIC_OFFICER_REQUIRED'; END IF;"
                body += 'INSERT INTO gis.gee_live_inputs(value) VALUES(' + quote(json.dumps(value)) + '::jsonb) RETURNING id INTO input;'
                body += "created:=gis.gee_live_command(actor,gen_random_uuid(),'create',jsonb_build_object('input_id',input),true);"
                body += "claimed:=gis.queue_protocol_kind('claim',jsonb_build_object('worker_id',actor),'gee_live_v2')->'job';"
                body += 'report:=' + quote(json.dumps(template)) + "::jsonb||jsonb_build_object('input_hash',claimed->>'input_hash');"
                body += "completed:=gis.queue_protocol_kind('complete',jsonb_build_object('job_id',claimed->>'id','worker_id',actor,'lease_token',claimed->>'lease_token','report',report),'gee_live_v2');"
                body += "IF completed->>'state' IS DISTINCT FROM 'succeeded' THEN RAISE EXCEPTION 'LOCAL_PROBE_FAILED'; END IF; END $probe$;SET CONSTRAINTS ALL IMMEDIATE;ROLLBACK;"
            else:
                body += '\nSET LOCAL ROLE gis_owner;INSERT INTO gis.schema_migrations(version,sha256) VALUES(44,' + quote(sha) + ');RESET ROLE;COMMIT;'
            self.db.transport(db, body)
            result[db] = 'rolled_back_full_lifecycle' if probe else 'applied'
        record = {'sha256':sha, 'databases':result, 'forward_only':True, 'probe':probe, 'runtime_instance':self.db.instance}
        (self.output / ('probe.json' if probe else 'migration-044.json')).write_text(json.dumps(record,indent=2),encoding='utf-8')
        return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('proof','probe','migrate'))
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    args = parser.parse_args()
    local = LiveLocal(args.runtime_dir)
    print(json.dumps(local.proof() if args.action=='proof' else local.migrate(args.review,probe=args.action=='probe')))
