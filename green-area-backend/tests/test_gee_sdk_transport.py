"""Real pinned SDK and client retry machinery, synthetic HTTP responses only."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from gis_worker.gee_live_contracts import Request, digest, queue_report
from gis_worker.gee_live_injected import fixture
from gis_worker.gee_sdk_transport import (FakeHTTPWire, PhysicalHTTP, FakeSDKAdapter,
    SDKBoundaryError, SANDBOX, FAKE_PRINCIPAL, require_genuine_startup)


def packet(product='ndvi', month=0, scenario='candidate'):
    request, geometry, raw = fixture(uuid4().hex[:12], product=product, month=month, scenario=scenario)
    request = Request.model_validate(request.model_dump(mode='json') | {'project': {
        'project_id': SANDBOX[0], 'project_number': SANDBOX[1], 'principal': FAKE_PRINCIPAL}})
    return request, geometry, raw, {'id': str(uuid4()), 'lease_token': str(uuid4()),
        'request': request.model_dump(mode='json'), 'job_remaining_seconds': 180,
        'input_hash': 'a'*64, 'input_revision': 1, 'semantic_request_sha256': request.request_hash()}


class Recorder:
    def __init__(self, budget=32):
        self.rows, self.events, self.budget, self.sealed = {}, [], budget, None

    def __call__(self, action, value):
        self.events.append(action)
        if action == 'reserve':
            if len(self.rows) >= self.budget:
                return {'granted': False}
            rid = str(uuid4())
            self.rows[rid] = {'state': 'reserved', 'kind': value['kind']}
            return {'request_id': rid, 'state': 'reserved'}
        if action == 'seal':
            assert set(value['receipts']) == set(self.rows)
            assert all(x['state'] == 'recorded' for x in self.rows.values())
            self.sealed = value
            return value
        row = self.rows[value['request_id']]
        if action == 'attempted':
            assert row['state'] == 'reserved'
            row['state'] = 'attempted'
        elif action == 'response':
            assert row['state'] == 'attempted'
            row.update(value)
            row['state'] = 'recorded'
        elif action == 'uncertain':
            row['state'] = 'uncertain'
        return {'state': row['state']}


def run_sdk(product='ndvi', month=0, scenario='candidate', statuses=(), refresh=False):
    req, geom, raw, job = packet(product, month, scenario)
    recorder = Recorder()
    wire = FakeHTTPWire(raw, responses=statuses, refresh=refresh)
    http = PhysicalHTTP(recorder, job, wire)
    # SDK retry backoff is real; eliminate randomized sleeping in unit tests.
    with patch('time.sleep', lambda *_: None):
        result = FakeSDKAdapter(http).compute(req, geom, as_of=date(2026, 1, 1))
    return result, recorder, wire, http


@pytest.mark.parametrize('product', ['ndvi','lst'])
@pytest.mark.parametrize('month', [0,2,12])
@pytest.mark.parametrize('scenario', ['candidate','zero','no_data','all_masked','incomplete'])
def test_actual_sdk_scientific_graph_and_synthetic_provenance(product, month, scenario):
    result, recorder, wire, http = run_sdk(product,month,scenario)
    assert result.content.synthetic and result.content.execution == 'injected'
    assert not result.content.publishable and result.content.request.scope.kind == 'sandbox_roi'
    assert result.content.statistics.mean == (0 if scenario == 'zero' else
        0.25 if product == 'ndvi' else 30) if scenario in ('candidate','zero') else result.content.statistics.mean is None
    categories = [c[0] for c in wire.calls]
    assert categories.count('discovery') == 2
    assert categories.count('algorithms') == categories.count('catalog') == categories.count('compute') == 1
    assert len(recorder.rows) == len(wire.calls) == 5
    assert recorder.events[-1] == 'seal'
    assert recorder.sealed['output']['output_sha256'] == result.output_sha256


@pytest.mark.parametrize('statuses,refresh,expected', [([503,200],False,6),([401,200],True,7)])
def test_sdk_internal_retry_and_authorized_http_refresh_intercepted(statuses,refresh,expected):
    _, r, wire, _ = run_sdk(statuses=statuses,refresh=refresh)
    assert len(wire.calls) == len(r.rows) == expected
    assert sum(x['kind']=='sdk_retry' for x in r.rows.values()) == 1
    if refresh:
        assert any(x[0]=='token' for x in wire.calls)
        assert all('offline-synthetic' not in json.dumps(x) for x in r.rows.values())


def test_budget_denial_precedes_wire_and_restart_does_not_refund():
    req, geom, raw, job=packet();r=Recorder(budget=2);wire=FakeHTTPWire(raw)
    with pytest.raises(Exception):FakeSDKAdapter(PhysicalHTTP(r,job,wire)).compute(req,geom,as_of=date(2026,1,1))
    assert len(wire.calls)==len(r.rows)==2
    with pytest.raises(SDKBoundaryError,match='BUDGET'):
        PhysicalHTTP(r,job,wire).request('https://earthengine.googleapis.com/$discovery/rest?version=v1')
    assert len(wire.calls)==2


def test_wire_send_requires_prior_durable_attempt():
    req,geom,raw,job=packet();r=Recorder();wire=FakeHTTPWire(raw)
    original=wire.send
    def check(*args):
        assert r.events[-1]=='attempted'
        return original(*args)
    wire.send=check
    FakeSDKAdapter(PhysicalHTTP(r,job,wire)).compute(req,geom,as_of=date(2026,1,1))


@pytest.mark.parametrize('action',['attempted','response'])
def test_missing_ack_is_uncertain_and_cannot_continue(action):
    _,_,raw,job=packet();r=Recorder();wire=FakeHTTPWire(raw)
    def callback(a,p):
        value=r(a,p)
        return {'state':'unknown'} if a==action else value
    http=PhysicalHTTP(callback,job,wire)
    with pytest.raises(SDKBoundaryError,match='ACK_REQUIRED'):
        http.request('https://earthengine.googleapis.com/$discovery/rest?version=v1')
    assert next(iter(r.rows.values()))['state']=='uncertain'
    assert len(wire.calls)==(0 if action=='attempted' else 1)


def test_slow_sql_ack_prevents_expired_request_send():
    _,_,raw,job=packet();r=Recorder();wire=FakeHTTPWire(raw);now=[0]
    def callback(a,p):
        v=r(a,p)
        if a=='attempted':now[0]=181
        return v
    with pytest.raises(SDKBoundaryError):
        PhysicalHTTP(callback,job,wire,clock=lambda:now[0]).request('https://earthengine.googleapis.com/$discovery/rest?version=v1')
    assert wire.calls==[]


def test_adapter_rejects_changed_period_or_geometry_before_init():
    req,geom,raw,job=packet();r=Recorder();wire=FakeHTTPWire(raw);adapter=FakeSDKAdapter(PhysicalHTTP(r,job,wire))
    with pytest.raises(ValueError):adapter.compute(req,{'type':'Point','coordinates':[100,13]},as_of=date(2026,1,1))
    other,*_=packet(month=2)
    with pytest.raises(SDKBoundaryError):adapter.compute(other,geom,as_of=date(2026,1,1))
    assert not r.rows and not wire.calls


def test_timeout_uncertainty_and_lost_response_ack_never_retry():
    _,_,raw,job=packet();r=Recorder();wire=FakeHTTPWire(raw)
    def uncertain(*_):raise TimeoutError('synthetic timeout')
    wire.send=uncertain;http=PhysicalHTTP(r,job,wire)
    with pytest.raises(TimeoutError):http.request('https://earthengine.googleapis.com/$discovery/rest?version=v1')
    assert len(r.rows)==1 and next(iter(r.rows.values()))['state']=='uncertain'
    with pytest.raises(SDKBoundaryError):http.request('https://earthengine.googleapis.com/$discovery/rest?version=v1')
    assert len(r.rows)==1


@pytest.mark.parametrize('uri', ['http://earthengine.googleapis.com','https://127.0.0.1/',
    'https://earthengine.googleapis.com.evil.invalid/', 'https://earthengine.googleapis.com:444/',
    'https://earthengine.googleapis.com/v1alpha/projects/innate-beacon-483307-v1/value:compute',
    'https://earthengine.googleapis.com/v1alpha/projects/green-area-gis-sandbox/algorithms?key=bad',
    'https://user@earthengine.googleapis.com/'])
def test_unknown_paths_project_redirect_credentials_fail_before_reserve(uri):
    _,_,raw,job=packet();r=Recorder();w=FakeHTTPWire(raw);h=PhysicalHTTP(r,job,w)
    with pytest.raises((ValueError,SDKBoundaryError)):h.request(uri)
    assert r.rows=={} and w.calls==[]


def test_no_real_mode_or_arbitrary_wire_or_runtime_flags():
    req,geom,raw,job=packet()
    for change in [{'execution':'live'},{'project':req.project.model_dump()|{'project_number':'122535800048'}}]:
        with pytest.raises(ValueError):PhysicalHTTP(Recorder(),job|{'request':job['request']|change},FakeHTTPWire(raw))
    with pytest.raises(SDKBoundaryError):PhysicalHTTP(Recorder(),job,object())
    with pytest.raises(SDKBoundaryError):require_genuine_startup(approved=True,network=True)


def test_sdk_uses_explicit_credentials_no_adc_and_restores_global_hooks():
    import ee,google.auth
    original=ee.deprecation._FetchDataCatalogStac
    with patch.object(google.auth,'default',side_effect=AssertionError('ADC forbidden')), \
         patch.object(ee.data,'get_persistent_credentials',side_effect=AssertionError('persistent forbidden')):
        run_sdk()
    assert ee.deprecation._FetchDataCatalogStac is original


def test_actual_serialized_graph_preserves_formulas():
    # The real SDK serializer, not a name-only mock graph, supplies request bytes.
    for product in ('ndvi','lst'):
        for month in (0,2):
            req,geom,raw,job=packet(product,month);r=Recorder();w=FakeHTTPWire(raw);bodies=[];send=w.send
            def collect(category,uri,method,body):
                if category=='compute':bodies.append(body.decode())
                return send(category,uri,method,body)
            w.send=collect
            FakeSDKAdapter(PhysicalHTTP(r,job,w)).compute(req,geom,as_of=date(2026,1,1))
            body=bodies[0]
            assert all(c in body for c in req.method.collections)
            for token in (['B8','B4','10000','0.6'] if product=='ndvi' else ['ST_B10','QA_PIXEL','0.00341802','149','273.15']):assert token in body
            assert '500' in body and 'bestEffort' in body
