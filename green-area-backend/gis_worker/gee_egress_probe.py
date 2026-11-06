"""Network-isolation probes executed INSIDE the Recorder/Worker proof containers.

Stdlib only. The probes send no credentials and no HTTP request to Google. The
optional TLS handshake goes through the relay, verifies the certificate against the
real hostname and closes immediately after the handshake (no application data).
Each probe returns a classification and the role's expectations decide PASS/FAIL;
the supervisor's own docker inspect evidence is checked separately.
"""
import errno
import hashlib
import json
import socket
import ssl
import struct

from gis_worker.gee_egress_relay import ROUTES, RelayError, _ipv4

ROLES = ('probe-recorder', 'probe-worker')
CONFIG_KEYS = {'version', 'role', 'relay_ip', 'gateway_ip', 'pins', 'tls_handshake'}
EXTERNAL = ('1.1.1.1', '9.9.9.9')


def tcp(ip, port, timeout=3.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return 'connected'
    except socket.timeout:
        return 'timeout'
    except ConnectionRefusedError:
        return 'refused'
    except OSError as e:
        return {errno.ENETUNREACH: 'unreachable', errno.EHOSTUNREACH: 'unreachable'}.get(e.errno, 'error')
    finally:
        s.close()


def dns(name):
    try:
        socket.getaddrinfo(name, 443, socket.AF_INET, socket.SOCK_STREAM)
        return 'resolved'
    except OSError:
        return 'failed'


def udp_dns(server, timeout=3.0):
    """One A query for example.com straight to a public resolver (bypassing Docker DNS)."""
    query = struct.pack('>HHHHHH', 0x4741, 0x0100, 1, 0, 0, 0) + b'\x07example\x03com\x00' + struct.pack('>HH', 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(query, (server, 53))
        s.recvfrom(512)
        return 'answered'
    except socket.timeout:
        return 'timeout'
    except OSError:
        return 'error'
    finally:
        s.close()


def http_health(ip, timeout=5.0):
    """GET /auth/v1/health on the local SQL gateway; returns the status line code."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, 8000))
        s.sendall(b'GET /auth/v1/health HTTP/1.1\r\nHost: ' + ip.encode() + b':8000\r\nConnection: close\r\n\r\n')
        head = s.recv(64)
        parts = head.split(b' ', 2)
        return int(parts[1]) if len(parts) > 1 and parts[0].startswith(b'HTTP/') else 'bad_response'
    except OSError:
        return 'unreachable'
    finally:
        s.close()


def tls_handshake(relay_ip, host, timeout=10.0):
    """Handshake only: no HTTP bytes, no credential, closes immediately."""
    context = ssl.create_default_context()
    raw = socket.create_connection((relay_ip, ROUTES[host]), timeout=timeout)
    try:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            cert = tls.getpeercert(binary_form=True)
            return {'result': 'verified', 'tls_version': tls.version(),
                'certificate_sha256': hashlib.sha256(cert).hexdigest()}
    except ssl.SSLCertVerificationError:
        return {'result': 'certificate_rejected'}
    except OSError:
        return {'result': 'failed'}
    finally:
        raw.close()


def validate_config(config):
    if type(config) is not dict or set(config) != CONFIG_KEYS or config['version'] != 1:
        raise RelayError('GEE_PROBE_CONFIG_REJECTED')
    if config['role'] not in ROLES or type(config['tls_handshake']) is not bool:
        raise RelayError('GEE_PROBE_CONFIG_REJECTED')
    if config['role'] == 'probe-worker' and config['tls_handshake']:
        raise RelayError('GEE_PROBE_CONFIG_REJECTED')
    _ipv4(config['relay_ip'], private=True)
    if config['gateway_ip'] is not None:
        _ipv4(config['gateway_ip'], private=True)
    pins = config['pins']
    if type(pins) is not dict or set(pins) != set(ROUTES):
        raise RelayError('GEE_PROBE_CONFIG_REJECTED')
    for ips in pins.values():
        if type(ips) is not list or not 1 <= len(ips) <= 8:
            raise RelayError('GEE_PROBE_CONFIG_REJECTED')
        for ip in ips:
            _ipv4(ip, private=False)
    return config


def run(config, *, tcp=tcp, dns=dns, udp_dns=udp_dns, http_health=http_health, tls_handshake=tls_handshake):
    """Return {'checks': {...}, 'failed': [...], 'verdict': 'PASS'|'FAIL'}."""
    config = validate_config(config)
    role, relay = config['role'], config['relay_ip']
    google = sorted({ip for ips in config['pins'].values() for ip in ips})[:4]
    checks, expect = {}, {}
    for ip in google:
        checks[f'direct_google_{ip}'] = tcp(ip, 443)
        expect[f'direct_google_{ip}'] = lambda v: v != 'connected'
    for ip in EXTERNAL:
        checks[f'direct_external_{ip}'] = tcp(ip, 443)
        expect[f'direct_external_{ip}'] = lambda v: v != 'connected'
        checks[f'udp_dns_{ip}'] = udp_dns(ip)
        expect[f'udp_dns_{ip}'] = lambda v: v != 'answered'
    for name in ('earthengine.googleapis.com', 'example.com'):
        checks[f'dns_{name}'] = dns(name)
        expect[f'dns_{name}'] = lambda v: v == 'failed'
    for host, port in ROUTES.items():
        checks[f'relay_{port}'] = tcp(relay, port)
        expect[f'relay_{port}'] = ((lambda v: v == 'connected') if role == 'probe-recorder'
            else (lambda v: v != 'connected'))
    for port in (22, 80, 443, 3128, 8080):
        checks[f'relay_other_{port}'] = tcp(relay, port)
        expect[f'relay_other_{port}'] = lambda v: v != 'connected'
    if config['gateway_ip'] is not None:
        checks['gateway_health'] = http_health(config['gateway_ip'])
        expect['gateway_health'] = lambda v: v == 200
        # Informational only: what else on the shared T0 backplane is reachable.
        checks['info_gateway_other_5432'] = tcp(config['gateway_ip'], 5432)
    if config['tls_handshake']:
        for host in ROUTES:
            checks[f'tls_{host}'] = tls_handshake(relay, host)
            expect[f'tls_{host}'] = lambda v: v.get('result') == 'verified'
    failed = sorted(k for k, ok in expect.items() if not ok(checks[k]))
    return {'role': role, 'checks': checks, 'failed': failed, 'verdict': 'FAIL' if failed else 'PASS'}


def main(config):
    print(json.dumps(run(config), sort_keys=True), flush=True)

