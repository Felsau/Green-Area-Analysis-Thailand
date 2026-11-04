"""Focused catalog bypass/canonical/queue-isolation checks in attested Local."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from uuid import uuid4

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('a64b_boundary_base',HERE/'gee_live_checks.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
from gis_worker.gee_live_contracts import canonical,digest,registered_input,queue_report
from gis_worker.gee_live_injected import fixture,InjectedSDK,InjectedTransport
from gis_worker.gee_live_bridge import InjectedBridge
from datetime import date


def check(local):
    local.proof();rows=[];quote=m.p.p.m.t2.t1.literal
    def record(name,ok):
        rows.append({'name':name,'status':'Pass' if ok else 'Fail'});print(json.dumps(rows[-1]),flush=True)
        if not ok:raise AssertionError(name)
    request,geometry,raw=fixture(uuid4().hex[:12],product='lst',month=2);value=registered_input(request,geometry)
    for case in ('uuid','number_type','geometry','scope','method','execution','canonical','missing'):
        bad=deepcopy(value)
        if case=='uuid':bad['request']['request_id']='-'*36
        elif case=='number_type':bad['request']['project']['project_number']=123456789012
        elif case=='geometry':bad['geometry']=None;bad['geometry_canonical']='null';bad['geometry_sha256']=digest(None);bad['request']['scope']['geometry_sha256']=digest(None)
        elif case=='scope':bad['request']['scope']['kind']='province'
        elif case=='method':bad['method']['st_multiplier']=2
        elif case=='execution':bad['request']['execution']='live'
        elif case=='missing':del bad['request']['project']['readiness']
        bad['request_canonical']=canonical({'request':{k:v for k,v in bad['request'].items() if k!='request_id'},'method':bad['method']})
        if case=='canonical':bad['request_canonical']=' '+bad['request_canonical']
        import hashlib
        bad['request_sha256']=hashlib.sha256(bad['request_canonical'].encode()).hexdigest()
        rejected=local.sql('INSERT INTO gis.gee_live_inputs(value) VALUES('+quote(json.dumps(bad))+'::jsonb)',check=False)
        record('catalog_bypass_'+case,rejected.returncode!=0 and 'GIS_' in rejected.stderr)
    vector={'ไทย':[100.0,0.000001,-0.0],'a':True}
    actual=local.sql('SELECT to_jsonb(gis.gee_live_canonical('+quote(json.dumps(vector))+'::jsonb))',read_only=True)
    record('sql_python_unicode_decimal_canonical_parity',actual==canonical(vector))
    # Reuse the same real Auth fixture creation logic, without credentials in logs.
    anon,service=local.local_keys();operator=local.client(service)
    def user(role):
        pw=m.secrets.token_urlsafe(30);email='a64b-boundary-'+uuid4().hex+'@example.invalid'
        created=operator.auth.admin.create_user({'email':email,'password':pw,'email_confirm':True,'role':role})
        client=local.client(anon);client.auth.sign_in_with_password({'email':email,'password':pw})
        return str(created.user.id),client
    actor,normal=user('authenticated');local.sql('INSERT INTO gis.officers(user_id) VALUES('+quote(actor)+')')
    _,mock=user('gis_gee_mock_worker');_,native=user('gis_native_worker');_,live=user('gis_gee_live_worker')
    input_id=local.sql('INSERT INTO gis.gee_live_inputs(value) VALUES('+quote(json.dumps(value))+'::jsonb) RETURNING to_jsonb(id)')
    created=local.sql('SELECT gis.gee_live_command('+quote(actor)+',gen_random_uuid(),\'create\',jsonb_build_object(\'input_id\','+quote(input_id)+'),true)')
    record('mock_cannot_claim_queued_live_job',mock.rpc('gis_gee_mock_worker',{'p_action':'claim','p_payload':{}}).execute().data['job'] is None)
    record('offline_cannot_claim_queued_live_job',native.rpc('gis_processing_worker',{'p_action':'claim','p_payload':{}}).execute().data['job'] is None)
    def call(action,payload=None):return live.rpc('gis_gee_live_worker',{'p_action':action,'p_payload':payload or {}}).execute().data
    job=call('claim')['job'];output=InjectedBridge(sdk=InjectedSDK(),transport=InjectedTransport(raw),authorization=lambda:request.project,as_of=date(2026,1,1)).compute(request,geometry)
    report=queue_report(job,output)
    for name,number in [('overflow','1e400'),('underflow','1e-400'),('decimal','30.00000000000000000000001')]:
        # LST monthly has neither the NDVI range check nor annual min/max
        # ordering; recompute every hash so only numeric validation rejects it.
        content=quote(json.dumps(report['output']['content']))+'::jsonb'
        changed="jsonb_set(jsonb_set("+content+",'{evidence,raw_statistics,mean}',"+quote(number)+"::jsonb),'{statistics,mean}',"+quote(number)+"::jsonb)"
        sql="WITH raw AS (SELECT "+changed+" c), content AS (SELECT jsonb_set(c,'{evidence_sha256}',to_jsonb(encode(sha256(convert_to(gis.gee_live_canonical(c->'evidence'),'UTF8')),'hex'))) c FROM raw), report AS (SELECT "+quote(json.dumps(report))+"::jsonb||jsonb_build_object('output',jsonb_build_object('content',c,'output_sha256',encode(sha256(convert_to(gis.gee_live_canonical(c),'UTF8')),'hex')),'output_canonical',gis.gee_live_canonical(c),'evidence_canonical',gis.gee_live_canonical(c->'evidence')) r FROM content) SELECT gis.validate_gee_live_report(r,e,j) FROM report,gis.editions e,gis.jobs j WHERE j.id="+quote(job['id'])+' AND e.id=j.edition_id'
        rejected=local.sql(sql,check=False)
        record('lst_monthly_'+name+'_independent_numeric_rejection',rejected.returncode!=0 and ('GIS_GEE_LIVE_NUMERIC_INVALID' in rejected.stderr or 'out of range' in rejected.stderr))
    call('complete',{'job_id':job['id'],'lease_token':job['lease_token'],'report':report})
    record('live_claims_only_own_protocol_and_commits',job['id']==created['body']['job_id'])
    result={'passed':len(rows),'failed':0,'rows':rows,'source':{str(Path(__file__).relative_to(m.p.REPO)).replace('\\','/'):hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},'google_access':False}
    (local.output/'boundary-checks.json').write_text(json.dumps(result,indent=2),encoding='utf-8');return result


if __name__=='__main__':
    import argparse,logging
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--runtime-dir',type=Path,required=True);args=parser.parse_args()
    for name in ('httpx','httpcore','supabase_auth','postgrest'):logging.getLogger(name).setLevel(logging.CRITICAL)
    def network(event,args):
        if event=='socket.connect' and (not isinstance(args[1],tuple) or args[1][0] not in ('127.0.0.1','::1')):raise RuntimeError('A64B_EXTERNAL_NETWORK_FORBIDDEN')
        if event=='socket.getaddrinfo' and args[0] not in ('127.0.0.1','::1','localhost',b'127.0.0.1',b'::1'):raise RuntimeError('A64B_EXTERNAL_DNS_FORBIDDEN')
    sys.addaudithook(network)
    result=check(m.p.LiveLocal(args.runtime_dir));print(json.dumps({'passed':result['passed'],'failed':result['failed']}))
