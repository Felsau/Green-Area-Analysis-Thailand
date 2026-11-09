"""A4.1 attested Local operator; no cloud or GeoTIFF publication capability."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
s=importlib.util.spec_from_file_location('a4_existing_a3',HERE/'ldd_publication_local.py')
a3=importlib.util.module_from_spec(s);sys.modules[s.name]=a3;s.loader.exec_module(a3);m=a3.m
MIGRATION=REPO/'green-area-backend/migrations/041_gis_geotiff_prepare.sql'
FROZEN040='b93d65306e112763cd24019a0abf225a1e02698ba9a3f9ae2da13f33392b083e'

class GeoTiffPrepareLocal(a3.LddPublicationLocal):
    def __init__(self,root):
        super().__init__(root);self.output=self.db.runtime.root/'a4-geotiff-prepare';self.output.mkdir(exist_ok=True)
    def proof_a2(self):
        self.check_frozen();self.attest()
        before=json.loads((self.output/'before.json').read_text())
        if any(hashlib.sha256((REPO/'green-area-backend/migrations'/n).read_bytes()).hexdigest()!=h for n,h in before['sql'].items()):raise RuntimeError('APPLIED_MIGRATION_CHANGED')
        for db in ('postgres','gis_t1_upgrade'):
            self.db.proof(db,stage='gis')
            state=self.sql("SELECT jsonb_build_object('gate',activation_enabled,'latest',(SELECT max(version) FROM gis.schema_migrations),'old',(SELECT sha256 FROM gis.schema_migrations WHERE version=40),'new',(SELECT sha256 FROM gis.schema_migrations WHERE version=41)) FROM gis.environment",db,read_only=True)
            if state['gate'] is not False or state['old']!=FROZEN040 or state['latest'] not in (40,41):raise RuntimeError('A4_LOCAL_TARGET_REJECTED')
            if state['latest']==41 and state['new']!=hashlib.sha256(MIGRATION.read_bytes()).hexdigest():raise RuntimeError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')
        return {'local_only':True,'broad_gate_closed':True}
    def prepare(self):
        super().prepare()
        from gis_geotiff_prepared import LocalPreparedGeoTiffStore
        self.geotiff_prepared_store=LocalPreparedGeoTiffStore(self.gis_runtime,self.db.runtime.root,self.geotiff_store,self.verify_geotiff_native)
        return self
    def migrate_a4(self,review):
        self.proof_a2();raw,digest=a3.a2.a1.reviewed_sql(MIGRATION,json.loads(Path(review).read_text()))
        outcomes={};quote=m.t2.t1.literal
        for db in ('postgres','gis_t1_upgrade'):
            self.db.proof(db,stage='gis');old=self.sql('SELECT to_jsonb(sha256) FROM gis.schema_migrations WHERE version=41',db,read_only=True)
            outcomes[db]=a3.a2.a1.ledger_action(old,digest)
            if outcomes[db]=='already_applied':continue
            body="BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='60s';SELECT set_config('gis.runtime_instance',"+quote(self.db.instance)+",true);SELECT set_config('gis.baseline_fingerprint',"+quote(m.t2.t1.legacy_fingerprint())+',true);'+raw.decode()+"\nSET LOCAL ROLE gis_owner;INSERT INTO gis.schema_migrations(version,sha256) VALUES(41,"+quote(digest)+');RESET ROLE;COMMIT;'
            self.db.transport(db,body)
        result={'sha256':digest,'databases':outcomes};(self.output/'migration-041.json').write_text(json.dumps(result,indent=2));return result
    def create_geotiff_native(self,*,verify):
        self.attest();self.geotiff_prepared_store.attest();run=uuid4().hex
        name=('gis-geotiff-verify-' if verify else 'gis-geotiff-prepare-worker-')+run[:12]
        args=['create','-i','--init','--name',name,'--entrypoint','','--network','none' if verify else 'green-area-gis-t0-internal',
            '--memory=1g','--memory-swap=1g','--cpus=1','--pids-limit=64','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges:true','--user=65534:65534',
            '--tmpfs=/tmp:rw,nosuid,noexec,size=32m,mode=1777','--mount','type=bind,src='+str(REPO/'green-area-backend/gis_worker')+',dst=/app/gis_worker,readonly',
            '--mount','type=bind,src='+str(self.geotiff_store.objects)+',dst=/data/geotiff/objects,readonly',
            '--mount','type=bind,src='+str(self.geotiff_prepared_store.staging)+',dst=/data/prepare'+(',readonly' if verify else ''),
            '--workdir=/app/gis_worker','--label','gis.a4.scope='+('geotiff-verify' if verify else 'geotiff-prepare'),
            '--label','gis.a4.instance='+self.db.instance,'--label','gis.a4.run='+run,'--label','com.docker.compose.project=green-area-gis-t0',m.IMAGE,
            'python3','-I','-B','/app/gis_worker/'+('geotiff_prepare_child.py' if verify else 'geotiff_prepare_worker.py')]
        if verify:args.append('--verify')
        cid=self.db.runtime.docker(args).strip();canonical=m.t2.t1.runtime_module.canonical_bind_path
        policy={'name':name,'run_id':run,'geotiff_storage':canonical(str(self.geotiff_store.objects)),'geotiff_staging':canonical(str(self.geotiff_prepared_store.staging))}
        if verify:policy['verify_only']=True
        self.db.runtime.verify_worker(cid,policy);self.approved[cid]=policy
        try:self.attest()
        except Exception:
            self.db.runtime.verify_worker(cid,policy);self.db.runtime.docker(['rm',cid]);self.approved.pop(cid,None);raise
        return cid,policy
    def verify_geotiff_native(self,request):
        cid,policy=self.create_geotiff_native(verify=True)
        try:
            with tempfile.TemporaryFile() as output:
                proc=subprocess.Popen(self.db.runtime.base+['start','-a','-i',cid],stdin=subprocess.PIPE,stdout=output,stderr=subprocess.DEVNULL,cwd=self.db.runtime.root,env=self.db.runtime.env)
                try:proc.communicate(json.dumps(request,allow_nan=False).encode(),timeout=25)
                except subprocess.TimeoutExpired:
                    self.db.runtime.docker(['stop','-t','1',cid],optional=True);proc.kill();proc.communicate();raise RuntimeError('TRUSTED_VERIFIER_TIMEOUT') from None
                output.seek(0);raw=output.read(16385)
                if proc.returncode or len(raw)>16384:raise RuntimeError('TRUSTED_VERIFIER_FAILED')
                return json.loads(raw)
        finally:self.db.runtime.verify_worker(cid,policy);self.db.runtime.docker(['rm',cid]);self.approved.pop(cid,None)

def prepare_container(local,identity=None):return a3.a2.PrepareContainer(local,identity,create_native=local.create_geotiff_native)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('proof','migrate'));p.add_argument('--runtime-dir',type=Path,required=True);p.add_argument('--review',type=Path)
    args=p.parse_args();local=GeoTiffPrepareLocal(args.runtime_dir);print(json.dumps(local.migrate_a4(args.review) if args.action=='migrate' else local.proof_a2()))
