"""Offline accounting/scientific tests. No Google execution or account claim."""
from datetime import date
import sys
from uuid import UUID, uuid4

import pytest

from gis_worker.gee_execution_safety import (AccountedTransport, SafetyError,
    LiveResultBinding, TrustedLiveEnvelope, UnapprovedPolicy, require_real_transport, report)
from gis_worker.gee_live_contracts import digest, queue_report
from gis_worker.gee_live_bridge import InjectedBridge
from gis_worker.gee_live_injected import fixture, InjectedSDK, InjectedTransport
from gis_worker.gee_safety_worker import InjectedChildPort, RehearsalWorker
from gis_worker.worker import WorkerError


def packet(scenario='candidate', product='ndvi'):
    request, geometry, raw = fixture('f'*12, product=product, scenario=scenario)
    output = InjectedBridge(sdk=InjectedSDK(), transport=InjectedTransport(raw),
        authorization=lambda:request.project, as_of=date(2026,1,1)).compute(request,geometry)
    job={'id':str(uuid4()),'lease_token':str(uuid4()),'session_id':str(uuid4()),
        'policy_sha256':digest(UnapprovedPolicy().model_dump(mode='json')),
        'input_hash':'1'*64,'input_revision':1,'semantic_request_sha256':request.request_hash(),
        'request':request.model_dump(mode='json'),'geometry':geometry,'job_remaining_seconds':180}
    return job,output


class Port:
    OFFLINE_INJECTED=True
    def __init__(self,output,run=lambda:None):self.output,self.run,self.calls=output,run,0
    def evaluate(self,*,timeout_seconds):
        assert 0<timeout_seconds<=120
        self.calls+=1;self.run();return self.output


class Ledger:
    """Unit double only; real atomic authority tested separately on Local SQL."""
    def __init__(self):self.rows={};self.keys={};self.closed=False
    def __call__(self,action,payload):
        if self.closed and action!='uncertain':raise SafetyError('GIS_SAFETY_SESSION_CLOSED')
        if action=='reserve':
            key=payload['request_key']
            if key in self.keys:return self.rows[self.keys[key]].copy()
            if len(self.rows)>=32:self.closed=True;return {'granted':False}
            rid=str(uuid4());self.keys[key]=rid;self.rows[rid]={'request_id':rid,'state':'reserved'}
        else:
            rid=payload['request_id'];row=self.rows[rid]
            if action=='attempted':
                if row['state']!='reserved':raise SafetyError('GIS_SAFETY_ONE_USE')
                row['state']='attempted'
            elif action=='finished':row.update(state='completed',evidence_sha256=payload['evidence_sha256'])
            elif action=='uncertain' and row['state']!='completed':row['state']='uncertain'
        return self.rows[rid].copy()


def test_live_policy_cannot_be_forged_or_enabled():
    policy=UnapprovedPolicy()
    assert policy.project_id is None and policy.google_principal is None
    with pytest.raises(SafetyError,match='NOT_APPROVED'):TrustedLiveEnvelope(policy=policy).require_authority()
    with pytest.raises(SafetyError,match='DISABLED'):require_real_transport()
    for key,value in [('project_id','invented'),('project_number','123'),('google_principal','invented'),('live_enabled',True),('account_verified',True),('transport_verified',True)]:
        with pytest.raises(ValueError):UnapprovedPolicy.model_validate(policy.model_dump()|{key:value})


def test_full_claimed_lineage_is_still_not_trusted_live_authority():
    job,out=packet()
    binding=LiveResultBinding(worker_subject=uuid4(),job_id=UUID(job['id']),attempt_number=1,
        result_id=uuid4(),lease_token=UUID(job['lease_token']),input_revision=1,input_hash=job['input_hash'],
        method_sha256=digest(out.content.request.method.model_dump(mode='json')),
        transport_evidence_sha256='2'*64,claimed_output=out)
    with pytest.raises(SafetyError):TrustedLiveEnvelope(policy=UnapprovedPolicy(),binding=binding).require_authority()
    value=binding.model_dump(mode='json')
    for key,changed in [('method_sha256','0'*64),('input_revision',2),('transport_verified',True),('attempt_number',3),('publishable',True)]:
        with pytest.raises(ValueError):LiveResultBinding.model_validate(value|{key:changed})


@pytest.mark.parametrize('scenario',['candidate','zero','no_data','all_masked','incomplete'])
@pytest.mark.parametrize('product',['ndvi','lst'])
def test_accounted_output_preserves_science(scenario,product):
    job,output=packet(scenario,product);ledger=Ledger();transport=AccountedTransport(ledger,job)
    actual,receipt=transport.execute(Port(output));wrapped=transport.report(actual,[receipt])
    assert wrapped['base']==queue_report(job,output)
    assert wrapped['execution']=='rehearsal' and wrapped['live_enabled'] is False
    assert actual.content.synthetic and not actual.content.publishable
    assert len(ledger.rows)==1 and next(iter(ledger.rows.values()))['state']=='completed'
    if scenario=='zero':assert actual.content.statistics.mean==0
    if scenario in ('no_data','all_masked','incomplete'):assert actual.content.statistics.mean is None


def test_receipt_capability_is_not_user_payload_or_other_transport():
    job,out=packet();a=AccountedTransport(Ledger(),job);b=AccountedTransport(Ledger(),job)
    output,receipt=a.execute(Port(out))
    for receipts in ([],[{'request_id':receipt.request_id}],[receipt]*33):
        with pytest.raises(SafetyError):a.report(output,receipts)
    with pytest.raises(SafetyError):b.report(output,[receipt])
    _,other=packet('zero')
    with pytest.raises(SafetyError,match='MISMATCH'):a.report(other,[receipt])


def test_reserve_replay_cannot_evaluate_twice():
    job,out=packet();ledger=Ledger();key=str(uuid4());p=Port(out)
    AccountedTransport(ledger,job).execute(p,request_key=key)
    with pytest.raises(SafetyError,match='ONE_USE'):AccountedTransport(ledger,job).execute(p,request_key=key)
    assert p.calls==1 and len(ledger.rows)==1


def test_uncertainty_and_new_keys_do_not_refund_budget():
    job,out=packet();ledger=Ledger()
    def fail():raise TimeoutError('private provider detail')
    for _ in range(32):
        with pytest.raises(TimeoutError):AccountedTransport(ledger,job).execute(Port(out,fail))
    with pytest.raises(SafetyError,match='BUDGET'):AccountedTransport(ledger,job).execute(Port(out))
    assert len(ledger.rows)==32 and all(r['state']=='uncertain' for r in ledger.rows.values())


@pytest.mark.parametrize('elapsed,remaining,code',[(120,180,'REQUEST_TIMEOUT'),(30,30,'JOB_TIMEOUT'),(181,180,'REQUEST_TIMEOUT')])
def test_elapsed_and_recovery_remaining_deadline(elapsed,remaining,code):
    job,out=packet();job['job_remaining_seconds']=remaining;now=[0];ledger=Ledger()
    def advance():now[0]+=elapsed
    t=AccountedTransport(ledger,job,clock=lambda:now[0])
    with pytest.raises(SafetyError,match=code):t.execute(Port(out,advance))
    assert next(iter(ledger.rows.values()))['state']=='uncertain'


def test_unaccountable_finish_stops_without_re_evaluation():
    job,out=packet();ledger=Ledger();p=Port(out)
    def call(action,payload):
        if action=='finished':raise RuntimeError('accounting unavailable')
        return ledger(action,payload)
    with pytest.raises(RuntimeError):AccountedTransport(call,job).execute(p)
    assert p.calls==1 and next(iter(ledger.rows.values()))['state']=='uncertain'


def test_real_transport_and_arbitrary_native_scenario_denied():
    job,out=packet();ledger=Ledger()
    with pytest.raises(SafetyError,match='DISABLED'):AccountedTransport(ledger,job).execute(object())
    assert not ledger.rows
    with pytest.raises(WorkerError):InjectedChildPort(job,scenario='../anything')
    for kind in ('live','url','command'):
        with pytest.raises(SafetyError):report(job,queue_report(job,out),failure_kind=kind)


@pytest.mark.skipif(sys.platform!='linux',reason='real isolated child requires Linux')
@pytest.mark.parametrize('product',['ndvi','lst'])
@pytest.mark.parametrize('scenario',['candidate','zero','no_data','incomplete'])
def test_real_linux_child_science(product,scenario):
    job,_=packet(product=product)
    output=InjectedChildPort(job,scenario=scenario).evaluate(timeout_seconds=5)
    assert output.content.execution=='injected' and not output.content.publishable
    assert output.content.status==('candidate' if scenario in ('candidate','zero') else scenario)
    if scenario=='zero':assert output.content.statistics.mean==0


@pytest.mark.skipif(sys.platform!='linux',reason='real isolated child requires Linux')
def test_real_linux_child_hard_timeout():
    job,_=packet()
    with pytest.raises(WorkerError,match='NATIVE_TIMEOUT'):
        InjectedChildPort(job,scenario='hang').evaluate(timeout_seconds=.3)


@pytest.mark.skipif(sys.platform!='linux',reason='real isolated child requires Linux')
def test_real_linux_child_shutdown_is_bounded():
    job,_=packet();owner=RehearsalWorker(None);owner._stop_event.set()
    with pytest.raises(WorkerError,match='WORKER_SHUTDOWN'):
        InjectedChildPort(job,scenario='hang',owner=owner).evaluate(timeout_seconds=5)


@pytest.mark.skipif(sys.platform!='linux',reason='real isolated child requires Linux')
@pytest.mark.parametrize('event,code,kind',[('_stop_event','WORKER_SHUTDOWN','transient'),('_lease_lost','NATIVE_PROCESS_FAILED','lease_expired')])
def test_worker_automatically_binds_native_stop_and_lease_events(event,code,kind):
    job,_=packet();ledger=Ledger()
    worker=RehearsalWorker(None,injected_port=lambda job:InjectedChildPort(job,scenario='hang'))
    worker.call=ledger;request=worker.build_native_request(job);getattr(worker,event).set()
    value=worker._execute_native(request)
    assert value['valid'] is False and value['error_code']==code and value['failure_kind']==kind
    assert all(r['state']=='uncertain' for r in ledger.rows.values())
