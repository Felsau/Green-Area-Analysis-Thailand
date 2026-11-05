"""Focused Local stop/expiry/error boundaries; new synthetic clocks only.

Never changes timestamps of existing records. Not a 20-minute elapsed test.
"""
from datetime import date
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import secrets
import sys
import time
from uuid import uuid4

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('a64d1_boundaries_local',HERE/'gee_safety_local.py')
p=importlib.util.module_from_spec(spec);sys.modules[spec.name]=p;spec.loader.exec_module(p)
from gis_worker.gee_execution_safety import report
from gis_worker.gee_live_contracts import queue_report
from gis_worker.gee_safety_worker import RehearsalWorker
from gis_worker.worker import WorkerError


def check(local):
    local.proof();quote=p.p.p.m.t2.t1.literal;rows=[]
    source=[Path(__file__),HERE/'gee_safety_local.py',p.MIGRATION,*(p.REPO/'green-area-backend/gis_worker').glob('*.py')]
    fingerprint={f.relative_to(p.REPO).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in source}
    path=local.output/('boundaries-'+uuid4().hex[:12])
    def record(name,ok):
        row={'name':name,'status':'Pass' if ok else 'Fail'};rows.append(row);print(json.dumps(row),flush=True)
        with path.with_suffix('.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row)+'\n')
        if not ok:raise AssertionError(name)
    def denied(name,fn,code):
        try:fn()
        except Exception as e:record(name,getattr(e,'code',None)=='P0001' and code in getattr(e,'message',str(e)))
        else:record(name,False)
    anon,service=local.local_keys();operator=local.client(service)
    def user(role):
        pw=secrets.token_urlsafe(30);created=operator.auth.admin.create_user({'email':'a64d1-boundary-'+uuid4().hex+'@example.invalid','password':pw,'email_confirm':True,'role':role})
        client=local.client(anon);client.auth.sign_in_with_password({'email':created.user.email,'password':pw});return str(created.user.id),client
    actor,_=user('authenticated');subject,client=user('gis_gee_safety_worker');local.sql('INSERT INTO gis.officers(user_id) VALUES('+quote(actor)+')')
    def rpc(action,payload=None):return client.rpc('gis_gee_safety_worker',{'p_action':action,'p_payload':payload or {}}).execute().data
    def register():
        req,geometry,raw=p.p.fixture(uuid4().hex[:12]);v=p.p.registered_input(req,geometry)
        iid=local.sql('INSERT INTO gis.gee_live_inputs(value) VALUES('+quote(json.dumps(v))+'::jsonb) RETURNING to_jsonb(id)')
        output=p.p.InjectedBridge(sdk=p.p.InjectedSDK(),transport=p.p.InjectedTransport(raw),authorization=lambda:req.project,as_of=date(2026,1,1)).compute(req,geometry)
        return iid,output
    def session(old=False):
        if not old:return local.sql('SELECT to_jsonb(gis.safety_session('+quote(actor)+','+quote(subject)+'))')
        # Fresh fixture born 19m30s old, immutable header, about30s remaining.
        return local.sql("WITH v AS(SELECT clock_timestamp()-interval '19 minutes 30 seconds' t,gis.safety_policy() p) INSERT INTO gis.gee_safety_sessions(actor_id,bound_worker,policy,policy_sha256,started_at,ends_at) SELECT "+quote(actor)+','+quote(subject)+",p,encode(sha256(convert_to(gis.gee_live_canonical(p),'UTF8')),'hex'),t,t+interval '20 minutes' FROM v RETURNING to_jsonb(id)")
    def enqueue(sid,item):return local.sql('SELECT gis.safety_enqueue('+quote(actor)+',gen_random_uuid(),'+quote(item[0])+','+quote(sid)+')')
    def lease(job):return {'job_id':job['id'],'lease_token':job['lease_token']}
    def reserve(job):return rpc('reserve',lease(job)|{'request_key':str(uuid4()),'kind':'compute'})
    def failure(job):return report(job,queue_report(job,infrastructure_error='WORKER_SHUTDOWN'),failure_kind='transient')
    item=register();sid=session();enqueue(sid,item);job=rpc('claim')['job'];a=reserve(job);b=reserve(job)
    rpc('attempted',lease(job)|{'request_id':a['request_id']})
    record('active_operator_stop',rpc('stop',{'session_id':sid})['state']=='stopped')
    good=report(job,queue_report(job,item[1]),[a['request_id'],b['request_id']])
    operations={'reserve':lambda:reserve(job),'attempted':lambda:rpc('attempted',lease(job)|{'request_id':b['request_id']}),
        'finished':lambda:rpc('finished',lease(job)|{'request_id':a['request_id'],'evidence_sha256':item[1].content.evidence_sha256}),
        'heartbeat':lambda:rpc('heartbeat',lease(job)|{'progress':10}),
        'complete':lambda:rpc('complete',lease(job)|{'report':good})}
    for name,fn in operations.items():denied('active_stop_fences_'+name,fn,'GIS_SAFETY_SESSION_CLOSED')
    record('active_stop_allows_uncertain',rpc('uncertain',lease(job)|{'request_id':a['request_id']})['state']=='uncertain')
    record('active_stop_terminal_cleanup',rpc('fail',lease(job)|{'error_code':'transient','report':failure(job)})['state']=='failed')
    record('stop_retains_all_charges',local.sql('SELECT jsonb_build_array(count(*),bool_and(state=\'uncertain\')) FROM gis.gee_safety_requests WHERE session_id='+quote(sid),read_only=True)==[2,True])
    item=register();sid=session(old=True);enqueue(sid,item);job=rpc('claim')['job'];a=reserve(job)
    rpc('attempted',lease(job)|{'request_id':a['request_id']})
    remaining=local.sql('SELECT to_jsonb(greatest(0,extract(epoch FROM ends_at-clock_timestamp()))) FROM gis.gee_safety_sessions WHERE id='+quote(sid),read_only=True)
    print(json.dumps({'event':'fresh_near_expiry_fixture_clock_boundary','seconds_remaining':remaining}),flush=True)
    deadline=time.monotonic()+float(remaining)+1
    while time.monotonic()<deadline:time.sleep(min(1,deadline-time.monotonic()))
    denied('20min_window_fences_reserve',lambda:reserve(job),'GIS_SAFETY_SESSION_CLOSED')
    denied('20min_window_fences_heartbeat',lambda:rpc('heartbeat',lease(job)|{'progress':10}),'GIS_SAFETY_SESSION_CLOSED')
    record('20min_window_terminal_no_retry',rpc('fail',lease(job)|{'error_code':'transient','report':failure(job)})['state']=='failed')
    record('20min_window_charges_retained',local.sql("SELECT jsonb_build_array(count(*),bool_and(state='uncertain')) FROM gis.gee_safety_requests WHERE session_id="+quote(sid),read_only=True)==[1,True])
    record('20min_window_cannot_claim_again',rpc('claim')['job'] is None)
    #Fresh logical job/attempt born old; no historical attempt UPDATE.
    item=register();sid=session();created=enqueue(sid,item);token=str(uuid4())
    local.sql("UPDATE gis.jobs SET state='running',attempt_count=1,worker_id="+quote(subject)+',lease_token='+quote(token)+",lease_until=clock_timestamp()+interval '60 seconds' WHERE id="+quote(created['job_id'])+";INSERT INTO gis.attempts(job_id,attempt_no,worker_id,lease_token,state,started_at) VALUES("+quote(created['job_id'])+',1,'+quote(subject)+','+quote(token)+",'running',clock_timestamp()-interval '181 seconds')")
    job=local.sql("SELECT gis.gee_live_claim_packet(id)||jsonb_build_object('input_hash',input_hash,'input_revision',input_revision) FROM gis.jobs WHERE id="+quote(created['job_id']),read_only=True)|{'id':created['job_id'],'lease_token':token,'session_id':sid,'policy_sha256':local.sql('SELECT to_jsonb(policy_sha256) FROM gis.gee_safety_sessions WHERE id='+quote(sid),read_only=True)}
    denied('synthetic_180s_boundary_exact_reserve_error',lambda:reserve(job),'GIS_SAFETY_JOB_TIMEOUT')
    denied('synthetic_180s_boundary_exact_heartbeat_error',lambda:rpc('heartbeat',lease(job)|{'progress':10}),'GIS_SAFETY_JOB_TIMEOUT')
    rpc('stop',{'session_id':sid});rpc('fail',lease(job)|{'error_code':'transient','report':failure(job)})
    #Latest Python mapping + realJWT/SQL result path, separate from injected child tests.
    item=register();sid=session();enqueue(sid,item)
    class Client:
        expected={'runtime_instance':local.db.instance,'baseline_fingerprint':p.p.p.m.t2.t1.legacy_fingerprint()}
        def __init__(self):self.subject=subject
        def call(self,name,payload):return client.rpc(name,payload).execute().data
    class Port:
        OFFLINE_INJECTED=True
        def evaluate(self,*,timeout_seconds):return item[1]
    worker=RehearsalWorker(Client(),injected_port=lambda _:Port());job=worker.call('claim')['job']
    record('latest_worker_real_auth_result',worker.process_job(job)['state']=='succeeded')
    rpc('stop',{'session_id':sid})
    item=register();sid=session();enqueue(sid,item)
    class StoppedPort:
        OFFLINE_INJECTED=True
        def evaluate(self,*,timeout_seconds):raise WorkerError('WORKER_SHUTDOWN')
    worker=RehearsalWorker(Client(),injected_port=lambda _:StoppedPort());job=worker.call('claim')['job']
    record('latest_worker_shutdown_safe_retry',worker.process_job(job)['state']=='queued')
    value=local.sql('SELECT validation_report FROM gis.attempts WHERE job_id='+quote(job['id']),read_only=True)
    record('latest_worker_preserves_shutdown_reason',value['error_code']=='WORKER_SHUTDOWN' and value['failure_kind']=='transient')
    rpc('stop',{'session_id':sid});rpc('recover')
    record('source_fingerprint_stable',all(hashlib.sha256((p.REPO/name).read_bytes()).hexdigest()==sha for name,sha in fingerprint.items()))
    result={'passed':len(rows),'failed':0,'rows':rows,'source':fingerprint,'real_local_auth_sql':True,'observations':'injected','google_access':False,'twenty_minute_full_wait':False,'synthetic_aged_session_attempt':True}
    path.with_suffix('.json').write_text(json.dumps(result,indent=2),encoding='utf-8');return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--runtime-dir',type=Path,required=True);args=parser.parse_args()
    for name in ('httpx','httpcore','supabase_auth','postgrest'):logging.getLogger(name).setLevel(logging.CRITICAL)
    def network(event,args):
        if event=='socket.connect' and (not isinstance(args[1],tuple) or args[1][0] not in ('127.0.0.1','::1')):raise RuntimeError('A64D1_EXTERNAL_NETWORK_FORBIDDEN')
        if event=='socket.getaddrinfo' and args[0] not in ('127.0.0.1','::1','localhost',b'127.0.0.1',b'::1'):raise RuntimeError('A64D1_EXTERNAL_DNS_FORBIDDEN')
    sys.addaudithook(network);result=check(p.SafetyLocal(args.runtime_dir));print(json.dumps({'passed':result['passed'],'failed':result['failed']}))
