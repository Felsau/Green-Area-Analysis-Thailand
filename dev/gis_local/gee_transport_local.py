"""Exact-reviewed, forward-only 046 operator for the existing local sandbox."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
spec = importlib.util.spec_from_file_location('a6_sdk_runtime', HERE/'gee_runtime_local.py')
p = importlib.util.module_from_spec(spec); sys.modules[spec.name] = p; spec.loader.exec_module(p)
REPO = p.REPO
MIGRATION = REPO/'green-area-backend/migrations/046_gis_gee_live_authority.sql'
DATABASES = ('postgres','gis_t1_upgrade')
SENSITIVE = ('green-area-backend/gis_worker/gee_sdk_transport.py',
    'dev/gis_local/gee_transport_local.py','dev/gis_local/gee_transport_checks.py')


class TransportLocal(p.RuntimeLocal):
    def __init__(self, root):
        super().__init__(root)
        self.output = self.db.runtime.root/'a6-sdk-http'
        self.output.mkdir(exist_ok=True)

    def proof(self):
        self.check_frozen(); self.attest()
        for db in DATABASES:
            self.db.proof(db,stage='gis')
            state=self.sql("SELECT jsonb_build_object('gate',(SELECT activation_enabled FROM gis.environment),"
                "'ledger',(SELECT jsonb_agg(to_jsonb(t) ORDER BY version) FROM gis.schema_migrations t))",db,read_only=True)
            if state['gate'] is not False or [r['version'] for r in state['ledger']] not in (list(range(27,46)),list(range(27,47))):
                raise RuntimeError('A6_TRANSPORT_LOCAL_BASELINE_REQUIRED')
            for row in state['ledger']:
                path=next((REPO/'green-area-backend/migrations').glob(f"{row['version']:03d}_*.sql"))
                if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
                    raise RuntimeError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')
        return {'local_only':True,'both_databases_verified':True,'broad_gate_closed':True,'ledger_source_match':True}

    def reviewed(self, path):
        v=json.loads(Path(path).read_text(encoding='utf-8'))
        sha=hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
        sources={n:hashlib.sha256((REPO/n).read_bytes()).hexdigest() for n in SENSITIVE}
        if (v.get('independent_review') is not True or v.get('unresolved_high_critical')!=0
            or v.get('files')!={MIGRATION.name:sha} or v.get('source_files')!=sources):
            raise RuntimeError('A6_TRANSPORT_EXACT_REVIEW_REQUIRED')
        return sha

    def migrate(self, review, *, probe=False):
        self.proof(); sha=self.reviewed(review); quote=p.p.p.p.m.t2.t1.literal
        if not probe:
            if json.loads(Path(review).read_text(encoding='utf-8')).get('approval')!='local_apply_after_rollback_review':
                raise RuntimeError('A6_TRANSPORT_APPLY_REVIEW_REQUIRED')
            v=json.loads((self.output/'probe.json').read_text())
            if v!={'sha256':sha,'runtime_instance':self.db.instance,'databases':{d:'rolled_back_lifecycle' for d in DATABASES}}:
                raise RuntimeError('A6_TRANSPORT_ROLLBACK_PROOF_REQUIRED')
        # Preflight BOTH databases before DDL; never hide a checksum mismatch.
        applied={db:self.sql('SELECT to_jsonb(sha256) FROM gis.schema_migrations WHERE version=46',db,read_only=True) for db in DATABASES}
        if any(value is not None and value!=sha for value in applied.values()):
            raise RuntimeError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')
        result={}
        for db,old in applied.items():
            if old is not None:
                if probe:raise RuntimeError('A6_TRANSPORT_PROBE_REQUIRES_UNAPPLIED_MIGRATION')
                result[db]='already_applied';continue
            self.db.proof(db,stage='gis');self.reviewed(review)
            body="BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='60s';"
            body+="SELECT set_config('gis.runtime_instance',"+quote(self.db.instance)+",true);"
            body+="SELECT set_config('gis.baseline_fingerprint',"+quote(p.p.p.p.m.t2.t1.legacy_fingerprint())+",true);"
            body+=MIGRATION.read_text(encoding='utf-8')
            if probe:
                from gee_transport_checks import rollback_lifecycle
                body+=rollback_lifecycle(self,db)
                body+='SET CONSTRAINTS ALL IMMEDIATE;ROLLBACK;'
            else:
                body+='SET LOCAL ROLE gis_owner;INSERT INTO gis.schema_migrations(version,sha256) VALUES(46,'+quote(sha)+');RESET ROLE;COMMIT;'
            self.db.transport(db,body)
            result[db]='rolled_back_lifecycle' if probe else 'applied'
        record={'sha256':sha,'runtime_instance':self.db.instance,'databases':result}
        (self.output/('probe.json' if probe else 'migration-046.json')).write_text(json.dumps(record,indent=2),encoding='utf-8')
        return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('proof','probe','migrate','snapshot','check','preserve'))
    parser.add_argument('--runtime-dir',type=Path,required=True);parser.add_argument('--review',type=Path)
    args=parser.parse_args();local=TransportLocal(args.runtime_dir)
    if args.action in ('proof','probe','migrate'):
        value=local.proof() if args.action=='proof' else local.migrate(args.review,probe=args.action=='probe')
    else:
        from gee_transport_checks import snapshot,check,preserve
        value={'snapshot':snapshot,'check':check,'preserve':preserve}[args.action](local)
    print(json.dumps(value))
