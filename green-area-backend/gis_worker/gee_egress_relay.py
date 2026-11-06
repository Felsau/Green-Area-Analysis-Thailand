"""Fixed-route TCP egress relay for the Recorder's Docker internal network.

The Recorder container has no route to the Internet (Docker ``internal`` network).
This relay is the only member of that network that is also on an egress bridge.
Each listen port forwards raw bytes to the pinned IPv4 addresses of exactly one
approved Google host on tcp/443. TLS stays end-to-end between the Recorder and
Google: the relay never terminates TLS, never parses HTTP, never resolves DNS and
has no CONNECT or destination selection. Clients cannot choose where it dials.

``dry_run`` accepts and logs the upstream it WOULD dial, then closes without
opening any upstream socket. Only metadata is logged, never payload bytes.
Stdlib only. The pinned addresses are a supervisor DNS snapshot, not authenticated.
"""
import ipaddress
import json
import selectors
import socket
import sys
import threading
import time

ROUTES = {'earthengine.googleapis.com': 8443, 'storage.googleapis.com': 8444}
UPSTREAM_PORT = 443
PRIVATE = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
MAX_ACTIVE = 4
MAX_TOTAL = 64
LIFETIME = 180
IDLE = 30
CONNECT_TIMEOUT = 10
MAX_BYTES = 8 * 1024 * 1024
CONFIG_KEYS = {'version', 'mode', 'bind_ip', 'expires_at', 'routes'}


class RelayError(ValueError):
    pass


def _ipv4(value, *, private):
    if type(value) is not str:
        raise RelayError('GEE_RELAY_IP_REJECTED')
    try:
        ip = ipaddress.IPv4Address(value)
    except ValueError:
        raise RelayError('GEE_RELAY_IP_REJECTED') from None
    ok = (any(ip in n for n in PRIVATE) and not ip.is_loopback) if private else ip.is_global
    if str(ip) != value or not ok or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        raise RelayError('GEE_RELAY_IP_REJECTED')
    return value


def validate_config(config, *, wall=time.time):
    if type(config) is not dict or set(config) != CONFIG_KEYS:
        raise RelayError('GEE_RELAY_CONFIG_REJECTED')
    if (config['version'] != 1 or type(config['version']) is not int
        or config['mode'] not in ('dry_run', 'forward')
        or type(config['expires_at']) is not int
        or not 0 < config['expires_at'] - wall() <= 1200):
        raise RelayError('GEE_RELAY_CONFIG_REJECTED')
    _ipv4(config['bind_ip'], private=True)
    routes = config['routes']
    if type(routes) is not dict or set(routes) != set(ROUTES):
        raise RelayError('GEE_RELAY_ROUTE_REJECTED')
    for ips in routes.values():
        if type(ips) is not list or not 1 <= len(ips) <= 8 or len(set(ips)) != len(ips):
            raise RelayError('GEE_RELAY_ROUTE_REJECTED')
        for ip in ips:
            _ipv4(ip, private=False)
    return {'version': 1, 'mode': config['mode'], 'bind_ip': config['bind_ip'],
        'expires_at': config['expires_at'], 'routes': {h: list(v) for h, v in routes.items()}}


def _stdout(event):
    sys.stdout.write(json.dumps(event, sort_keys=True, separators=(',', ':')) + '\n')
    sys.stdout.flush()


class Relay:
    """``dial``, ``ports`` and ``listen_ip`` are code-level injection points for tests only.

    They are never read from configuration, environment or a client.
    """
    def __init__(self, config, *, dial=socket.create_connection, ports=None, listen_ip=None,
        log=_stdout, wall=time.time, clock=time.monotonic):
        self.config = validate_config(config, wall=wall)
        # Tests may listen on loopback; the packaged entry never passes listen_ip.
        self.listen_ip = self.config['bind_ip'] if listen_ip is None else listen_ip
        self.dial, self.log, self.wall, self.clock = dial, log, wall, clock
        self.ports = dict(ports or ROUTES)
        if set(self.ports) != set(ROUTES):
            raise RelayError('GEE_RELAY_ROUTE_REJECTED')
        self.lock = threading.Lock()
        self.active = self.total = 0
        self.stop = threading.Event()
        self.threads = []

    def serve(self):
        listeners = {}
        try:
            for host, port in self.ports.items():
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((self.listen_ip, port))
                s.listen(8)
                s.setblocking(False)
                listeners[s] = host
            self.log({'event': 'listening', 'mode': self.config['mode'],
                'ports': {h: p for h, p in self.ports.items()}})
            with selectors.DefaultSelector() as sel:
                for s in listeners:
                    sel.register(s, selectors.EVENT_READ)
                while not self.stop.is_set() and self.wall() < self.config['expires_at']:
                    for key, _ in sel.select(timeout=.2):
                        try:
                            client, peer = key.fileobj.accept()
                        except OSError:
                            continue
                        self._admit(client, peer, listeners[key.fileobj])
        finally:
            for s in listeners:
                s.close()
            self.stop.set()
            for t in self.threads:
                t.join(timeout=LIFETIME)
            self.log({'event': 'stopped', 'total': self.total})

    def _admit(self, client, peer, host):
        with self.lock:
            if self.active >= MAX_ACTIVE or self.total >= MAX_TOTAL:
                client.close()
                self.log({'event': 'rejected', 'host': host, 'reason': 'limit'})
                return
            self.active += 1
            self.total += 1
        t = threading.Thread(target=self._handle, args=(client, peer, host), daemon=True)
        self.threads.append(t)
        t.start()

    def _handle(self, client, peer, host):
        started, sent, received, outcome, upstream_ip = self.clock(), 0, 0, 'closed', None
        upstream = None
        try:
            ips = self.config['routes'][host]
            if self.config['mode'] == 'dry_run':
                upstream_ip, outcome = ips[0], 'dry_run'
                return
            for ip in ips:
                try:
                    upstream = self.dial((ip, UPSTREAM_PORT), timeout=CONNECT_TIMEOUT)
                    upstream_ip = ip
                    break
                except OSError:
                    continue
            if upstream is None:
                outcome = 'upstream_unreachable'
                return
            sent, received, outcome = self._pump(client, upstream, started)
        except Exception:
            outcome = 'error'
        finally:
            for s in (client, upstream):
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass
            with self.lock:
                self.active -= 1
            self.log({'event': 'connection', 'host': host, 'upstream': upstream_ip,
                'peer': peer[0] if isinstance(peer, tuple) else None, 'outcome': outcome,
                'bytes_out': sent, 'bytes_in': received,
                'seconds': round(self.clock() - started, 3)})

    def _pump(self, client, upstream, started):
        counts = {client: 0, upstream: 0}
        other = {client: upstream, upstream: client}
        last = self.clock()
        with selectors.DefaultSelector() as sel:
            for s in (client, upstream):
                s.setblocking(False)
                sel.register(s, selectors.EVENT_READ)
            while True:
                now = self.clock()
                if now - started > LIFETIME:
                    return counts[client], counts[upstream], 'lifetime'
                if now - last > IDLE:
                    return counts[client], counts[upstream], 'idle'
                if self.stop.is_set():
                    return counts[client], counts[upstream], 'stopped'
                for key, _ in sel.select(timeout=.2):
                    src = key.fileobj
                    try:
                        data = src.recv(65536)
                    except BlockingIOError:
                        continue
                    if not data:
                        return counts[client], counts[upstream], 'closed'
                    counts[src] += len(data)
                    if counts[src] > MAX_BYTES:
                        return counts[client], counts[upstream], 'byte_limit'
                    other[src].setblocking(True)
                    other[src].settimeout(IDLE)
                    other[src].sendall(data)
                    other[src].setblocking(False)
                    last = self.clock()
