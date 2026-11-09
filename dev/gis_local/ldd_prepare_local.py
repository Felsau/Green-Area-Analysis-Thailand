"""Attested Local A2 operator. No production env, Cloud or new image/service.

The local API's private verifier uses a one-shot credential-free, network=none
container. Queue daemon sees only its least-privilege JWT and staging RW mount.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location('a2_existing_a1', HERE/'publication_local.py')
a1 = importlib.util.module_from_spec(spec);sys.modules[spec.name] = a1;spec.loader.exec_module(a1)
m = a1.p.m
MIGRATION = REPO/'green-area-backend/migrations/038_gis_ldd_prepare.sql'
FROZEN_037 = 'bacd6937efb07d54fb37bef3d2be83a07c2ebff43ff97879d5220096532fcde6'


class LddPrepareLocal(a1.PublicationLocal):
    def __init__(self, root):
        super().__init__(root)
        self.output = self.db.runtime.root/'a2-ldd-prepare'
        self.output.mkdir(exist_ok=True)

    def proof_a2(self):
        self.check_frozen();self.attest()
        if m.fingerprint()['branch'] != 'feature/gis-data-management':
            raise RuntimeError('WRONG_BRANCH')
        if hashlib.sha256(a1.MIGRATION.read_bytes()).hexdigest() != FROZEN_037:
            raise RuntimeError('APPLIED_037_CHANGED')
        for db in a1.DATABASES:
            self.db.proof(db, stage='gis')
            state = self.sql("SELECT jsonb_build_object('gate',activation_enabled,'latest',(SELECT max(version) FROM gis.schema_migrations),"
                "'old',(SELECT sha256 FROM gis.schema_migrations WHERE version=37),'new',(SELECT sha256 FROM gis.schema_migrations WHERE version=38)) FROM gis.environment",db,read_only=True)
            if state['gate'] is not False or state['old'] != FROZEN_037 or state['latest'] not in (37,38):
                raise RuntimeError('A2_CLOSED_LOCAL_TARGET_REQUIRED')
            if state['latest']==38 and state['new'] != hashlib.sha256(MIGRATION.read_bytes()).hexdigest():
                raise RuntimeError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')
        return {'local_only':True,'gate_closed':True,'databases':list(a1.DATABASES)}

    def migrate_a2(self, review_path):
        self.proof_a2()
        raw,digest = a1.reviewed_sql(MIGRATION,json.loads(Path(review_path).read_text(encoding='utf-8')))
        outcomes={}
        for db in a1.DATABASES:
            self.db.proof(db,stage='gis')
            old=self.sql('SELECT to_jsonb(sha256) FROM gis.schema_migrations WHERE version=38',db,read_only=True)
            outcomes[db]=a1.ledger_action(old,digest)
            if outcomes[db]=='already_applied':continue
            literal=m.t2.t1.literal
            sql=("BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='60s';"
                +"SELECT set_config('gis.runtime_instance',"+literal(self.db.instance)+',true);'
                +"SELECT set_config('gis.baseline_fingerprint',"+literal(m.t2.t1.legacy_fingerprint())+',true);'
                +raw.decode('utf-8-sig')+"\nSET LOCAL ROLE gis_owner;INSERT INTO gis.schema_migrations(version,sha256) VALUES(38,"+literal(digest)+');RESET ROLE;COMMIT;')
            self.db.transport(db,sql)
        result={'sha256':digest,'databases':outcomes,'forward_only':True}
        (self.output/'migration-038.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        return result

    def prepare(self):
        self.proof_a2()
        super().prepare()
        from gis_ldd_prepared import LocalPreparedStore
        self.prepared_store=LocalPreparedStore(self.gis_runtime,self.db.runtime.root,self.store,self.verify_native)
        return self

    def api(self):
        from fastapi.testclient import TestClient
        from gis_app import create_app
        return TestClient(create_app(self.gis_runtime,ldd_store=self.store,geotiff_store=self.geotiff_store,
            prepared_store=self.prepared_store),base_url='http://127.0.0.1:55422')

    def create_native(self, *, verify):
        self.attest();self.prepared_store.attest()
        run=uuid4().hex
        name=('gis-ldd-verify-' if verify else 'gis-ldd-prepare-worker-')+run[:12]
        scope='ldd-verify' if verify else 'ldd-prepare'
        args=['create','-i','--init','--name',name,'--entrypoint','','--network','none' if verify else 'green-area-gis-t0-internal',
            '--memory=1g','--memory-swap=1g','--cpus=1','--pids-limit=64','--read-only','--cap-drop=ALL',
            '--security-opt=no-new-privileges:true','--user=65534:65534','--tmpfs=/tmp:rw,nosuid,noexec,size=32m,mode=1777',
            '--mount','type=bind,src='+str(REPO/'green-area-backend/gis_worker')+',dst=/app/gis_worker,readonly',
            '--mount','type=bind,src='+str(self.store.objects)+',dst=/data/ldd,readonly',
            '--mount','type=bind,src='+str(self.prepared_store.staging)+',dst=/data/prepare'+(',readonly' if verify else ''),
            '--workdir=/app/gis_worker','--label','gis.a2.scope='+scope,'--label','gis.a2.instance='+self.db.instance,
            '--label','gis.a2.run='+run,'--label','com.docker.compose.project=green-area-gis-t0',m.IMAGE,
            'python3','-I','-B','/app/gis_worker/'+('ldd_prepare_child.py' if verify else 'ldd_prepare_worker.py')]
        if verify:args.append('--verify')
        cid=self.db.runtime.docker(args).strip()
        canonical=m.t2.t1.runtime_module.canonical_bind_path
        policy={'name':name,'run_id':run,'ldd_storage':canonical(str(self.store.objects)),
            'prepare_staging':canonical(str(self.prepared_store.staging))}
        if verify:policy['verify_only']=True
        self.db.runtime.verify_worker(cid,policy)
        self.approved[cid]=policy
        try:
            self.attest()
        except Exception:
            # This create operation owns the exact inspected, not-yet-started
            # container. Do not leave it behind if aggregate guard checks fail.
            self.db.runtime.verify_worker(cid,policy)
            self.db.runtime.docker(['rm',cid])
            self.approved.pop(cid,None)
            raise
        return cid,policy

    def verify_native(self, request):
        cid,_=self.create_native(verify=True)
        try:
            with tempfile.TemporaryFile() as output:
                proc=subprocess.Popen(self.db.runtime.base+['start','-a','-i',cid],stdin=subprocess.PIPE,stdout=output,
                    stderr=subprocess.DEVNULL,cwd=self.db.runtime.root,env=self.db.runtime.env)
                try:
                    proc.communicate(json.dumps(request,allow_nan=False).encode(),timeout=25)
                except subprocess.TimeoutExpired:
                    self.db.runtime.docker(['stop','-t','1',cid],optional=True)
                    proc.kill();proc.communicate()
                    raise RuntimeError('TRUSTED_VERIFIER_TIMEOUT') from None
                output.seek(0);raw=output.read(16385)
                if proc.returncode or len(raw)>16384:raise RuntimeError('TRUSTED_VERIFIER_FAILED')
                return json.loads(raw)
        finally:
            # Only this exact owned, inspected one-shot container is removed.
            self.db.runtime.verify_worker(cid,self.approved[cid])
            self.db.runtime.docker(['rm',cid])
            self.approved.pop(cid,None)


class PrepareContainer(m.ContainerWorker):
    def __init__(self, local, identity=None, *, create_native=None):
        self.local=local
        self.identity=identity or m.identity_module.provision(local)
        self.events,self.errors=[],[]
        self.cid,self.policy=(create_native or local.create_native)(verify=False)
        self.proc=subprocess.Popen(local.db.runtime.base+['start','-a','-i',self.cid],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,cwd=local.db.runtime.root,env=local.db.runtime.env)
        identity=self.identity
        bootstrap={'api_url':'http://green-area-gis-t0-gateway:8000','subject':identity.subject,'anon_key':identity.anon_key,
            'access_token':identity.access_token,'refresh_token':identity.refresh_token,'runtime_instance':local.db.instance,
            'baseline_fingerprint':m.t2.t1.legacy_fingerprint()}
        self.proc.stdin.write((json.dumps(bootstrap)+'\n').encode());self.proc.stdin.close()
        def collect():
            for line in iter(lambda:self.proc.stdout.readline(4097),b''):
                try:
                    item=json.loads(line)
                    if len(line)>4096 or set(item)-{'event','job_id','state','error_code'}:raise ValueError()
                    if len(self.events)<512:self.events.append(item)
                except Exception:
                    if len(self.errors)<512:self.errors.append('WORKER_EVENT_REJECTED')
        self.reader=m.threading.Thread(target=collect,daemon=True);self.reader.start()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('proof','migrate'))
    parser.add_argument('--runtime-dir',type=Path,required=True)
    parser.add_argument('--review',type=Path)
    args=parser.parse_args();local=LddPrepareLocal(args.runtime_dir)
    print(json.dumps(local.migrate_a2(args.review) if args.action=='migrate' else local.proof_a2()))
