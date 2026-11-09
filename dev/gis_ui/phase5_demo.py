"""Existing local sandbox demo: no migrations, dotenv, live GEE or Cloud.

Human passwords use getpass and remain in memory. Smoke credentials are random
and sent only over the private browser stdin pipe. Worker credentials never go
to the browser, environment, evidence or console. Existing launchers own limits,
JWTs, exact container approval and graceful shutdown.
"""
from __future__ import annotations
import argparse
import getpass
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from uuid import uuid4

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
spec=importlib.util.spec_from_file_location('phase5_existing_local',HERE/'phase4_local.py')
p=importlib.util.module_from_spec(spec);sys.modules[spec.name]=p;spec.loader.exec_module(p)
m=p.m


def local_target(root):
    if m.fingerprint()['branch']!=m.GIS_BRANCH:
        raise RuntimeError('WRONG_BRANCH')
    local=p.Phase4Local(root)
    local.check_frozen()
    return local


def source():
    value=m.fingerprint()
    for name in ('gis_ldd_storage.py','gis_geotiff_storage.py','gee_utils.py','routers/ndvi/compute.py','routers/ndvi/endpoints.py','routers/lst.py','dependencies.py'):
        path=REPO/'green-area-backend'/name
        value['files'][path.relative_to(REPO).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    for path in HERE.glob('phase5_*'):
        if path.is_file():value['files'][path.relative_to(REPO).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ('legacy_demo.py','legacy_smoke.cjs','vite.config.mjs','tests/test_legacy_demo.py'):
        path=HERE/name
        value['files'][path.relative_to(REPO).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    for path in (REPO/'green-area-backend/routers').rglob('*.py'):
        value['files'][path.relative_to(REPO).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    for path in (REPO/'green-area-frontend/src').rglob('*'):
        if path.is_file() and path.suffix in ('.js','.css'):value['files'][path.relative_to(REPO).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    value['sha256']=hashlib.sha256(json.dumps(value['files'],sort_keys=True).encode()).hexdigest()
    return value


class Demo:
    def __init__(self,root):
        self.local=local_target(root).prepare()
        self.local.attest()
        for port in (3000,55422):
            with socket.socket() as sock:sock.bind(('127.0.0.1',port))
        self.run=uuid4().hex[:10]
        self.output=root/'phase5'/self.run
        self.output.mkdir(parents=True)
        self.before=self.local.baseline()
        self.initial_source=source()
        self.workers=[];self.server=None;self.vite=None;self.thread=None
        self.users={};self.anon=None
        self.smoke_exit=None

    def accounts(self,password):
        if not 12<=len(password)<=72:raise RuntimeError('DEMO_PASSWORD_LENGTH_12_TO_72')
        anon,service=self.local.local_keys()
        self.anon=anon
        operator=self.local.client(service)
        for role in ('admin','officer','normal'):
            email=f'gis-demo-{role}-{self.run}@example.invalid'
            user=operator.auth.admin.create_user({'email':email,'password':password,'email_confirm':True,
                'user_metadata':{'display_name':'Local Demo '+role}}).user
            self.users[role]={'email':email,'password':password,'id':str(user.id)}
        # Only the ID just returned by local Auth is elevated; no existing user
        # or password is modified and no user-supplied actor/role is accepted.
        self.local.sql("UPDATE public.profiles SET role='admin' WHERE id="+m.t2.t1.literal(self.users['admin']['id'])+"::uuid AND role='user'",role='postgres')

    def start(self, launchers=None):
        if launchers is None:launchers=(lambda:m.ContainerWorker(self.local,m.identity_module.provision(self.local)),
            lambda:p.p.m.LddContainer(self.local),lambda:p.GeoTiffContainer(self.local),
            lambda:p.p.ProcessingContainer(self.local))
        for launch in launchers:
            worker=launch();self.workers.append(worker)
            m.wait_for(lambda:worker.has('ready') or worker.has('fatal'),30)
            if not worker.has('ready'):raise RuntimeError('DEMO_WORKER_NOT_READY')
        sys.path.insert(0,str(REPO/'green-area-backend'))
        spec=importlib.util.spec_from_file_location('phase5_local_legacy',HERE/'legacy_demo.py')
        legacy=importlib.util.module_from_spec(spec);sys.modules[spec.name]=legacy;spec.loader.exec_module(legacy)
        import uvicorn
        self.server=uvicorn.Server(uvicorn.Config(legacy.create_app(self.local),
            host='127.0.0.1',port=55422,log_level='critical',access_log=False))
        self.thread=threading.Thread(target=self.server.run,daemon=True);self.thread.start()
        m.wait_for(lambda:self.server.started,20)
        env={k:v for k,v in os.environ.items() if k.upper() in {'PATH','SYSTEMROOT','SYSTEMDRIVE','TEMP','TMP','LOCALAPPDATA','APPDATA','USERPROFILE','COMSPEC','PATHEXT','PROGRAMFILES','PROGRAMFILES(X86)','PROGRAMW6432'}}
        env.update(GIS_UI_LOCAL='true',GIS_UI_LOCAL_ANON_KEY=self.anon)
        node=shutil.which('node')
        if not node:raise RuntimeError('NODE_UNAVAILABLE')
        self.vite=subprocess.Popen([node,str(REPO/'green-area-frontend/node_modules/vite/bin/vite.js'),
            '--config',str(HERE/'vite.config.mjs')],cwd=REPO/'green-area-frontend',env=env,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        def ready():
            if self.vite.poll() is not None:raise RuntimeError('DEMO_UI_START_FAILED')
            try:
                with socket.create_connection(('127.0.0.1',3000),timeout=.5):return True
            except OSError:return False
        m.wait_for(ready,30)
        self.env=env

    def grant_officer(self):
        import httpx
        admin=self.users['admin']
        session=self.local.client(self.anon).auth.sign_in_with_password({'email':admin['email'],'password':admin['password']}).session
        with httpx.Client(trust_env=False,follow_redirects=False,timeout=60) as client:
            response=client.post('http://127.0.0.1:55422/gis/officers',
                headers={'Authorization':'Bearer '+session.access_token,'Idempotency-Key':str(uuid4())},
                json={'user_id':self.users['officer']['id'],'reason':'New local demo account only'})
            if response.status_code!=200:raise RuntimeError('DEMO_OFFICER_BOOTSTRAP_FAILED')

    def smoke(self,node_modules):
        # No staging/production fixtures. Existing reviewed files are reused.
        fixture_root=self.local.db.runtime.root/'phase4/fixtures'
        manifest=json.loads((fixture_root/'manifest.json').read_text(encoding='utf-8'))
        for fixture in manifest['fixtures'].values():
            path=fixture_root/fixture['filename']
            if hashlib.sha256(path.read_bytes()).hexdigest()!=fixture['sha256']:raise RuntimeError('FIXTURE_DRIFT')
        year=self.local.sql("SELECT to_jsonb(y) FROM generate_series(1980,2026)y WHERE NOT EXISTS(SELECT 1 FROM gis.datasets WHERE province='Bangkok Metropolis' AND data_year=y) ORDER BY y LIMIT 1",read_only=True)
        period=self.local.sql("SELECT jsonb_build_object('year',y,'month',mon) FROM generate_series(2017,2026)y CROSS JOIN generate_series(1,12)mon WHERE NOT EXISTS(SELECT 1 FROM gis.processing_requests WHERE province='Bangkok Metropolis' AND data_year=y AND month=mon AND metric='ndvi') ORDER BY y DESC,mon DESC LIMIT 1",read_only=True)
        if year is None or period is None:raise RuntimeError('NO_UNUSED_DEMO_SCOPE')
        from gis_worker.provider import fixture_manifest
        payload={'users':self.users,'run':self.run,'year':year,'province':'Bangkok Metropolis','output':str(self.output),'repo':str(REPO),
            'fixture_root':str(fixture_root),'ldd_fixture':str(REPO/'green-area-backend/gis_worker/fixtures/ldd_valid.zip'),
            'processing_year':period['year'],'processing_month':period['month'],'native_manifest':fixture_manifest('t3-ldd-valid-v2')}
        env={**self.env,'GIS_TEST_NODE_MODULES':str(node_modules)}
        proc=subprocess.Popen([shutil.which('node'),str(HERE/'phase5_smoke.cjs')],cwd=REPO,env=env,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8')
        try:
            stdout,_=proc.communicate(json.dumps(payload)+'\n',timeout=600)
            self.smoke_exit=proc.returncode
            for line in stdout.splitlines():
                value=json.loads(line)
                if set(value)<={'rows','code','step'}:print(json.dumps(value),flush=True)
        except subprocess.TimeoutExpired:
            proc.kill();proc.communicate();self.smoke_exit=2

    def closing_baseline(self):
        """Read-only proof after shutdown. A failure is reported, never treated as a pass.

        Ctrl+C reaches every process in this console, so a docker client running at that
        moment can exit non-zero: try once more before reporting the check as failed.
        """
        for attempt in (1,2):
            try:return self.local.baseline()
            except Exception:
                if attempt==1:time.sleep(1)
        return None

    def close(self):
        errors=[]
        if self.vite is not None:
            self.vite.terminate()
            try:self.vite.wait(timeout=15)
            except subprocess.TimeoutExpired:errors.append('UI_STOP_FAILED')
        if self.server is not None:
            self.server.should_exit=True;self.thread.join(timeout=20)
            if self.thread.is_alive():errors.append('API_STOP_FAILED')
        for worker in reversed(self.workers):
            try:worker.close()
            except Exception:errors.append('OWNED_WORKER_STOP_FAILED')
        after=self.closing_baseline()
        checks={}
        if after is None:
            errors.append('BASELINE_CHECK_FAILED');checks['baseline_checked']=False
        else:
            for database,before in self.before.items():
                now=after[database]
                checks[database]={'ledger_unchanged':before['ledger']==now['ledger'],
                    'old_profiles_unchanged':all(now['profiles'].get(k)==v for k,v in before['profiles'].items()),
                    'public_legacy_unchanged':all(now['tables'].get(k)==v for k,v in before['tables'].items() if k!='profiles')}
        checks.update(source_unchanged=self.initial_source==source(),owned_workers_removed=not self.local.approved)
        report={'run':self.run,'smoke_exit':self.smoke_exit,'checks':checks,'cleanup_errors':errors,
            'source':self.initial_source,'passwords_or_tokens_persisted':False,'cloud_access':False,
            'cleanup':'Only owned workers/API/UI stopped; original files, test rows and core volumes retained'}
        (self.output/'local-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({'evidence':str(self.output),'smoke_exit':self.smoke_exit,'checks':checks,'cleanup_errors':errors}),flush=True)
        return not errors and all(all(v.values()) if isinstance(v,dict) else v for v in checks.values())


def wait_until_stopped(demo,stopped,grace=2):
    """Return on Ctrl+C; raise only if a component died and no Ctrl+C follows.

    Ctrl+C also reaches the UI and workers in this console, and they can exit before this
    process handles its own signal.
    """
    while not stopped.wait(.5):
        if demo.vite.poll() is not None or any(w.proc.poll() is not None for w in demo.workers):
            if stopped.wait(grace):return
            raise RuntimeError('DEMO_COMPONENT_STOPPED')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('core-start','core-stop','start','smoke'))
    parser.add_argument('--runtime-dir',type=Path,required=True)
    parser.add_argument('--node-modules',type=Path)
    args=parser.parse_args();logging.disable(logging.CRITICAL)
    if args.action in ('core-start','core-stop'):
        local=local_target(args.runtime_dir)
        if args.action=='core-start':local.db.resume();local.attest()
        else:local.db.runtime.verify_containers();local.db.runtime.stop()
        print(json.dumps({'action':args.action,'owned_local_only':True,'volumes_preserved':True}));return 0
    if args.action=='start' and not sys.stdin.isatty():raise RuntimeError('INTERACTIVE_TERMINAL_REQUIRED')
    password=secrets.token_urlsafe(24) if args.action=='smoke' else getpass.getpass('New local demo password (12-72 characters; hidden, not saved): ')
    demo=Demo(args.runtime_dir)
    stopped=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stopped.set())
    try:
        demo.accounts(password);demo.start()
        if args.action=='smoke':
            if args.node_modules is None:raise RuntimeError('BUNDLED_PLAYWRIGHT_PATH_REQUIRED')
            demo.smoke(args.node_modules)
        else:
            demo.grant_officer()
            print('Local demo: http://127.0.0.1:3000/?view=gis | API http://127.0.0.1:55422',flush=True)
            print(json.dumps({'local_test_accounts':{role:{'email':u['email'],'id':u['id']} for role,u in demo.users.items()},
                'password':'Use the password entered above; it is never displayed or stored'}),flush=True)
            print('Ctrl+C: stop owned API/UI/workers; keep all data and core services.',flush=True)
            wait_until_stopped(demo,stopped)
    finally:
        safe=demo.close()
    return 0 if safe and (args.action!='smoke' or demo.smoke_exit==0) else 1


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:print(json.dumps({'ok':False,'code':'LOCAL_DEMO_FAILED'}));raise SystemExit(1)
