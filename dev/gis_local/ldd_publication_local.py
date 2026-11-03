"""A3 Local operator; exact forward migration, broad gate closed, RO verifier."""
import argparse
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
spec=importlib.util.spec_from_file_location('a3_existing_a2',HERE/'ldd_prepare_local.py')
a2=importlib.util.module_from_spec(spec);sys.modules[spec.name]=a2;spec.loader.exec_module(a2)
m=a2.m
MIGRATION=REPO/'green-area-backend/migrations/039_gis_ldd_publication.sql'
CORRECTION=REPO/'green-area-backend/migrations/040_gis_ldd_publication_jsonb_fix.sql'
FROZEN_038='e55344ef585e9c23c9269dae414ed73ba05fa508625fe6c6e7acf2e148795825'

class LddPublicationLocal(a2.LddPrepareLocal):
    def __init__(self,root):
        super().__init__(root);self.output=self.db.runtime.root/'a3-ldd-publication';self.output.mkdir(exist_ok=True)

    def proof_a2(self):
        # Preserve historical A2 proof; this approved subclass alone permits039.
        self.check_frozen();self.attest()
        if hashlib.sha256(a2.a1.MIGRATION.read_bytes()).hexdigest()!=a2.FROZEN_037 or hashlib.sha256(a2.MIGRATION.read_bytes()).hexdigest()!=FROZEN_038:
            raise RuntimeError('APPLIED_MIGRATION_CHANGED')
        for db in a2.a1.DATABASES:
            self.db.proof(db,stage='gis')
            state=self.sql("SELECT jsonb_build_object('gate',activation_enabled,'latest',(SELECT max(version) FROM gis.schema_migrations),'sha38',(SELECT sha256 FROM gis.schema_migrations WHERE version=38),'sha39',(SELECT sha256 FROM gis.schema_migrations WHERE version=39),'sha40',(SELECT sha256 FROM gis.schema_migrations WHERE version=40)) FROM gis.environment",db,read_only=True)
            if state['gate'] is not False or state['latest'] not in (38,39,40) or state['sha38']!=FROZEN_038:raise RuntimeError('A3_LOCAL_TARGET_REJECTED')
            if state['latest']>=39 and state['sha39']!=hashlib.sha256(MIGRATION.read_bytes()).hexdigest():raise RuntimeError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')
            if state['latest']==40 and state['sha40']!=hashlib.sha256(CORRECTION.read_bytes()).hexdigest():raise RuntimeError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')
        return {'local_only':True,'broad_gate_closed':True,'databases':list(a2.a1.DATABASES)}

    def runtime(self,*,activation=False):
        if activation:raise RuntimeError('A3_BROAD_GATE_FORBIDDEN')
        runtime=super().runtime(activation=False)
        runtime.settings=replace(runtime.settings,ldd_publication_enabled=True);runtime.settings.validate()
        runtime.ldd_publication_enabled=True
        return runtime

    def prepare(self):
        super().prepare()
        from gis_ldd_publication import LocalLddPublication
        self.publication=LocalLddPublication(self.gis_runtime,self.prepared_store,self.verify_publication_native)
        return self

    def migrate_a3(self,review_path,version=39):
        if version not in (39,40):raise RuntimeError('A3_MIGRATION_VERSION_REJECTED')
        path=MIGRATION if version==39 else CORRECTION
        self.proof_a2();raw,digest=a2.a1.reviewed_sql(path,json.loads(Path(review_path).read_text(encoding='utf-8')))
        outcomes={};literal=m.t2.t1.literal
        for db in a2.a1.DATABASES:
            self.db.proof(db,stage='gis')
            old=self.sql('SELECT to_jsonb(sha256) FROM gis.schema_migrations WHERE version='+str(version),db,read_only=True)
            outcomes[db]=a2.a1.ledger_action(old,digest)
            if outcomes[db]=='already_applied':continue
            body=("BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='60s';"
                +"SELECT set_config('gis.runtime_instance',"+literal(self.db.instance)+',true);'
                +"SELECT set_config('gis.baseline_fingerprint',"+literal(m.t2.t1.legacy_fingerprint())+',true);'
                +raw.decode('utf-8-sig')+"\nSET LOCAL ROLE gis_owner;INSERT INTO gis.schema_migrations(version,sha256) VALUES("+str(version)+','+literal(digest)+');RESET ROLE;COMMIT;')
            self.db.transport(db,body)
        report={'sha256':digest,'databases':outcomes,'broad_gate_closed':True}
        (self.output/('migration-%03d.json'%version)).write_text(json.dumps(report,indent=2),encoding='utf-8');return report

    def verify_publication_native(self,packet):
        self.attest();self.prepared_store.attest();run=uuid4().hex;name='gis-ldd-publication-verify-'+run[:12]
        args=['create','-i','--init','--name',name,'--entrypoint','','--network','none','--memory=1g','--memory-swap=1g',
            '--cpus=1','--pids-limit=64','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges:true','--user=65534:65534',
            '--tmpfs=/tmp:rw,nosuid,noexec,size=32m,mode=1777',
            '--mount','type=bind,src='+str(REPO/'green-area-backend/gis_worker')+',dst=/app/gis_worker,readonly',
            '--mount','type=bind,src='+str(self.store.objects)+',dst=/data/ldd,readonly',
            '--mount','type=bind,src='+str(self.prepared_store.objects)+',dst=/data/ldd-artifacts,readonly',
            '--workdir=/app/gis_worker','--label','gis.a3.scope=ldd-publication-verifier','--label','gis.a3.instance='+self.db.instance,
            '--label','gis.a3.run='+run,'--label','com.docker.compose.project=green-area-gis-t0',m.IMAGE,
            'python3','-I','-B','/app/gis_worker/ldd_publication_child.py']
        cid=self.db.runtime.docker(args).strip();canonical=m.t2.t1.runtime_module.canonical_bind_path
        policy={'name':name,'run_id':run,'ldd_storage':canonical(str(self.store.objects)),
            'prepare_objects':canonical(str(self.prepared_store.objects)),'publication_only':True}
        self.db.runtime.verify_worker(cid,policy);self.approved[cid]=policy
        try:
            self.attest()
            with tempfile.TemporaryFile() as output:
                proc=subprocess.Popen(self.db.runtime.base+['start','-a','-i',cid],stdin=subprocess.PIPE,stdout=output,stderr=subprocess.DEVNULL,cwd=self.db.runtime.root,env=self.db.runtime.env)
                try:proc.communicate(json.dumps(packet,allow_nan=False).encode(),timeout=25)
                except subprocess.TimeoutExpired:
                    self.db.runtime.docker(['stop','-t','1',cid],optional=True);proc.kill();proc.communicate();raise RuntimeError('PUBLICATION_VERIFIER_TIMEOUT') from None
                output.seek(0);raw=output.read(16385)
                if proc.returncode or len(raw)>16384:raise RuntimeError('PUBLICATION_VERIFIER_FAILED')
                return json.loads(raw)
        finally:
            self.db.runtime.verify_worker(cid,policy);self.db.runtime.docker(['rm',cid]);self.approved.pop(cid,None)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('proof','migrate'))
    parser.add_argument('--runtime-dir',type=Path,required=True);parser.add_argument('--review',type=Path);parser.add_argument('--version',type=int,choices=(39,40),default=39)
    args=parser.parse_args();local=LddPublicationLocal(args.runtime_dir)
    print(json.dumps(local.migrate_a3(args.review,args.version) if args.action=='migrate' else local.proof_a2()))
