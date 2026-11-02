"""Local Linux worker; private stdin Auth session, bounded credential-free child."""
from __future__ import annotations
import base64, ctypes, json, os, re, signal, subprocess, sys, tempfile, threading, time
from pathlib import Path
from urllib import request as http, error as http_error
from uuid import UUID
HERE=Path(__file__).resolve().parent
LOCAL_URL='http://green-area-gis-t0-gateway:8000'
ISSUER='http://127.0.0.1:55421/auth/v1'
INFRA={'TRANSIENT_SYNTHETIC','NATIVE_TIMEOUT','NATIVE_MEMORY_LIMIT','NATIVE_PROCESS_FAILED','WORKER_SHUTDOWN','NATIVE_OUTPUT_LIMIT'}
class WorkerError(RuntimeError): pass

def event(name,**safe):
    print(json.dumps({'event':name,**safe},separators=(',',':')),flush=True)

class NoRedirect(http.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): raise WorkerError('WORKER_REDIRECT_REJECTED')

class LocalWorkerClient:
    RPC_NAMES=('gis_worker_v2','gis_worker_readiness_v2')
    def __init__(self,b):
        keys={'api_url','subject','anon_key','access_token','refresh_token','runtime_instance','baseline_fingerprint'}
        if not isinstance(b,dict) or set(b)!=keys or b['api_url']!=LOCAL_URL: raise WorkerError('WORKER_TARGET_REJECTED')
        self.subject=str(UUID(b['subject']))
        self.expected={k:b[k] for k in ('runtime_instance','baseline_fingerprint')}
        if not re.fullmatch('[a-f0-9]{32}',b['runtime_instance']) or not re.fullmatch('[a-f0-9]{64}',b['baseline_fingerprint']): raise WorkerError('WORKER_TARGET_REJECTED')
        self._anon,self._access,self._refresh=b['anon_key'],b['access_token'],b['refresh_token']
        self._lock=threading.RLock()
        self._opener=http.build_opener(http.ProxyHandler({}),NoRedirect())
        self._claims(self._access)
    def _claims(self,token):
        try:
            part=token.split('.')[1]; c=json.loads(base64.urlsafe_b64decode(part+'='*(-len(part)%4)))
            if c['sub']!=self.subject or c['role']!='gis_native_worker' or c['iss']!=ISSUER or type(c['exp']) is not int: raise ValueError()
            return c
        except Exception: raise WorkerError('WORKER_IDENTITY_REJECTED') from None
    def _request(self,path,payload,access):
        if path not in tuple('/rest/v1/rpc/'+name for name in self.RPC_NAMES)+('/auth/v1/token?grant_type=refresh_token',): raise WorkerError('WORKER_RPC_REJECTED')
        raw=json.dumps(payload,allow_nan=False,separators=(',',':')).encode()
        if len(raw)>65536: raise WorkerError('WORKER_REQUEST_LIMIT')
        req=http.Request(LOCAL_URL+path,data=raw,method='POST',headers={'apikey':self._anon,'Authorization':'Bearer '+access,'Content-Type':'application/json'})
        try:
            with self._opener.open(req,timeout=5) as r: value=r.read(65537)
            if len(value)>65536: raise WorkerError('WORKER_RESPONSE_LIMIT')
            return json.loads(value)
        except http_error.HTTPError as e:
            try: code=json.loads(e.read(2048)).get('message','')
            except Exception: code=''
            raise WorkerError(code if re.fullmatch('GIS_[A-Z0-9_]+',code) else 'WORKER_HTTP_DENIED') from None
        except (OSError,ValueError): raise WorkerError('WORKER_TRANSPORT_FAILED') from None
    def call(self,name,payload):
        if name not in self.RPC_NAMES: raise WorkerError('WORKER_RPC_REJECTED')
        with self._lock:
            if self._claims(self._access)['exp']-time.time()<60:
                r=self._request('/auth/v1/token?grant_type=refresh_token',{'refresh_token':self._refresh},self._access)
                self._claims(r['access_token']); self._access,self._refresh=r['access_token'],r['refresh_token']
            access=self._access
        return self._request('/rest/v1/rpc/'+name,payload,access)

class GisWorker:
    CHILD_SCRIPT='native_child.py'
    def __init__(self,client):
        self.client=client; self._stop_event=threading.Event(); self._lease_lost=threading.Event()
    def stop(self,*_): self._stop_event.set()
    def readiness(self):
        r=self.client.call('gis_worker_readiness_v2',{})
        if (not isinstance(r,dict) or r.get('status')!='ready' or r.get('worker_role')!='gis_native_worker'
            or r.get('subject')!=self.client.subject or r.get('database_name')!='postgres' or r.get('cluster_name')!='green-area-gis-t0'
            or r.get('contract_version')!='1.3.0-t3-remediation' or not {27,28,29,30,31,32,33}<=set(r.get('migration_versions',[]))
            or any(r.get(k)!=v for k,v in self.client.expected.items())): raise WorkerError('WORKER_TARGET_REJECTED')
        return r
    def call(self,action,payload=None):
        self.readiness()
        return self.client.call('gis_worker_v2',{'p_action':action,'p_payload':payload or {}})
    def build_native_request(self,job):
        return {'fixture_id':job['manifest']['fixture_id'],'manifest':job['manifest'],'input_hash':job['input_hash'],'input_revision':job['input_revision'],'attempt_number':job['attempt_number']}
    def failure_report(self,request,code):
        from gis_worker.provider import report_failure
        return report_failure(request,code)
    def _execute_native(self,request,timeout=25):
        report_failure=self.failure_report
        if sys.platform!='linux': raise WorkerError('LINUX_WORKER_REQUIRED')
        clean={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','GDAL_NUM_THREADS':'1'}
        with tempfile.TemporaryFile(dir='/tmp') as output:
            proc=subprocess.Popen([sys.executable,'-I','-B',str(HERE/self.CHILD_SCRIPT)],stdin=subprocess.PIPE,stdout=output,stderr=subprocess.DEVNULL,env=clean,close_fds=True,start_new_session=True)
            try:
                proc.stdin.write(json.dumps(request,allow_nan=False).encode());proc.stdin.close()
                deadline=time.monotonic()+timeout; code=None
                while proc.poll() is None:
                    if self._lease_lost.is_set(): raise WorkerError('GIS_STALE_LEASE')
                    if self._stop_event.is_set(): code='WORKER_SHUTDOWN';break
                    if time.monotonic()>=deadline: code='NATIVE_TIMEOUT';break
                    time.sleep(.1)
                if code: return report_failure(request,code)
                if proc.returncode: return report_failure(request,'NATIVE_MEMORY_LIMIT' if proc.returncode==-9 else 'NATIVE_PROCESS_FAILED')
                output.seek(0);raw=output.read(16385)
                if len(raw)>16384:return report_failure(request,'NATIVE_OUTPUT_LIMIT')
                result=json.loads(raw)
                if not isinstance(result,dict):raise ValueError()
                return result
            except (ValueError,OSError):return report_failure(request,'NATIVE_PROCESS_FAILED')
            finally:
                if proc.poll() is None:
                    try:os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                proc.wait(timeout=5)
    def process_job(self,job):
        self._lease_lost.clear()
        request=self.build_native_request(job)
        lease={'job_id':job['id'],'lease_token':job['lease_token']}
        stop=threading.Event()
        def heartbeat():
            progress=5
            while not stop.wait(5):
                progress=min(90,progress+5)
                try:self.call('heartbeat',{**lease,'progress':progress});event('heartbeat',job_id=job['id'])
                except Exception:self._lease_lost.set();return
        thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
        try:
            report=self._execute_native(request)
            stop.set();thread.join(timeout=11)
            if self._lease_lost.is_set() or thread.is_alive():raise WorkerError('GIS_STALE_LEASE')
            result=self.call('fail',{**lease,'error_code':'transient','report':report}) if report.get('error_code') in INFRA else self.call('complete',{**lease,'report':report})
            event('finished',job_id=job['id'],state=result.get('state'),error_code=report.get('error_code'));return result
        finally:stop.set();thread.join(timeout=11)
    def run(self):
        self.readiness();event('ready')
        while not self._stop_event.is_set():
            try:
                self.call('recover')
                if self._stop_event.is_set():break
                job=self.call('claim').get('job')
                if not job:self._stop_event.wait(.5);continue
                event('claimed',job_id=job['id']);self.process_job(job)
            except Exception as e:
                code=str(e) if isinstance(e,WorkerError) else 'WORKER_CYCLE_FAILED'
                event('cycle_failed',error_code=code if re.fullmatch('(?:GIS|WORKER)_[A-Z0-9_]+',code) else 'WORKER_CYCLE_FAILED');self._stop_event.wait(1)
        event('stopped')

def main(client_class=LocalWorkerClient,worker_class=GisWorker):
    if sys.platform!='linux':raise WorkerError('LINUX_WORKER_REQUIRED')
    if ctypes.CDLL(None,use_errno=True).prctl(4,0,0,0,0)!=0:raise WorkerError('WORKER_PROCESS_ISOLATION_FAILED')
    sys.path.insert(0,str(HERE.parent));raw=sys.stdin.buffer.readline(32769)
    if len(raw)>32768 or not raw.endswith(b'\n'):raise WorkerError('WORKER_BOOTSTRAP_REJECTED')
    client=client_class(json.loads(raw));del raw
    worker=worker_class(client);signal.signal(signal.SIGTERM,worker.stop);signal.signal(signal.SIGINT,worker.stop);worker.run()
if __name__=='__main__':
    try:main()
    except Exception as error:
        code=str(error) if isinstance(error,WorkerError) else ''
        event('fatal',error_code=code if re.fullmatch('(?:GIS|WORKER)_[A-Z0-9_]+',code) else 'WORKER_STARTUP_FAILED')
        raise SystemExit(1)
