"""One-job, one-lease Linux Recorder IPC; no generic HTTP/RPC proxy.

Supervisor creates SOCK_SEQPACKET endpoints, execs separate UID processes with
only their endpoint FD, and pins peer PID/UID + recorder verification key.
SCM_CREDENTIALS checks each sender (not socketpair creator's SO_PEERCRED).
Only Recorder holds Google credentials and the SQL047 Recorder identity.
"""
from datetime import date
import json
import os
import secrets
import socket
import struct
import time

from gis_worker.gee_genuine_identity import GenuineBoundaryError
from gis_worker.gee_live_contracts import canonical, Request

MAX_PACKET = 256 * 1024


def channel_pair():
    if not hasattr(socket, 'SCM_CREDENTIALS'):
        raise GenuineBoundaryError('GEE_RECORDER_LINUX_REQUIRED')
    pair = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    for endpoint in pair:
        endpoint.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        endpoint.settimeout(180)
    return pair


def receive(endpoint, *, pid, uid, timeout):
    try:
        if (endpoint.family != socket.AF_UNIX or endpoint.type != socket.SOCK_SEQPACKET
            or type(pid) is not int or pid <= 0 or type(uid) is not int or uid <= 0
            or not 0 < timeout <= 180):
            raise ValueError()
        endpoint.settimeout(timeout)
        raw, ancillary, flags, _ = endpoint.recvmsg(MAX_PACKET, socket.CMSG_SPACE(12))
        identities = [struct.unpack('3i', data) for level, kind, data in ancillary
            if level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS and len(data) == 12]
        if (not raw or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC)
            or len(identities) != 1 or identities[0][:2] != (pid, uid)):
            raise ValueError()
        def unique(pairs):
            d = {}
            for k,v in pairs:
                if k in d: raise ValueError()
                d[k]=v
            return d
        value = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(value, dict) or canonical(value).encode() != raw:
            raise ValueError()
        return value
    except Exception:
        endpoint.close()
        raise GenuineBoundaryError('GEE_RECORDER_CHANNEL_REJECTED') from None


def send(endpoint, value):
    try:
        raw = canonical(value).encode()
        if len(raw) > MAX_PACKET or endpoint.send(raw) != len(raw):
            raise ValueError()
    except Exception:
        endpoint.close()
        raise GenuineBoundaryError('GEE_RECORDER_CHANNEL_REJECTED') from None


class RecorderClient:
    """Worker dependency containing NO Google token or Recorder GIS JWT."""
    def __init__(self, endpoint, *, binding, recorder_pid, recorder_uid, recorder_key,
        clock=time.monotonic):
        if (type(recorder_key) is not bytes or len(recorder_key) != 32
            or recorder_uid == os.getuid()):
            raise GenuineBoundaryError('GEE_RECORDER_PEER_REJECTED')
        self.endpoint, self.binding = endpoint, binding
        self.pid, self.uid, self.key = recorder_pid, recorder_uid, recorder_key
        self.clock, self.deadline, self.used = clock, clock()+180, False

    def compute(self, request, geometry, *, as_of):
        self.binding.check(request, geometry)
        if self.used or type(as_of) is not date:
            raise GenuineBoundaryError('GEE_RECORDER_REPLAY')
        self.used = True
        nonce = secrets.token_hex(32)
        value = {'version':1,'action':'compute','binding':self.binding.fingerprint(),
            'nonce':nonce,'sequence':1,'as_of':as_of.isoformat()}
        try:
            send(self.endpoint,value)
            response = receive(self.endpoint,pid=self.pid,uid=self.uid,
                timeout=min(180,self.deadline-self.clock()))
            if set(response) != {'envelope','signature'}:
                raise ValueError()
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            Ed25519PublicKey.from_public_bytes(self.key).verify(
                bytes.fromhex(response['signature']),canonical(response['envelope']).encode())
            envelope=response['envelope']
            if (set(envelope) != {'request','report'} or envelope['request'] != value
                or self.clock() >= self.deadline):
                raise ValueError()
            report=envelope['report']
            if (report.get('protocol') != 'gee_genuine_https' or report.get('schema_version') != 4
                or report.get('session_id') != str(self.binding.session_id)
                or report.get('base',{}).get('input_hash') != self.binding.input_hash
                or report.get('base',{}).get('input_revision') != self.binding.input_revision):
                raise ValueError()
            # Signature authenticates the process response, NOT Google origin.
            # SQL047 complete + immutable seal still enforce scientific/fencing invariants.
            return report
        except Exception:
            raise GenuineBoundaryError('GEE_RECORDER_RESPONSE_REJECTED') from None
        finally:
            self.endpoint.close()


def serve_once(endpoint, *, binding, worker_pid, worker_uid, signer, runtime,
    request, geometry, as_of, timeout=180):
    """Trusted supervisor dependencies, NOT job-selectable callbacks/commands.

    The real runtime is the gated GenuineWorkerRuntime using SDK accounting and
    SQL047 recorder. An offline test may inject a synthetic runtime explicitly.
    """
    try:
        if worker_uid == os.getuid():
            raise ValueError()
        binding.check(request,geometry)
        value=receive(endpoint,pid=worker_pid,uid=worker_uid,timeout=timeout)
        if (set(value) != {'version','action','binding','nonce','sequence','as_of'}
            or type(value['version']) is not int or value['version'] != 1
            or value['action'] != 'compute' or value['binding'] != binding.fingerprint()
            or type(value['sequence']) is not int or value['sequence'] != 1
            or value['as_of'] != as_of.isoformat()
            or type(value['nonce']) is not str or len(value['nonce']) != 64
            or any(c not in '0123456789abcdef' for c in value['nonce'])):
            raise ValueError()
        report=runtime.compute(request,geometry,as_of=as_of)
        envelope={'request':value,'report':report}
        send(endpoint,{'envelope':envelope,'signature':signer(canonical(envelope).encode()).hex()})
    except Exception:
        # Do not send raw exception, credential, signing key or transport data.
        raise GenuineBoundaryError('GEE_RECORDER_SESSION_FAILED') from None
    finally:
        endpoint.close()


class RecorderWorkerRuntime:
    """Exact IPC-only runtime accepted by the existing queue worker."""
    def __init__(self, client):
        if type(client) is not RecorderClient:
            raise GenuineBoundaryError('GEE_RECORDER_CLIENT_REQUIRED')
        # A channel object alone never authorizes Live startup.
        from gis_worker.gee_genuine_runtime import require_selective_egress
        require_selective_egress(None,client.binding)
        self.client, self.binding = client, client.binding

    def compute(self,*args,**kwargs):
        return self.client.compute(*args,**kwargs)
