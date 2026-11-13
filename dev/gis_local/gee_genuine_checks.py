"""Local synthetic SQL authority tests. NOT evidence of Google observations."""
from datetime import date
import hashlib
import json
import logging
from pathlib import Path
import secrets
from uuid import uuid4

from gis_worker.gee_live_contracts import Request, canonical, digest
from gis_worker.gee_live_injected import fixture
from gis_worker.gee_live_bridge import observation_output
from gis_worker.gee_genuine_identity import PROJECT_ID, PROJECT_NUMBER, PRINCIPAL
from gee_transport_checks import quote, snapshot_value


def sample(product='ndvi'):
    req,geom,raw=fixture(uuid4().hex[:12],product=product,month=2)
    req=Request.model_validate(req.model_dump(mode='json')|{'execution':'live','project':{
        'project_id':PROJECT_ID,'project_number':PROJECT_NUMBER,'principal':PRINCIPAL,'readiness':'verified_sandbox'}})
    value={'request':req.model_dump(mode='json'),'method':req.method.model_dump(mode='json'),'geometry':geom,
        'request_canonical':canonical(req.semantic()),'geometry_canonical':canonical(geom),
        'request_sha256':req.request_hash(),'geometry_sha256':req.scope.geometry_sha256}
    out=observation_output(req,raw,as_of=date(2026,1,1))
    return value,raw,out


def setup_sql(actor,worker,recorder,*,product='ndvi',expiry="interval '20 minutes'"):
    value,raw,out=sample(product)
    sql="SET LOCAL ROLE gis_owner;DO $setup$ DECLARE i uuid;s uuid;v jsonb;runtime uuid;j jsonb;t timestamptz;BEGIN t:=clock_timestamp();"
    sql+="INSERT INTO gis.gee_live_inputs(value) VALUES("+quote(json.dumps(value))+"::jsonb) RETURNING id INTO i;"
    sql+="s:=gis.safety_session("+quote(actor)+","+quote(worker)+");v:=gis.safety_enqueue("+quote(actor)+",gen_random_uuid(),i,s);"
    sql+="INSERT INTO gis.gee_https_runtimes(recorder_id,image_id,network_policy_sha256,credential_issuer_key_sha256,approved_by,approved_at,expires_at) VALUES("
    sql+=quote(recorder)+",'sha256:'||repeat('a',64),repeat('b',64),repeat('c',64),"+quote(actor)+",t,t+"+expiry+") RETURNING id INTO runtime;"
    sql+="PERFORM gis.https_authorize((v->>'job_id')::uuid,"+quote(recorder)+",runtime);"
    sql+="j:=gis.queue_protocol_kind('claim',jsonb_build_object('worker_id',"+quote(worker)+"),'gee_genuine_https')->'job';"
    sql+="IF j->>'id' IS DISTINCT FROM v->>'job_id' THEN RAISE EXCEPTION 'HTTPS_CLAIM_FAILED';END IF;"
    sql+="PERFORM set_config('https.job',j::text,true);END $setup$;"
    return sql,raw,out


def observation_sql(recorder,raw,out):
    body=json.dumps({'result':raw})
    payload={'request_sha256':'a'*64,'response_sha256':hashlib.sha256(body.encode()).hexdigest(),
        'status':200,'category':'compute','observation':raw,'response_body':body,
        'uri':'https://earthengine.googleapis.com/v1/projects/green-area-gis-sandbox/value:compute',
        'method':'POST','peer_ip':'8.8.8.8','certificate_sha256':'d'*64,'tls_version':'TLSv1.3'}
    sql="DO $rec$ DECLARE j jsonb:=current_setting('https.job')::jsonb;r jsonb;v jsonb;sealed jsonb;BEGIN "
    sql+="r:=gis.https_record("+quote(recorder)+",'reserve',jsonb_build_object('job_id',j->>'id','lease_token',j->>'lease_token','request_key',gen_random_uuid(),'kind','compute'));"
    sql+="v:=jsonb_build_object('job_id',j->>'id','lease_token',j->>'lease_token','request_id',r->>'request_id');"
    sql+="PERFORM gis.https_record("+quote(recorder)+",'attempted',v);"
    wrong=payload|{'response_sha256':'0'*64}
    sql+=expect_denied("gis.https_record("+quote(recorder)+",'response',v||"+quote(json.dumps(wrong))+"::jsonb)",['GIS_HTTPS_OBSERVATION_REJECTED'])
    sql+="PERFORM gis.https_record("+quote(recorder)+",'response',v||"+quote(json.dumps(payload))+"::jsonb);"
    sql+=expect_denied("gis.https_record("+quote(recorder)+",'response',v||"+quote(json.dumps(payload))+"::jsonb)",['duplicate key value violates unique constraint "gee_https_receipts_pkey"'])
    sql+="sealed:=gis.https_record("+quote(recorder)+",'seal',jsonb_build_object('job_id',j->>'id','lease_token',j->>'lease_token','output',"+quote(out.model_dump_json())+"::jsonb,'receipts',jsonb_build_array(r->>'request_id')));"
    sql+="PERFORM set_config('https.report',sealed::text,true);END $rec$;"
    return sql


def expect_denied(expression, expected):
    return ("BEGIN PERFORM "+expression+";RAISE EXCEPTION 'TEST_MUST_DENY';EXCEPTION WHEN OTHERS THEN "
        "IF SQLERRM NOT IN ("+','.join(quote(e) for e in expected)+") THEN RAISE;END IF;END;")


def negative_lifecycle(local,db):
    users=local.sql("SELECT jsonb_build_object('actor',(SELECT user_id FROM gis.officers ORDER BY user_id LIMIT 1),'users',(SELECT jsonb_agg(id) FROM (SELECT id FROM public.profiles ORDER BY id LIMIT 3) x))",db,read_only=True)
    actor=users['actor'];worker,recorder=[x for x in users['users'] if x!=actor][:2]
    sql,raw,out=setup_sql(actor,worker,recorder)
    # Exercise the exact private Guards delegated by the authenticated RPC.
    # Never elevate the non-superuser Local operator to authenticator. Actual
    # GoTrue/JWT/PostgREST ACL is separately exercised by check() after Apply.
    sql+="DO $deny$ DECLARE j jsonb:=current_setting('https.job')::jsonb;a text;BEGIN "
    for action in ('reserve','attempted','finished','uncertain'):
        sql+=expect_denied("gis.https_rehearsal_budget("+quote(worker)+","+quote(action)+",jsonb_build_object('job_id',j->>'id','lease_token',j->>'lease_token'))",['GIS_WORKER_PROTOCOL_MISMATCH'])
    sql+=expect_denied("gis.https_assert_rehearsal_session((j->>'session_id')::uuid)",['GIS_WORKER_PROTOCOL_MISMATCH'])
    sql+="IF gis.safety_finalize_stopped("+quote(worker)+")<>0 THEN RAISE EXCEPTION 'CROSS_PROTOCOL_RECOVERY';END IF;END $deny$;"
    sql+="DO $fence$ DECLARE j jsonb:=current_setting('https.job')::jsonb;BEGIN "
    sql+=expect_denied("gis.https_record("+quote(recorder)+",'reserve',jsonb_build_object('job_id',j->>'id','lease_token',gen_random_uuid(),'request_key',gen_random_uuid(),'kind','compute'))",['GIS_STALE_LEASE'])
    sql+=expect_denied("gis.https_record("+quote(worker)+",'reserve',jsonb_build_object('job_id',j->>'id','lease_token',j->>'lease_token','request_key',gen_random_uuid(),'kind','compute'))",['GIS_TRANSPORT_AUTHORITY_REQUIRED'])
    sql+=expect_denied("gis.transport_authorize_fake((j->>'id')::uuid,"+quote(recorder)+")",['GIS_TRANSPORT_FAKE_BINDING_REQUIRED'])
    for uri in ('https://earthengine.googleapis.com/v1/projects/innate-beacon-483307-v1/value:compute',
        'https://earthengine.googleapis.com.evil.invalid/v1/projects/green-area-gis-sandbox/value:compute',
        'http://earthengine.googleapis.com/v1/projects/green-area-gis-sandbox/value:compute'):
        sql+="IF gis.https_endpoint("+quote(uri)+",'POST','compute') THEN RAISE EXCEPTION 'BAD_ENDPOINT_ACCEPTED';END IF;"
    for query in ('?prettyPrint=false&alt=json','?alt=json&prettyPrint=false',''):
        sql+="IF NOT gis.https_endpoint('https://earthengine.googleapis.com/v1/projects/green-area-gis-sandbox/value:compute"+query+"','POST','compute') THEN RAISE EXCEPTION 'SDK_ENDPOINT_REJECTED';END IF;"
    sql+="END $fence$;"
    sql+=observation_sql(recorder,raw,out)
    sql+="DO $stale$ DECLARE j jsonb:=current_setting('https.job')::jsonb;BEGIN "
    sql+=expect_denied("gis.queue_protocol_kind('complete',jsonb_build_object('job_id',j->>'id','worker_id',j->>'worker_id','lease_token',gen_random_uuid(),'report',current_setting('https.report')::jsonb),'gee_genuine_https')",['GIS_STALE_LEASE'])
    sql+=expect_denied("gis.https_record("+quote(recorder)+",'seal',jsonb_build_object('job_id',j->>'id','lease_token',j->>'lease_token','output',"+quote(out.model_dump_json())+"::jsonb,'receipts',jsonb_build_array(gen_random_uuid())))",['GIS_TRANSPORT_RECEIPT_SET_REJECTED'])
    sql+="PERFORM gis.queue_protocol_kind('complete',jsonb_build_object('job_id',j->>'id','worker_id',j->>'worker_id','lease_token',j->>'lease_token','report',current_setting('https.report')::jsonb),'gee_genuine_https');"
    sql+="END $stale$;"
    return sql


def expiry_lifecycle(local,db):
    users=local.sql("SELECT jsonb_build_object('actor',(SELECT user_id FROM gis.officers ORDER BY user_id LIMIT 1),'users',(SELECT jsonb_agg(id) FROM (SELECT id FROM public.profiles ORDER BY id LIMIT 3) x))",db,read_only=True)
    actor=users['actor'];worker,recorder=[x for x in users['users'] if x!=actor][:2]
    sql,raw,out=setup_sql(actor,worker,recorder,expiry="interval '1 second'")
    sql+="DO $expiry$ DECLARE j jsonb:=current_setting('https.job')::jsonb;r jsonb;payload jsonb;base jsonb;wrapped jsonb;v jsonb;BEGIN "
    sql+="r:=gis.https_record("+quote(recorder)+",'reserve',jsonb_build_object('job_id',j->>'id','lease_token',j->>'lease_token','request_key',gen_random_uuid(),'kind','compute'));"
    sql+="payload:=jsonb_build_object('job_id',j->>'id','lease_token',j->>'lease_token','request_id',r->>'request_id');"
    sql+="PERFORM gis.https_record("+quote(recorder)+",'attempted',payload);PERFORM pg_sleep(1.1);"
    sql+=expect_denied("gis.https_record("+quote(recorder)+",'reserve',jsonb_build_object('job_id',j->>'id','lease_token',j->>'lease_token','request_key',gen_random_uuid(),'kind','compute'))",['GIS_HTTPS_APPROVAL_REQUIRED'])
    sql+="PERFORM gis.https_record("+quote(recorder)+",'uncertain',payload);"
    sql+="base:=jsonb_build_object('schema_version',2,'protocol','gee_live_v2','valid',false,'error_code','NATIVE_PROCESS_FAILED','input_hash',j->>'input_hash','input_revision',j->'input_revision','semantic_request_sha256',j->>'semantic_request_sha256','output',NULL,'output_canonical',NULL,'evidence_canonical',NULL);"
    sql+="wrapped:=jsonb_build_object('schema_version',4,'protocol','gee_genuine_https','execution','live','live_enabled',false,'session_id',j->>'session_id','policy_sha256',j->>'policy_sha256','valid',false,'error_code','NATIVE_PROCESS_FAILED','base',base,'receipts','[]'::jsonb,'failure_kind','accounting_uncertain');"
    sql+="v:=gis.queue_protocol_kind('fail',jsonb_build_object('job_id',j->>'id','worker_id',j->>'worker_id','lease_token',j->>'lease_token','error_code','transient','report',wrapped),'gee_genuine_https');"
    sql+="IF v->>'state'<>'queued' THEN RAISE EXCEPTION 'EXPIRY_FAILURE_NOT_RECORDED';END IF;"
    sql+="UPDATE gis.gee_safety_sessions SET state='stopped',stopped_at=clock_timestamp(),stop_reason='operator_stop' WHERE id=(j->>'session_id')::uuid;"
    sql+="IF gis.safety_finalize_stopped((j->>'worker_id')::uuid)<>0 OR NOT EXISTS(SELECT 1 FROM gis.jobs WHERE id=(j->>'id')::uuid AND state='queued') THEN RAISE EXCEPTION 'ELIGIBLE_CROSS_PROTOCOL_RECOVERY';END IF;"
    sql+="PERFORM gis.https_finalize_protocol((j->>'worker_id')::uuid,'gee_genuine_https');"
    sql+="IF NOT EXISTS(SELECT 1 FROM gis.jobs WHERE id=(j->>'id')::uuid AND state='failed') THEN RAISE EXCEPTION 'EXPIRED_RUNTIME_NOT_FINALIZED';END IF;END $expiry$;"
    return sql


def rollback_lifecycle(local,db):
    users=local.sql("SELECT jsonb_build_object('actor',(SELECT user_id FROM gis.officers ORDER BY user_id LIMIT 1),'users',(SELECT jsonb_agg(id) FROM (SELECT id FROM public.profiles ORDER BY id LIMIT 3) x))",db,read_only=True)
    actor=users['actor'];others=[x for x in users['users'] if x!=actor]
    if not actor or len(others)<2:raise RuntimeError('LOCAL_SYNTHETIC_USERS_REQUIRED')
    worker,recorder=others[:2]
    sql,raw,out=setup_sql(actor,worker,recorder)
    sql+=observation_sql(recorder,raw,out)
    sql+="DO $done$ DECLARE j jsonb:=current_setting('https.job')::jsonb;v jsonb;BEGIN "
    sql+="v:=gis.queue_protocol_kind('complete',jsonb_build_object('job_id',j->>'id','worker_id',j->>'worker_id','lease_token',j->>'lease_token','report',current_setting('https.report')::jsonb),'gee_genuine_https');"
    sql+="IF v->>'state' IS DISTINCT FROM 'succeeded' THEN RAISE EXCEPTION 'HTTPS_PROBE_COMPLETION_FAILED';END IF;"
    sql+="IF EXISTS(SELECT 1 FROM gis.datasets d JOIN gis.jobs q ON q.edition_id=d.active_edition_id WHERE q.id=(j->>'id')::uuid) THEN RAISE EXCEPTION 'HTTPS_PUBLISHED';END IF;END $done$;"
    return sql+negative_lifecycle(local,db)+expiry_lifecycle(local,db)


def snapshot(local):
    local.proof();path=local.output/'before.json'
    if path.exists():raise RuntimeError('GEE_HTTPS_SNAPSHOT_ALREADY_EXISTS')
    path.write_text(json.dumps(snapshot_value(local),indent=2),encoding='utf-8')
    return {'saved':True,'local_only':True}


def preserve(local):
    local.proof();old=json.loads((local.output/'before.json').read_text());now=snapshot_value(local);checks=[]
    for db,b in old['baseline'].items():
        n=now['baseline'][db]
        checks.append((db+'_legacy_cache_saved_areas',all(v==n['tables'][t] for t,v in b['tables'].items() if t!='profiles')))
        checks.append((db+'_profiles',all(n['profiles'].get(k)==v for k,v in b['profiles'].items())))
        checks.append((db+'_ledger_prefix',n['ledger'][:len(b['ledger'])]==b['ledger']))
        checks.append((db+'_old_gis_rows_history_pointers',all(all(h in now['gis'][db][t] for h in rows) for t,rows in old['gis'][db].items())))
        checks.append((db+'_no_runtime_approval_or_running_jobs',local.sql("SELECT jsonb_build_array((SELECT count(*) FROM gis.gee_https_runtimes),(SELECT count(*) FROM gis.jobs WHERE state IN ('queued','running')),(SELECT activation_enabled FROM gis.environment))",db,read_only=True)==[0,0,False]))
    checks.append(('migration_000_046_bytes',all(now['source'][n]==h for n,h in old['source'].items() if int(Path(n).name[:3])<=46)))
    reviewed='4d8af35d59bc90f81de4bd835a74ec6e957e7803ab6c6cdee268d67a63ff15f8'
    checks.append(('migration_047_applied_reviewed_checksum',all(local.sql('SELECT to_jsonb(sha256) FROM gis.schema_migrations WHERE version=47',db,read_only=True)==reviewed for db in ('postgres','gis_t1_upgrade')) and now['source']['green-area-backend/migrations/047_gis_genuine_https.sql']==reviewed))
    result={'passed':sum(v for _,v in checks),'failed':sum(not v for _,v in checks),'checks':checks}
    (local.output/'preservation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def check(local):
    local.proof();rows=[]
    root=Path(__file__).parents[2]
    paths=list((root/'green-area-backend/gis_worker').glob('gee*.py'))
    paths+=[Path(__file__),root/'dev/gis_local/gee_genuine_local.py',root/'green-area-backend/migrations/047_gis_genuine_https.sql',root/'green-area-backend/tests/test_gee_genuine_foundation.py']
    sources={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    def record(name,passed):
        rows.append({'name':name,'passed':bool(passed)})
        if not passed:raise AssertionError(name)
    def denied(name,call):
        try:call()
        except Exception as e:record(name,getattr(e,'code','') in ('42501','P0001','PGRST106','PGRST205','23514'))
        else:record(name,False)
    for name in ('httpx','httpcore','postgrest','supabase_auth'):logging.getLogger(name).setLevel(logging.CRITICAL)
    anon,service=local.local_keys();admin=local.client(service)
    def user(role):
        password=secrets.token_urlsafe(32)
        obj=admin.auth.admin.create_user({'email':'https-local-'+uuid4().hex+'@example.invalid','password':password,'email_confirm':True,'role':role}).user
        c=local.client(anon);c.auth.sign_in_with_password({'email':obj.email,'password':password})
        return str(obj.id),c
    worker,w=user('gis_gee_https_worker');recorder,r=user('gis_gee_https_recorder');normal,n=user('authenticated')
    def rpc(c,name,action,payload=None):return c.rpc(name,{'p_action':action,'p_payload':payload or {}}).execute().data
    record('actual_jwt_worker_subject',w.rpc('gis_gee_https_readiness',{}).execute().data['subject']==worker)
    record('actual_jwt_recorder_subject',rpc(r,'gis_gee_https_recorder','readiness')['subject']==recorder)
    for label,c in [('worker',w),('normal',n),('service',admin)]:
        denied(label+'_cannot_record',lambda c=c:rpc(c,'gis_gee_https_recorder','readiness'))
    denied('recorder_cannot_claim',lambda:rpc(r,'gis_gee_https_worker','claim'))
    denied('worker_no_raw_budget',lambda:rpc(w,'gis_gee_https_worker','reserve'))
    for label,c in [('worker',w),('recorder',r)]:
        denied(label+'_no_private_tables',lambda c=c:c.schema('gis').table('gee_https_authorities').select('*').execute())
        denied(label+'_no_legacy_write',lambda c=c:c.table('ndvi_annual').update({'ndvi_mean':0}).eq('id',0).execute())
        for name in ('gis_worker_v2','gis_gee_safety_worker','gis_gee_transport_recorder','gis_gee_mock_worker'):
            denied(label+'_denied_'+name,lambda c=c,name=name:rpc(c,name,'claim'))
    for db in ('postgres','gis_t1_upgrade'):
        local.db.proof(db,stage='gis')
        # Complete lifecycle is transaction-scoped and explicitly feeds synthetic
        # recorder observations. No active runtime approval or job survives.
        sql=rollback_lifecycle(local,db)
        local.db.transport(db,"BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='60s';"+sql+'SET CONSTRAINTS ALL IMMEDIATE;ROLLBACK;')
        record(db+'_synthetic_authority_candidate_rollback',True)
        record(db+'_protocol_budget_stop_recovery_fencing_expiry_rollback',True)
        # Index relations have no RLS flags; inspect the four base tables only.
        record(db+'_forced_rls_no_worker_table_access',local.sql("SELECT to_jsonb(count(*)=4 AND bool_and(relrowsecurity AND relforcerowsecurity AND NOT has_table_privilege('gis_gee_https_worker',c.oid,'SELECT,INSERT,UPDATE,DELETE') AND NOT has_table_privilege('gis_gee_https_recorder',c.oid,'SELECT,INSERT,UPDATE,DELETE'))) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='gis' AND c.relkind='r' AND c.relname LIKE 'gee_https_%'",db,read_only=True) is True)
    record('no_approved_runtime',local.sql('SELECT to_jsonb(count(*)) FROM gis.gee_https_runtimes',read_only=True)==0)
    record('source_fingerprint_stable',all(hashlib.sha256((root/p).read_bytes()).hexdigest()==h for p,h in sources.items()))
    result={'passed':len(rows),'failed':0,'checks':rows,'google_http':False,'synthetic_sql_observations_only':True,'source':sources}
    (local.output/'integration.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
