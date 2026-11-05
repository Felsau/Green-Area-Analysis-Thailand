"""Synthetic observations/IPC only; no token issuance or Google network."""
from dataclasses import replace
from datetime import datetime, timezone, date
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

if __name__ == '__main__':
    # Fixed packaged paths, not environment-supplied dependency discovery.
    sys.path[:0]=['/sdk',str(Path(__file__).parents[1]),str(Path(__file__).parent)]

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from test_gee_genuine_foundation import packet
from gis_worker.gee_genuine_identity import ExplicitGoogleCredentials, GenuineBoundaryError
from gis_worker.gee_operator_delivery import OperatorDelivery, MintObservation, MINT_URL, SCOPES, observe_real_mint
from gis_worker.gee_restricted_network import (PinnedDestinations, PinnedHTTPSConnection,
    deny_internet_sockets, isolate_recorder_child)
from gis_worker.gee_recorder_channel import channel_pair, receive, send, RecorderClient, serve_once
from gis_worker.gee_genuine_runtime import GenuineBinding, require_selective_egress
from gis_worker.gee_live_contracts import Request, canonical

LINUX = sys.platform == 'linux'


def observed(binding, change=None):
    observer,issuer=Ed25519PrivateKey.generate(),Ed25519PrivateKey.generate()
    observation=MintObservation(b'synthetic-observed-only',MINT_URL,
        {'scope':SCOPES,'lifetime':'1800s'},
        {'projectId':binding.project.project_id,'email':binding.project.principal,
            'uniqueId':binding.principal_id,'disabled':False},
        '1970-01-01T00:20:00Z',1000,'b'*64,binding.fingerprint(),b'')
    if change: observation=replace(observation,**change)
    observation=replace(observation,signature=observer.sign(observation.message()))
    provider=OperatorDelivery(binding=binding,observer_key=observer.public_key().public_bytes_raw(),
        issuer=issuer.sign,challenge='b'*64,wall=lambda:1000)
    return provider,observation,issuer


def test_observed_mint_contract_to_signed_delivery_explicitly():
    _,_,_,binding,_=packet();provider,o,key=observed(binding)
    delivered=provider.deliver(o)
    c=ExplicitGoogleCredentials(delivered,binding,issuer_key=key.public_key().public_bytes_raw(),
        wall=lambda:1000,monotonic=lambda:10)
    assert c.headers(binding)['Authorization']=='Bearer synthetic-observed-only'
    assert 'synthetic-observed-only' not in repr(o)+repr(delivered)+repr(c)
    with pytest.raises(GenuineBoundaryError,match='REPLAY'):provider.deliver(o)
    c.close()


@pytest.mark.parametrize('change',[
    {'request_url':MINT_URL.replace('green-area-gis-sandbox','innate-beacon-483307-v1')},
    {'request_body':{'scope':['https://www.googleapis.com/auth/cloud-platform'],'lifetime':'1800s'}},
    {'response_expire_time':'1970-01-01T00:16:40Z'},
    {'response_expire_time':'1970-01-01T00:20:00'},
    {'response_expire_time':'1970-01-02T00:20:00Z'},
    {'observed_at':980},{'observed_at':1001},{'nonce':'c'*64},
    {'binding_sha256':'a'*64},
    {'service_account':{'projectId':'green-area-gis-sandbox','email':'wrong','uniqueId':'1','disabled':False}},
])
def test_mint_identity_expiry_scope_and_freshness_rejected(change):
    *_,b,j=packet();p,o,k=observed(b,change)
    with pytest.raises(GenuineBoundaryError,match='OBSERVATION_REJECTED'):p.deliver(o)


def test_forged_observation_and_unverified_real_observer_fail_closed():
    *_,b,j=packet();p,o,k=observed(b)
    with pytest.raises(GenuineBoundaryError):p.deliver(replace(o,token=b'synthetic-forgery-only'))
    with pytest.raises(GenuineBoundaryError,match='NOT_VERIFIED'):observe_real_mint()
    with pytest.raises(GenuineBoundaryError,match='NOT_VERIFIED'):require_selective_egress(True,b)


def test_rfc3339_fractional_expiry_is_conservatively_floored():
    *_,b,j=packet();p,o,k=observed(b,{'response_expire_time':'1970-01-01T00:20:00.123456789Z'})
    assert p.deliver(o).expires_at==1200


def pins():
    return PinnedDestinations((('earthengine.googleapis.com',('8.8.8.8',)),
        ('storage.googleapis.com',('8.8.4.4',))),time.time()+300)


@pytest.mark.parametrize('ip',['127.0.0.1','169.254.169.254','10.0.0.1','::1','8.8.8.8; accept','0177.0.0.1'])
def test_pin_ip_injection_private_metadata_loopback_denied(ip):
    p=replace(pins(),addresses=(('earthengine.googleapis.com',(ip,)),('storage.googleapis.com',('8.8.4.4',))))
    with pytest.raises(GenuineBoundaryError):p.validate()


@pytest.mark.parametrize('host',['innate-beacon-483307-v1','8.8.8.8','earthengine.googleapis.com.evil',
    'oauth2.googleapis.com','iamcredentials.googleapis.com'])
def test_no_ip_as_host_or_auth_endpoint(host):
    with pytest.raises(GenuineBoundaryError):pins().address(host)


def test_expired_pins_no_dns_no_broad_established_nft_allow():
    p=pins();text=p.nft_rules()
    assert 'policy drop' in text and 'tcp dport 443' in text and 'udp' not in text
    assert 'dport 53' not in text and 'ip6' not in text
    assert 'ct state established accept' not in text.split('chain output')[1].split('chain input')[0]
    with pytest.raises(GenuineBoundaryError):replace(p,expires_at=time.time()-1).validate()


def test_literal_dial_preserves_hostname_tls_and_never_resolves_dns():
    import ssl
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    calls=[]
    class Raw:
        def settimeout(self,v):pass
        def connect(self,addr):calls.append(addr)
        def close(self):pass
    conn=PinnedHTTPSConnection('earthengine.googleapis.com',pins=pins(),context=ctx,timeout=2)
    with patch('socket.getaddrinfo',side_effect=AssertionError('DNS forbidden')), \
        patch('socket.socket',return_value=Raw()), \
        patch.object(ctx,'wrap_socket',side_effect=lambda raw,**kw:calls.append(kw) or raw):
        conn.connect()
    assert calls==[('8.8.8.8',443),{'server_hostname':'earthengine.googleapis.com'}]


@pytest.mark.skipif(not LINUX,reason='Linux kernel boundary')
@pytest.mark.parametrize('family',[socket.AF_INET,socket.AF_INET6,getattr(socket,'AF_PACKET',17)])
def test_seccomp_denies_real_socket_syscalls(family):
    code="import sys,socket;sys.path.insert(0,sys.argv[1]);from gis_worker.gee_restricted_network import deny_internet_sockets;deny_internet_sockets();socket.socket(int(sys.argv[2]),socket.SOCK_STREAM)"
    result=subprocess.run([sys.executable,'-I','-B','-c',code,str(Path(__file__).parents[1]),str(family)],
        capture_output=True,timeout=10,env={})
    assert result.returncode!=0 and b'Operation not permitted' in result.stderr


@pytest.mark.skipif(not LINUX,reason='Linux kernel boundary')
def test_seccomp_allows_unix_and_no_namespace_escape():
    code="""import sys,socket,ctypes
sys.path.insert(0,sys.argv[1])
from gis_worker.gee_restricted_network import deny_internet_sockets
deny_internet_sockets()
a,b=socket.socketpair();a.send(b'ok');assert b.recv(2)==b'ok'
lib=ctypes.CDLL(None,use_errno=True);assert lib.unshare(0x40000000)==-1
assert ctypes.get_errno()==1
"""
    result=subprocess.run([sys.executable,'-I','-B','-c',code,str(Path(__file__).parents[1])],capture_output=True,timeout=10,env={})
    assert result.returncode==0,result.stderr.decode()


@pytest.mark.skipif(not LINUX,reason='Linux thread-wide kernel installation boundary')
def test_seccomp_refuses_install_after_threads_started():
    code='''import sys,threading
sys.path.insert(0,sys.argv[1])
from gis_worker.gee_restricted_network import deny_internet_sockets
e=threading.Event();t=threading.Thread(target=e.wait);t.start()
try:
 try:deny_internet_sockets()
 except ValueError as x:assert str(x)=='GEE_KERNEL_THREADS_REJECTED'
 else:raise AssertionError('thread bypass')
finally:e.set();t.join()
'''
    result=subprocess.run([sys.executable,'-I','-B','-c',code,str(Path(__file__).parents[1])],capture_output=True,timeout=10,env={})
    assert result.returncode==0,result.stderr.decode()


@pytest.mark.skipif(not LINUX,reason='Linux credential-bearing IPC')
def test_wrong_peer_and_oversized_or_duplicate_packets_rejected():
    a,b=channel_pair();a.send(b'{}')
    with pytest.raises(GenuineBoundaryError):receive(b,pid=os.getpid()+1,uid=10001,timeout=.2)
    a.close()


@pytest.mark.skipif(not LINUX or os.geteuid()!=0,reason='Linux UID credential parser checks')
@pytest.mark.parametrize('kind',['duplicate','oversized'])
def test_malformed_packet_from_correct_actual_peer(kind):
    a,b=channel_pair()
    a.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,1024*1024)
    code='''import os,sys,socket
s=socket.socket(fileno=int(sys.argv[1]));os.setgroups([]);os.setgid(10001);os.setuid(10001)
s.settimeout(3);s.send(b'{"x":1,"x":1}' if sys.argv[2]=='duplicate' else b'x'*(256*1024+1))
'''
    child=subprocess.Popen([sys.executable,'-I','-B','-c',code,str(a.fileno()),kind],
        pass_fds=(a.fileno(),),stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={})
    a.close()
    try:
        with pytest.raises(GenuineBoundaryError):receive(b,pid=child.pid,uid=10001,timeout=5)
        out,error=child.communicate(timeout=5)
        assert child.returncode==0,error
    finally:
        if child.poll() is None:child.kill();child.wait(timeout=5)


@pytest.mark.skipif(not LINUX or os.geteuid()!=0,reason='Isolated Linux root supervisor drops child UIDs')
@pytest.mark.parametrize('scenario',['ok','forged','nonce','rpc_bypass','timeout','crash','extra_fd'])
def test_separate_uid_recorder_worker_processes_and_replacement(scenario):
    """Clean exec; no fork-copied credentials. Secret born in Recorder child.

    No real runtime/DB. Lease recovery/fencing remain SQL047 authority and use
    unchanged prior evidence; this proves IPC failure/clean replacement only.
    """
    req,geom,_,binding,_=packet();a,b=channel_pair()
    child=Path(__file__).resolve()
    command=[sys.executable,'-I','-B',str(child),'--boundary-child']
    safeenv={}
    w=subprocess.Popen(command+['worker',str(a.fileno())],pass_fds=(a.fileno(),),
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=safeenv)
    r=subprocess.Popen(command+['recorder',str(b.fileno())],pass_fds=(b.fileno(),),
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=safeenv)
    a.close();b.close()
    config={'binding':binding.model_dump(mode='json'),'request':req.model_dump(mode='json'),
        'geometry':geom,'scenario':scenario,'worker_pid':w.pid,'recorder_pid':r.pid}
    try:
        r.stdin.write((json.dumps(config)+'\n').encode());r.stdin.flush()
        # Public verification key only; never tokens/signing keys on stdout.
        import select
        assert select.select([r.stdout],[],[],10)[0],'recorder startup deadline'
        key=r.stdout.readline().decode().strip();assert len(key)==64
        config['key']=key
        wo,we=w.communicate((json.dumps(config)+'\n').encode(),timeout=12)
        r.wait(timeout=12)
        assert w.returncode==0,(wo,we)
        assert wo.strip()==(b'ACCEPTED' if scenario=='ok' else b'REJECTED')
        assert b'synthetic-recorder-secret' not in wo+we
    finally:
        for process in (w,r):
            if process.poll() is None:process.kill();process.wait(timeout=5)
    if scenario=='crash':
        # Fresh exec/channel/key after failure; SQL fencing evidence remains separate.
        test_separate_uid_recorder_worker_processes_and_replacement('ok')


def boundary_child():
    # Invoked only by the explicit offline tests above, never by Live launcher.
    sys.path.insert(0,str(Path(__file__).parents[1]))
    role,fd=sys.argv[2],int(sys.argv[3]);config=json.loads(sys.stdin.readline())
    endpoint=socket.socket(fileno=fd)
    # Already clean exec/close_fds; setgroups BEFORE irrevocable UID drop.
    os.setgroups([]);os.setgid(10002 if role=='recorder' else 10001)
    os.setuid(10002 if role=='recorder' else 10001)
    if config['scenario']=='extra_fd' and role=='worker':
        with open('/dev/null','rb'):
            try:isolate_recorder_child(uid=10001,ipc_fds=(fd,))
            except GenuineBoundaryError:print('REJECTED');return
            raise AssertionError('inherited FD accepted')
    isolate_recorder_child(uid=10002 if role=='recorder' else 10001,ipc_fds=(fd,))
    binding=GenuineBinding.model_validate(config['binding'])
    request=Request.model_validate(config['request']);geometry=config['geometry']
    if role=='recorder':
        key=Ed25519PrivateKey.generate()
        print(key.public_key().public_bytes_raw().hex(),flush=True)
        secret=b'synthetic-recorder-secret-only' # never in Worker memory
        scenario=config['scenario']
        if scenario=='crash':os._exit(3)
        if scenario=='timeout':time.sleep(2)
        if scenario=='nonce':
            value=receive(endpoint,pid=config['worker_pid'],uid=10001,timeout=3)
            value['nonce']='0'*64
            envelope={'request':value,'report':{}}
            send(endpoint,{'envelope':envelope,'signature':key.sign(canonical(envelope).encode()).hex()})
            return
        def compute(*args,**kwargs):
            assert secret
            return {'schema_version':4,'protocol':'gee_genuine_https','session_id':str(binding.session_id),
                'base':{'input_hash':binding.input_hash,'input_revision':binding.input_revision}}
        signer=key.sign if scenario!='forged' else Ed25519PrivateKey.generate().sign
        try:serve_once(endpoint,binding=binding,worker_pid=config['worker_pid'],worker_uid=10001,
            signer=signer,runtime=SimpleNamespace(compute=compute),request=request,geometry=geometry,as_of=date(2026,1,1),timeout=3)
        except GenuineBoundaryError:pass
    else:
        # Recorder memory cannot be read despite a shared container PID namespace.
        try:Path('/proc/'+str(config['recorder_pid'])+'/mem').open('rb')
        except PermissionError:pass
        else:raise AssertionError('recorder memory readable')
        if config['scenario']=='rpc_bypass':
            send(endpoint,{'action':'response','response_body':'forged','binding':binding.fingerprint()})
            try:receive(endpoint,pid=config['recorder_pid'],uid=10002,timeout=3)
            except GenuineBoundaryError:print('REJECTED');return
            raise AssertionError('recorder authority exposed')
        client=RecorderClient(endpoint,binding=binding,recorder_pid=config['recorder_pid'],
            recorder_uid=10002,recorder_key=bytes.fromhex(config['key']))
        if config['scenario']=='timeout':client.deadline=client.clock()+.2
        try:
            client.compute(request,geometry,as_of=date(2026,1,1));print('ACCEPTED')
            try:client.compute(request,geometry,as_of=date(2026,1,1))
            except GenuineBoundaryError:pass
            else:raise AssertionError('replay accepted')
        except GenuineBoundaryError:print('REJECTED')


if __name__=='__main__' and '--boundary-child' in sys.argv:
    boundary_child()
