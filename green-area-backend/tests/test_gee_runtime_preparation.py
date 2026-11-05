"""Offline identity/transport tests. Fake leases never authorize Google."""
from copy import deepcopy
from dataclasses import replace
import sys
import json
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest

from gis_worker.gee_runtime_identity import (CredentialBoundaryError, DisabledGoogleCredentials,
    InjectedCredentials, RuntimeBinding)
from gis_worker.gee_runtime_transport import PreparedInjectedTransport, require_live_egress
from gis_worker.gee_live_contracts import Request, geometry_digest
from tests.test_gee_execution_safety import Ledger, Port, packet


def claim(scenario='candidate', product='ndvi'):
    job, output = packet(scenario, product)
    subject = str(uuid4())
    job.update(worker_id=subject, attempt_number=1, manifest={
        'schema_version':8, 'provider':'gee_safety_rehearsal',
        'session_id':job['session_id'], 'policy_sha256':job['policy_sha256']})
    return job, output, subject


def credentials(job, subject, **kwargs):
    binding = RuntimeBinding.from_claim(job, subject)
    provider = InjectedCredentials(binding, **kwargs)
    return binding, provider, provider.issue(binding)


@pytest.mark.parametrize('latitude',[13.0,1e-6])
def test_v2_geometry_canonicalization_accepts_integral_and_exponent_numbers(latitude):
    from gis_worker.gee_contracts import geometry_digest as old_digest
    job,_,subject=claim()
    geometry={'type':'Polygon','coordinates':[[[100.0,latitude],[100.01,latitude],
        [100.01,latitude+.01],[100.0,latitude+.01],[100.0,latitude]]]}
    value=deepcopy(job['request']);value['scope']['geometry_sha256']=geometry_digest(geometry)
    request=Request.model_validate(value)
    job.update(geometry=geometry,request=request.model_dump(mode='json'),
        semantic_request_sha256=request.request_hash())
    assert old_digest(geometry)!=geometry_digest(geometry)
    assert RuntimeBinding.from_claim(job,subject).geometry_sha256==geometry_digest(geometry)


def test_real_credentials_and_live_egress_cannot_be_enabled(monkeypatch):
    monkeypatch.setenv('GOOGLE_APPLICATION_CREDENTIALS', '/not-mounted/fake-adc.json')
    channel = DisabledGoogleCredentials()
    assert channel.APPROVED_PROJECTS == () and channel.APPROVED_PRINCIPAL is None
    for method in ('issue','renew','revoke','authorize'):
        with pytest.raises(CredentialBoundaryError,match='DISABLED'):
            getattr(channel,method)(project='payload-approval', verified=True)
    assert 'ee' not in sys.modules and 'google.auth' not in sys.modules


@pytest.mark.parametrize('arguments',[[],['--live'],['--unknown']])
def test_default_or_unapproved_entrypoint_exits_before_reading_stdin(arguments):
    script=Path(__file__).resolve().parents[1]/'gis_worker/gee_runtime_probe.py'
    result=subprocess.run([sys.executable,'-I','-B',str(script),*arguments],
        input='FAKE_ONLY_SENTINEL_NOT_A_CREDENTIAL',capture_output=True,text=True,timeout=5)
    assert result.returncode==78
    assert json.loads(result.stdout)=={'live_enabled':False,'status':'disabled'}
    assert 'SENTINEL' not in result.stdout+result.stderr


@pytest.mark.parametrize('destination', ['https://192.0.2.1/','https://unapproved.invalid/',
    'http://127.0.0.1/','https://[2001:db8::1]/','file:///private','https://redirect.invalid/'])
def test_destination_dns_redirect_or_caller_flags_never_open_live_egress(destination):
    with pytest.raises(ValueError,match='EGRESS_BLOCKED'):
        require_live_egress(destination, verified=True, restricted=True)


@pytest.mark.parametrize('field',['worker','session','policy','geometry','revision','semantic','protocol'])
def test_untrusted_claim_lineage_is_rejected(field):
    job,_,subject = claim();bad = deepcopy(job)
    if field=='worker':bad['worker_id']=str(uuid4())
    elif field=='session':bad['session_id']=str(uuid4())
    elif field=='policy':bad['policy_sha256']='0'*64
    elif field=='geometry':bad['geometry']['coordinates'][0][0][0]+=.01
    elif field=='revision':bad['input_revision']=2
    elif field=='semantic':bad['semantic_request_sha256']='0'*64
    else:bad['manifest']['provider']='gee_contract_mock'
    with pytest.raises((ValueError,KeyError)):RuntimeBinding.from_claim(bad,subject)


@pytest.mark.parametrize('field',['worker_subject','session_id','job_id','attempt_number','project',
    'principal','request_sha256','method_sha256','geometry_sha256','lease_sha256','policy_sha256'])
def test_fake_credentials_are_bound_to_complete_context(field):
    job,_,subject=claim();binding,provider,token=credentials(job,subject)
    bad=binding.model_dump(mode='json')
    if field in ('worker_subject','session_id','job_id'):bad[field]=str(uuid4())
    elif field=='attempt_number':bad[field]=2
    elif field=='project':bad['project']={'project_id':'synthetic-other','project_number':'999999999',
        'principal':'worker@synthetic-other.iam.gserviceaccount.com','readiness':'not_verified'}
    elif field=='principal':bad['project']['principal']='other@'+bad['project']['project_id']+'.iam.gserviceaccount.com'
    else:bad[field]='0'*64
    bad=RuntimeBinding.model_validate(bad)
    with pytest.raises(CredentialBoundaryError,match='BINDING_REJECTED'):provider.authorize(token,bad)


def test_fake_token_expiry_renewal_revocation_and_no_serialized_authority():
    job,_,subject=claim();now=[0]
    binding,provider,token=credentials(job,subject,clock=lambda:now[0])
    assert repr(token)=='<FakeGoogleLease injected-only redacted>'
    with pytest.raises(CredentialBoundaryError,match='ISSUER'):provider.authorize(replace(token,expires_at=9999),binding)
    other=InjectedCredentials(binding,clock=lambda:now[0])
    with pytest.raises(CredentialBoundaryError,match='ISSUER'):other.authorize(token,binding)
    new=provider.renew(token,binding)
    with pytest.raises(CredentialBoundaryError,match='REVOKED'):provider.authorize(token,binding)
    provider.authorize(new,binding);now[0]=31
    with pytest.raises(CredentialBoundaryError,match='EXPIRED'):provider.authorize(new,binding)
    with pytest.raises(CredentialBoundaryError,match='EXPIRED'):provider.renew(new,binding)


@pytest.mark.parametrize('ttl',[0,31,True,float('inf'),float('nan')])
def test_unbounded_fake_token_ttl_is_rejected(ttl):
    job,_,subject=claim();binding,provider,_=credentials(job,subject)
    with pytest.raises(CredentialBoundaryError):provider.issue(binding,ttl_seconds=ttl)


@pytest.mark.parametrize('scenario',['candidate','zero','no_data','all_masked','incomplete'])
@pytest.mark.parametrize('product',['ndvi','lst'])
def test_each_compute_retry_reference_is_separately_accounted(scenario,product):
    job,out,subject=claim(scenario,product);_,provider,token=credentials(job,subject);ledger=Ledger()
    value=PreparedInjectedTransport(ledger,job,subject,provider,token).run(
        [('compute',Port(out)),('sdk_retry',Port(out)),('reference',Port(out))])
    assert len(ledger.rows)==3 and all(r['state']=='completed' for r in ledger.rows.values())
    assert value['live_enabled'] is False and value['base']['output']==out.model_dump(mode='json')
    assert len(value['receipts'])==3 and not out.content.publishable and out.content.synthetic
    assert 'credential' not in str(value).lower() and 'FakeGoogleLease' not in str(value)


@pytest.mark.parametrize('when',['before','after_reserve','during_evaluation'])
def test_revoked_or_expired_credential_stops_attempt_and_preserves_uncertainty(when):
    job,out,subject=claim();now=[0];binding,provider,token=credentials(job,subject,clock=lambda:now[0])
    ledger=Ledger();port=Port(out,lambda:now.__setitem__(0,31) if when=='during_evaluation' else None)
    def call(action,payload):
        value=ledger(action,payload)
        if when=='after_reserve' and action=='reserve':provider.revoke(token)
        return value
    transport=PreparedInjectedTransport(call,job,subject,provider,token,clock=lambda:now[0])
    if when=='before':provider.revoke(token)
    with pytest.raises(CredentialBoundaryError):transport.run([('compute',port)])
    assert port.calls==(1 if when=='during_evaluation' else 0)
    assert len(ledger.rows)==(0 if when=='before' else 1)
    assert all(r['state']=='uncertain' for r in ledger.rows.values())


def test_unknown_plan_and_unaccounted_transport_fail_closed():
    job,out,subject=claim();_,provider,token=credentials(job,subject);ledger=Ledger()
    transport=PreparedInjectedTransport(ledger,job,subject,provider,token)
    for plan in ([],{},[('compute',Port(out))]*33):
        with pytest.raises(ValueError):transport.run(plan)
    with pytest.raises(ValueError):transport.run([('unknown_kind',Port(out))])
    with pytest.raises(ValueError):transport.run([('compute',object())])
    assert len(ledger.rows)==1 and next(iter(ledger.rows.values()))['state']=='uncertain'


def test_ambiguous_finish_and_restart_cannot_reset_request_budget():
    job,out,subject=claim();_,provider,token=credentials(job,subject);ledger=Ledger()
    def call(action,payload):
        if action=='finished':raise TimeoutError('private details must not be persisted')
        return ledger(action,payload)
    for _ in range(32):
        with pytest.raises(TimeoutError):PreparedInjectedTransport(call,job,subject,provider,token).run([('sdk_retry',Port(out))])
    with pytest.raises(ValueError,match='BUDGET'):PreparedInjectedTransport(call,job,subject,provider,token).run([('reference',Port(out))])
    assert len(ledger.rows)==32 and all(r['state']=='uncertain' for r in ledger.rows.values())
