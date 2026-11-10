"""Attested T3-only local operator. Never a worker credential provider on Cloud."""
from __future__ import annotations
import hashlib, importlib.util, json, logging, queue, subprocess, sys, threading, time
from pathlib import Path
from uuid import uuid4

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
spec=importlib.util.spec_from_file_location('remediation_t2',HERE.parent/'gis_local/t2_local.py')
t2=importlib.util.module_from_spec(spec);sys.modules[spec.name]=t2;spec.loader.exec_module(t2)
spec=importlib.util.spec_from_file_location('remediation_identity',HERE/'t3_identity.py')
identity_module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=identity_module;spec.loader.exec_module(identity_module)
IMAGE='sha256:fca4560d8a0d0198c0eb75fbf6598314cd8ed4a5e8bafa00e1d7298126aa04c9'
MIGRATION=REPO/'green-area-backend/migrations/032_gis_worker_remediation.sql'
# The only local branch the attested operators run on. Every operator that checks the branch reads this.
GIS_BRANCH='feature/gis-w2-integration-prep'

def fingerprint():
    files={}
    for folder in ('dev/gis_local','dev/gis_worker','green-area-backend/gis_worker','green-area-backend/migrations','green-area-backend/tests'):
        for p in sorted((REPO/folder).rglob('*')):
            if p.is_file() and p.suffix in ('.py','.sql','.json','.yaml','.zip','.tif') and not any(x in p.parts for x in ('__pycache__','.pytest_cache')):
                if p.name.endswith('evidence.json'):continue
                files[p.relative_to(REPO).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    for name in ('main.py','gis_app.py','gis_runtime.py','gis_schemas.py','gis_service.py','routers/gis.py'):
        p=REPO/'green-area-backend'/name;files[p.relative_to(REPO).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    return {'sha256':hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'files':files,
            'branch':subprocess.check_output(['git','branch','--show-current'],cwd=REPO,text=True).strip(),
            'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()}

class Local(t2.LocalT2):
    def __init__(self,root):
        super().__init__(root)
        self.directory=self.db.runtime.root/'t3-remediation';self.directory.mkdir(exist_ok=True)
        self.approved={}
        self._strict=self.db.runtime.verify_containers
        self.db.runtime.verify_containers=lambda:self._strict(approved_workers=self.approved)
        self.frozen=json.loads((self.directory/'initial-source-state.json').read_text(encoding='utf-8'))
        self.check_frozen()
    def check_frozen(self):
        if fingerprint()['branch']!=GIS_BRANCH:raise t2.t1.SafetyError('WRONG_BRANCH')
        for rel,h in self.frozen['files'].items():
            if rel.startswith('green-area-backend/migrations/') and int(Path(rel).name[:3])<=31:
                if hashlib.sha256((REPO/rel).read_bytes()).hexdigest()!=h:raise t2.t1.SafetyError('APPLIED_MIGRATION_FILE_CHANGED')
        for version in (32,33):
            record=self.directory/('migration-%03d.json'%version)
            if record.exists():
                expected=json.loads(record.read_text(encoding='utf-8'))['sha256']
                path=next((REPO/'green-area-backend/migrations').glob('%03d_*.sql'%version))
                if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise t2.t1.SafetyError('APPLIED_MIGRATION_FILE_CHANGED')
    def sql(self,body,database='postgres',role='gis_owner',read_only=False,check=True):
        self.attest();self.db.proof(database,stage='gis')
        if role not in ('gis_owner','gis_worker','postgres'):raise t2.t1.SafetyError('OPERATOR_ROLE_REJECTED')
        switch='' if role=='postgres' else 'SET LOCAL ROLE '+role+';'
        result=self.db.transport(database,('BEGIN READ ONLY;' if read_only else 'BEGIN;')+"SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='30s';"+switch+body+';COMMIT;',check=check)
        if not check:return result
        lines=[x for x in result.stdout.splitlines() if x.strip()]
        return json.loads(lines[-1]) if lines else None
    def migrate(self,review_path,version=32):
        if version not in (32,33):raise t2.t1.SafetyError('MIGRATION_VERSION_REJECTED')
        self.check_frozen();self.attest()
        path=next((REPO/'green-area-backend/migrations').glob('%03d_*.sql'%version))
        content=path.read_bytes();checksum=hashlib.sha256(content).hexdigest()
        review=json.loads(Path(review_path).read_text(encoding='utf-8'))
        if review.get('independent_review') is not True or review.get('unresolved_high_critical')!=0 or review.get('files')!={path.name:checksum}:
            raise t2.t1.SafetyError('EXACT_INDEPENDENT_REVIEW_REQUIRED')
        for database in ('postgres','gis_t1_upgrade'):
            self.db.proof(database,stage='gis')
            existing=self.sql("SELECT to_jsonb(sha256) FROM gis.schema_migrations WHERE version="+str(version),database,read_only=True)
            if existing:
                if existing!=checksum:raise t2.t1.SafetyError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')
                continue
            body=("BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='60s';"
                +"SELECT set_config('gis.runtime_instance',"+t2.t1.literal(self.db.instance)+",true);"
                +"SELECT set_config('gis.baseline_fingerprint',"+t2.t1.literal(t2.t1.legacy_fingerprint())+",true);"
                +content.decode('utf-8-sig')+"\nSET LOCAL ROLE gis_owner;INSERT INTO gis.schema_migrations(version,sha256) VALUES("+str(version)+","+t2.t1.literal(checksum)+");RESET ROLE;COMMIT;")
            self.db.transport(database,body)
        self.write('migration-%03d.json'%version,{'sha256':checksum,'databases':['postgres','gis_t1_upgrade'],'reviewer':review.get('reviewer'),'forward_only':True})
    def baseline(self):
        result={}
        for db in ('postgres','gis_t1_upgrade'):
            tables=self.sql("SELECT jsonb_agg(tablename ORDER BY tablename) FROM pg_tables WHERE schemaname='public'",db,role='postgres',read_only=True)
            pairs=[]
            for table in tables:
                ident='"'+table.replace('"','""')+'"'
                pairs.append(t2.t1.literal(table)+",(SELECT jsonb_build_object('rows',count(*),'hash',md5(COALESCE(string_agg(to_jsonb(t)::text,'|' ORDER BY to_jsonb(t)::text),''))) FROM public."+ident+' t)')
            public=self.sql("SELECT jsonb_build_object('tables',jsonb_build_object("+','.join(pairs)+"),'profiles',(SELECT COALESCE(jsonb_object_agg(id::text,md5(to_jsonb(t)::text)),'{}'::jsonb) FROM public.profiles t))",db,role='postgres',read_only=True)
            public['ledger']=self.sql("SELECT jsonb_agg(to_jsonb(s) ORDER BY version) FROM gis.schema_migrations s",db,read_only=True)
            result[db]=public
        return result

class ContainerWorker:
    """Only the local operator controls Docker. Daemon receives no Docker socket."""
    def __init__(self,local,identity):
        self.local=local;self.identity=identity;self.events=[];self.errors=[]
        run=uuid4().hex;name='gis-t3-worker-'+run[:12]
        local.attest()
        args=['create','-i','--init','--name',name,'--entrypoint','','--network','green-area-gis-t0-internal',
              '--memory=1g','--memory-swap=1g','--cpus=1','--pids-limit=64','--read-only','--cap-drop=ALL',
              '--security-opt=no-new-privileges:true','--user=65534:65534',
              '--tmpfs=/tmp:rw,nosuid,noexec,size=32m,mode=1777',
              '--mount','type=bind,src='+str(REPO/'green-area-backend/gis_worker')+',dst=/app/gis_worker,readonly',
              '--workdir=/app/gis_worker','--label','gis.t3.scope=gis-worker-t3','--label','gis.t3.instance='+local.db.instance,
              '--label','gis.t3.run='+run,'--label','com.docker.compose.project=green-area-gis-t0',
              IMAGE,'python3','-I','-B','/app/gis_worker/worker.py']
        self.cid=local.db.runtime.docker(args).strip()
        self.policy={'name':name,'run_id':run}
        local.db.runtime.verify_worker(self.cid,self.policy)
        local.approved[self.cid]=self.policy
        local.attest()
        self.proc=subprocess.Popen(local.db.runtime.base+['start','-a','-i',self.cid],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            cwd=local.db.runtime.root,env=local.db.runtime.env)
        bootstrap={'api_url':'http://green-area-gis-t0-gateway:8000','subject':identity.subject,
                   'anon_key':identity.anon_key,'access_token':identity.access_token,'refresh_token':identity.refresh_token,
                   'runtime_instance':local.db.instance,'baseline_fingerprint':t2.t1.legacy_fingerprint()}
        self.proc.stdin.write((json.dumps(bootstrap)+'\n').encode());self.proc.stdin.close()
        def collect():
            while True:
                line=self.proc.stdout.readline(4097)
                if not line:break
                try:
                    item=json.loads(line)
                    if set(item)-{'event','job_id','state','error_code'} or len(line)>4096:raise ValueError()
                    if len(self.events)<512:self.events.append(item)
                except Exception:
                    if len(self.errors)<512:self.errors.append('WORKER_EVENT_REJECTED')
        self.reader=threading.Thread(target=collect,daemon=True);self.reader.start()
    def has(self,event,job=None):
        return any(x.get('event')==event and (job is None or x.get('job_id')==job) for x in self.events)
    def signal(self,name):
        self.local.db.runtime.verify_worker(self.cid,self.policy)
        self.local.db.runtime.docker(['kill','--signal',name,self.cid])
    def close(self):
        self.local.db.runtime.verify_worker(self.cid,self.policy)
        state=json.loads(self.local.db.runtime.docker(['inspect','--format','{{json .State}}',self.cid]))
        if state.get('Running'):
            self.signal('SIGTERM')
            deadline=time.monotonic()+20
            while self.proc.poll() is None and time.monotonic()<deadline:time.sleep(.2)
            if self.proc.poll() is None:self.signal('SIGKILL')
        self.proc.wait(timeout=10);self.reader.join(timeout=2)
        self.local.db.runtime.verify_worker(self.cid,self.policy)
        self.local.db.runtime.docker(['rm',self.cid])
        del self.local.approved[self.cid]
        self.local.attest()

def wait_for(predicate,timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.3)
    raise RuntimeError('LOCAL_TEST_WAIT_EXPIRED')
