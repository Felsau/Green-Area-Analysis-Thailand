"""Actual Local JWT/SQL accounting tests; observations are injected, never Google."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
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
spec=importlib.util.spec_from_file_location('a64d1_checks_local',HERE/'gee_safety_local.py')
p=importlib.util.module_from_spec(spec);sys.modules[spec.name]=p;spec.loader.exec_module(p)
from gis_worker.gee_execution_safety import AccountedTransport, report
from gis_worker.gee_live_contracts import registered_input,queue_report,canonical,digest
from gis_worker.gee_live_injected import fixture,InjectedSDK,InjectedTransport
from gis_worker.gee_live_bridge import InjectedBridge
from gis_worker.gee_safety_worker import RehearsalWorker


def check(local):
    local.proof();seed=uuid4().hex[:12];path=local.output/('checks-'+seed)
    sources=[Path(__file__),HERE/'gee_safety_local.py',p.MIGRATION,
        *(p.REPO/'green-area-backend/gis_worker'/name for name in ('gee_execution_safety.py','gee_safety_worker.py','gee_safety_child.py','gee_live_contracts.py','gee_live_bridge.py','worker.py'))]
    fingerprint={f.relative_to(p.REPO).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in sources}
    path.with_suffix('.source.json').write_text(json.dumps(fingerprint,indent=2),encoding='utf-8')
    rows=[]
    def record(name,ok):
        row={'name':name,'status':'Pass' if ok else 'Fail'};rows.append(row)
        with path.with_suffix('.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row)+'\n')
        print(json.dumps(row),flush=True)
        if not ok:raise AssertionError(name)
    def denied(name,fn):
        try:fn()
        except Exception as error:record(name,str(getattr(error,'code','')) in ('P0001','42501','23514','PGRST106','PGRST205','22003'))
        else:record(name,False)
    def sql_denied(name,body):
        value=local.sql(body,check=False);record(name,value.returncode!=0 and ('GIS_' in value.stderr or 'permission denied' in value.stderr))
    def wait(fn,timeout=85):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            value=fn()
            if value:return value
            time.sleep(.5)
        raise RuntimeError('A64D1_LOCAL_WAIT_EXPIRED')
    quote=p.p.p.m.t2.t1.literal
    anon,service=local.local_keys();operator=local.client(service)
    def user(role):
        pw=secrets.token_urlsafe(30)
        created=operator.auth.admin.create_user({'email':'a64d1-'+uuid4().hex+'@example.invalid','password':pw,'email_confirm':True,'role':role})
        client=local.client(anon);session=client.auth.sign_in_with_password({'email':created.user.email,'password':pw}).session
        if session is None:raise RuntimeError('LOCAL_AUTH_REQUIRED')
        return str(created.user.id),client
    actor,normal=user('authenticated');local.sql('INSERT INTO gis.officers(user_id) VALUES('+quote(actor)+')')
    workers=[user('gis_gee_safety_worker') for _ in range(2)]
    def rpc(action,payload=None,index=0):return workers[index][1].rpc('gis_gee_safety_worker',{'p_action':action,'p_payload':payload or {}}).execute().data
    for i,(subject,client) in enumerate(workers):
        ready=client.rpc('gis_gee_safety_readiness',{}).execute().data
        record('trusted_jwt_subject_'+str(i),ready['subject']==subject and ready['live_enabled'] is False)
    denied('normal_cannot_call_safety',lambda:normal.rpc('gis_gee_safety_worker',{'p_action':'claim'}).execute())
    denied('service_cannot_call_safety',lambda:operator.rpc('gis_gee_safety_worker',{'p_action':'claim'}).execute())
    denied('payload_worker_spoof',lambda:rpc('claim',{'worker_id':workers[1][0]}))
    for name in ('gis_worker_v2','gis_gee_mock_worker','gis_gee_live_worker','gis_processing_worker'):
        denied('worker_denied_'+name,lambda n=name:workers[0][1].rpc(n,{'p_action':'claim','p_payload':{}}).execute())
    denied('worker_admin_denied',lambda:workers[0][1].rpc('gis_command',{'p_actor':actor,'p_request_id':str(uuid4()),'p_operation':'grant_officer','p_payload':{},'p_backend_sandbox':False}).execute())
    denied('worker_private_table_denied',lambda:workers[0][1].schema('gis').table('gee_safety_sessions').select('*').execute())
    denied('worker_legacy_write_denied',lambda:workers[0][1].table('ndvi_annual').update({'ndvi_mean':0}).eq('id',0).execute())
    for action in ('live','live_compute','live_complete'):
        denied(action+'_always_disabled',lambda a=action:rpc(a))
    for db in p.p.p.DATABASES:
        acl=local.sql("SELECT jsonb_build_object('rpc',(SELECT jsonb_agg(p.proname ORDER BY p.proname) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prorettype<>'trigger'::regtype AND has_function_privilege('gis_gee_safety_worker',p.oid,'EXECUTE')),'rls',(SELECT bool_and(relrowsecurity AND relforcerowsecurity AND NOT has_table_privilege('gis_gee_safety_worker',c.oid,'SELECT,INSERT,UPDATE,DELETE')) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='gis' AND c.relkind='r' AND c.relname LIKE 'gee_safety_%'))",db,read_only=True)
        record(db+'_least_privilege_rls',acl=={'rpc':['gis_gee_safety_readiness','gis_gee_safety_worker'],'rls':True})
    sessions=[]
    def session():
        sid=local.sql('SELECT to_jsonb(gis.safety_session('+quote(actor)+','+quote(workers[0][0])+'))');sessions.append(sid);return sid
    def register(product='ndvi',scenario='candidate',month=0):
        request,geometry,raw=fixture(uuid4().hex[:12],product=product,scenario=scenario,month=month)
        value=registered_input(request,geometry)
        iid=local.sql('INSERT INTO gis.gee_live_inputs(value) VALUES('+quote(json.dumps(value))+'::jsonb) RETURNING to_jsonb(id)')
        output=InjectedBridge(sdk=InjectedSDK(),transport=InjectedTransport(raw),authorization=lambda:request.project,as_of=date(2026,1,1)).compute(request,geometry)
        return iid,output
    def enqueue(sid,item,key=None):return local.sql('SELECT gis.safety_enqueue('+quote(actor)+','+quote(key or str(uuid4()))+','+quote(item[0])+','+quote(sid)+')')
    def state(jid):return local.sql("SELECT jsonb_build_object('job',to_jsonb(j),'requests',(SELECT jsonb_agg(to_jsonb(r) ORDER BY reserved_at) FROM gis.gee_safety_requests r WHERE r.job_id=j.id),'attempts',(SELECT jsonb_agg(to_jsonb(a) ORDER BY attempt_no) FROM gis.attempts a WHERE a.job_id=j.id),'candidate',(SELECT to_jsonb(c) FROM gis.gee_live_candidates c WHERE c.job_id=j.id)) FROM gis.jobs j WHERE id="+quote(jid),read_only=True)
    def lease(job):return {'job_id':job['id'],'lease_token':job['lease_token']}
    def reserve(job,key=None):return rpc('reserve',lease(job)|{'request_key':key or str(uuid4()),'kind':'compute'})
    def fail(job):return rpc('fail',lease(job)|{'error_code':'transient','report':report(job,queue_report(job,infrastructure_error='NATIVE_TIMEOUT'),failure_kind='request_timeout')})
    class Port:
        OFFLINE_INJECTED=True
        def __init__(self,output):self.output=output
        def evaluate(self,*,timeout_seconds):return self.output
    def good_report(job,item):
        t=AccountedTransport(rpc,job);out,receipt=t.execute(Port(item[1]));return t.report(out,[receipt])
    sid=session();item=register();key=str(uuid4());created=enqueue(sid,item,key)
    record('same_and_new_idempotency_key_reuse_logical_job',enqueue(sid,item,key)==created and enqueue(sid,item)==created)
    record('other_subject_cannot_claim_bound_job',rpc('claim',index=1)['job'] is None)
    with ThreadPoolExecutor(max_workers=2) as pool:claims=list(pool.map(lambda _:rpc('claim')['job'],range(2)))
    record('concurrent_claim_once',sum(j is not None for j in claims)==1);job=next(j for j in claims if j)
    good=good_report(job,item)
    denied('other_subject_cannot_complete',lambda:rpc('complete',lease(job)|{'report':good},index=1))
    denied('stale_token_denied',lambda:rpc('complete',lease(job)|{'lease_token':str(uuid4()),'report':good}))
    for field in ('protocol','policy_sha256','session_id','receipts'):
        bad=deepcopy(good);bad[field]=[] if field=='receipts' else str(uuid4()) if field=='session_id' else '0'*64
        denied('wrong_'+field,lambda b=bad:rpc('complete',lease(job)|{'report':b}))
    for field in ('project','scope','statistics','method'):
        bad=deepcopy(good);c=bad['base']['output']['content']
        if field=='project':c['evidence']['project']['project_number']='999999999999'
        elif field=='scope':c['geometry_sha256']='0'*64
        elif field=='statistics':c['statistics']['mean']=.9
        else:c['evidence']['method']['reduction_scale_m']=10
        bad['base']['evidence_canonical']=canonical(c['evidence']);c['evidence_sha256']=digest(c['evidence'])
        bad['base']['output_canonical']=canonical(c);bad['base']['output']['output_sha256']=digest(c)
        denied('forged_'+field,lambda b=bad:rpc('complete',lease(job)|{'report':b}))
    with ThreadPoolExecutor(max_workers=2) as pool:done=list(pool.map(lambda _:rpc('complete',lease(job)|{'report':good}),range(2)))
    record('concurrent_complete_single_result',all(r['state']=='succeeded' for r in done) and sum(r.get('replayed',False) for r in done)==1)
    saved=state(job['id']);record('candidate_exact_injected_output',saved['candidate']['output']==item[1].model_dump(mode='json'))
    record('candidate_never_eligible_or_publishable',local.sql('SELECT jsonb_build_array(gis.eligible('+quote(job['edition_id'])+','+quote(job['dataset_id'])+'),gis.publication_ready('+quote(job['edition_id'])+','+quote(job['dataset_id'])+'))',read_only=True)==[False,False])
    sql_denied('immutable_candidate','UPDATE gis.gee_live_candidates SET output=output WHERE job_id='+quote(job['id']))
    sql_denied('immutable_reservation','DELETE FROM gis.gee_safety_requests WHERE job_id='+quote(job['id']))
    sql_denied('immutable_session_header','UPDATE gis.gee_safety_sessions SET ends_at=ends_at+interval \'1 minute\' WHERE id='+quote(sid))
    for product,scenario in [('lst','candidate'),('ndvi','zero'),('lst','no_data')]:
        item=register(product,scenario);created=enqueue(sid,item);job=rpc('claim')['job']
        result=rpc('complete',lease(job)|{'report':good_report(job,item)})
        record(product+'_'+scenario,result['state']==('succeeded' if scenario!='no_data' else 'failed'))
    sql_denied('fifth_job_denied_new_key','SELECT gis.safety_enqueue('+quote(actor)+',gen_random_uuid(),'+quote(register()[0])+','+quote(sid)+')')
    #32 concurrent durable reservations, no browser/worker-local counter.
    sid=session();item=register();enqueue(sid,item);job=rpc('claim')['job'];request_key=str(uuid4())
    a=reserve(job,request_key);b=reserve(job,request_key)
    record('reserve_idempotency_no_new_slot',a['request_id']==b['request_id'])
    rpc('attempted',lease(job)|{'request_id':a['request_id']})
    denied('attempted_replay_cannot_compute_again',lambda:rpc('attempted',lease(job)|{'request_id':a['request_id']}))
    rpc('uncertain',lease(job)|{'request_id':a['request_id']})
    with ThreadPoolExecutor(max_workers=4) as pool:reservations=list(pool.map(lambda _:reserve(job),range(31)))
    record('concurrent_budget_32_exact',len(state(job['id'])['requests'])==32)
    record('request_33_durably_exhausts',reserve(job).get('granted') is False)
    denied('exhausted_blocks_heartbeat',lambda:rpc('heartbeat',lease(job)|{'progress':10}))
    record('exhaustion_stops_retry',fail(job)['state']=='failed')
    record('uncertain_never_refunded',all(r['state']=='uncertain' for r in state(job['id'])['requests']))
    #Stop queued sessions under concurrent recover, checking the narrow guard.
    stopped=[]
    for _ in range(2):
        s=session();jobs=[enqueue(s,register())['job_id'] for _ in range(2)];rpc('stop',{'session_id':s});stopped+=jobs
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:rpc('recover'),range(2)))
    rpc('recover');record('stopped_queued_finalized_no_deadlock',all(state(j)['job']['state']=='failed' for j in stopped))
    #Real lease expiry/replacement. Outstanding attempt is permanently uncertain.
    sid=session();item=register();enqueue(sid,item);old=rpc('claim')['job'];r=reserve(old)
    rpc('attempted',lease(old)|{'request_id':r['request_id']})
    print(json.dumps({'event':'actual_60s_lease_expiry_wait'}),flush=True)
    wait(lambda:rpc('recover')['recovered']==1)
    denied('expired_old_token_reserve_denied',lambda:reserve(old))
    replacement=wait(lambda:rpc('claim')['job']);record('replacement_does_not_reset_attempt',replacement['attempt_number']==2 and replacement['id']==old['id'])
    before=state(old['id']);record('recovery_retains_spent_uncertain_slot',len(before['requests'])==1 and before['requests'][0]['state']=='uncertain')
    denied('stale_after_recovery_completion_denied',lambda:rpc('complete',lease(old)|{'report':good_report(replacement,item)}))
    record('second_failure_terminal',fail(replacement)['state']=='failed' and len(state(old['id'])['attempts'])==2)
    #Actual 120s request and 180s logical deadline across a retry, with heartbeats.
    sid=session();item=register();enqueue(sid,item);first=rpc('claim')['job'];fail(first)
    job=wait(lambda:rpc('claim')['job']);r=reserve(job);rpc('attempted',lease(job)|{'request_id':r['request_id']})
    start=time.monotonic();request_done=False;heartbeats=0
    print(json.dumps({'event':'actual_120s_request_180s_logical_job_wait'}),flush=True)
    while time.monotonic()-start<184:
        time.sleep(5)
        if not request_done and time.monotonic()-start>=121:
            finished=rpc('finished',lease(job)|{'request_id':r['request_id'],'evidence_sha256':item[1].content.evidence_sha256})
            record('real_120s_request_becomes_uncertain',finished['state']=='uncertain');request_done=True
        try:rpc('heartbeat',lease(job)|{'progress':min(90,heartbeats+1)});heartbeats+=1
        except Exception as error:
            record('real_180s_exact_job_timeout',getattr(error,'message','')=='GIS_SAFETY_JOB_TIMEOUT')
            break
    record('logical_deadline_not_reset_on_retry',time.monotonic()-start<180 and heartbeats>20)
    denied('logical_deadline_blocks_new_reservation',lambda:reserve(job))
    denied('logical_deadline_blocks_heartbeat',lambda:rpc('heartbeat',lease(job)|{'progress':90}))
    fail(job);record('deadline_final_failure_keeps_history',state(job['id'])['job']['state']=='failed' and len(state(job['id'])['requests'])==1)
    #RehearsalWorker lifecycle using real Auth RPC with injected compute port.
    sid=session();item=register();enqueue(sid,item)
    class Client:
        subject=workers[0][0]
        expected={'runtime_instance':local.db.instance,'baseline_fingerprint':p.p.p.m.t2.t1.legacy_fingerprint()}
        def call(self,name,payload):return workers[0][1].rpc(name,payload).execute().data
    worker=RehearsalWorker(Client(),injected_port=lambda job:Port(item[1]));job=worker.call('claim')['job']
    result=worker.process_job(job);record('real_auth_queue_python_worker_result',result['state']=='succeeded' and state(job['id'])['candidate'] is not None)
    for sid in sessions:rpc('stop',{'session_id':sid})
    rpc('recover')
    record('source_fingerprint_stable',all(hashlib.sha256((p.REPO/name).read_bytes()).hexdigest()==sha for name,sha in fingerprint.items()))
    result={'passed':len(rows),'failed':0,'rows':rows,'source':fingerprint,'real_auth_sql':True,'observations':'injected','google_access':False,'live_daemon_started':False}
    path.with_suffix('.json').write_text(json.dumps(result,indent=2),encoding='utf-8');return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--runtime-dir',type=Path,required=True);args=parser.parse_args()
    for name in ('httpx','httpcore','supabase_auth','postgrest'):logging.getLogger(name).setLevel(logging.CRITICAL)
    def network(event,args):
        if event=='socket.connect' and (not isinstance(args[1],tuple) or args[1][0] not in ('127.0.0.1','::1')):raise RuntimeError('A64D1_EXTERNAL_NETWORK_FORBIDDEN')
        if event=='socket.getaddrinfo' and args[0] not in ('127.0.0.1','::1','localhost',b'127.0.0.1',b'::1'):raise RuntimeError('A64D1_EXTERNAL_DNS_FORBIDDEN')
    sys.addaudithook(network)
    result=check(p.SafetyLocal(args.runtime_dir));print(json.dumps({'passed':result['passed'],'failed':result['failed']}))
