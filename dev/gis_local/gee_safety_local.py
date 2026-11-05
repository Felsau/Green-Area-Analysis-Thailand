"""Reviewed A6.4d-1 Local-only operator. Never enables live execution."""
from __future__ import annotations
import argparse
from datetime import date
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from uuid import uuid4

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('a64d1_previous_local',HERE/'gee_live_local.py')
p=importlib.util.module_from_spec(spec);sys.modules[spec.name]=p;spec.loader.exec_module(p)
REPO=p.REPO
MIGRATION=REPO/'green-area-backend/migrations/045_gis_execution_safety.sql'
SENSITIVE=('green-area-backend/gis_worker/gee_execution_safety.py',
    'green-area-backend/gis_worker/gee_safety_worker.py','green-area-backend/gis_worker/gee_safety_child.py',
    'dev/gis_local/gee_safety_local.py')


class SafetyLocal(p.LiveLocal):
    def __init__(self,root):
        super().__init__(root)
        self.output=self.db.runtime.root/'a6-4d1-safety';self.output.mkdir(exist_ok=True)

    def proof(self):
        self.check_frozen();self.attest()
        for db in p.p.DATABASES:
            self.db.proof(db,stage='gis')
            state=self.sql("SELECT jsonb_build_object('gate',(SELECT activation_enabled FROM gis.environment),"
                "'ledger',(SELECT jsonb_agg(to_jsonb(t) ORDER BY version) FROM gis.schema_migrations t))",db,read_only=True)
            if state['gate'] is not False or [r['version'] for r in state['ledger']] not in (list(range(27,45)),list(range(27,46))):
                raise RuntimeError('A64D1_CLOSED_LOCAL_BASELINE_REQUIRED')
            for row in state['ledger']:
                path=next((REPO/'green-area-backend/migrations').glob(f"{row['version']:03d}_*.sql"))
                if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
                    raise RuntimeError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')
        return {'local_only':True,'broad_gate_closed':True,'ledger_source_match':True}

    def reviewed(self,path):
        value=json.loads(Path(path).read_text(encoding='utf-8'))
        sha=hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
        source={name:hashlib.sha256((REPO/name).read_bytes()).hexdigest() for name in SENSITIVE}
        if (value.get('independent_review') is not True or value.get('unresolved_high_critical')!=0
            or value.get('files')!={MIGRATION.name:sha} or value.get('source_files')!=source):
            raise RuntimeError('A64D1_EXACT_REVIEW_REQUIRED')
        return sha

    def migrate(self,review,*,probe=False):
        self.proof();sha=self.reviewed(review);quote=p.p.m.t2.t1.literal;result={}
        if not probe:
            proof=json.loads((self.output/'probe.json').read_text(encoding='utf-8'))
            if proof.get('sha256')!=sha or proof.get('runtime_instance')!=self.db.instance or proof.get('databases')!={db:'rolled_back_full_lifecycle' for db in p.p.DATABASES}:
                raise RuntimeError('A64D1_ROLLBACK_LIFECYCLE_REQUIRED')
        for db in p.p.DATABASES:
            self.db.proof(db,stage='gis')
            old=self.sql('SELECT to_jsonb(sha256) FROM gis.schema_migrations WHERE version=45',db,read_only=True)
            if old is not None:
                if old!=sha:raise RuntimeError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')
                result[db]='already_applied';continue
            body=("BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='60s';"
                +"SELECT set_config('gis.runtime_instance',"+quote(self.db.instance)+",true);"
                +"SELECT set_config('gis.baseline_fingerprint',"+quote(p.p.m.t2.t1.legacy_fingerprint())+",true);"
                +MIGRATION.read_text(encoding='utf-8'))
            if probe:
                from gis_worker.gee_execution_safety import report
                request,geometry,raw=p.fixture(uuid4().hex[:12]);value=p.registered_input(request,geometry)
                output=p.InjectedBridge(sdk=p.InjectedSDK(),transport=p.InjectedTransport(raw),authorization=lambda:request.project,as_of=date(2026,1,1)).compute(request,geometry)
                template=p.queue_report({'input_hash':'0'*64,'input_revision':1,'semantic_request_sha256':request.request_hash()},output)
                body+="SET LOCAL ROLE gis_owner;DO $probe$ DECLARE input uuid;actor uuid;session uuid;created jsonb;claimed jsonb;reservation jsonb;base jsonb;wrapped jsonb;done jsonb;BEGIN "
                body+="SELECT user_id INTO actor FROM gis.officers LIMIT 1;IF actor IS NULL THEN RAISE EXCEPTION 'LOCAL_SYNTHETIC_OFFICER_REQUIRED';END IF;"
                body+='INSERT INTO gis.gee_live_inputs(value) VALUES('+quote(json.dumps(value))+'::jsonb) RETURNING id INTO input;'
                body+="session:=gis.safety_session(actor,actor);created:=gis.safety_enqueue(actor,gen_random_uuid(),input,session);"
                body+="claimed:=gis.queue_protocol_kind('claim',jsonb_build_object('worker_id',actor),'gee_safety_rehearsal')->'job';"
                body+="reservation:=gis.safety_budget(actor,'reserve',jsonb_build_object('job_id',claimed->>'id','lease_token',claimed->>'lease_token','request_key',gen_random_uuid(),'kind','compute'));"
                body+="PERFORM gis.safety_budget(actor,'attempted',jsonb_build_object('job_id',claimed->>'id','lease_token',claimed->>'lease_token','request_id',reservation->>'request_id'));"
                body+="PERFORM gis.safety_budget(actor,'finished',jsonb_build_object('job_id',claimed->>'id','lease_token',claimed->>'lease_token','request_id',reservation->>'request_id','evidence_sha256',"+quote(output.content.evidence_sha256)+"));"
                body+='base:='+quote(json.dumps(template))+"::jsonb||jsonb_build_object('input_hash',claimed->>'input_hash');"
                body+="wrapped:=jsonb_build_object('schema_version',3,'protocol','gee_safety_rehearsal','execution','rehearsal','live_enabled',false,'session_id',session,'policy_sha256',claimed->>'policy_sha256','valid',base->'valid','error_code',base->'error_code','base',base,'receipts',jsonb_build_array(reservation->>'request_id'),'failure_kind',null);"
                body+="done:=gis.queue_protocol_kind('complete',jsonb_build_object('worker_id',actor,'job_id',claimed->>'id','lease_token',claimed->>'lease_token','report',wrapped),'gee_safety_rehearsal');IF done->>'state' IS DISTINCT FROM 'succeeded' THEN RAISE EXCEPTION 'A64D1_PROBE_FAILED';END IF;END $probe$;SET CONSTRAINTS ALL IMMEDIATE;ROLLBACK;"
            else:
                body+='\nSET LOCAL ROLE gis_owner;INSERT INTO gis.schema_migrations(version,sha256) VALUES(45,'+quote(sha)+');RESET ROLE;COMMIT;'
            self.db.transport(db,body);result[db]='rolled_back_full_lifecycle' if probe else 'applied'
        record={'sha256':sha,'databases':result,'forward_only':True,'probe':probe,'runtime_instance':self.db.instance}
        (self.output/('probe.json' if probe else 'migration-045.json')).write_text(json.dumps(record,indent=2),encoding='utf-8')
        return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('proof','probe','migrate'))
    parser.add_argument('--runtime-dir',type=Path,required=True);parser.add_argument('--review',type=Path)
    args=parser.parse_args();local=SafetyLocal(args.runtime_dir)
    print(json.dumps(local.proof() if args.action=='proof' else local.migrate(args.review,probe=args.action=='probe')))
