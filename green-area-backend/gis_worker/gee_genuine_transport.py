"""Pinned SDK + accounted HTTPS. Importing this module never opens a socket.

Real construction requires the still-closed network-layer gate. Tests replace
the socket/egress boundary, not Google, and cannot constitute Live provenance.
The privileged recorder observes this transport; hashes from a job are never
accepted as attestations. The worker must not possess the recorder's GIS JWT.
"""
from datetime import date
import hashlib
import ipaddress
import json
import socket
import ssl
import threading
import time
from importlib.metadata import version
from urllib.parse import urlsplit, parse_qsl
from types import SimpleNamespace

from gis_worker.gee_genuine_identity import ExplicitGoogleCredentials, GenuineBoundaryError
from gis_worker.gee_genuine_runtime import require_selective_egress
from gis_worker.gee_live_bridge import _build_expression, observation_output
from gis_worker.gee_live_contracts import Request
from gis_worker.gee_sdk_transport import PhysicalHTTP, SDK_VERSION, _SDK_LOCK
from gis_worker.gee_restricted_network import PinnedDestinations, PinnedHTTPSConnection

MAX_HTTP_BYTES = 1024 * 1024


class GenuineHTTPSWire:
    def __init__(self, *, binding, credentials, egress, deadline, clock=time.monotonic):
        require_selective_egress(egress, binding)
        if type(credentials) is not ExplicitGoogleCredentials:
            raise GenuineBoundaryError('GEE_EXPLICIT_CREDENTIALS_REQUIRED')
        credentials.authorize(binding)
        if type(egress) is not PinnedDestinations:
            raise GenuineBoundaryError('GEE_EGRESS_PINS_REQUIRED')
        egress.validate()
        self.egress = egress
        self.binding, self.credentials = binding, credentials
        self.deadline, self.clock = deadline, clock
        self.evidence = None

    def send(self, category, uri, method, body):
        self.evidence = None
        self.credentials.authorize(self.binding)
        u = urlsplit(uri)
        if (PhysicalHTTP.category(SimpleNamespace(project=self.binding.project.project_id), uri, method) != category
            or category == 'token'):
            raise GenuineBoundaryError('GEE_HTTPS_TARGET_REJECTED')
        remaining = min(120, self.deadline - self.clock(), self.credentials.remaining(self.binding))
        if remaining <= 0:
            raise GenuineBoundaryError('GEE_HTTPS_DEADLINE')
        import certifi
        # An explicit dependency CA bundle prevents SSL_CERT_FILE / proxy
        # environment settings from silently replacing the trust roots.
        # create_default_context also honors SSLKEYLOGFILE. Build explicitly so
        # inherited process settings cannot write TLS session secrets to disk.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = True
        context.load_verify_locations(cafile=certifi.where())
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        # No proxy env, custom CA files, ADC, redirects, connection pool or
        # hidden HTTP retries. Actual egress must ALSO be network-layer enforced.
        connection = PinnedHTTPSConnection(u.hostname, pins=self.egress,
            port=443, timeout=remaining, context=context)
        timer = None
        def expire():
            try:
                if connection.sock:
                    connection.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            finally:
                connection.close()
        try:
            timer = threading.Timer(remaining, expire)
            timer.daemon = True
            timer.start()
            connection.connect()
            peer = ipaddress.ip_address(connection.sock.getpeername()[0])
            if not peer.is_global or connection.sock.version() not in ('TLSv1.2', 'TLSv1.3'):
                raise GenuineBoundaryError('GEE_HTTPS_PEER_REJECTED')
            certificate = connection.sock.getpeercert(binary_form=True)
            tls_version = connection.sock.version()
            if not certificate or context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
                raise GenuineBoundaryError('GEE_HTTPS_TLS_REQUIRED')
            headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
                'Accept-Encoding': 'identity', 'Connection': 'close'}
            # Public catalog metadata never receives the bearer credential.
            if u.hostname == 'earthengine.googleapis.com':
                headers.update(self.credentials.headers(self.binding))
            connection.request(method, u.path + ('?' + u.query if u.query else ''), body=body or None, headers=headers)
            response = connection.getresponse()
            if 300 <= response.status < 400 or response.getheader('Content-Encoding', 'identity') != 'identity':
                raise GenuineBoundaryError('GEE_HTTPS_REDIRECT_OR_ENCODING_REJECTED')
            raw = response.read(MAX_HTTP_BYTES + 1)
            if len(raw) > MAX_HTTP_BYTES or self.clock() >= self.deadline:
                raise GenuineBoundaryError('GEE_HTTPS_RESPONSE_LIMIT_OR_DEADLINE')
            self.credentials.authorize(self.binding)
            # Response is bounded JSON from the verified HTTPS exchange. The
            # recorder recomputes body hashes; no caller-supplied origin claim.
            text = raw.decode('utf-8', errors='strict')
            json.loads(text)
            self.evidence = {'uri': uri, 'method': method,
                'peer_ip': str(peer), 'certificate_sha256': hashlib.sha256(certificate).hexdigest(),
                'tls_version': tls_version, 'response_body': text}
            return response.status, raw
        except GenuineBoundaryError:
            raise
        except Exception:
            # HTTP/socket exceptions can carry request headers or credentials.
            raise GenuineBoundaryError('GEE_HTTPS_EXCHANGE_FAILED') from None
        finally:
            if timer is not None:
                timer.cancel()
            connection.close()


class GenuinePhysicalHTTP(PhysicalHTTP):
    """Reuse 046's physical reserve/attempt/uncertain/retry/seal boundary."""
    def __init__(self, recorder, job, wire, *, binding, clock=time.monotonic):
        if type(wire) is not GenuineHTTPSWire:
            raise GenuineBoundaryError('GEE_GENUINE_HTTPS_WIRE_REQUIRED')
        request = Request.model_validate(job['request'])
        binding.check(request, job['geometry'])
        if (str(binding.job_id) != job['id'] or str(binding.session_id) != job['session_id']
            or str(binding.worker_subject) != job['worker_id']
            or binding.attempt_number != job['attempt_number']
            or binding.input_hash != job['input_hash']
            or binding.lease_sha256 != hashlib.sha256(__import__('uuid').UUID(job['lease_token']).bytes).hexdigest()
            or wire.binding != binding):
            raise GenuineBoundaryError('GEE_GENUINE_JOB_REJECTED')
        require_selective_egress(None, binding)
        self.binding = binding
        self.project, self.job, self.wire, self.clock = request.project.project_id, dict(job), wire, clock
        self.started = clock()
        self.remaining = min(180, float(job['job_remaining_seconds']))
        if not 0 < self.remaining <= 180:
            raise GenuineBoundaryError('GEE_GENUINE_DEADLINE_REJECTED')
        self.wire.deadline = min(self.wire.deadline, self.started + self.remaining)
        self.ids, self.retry_targets, self.failed = [], set(), False
        def observed(action, payload):
            if action == 'response':
                if wire.evidence is None:
                    raise GenuineBoundaryError('GEE_HTTPS_OBSERVATION_REQUIRED')
                payload = payload | wire.evidence
            return recorder(action, payload)
        self.call = observed

    def category(self, uri, method):
        category = super().category(uri, method)
        u = urlsplit(uri)
        pairs = parse_qsl(u.query, keep_blank_values=True)
        if category == 'token' or len(pairs) != len({k for k, _ in pairs}):
            raise GenuineBoundaryError('GEE_AUTH_REFRESH_OR_QUERY_REJECTED')
        return category

    def seal(self, output):
        self.sealed_report = super().seal(output)
        return self.sealed_report


class GenuineSDKAdapter:
    def __init__(self, http, *, credentials):
        if type(http) is not GenuinePhysicalHTTP or type(credentials) is not ExplicitGoogleCredentials:
            raise GenuineBoundaryError('GEE_GENUINE_DEPENDENCIES_REQUIRED')
        require_selective_egress(None, http.binding)
        self.http, self.credentials = http, credentials

    def compute(self, request, geometry, *, as_of: date):
        require_selective_egress(None, self.http.binding)
        if type(as_of) is not date or request.period.end_exclusive > as_of or as_of > date.today():
            raise GenuineBoundaryError('GEE_GENUINE_PERIOD_REJECTED')
        self.http.binding.check(request, geometry)
        self.credentials.authorize(self.http.binding)
        if version('earthengine-api') != SDK_VERSION:
            raise GenuineBoundaryError('GEE_SDK_VERSION_REJECTED')
        if not _SDK_LOCK.acquire(blocking=False):
            raise GenuineBoundaryError('GEE_SDK_CONCURRENCY_REJECTED')
        import ee
        original = ee.deprecation._FetchDataCatalogStac
        try:
            ee.Reset()
            def catalog():
                response, raw = self.http.request('https://storage.googleapis.com/earthengine-stac/catalog/catalog_deprecated.json')
                if response.status != 200:
                    raise GenuineBoundaryError('GEE_CATALOG_REJECTED')
                return json.loads(raw)
            ee.deprecation._FetchDataCatalogStac = catalog
            ee.Initialize(credentials=self.credentials.sdk_credentials(self.http.binding),
                project=self.http.project, opt_url='https://earthengine.googleapis.com', http_transport=self.http)
            ee.data.setMaxRetries(1)
            graph = _build_expression(ee, request, geometry)
            raw = ee.data.computeValue(graph)
            output = observation_output(request, raw, as_of=as_of)
            self.credentials.authorize(self.http.binding)
            self.http.seal(output)
            return output
        finally:
            ee.deprecation._FetchDataCatalogStac = original
            ee.Reset()
            _SDK_LOCK.release()
