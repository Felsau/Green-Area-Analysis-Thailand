"""Real Local Auth/SQL with injected SDK observations; never real GEE."""
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

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('a64b_checks_local', HERE / 'gee_live_local.py')
p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p
spec.loader.exec_module(p)
from gis_worker.gee_live_contracts import registered_input, queue_report, canonical, digest
from gis_worker.gee_live_injected import fixture, InjectedSDK, InjectedTransport
from gis_worker.gee_live_bridge import InjectedBridge


def check(local):
    local.proof()
    seed = uuid4().hex[:12]
    output_path = local.output / ('checks-' + seed)
    sources = [Path(__file__), HERE / 'gee_live_local.py', p.MIGRATION,
        *(p.REPO/'green-area-backend/gis_worker'/name for name in ('gee_live_contracts.py','gee_live_bridge.py','gee_live_injected.py','gee_live_worker.py'))]
    fingerprint = {f.relative_to(p.REPO).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in sources}
    output_path.with_suffix('.source.json').write_text(json.dumps(fingerprint,indent=2),encoding='utf-8')
    rows = []
    def record(name, ok):
        row={'name':name,'status':'Pass' if ok else 'Fail'};rows.append(row)
        with output_path.with_suffix('.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row)+'\n')
        print(json.dumps(row),flush=True)
        if not ok:raise AssertionError(name)
    def denied(name, fn):
        try:fn()
        except Exception as error:record(name,str(getattr(error,'code','')) in ('P0001','42501','23514','PGRST106','PGRST205','22003'))
        else:record(name,False)
    def sql_denied(name, body):
        value=local.sql(body,check=False)
        record(name,value.returncode!=0 and ('GIS_' in value.stderr or 'out of range' in value.stderr))
    def wait(fn,timeout=100):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            value=fn()
            if value:return value
            time.sleep(.5)
        raise RuntimeError('A64B_LOCAL_WAIT_EXPIRED')
    quote=p.p.m.t2.t1.literal
    anon,service=local.local_keys()
    operator=local.client(service)
    def user(role):
        pw=secrets.token_urlsafe(30)
        created=operator.auth.admin.create_user({'email':'a64b-'+uuid4().hex+'@example.invalid','password':pw,'email_confirm':True,'role':role})
        client=local.client(anon)
        session=client.auth.sign_in_with_password({'email':created.user.email,'password':pw}).session
        if session is None:raise RuntimeError('LOCAL_AUTH_REQUIRED')
        return str(created.user.id),client
    actor,normal=user('authenticated')
    local.sql('INSERT INTO gis.officers(user_id) VALUES('+quote(actor)+')')
    workers=[user('gis_gee_live_worker') for _ in range(2)]
    def rpc(index,action,payload=None):
        return workers[index][1].rpc('gis_gee_live_worker',{'p_action':action,'p_payload':payload or {}}).execute().data
    for index,(subject,client) in enumerate(workers):
        ready=client.rpc('gis_gee_live_readiness',{}).execute().data
        record('trusted_jwt_subject_'+str(index),ready['subject']==subject and ready['execution']=='injected' and ready['live_enabled'] is False)
    denied('normal_user_cannot_claim_live',lambda:normal.rpc('gis_gee_live_worker',{'p_action':'claim','p_payload':{}}).execute())
    denied('payload_worker_subject_spoofing',lambda:rpc(0,'claim',{'worker_id':workers[1][0]}))
    for name,body in [('gis_worker_v2',{'p_action':'claim','p_payload':{}}),('gis_gee_mock_worker',{'p_action':'claim','p_payload':{}}),
        ('gis_processing_worker',{'p_action':'claim','p_payload':{}}),('gis_command',{'p_actor':actor,'p_request_id':str(uuid4()),'p_operation':'grant_officer','p_payload':{},'p_backend_sandbox':False})]:
        denied('worker_denied_'+name,lambda n=name,b=body:workers[0][1].rpc(n,b).execute())
    denied('worker_private_table_denied',lambda:workers[0][1].schema('gis').table('gee_live_candidates').select('*').execute())
    denied('worker_legacy_write_denied',lambda:workers[0][1].table('ndvi_annual').update({'ndvi_mean':0}).eq('id',0).execute())
    record('service_cannot_call_worker',not operator.rpc('gis_gee_mock_read',{'p_actor':actor,'p_job':str(uuid4())}).execute().data)
    denied('service_role_cannot_use_live_worker',lambda:operator.rpc('gis_gee_live_worker',{'p_action':'claim','p_payload':{}}).execute())

    for db in p.p.DATABASES:
        value=local.sql("SELECT jsonb_build_object('rpc',(SELECT jsonb_agg(p.proname ORDER BY p.proname) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prorettype<>'trigger'::regtype AND has_function_privilege('gis_gee_live_worker',p.oid,'EXECUTE')),'rls',(SELECT bool_and(relrowsecurity AND relforcerowsecurity AND NOT has_table_privilege('gis_gee_live_worker',c.oid,'SELECT,INSERT,UPDATE,DELETE')) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='gis' AND c.relname IN ('gee_live_inputs','gee_live_requests','gee_live_candidates')))",db,read_only=True)
        record(db+'_least_privilege_rls',value=={'rpc':['gis_gee_live_readiness','gis_gee_live_worker'],'rls':True})
    def register(product='ndvi',month=0,scenario='candidate',scope='sandbox_roi'):
        request,geometry,raw=fixture(uuid4().hex[:12],product=product,month=month,scenario=scenario,scope=scope)
        value=registered_input(request,geometry)
        input_id=local.sql('INSERT INTO gis.gee_live_inputs(value) VALUES('+quote(json.dumps(value))+'::jsonb) RETURNING to_jsonb(id)')
        return input_id,request,geometry,raw,value
    def enqueue(input_id,key=None):
        return local.sql('SELECT gis.gee_live_command('+quote(actor)+','+quote(key or str(uuid4()))+",'create',"+quote(json.dumps({'input_id':input_id}))+ '::jsonb,true)')
    def state(job):
        return local.sql("SELECT jsonb_build_object('job',to_jsonb(j),'candidate',(SELECT to_jsonb(c) FROM gis.gee_live_candidates c WHERE c.job_id=j.id),'attempts',(SELECT jsonb_agg(to_jsonb(a) ORDER BY attempt_no) FROM gis.attempts a WHERE a.job_id=j.id)) FROM gis.jobs j WHERE id="+quote(job),read_only=True)
    def compute(item):
        _,request,geometry,raw,_=item
        return InjectedBridge(sdk=InjectedSDK(),transport=InjectedTransport(raw),authorization=lambda:request.project,as_of=date(2026,1,1)).compute(request,geometry)
    item=register();key=str(uuid4());created=enqueue(item[0],key);jid=created['body']['job_id']
    record('idempotent_request_reuses_job',enqueue(item[0],key)['body']==created['body'] and enqueue(item[0])['body']==created['body'])
    record('mock_protocol_cannot_claim_live_job',workers[0][1].rpc('gis_gee_live_readiness',{}).execute().data['protocol']=='gee_live_v2')
    with ThreadPoolExecutor(max_workers=2) as pool:claims=list(pool.map(lambda i:rpc(i,'claim')['job'],range(2)))
    record('atomic_concurrent_claim',sum(j is not None for j in claims)==1)
    winner=0 if claims[0] else 1;other=1-winner;job=claims[winner];output=compute(item);good=queue_report(job,output)
    lease={'job_id':jid,'lease_token':job['lease_token']}
    denied('other_worker_cannot_complete',lambda:rpc(other,'complete',lease|{'report':good}))
    denied('wrong_fencing_token',lambda:rpc(winner,'complete',lease|{'lease_token':str(uuid4()),'report':good}))
    for key in ('protocol','input_hash','input_revision','semantic_request_sha256'):
        bad=deepcopy(good);bad[key]=2 if key=='input_revision' else '0'*64
        denied('wrong_'+key,lambda b=bad:rpc(winner,'complete',lease|{'report':b}))
    for field in ('execution','project','method','geometry','evidence','statistics','missing','no_data','nonfinite','decimal'):
        bad=deepcopy(good);content=bad['output']['content']
        if field=='execution':content['execution']='live';content['synthetic']=False
        elif field=='project':content['evidence']['project']['project_number']='999999999999'
        elif field=='method':content['evidence']['method']['reduction_scale_m']=10
        elif field=='geometry':content['geometry_sha256']='0'*64
        elif field=='evidence':content['evidence']['complete']=False
        elif field=='statistics':content['statistics']['mean']=0.9
        elif field=='missing':del content['evidence']['valid_pixels']
        elif field=='no_data':content['evidence']['valid_pixels']=0
        elif field in ('nonfinite','decimal'):
            # Inject raw JSON decimal later: Python cannot represent these values.
            replacement='1'+('0'*400) if field=='nonfinite' else '0.2500000000000000000000001'
            value=quote(json.dumps(bad['output']['content']))
            altered="jsonb_set(jsonb_set(jsonb_set("+value+"::jsonb,'{evidence,raw_statistics,mean}',"+quote(replacement)+"::jsonb),'{evidence,raw_statistics,min}',"+quote(replacement)+"::jsonb),'{evidence,raw_statistics,max}',"+quote(replacement)+"::jsonb)"
            if field=='nonfinite':
                altered="jsonb_set("+altered+",'{statistics}',jsonb_build_object('mean',"+quote(replacement)+"::jsonb,'min',"+quote(replacement)+"::jsonb,'max',"+quote(replacement)+"::jsonb))"
            sql="WITH raw AS (SELECT "+altered+" AS c), content AS (SELECT jsonb_set(c,'{evidence_sha256}',to_jsonb(encode(sha256(convert_to(gis.gee_live_canonical(c->'evidence'),'UTF8')),'hex'))) c FROM raw), report AS (SELECT "+quote(json.dumps(bad))+"::jsonb||jsonb_build_object('output',jsonb_build_object('content',c,'output_sha256',encode(sha256(convert_to(gis.gee_live_canonical(c),'UTF8')),'hex')),'output_canonical',gis.gee_live_canonical(c),'evidence_canonical',gis.gee_live_canonical(c->'evidence')) AS r FROM content) SELECT gis.validate_gee_live_report(r,e,j) FROM report,gis.editions e,gis.jobs j WHERE j.id="+quote(jid)+' AND e.id=j.edition_id'
            sql_denied('raw_'+field+'_rejected',sql);continue
        bad['evidence_canonical']=canonical(content['evidence']);content['evidence_sha256']=digest(content['evidence'])
        bad['output_canonical']=canonical(content);bad['output']['output_sha256']=digest(content)
        denied('forged_'+field,lambda b=bad:rpc(winner,'complete',lease|{'report':b}))
    old=state(jid)['job']['lease_until'];time.sleep(1)
    record('heartbeat_renews_lease',rpc(winner,'heartbeat',lease|{'progress':20})['lease_until']>old)
    with ThreadPoolExecutor(max_workers=2) as pool:completed=list(pool.map(lambda _:rpc(winner,'complete',lease|{'report':good}),range(2)))
    record('concurrent_completion_single_candidate',all(c['state']=='succeeded' for c in completed) and sum(c.get('replayed',False) for c in completed)==1)
    saved=state(jid)
    record('candidate_exact_output_and_subject',saved['candidate']['output']==output.model_dump(mode='json') and saved['candidate']['worker_id']==workers[winner][0])
    record('candidate_neither_validated_nor_publishable',local.sql('SELECT jsonb_build_array(gis.eligible('+quote(job['edition_id'])+','+quote(job['dataset_id'])+'),gis.publication_ready('+quote(job['edition_id'])+','+quote(job['dataset_id'])+'))',read_only=True)==[False,False])
    sql_denied('candidate_immutable','UPDATE gis.gee_live_candidates SET output=output WHERE job_id='+quote(jid))
    sql_denied('candidate_cannot_be_validated',"UPDATE gis.editions SET state='validated',validated_result_id="+quote(saved['candidate']['result_id'])+' WHERE id='+quote(job['edition_id']))
    sql_denied('candidate_cannot_be_active','UPDATE gis.datasets SET active_edition_id='+quote(job['edition_id'])+',revision=revision+1 WHERE id='+quote(job['dataset_id']))
    for product,month,scenario in [('ndvi',2,'candidate'),('lst',0,'candidate'),('lst',2,'candidate'),('ndvi',3,'zero'),('ndvi',4,'no_data'),('ndvi',5,'all_masked'),('ndvi',6,'incomplete')]:
        item=register(product,month,scenario)
        jid=enqueue(item[0])['body']['job_id'];job=rpc(0,'claim')['job'];out=compute(item)
        done=rpc(0,'complete',{'job_id':jid,'lease_token':job['lease_token'],'report':queue_report(job,out)})
        row=state(jid);success=out.content.status=='candidate'
        record(product+'_'+str(month)+'_'+scenario,done['state']==('succeeded' if success else 'failed') and bool(row['candidate'])==success)
    item=register(month=7);jid=enqueue(item[0])['body']['job_id']
    for attempt in range(1,4):
        job=wait(lambda:rpc(0,'claim')['job'])
        record('retry_attempt_'+str(attempt),job['id']==jid and job['attempt_number']==attempt)
        result=rpc(0,'fail',{'job_id':jid,'lease_token':job['lease_token'],'error_code':'transient','report':queue_report(job,infrastructure_error='NATIVE_TIMEOUT')})
    record('exhaustion_no_candidate',result['state']=='failed' and state(jid)['candidate'] is None and len(state(jid)['attempts'])==3)
    item=register(month=8);jid=enqueue(item[0])['body']['job_id'];abandoned=rpc(0,'claim')['job']
    print(json.dumps({'event':'waiting_for_actual_live_protocol_lease_expiry','job_id':jid}),flush=True)
    wait(lambda:rpc(1,'recover')['recovered']==1)
    old_report=queue_report(abandoned,compute(item))
    denied('expired_completion_rejected',lambda:rpc(0,'complete',{'job_id':jid,'lease_token':abandoned['lease_token'],'report':old_report}))
    replacement=wait(lambda:rpc(1,'claim')['job'])
    denied('stale_after_replacement_rejected',lambda:rpc(0,'complete',{'job_id':jid,'lease_token':abandoned['lease_token'],'report':old_report}))
    rpc(1,'complete',{'job_id':jid,'lease_token':replacement['lease_token'],'report':old_report})
    record('actual_expiry_recovery_history', [a['state'] for a in state(jid)['attempts']]==['expired','succeeded'])
    record('source_fingerprint_stable',all(hashlib.sha256((p.REPO/name).read_bytes()).hexdigest()==sha for name,sha in fingerprint.items()))
    result={'passed':len(rows),'failed':0,'rows':rows,'source':fingerprint,'real_auth_sql_rpc':True,'sdk_observations':'injected','google_access':False,'daemon_process_tested':False}
    output_path.with_suffix('.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--runtime-dir',type=Path,required=True);args=parser.parse_args()
    for name in ('httpx','httpcore','supabase_auth','postgrest'):logging.getLogger(name).setLevel(logging.CRITICAL)
    def network(event,args):
        if event=='socket.connect' and (not isinstance(args[1],tuple) or args[1][0] not in ('127.0.0.1','::1')):raise RuntimeError('A64B_EXTERNAL_NETWORK_FORBIDDEN')
        if event=='socket.getaddrinfo' and args[0] not in ('127.0.0.1','::1','localhost',b'127.0.0.1',b'::1'):raise RuntimeError('A64B_EXTERNAL_DNS_FORBIDDEN')
    sys.addaudithook(network)
    result=check(p.LiveLocal(args.runtime_dir));print(json.dumps({'passed':result['passed'],'failed':result['failed']}))
