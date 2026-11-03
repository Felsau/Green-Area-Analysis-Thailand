"""Attested A4.1 Local JWT/queue/recovery and existing LDD regression checks.

Fresh synthetic rows only. No lease backdating, migration, credentials in output,
publication or deletion of pre-existing files. Container faults target owned IDs.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import io
import json
import logging
from pathlib import Path
import secrets
import sys
import time
from uuid import uuid4
import zipfile

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
spec=importlib.util.spec_from_file_location('a4_lifecycle_checks',HERE/'geotiff_prepare_checks.py')
checks=importlib.util.module_from_spec(spec);sys.modules[spec.name]=checks;spec.loader.exec_module(checks)
a4=checks.a4;m=a4.m


def run(root,targets):
    logging.disable(logging.CRITICAL)
    demo=checks.demo_module.Demo(root);local=demo.local
    out=local.output/('lifecycle-'+demo.run);out.mkdir();initial=checks.source();rows=[];events=[]
    literal=m.t2.t1.literal;api=None;paused=set()
    def check(name,value):
        rows.append({'name':name,'status':'Pass' if value else 'Fail'});print(json.dumps(rows[-1]),flush=True)
        if not value:raise AssertionError(name)
    def sql(query):return local.sql(query,read_only=True)
    def state(jid):return sql('SELECT to_jsonb(j) FROM gis.jobs j WHERE id='+literal(jid)+'::uuid')
    def wait(test,seconds=120):return m.wait_for(test,seconds)
    def req(method,path,body=None,**kw):
        h={**headers,'Idempotency-Key':str(uuid4()),**kw.pop('headers',{})}
        r=api.request(method,'/gis'+path,json=body,headers=h,**kw)
        if r.status_code not in (200,201,202):raise RuntimeError('HTTP_'+str(r.status_code)+'_'+path.split('/')[-1])
        return r.json()
    def rpc(identity,action,payload=None,name='gis_geotiff_prepare_worker'):
        return identity.client.rpc(name,{'p_action':action,'p_payload':payload or {}}).execute().data
    def denied(name,call):
        try:call()
        except Exception as e:
            check(name,str(getattr(e,'code',''))=='42501' or str(getattr(e,'message','')).startswith(('GIS_STALE_LEASE','GIS_WORKER_IDENTITY_MISMATCH','GIS_WORKER_PROTOCOL_MISMATCH')));return
        check(name,False)
    def start(factory):
        w=factory();demo.workers.append(w);wait(lambda:w.has('ready') or w.has('fatal'),30)
        check('owned_linux_ready_'+str(len(rows)),w.has('ready'));return w
    def close(w):
        if w.cid in paused:local.db.runtime.docker(['unpause',w.cid]);paused.remove(w.cid)
        w.close();events.extend(w.events);demo.workers.remove(w)
    def payload(d,e):
        p=req('GET','/editions/'+e['id']+'/geotiff-prepared')
        return {'expected_dataset_revision':d['revision'],'expected_input_revision':e['input_revision'],
            'input_hash':e['input_hash'],'validation_result_id':p['validation_result_id'],
            'province':d['province'],'data_year':d['data_year'],'month':d['month']}
    def upload(d,raw):
        req('POST','/datasets/'+d['id']+'/geotiff-uploads',headers={'Content-Type':'image/tiff'},content=raw,
            params={'expected_revision':d['revision'],'crs':'EPSG:4326','profile':'ndvi_ready'})
        e=next(e for e in req('GET','/datasets/'+d['id']+'/editions',params={'limit':100})['data'] if e['upload']['sha256']==hashlib.sha256(raw).hexdigest())
        j=req('POST','/editions/'+e['id']+'/validation-jobs',{'expected_revision':e['input_revision']})
        wait(lambda:state(j['id'])['state'] in ('succeeded','failed'))
        check('native_validation_before_prepare',state(j['id'])['state']=='succeeded');return req('GET','/editions/'+e['id'])
    try:
        check('initial_queue_idle',sql("SELECT to_jsonb(count(*)=0) FROM gis.jobs WHERE state IN ('queued','running')"))
        demo.accounts(secrets.token_urlsafe(24));u=demo.users['admin']
        token=local.client(demo.anon).auth.sign_in_with_password({'email':u['email'],'password':u['password']}).session.access_token
        headers={'Authorization':'Bearer '+token};api=local.api();api.app.state.gis_geotiff_prepared_store=local.geotiff_prepared_store
        t=json.loads(targets.read_text());raw=(targets.parent/'fixtures/large.tif').read_bytes()
        check('large_fixture_sha',hashlib.sha256(raw).hexdigest()==t['manifest']['large']['sha256'])
        validator=start(lambda:checks.demo_module.p.GeoTiffContainer(local))
        e=upload(t['ndvi'],raw);d=t['ndvi'];body=payload(d,e)
        j=req('POST','/editions/'+e['id']+'/geotiff-prepare-jobs',body)
        time.sleep(1)
        check('legacy_validator_cannot_claim_geo_prepare',state(j['id'])['state']=='queued' and state(j['id'])['attempt_count']==0)
        close(validator)
        first=start(lambda:a4.prepare_container(local))
        # Event is emitted immediately after the actual atomic JWT claim. Poll
        # locally at 1ms, then freeze this exact owned container before native
        # completion. No production worker or unknown container can be targeted.
        end=time.monotonic()+15
        while not first.has('claimed',j['id']) and time.monotonic()<end:time.sleep(.001)
        local.db.runtime.docker(['pause',first.cid]);paused.add(first.cid)
        frozen=state(j['id']);check('real_worker_claim_before_kill',frozen['state']=='running' and frozen['worker_id']==first.identity.subject)
        local.db.runtime.verify_worker(first.cid,first.policy)
        local.db.runtime.docker(['unpause',first.cid]);paused.remove(first.cid)
        local.db.runtime.docker(['kill','--signal','SIGKILL',first.cid]);first.proc.wait(timeout=15)
        check('actual_sigkill_leaves_durable_running_job',first.proc.returncode!=0 and state(j['id'])['state']=='running')
        close(first)
        # Closing the HTTP client does not remove the durable queue item.
        api.close();api=local.api();api.app.state.gis_geotiff_prepared_store=local.geotiff_prepared_store
        replacement=start(lambda:a4.prepare_container(local))
        wait(lambda:state(j['id'])['state']=='succeeded',110)
        final=state(j['id']);attempts=sql('SELECT jsonb_agg(to_jsonb(a) ORDER BY attempt_no) FROM gis.attempts a WHERE job_id='+literal(j['id'])+'::uuid')
        check('replacement_recovers_real_lease_and_native_success',final['attempt_count']==2 and [a['state'] for a in attempts]==['expired','succeeded'])
        denied('stale_worker_complete_fenced',lambda:rpc(first.identity,'complete',{'job_id':j['id'],'lease_token':frozen['lease_token'],'report':{}}))
        check('single_result_after_recovery',sql('SELECT to_jsonb(count(*)=1) FROM gis.results WHERE job_id='+literal(j['id'])+'::uuid'))
        verify=req('POST','/editions/'+e['id']+'/geotiff-prepare-verification',{'job_id':j['id']})
        check('one_million_pixel_verified_capacity',verify['ready_for_review'] and verify['summary']['statistics']['valid_pixels']==1000000 and verify['summary']['statistics']['mean']==.5)
        replacement.signal('SIGINT');replacement.proc.wait(timeout=20)
        check('real_geo_daemon_sigint',replacement.proc.returncode==0 and replacement.has('stopped'));close(replacement)
        # A monthly dataset with annual-tagged source passes the original upload
        # validator but MUST be rejected by this new preparation provider.
        month=sql("SELECT to_jsonb(mon) FROM generate_series(1,12)mon WHERE NOT EXISTS(SELECT 1 FROM gis.datasets WHERE province='Bangkok Metropolis' AND data_year="+str(t['year'])+" AND month=mon AND kind='geotiff' AND purpose='ndvi') ORDER BY mon LIMIT 1")
        d2=req('POST','/datasets',{'province':d['province'],'data_year':d['data_year'],'month':month,'kind':'geotiff','purpose':'ndvi','title':'A4 lifecycle '+demo.run})
        validator=start(lambda:checks.demo_module.p.GeoTiffContainer(local));e2=upload(d2,(targets.parent/'fixtures/ndvi_ready.tif').read_bytes());close(validator)
        b2=payload(d2,e2);j2=req('POST','/editions/'+e2['id']+'/geotiff-prepare-jobs',b2)
        who=[m.identity_module.provision(local),m.identity_module.provision(local)]
        denied('worker_subject_spoofing_denied',lambda:rpc(who[0],'claim',{'worker_id':str(uuid4())}))
        with ThreadPoolExecutor(max_workers=2) as pool:claims=list(pool.map(lambda i:rpc(i,'claim'),who))
        wins=[(i,c['job']) for i,c in zip(who,claims) if c.get('job')]
        check('two_jwt_concurrent_claims_exactly_once',len(wins)==1 and wins[0][1]['id']==j2['id'] and state(j2['id'])['attempt_count']==1)
        identity,claimed=wins[0];lease={'job_id':j2['id'],'lease_token':claimed['lease_token']}
        from gis_worker.geotiff_prepare_provider import failure
        denied('native_validator_protocol_cannot_complete_prepare',lambda:rpc(identity,'complete',{**lease,'report':{}},name='gis_geotiff_worker'))
        before=state(j2['id'])['lease_until'];time.sleep(1);rpc(identity,'heartbeat',{**lease,'progress':10})
        check('jwt_heartbeat_extends_lease',state(j2['id'])['lease_until']>before)
        report=failure(claimed['prepare_request'],'NATIVE_TIMEOUT')
        check('transient_retry_via_real_jwt_rpc',rpc(identity,'fail',{**lease,'error_code':'transient','report':report})['state']=='queued')
        denied('old_attempt_token_after_retry_fenced',lambda:rpc(identity,'complete',{**lease,'report':report}))
        check('retry_backoff_not_immediately_claimable',rpc(who[1],'claim')['job'] is None)
        for attempt in (2,3):
            wait(lambda:(c if (c:=rpc(who[1],'claim')).get('job') else None),12)
            current=state(j2['id']);packet=sql('SELECT gis.geotiff_prepare_packet('+literal(j2['id'])+'::uuid)')
            rpc(who[1],'fail',{'job_id':j2['id'],'lease_token':current['lease_token'],'error_code':'transient','report':failure(packet,'NATIVE_TIMEOUT')})
        check('retry_budget_three_attempts',state(j2['id'])['state']=='failed' and state(j2['id'])['attempt_count']==3)
        retry_body={**b2,'job_id':j2['id'],'reason':'Synthetic RPC transport-failure retry budget test'}
        rj=req('POST','/editions/'+e2['id']+'/geotiff-prepare-retry',retry_body)
        r=api.post('/gis/editions/'+e2['id']+'/geotiff-prepare-retry',json=retry_body,headers={**headers,'Idempotency-Key':str(uuid4())})
        check('explicit_retry_child_only_once',rj['parent_job_id']==j2['id'] and r.status_code==409)
        w=start(lambda:a4.prepare_container(local));wait(lambda:state(rj['id'])['state']=='failed')
        bad=sql('SELECT to_jsonb(a) FROM gis.attempts a WHERE job_id='+literal(rj['id'])+'::uuid ORDER BY attempt_no DESC LIMIT 1')
        check('actual_native_period_mismatch_is_invalid_not_transient',bad['error_code']=='invalid_data' and bad['validation_report']['error_code']=='PREPARE_PERIOD_SCOPE_MISMATCH')
        w.signal('SIGTERM');w.proc.wait(timeout=20);check('real_geo_daemon_sigterm',w.proc.returncode==0 and w.has('stopped'));close(w)
        denied('worker_cannot_certify',lambda:who[0].client.rpc('gis_geotiff_verify_complete',{'p_actor':who[0].subject,'p_request_id':str(uuid4()),'p_job':j['id'],'p_proof':{}}).execute())
        denied('worker_cannot_admin_rpc',lambda:who[0].client.rpc('gis_command',{'p_actor':who[0].subject,'p_request_id':str(uuid4()),'p_operation':'grant_officer','p_payload':{}}).execute())
        denied('worker_cannot_legacy_write',lambda:who[0].client.table('profiles').update({'role':'admin'}).eq('id',who[0].subject).execute())
        # Actual original LDD upload/prepare/RO trusted verification after041.
        lyear=sql("SELECT to_jsonb(y) FROM generate_series(1980,2027)y WHERE NOT EXISTS(SELECT 1 FROM gis.datasets WHERE province='Bangkok Metropolis' AND data_year=y AND kind='ldd_shapefile') ORDER BY y LIMIT 1")
        ld=req('POST','/datasets',{'province':'Bangkok Metropolis','data_year':lyear,'month':0,'kind':'ldd_shapefile','purpose':'landuse','title':'A4 LDD regression '+demo.run})
        buf=io.BytesIO((REPO/'green-area-backend/gis_worker/fixtures/ldd_valid.zip').read_bytes())
        with zipfile.ZipFile(buf,'a') as z:z.comment=('A4 regression '+demo.run).encode()
        req('POST','/datasets/'+ld['id']+'/ldd-uploads',headers={'Content-Type':'application/zip'},content=buf.getvalue(),params={'expected_revision':ld['revision'],'crs':'EPSG:32647','encoding':'auto'})
        le=req('GET','/datasets/'+ld['id']+'/editions',params={'limit':100})['data'][0]
        lw=start(lambda:checks.demo_module.p.p.m.LddContainer(local))
        lj=req('POST','/editions/'+le['id']+'/validation-jobs',{'expected_revision':le['input_revision']});wait(lambda:state(lj['id'])['state']=='succeeded');close(lw)
        le=req('GET','/editions/'+le['id']);check('legacy_ldd_still_validated',le['state']=='validated')
        lw=start(lambda:a4.a3.a2.PrepareContainer(local))
        lp={'expected_dataset_revision':ld['revision'],'expected_input_revision':le['input_revision'],
            'input_hash':le['input_hash'],'province':ld['province'],'data_year':ld['data_year']}
        lj=req('POST','/editions/'+le['id']+'/prepare-jobs',lp);wait(lambda:state(lj['id'])['state']=='succeeded')
        verified=req('POST','/editions/'+le['id']+'/prepare-verification',{'job_id':lj['id']})
        check('legacy_ldd_prepare_verifier_publication_readiness_preserved',verified['ready_for_publication'] and verified['summary']['total_area_m2']==6400)
        close(lw);check('ldd_not_auto_activated',req('GET','/datasets/'+ld['id'])['active_edition_id'] is None)
        check('queue_idle_after_tests',sql("SELECT to_jsonb(count(*)=0) FROM gis.jobs WHERE state IN ('queued','running')"))
    except Exception as error:
        rows.append({'name':'execution','status':'Fail','diagnostic':str(error)[:200]});print(json.dumps(rows[-1]),flush=True)
    finally:
        if api is not None:api.close()
        for w in demo.workers:
            if w.cid in paused:local.db.runtime.docker(['unpause',w.cid]);paused.remove(w.cid)
        for w in demo.workers:events.extend(w.events)
        clean=demo.close();final=checks.source()
        (out/'results.json').write_text(json.dumps({'rows':rows,'source':initial,'source_unchanged':initial==final,'events':events,'cleanup':clean,'synthetic_only':True,'retry_faults':'JWT RPC NATIVE_TIMEOUT injection; not an actual native wall timeout'},indent=2),encoding='utf-8')
    return 0 if clean and initial==final and rows and all(r['status']=='Pass' for r in rows) else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runtime-dir',type=Path,required=True);p.add_argument('--targets',type=Path,required=True)
    args=p.parse_args();raise SystemExit(run(args.runtime_dir,args.targets))
