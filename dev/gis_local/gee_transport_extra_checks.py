"""Focused actual-Auth concurrency/scientific negatives after046. Local only."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import logging
from pathlib import Path
import secrets
import sys
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parent))
from gee_transport_local import TransportLocal, REPO
from gee_transport_checks import sample,quote
from gis_worker.gee_live_contracts import registered_input,queue_report,canonical


def check(local):
    local.proof();rows=[]
    paths=[Path(__file__),REPO/'green-area-backend/migrations/046_gis_gee_live_authority.sql',
        REPO/'green-area-backend/gis_worker/gee_sdk_transport.py']
    sources={p.relative_to(REPO).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    def record(name,ok):
        rows.append({'name':name,'passed':bool(ok)});print(json.dumps(rows[-1]),flush=True)
        if not ok:raise AssertionError(name)
    def denied(name,fn):
        try:fn()
        except Exception as e:record(name,getattr(e,'code','') in ('P0001','42501','23514','23505'))
        else:record(name,False)
    for n in ('httpx','httpcore','postgrest','supabase_auth'):logging.getLogger(n).setLevel(logging.CRITICAL)
    anon,service=local.local_keys();operator=local.client(service)
    def user(role):
        password=secrets.token_urlsafe(30)
        u=operator.auth.admin.create_user({'email':'a6-extra-'+uuid4().hex+'@example.invalid','password':password,'email_confirm':True,'role':role}).user
        c=local.client(anon);c.auth.sign_in_with_password({'email':u.email,'password':password})
        return str(u.id),c
    actor,_=user('authenticated');worker,w=user('gis_gee_safety_worker');recorder,r=user('gis_gee_transport_recorder')
    local.sql('INSERT INTO gis.officers(user_id) VALUES('+quote(actor)+')')
    def wr(a,p=None):return w.rpc('gis_gee_safety_worker',{'p_action':a,'p_payload':p or {}}).execute().data
    def rec(a,p):return r.rpc('gis_gee_transport_recorder',{'p_action':a,'p_payload':p}).execute().data
    sid=local.sql('SELECT to_jsonb(gis.safety_session('+quote(actor)+','+quote(worker)+'))')
    def enqueue(bound=True):
        req,geom,raw,out=sample()
        iid=local.sql('INSERT INTO gis.gee_live_inputs(value) VALUES('+quote(json.dumps(registered_input(req,geom)))+'::jsonb) RETURNING to_jsonb(id)')
        v=local.sql('SELECT gis.safety_enqueue('+quote(actor)+',gen_random_uuid(),'+quote(iid)+','+quote(sid)+')')
        if bound:local.sql('SELECT gis.transport_authorize_fake('+quote(v['job_id'])+','+quote(recorder)+')')
        return v,raw,out
    def process(bound=True):
        v,raw,out=enqueue(bound)
        with ThreadPoolExecutor(max_workers=2) as pool:claims=list(pool.map(lambda _:wr('claim'),range(2)))
        jobs=[c.get('job') for c in claims if c.get('job')]
        record('atomic_concurrent_claim_'+str(bound),len(jobs)==1 and jobs[0]['id']==v['job_id'])
        j=jobs[0];lease={'job_id':j['id'],'lease_token':j['lease_token']}
        call=rec if bound else wr
        rid=call('reserve',lease|{'request_key':str(uuid4()),'kind':'compute'})['request_id']
        call('attempted',lease|{'request_id':rid})
        payload=lease|{'request_id':rid,'request_sha256':'a'*64,
            'response_sha256':hashlib.sha256(canonical({'result':raw}).encode()).hexdigest(),
            'status':200,'category':'compute','observation':raw}
        if bound:
            denied('wrong_response_hash_rejected',lambda:rec('response',payload|{'response_sha256':'0'*64}))
            rec('response',payload)
            denied('response_replay_rejected',lambda:rec('response',payload))
            for field in ('input_revision','method','observation'):
                bad=out.model_dump(mode='json')
                if field=='input_revision':bad['content']['request']['input_revision']=2
                elif field=='method':bad['content']['evidence']['method']['reflectance_divisor']=1
                else:bad['content']['evidence']['raw_statistics']['mean']=0.75
                denied(field+'_forged_output_rejected',lambda b=bad:rec('seal',lease|{'output':b,'receipts':[rid]}))
            report=rec('seal',lease|{'output':out.model_dump(mode='json'),'receipts':[rid]})
        else:
            wr('finished',lease|{'request_id':rid,'evidence_sha256':out.content.evidence_sha256})
            report={'schema_version':3,'protocol':'gee_safety_rehearsal','execution':'rehearsal','live_enabled':False,
                'session_id':sid,'policy_sha256':j['policy_sha256'],'valid':True,'error_code':None,
                'base':queue_report(j,out),'receipts':[rid],'failure_kind':None}
        payload=lease|{'report':report}
        with ThreadPoolExecutor(max_workers=2) as pool:done=list(pool.map(lambda _:wr('complete',payload),range(2)))
        record('atomic_concurrent_complete_'+str(bound),all(d['state']=='succeeded' for d in done) and sum(d.get('replayed') is True for d in done)==1)
        record('one_result_'+str(bound),local.sql('SELECT to_jsonb(count(*)) FROM gis.results WHERE job_id='+quote(j['id']),read_only=True)==1)
    process(True)
    process(False)
    record('budget_shared_across_jobs',local.sql('SELECT to_jsonb(count(*)) FROM gis.gee_safety_requests WHERE session_id='+quote(sid),read_only=True)==2)
    # Constraints reject metadata tampering without changing immutable rows.
    for field,value in [('project_id','innate-beacon-483307-v1'),('google_principal','forged@green-area-gis-sandbox.iam.gserviceaccount.com'),('mode','google_https')]:
        sql='UPDATE gis.gee_transport_authorities SET '+field+'='+quote(value)+' WHERE session_id='+quote(sid)
        v=local.sql(sql,check=False)
        record(field+'_authority_change_rejected',v.returncode!=0 and 'GIS_GEE_LIVE_IMMUTABLE' in v.stderr)
    record('extra_source_stable',all(hashlib.sha256((REPO/p).read_bytes()).hexdigest()==h for p,h in sources.items()))
    result={'passed':len(rows),'failed':0,'checks':rows,'source':sources,'actual_auth_sql':True,'google_calls':False}
    (local.output/'extra-integration.json').write_text(json.dumps(result,indent=2))
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--runtime-dir',type=Path,required=True)
    args=ap.parse_args();print(json.dumps(check(TransportLocal(args.runtime_dir))))
