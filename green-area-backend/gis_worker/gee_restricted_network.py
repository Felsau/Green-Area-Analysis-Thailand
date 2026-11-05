"""No runtime DNS; pinned IPv4/TLS dialer and default-deny namespace policy.

Generating nft rules does not install or attest them. Live gate remains closed.
The worker cannot use this dialer: its seccomp policy forbids Internet sockets.
"""
from dataclasses import dataclass
import ctypes
import errno
import http.client
import ipaddress
import platform
import os
from pathlib import Path
import stat
import socket
import ssl
import time

from gis_worker.gee_genuine_identity import GenuineBoundaryError

HOSTS = ('earthengine.googleapis.com', 'storage.googleapis.com')
# Local SQL047 gateway: one fixed port on an RFC1918 IP literal. Never a hostname
# (no DNS inside the Recorder netns), loopback, link-local/metadata or public IP.
GATEWAY_PORT = 8000
GATEWAY_NETWORKS = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def validate_gateway_endpoint(endpoint):
    try:
        if type(endpoint) is not tuple or len(endpoint) != 2:
            raise ValueError()
        host, port = endpoint
        if type(host) is not str or type(port) is not int or port != GATEWAY_PORT:
            raise ValueError()
        ip = ipaddress.IPv4Address(host)  # rejects names, IPv6, octal and padded forms
        if (str(ip) != host or not any(ip in n for n in GATEWAY_NETWORKS)
            or ip.is_loopback or ip.is_link_local or ip.is_multicast
            or ip.is_unspecified or ip.is_reserved):
            raise ValueError()
    except Exception:
        raise GenuineBoundaryError('GEE_EGRESS_GATEWAY_REJECTED') from None
    return endpoint


@dataclass(frozen=True)
class PinnedDestinations:
    # Supervisor-supplied authenticated DNS snapshot. Never accepted from jobs.
    addresses: tuple
    expires_at: float
    gateway_endpoint: tuple | None = None

    def validate(self, *, wall=time.time):
        if (type(self.expires_at) not in (int, float)
            or not 0 < self.expires_at - wall() <= 1200
            or type(self.addresses) is not tuple or len(self.addresses) != 2):
            raise GenuineBoundaryError('GEE_EGRESS_PIN_REJECTED')
        if tuple(h for h, _ in self.addresses) != HOSTS:
            raise GenuineBoundaryError('GEE_EGRESS_HOST_REJECTED')
        for _, ips in self.addresses:
            if type(ips) is not tuple or not 1 <= len(ips) <= 8 or len(set(ips)) != len(ips):
                raise GenuineBoundaryError('GEE_EGRESS_PIN_REJECTED')
            for ip in ips:
                try:
                    v = ipaddress.IPv4Address(ip)
                    if str(v) != ip or not v.is_global:
                        raise ValueError()
                except Exception:
                    raise GenuineBoundaryError('GEE_EGRESS_IP_REJECTED') from None
        if self.gateway_endpoint is not None:
            validate_gateway_endpoint(self.gateway_endpoint)
        return self

    def address(self, host, *, wall=time.time):
        self.validate(wall=wall)
        if host not in HOSTS:
            raise GenuineBoundaryError('GEE_EGRESS_HOST_REJECTED')
        return dict(self.addresses)[host][0]

    def nft_rules(self, *, wall=time.time):
        """For a NEW isolated Recorder netns, never the host/existing namespace.

        Drops IPv6, UDP, DNS53, non443, localhost and all other destinations.
        Optionally permits one validated RFC1918 SQL gateway IP:8000 (gateway_endpoint).
        No broad established-flow exception; no hostname/DNS at packet time.
        IP list is short-lived; expiry must also be enforced by supervisor.
        """
        self.validate(wall=wall)
        ips = ', '.join(sorted({ip for _, ips in self.addresses for ip in ips}))
        rules = ('table inet gee_recorder {\n'
            ' set approved4 { type ipv4_addr; elements = { ' + ips + ' }; }\n')
        if self.gateway_endpoint is not None:
            gw_ip, gw_port = self.gateway_endpoint
            rules += (' set approved_sql { type ipv4_addr; elements = { ' + gw_ip + ' }; }\n'
                ' chain output { type filter hook output priority -100; policy drop;\n'
                '  ip daddr @approved4 tcp dport 443 accept\n'
                f'  ip daddr @approved_sql tcp dport {gw_port} accept\n'
                ' }\n'
                ' chain input { type filter hook input priority -100; policy drop;\n'
                '  ip saddr @approved4 tcp sport 443 ct state established accept\n'
                f'  ip saddr @approved_sql tcp sport {gw_port} ct state established accept\n'
                ' }\n')
        else:
            rules += (' chain output { type filter hook output priority -100; policy drop;\n'
                '  ip daddr @approved4 tcp dport 443 accept\n }\n'
                ' chain input { type filter hook input priority -100; policy drop;\n'
                '  ip saddr @approved4 tcp sport 443 ct state established accept\n }\n')
        rules += ' chain forward { type filter hook forward priority -100; policy drop; }\n}\n'
        return rules


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """No getaddrinfo, DNS rebinding, proxy tunnel, redirects or IP-as-host.

    TLS verification uses the original approved DNS hostname, despite dialing a
    literal address. Context comes from the existing explicit Certifi boundary.
    """
    def __init__(self, host, *, pins, **kwargs):
        self.pins = pins
        pins.address(host)
        super().__init__(host, **kwargs)

    def connect(self):
        if self._tunnel_host or self.port != 443:
            raise GenuineBoundaryError('GEE_EGRESS_TUNNEL_REJECTED')
        ctx = self._context
        if (ctx.verify_mode != ssl.CERT_REQUIRED or not ctx.check_hostname
            or ctx.keylog_filename is not None):
            raise GenuineBoundaryError('GEE_EGRESS_TLS_REJECTED')
        ip = self.pins.address(self.host)
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            raw.settimeout(self.timeout)
            raw.connect((ip, 443))
            self.sock = ctx.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise GenuineBoundaryError('GEE_EGRESS_DIAL_FAILED') from None


def deny_internet_sockets():
    """Irreversible Linux amd64 seccomp, called AFTER clean exec/bootstrap.

    Only AF_UNIX socket creation permitted. Also denies ptrace/namespace escape,
    FD theft and io_uring bypass. Inherited FDs must separately be allowlisted.
    Unsupported platform/install failure stops the process; no fallback.
    """
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise GenuineBoundaryError('GEE_KERNEL_ISOLATION_UNSUPPORTED')
    if len(list(Path('/proc/self/task').iterdir())) != 1:
        raise GenuineBoundaryError('GEE_KERNEL_THREADS_REJECTED')
    class Filter(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte),
            ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_ = [('len', ctypes.c_ushort), ('filter', ctypes.POINTER(Filter))]
    # arch then syscall number; x32/other ABIs fail closed.
    instructions = [(0x20,0,0,4), (0x15,1,0,0xc000003e), (0x06,0,0,0x80000000),
        (0x20,0,0,0), (0x35,0,1,0x40000000), (0x06,0,0,0x80000000),
        (0x15,0,4,41), (0x20,0,0,16), (0x15,1,0,socket.AF_UNIX),
        (0x06,0,0,0x00050000|errno.EPERM), (0x06,0,0,0x7fff0000)]
    # deny socketpair of other domains too; AF_UNIX socketpairs remain allowed.
    instructions += [(0x15,0,4,53),(0x20,0,0,16),(0x15,1,0,socket.AF_UNIX),
        (0x06,0,0,0x00050000|errno.EPERM),(0x06,0,0,0x7fff0000)]
    for nr in (101,155,165,166,272,308,310,311,321,425,426,427,438):
        instructions += [(0x15,0,1,nr),(0x06,0,0,0x00050000|errno.EPERM)]
    instructions += [(0x06,0,0,0x7fff0000)]
    arr=(Filter*len(instructions))(*(Filter(*v) for v in instructions))
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(38,1,0,0,0) or libc.prctl(4,0,0,0,0):
        raise GenuineBoundaryError('GEE_KERNEL_ISOLATION_FAILED')
    prog=Program(len(instructions),arr)
    if libc.prctl(22,2,ctypes.byref(prog),0,0):
        raise GenuineBoundaryError('GEE_KERNEL_ISOLATION_FAILED')


def isolate_recorder_child(*, uid, ipc_fds):
    """After clean exec + UID drop, before receiving secrets/starting threads.

    Standard streams must be supervisor pipes; only explicit Unix packet
    endpoints pass. No inherited files, Internet sockets or unknown FDs.
    Installs deny-all-Internet, NOT selective Live egress approval.
    """
    if (platform.system()!='Linux' or type(uid) is not int or uid<=0 or os.getuid()!=uid
        or os.getgid()!=uid or os.getgroups()
        or type(ipc_fds) is not tuple or not 1<=len(ipc_fds)<=2
        or len(set(ipc_fds))!=len(ipc_fds)
        or any(type(fd) is not int or fd<3 for fd in ipc_fds)):
        raise GenuineBoundaryError('GEE_CHILD_IDENTITY_REJECTED')
    try:
        actual={int(p.name) for p in Path('/proc/self/fd').iterdir()}
        # Exclude the now-closed transient directory FD used for enumeration.
        actual={fd for fd in actual if Path('/proc/self/fd/'+str(fd)).exists()}
        if actual!={0,1,2,*ipc_fds}:
            raise ValueError()
        if any(not stat.S_ISFIFO(os.fstat(fd).st_mode) for fd in (0,1,2)):
            raise ValueError()
        for fd in ipc_fds:
            with socket.socket(fileno=os.dup(fd)) as endpoint:
                if endpoint.family!=socket.AF_UNIX or endpoint.type!=socket.SOCK_SEQPACKET:
                    raise ValueError()
    except Exception:
        raise GenuineBoundaryError('GEE_CHILD_FD_REJECTED') from None
    deny_internet_sockets()
