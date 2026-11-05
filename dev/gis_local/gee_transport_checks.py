"""Local-only SDK/SQL recorder tests. No Google identity/network is used."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date
import hashlib
import json
import logging
from pathlib import Path
import secrets
import time
from uuid import uuid4

from gis_worker.gee_live_bridge import InjectedBridge
from gis_worker.gee_live_contracts import Request, registered_input, queue_report, canonical, digest
from gis_worker.gee_live_injected import fixture, InjectedSDK, InjectedTransport
from gis_worker.gee_sdk_transport import FakeHTTPWire, PhysicalHTTP, FakeSDKAdapter, SANDBOX, FAKE_PRINCIPAL


def quote(s):
    return "'"+str(s).replace("'","''")+"'"


def sample(product='ndvi',month=0,scenario='candidate'):
    req,geom,raw=fixture(uuid4().hex[:12],product=product,month=month,scenario=scenario)
    req=Request.model_validate(req.model_dump(mode='json')|{'project':{'project_id':SANDBOX[0],
        'project_number':SANDBOX[1],'principal':FAKE_PRINCIPAL}})
    out=InjectedBridge(sdk=InjectedSDK(),transport=InjectedTransport(raw),authorization=lambda:req.project,
        as_of=date(2026,1,1)).compute(req,geom)
    return req,geom,raw,out


def rollback_lifecycle(local,db):
    req,geom,raw,out=sample()
    # Owner-only transaction probe; public JWT boundaries are tested separately
    # with actual GoTrue tokens after Apply. Never elevate the local migrator.
    body="SET LOCAL ROLE gis_owner;DO $probe$ DECLARE actor uuid;recorder uuid;i uuid;s uuid;v jsonb;j jsonb;BEGIN "
    body+="SELECT user_id INTO actor FROM gis.officers ORDER BY user_id LIMIT 1;SELECT id INTO recorder FROM public.profiles WHERE id<>actor ORDER BY id LIMIT 1;IF actor IS NULL OR recorder IS NULL THEN RAISE EXCEPTION 'LOCAL_SYNTHETIC_USERS_REQUIRED';END IF;"
    body+='INSERT INTO gis.gee_live_inputs(value) VALUES('+quote(json.dumps(registered_input(req,geom)))+'::jsonb) RETURNING id INTO i;'
    body+="s:=gis.safety_session(actor,actor);v:=gis.safety_enqueue(actor,gen_random_uuid(),i,s);"
    body+="PERFORM gis.transport_authorize_fake((v->>'job_id')::uuid,recorder);j:=gis.queue_protocol_kind('claim',jsonb_build_object('worker_id',actor),'gee_safety_rehearsal')->'job';"
    body+="IF j->>'id' IS DISTINCT FROM v->>'job_id' THEN RAISE EXCEPTION 'PROBE_QUEUE_NOT_IDLE';END IF;"
    body+="PERFORM set_config('a6.probe_job',j::text,true);PERFORM set_config('a6.probe_recorder',recorder::text,true);END $probe$;"
    body+="DO $rec$ DECLARE j jsonb:=current_setting('a6.probe_job')::jsonb;recorder uuid:=current_setting('a6.probe_recorder')::uuid;r jsonb;v jsonb;BEGIN "
    body+="r:=gis.transport_record(recorder,'reserve',jsonb_build_object('job_id',j->>'id','lease_token',j->>'lease_token','request_key',gen_random_uuid(),'kind','compute'));"
    body+="v:=jsonb_build_object('job_id',j->>'id','lease_token',j->>'lease_token','request_id',r->>'request_id');PERFORM gis.transport_record(recorder,'attempted',v);"
    payload={'request_sha256':'a'*64,'response_sha256':hashlib.sha256(canonical({'result':raw}).encode()).hexdigest(),
        'status':200,'category':'compute','observation':raw}
    body+="PERFORM gis.transport_record(recorder,'response',v||"+quote(json.dumps(payload))+"::jsonb);"
    body+="v:=gis.transport_record(recorder,'seal',jsonb_build_object('job_id',j->>'id','lease_token',j->>'lease_token','output',"+quote(out.model_dump_json())+"::jsonb,'receipts',jsonb_build_array(r->>'request_id')));PERFORM set_config('a6.probe_report',v::text,true);END $rec$;"
    body+="DO $done$ DECLARE j jsonb:=current_setting('a6.probe_job')::jsonb;v jsonb;BEGIN "
    body+="v:=gis.queue_protocol_kind('complete',jsonb_build_object('worker_id',j->>'worker_id','job_id',j->>'id','lease_token',j->>'lease_token','report',current_setting('a6.probe_report')::jsonb),'gee_safety_rehearsal');IF v->>'state' IS DISTINCT FROM 'succeeded' THEN RAISE EXCEPTION 'PROBE_CANDIDATE_FAILED';END IF;END $done$;"
    return body


def snapshot_value(local):
    value={'baseline':local.baseline(),'gis':{},'source':{}}
    for db in ('postgres','gis_t1_upgrade'):
        tables=local.sql("SELECT jsonb_agg(tablename) FROM pg_tables WHERE schemaname='gis'",db,read_only=True)
        pairs=[]
        for t in tables:
            ident='"'+t.replace('"','""')+'"'
            pairs.append(quote(t)+",(SELECT COALESCE(jsonb_agg(md5(to_jsonb(t)::text) ORDER BY to_jsonb(t)::text),'[]'::jsonb) FROM gis."+ident+' t)')
        value['gis'][db]=local.sql('SELECT jsonb_build_object('+','.join(pairs)+')',db,read_only=True)
    root=Path(__file__).parents[2]
    for f in (root/'green-area-backend/migrations').glob('*.sql'):
        value['source'][f.relative_to(root).as_posix()]=hashlib.sha256(f.read_bytes()).hexdigest()
    return value


def snapshot(local):
    local.proof()
    path=local.output/'before.json'
    if path.exists():raise RuntimeError('A6_BASELINE_ALREADY_EXISTS')
    path.write_text(json.dumps(snapshot_value(local),indent=2),encoding='utf-8')
    return {'snapshot_saved':True,'local_only':True}


def preserve(local):
    local.proof();old=json.loads((local.output/'before.json').read_text());now=snapshot_value(local);rows=[]
    for db,b in old['baseline'].items():
        n=now['baseline'][db]
        rows.append((db+'_legacy_tables',all(v==n['tables'][t] for t,v in b['tables'].items() if t!='profiles')))
        rows.append((db+'_original_profiles',all(n['profiles'].get(k)==v for k,v in b['profiles'].items())))
        rows.append((db+'_old_ledger',n['ledger'][:len(b['ledger'])]==b['ledger']))
        rows.append((db+'_old_gis_rows',all(all(h in now['gis'][db][t] for h in hashes) for t,hashes in old['gis'][db].items())))
        rows.append((db+'_gate_queue',local.sql("SELECT jsonb_build_array((SELECT activation_enabled FROM gis.environment),(SELECT count(*) FROM gis.jobs WHERE state IN ('queued','running')))",db,read_only=True)==[False,0]))
    rows.append(('old_migration_bytes',all(now['source'].get(p)==h for p,h in old['source'].items() if int(Path(p).name[:3])<=45)))
    result={'passed':sum(ok for _,ok in rows),'failed':sum(not ok for _,ok in rows),'checks':rows}
    (local.output/'preservation.json').write_text(json.dumps(result,indent=2))
    return result


def check(local):
    local.proof();rows=[];run=uuid4().hex[:10]
    root=Path(__file__).parents[2]
    files=['green-area-backend/migrations/046_gis_gee_live_authority.sql',
        'green-area-backend/gis_worker/gee_sdk_transport.py','dev/gis_local/gee_transport_local.py',
        'dev/gis_local/gee_transport_checks.py','green-area-backend/gis_worker/gee_live_bridge.py',
        'green-area-backend/gis_worker/gee_live_contracts.py']
    sources={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in files}
    def record(name,ok):
        rows.append({'name':name,'passed':bool(ok)})
        print(json.dumps(rows[-1]),flush=True)
        if not ok:raise AssertionError(name)
    def denied(name,fn):
        try:fn()
        except Exception as e:
            record(name,str(getattr(e,'code','')) in ('P0001','42501','23514','23505','PGRST106','PGRST205','22003','22P02'))
        else:record(name,False)
    def sql_denied(name,body):
        v=local.sql(body,check=False)
        record(name,v.returncode!=0 and ('GIS_' in v.stderr or 'permission denied' in v.stderr))
    for name in ('httpx','httpcore','postgrest','supabase_auth'):logging.getLogger(name).setLevel(logging.CRITICAL)
    anon,service=local.local_keys();operator=local.client(service)
    def user(role):
        password=secrets.token_urlsafe(32)
        u=operator.auth.admin.create_user({'email':'a6-http-'+uuid4().hex+'@example.invalid','password':password,'email_confirm':True,'role':role}).user
        c=local.client(anon);c.auth.sign_in_with_password({'email':u.email,'password':password})
        return str(u.id),c
    actor,normal=user('authenticated');worker,wclient=user('gis_gee_safety_worker')
    recorder,rclient=user('gis_gee_transport_recorder');other,otherclient=user('gis_gee_transport_recorder')
    local.sql('INSERT INTO gis.officers(user_id) VALUES('+quote(actor)+')')
    def wr(action,payload=None):return wclient.rpc('gis_gee_safety_worker',{'p_action':action,'p_payload':payload or {}}).execute().data
    def rec(action,payload=None,client=rclient):return client.rpc('gis_gee_transport_recorder',{'p_action':action,'p_payload':payload or {}}).execute().data
    record('recorder_trusted_jwt_subject',rec('readiness')['subject']==recorder)
    for label,client in [('worker',wclient),('normal',normal),('service',operator)]:
        denied(label+'_cannot_record',lambda c=client:rec('readiness',client=c))
    for rpc in ('gis_gee_safety_worker','gis_gee_live_worker','gis_worker_v2','gis_gee_mock_worker'):
        denied('recorder_denied_'+rpc,lambda n=rpc:rclient.rpc(n,{'p_action':'claim','p_payload':{}}).execute())
    denied('recorder_no_admin_rpc',lambda:rclient.rpc('gis_command',{'p_actor':actor,'p_request_id':str(uuid4()),'p_operation':'grant_officer','p_payload':{},'p_backend_sandbox':False}).execute())
    denied('recorder_no_direct_tables',lambda:rclient.schema('gis').table('gee_transport_authorities').select('*').execute())
    denied('recorder_no_legacy_writes',lambda:rclient.table('ndvi_annual').update({'ndvi_mean':0}).eq('id',0).execute())
    denied('genuine_complete_disabled',lambda:rec('live_complete'))
    for db in ('postgres','gis_t1_upgrade'):
        acl=local.sql("SELECT jsonb_build_object('functions',(SELECT jsonb_agg(p.proname ORDER BY p.proname) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prorettype<>'trigger'::regtype AND has_function_privilege('gis_gee_transport_recorder',p.oid,'EXECUTE')),'rls',(SELECT bool_and(relrowsecurity AND relforcerowsecurity AND NOT has_table_privilege('gis_gee_transport_recorder',c.oid,'SELECT,INSERT,UPDATE,DELETE')) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='gis' AND c.relkind='r' AND c.relname LIKE 'gee_transport_%'))",db,read_only=True)
        record(db+'_recorder_least_privilege',acl=={'functions':['gis_gee_transport_recorder'],'rls':True})
    def new_job(product='ndvi',month=0,scenario='candidate',bound=True):
        req,geom,raw,out=sample(product,month,scenario)
        iid=local.sql('INSERT INTO gis.gee_live_inputs(value) VALUES('+quote(json.dumps(registered_input(req,geom)))+'::jsonb) RETURNING to_jsonb(id)')
        sid=local.sql('SELECT to_jsonb(gis.safety_session('+quote(actor)+','+quote(worker)+'))')
        v=local.sql('SELECT gis.safety_enqueue('+quote(actor)+',gen_random_uuid(),'+quote(iid)+','+quote(sid)+')')
        if bound:local.sql('SELECT gis.transport_authorize_fake('+quote(v['job_id'])+','+quote(recorder)+')')
        j=wr('claim')['job'];record('claimed_own_'+j['id'],j['id']==v['job_id'])
        return j,req,geom,raw,out
    def fail(j):
        wr('stop',{'session_id':j['session_id']})
        return wr('fail',{'job_id':j['id'],'lease_token':j['lease_token'],'error_code':'transient','report':
            {'schema_version':3,'protocol':'gee_safety_rehearsal','execution':'rehearsal','live_enabled':False,'session_id':j['session_id'],
            'policy_sha256':j['policy_sha256'],'valid':False,'error_code':'NATIVE_PROCESS_FAILED','base':queue_report(j,infrastructure_error='NATIVE_PROCESS_FAILED'),'receipts':[],'failure_kind':'accounting_uncertain'}})
    # Full real-SDK→actual Auth/SQL recorder→original worker completion.
    for product,month,statuses,refresh in [('ndvi',0,[503,200],False),('lst',2,[401,200],True)]:
        j,req,geom,raw,_=new_job(product,month);sealed=[]
        def callback(action,payload):
            v=rec(action,payload)
            if action=='seal':sealed.append(v)
            return v
        wire=FakeHTTPWire(raw,responses=statuses,refresh=refresh)
        result=FakeSDKAdapter(PhysicalHTTP(callback,j,wire)).compute(req,geom,as_of=date(2026,1,1))
        payload={'job_id':j['id'],'lease_token':j['lease_token'],'report':sealed[0]}
        done=wr('complete',payload)
        record(product+'_sdk_auth_sql_candidate',done['state']=='succeeded' and result.content.synthetic and not result.content.publishable)
        record(product+'_physical_count_matches_sql',local.sql('SELECT to_jsonb(count(*)) FROM gis.gee_transport_receipts WHERE job_id='+quote(j['id']),read_only=True)==len(wire.calls))
        record(product+'_idempotent_completion',wr('complete',payload).get('replayed') is True)
        denied(product+'_recorder_receipt_replay',lambda:rec('response',{'job_id':j['id'],'lease_token':j['lease_token'],'request_id':sealed[0]['receipts'][0]}))
        state=local.sql('SELECT jsonb_build_array(e.state,d.active_edition_id,c.output->\'content\'->\'publishable\') FROM gis.editions e JOIN gis.datasets d ON d.id=e.dataset_id JOIN gis.gee_live_candidates c ON c.edition_id=e.id WHERE e.id='+quote(j['edition_id']),read_only=True)
        record(product+'_draft_no_activation',state==['draft',None,False])
        sql_denied(product+'_candidate_immutable','UPDATE gis.gee_live_candidates SET output=output WHERE job_id='+quote(j['id']))
        sql_denied(product+'_receipt_immutable','DELETE FROM gis.gee_transport_receipts WHERE job_id='+quote(j['id']))
    # Old RPC completion cannot bypass new authority, even with worker-written045 reservations.
    j,req,geom,raw,out=new_job();lease={'job_id':j['id'],'lease_token':j['lease_token']}
    denied('wrong_recorder_subject',lambda:rec('reserve',lease|{'request_key':str(uuid4()),'kind':'compute'},client=otherclient))
    denied('spoof_worker_payload',lambda:rec('reserve',lease|{'request_key':str(uuid4()),'kind':'compute','worker_id':worker}))
    denied('expired_token_recorder',lambda:rec('reserve',lease|{'lease_token':str(uuid4()),'request_key':str(uuid4()),'kind':'compute'}))
    rid=wr('reserve',lease|{'request_key':str(uuid4()),'kind':'compute'})['request_id']
    wr('attempted',lease|{'request_id':rid});wr('finished',lease|{'request_id':rid,'evidence_sha256':out.content.evidence_sha256})
    wrapped={'schema_version':3,'protocol':'gee_safety_rehearsal','execution':'rehearsal','live_enabled':False,'session_id':j['session_id'],
        'policy_sha256':j['policy_sha256'],'valid':True,'error_code':None,'base':queue_report(j,out),'receipts':[rid],'failure_kind':None}
    denied('old_worker_completion_without_recorder_seal_rejected',lambda:wr('complete',lease|{'report':wrapped}))
    denied('forged_receipt_seal_rejected',lambda:rec('seal',lease|{'output':out.model_dump(mode='json'),'receipts':[str(uuid4())]}))
    fail(j)
    # Concurrent durable reservations share a single 32-request session budget.
    pool_clients=[local.client(anon) for _ in range(4)]
    for c in pool_clients:c.postgrest.auth(rclient.auth.get_session().access_token)
    j,req,geom,raw,out=new_job();lease={'job_id':j['id'],'lease_token':j['lease_token']}
    def reserve(index):
        c=pool_clients[index%len(pool_clients)]
        try:return rec('reserve',lease|{'request_key':str(uuid4()),'kind':'compute'},client=c)
        except Exception as e:
            if getattr(e,'message','')=='GIS_SAFETY_SESSION_CLOSED':return {'granted':False}
            raise
    with ThreadPoolExecutor(max_workers=4) as pool:vals=list(pool.map(reserve,range(34)))
    record('concurrent_32_budget_no_overshoot',sum(x.get('granted') is not False for x in vals)==32)
    record('session_budget_sql_count',local.sql('SELECT to_jsonb(count(*)) FROM gis.gee_safety_requests WHERE session_id='+quote(j['session_id']),read_only=True)==32)
    fail(j)
    record('source_fingerprint_stable',all(hashlib.sha256((root/p).read_bytes()).hexdigest()==h for p,h in sources.items()))
    result={'passed':len(rows),'failed':0,'checks':rows,'real_google':False,'actual_sdk_fake_http':True,'source':sources}
    (local.output/'integration.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
