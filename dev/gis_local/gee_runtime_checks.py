"""Real Local JWT/SQL plus fake credential/request plans. Never Google calls."""
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
spec=importlib.util.spec_from_file_location('a64d2_runtime_checks',HERE/'gee_runtime_local.py')
p=importlib.util.module_from_spec(spec);sys.modules[spec.name]=p;spec.loader.exec_module(p)
from gis_worker.gee_runtime_identity import RuntimeBinding,InjectedCredentials
from gis_worker.gee_runtime_transport import PreparedInjectedTransport


def check(local):
    local.proof();rows=[];path=local.output/('checks-'+uuid4().hex[:12])
    sources=[Path(__file__),HERE/'gee-runtime-image.lock.json',HERE/'gee-runtime-review.json',
        *(p.REPO/n for n in p.SENSITIVE),
        p.REPO/'green-area-backend/migrations/045_gis_execution_safety.sql',
        p.REPO/'green-area-backend/gis_worker/gee_execution_safety.py']
    fingerprint={f.relative_to(p.REPO).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in sources}
    path.with_suffix('.source.json').write_text(json.dumps(fingerprint,indent=2),encoding='utf-8')
    def record(name,ok):
        row={'name':name,'status':'Pass' if ok else 'Fail'};rows.append(row);print(json.dumps(row),flush=True)
        with path.with_suffix('.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row)+'\n')
        if not ok:raise AssertionError(name)
    def reject(name,fn,expected):
        try:fn()
        except Exception as error:record(name,expected in (getattr(error,'message',None) or str(error)))
        else:record(name,False)
    quote=p.p.p.p.m.t2.t1.literal
    anon,service=local.local_keys();operator=local.client(service)
    def user(role):
        password=secrets.token_urlsafe(30)
        created=operator.auth.admin.create_user({'email':'a64d2-'+uuid4().hex+'@example.invalid','password':password,'email_confirm':True,'role':role})
        client=local.client(anon);session=client.auth.sign_in_with_password({'email':created.user.email,'password':password}).session
        if session is None:raise RuntimeError('A64D2_LOCAL_AUTH_REQUIRED')
        return str(created.user.id),client
    actor,_=user('authenticated');subject,client=user('gis_gee_safety_worker')
    local.sql('INSERT INTO gis.officers(user_id) VALUES('+quote(actor)+')')
    def rpc(action,payload=None):return client.rpc('gis_gee_safety_worker',{'p_action':action,'p_payload':payload or {}}).execute().data
    ready=client.rpc('gis_gee_safety_readiness',{}).execute().data
    record('actual_local_jwt_subject_and_closed_live_gate',ready['subject']==subject and ready['live_enabled'] is False)
    def new_job():
        request,geometry,raw=p.p.p.fixture(uuid4().hex[:12]);value=p.p.p.registered_input(request,geometry)
        iid=local.sql('INSERT INTO gis.gee_live_inputs(value) VALUES('+quote(json.dumps(value))+'::jsonb) RETURNING to_jsonb(id)')
        sid=local.sql('SELECT to_jsonb(gis.safety_session('+quote(actor)+','+quote(subject)+'))')
        local.sql('SELECT gis.safety_enqueue('+quote(actor)+',gen_random_uuid(),'+quote(iid)+','+quote(sid)+')')
        output=p.p.p.InjectedBridge(sdk=p.p.p.InjectedSDK(),transport=p.p.p.InjectedTransport(raw),authorization=lambda:request.project,as_of=date(2026,1,1)).compute(request,geometry)
        return sid,rpc('claim')['job'],output
    def lease(job):return {'job_id':job['id'],'lease_token':job['lease_token']}
    def state(job):return local.sql("SELECT jsonb_build_object('requests',(SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY reserved_at),'[]'::jsonb) FROM gis.gee_safety_requests r WHERE r.job_id=j.id),'attempts',(SELECT jsonb_agg(to_jsonb(a) ORDER BY attempt_no) FROM gis.attempts a WHERE a.job_id=j.id),'candidate',(SELECT to_jsonb(c) FROM gis.gee_live_candidates c WHERE c.job_id=j.id),'job',to_jsonb(j)) FROM gis.jobs j WHERE id="+quote(job['id']),read_only=True)
    def token(job):
        binding=RuntimeBinding.from_claim(job,subject);provider=InjectedCredentials(binding)
        return binding,provider,provider.issue(binding)
    class Port:
        OFFLINE_INJECTED=True
        def __init__(self,output):self.output=output
        def evaluate(self,*,timeout_seconds):return self.output
    sid,job,output=new_job();binding,provider,credential=token(job)
    reject('wrong_worker_context_rejected',lambda:PreparedInjectedTransport(rpc,job,str(uuid4()),provider,credential),'CONTEXT_REJECTED')
    wrong=binding.model_dump(mode='json');wrong['project']['principal']='other@'+binding.project.project_id+'.iam.gserviceaccount.com'
    reject('wrong_google_principal_rejected',lambda:provider.authorize(credential,RuntimeBinding.model_validate(wrong)),'BINDING_REJECTED')
    provider.revoke(credential)
    reject('revoked_fake_credential_before_sql_reservation',lambda:PreparedInjectedTransport(rpc,job,subject,provider,credential),'REVOKED')
    record('credential_rejections_do_not_allocate_requests',state(job)['requests']==[])
    credential=provider.issue(binding)
    wrapped=PreparedInjectedTransport(rpc,job,subject,provider,credential).run(
        [('compute',Port(output)),('sdk_retry',Port(output)),('reference',Port(output))])
    saved=state(job)
    record('three_actual_durable_request_kinds',len(saved['requests'])==3 and {r['kind'] for r in saved['requests']}=={'compute','sdk_retry','reference'} and all(r['state']=='completed' for r in saved['requests']))
    record('fake_credential_not_in_report',str(credential.lease_id) not in json.dumps(wrapped) and 'FakeGoogleLease' not in json.dumps(wrapped))
    done=rpc('complete',lease(job)|{'report':wrapped})
    record('injected_candidate_committed_once',done['state']=='succeeded' and rpc('complete',lease(job)|{'report':wrapped})['replayed'] is True)
    record('candidate_not_publishable_and_correct_observation',state(job)['candidate']['output']==output.model_dump(mode='json') and output.content.publishable is False and output.content.synthetic is True)
    rpc('stop',{'session_id':sid})
    #Replacement caller and fake credential provider after actual60s lease loss.
    sid,old,output=new_job();binding,provider,credential=token(old)
    class TimeoutPort:
        OFFLINE_INJECTED=True
        def evaluate(self,*,timeout_seconds):raise TimeoutError('injected transport timeout')
    reject('injected_timeout_consumes_uncertain_request',lambda:PreparedInjectedTransport(rpc,old,subject,provider,credential).run([('compute',TimeoutPort())]),'injected transport timeout')
    record('uncertain_charge_persisted_before_recovery',len(state(old)['requests'])==1 and state(old)['requests'][0]['state']=='uncertain')
    print(json.dumps({'event':'actual_lease_expiry_no_live_daemon_started'}),flush=True)
    until=time.monotonic()+85
    while rpc('recover')['recovered']!=1:
        if time.monotonic()>until:raise RuntimeError('A64D2_LEASE_RECOVERY_WAIT_EXPIRED')
        time.sleep(.5)
    until=time.monotonic()+15;job=None
    while job is None:
        job=rpc('claim')['job']
        if time.monotonic()>until:raise RuntimeError('A64D2_REPLACEMENT_CLAIM_WAIT_EXPIRED')
        if job is None:time.sleep(.5)
    record('replacement_keeps_logical_job_and_attempt_budget',job['id']==old['id'] and job['attempt_number']==2)
    replacement_binding,new_provider,new_credential=token(job)
    reject('old_fake_lease_not_valid_for_replacement_attempt',lambda:provider.authorize(credential,replacement_binding),'BINDING_REJECTED')
    reject('old_sql_fencing_token_rejected',lambda:rpc('reserve',lease(old)|{'request_key':str(uuid4()),'kind':'reference'}),'GIS_STALE_LEASE')
    wrapped=PreparedInjectedTransport(rpc,job,subject,new_provider,new_credential).run([('sdk_retry',Port(output)),('reference',Port(output))])
    record('replacement_requests_do_not_reset_session_budget',len(state(job)['requests'])==3 and state(job)['requests'][0]['state']=='uncertain')
    rpc('complete',lease(job)|{'report':wrapped})
    saved=state(job)
    record('recovery_history_and_candidate_fenced',[a['state'] for a in saved['attempts']]==['expired','succeeded'] and saved['candidate']['attempt_no']==2)
    rpc('stop',{'session_id':sid})
    sid,job,output=new_job();binding,provider,credential=token(job)
    rpc('stop',{'session_id':sid})
    reject('sql_session_stop_blocks_valid_fake_credential_plan',lambda:PreparedInjectedTransport(rpc,job,subject,provider,credential).run([('reference',Port(output))]),'GIS_SAFETY_SESSION_CLOSED')
    record('stopped_session_created_no_http_reservation',state(job)['requests']==[])
    from gis_worker.gee_execution_safety import report
    from gis_worker.gee_live_contracts import queue_report
    rpc('fail',lease(job)|{'error_code':'transient','report':report(job,queue_report(job,infrastructure_error='WORKER_SHUTDOWN'),failure_kind='session_stopped')})
    record('source_fingerprint_stable',all(hashlib.sha256((p.REPO/n).read_bytes()).hexdigest()==h for n,h in fingerprint.items()))
    result={'passed':len(rows),'failed':0,'rows':rows,'source':fingerprint,'google_access':False,
        'real_local_auth_sql':True,'physical_sdk_interception':False,'actual_live_daemon_started':False,'credential_type':'fake-in-memory-only'}
    path.with_suffix('.json').write_text(json.dumps(result,indent=2),encoding='utf-8');return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--runtime-dir',type=Path,required=True);args=parser.parse_args()
    for name in ('httpx','httpcore','supabase_auth','postgrest'):logging.getLogger(name).setLevel(logging.CRITICAL)
    def network(event,args):
        if event=='socket.connect' and (not isinstance(args[1],tuple) or args[1][0] not in ('127.0.0.1','::1')):raise RuntimeError('A64D2_EXTERNAL_NETWORK_FORBIDDEN')
        if event=='socket.getaddrinfo' and args[0] not in ('127.0.0.1','::1','localhost',b'127.0.0.1',b'::1'):raise RuntimeError('A64D2_EXTERNAL_DNS_FORBIDDEN')
    sys.addaudithook(network)
    result=check(p.RuntimeLocal(args.runtime_dir));print(json.dumps({'passed':result['passed'],'failed':result['failed']}))
