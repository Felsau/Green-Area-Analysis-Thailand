"""Local integration transport/mount tests; no Auth/DB/Cloud calls."""
import importlib.util
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest

spec = importlib.util.spec_from_file_location('local_legacy_unit', Path(__file__).parents[1] / 'legacy_demo.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.mark.parametrize('path', ['/auth/v1/user', '/rest/v1/profiles', '/rest/v1/ndvi_annual'])
def test_only_local_get_is_forwarded_and_attested(path):
    seen, attest = [], Mock()
    transport = m.ReadOnlyLocalTransport(attest, httpx.MockTransport(lambda req: seen.append(req.url) or httpx.Response(200)))
    with httpx.Client(transport=transport) as c:
        assert c.get(m.LOCAL_URL + path).status_code == 200
    attest.assert_called_once()
    assert len(seen) == 1


@pytest.mark.parametrize('method,url', [
    ('GET', 'https://127.0.0.1:55421/rest/v1/profiles'),
    ('GET', 'http://localhost:55421/rest/v1/profiles'),
    ('GET', 'http://127.0.0.1:8000/rest/v1/profiles'),
    ('GET', 'https://unknown.invalid/rest/v1/profiles'),
    ('GET', 'http://user:pass@127.0.0.1:55421/rest/v1/profiles'),
    ('GET', m.LOCAL_URL + '/rest/v1/profiles#fragment'),
    ('GET', m.LOCAL_URL + '/rest/v1/rpc/gis_command'),
    ('GET', m.LOCAL_URL + '/auth/v1/admin/users'),
    ('GET', m.LOCAL_URL + '/rest/v1/unknown'),
    ('POST', m.LOCAL_URL + '/rest/v1/profiles'),
    ('PATCH', m.LOCAL_URL + '/rest/v1/profiles'),
    ('DELETE', m.LOCAL_URL + '/rest/v1/ndvi_annual'),
    ('PUT', m.LOCAL_URL + '/auth/v1/user'),
])
def test_forbidden_transport_never_connects(method, url):
    inner, attest = Mock(), Mock()
    with httpx.Client(transport=m.ReadOnlyLocalTransport(attest, inner)) as c:
        with pytest.raises(HTTPException) as error:
            c.request(method, url)
    assert error.value.status_code == 503
    inner.handle_request.assert_not_called()
    attest.assert_not_called()


def test_failed_attestation_prevents_network():
    inner = Mock()
    with httpx.Client(transport=m.ReadOnlyLocalTransport(Mock(side_effect=RuntimeError('wrong target')), inner)) as c:
        with pytest.raises(RuntimeError):
            c.get(m.LOCAL_URL + '/rest/v1/profiles')
    inner.handle_request.assert_not_called()


@pytest.mark.parametrize('name', ['main', 'dependencies', 'routers.maps.analysis.context', 'routers.account', 'gee_utils'])
def test_preloaded_legacy_modules_fail_before_target(monkeypatch, name):
    monkeypatch.setitem(sys.modules, name, SimpleNamespace())
    local = Mock()
    with pytest.raises(RuntimeError, match='FRESH_PROCESS'):
        m.create_app(local)
    local.attest.assert_not_called()


def test_mount_is_read_only_default_closed_and_preserves_auth():
    legacy, app = FastAPI(), FastAPI()
    called = []
    def health():
        return {'ok': True}
    health.__module__ = 'main'
    legacy.add_api_route('/health', health, methods=['GET'])
    def dangerous():
        called.append(True)
        raise AssertionError('must not execute')
    legacy.add_api_route('/ndvi/{province_name}', dangerous, methods=['GET'])
    legacy.add_api_route('/cache', dangerous, methods=['DELETE'])
    legacy.add_api_route('/future-read', dangerous, methods=['GET'])
    def auth(value):
        if value != 'Bearer synthetic':
            raise HTTPException(401)
    m.mount_legacy(app, SimpleNamespace(app=legacy), SimpleNamespace(require_user=auth))
    with TestClient(app) as c:
        assert c.get('/health').json() == {'ok': True}
        assert c.get('/ndvi/Bangkok').status_code == 401
        assert c.get('/ndvi/Bangkok', headers={'Authorization': 'Bearer synthetic'}).json()['detail']['code'] == 'LOCAL_GEE_BLOCKED'
        assert c.delete('/cache', headers={'Authorization': 'Bearer synthetic'}).json()['detail']['code'] == 'LOCAL_READ_ONLY'
        assert c.get('/future-read', headers={'Authorization': 'Bearer synthetic'}).status_code == 503
    assert not called


def cached_ndvi_client(rows):
    """The real route identity mounted over an original endpoint that must never run."""
    legacy, app, called, chains = FastAPI(), FastAPI(), [], []
    def get_ndvi(province_name: str):
        called.append(province_name)
        raise AssertionError('the original endpoint deletes stale rows and calls GEE')
    get_ndvi.__module__ = 'routers.ndvi.endpoints'
    legacy.add_api_route('/ndvi/{province_name}', get_ndvi, methods=['GET'])
    def auth(value):
        if value != 'Bearer synthetic':
            raise HTTPException(401)
    def ensure_province(name):
        if name != 'Bangkok Metropolis':
            raise HTTPException(404)
    def supa_call(builder):
        client = MagicMock()
        table = client.table.return_value
        table.select.return_value = table.eq.return_value = table.limit.return_value = table
        table.execute.return_value = SimpleNamespace(data=rows)
        chains.append(client)
        return builder(client)
    deps = SimpleNamespace(require_user=auth, ensure_province=ensure_province, supa_call=supa_call,
        resolve_year=lambda year: 2026 if year is None else year, YEAR_MIN=1980, YEAR_MAX=2027, CURRENT_CACHE_VERSION=2)
    m.mount_legacy(app, SimpleNamespace(app=legacy), deps)
    return app, called, chains


AUTH = {'Authorization': 'Bearer synthetic'}
ROW = {'id': 9, 'province': 'Bangkok Metropolis', 'year': 2024, 'ndvi_mean': 0.3754, 'ndvi_min': 0.0015, 'ndvi_max': 0.8295,
    'green_area_pct': 62, 'validation': None, 'cache_version': 2, 'created_at': '2026-11-06T10:52:56+00:00'}


def test_cached_ndvi_returns_a_row_the_original_would_treat_as_stale_without_touching_it():
    app, called, chains = cached_ndvi_client([ROW])
    with TestClient(app) as c:
        response = c.get('/ndvi/Bangkok Metropolis?year=2024', headers=AUTH)
    body = response.json()
    assert response.status_code == 200 and body['ndvi_mean'] == 0.3754 and body['green_area_pct'] == 62
    assert body['from_cache'] is True and body['cached_at'] == ROW['created_at'] and body['year'] == 2024
    assert not {'id', 'created_at', 'cache_version'} & set(body)
    assert not called
    table = chains[0].table.return_value
    chains[0].table.assert_called_once_with('ndvi_annual')
    assert not table.delete.called and not table.insert.called and not table.update.called and not table.upsert.called


@pytest.mark.parametrize('rows', [[], [{**ROW, 'cache_version': 1}], [{k: v for k, v in ROW.items() if k != 'cache_version'}]])
def test_cached_ndvi_without_a_trusted_row_stays_blocked(rows):
    app, called, _ = cached_ndvi_client(rows)
    with TestClient(app) as c:
        response = c.get('/ndvi/Bangkok Metropolis?year=2024', headers=AUTH)
    assert response.status_code == 503 and response.json()['detail']['code'] == 'LOCAL_GEE_BLOCKED'
    assert not called


@pytest.mark.parametrize('path,headers,status', [
    ('/ndvi/Bangkok Metropolis?year=2024', {}, 401),
    ('/ndvi/Unknown?year=2024', AUTH, 404),
    ('/ndvi/Bangkok Metropolis?year=abc', AUTH, 422),
    ('/ndvi/Bangkok Metropolis?year=1979', AUTH, 422),
])
def test_cached_ndvi_rejects_before_reading(path, headers, status):
    app, called, chains = cached_ndvi_client([ROW])
    with TestClient(app) as c:
        assert c.get(path, headers=headers).status_code == status
    assert not called and not chains


def test_clean_factory_import_suppresses_app_environment_and_gee():
    # A separate process is required by the same fail-closed import boundary.
    repo = Path(__file__).resolve().parents[3]
    code = '''
import importlib.util,sys,os,json
sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
repo=Path(REPO)
sys.path.insert(0,str(repo/'green-area-backend'))
spec=importlib.util.spec_from_file_location('fresh_local_factory',repo/'dev/gis_ui/legacy_demo.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
from gis_runtime import GISRuntime
from fastapi.testclient import TestClient
import ee
runtime=GISRuntime();runtime.require_ready=lambda:None
local=SimpleNamespace(attest=Mock(),gis_runtime=runtime,local_keys=lambda:('synthetic-not-real','synthetic-not-real'),store=None,geotiff_store=None)
def deny(*a,**k):raise AssertionError('NETWORK_OR_GEE_MUST_NOT_RUN')
with patch.dict(os.environ,{'GEE_PROJECT':'must-not-inherit','EE_CREDENTIALS_JSON':'must-not-read','SUPABASE_URL':'https://must-not-contact.invalid'}),patch('socket.socket.connect',deny),patch.object(ee,'Initialize',deny):
 app=m.create_app(local)
 assert sys.modules['main'].GEE_PROJECT is None
 assert sys.modules['dependencies'].SUPABASE_URL is None
 assert os.environ['GEE_PROJECT']=='must-not-inherit'
 assert len(app.state.local_legacy_routes)>30
with TestClient(app) as c:assert c.get('/health').status_code==200
'''.replace('Path(REPO)', 'Path(' + repr(str(repo)) + ')')
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code], cwd=repo,
        capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, (result.stderr or '')[-1800:]
