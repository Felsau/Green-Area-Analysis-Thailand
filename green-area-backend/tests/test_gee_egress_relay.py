"""Offline tests for the A6 egress relay, isolation probes and proof launcher logic.

Loopback sockets only. The relay's upstream dial is injected, so no packet leaves
this host and nothing reaches Google.
"""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from unittest.mock import patch

import pytest

from gis_worker import gee_egress_relay as relay_mod
from gis_worker.gee_egress_relay import ROUTES, Relay, RelayError, validate_config
from gis_worker import gee_egress_probe as probe_mod
from gis_worker.gee_genuine_identity import GenuineBoundaryError
from gis_worker.gee_restricted_network import (HOSTS, PinnedDestinations, PinnedHTTPSConnection,
    RELAY_PORTS, validate_relay_ip)

PINS = {'earthengine.googleapis.com': ['142.250.1.10', '142.250.1.11'],
    'storage.googleapis.com': ['142.250.2.20']}
DEV = Path(__file__).resolve().parents[2] / 'dev' / 'gis_local'


def config(**change):
    return {'version': 1, 'mode': 'dry_run', 'bind_ip': '172.30.0.2',
        'expires_at': int(time.time()) + 300, 'routes': {h: list(v) for h, v in PINS.items()}} | change


def raw_connect(addr, timeout=5):
    # Literal-IP connect without Python-level getaddrinfo, so DNS can be patched to fail.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(addr)
    return s


def free_ports():
    ports = {}
    for host in ROUTES:
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        ports[host] = s.getsockname()[1]
        s.close()
    return ports


class Running:
    """Start a relay on loopback ports in a thread, collecting its JSON log events."""
    def __init__(self, cfg, **kw):
        self.events, self.ports = [], free_ports()
        self.relay = Relay(cfg, ports=self.ports, listen_ip='127.0.0.1', log=self.events.append, **kw)
        self.thread = threading.Thread(target=self.relay.serve, daemon=True)

    def __enter__(self):
        self.thread.start()
        end = time.monotonic() + 5
        while not any(e['event'] == 'listening' for e in self.events):
            assert time.monotonic() < end
            time.sleep(.01)
        return self

    def __exit__(self, *exc):
        self.relay.stop.set()
        self.thread.join(5)
        assert not self.thread.is_alive()

    def connect(self, host='earthengine.googleapis.com'):
        return raw_connect(('127.0.0.1', self.ports[host]))

    def wait(self, kind='connection', n=1):
        end = time.monotonic() + 5
        while sum(e['event'] == kind for e in self.events) < n:
            assert time.monotonic() < end, self.events
            time.sleep(.01)
        return [e for e in self.events if e['event'] == kind]


class Echo:
    """Loopback echo upstream; closed on exit so no thread outlives the test."""
    def __init__(self):
        self.server = socket.create_server(('127.0.0.1', 0))
        self.server.settimeout(.1)
        self.addr = self.server.getsockname()
        self.stopped = threading.Event()
        self.threads = [threading.Thread(target=self.loop, daemon=True)]
        self.threads[0].start()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stopped.set()
        for t in self.threads:
            t.join(5)

    def loop(self):
        try:
            self._accept()
        finally:
            self.server.close()

    def _accept(self):
        while not self.stopped.is_set():
            try:
                c, _ = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            c.settimeout(5)
            def serve(c=c):
                with c:
                    while (data := c.recv(65536)):
                        c.sendall(data)
            t = threading.Thread(target=serve, daemon=True)
            self.threads.append(t)
            t.start()


@pytest.fixture(autouse=True)
def no_leaked_threads():
    before = set(threading.enumerate())
    yield
    end = time.monotonic() + 5
    while set(threading.enumerate()) - before and time.monotonic() < end:
        time.sleep(.02)
    leaked = set(threading.enumerate()) - before
    assert not leaked, [t.name + ':' + str(getattr(t, '_target', None)) for t in leaked]


# --- configuration ---------------------------------------------------------------

@pytest.mark.parametrize('change', [
    {'version': 2}, {'version': True}, {'mode': 'proxy'}, {'mode': None},
    {'bind_ip': '127.0.0.1'}, {'bind_ip': '8.8.8.8'}, {'bind_ip': '169.254.1.1'}, {'bind_ip': 'relay'},
    {'bind_ip': '172.030.0.2'}, {'expires_at': int(time.time()) - 1}, {'expires_at': int(time.time()) + 5000},
    {'expires_at': 1.5},
    {'routes': {'earthengine.googleapis.com': ['142.250.1.10']}},
    {'routes': {**PINS, 'oauth2.googleapis.com': ['142.250.3.3']}},
    {'routes': {**PINS, 'earthengine.googleapis.com': ['10.0.0.1']}},
    {'routes': {**PINS, 'earthengine.googleapis.com': ['169.254.169.254']}},
    {'routes': {**PINS, 'earthengine.googleapis.com': ['127.0.0.1']}},
    {'routes': {**PINS, 'earthengine.googleapis.com': ['142.250.1.10', '142.250.1.10']}},
    {'routes': {**PINS, 'earthengine.googleapis.com': [f'142.250.1.{i}' for i in range(1, 10)]}},
    {'routes': {**PINS, 'earthengine.googleapis.com': []}},
    {'routes': {**PINS, 'earthengine.googleapis.com': '142.250.1.10'}},
    {'routes': {**PINS, 'earthengine.googleapis.com': ['earthengine.googleapis.com']}},
    {'extra': 1},
])
def test_relay_config_rejects_unpinned_private_expired_or_extra_values(change):
    with pytest.raises(RelayError):
        validate_config(config(**change))


def test_relay_ports_are_fixed_and_shared_with_the_recorder_dialer():
    assert ROUTES == RELAY_PORTS == {'earthengine.googleapis.com': 8443, 'storage.googleapis.com': 8444}
    assert tuple(ROUTES) == HOSTS and relay_mod.UPSTREAM_PORT == 443
    with pytest.raises(RelayError):
        Relay(config(), ports={'earthengine.googleapis.com': 1})


# --- relay behaviour ---------------------------------------------------------------

def test_dry_run_never_dials_and_logs_only_metadata():
    def no_dial(*a, **k):
        raise AssertionError('dry run must not open an upstream socket')
    with patch('socket.getaddrinfo', side_effect=AssertionError('DNS forbidden')), \
            Running(config(), dial=no_dial) as r:
        with r.connect() as c:
            try:
                c.sendall(b'CONNECT evil.example:443 HTTP/1.1\r\n\r\nsecret-payload')
                assert c.recv(10) == b''  # closed without forwarding anything
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass
        event = r.wait()[0]
    assert (event['outcome'], event['upstream'], event['host']) == ('dry_run', '142.250.1.10', 'earthengine.googleapis.com')
    assert 'secret-payload' not in json.dumps(r.events) and 'evil' not in json.dumps(r.events)


def test_forward_dials_only_the_pinned_ip_on_443_and_relays_bytes():
    dialed = []
    def dial(addr, timeout):
        dialed.append(addr)
        return raw_connect(echo.addr, timeout)
    with Echo() as echo, patch('socket.getaddrinfo', side_effect=AssertionError('DNS forbidden')), \
            Running(config(mode='forward'), dial=dial) as r:
        with r.connect('storage.googleapis.com') as c:
            c.sendall(b'tls-bytes-opaque')
            assert c.recv(100) == b'tls-bytes-opaque'
        event = r.wait()[0]
    assert dialed == [('142.250.2.20', 443)]
    assert event['upstream'] == '142.250.2.20' and event['bytes_out'] == 16 == event['bytes_in']
    assert 'tls-bytes-opaque' not in json.dumps(r.events)


def test_forward_falls_back_across_pins_then_fails_closed():
    dialed = []
    def dial(addr, timeout):
        dialed.append(addr)
        if addr[0] == '142.250.1.10':
            raise OSError('down')
        return raw_connect(echo.addr, timeout)
    with Echo() as echo, Running(config(mode='forward'), dial=dial) as r:
        with r.connect() as c:
            c.sendall(b'x')
            assert c.recv(1) == b'x'
        assert r.wait()[0]['upstream'] == '142.250.1.11'
    assert dialed == [('142.250.1.10', 443), ('142.250.1.11', 443)]

    def down(addr, timeout):
        raise OSError('down')
    with Running(config(mode='forward'), dial=down) as r:
        with r.connect() as c:
            assert c.recv(1) == b''
        assert r.wait()[0]['outcome'] == 'upstream_unreachable'


def test_relay_connection_and_byte_limits(monkeypatch):
    monkeypatch.setattr(relay_mod, 'MAX_ACTIVE', 1)
    monkeypatch.setattr(relay_mod, 'MAX_BYTES', 8)
    with Echo() as echo, Running(config(mode='forward'), dial=lambda a, timeout: raw_connect(echo.addr)) as r:
        first = r.connect()
        first.sendall(b'1234')
        assert first.recv(4) == b'1234'
        with r.connect() as second:
            assert second.recv(1) == b''
        assert r.wait('rejected')[0]['reason'] == 'limit'
        first.sendall(b'123456789')
        assert r.wait()[0]['outcome'] == 'byte_limit'
        first.close()


def test_relay_stops_accepting_after_expiry():
    events = []
    now = [time.time()]
    relay = Relay(config(), ports=free_ports(), listen_ip='127.0.0.1', log=events.append, wall=lambda: now[0])
    now[0] += 400
    thread = threading.Thread(target=relay.serve, daemon=True)
    thread.start()
    thread.join(3)
    assert not thread.is_alive() and events[-1]['event'] == 'stopped'


# --- recorder dialer through the relay ----------------------------------------------

def test_recorder_tls_dials_the_relay_port_but_verifies_the_real_hostname():
    import ssl
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    pins = replace(PinnedDestinations((('earthengine.googleapis.com', ('8.8.8.8',)),
        ('storage.googleapis.com', ('8.8.4.4',))), time.time() + 300), relay_ip='172.30.0.2')
    calls = []

    class Raw:
        def settimeout(self, v): pass
        def connect(self, addr): calls.append(addr)
        def close(self): pass
    for host, port in (('earthengine.googleapis.com', 8443), ('storage.googleapis.com', 8444)):
        calls.clear()
        conn = PinnedHTTPSConnection(host, pins=pins, context=ctx, timeout=2)
        with patch('socket.getaddrinfo', side_effect=AssertionError('DNS forbidden')), \
                patch('socket.socket', return_value=Raw()), \
                patch.object(ctx, 'wrap_socket', side_effect=lambda raw, **kw: calls.append(kw) or raw):
            conn.connect()
        assert calls == [('172.30.0.2', port), {'server_hostname': host}]
    with pytest.raises(GenuineBoundaryError, match='HOST_REJECTED'):
        PinnedHTTPSConnection('oauth2.googleapis.com', pins=pins, context=ctx)
    # None is the explicit direct-dial default (nft design); the relay is opt-in per pins.
    assert PinnedDestinations(pins.addresses, pins.expires_at).relay_ip is None
    with pytest.raises(GenuineBoundaryError, match='RELAY_REJECTED'):
        validate_relay_ip(None)


@pytest.mark.parametrize('ip', ['127.0.0.1', '8.8.8.8', '169.254.169.254', '0.0.0.0', 'relay',
    '172.030.0.2', '::1', 172, '224.0.0.1', '100.64.0.1', ''])
def test_relay_ip_must_be_an_rfc1918_literal(ip):
    with pytest.raises(GenuineBoundaryError, match='RELAY_REJECTED'):
        validate_relay_ip(ip)
    pins = PinnedDestinations((('earthengine.googleapis.com', ('8.8.8.8',)),
        ('storage.googleapis.com', ('8.8.4.4',))), time.time() + 300, relay_ip=ip)
    with pytest.raises(GenuineBoundaryError, match='RELAY_REJECTED'):
        pins.validate()


# --- isolation probes ---------------------------------------------------------------

def probe_config(role='probe-recorder', **change):
    return {'version': 1, 'role': role, 'relay_ip': '172.30.0.2', 'gateway_ip': '172.20.0.5',
        'pins': PINS, 'tls_handshake': False} | change


def fakes(**override):
    def tcp(ip, port):
        if ip == '172.30.0.2' and port in (8443, 8444):
            return override.get('relay', 'connected')
        return override.get('other', 'unreachable')
    return dict(tcp=tcp, dns=lambda name: override.get('dns', 'failed'),
        udp_dns=lambda ip: override.get('udp', 'timeout'),
        http_health=lambda ip: override.get('health', 200),
        tls_handshake=lambda relay, host: override.get('tls', {'result': 'verified'}))


def test_isolated_recorder_and_worker_pass():
    assert probe_mod.run(probe_config(), **fakes())['verdict'] == 'PASS'
    assert probe_mod.run(probe_config(tls_handshake=True), **fakes())['verdict'] == 'PASS'
    assert probe_mod.run(probe_config('probe-worker'), **fakes(relay='unreachable'))['verdict'] == 'PASS'
    result = probe_mod.run(probe_config(gateway_ip=None), **fakes())
    assert result['verdict'] == 'PASS' and 'gateway_health' not in result['checks']


@pytest.mark.parametrize('role,override,failed', [
    ('probe-recorder', {'other': 'connected'}, 'direct_google_142.250.1.10'),
    ('probe-recorder', {'dns': 'resolved'}, 'dns_example.com'),
    ('probe-recorder', {'udp': 'answered'}, 'udp_dns_1.1.1.1'),
    ('probe-recorder', {'relay': 'refused'}, 'relay_8443'),
    ('probe-recorder', {'health': 503}, 'gateway_health'),
    ('probe-worker', {'relay': 'connected'}, 'relay_8443'),
    ('probe-worker', {'other': 'connected'}, 'direct_external_1.1.1.1'),
])
def test_any_reachable_path_outside_the_policy_fails(role, override, failed):
    result = probe_mod.run(probe_config(role), **fakes(**override))
    assert result['verdict'] == 'FAIL' and failed in result['failed']


def test_tls_handshake_must_verify_the_real_certificate():
    result = probe_mod.run(probe_config(tls_handshake=True), **fakes(tls={'result': 'certificate_rejected'}))
    assert result['verdict'] == 'FAIL' and 'tls_earthengine.googleapis.com' in result['failed']


@pytest.mark.parametrize('change', [{'role': 'relay'}, {'relay_ip': '8.8.8.8'}, {'relay_ip': '127.0.0.1'},
    {'gateway_ip': '169.254.169.254'}, {'tls_handshake': 'yes'}, {'pins': {'earthengine.googleapis.com': ['1.1.1.1']}},
    {'pins': {**PINS, 'storage.googleapis.com': ['10.1.1.1']}}, {'extra': 1}, {'version': 2}])
def test_probe_config_is_exact(change):
    with pytest.raises(RelayError):
        probe_mod.run(probe_config(**change), **fakes())
    with pytest.raises(RelayError):
        probe_mod.validate_config(probe_config('probe-worker', tls_handshake=True))


def test_probe_primitives_classify_real_loopback_sockets():
    closed = socket.socket()
    closed.bind(('127.0.0.1', 0))
    port = closed.getsockname()[1]
    closed.close()
    # Linux refuses at once; Windows retries the SYN and times out. Never 'connected'.
    assert probe_mod.tcp('127.0.0.1', port, timeout=1) in (('refused', 'timeout') if sys.platform == 'win32' else ('refused',))
    server = socket.create_server(('127.0.0.1', 0))
    assert probe_mod.tcp('127.0.0.1', server.getsockname()[1], timeout=1) == 'connected'
    server.close()
    with patch('socket.getaddrinfo', side_effect=OSError('no dns')):
        assert probe_mod.dns('example.com') == 'failed'


# --- operator launcher (pure functions; Docker itself is NOT exercised here) ---------

def launcher():
    spec = importlib.util.spec_from_file_location('gee_egress_local', DEV / 'gee_egress_local.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspect_info(role='relay', **change):
    info = {'Image': 'sha256:' + 'a' * 64,
        'Config': {'User': '65534:65534', 'Entrypoint': ['/usr/local/bin/python3', '-I', '-B', '/app/egress_entry.py'],
            'Cmd': [role], 'Env': ['PATH=/usr/local/bin', 'LANG=C.UTF-8', 'PYTHON_VERSION=3.11']},
        'HostConfig': {'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'], 'CapAdd': None,
            'SecurityOpt': ['no-new-privileges:true'], 'PidsLimit': 32, 'Memory': 268435456,
            'MemorySwap': 268435456, 'NanoCpus': 500000000, 'PublishAllPorts': False,
            'PortBindings': {}, 'PidMode': '', 'IpcMode': 'private'},
        'Mounts': [], 'NetworkSettings': {'Networks': {'gis-a6-egress-int-x': {'IPAddress': '172.30.0.2'}}}}
    for path, value in change.items():
        section, key = path.split('.')
        info[section][key] = value
    return info


def test_launcher_container_verifier_accepts_only_the_exact_hardened_shape():
    m = launcher()
    measured, problems = m.verify_container(inspect_info(), image_id='sha256:' + 'a' * 64, role='relay',
        networks=['gis-a6-egress-int-x'])
    assert problems == [] and measured['networks'] == {'gis-a6-egress-int-x': '172.30.0.2'}
    bad = [
        {'HostConfig.Privileged': True}, {'HostConfig.ReadonlyRootfs': False},
        {'HostConfig.CapAdd': ['NET_ADMIN']}, {'HostConfig.CapDrop': []},
        {'HostConfig.PortBindings': {'8443/tcp': [{'HostPort': '8443'}]}},
        {'HostConfig.SecurityOpt': []}, {'HostConfig.PidMode': 'host'},
        {'Config.User': '0:0'}, {'Config.Cmd': ['probe-worker']},
        {'Config.Env': ['GOOGLE_APPLICATION_CREDENTIALS=/x']},
        {'NetworkSettings.Networks': {'bridge': {'IPAddress': '172.17.0.2'}}},
    ]
    for change in bad:
        _, problems = m.verify_container(inspect_info(**change), image_id='sha256:' + 'a' * 64,
            role='relay', networks=['gis-a6-egress-int-x'])
        assert problems, change
    _, problems = m.verify_container(inspect_info(), image_id='sha256:' + 'b' * 64, role='relay',
        networks=['gis-a6-egress-int-x'])
    assert 'image' in problems


def test_launcher_network_verifier_and_verdict():
    m = launcher()
    _, problems = m.verify_network({'Name': 'n', 'Internal': True, 'Driver': 'bridge', 'Containers': {}},
        name='n', internal=True)
    assert problems == []
    _, problems = m.verify_network({'Name': 'n', 'Internal': False, 'Driver': 'bridge'}, name='n', internal=True)
    assert problems == ['network_n']
    ok = {'probe-recorder': {'verdict': 'PASS'}, 'probe-worker': {'verdict': 'PASS'}}
    listening = [{'event': 'listening'}]
    conn = {'event': 'connection', 'host': 'earthengine.googleapis.com', 'upstream': '142.250.1.10', 'outcome': 'dry_run'}
    assert m.evaluate(probes=ok, measured_problems=[], relay_events=listening + [conn], pins=PINS,
        forward=False)['verdict'] == 'PASS'
    cases = [
        dict(probes={**ok, 'probe-worker': {'verdict': 'FAIL'}}),
        dict(measured_problems=['relay:Privileged']),
        dict(relay_events=listening + [{**conn, 'upstream': '8.8.8.8'}]),
        dict(relay_events=listening + [{**conn, 'outcome': 'closed'}]),
        dict(relay_events=[conn]),
        dict(probes={**ok, 'probe-recorder': {'verdict': 'NO_OUTPUT'}}),
    ]
    for case in cases:
        args = dict(probes=ok, measured_problems=[], relay_events=listening + [conn], pins=PINS, forward=False) | case
        assert m.evaluate(**args)['verdict'] == 'FAIL', case


def test_launcher_pin_snapshot_keeps_only_global_ipv4():
    m = launcher()
    def resolver(host, port, family, kind):
        ips = ['142.250.1.10', '10.0.0.1', '127.0.0.1', '142.250.1.10'] + [f'142.250.9.{i}' for i in range(1, 12)]
        return [(family, kind, 6, '', (ip, port)) for ip in ips]
    pins = m.resolve_pins(resolver)
    assert set(pins) == set(HOSTS) and all(len(v) == 8 for v in pins.values())
    assert all(not ip.startswith(('10.', '127.')) for v in pins.values() for ip in v)
    with pytest.raises(RuntimeError, match='PIN_RESOLUTION_FAILED'):
        m.resolve_pins(lambda *a: [(2, 1, 6, '', ('10.0.0.1', 443))])


@pytest.mark.parametrize('argv', [[], ['live'], ['relay', 'extra'], ['--offline-probe']])
def test_packaged_entry_accepts_only_fixed_roles(argv):
    entry = DEV / 'gee_egress_entry.py'
    result = subprocess.run([sys.executable, '-I', '-B', str(entry), *argv], input='{}\n',
        capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'GEE_EGRESS_ROLE_REJECTED' in result.stderr
    result = subprocess.run([sys.executable, '-I', '-B', str(entry), 'probe-worker'],
        input=json.dumps(probe_config('probe-recorder')) + '\n', capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'GEE_EGRESS_ROLE_REJECTED' in result.stderr
