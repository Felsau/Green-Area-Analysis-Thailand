"""One-shot offline image probe, NOT a live worker entrypoint."""
import json
import os
from pathlib import Path
import sys


def kernel_network_probe():
    """Network-none proof against reserved addresses, never Google endpoints."""
    import socket
    if sys.platform != 'linux' or os.geteuid() != 65534:
        raise RuntimeError('GEE_PROBE_PLATFORM_REJECTED')
    if {p.name for p in Path('/sys/class/net').iterdir()} != {'lo'}:
        raise RuntimeError('GEE_PROBE_NETWORK_NOT_NONE')
    checks = {}
    for name, family, address in (
        ('ipv4_external_denied', socket.AF_INET, ('192.0.2.1', 443)),
        ('ipv6_external_denied', socket.AF_INET6, ('2001:db8::1', 443))):
        with socket.socket(family, socket.SOCK_STREAM) as stream:
            stream.settimeout(.5)
            try:
                stream.connect(address)
            except OSError:
                checks[name] = True
            else:
                raise RuntimeError('GEE_PROBE_EXTERNAL_ROUTE_PRESENT')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as stream:
        try:
            # Reserved test destination, not an actual DNS server or query.
            stream.sendto(b'OFFLINE_NETWORK_DENIAL_PROBE', ('192.0.2.53', 53))
        except OSError:
            checks['external_dns_datagram_denied'] = True
        else:
            raise RuntimeError('GEE_PROBE_EXTERNAL_DNS_ROUTE_PRESENT')
    return checks


def redirect_probe():
    """Local-only302 response; never follows the reserved external destination."""
    import http.client
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading
    from gis_worker.gee_runtime_transport import require_live_egress
    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header('Location', 'https://192.0.2.1/changed-destination')
            self.end_headers()
        def log_message(self, *args):
            pass
    server = HTTPServer(('127.0.0.1', 0), Redirect)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
    try:
        connection.request('GET', '/')
        response = connection.getresponse()
        if response.status != 302:
            raise RuntimeError('GEE_PROBE_REDIRECT_FIXTURE_FAILED')
        try:
            require_live_egress(response.getheader('Location'))
        except ValueError as error:
            if str(error) != 'GEE_LIVE_EGRESS_BLOCKED':
                raise
        else:
            raise RuntimeError('GEE_PROBE_REDIRECT_NOT_REJECTED')
    finally:
        connection.close()
        thread.join(timeout=3)
        server.server_close()
    return {'local_302_not_followed': True}


def injected_probe():
    from datetime import date
    from uuid import uuid4
    from gis_worker.gee_execution_safety import UnapprovedPolicy
    from gis_worker.gee_live_contracts import digest
    from gis_worker.gee_live_injected import fixture, InjectedSDK, InjectedTransport
    from gis_worker.gee_live_bridge import InjectedBridge
    from gis_worker.gee_runtime_identity import (RuntimeBinding, InjectedCredentials,
        DisabledGoogleCredentials, CredentialBoundaryError)
    from gis_worker.gee_runtime_transport import PreparedInjectedTransport
    request, geometry, raw = fixture('e' * 12)
    policy_sha = digest(UnapprovedPolicy().model_dump(mode='json'))
    subject, session = str(uuid4()), str(uuid4())
    job = {'id': str(uuid4()), 'lease_token': str(uuid4()), 'worker_id': subject,
        'session_id': session, 'policy_sha256': policy_sha, 'attempt_number': 1,
        'input_hash': '1' * 64, 'input_revision': 1, 'job_remaining_seconds': 180,
        'request': request.model_dump(mode='json'), 'geometry': geometry,
        'semantic_request_sha256': request.request_hash(),
        'manifest': {'schema_version': 8, 'provider': 'gee_safety_rehearsal',
            'session_id': session, 'policy_sha256': policy_sha}}
    output = InjectedBridge(sdk=InjectedSDK(), transport=InjectedTransport(raw),
        authorization=lambda: request.project, as_of=date(2026, 1, 1)).compute(request, geometry)
    binding = RuntimeBinding.from_claim(job, subject)
    provider = InjectedCredentials(binding)
    credential = provider.issue(binding)
    rows = {}
    def accounting(action, payload):
        # In-memory test double only. Real SQL authority is tested separately.
        if action == 'reserve':
            rid = str(uuid4())
            rows[rid] = {'request_id': rid, 'state': 'reserved', 'kind': payload['kind']}
        else:
            rid = payload['request_id']
            rows[rid]['state'] = {'attempted': 'attempted', 'finished': 'completed',
                'uncertain': 'uncertain'}[action]
        return rows[rid].copy()
    class Port:
        OFFLINE_INJECTED = True
        def evaluate(self, *, timeout_seconds):
            return output
    wrapped = PreparedInjectedTransport(accounting, job, subject, provider, credential).run(
        [('compute', Port()), ('sdk_retry', Port()), ('reference', Port())])
    if (len(rows) != 3 or {r['kind'] for r in rows.values()} != {'compute', 'sdk_retry', 'reference'}
        or wrapped['execution'] != 'rehearsal' or wrapped['live_enabled'] is not False
        or wrapped['base']['output']['content']['publishable'] is not False):
        raise RuntimeError('GEE_PROBE_ACCOUNTING_FAILED')
    try:
        DisabledGoogleCredentials().issue()
    except CredentialBoundaryError:
        pass
    else:
        raise RuntimeError('GEE_PROBE_REAL_CREDENTIALS_ENABLED')
    return {'injected_only': True, 'simulated_request_count': 3,
        'candidate_publishable': False, 'real_credential_delivery_disabled': True}


def main():
    # Default/unknown command denies before credentials, stdin or SDK imports.
    if sys.argv[1:] != ['--offline-probe']:
        sys.stdout.write('{"live_enabled":false,"status":"disabled"}\n')
        return 78
    if sys.platform != 'linux':
        return 70
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 ** 2, 512 * 1024 ** 2))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16384, 16384))
    os.environ['PYDANTIC_DISABLE_PLUGINS'] = '__all__'
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    checks = kernel_network_probe()
    checks.update(redirect_probe())
    # After the OS-level proof, block all Python network/SDK/auth/file discovery.
    from gis_worker.gee_mock_child import install_guards
    install_guards()
    checks.update(injected_probe())
    if any(n == 'ee' or n.startswith(('google.auth', 'dotenv')) for n in sys.modules):
        raise RuntimeError('GEE_PROBE_AUTH_SDK_IMPORTED')
    from importlib.metadata import version, PackageNotFoundError
    try:
        sdk_version = version('earthengine-api')
    except PackageNotFoundError:
        sdk_version = None
    sys.stdout.write(json.dumps({'mode': 'offline-probe', 'live_enabled': False,
        'google_calls': False, 'network_policy': 'gee-live-deny-external-v1',
        'earthengine_sdk_version': sdk_version, 'physical_sdk_accounting_verified': False,
        'checks': checks}, separators=(',', ':')) + '\n')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        # Never expose arbitrary provider/credential exception details.
        sys.stdout.write('{"status":"probe-failed","live_enabled":false}\n')
        raise SystemExit(1)
