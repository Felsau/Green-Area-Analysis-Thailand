"""GEE Dashboard processing (scope 2.1.15, migration 048) without Google or a database.

The real endpoint calls are injected, so no Earth Engine, Supabase or credential is used.
The SQL lifecycle of migration 048 is exercised by dev/gis_local/gee_dashboard_local.py
(rolled-back probe on the local T0 databases); here only its static contract is pinned.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import threading
import time

import pytest

from gis_worker import gee_dashboard_provider as provider
from gis_worker.gee_dashboard_worker import GeeDashboardWorker, HostClient, HOST_URL
from gis_worker.worker import INFRA, WorkerError

MIGRATIONS = Path(__file__).resolve().parents[1] / 'migrations'
M047 = MIGRATIONS / '047_gis_genuine_https.sql'
M048 = MIGRATIONS / '048_gis_gee_dashboard_processing.sql'
PID = '5f0c2f8e-1111-4c2a-9a55-0b7ad2f8f001'


def manifest(metric='ndvi', month=0, district=None):
    return {'schema_version': 9, 'provider': 'gee_dashboard', 'mode': 'gee_dashboard',
        'provenance': 'gis-processing-gee-dashboard-v1', 'data_kind': 'summary', 'province': 'Chiang Mai',
        'district': district, 'metric': metric, 'data_year': 2024, 'month': month,
        'start_date': '2024-01-01', 'end_date': '2025-01-01', 'scale_m': 500 if district is None else 100,
        'processing_version': 'gee-dashboard-v1', 'source_collections': ['X'], 'cloud_mask': 'm',
        'cache_table': provider.cache_table(metric, district, month), 'requested_on': '2026-11-06'}


def request(**kw):
    return {'processing_id': PID, 'manifest': manifest(**kw), 'input_hash': 'a' * 64, 'input_revision': 1,
        'attempt_number': 1}


class Endpoints:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def __call__(self, metric, province, district, year, monthly):
        self.calls.append((metric, province, district, year, monthly))
        if self.error:
            raise self.error
        return deepcopy(self.response)


# --- request contract -------------------------------------------------------------

@pytest.mark.parametrize('metric,district,month,table', [
    ('ndvi', None, 0, 'ndvi_annual'), ('ndvi', None, 3, 'ndvi_monthly'),
    ('ndvi', 'Mueang', 0, 'district_ndvi_annual'), ('ndvi', 'Mueang', 12, 'district_ndvi_monthly'),
    ('lst', None, 0, 'province_lst_annual'), ('lst', None, 1, 'province_lst_monthly'),
    ('lst', 'Mueang', 0, 'district_lst_annual'), ('lst', 'Mueang', 7, 'district_lst_monthly')])
def test_cache_table_matches_the_dashboard_tables(metric, district, month, table):
    assert provider.cache_table(metric, district, month) == table
    sql = M048.read_text(encoding='utf-8')
    assert "CREATE FUNCTION gis.dashboard_cache_table" in sql


@pytest.mark.parametrize('change', [
    {'provider': 'offline_synthetic'}, {'mode': 'offline_synthetic'}, {'schema_version': 3},
    {'cache_table': 'ndvi_monthly'}, {'metric': 'evi'}, {'month': 13}, {'requested_on': '6/11/2026'},
    {'province': ''}, {'district': 'x' * 121}, {'extra': 1}, {'processing_version': 'gee-offline-v1'}])
def test_check_request_rejects_any_non_dashboard_manifest(change):
    r = request()
    r['manifest'] = {**r['manifest'], **change}
    with pytest.raises(provider.DashboardProcessingError):
        provider.check_request(r)


@pytest.mark.parametrize('change', [{'input_hash': 'A' * 64}, {'input_revision': 2}, {'attempt_number': 4},
    {'processing_id': 'nope'}, {'extra': 1}])
def test_check_request_rejects_bad_job_fields(change):
    with pytest.raises(provider.DashboardProcessingError):
        provider.check_request({**request(), **change})


# --- compute through the injected Dashboard endpoints ---------------------------------

def test_annual_ndvi_uses_the_endpoint_values_and_reports_the_cache_row():
    e = Endpoints({'ndvi_mean': 0.4512, 'ndvi_min': -0.12, 'ndvi_max': 0.91, 'from_cache': False,
        'data_quality': {'n_images': 41, 'season': 'dry'}, 'green_area_pct': 55.1})
    report = provider.compute(request(), e)
    assert e.calls == [('ndvi', 'Chiang Mai', None, 2024, False)]
    assert report['valid'] is True and report['synthetic'] is False and report['error_code'] is None
    assert report['statistics'] == {'valid_pixels': None, 'mean': 0.4512, 'min': -0.12, 'max': 0.91}
    assert report['cache'] == {'table': 'ndvi_annual', 'province': 'Chiang Mai', 'district': None,
        'year': 2024, 'month': 0, 'written': True}
    assert report['observation'] == {'from_cache': False, 'cached_at': None, 'image_count': None,
        'data_quality': {'n_images': 41, 'season': 'dry'}}
    assert report['metadata'] == manifest() and set(report) == {'schema_version', 'provider_build', 'mode',
        'synthetic', 'processing_id', 'input_hash', 'input_revision', 'valid', 'error_code', 'statistics',
        'metadata', 'observation', 'cache'}


def test_existing_cache_point_is_reported_without_a_new_compute_claim():
    e = Endpoints({'lst_mean': 30.1, 'lst_min': 22.0, 'lst_max': 41.5, 'from_cache': True,
        'cached_at': '2026-10-01T00:00:00+00:00'})
    report = provider.compute(request(metric='lst', district='Mueang'), e)
    assert e.calls == [('lst', 'Chiang Mai', 'Mueang', 2024, False)]
    assert report['observation']['from_cache'] is True and report['observation']['cached_at'].startswith('2026-10-01')
    assert report['cache']['table'] == 'district_lst_annual'


def test_monthly_selects_only_the_requested_month_and_never_invents_extrema():
    rows = [{'month_num': m, 'month': 'x', 'ndvi': round(0.1 * m / 12, 4), 'image_count': m} for m in range(1, 13)]
    report = provider.compute(request(month=4), Endpoints({'monthly': rows, 'from_cache': False}))
    assert report['statistics'] == {'valid_pixels': None, 'mean': rows[3]['ndvi'], 'min': None, 'max': None}
    assert report['observation']['image_count'] == 4 and report['cache']['month'] == 4


@pytest.mark.parametrize('response,code', [
    ({'ndvi_mean': None, 'ndvi_min': 0.1, 'ndvi_max': 0.2}, provider.NO_DATA),
    ({'ndvi_mean': 0.5, 'ndvi_min': 0.6, 'ndvi_max': 0.9}, provider.IMPLAUSIBLE),
    ({'ndvi_mean': 1.5, 'ndvi_min': 0.1, 'ndvi_max': 1.9}, provider.IMPLAUSIBLE),
    ({'ndvi_mean': float('nan'), 'ndvi_min': 0.1, 'ndvi_max': 0.2}, provider.NO_DATA),
    ({'ndvi_mean': True, 'ndvi_min': 0.1, 'ndvi_max': 0.2}, provider.NO_DATA),
    ('not a dict', provider.TRANSIENT)])
def test_annual_values_are_checked_before_reporting(response, code):
    report = provider.compute(request(), Endpoints(response))
    assert report['valid'] is False and report['error_code'] == code
    assert report['statistics'] == {'valid_pixels': None, 'mean': None, 'min': None, 'max': None}
    assert report['observation'] is None and report['cache'] is None


@pytest.mark.parametrize('rows,code', [
    ([{'month_num': 4, 'ndvi': None, 'image_count': 0}], provider.NO_DATA),
    ([{'month_num': 4, 'ndvi': 0.3, 'image_count': 0}], provider.NO_DATA),
    ([{'month_num': 4, 'ndvi': 3.0, 'image_count': 2}], provider.IMPLAUSIBLE),
    ([{'month_num': 5, 'ndvi': 0.3, 'image_count': 2}], provider.TRANSIENT), (None, provider.TRANSIENT)])
def test_monthly_values_are_checked_before_reporting(rows, code):
    report = provider.compute(request(month=4), Endpoints({'monthly': rows}))
    assert report['valid'] is False and report['error_code'] == code


def test_no_imagery_is_a_final_no_data_result_and_other_errors_are_transient():
    assert provider.compute(request(), Endpoints(error=provider.NoData()))['error_code'] == provider.NO_DATA
    secret = 'https://earthengine.googleapis.com/v1/projects/innate-beacon-483307-v1 token=ya29.secret'
    report = provider.compute(request(), Endpoints(error=RuntimeError(secret)))
    assert report['error_code'] == provider.TRANSIENT and provider.TRANSIENT in INFRA
    assert 'ya29' not in json.dumps(report) and 'innate-beacon' not in json.dumps(report)
    assert provider.NO_DATA not in INFRA and provider.IMPLAUSIBLE not in INFRA


def test_oversized_data_quality_is_dropped_not_truncated():
    big = {'scenes': ['x' * 100] * 200}
    report = provider.compute(request(), Endpoints({'ndvi_mean': 0.4, 'ndvi_min': 0.1, 'ndvi_max': 0.6,
        'data_quality': big}))
    assert report['valid'] is True and report['observation']['data_quality'] is None
    assert len(json.dumps(report).encode()) < 16384


def test_legacy_endpoint_binding_maps_404_to_no_data(monkeypatch):
    import sys
    import types
    HTTPException = pytest.importorskip('fastapi').HTTPException
    calls = []
    ndvi = types.SimpleNamespace(**{n: (lambda n: lambda *a, **k: calls.append((n, a, k)) or {'ok': n})(n) for n in
        ('get_ndvi', 'get_ndvi_monthly', 'get_district_ndvi', 'get_district_ndvi_monthly')})
    lst = types.SimpleNamespace(**{n: (lambda n: lambda *a, **k: calls.append((n, a, k)) or {'ok': n})(n) for n in
        ('get_lst', 'get_lst_monthly', 'get_district_lst', 'get_district_lst_monthly')})
    routers = types.ModuleType('routers'); routers.lst = lst
    ndvi_pkg = types.ModuleType('routers.ndvi'); ndvi_pkg.endpoints = ndvi
    monkeypatch.setitem(sys.modules, 'routers', routers)
    monkeypatch.setitem(sys.modules, 'routers.ndvi', ndvi_pkg)
    monkeypatch.setitem(sys.modules, 'routers.ndvi.endpoints', ndvi)
    monkeypatch.setitem(sys.modules, 'routers.lst', lst)
    bound = provider.LegacyEndpoints()
    assert bound('ndvi', 'P', None, 2024, False) == {'ok': 'get_ndvi'}
    assert bound('lst', 'P', 'D', 2023, True) == {'ok': 'get_district_lst_monthly'}
    assert calls[-1] == ('get_district_lst_monthly', ('P', 'D'), {'year': 2023})
    def missing(*a, **k):
        raise HTTPException(status_code=404, detail='none')
    def broken(*a, **k):
        raise HTTPException(status_code=500, detail='x')
    bound.calls[('ndvi', False, False)] = lambda p, d, y: missing()
    with pytest.raises(provider.NoData):
        bound('ndvi', 'P', None, 2024, False)
    bound.calls[('ndvi', False, False)] = lambda p, d, y: broken()
    with pytest.raises(HTTPException):
        bound('ndvi', 'P', None, 2024, False)


# --- host worker ----------------------------------------------------------------------

def token(sub, role='gis_native_worker', exp=None):
    import base64
    claims = {'sub': sub, 'role': role, 'iss': 'http://127.0.0.1:55421/auth/v1', 'exp': exp or int(time.time()) + 3600}
    return 'h.' + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=') + '.s'


SUB = '9b1c2f8e-2222-4c2a-9a55-0b7ad2f8f002'


def bootstrap(**change):
    return {'api_url': HOST_URL, 'subject': SUB, 'anon_key': 'anon', 'access_token': token(SUB),
        'refresh_token': 'r', 'runtime_instance': 'a' * 32, 'baseline_fingerprint': 'b' * 64} | change


@pytest.mark.parametrize('change', [{'api_url': 'http://green-area-gis-t0-gateway:8000'},
    {'api_url': 'http://127.0.0.1:55422'}, {'api_url': 'https://evil.example'},
    {'access_token': token(SUB, role='gis_gee_https_worker')}, {'extra': 1}])
def test_host_client_accepts_only_the_local_gateway_and_native_worker_jwt(change):
    with pytest.raises(WorkerError):
        HostClient(bootstrap(**change))


def test_host_client_posts_only_to_the_dashboard_rpcs_on_loopback():
    client = HostClient(bootstrap())
    seen = []

    class Response:
        def __init__(self, data): self.data = json.dumps(data).encode()
        def read(self, n): return self.data
        def __enter__(self): return self
        def __exit__(self, *a): pass

    class Opener:
        def open(self, req, timeout):
            seen.append((req.full_url, json.loads(req.data)))
            return Response({'job': None})
    client._opener = Opener()
    assert client.call('gis_gee_dashboard_worker', {'p_action': 'claim', 'p_payload': {}}) == {'job': None}
    assert seen == [('http://127.0.0.1:55421/rest/v1/rpc/gis_gee_dashboard_worker', {'p_action': 'claim', 'p_payload': {}})]
    for name in ('gis_processing_worker', 'gis_worker_v2', 'gis_gee_https_worker'):
        with pytest.raises(WorkerError, match='RPC_REJECTED'):
            client.call(name, {})


class FakeClient:
    subject = SUB
    expected = {'runtime_instance': 'a' * 32, 'baseline_fingerprint': 'b' * 64}

    def __init__(self, readiness=None):
        self.calls = []
        self.ready = {'status': 'ready', 'worker_role': 'gis_native_worker', 'protocol': 'gee_dashboard',
            'contract_version': '1.0.0-gee-dashboard', 'subject': SUB, 'database_name': 'postgres',
            'cluster_name': 'green-area-gis-t0', 'migration_versions': list(range(27, 49)), **self.expected}
        if readiness:
            self.ready.update(readiness)

    def call(self, name, payload):
        self.calls.append((name, payload))
        if name == 'gis_gee_dashboard_readiness':
            return self.ready
        action = payload['p_action']
        return {'state': 'succeeded'} if action == 'complete' else {'state': 'queued'} if action == 'fail' else {}


@pytest.mark.parametrize('change', [{'protocol': 'gee_offline'}, {'contract_version': '1.0.0-processing-offline'},
    {'migration_versions': list(range(27, 48))}, {'subject': 'other'}, {'runtime_instance': 'c' * 32}])
def test_worker_refuses_a_target_that_is_not_the_048_dashboard_contract(change):
    with pytest.raises(WorkerError, match='TARGET_REJECTED'):
        GeeDashboardWorker(FakeClient(change), endpoints=Endpoints()).readiness()


def job(**kw):
    r = request(**kw)
    return {'id': '7e1c2f8e-3333-4c2a-9a55-0b7ad2f8f003', 'lease_token': '8e1c2f8e-4444-4c2a-9a55-0b7ad2f8f004', **r}


def test_worker_completes_a_valid_point_and_fails_transient_errors_for_retry():
    client = FakeClient()
    worker = GeeDashboardWorker(client, endpoints=Endpoints({'ndvi_mean': 0.4, 'ndvi_min': 0.1, 'ndvi_max': 0.6}))
    assert worker.process_job(job())['state'] == 'succeeded'
    rpc = [p for n, p in client.calls if n == 'gis_gee_dashboard_worker']
    assert rpc[-1]['p_action'] == 'complete' and rpc[-1]['p_payload']['report']['valid'] is True
    client = FakeClient()
    worker = GeeDashboardWorker(client, endpoints=Endpoints(error=RuntimeError('boom')))
    worker.process_job(job())
    last = [p for n, p in client.calls if n == 'gis_gee_dashboard_worker'][-1]
    assert last['p_action'] == 'fail' and last['p_payload']['error_code'] == 'transient'
    assert last['p_payload']['report']['error_code'] == provider.TRANSIENT


def test_worker_reports_no_data_as_final_complete_not_retry():
    client = FakeClient()
    GeeDashboardWorker(client, endpoints=Endpoints(error=provider.NoData())).process_job(job())
    last = [p for n, p in client.calls if n == 'gis_gee_dashboard_worker'][-1]
    assert last['p_action'] == 'complete' and last['p_payload']['report']['error_code'] == provider.NO_DATA


def test_slow_compute_respects_shutdown_and_lease_loss():
    release = threading.Event()

    def slow(*a):
        release.wait(5)
        return {'ndvi_mean': 0.4, 'ndvi_min': 0.1, 'ndvi_max': 0.6}
    worker = GeeDashboardWorker(FakeClient(), endpoints=slow)
    r = provider.check_request(request())
    threading.Timer(.3, worker._stop_event.set).start()
    assert worker._execute_native(r, timeout=5)['error_code'] == 'WORKER_SHUTDOWN'
    worker = GeeDashboardWorker(FakeClient(), endpoints=slow)
    assert worker._execute_native(r, timeout=.3)['error_code'] == 'NATIVE_TIMEOUT'
    worker = GeeDashboardWorker(FakeClient(), endpoints=slow)
    threading.Timer(.3, worker._lease_lost.set).start()
    with pytest.raises(WorkerError, match='STALE_LEASE'):
        worker._execute_native(r, timeout=5)
    release.set()


# --- API schema -----------------------------------------------------------------------

def test_processing_create_accepts_gee_dashboard_only_with_the_standard_scenario():
    from gis_schemas import ProcessingCreate
    body = {'province': 'Chiang Mai', 'metric': 'ndvi', 'data_year': 2024, 'month': 0}
    assert ProcessingCreate.model_validate({**body, 'mode': 'gee_dashboard'}).mode == 'gee_dashboard'
    assert ProcessingCreate.model_validate(body).mode == 'offline_synthetic'
    with pytest.raises(ValueError):
        ProcessingCreate.model_validate({**body, 'mode': 'gee_dashboard', 'scenario': 'no_data'})
    for mode in ('gee_live', 'gee_genuine_https', 'live'):
        with pytest.raises(ValueError):
            ProcessingCreate.model_validate({**body, 'mode': mode})
    with pytest.raises(ValueError):
        ProcessingCreate.model_validate({**body, 'mode': 'gee_dashboard', 'requested_on': '2020-01-01'})


# --- migration 048 static contract -------------------------------------------------------

def test_048_extends_047_queue_with_only_the_listed_protocol_additions():
    src, new = M047.read_text(encoding='utf-8'), M048.read_text(encoding='utf-8')
    start = "CREATE OR REPLACE FUNCTION gis.queue_protocol_kind("
    old_body = src[src.index(start):src.index('END $f$;', src.index(start)) + 8]
    new_body = new[new.index(start):new.index('END $f$;', new.index(start)) + 8]
    expected = old_body
    for old, repl, count in [
        ("'gee_offline','geotiff','gee_contract_mock','gee_live_v2','gee_safety_rehearsal','gee_genuine_https') OR p_protocol IS NULL",
         "'gee_offline','gee_dashboard','geotiff','gee_contract_mock','gee_live_v2','gee_safety_rehearsal','gee_genuine_https') OR p_protocol IS NULL", 1),
        ("     IF p_protocol='gee_offline' THEN\n       SELECT * INTO processing_request",
         "     IF p_protocol IN ('gee_offline','gee_dashboard') THEN\n       SELECT * INTO processing_request", 1),
        ("WHEN p_protocol='gee_offline' THEN 'processing.", "WHEN p_protocol IN ('gee_offline','gee_dashboard') THEN 'processing.", 4),
        ("ELSIF p_protocol='gee_offline' THEN PERFORM gis.validate_processing_report",
         "ELSIF p_protocol IN ('gee_offline','gee_dashboard') THEN PERFORM gis.validate_processing_report", 1),
        ("WHEN p_protocol='gee_offline' THEN 'offline_processing'",
         "WHEN p_protocol='gee_dashboard' THEN 'gee_dashboard' WHEN p_protocol='gee_offline' THEN 'offline_processing'", 1),
        ("IF p_protocol IN ('gee_offline','geotiff','gee_contract_mock','gee_live_v2','gee_safety_rehearsal','gee_genuine_https') THEN\n       UPDATE gis.editions SET state='draft'",
         "IF p_protocol IN ('gee_offline','gee_dashboard','geotiff','gee_contract_mock','gee_live_v2','gee_safety_rehearsal','gee_genuine_https') THEN\n       UPDATE gis.editions SET state='draft'", 1)]:
        assert expected.count(old) == count
        expected = expected.replace(old, repl)
    assert new_body == expected


def test_048_guard_grants_and_closed_gates():
    sql = M048.read_text(encoding='utf-8')
    assert "version=47 AND sha256='41a913e80f5699e9c6cd9136054af33665ea56f35caa2eba26274f0ae1f6a28e'" in sql
    assert "EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=48)" in sql and 'NOT activation_enabled' in sql
    grants = re.findall(r'GRANT EXECUTE ON FUNCTION ([^;]+) TO ([a-z_]+);', sql)
    assert grants == [('public.gis_gee_dashboard_worker(text,jsonb),public.gis_gee_dashboard_readiness()', 'gis_native_worker')]
    # No gate, live flag, cache table or secret is touched by the database side.
    for forbidden in ('activation_enabled=true', "live_enabled',true", 'INSERT INTO public.', 'UPDATE public.',
            'DELETE FROM public.', 'gee_https_runtimes', 'service_role_key', 'GEE_PROJECT'):
        assert forbidden not in sql
    assert "'live_enabled'" not in sql.split('gis.processing_read(p_actor uuid')[1].split('END $f$;')[0].replace("-- live_enabled", '')
    assert sql.count('\r') == 0


def test_older_migrations_are_unchanged_bytes():
    pinned = {'047_gis_genuine_https.sql': '41a913e80f5699e9c6cd9136054af33665ea56f35caa2eba26274f0ae1f6a28e'}
    for name, sha in pinned.items():
        assert hashlib.sha256((MIGRATIONS / name).read_bytes()).hexdigest() == sha
