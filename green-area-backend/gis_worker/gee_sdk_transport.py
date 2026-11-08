"""Pinned real SDK over an in-memory HTTP wire. Never a Live entry point.

The SDK, discovery, serialization, AuthorizedHttp refresh and googleapiclient
retry loops are real. HTTP responses and Google credentials are synthetic.
No arbitrary HTTP client/URL/credential provider can be supplied by a job.
"""
from copy import deepcopy
from datetime import date
from importlib.metadata import version
import hashlib
import json
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit, parse_qs
from uuid import uuid4

from gis_worker.gee_live_bridge import InjectedBridge
from gis_worker.gee_live_contracts import Request, canonical

SDK_VERSION = '1.7.30'
SANDBOX = ('green-area-gis-sandbox', '977478562022')
FAKE_PRINCIPAL = 'offline-test@green-area-gis-sandbox.iam.gserviceaccount.com'
NETWORK_POLICY = 'gee-sdk-fake-http-deny-all-v1'
_SDK_LOCK = threading.Lock()


class SDKBoundaryError(ValueError):
    pass


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require_genuine_startup(*args, **kwargs):
    raise SDKBoundaryError('GEE_GENUINE_RUNTIME_NOT_APPROVED')


class FakeHTTPWire:
    """Exact in-memory wire, not a user-extensible network transport.

    Vendor test documents are already installed with the exact pinned SDK.
    Nothing is fetched, pip-installed, or loaded from credential directories.
    """
    def __init__(self, raw, *, responses=(), refresh=False):
        if version('earthengine-api') != SDK_VERSION:
            raise SDKBoundaryError('GEE_SDK_VERSION_REJECTED')
        import ee
        root = Path(ee.__file__).parent / 'tests'
        self.documents = {
            'discovery': (root / 'cloud_api_discovery_document.json').read_bytes(),
            'algorithms': (root / 'algorithms.json').read_bytes(),
        }
        self.raw = deepcopy(raw)
        self.responses = list(responses)
        if any(type(x) is not int or x not in (200, 401, 429, 503) for x in self.responses):
            raise SDKBoundaryError('GEE_FAKE_RESPONSE_REJECTED')
        self.calls = []
        self.refresh = refresh

    def send(self, category, uri, method, body):
        # No sockets, HTTP libraries or callbacks here, including failure paths.
        self.calls.append((category, uri, method, sha(body)))
        status = self.responses.pop(0) if category == 'compute' and self.responses else 200
        if category == 'token':
            value = {'access_token': 'offline-synthetic-only', 'expires_in': 60, 'token_type': 'Bearer'}
        elif category in self.documents:
            return status, self.documents[category]
        elif category == 'catalog':
            value = {'links': []}
        elif status == 200:
            value = {'result': self.raw}
        else:
            value = {'error': {'code': status, 'message': 'offline synthetic HTTP response'}}
        return status, canonical(value).encode()


class PhysicalHTTP:
    """Reserve/attempt before EVERY underlying HTTP send, including retries.

    The recorder callback is a trusted parent dependency, not a job field. True
    request/response hashes are separate from SQL045's final observation hash.
    No Authorization headers/token bytes are logged, hashed or stored.
    """
    def __init__(self, recorder, job, wire, *, clock=time.monotonic):
        if type(wire) is not FakeHTTPWire:
            raise SDKBoundaryError('GEE_FAKE_WIRE_REQUIRED')
        request = Request.model_validate(job['request'])
        if (request.execution != 'injected'
            or (request.project.project_id, request.project.project_number) != SANDBOX
            or request.project.principal != FAKE_PRINCIPAL):
            raise SDKBoundaryError('GEE_FAKE_PROJECT_REJECTED')
        self.project = request.project.project_id
        self.call, self.job, self.wire, self.clock = recorder, dict(job), wire, clock
        self.started = clock()
        self.remaining = min(180, float(job.get('job_remaining_seconds', 180)))
        self.ids, self.retry_targets = [], set()
        self.failed = False

    def category(self, uri, method):
        u = urlsplit(uri)
        if (u.scheme != 'https' or u.username or u.password or u.fragment or u.port not in (None, 443)):
            raise SDKBoundaryError('GEE_HTTP_TARGET_REJECTED')
        if u.netloc == 'oauth2.googleapis.com' and u.path == '/token' and method == 'POST' and not u.query:
            return 'token'
        if u.netloc == 'storage.googleapis.com' and u.path == '/earthengine-stac/catalog/catalog_deprecated.json' and method == 'GET' and not u.query:
            return 'catalog'
        if u.netloc != 'earthengine.googleapis.com' or set(parse_qs(u.query)) - {'version', 'prettyPrint', 'alt', 'fields'}:
            raise SDKBoundaryError('GEE_HTTP_TARGET_REJECTED')
        if u.path == '/$discovery/rest' and method == 'GET' and set(parse_qs(u.query)) <= {'version', 'prettyPrint'}:
            return 'discovery'
        if u.path in ('/v1alpha/projects/' + self.project + '/algorithms', '/v1/projects/' + self.project + '/algorithms') and method == 'GET':
            return 'algorithms'
        if u.path in ('/v1alpha/projects/' + self.project + '/value:compute', '/v1/projects/' + self.project + '/value:compute') and method == 'POST':
            return 'compute'
        raise SDKBoundaryError('GEE_HTTP_TARGET_REJECTED')

    def request(self, uri, method='GET', body=None, headers=None, **kwargs):
        if self.failed or self.clock() - self.started >= self.remaining:
            raise SDKBoundaryError('GEE_HTTP_SESSION_STOPPED')
        category = self.category(uri, method)
        raw = body.encode() if isinstance(body, str) else body or b''
        if not isinstance(raw, bytes) or len(raw) > 1024 * 1024:
            raise SDKBoundaryError('GEE_HTTP_BODY_REJECTED')
        key = (method, uri)
        kind = 'sdk_retry' if key in self.retry_targets else 'compute' if category == 'compute' else 'discovery'
        lease = {'job_id': self.job['id'], 'lease_token': self.job['lease_token']}
        reservation = self.call('reserve', lease | {'request_key': str(uuid4()), 'kind': kind})
        if reservation.get('granted') is False:
            self.failed = True
            raise SDKBoundaryError('GEE_HTTP_BUDGET_EXHAUSTED')
        rid = reservation['request_id']
        payload = lease | {'request_id': rid}
        try:
            ack = self.call('attempted', payload)
            if ack.get('state') != 'attempted':
                raise SDKBoundaryError('GEE_HTTP_ATTEMPT_ACK_REQUIRED')
            if self.clock() - self.started >= self.remaining:
                raise SDKBoundaryError('GEE_HTTP_SESSION_STOPPED')
            before = self.clock()
            status, response = self.wire.send(category, uri, method, raw)
            if self.clock() - before >= 120 or self.clock() - self.started >= self.remaining:
                raise TimeoutError('GEE_HTTP_TIMEOUT')
            if len(response) > 1024 * 1024:
                raise SDKBoundaryError('GEE_HTTP_RESPONSE_LIMIT')
            # Auth body may contain tokens in the future. Store only its fixed
            # category hash, never its credential-bearing request/response bytes.
            request_hash = sha(canonical({'method': method, 'uri': uri,
                'body_sha256': sha(raw) if category != 'token' else sha(b'credential-redacted')}).encode())
            response_hash = sha(response) if category != 'token' else sha(b'credential-redacted')
            ack = self.call('response', payload | {'request_sha256': request_hash,
                'response_sha256': response_hash, 'status': status, 'category': category,
                'observation': json.loads(response)['result'] if category == 'compute' and status == 200 else None})
            if ack.get('state') != 'recorded':
                raise SDKBoundaryError('GEE_HTTP_RESPONSE_ACK_REQUIRED')
            self.ids.append(rid)
            if status >= 400:
                self.retry_targets.add(key)
            else:
                self.retry_targets.discard(key)
            from httplib2 import Response
            return Response({'status': str(status), 'content-type': 'application/json'}), response
        except Exception:
            self.failed = True
            try:
                self.call('uncertain', payload)
            except Exception:
                pass
            raise

    def seal(self, output):
        if self.failed or not self.ids:
            raise SDKBoundaryError('GEE_HTTP_INCOMPLETE')
        return self.call('seal', {'job_id': self.job['id'], 'lease_token': self.job['lease_token'],
            'output': output.model_dump(mode='json'), 'receipts': self.ids})


class _SDKView:
    OFFLINE_INJECTED = True

    def __init__(self, sdk):
        self.sdk = sdk

    def __getattr__(self, name):
        return getattr(self.sdk, name)


class _SDKCompute:
    OFFLINE_INJECTED = True

    def __init__(self, sdk):
        self.sdk = sdk

    def evaluate(self, graph, *, project):
        return self.sdk.data.computeValue(graph)


def _fake_credentials(refresh=False):
    from google.auth.credentials import Credentials

    class FakeCredentials(Credentials):
        def __init__(self):
            super().__init__()
            self.token = 'offline-synthetic-only'

        def refresh(self, request):
            if not refresh:
                raise SDKBoundaryError('GEE_CREDENTIAL_REFRESH_DISABLED')
            response = request('https://oauth2.googleapis.com/token', method='POST', body=b'fake-only')
            if response.status != 200:
                raise SDKBoundaryError('GEE_FAKE_REFRESH_REJECTED')
            self.token = 'offline-synthetic-renewed'

    return FakeCredentials()


class FakeSDKAdapter:
    """Process-local SDK lock; real credentials/transport/startup are absent."""
    def __init__(self, http):
        if type(http) is not PhysicalHTTP:
            raise SDKBoundaryError('GEE_ACCOUNTED_HTTP_REQUIRED')
        self.http = http

    def compute(self, request, geometry, *, as_of: date):
        # Check identity and the injected discriminator before SDK imports/init.
        request = Request.model_validate(request.model_dump(mode='json'))
        from gis_worker.gee_live_contracts import geometry_digest
        bound = Request.model_validate(self.http.job['request'])
        if (request.execution != 'injected' or request != bound
            or geometry_digest(geometry) != request.scope.geometry_sha256):
            raise SDKBoundaryError('GEE_GENUINE_RUNTIME_NOT_APPROVED')
        if not _SDK_LOCK.acquire(blocking=False):
            raise SDKBoundaryError('GEE_SDK_CONCURRENCY_REJECTED')
        import ee
        original = ee.deprecation._FetchDataCatalogStac
        try:
            ee.Reset()
            # SDK1.7.30 otherwise uses urllib outside http_transport here. Route
            # the exact public metadata lookup through the SAME accounted wire.
            def catalog():
                response, raw = self.http.request(
                    'https://storage.googleapis.com/earthengine-stac/catalog/catalog_deprecated.json')
                if response.status != 200:
                    raise SDKBoundaryError('GEE_CATALOG_REJECTED')
                return json.loads(raw)
            ee.deprecation._FetchDataCatalogStac = catalog
            ee.Initialize(credentials=_fake_credentials(self.http.wire.refresh),
                project=self.http.project, opt_url='https://earthengine.googleapis.com',
                http_transport=self.http)
            ee.data.setMaxRetries(1)
            output = InjectedBridge(sdk=_SDKView(ee), transport=_SDKCompute(ee),
                authorization=lambda: request.project, as_of=as_of).compute(request, geometry)
            self.http.seal(output)
            return output
        finally:
            ee.deprecation._FetchDataCatalogStac = original
            ee.Reset()
            _SDK_LOCK.release()
