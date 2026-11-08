"""Synthetic observations/IPC only; no token issuance or Google network."""
import base64
from dataclasses import replace
from datetime import date
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

if __name__ == '__main__':
    # Fixed packaged paths, not environment-supplied dependency discovery.
    sys.path[:0]=['/sdk',str(Path(__file__).parents[1]),str(Path(__file__).parent)]

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from test_gee_genuine_foundation import packet
from gis_worker.gee_genuine_identity import ExplicitGoogleCredentials, GenuineBoundaryError, CredentialDelivery, PROJECT_ID, PROJECT_NUMBER, PRINCIPAL, PRINCIPAL_ID
from gis_worker.gee_operator_delivery import (OperatorDelivery, MintObservation, MINT_URL, SCOPES,
    observe_real_mint, deliver_credential, receive_credential)
from gis_worker.gee_restricted_network import (PinnedDestinations, PinnedHTTPSConnection,
    isolate_recorder_child, validate_gateway_endpoint)
from gis_worker.gee_recorder_channel import channel_pair, receive, send, RecorderClient, serve_once
from gis_worker.gee_recorder_client import (RecorderSQLClient, ALLOWED_ACTIONS, ISSUER, RPC_PATH,
    READINESS_KEYS)
from gis_worker.gee_genuine_runtime import GenuineBinding, require_selective_egress
from gis_worker.gee_attestation import (H3_STATUS, ProcessMeasurement, measure_process,
    supervisor_net_ns, create_runtime_attestation, verify_runtime_attestation)
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


SQL047 = Path(__file__).parents[1] / 'migrations' / '047_gis_genuine_https.sql'
GATEWAY = ('172.18.0.2', 8000)
TOKEN = b'synthetic-supervisor-token-only'
def WALL():
    return 1050


def make_mock_token(sub, role, exp=None, iss='http://127.0.0.1:55421/auth/v1'):
    claims = {'sub': sub, 'role': role, 'iss': iss, 'exp': exp or int(time.time() + 3600)}
    part = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
    return f'head.{part}.sig'


SUB = '11111111-1111-4111-8111-111111111111'


def bootstrap(**change):
    return {'api_url': 'http://172.18.0.2:8000', 'subject': SUB, 'anon_key': 'test-anon-key',
        'access_token': make_mock_token(SUB, 'gis_gee_https_recorder'),
        'refresh_token': 'test-refresh-token', 'runtime_instance': 'a' * 32,
        'baseline_fingerprint': 'b' * 64} | change


class FakeResponse:
    def __init__(self, data):
        self.data = json.dumps(data).encode()
    def read(self, *args):
        return self.data
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


class FakeOpener:
    def __init__(self, answer):
        self.answer, self.calls = answer, []
    def open(self, req, timeout=5):
        self.calls.append((req.full_url, json.loads(req.data.decode()), dict(req.headers)))
        return FakeResponse(self.answer(req.full_url, self.calls[-1][1]))


SQL_READINESS = {'subject': SUB, 'mode': 'google_https', 'live_enabled': False,
    'genuine_completion_enabled': False}


def test_recorder_client_matches_real_sql047_grants_actions_and_response_shape():
    sql = SQL047.read_text(encoding='utf8')
    actions = re.search(r"IF p_action NOT IN \(([^)]*)\) THEN RAISE EXCEPTION 'GIS_TRANSPORT_ACTION_REJECTED'", sql)
    assert set(re.findall(r"'(\w+)'", actions.group(1))) == set(ALLOWED_ACTIONS)
    # Recorder readiness is an action of the Recorder RPC with an exactly-empty payload.
    assert "IF p_action='readiness' THEN\n  PERFORM gis.keys(p_payload,ARRAY[]::text[]);" in sql
    shape = re.search(r"IF p_action='readiness' THEN.*?RETURN jsonb_build_object\(([^;]*?)\);", sql, re.S).group(1)
    assert set(re.findall(r"'(\w+)',", shape)) - {'google_https'} == READINESS_KEYS | set()
    # The old readiness RPC is Worker-only, so the Recorder must never call it.
    assert 'public.gis_gee_https_readiness() TO gis_gee_https_worker;' in sql
    assert 'gis_gee_https_readiness() TO gis_gee_https_recorder' not in sql
    assert 'GRANT EXECUTE ON FUNCTION public.gis_gee_https_recorder(text,jsonb) TO gis_gee_https_recorder;' in sql
    assert RPC_PATH == '/rest/v1/rpc/gis_gee_https_recorder'
    assert "'http://127.0.0.1:55421/auth/v1'" in sql and ISSUER == 'http://127.0.0.1:55421/auth/v1'
    from gis_worker.worker import ISSUER as WORKER_ISSUER
    assert ISSUER == WORKER_ISSUER


def test_recorder_sql_client_readiness_record_and_seal_use_recorder_rpc_only():
    opener = FakeOpener(lambda url, body: SQL_READINESS if body['p_action'] == 'readiness'
        else {'state': 'recorded'})
    client = RecorderSQLClient(bootstrap(), gateway_endpoint=GATEWAY, opener=opener)
    assert client.readiness() == SQL_READINESS
    assert opener.calls[-1][0] == 'http://172.18.0.2:8000/rest/v1/rpc/gis_gee_https_recorder'
    assert opener.calls[-1][1] == {'p_action': 'readiness', 'p_payload': {}}
    assert client.record('reserve', {'job_id': 'j1'}) == {'state': 'recorded'}
    assert client('seal', {'job_id': 'j1'}) == {'state': 'recorded'}
    assert [c[1]['p_action'] for c in opener.calls] == ['readiness', 'reserve', 'seal']
    assert all('gis_gee_https_readiness' not in c[0] for c in opener.calls)
    for action in ('claim', 'readiness', 'live_x', ''):
        with pytest.raises(GenuineBoundaryError, match='ACTION_REJECTED'):
            client.record(action)
    with pytest.raises(GenuineBoundaryError, match='PAYLOAD_REJECTED'):
        client.record('reserve', ['x'])
    assert 'test-anon-key' not in repr(client) and 'head.' not in repr(client)


@pytest.mark.parametrize('answer', [
    {**SQL_READINESS, 'subject': '22222222-2222-4222-8222-222222222222'},
    {**SQL_READINESS, 'live_enabled': True},
    {**SQL_READINESS, 'genuine_completion_enabled': True},
    {**SQL_READINESS, 'mode': 'other'},
    {**SQL_READINESS, 'worker_role': 'gis_gee_https_recorder'},
    {k: v for k, v in SQL_READINESS.items() if k != 'mode'},
    {'subject': SUB, 'worker_role': 'gis_gee_https_worker', 'protocol': 'gee_genuine_https'},
    [], 'ok', None,
])
def test_readiness_response_must_match_sql047_exactly(answer):
    client = RecorderSQLClient(bootstrap(), gateway_endpoint=GATEWAY, opener=FakeOpener(lambda *a: answer))
    with pytest.raises(GenuineBoundaryError, match='TARGET_REJECTED'):
        client.readiness()


@pytest.mark.parametrize('url', [
    'https://172.18.0.2:8000', 'http://172.evil.com:8000', 'http://172.217.14.202:8000',
    'http://172.32.0.5:8000', 'http://172.18.0.3:8000', 'http://169.254.169.254:8000',
    'http://127.0.0.1:8000', 'http://localhost:8000', 'http://0.0.0.0:8000',
    'http://224.0.0.1:8000', 'http://green-area-gis-t0-gateway:8000', 'http://172.18.0.2:8001',
    'http://172.18.0.2', 'http://user@172.18.0.2:8000', 'http://172.18.0.2:8000/',
    'http://172.18.0.2:8000/x', 'http://172.18.0.2:8000?x=1', 'http://172.018.0.2:8000',
    'http://[::1]:8000', 'https://evil.external.com', 'http://8.8.8.8:8000', '', None, 7,
])
def test_sql_client_destination_is_bound_exactly_to_the_configured_gateway(url):
    with pytest.raises(GenuineBoundaryError, match='TARGET_REJECTED'):
        RecorderSQLClient(bootstrap(api_url=url), gateway_endpoint=GATEWAY)


@pytest.mark.parametrize('endpoint', [
    ('169.254.169.254', 8000), ('127.0.0.1', 8000), ('0.0.0.0', 8000), ('224.0.0.1', 8000),
    ('255.255.255.255', 8000), ('8.8.8.8', 8000), ('172.32.0.1', 8000), ('172.15.255.255', 8000),
    ('100.64.0.1', 8000), ('172.18.0.2', 443), ('172.18.0.2', 8001), ('172.18.0.2', True),
    ('172.18.0.2', '8000'), ('green-area-gis-t0-gateway', 8000), ('172.018.0.2', 8000),
    ('172.18.0.2; accept', 8000), ('::1', 8000), ('::ffff:172.18.0.2', 8000), (b'172.18.0.2', 8000),
    ('172.18.0.2',), ['172.18.0.2', 8000], '172.18.0.2:8000',
])
def test_gateway_endpoint_rejects_public_metadata_loopback_multicast_and_odd_forms(endpoint):
    with pytest.raises(GenuineBoundaryError, match='GATEWAY_REJECTED'):
        validate_gateway_endpoint(endpoint)
    with pytest.raises(GenuineBoundaryError, match='GATEWAY_REJECTED'):
        replace(pins(), gateway_endpoint=endpoint).nft_rules()
    with pytest.raises(GenuineBoundaryError):
        RecorderSQLClient(bootstrap(), gateway_endpoint=endpoint)


@pytest.mark.parametrize('ip', ['10.1.2.3', '192.168.1.5', '172.16.0.1', '172.31.255.254', '172.18.0.2'])
def test_rfc1918_gateway_is_the_only_extra_nft_allow(ip):
    # None is the explicit no-gateway default for the nft policy, never for the SQL client.
    assert pins().gateway_endpoint is None
    with pytest.raises(GenuineBoundaryError, match='GATEWAY_REJECTED'):
        validate_gateway_endpoint(None)
    with pytest.raises(GenuineBoundaryError, match='GATEWAY_REJECTED'):
        RecorderSQLClient(bootstrap(), gateway_endpoint=None)
    base = pins()
    text = replace(base, gateway_endpoint=(ip, 8000)).nft_rules()
    assert f'set approved_sql {{ type ipv4_addr; elements = {{ {ip} }}; }}' in text
    assert 'ip daddr @approved_sql tcp dport 8000 accept' in text
    assert 'ip saddr @approved_sql tcp sport 8000 ct state established accept' in text
    assert 'policy drop' in text and 'udp' not in text and 'dport 53' not in text
    assert text.count('accept') == 4
    assert 'approved_sql' not in base.nft_rules() and base.nft_rules().count('accept') == 2
    assert RecorderSQLClient(bootstrap(api_url=f'http://{ip}:8000'),
        gateway_endpoint=(ip, 8000)).api_url == f'http://{ip}:8000'


@pytest.mark.parametrize('change', [
    {'access_token': make_mock_token(SUB, 'gis_gee_https_worker')},
    {'access_token': make_mock_token('22222222-2222-4222-8222-222222222222', 'gis_gee_https_recorder')},
    {'access_token': make_mock_token(SUB, 'gis_gee_https_recorder', iss='http://evil/auth/v1')},
    {'access_token': 'not-a-jwt'}, {'subject': 'not-a-uuid'}, {'runtime_instance': 'A' * 32},
    {'baseline_fingerprint': 'b' * 63}, {'extra': 1}, {'anon_key': 7}, {'anon_key': ''},
    {'refresh_token': None}, {'access_token': None},
])
def test_sql_client_identity_and_bootstrap_rejections(change):
    with pytest.raises(GenuineBoundaryError):
        RecorderSQLClient(bootstrap(**change), gateway_endpoint=GATEWAY)


def test_sql_client_refresh_redirect_and_error_hygiene():
    expiring = make_mock_token(SUB, 'gis_gee_https_recorder', exp=int(time.time() + 10))
    fresh = make_mock_token(SUB, 'gis_gee_https_recorder')
    opener = FakeOpener(lambda url, body: {'access_token': fresh, 'refresh_token': 'r2'}
        if 'token?grant_type' in url else {'state': 'recorded'})
    client = RecorderSQLClient(bootstrap(access_token=expiring), gateway_endpoint=GATEWAY, opener=opener)
    client.record('reserve', {})
    assert 'grant_type=refresh_token' in opener.calls[0][0] and 'gis_gee_https_recorder' in opener.calls[1][0]
    for bad in ({}, {'access_token': fresh}, {'access_token': 1, 'refresh_token': 'x'},
        {'access_token': make_mock_token(SUB, 'gis_gee_https_worker'), 'refresh_token': 'x'}):
        client = RecorderSQLClient(bootstrap(access_token=expiring), gateway_endpoint=GATEWAY,
            opener=FakeOpener(lambda url, body, bad=bad: bad))
        with pytest.raises(GenuineBoundaryError, match='IDENTITY_REJECTED'):
            client.record('reserve', {})
    class Broken:
        def open(self, req, timeout=5):
            raise TypeError('internal detail test-refresh-token')
    with pytest.raises(GenuineBoundaryError, match='TRANSPORT_FAILED') as caught:
        RecorderSQLClient(bootstrap(), gateway_endpoint=GATEWAY, opener=Broken()).record('reserve', {})
    assert 'test-refresh-token' not in str(caught.value)
    from gis_worker.gee_recorder_client import _NoRedirect
    with pytest.raises(GenuineBoundaryError, match='REDIRECT_REJECTED'):
        _NoRedirect().redirect_request(None, None, 302, 'x', {}, 'http://evil/')


@pytest.mark.skipif(not LINUX, reason='Linux SCM_CREDENTIALS socket IPC')
def test_root_peer_is_rejected_by_default_in_shared_recorder_ipc():
    for kwargs in ({}, {'allow_root': False}, {'allow_root': 1}, {'allow_root': 'yes'}):
        a, b = channel_pair()
        a.send(b'{}')
        with pytest.raises(GenuineBoundaryError, match='CHANNEL_REJECTED'):
            receive(b, pid=os.getpid(), uid=0, timeout=.2, **kwargs)
        a.close()
    a, b = channel_pair()
    with pytest.raises(GenuineBoundaryError, match='CHANNEL_REJECTED'):
        receive(b, pid=os.getpid(), uid=-1, timeout=.2, allow_root=True)


# --- supervisor -> Recorder credential delivery (real kernel credentials, forked peers) ---

def make_delivery(binding, issuer, *, issued_at=1000, expires_at=1800, token=TOKEN):
    d = CredentialDelivery(token, PROJECT_ID, PROJECT_NUMBER, PRINCIPAL, PRINCIPAL_ID,
        issued_at, expires_at, binding.fingerprint(), b'')
    return replace(d, signature=issuer.sign(d.signed_message()))


def credential_payload(d, nonce):
    return {'version': 1, 'action': 'deliver_credential', 'nonce': nonce, 'token': d.token.decode(),
        'project_id': d.project_id, 'project_number': d.project_number, 'principal': d.principal,
        'principal_id': d.principal_id, 'issued_at': d.issued_at, 'expires_at': d.expires_at,
        'binding_sha256': d.binding_sha256, 'signature': d.signature.hex()}


def good_hello(binding, nonce=None):
    return {'version': 1, 'action': 'credential_hello', 'binding': binding.fingerprint(),
        'nonce': nonce or secrets.token_hex(32), 'sent_at': 1050}


def fork_recorder(a, b, fn):
    """Fork the Recorder-side peer. A root supervisor drops it to a real non-root UID."""
    uid = 10002 if os.geteuid() == 0 else os.getuid()
    pid = os.fork()
    if pid == 0:
        code = 70
        try:
            a.close()
            if os.geteuid() == 0:
                os.setgroups([]); os.setgid(uid); os.setuid(uid)
            code = fn(b)
        except GenuineBoundaryError as e:
            # Credential rejections must carry no exception context (no token-bearing chain).
            code = 3 if ((str(e) == 'GEE_CREDENTIAL_DELIVERY_REJECTED' and e.__context__ is None)
                or 'CHANNEL' in str(e)) and TOKEN.decode() not in repr(e) + repr(e.__cause__) else 5
        except BaseException:
            code = 71
        finally:
            os._exit(code)
    b.close()
    return pid, uid


def reap(pid, limit=15):
    end = time.monotonic() + limit
    while time.monotonic() < end:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            return os.waitstatus_to_exitcode(status)
        time.sleep(.02)
    os.kill(pid, 9); os.waitpid(pid, 0)
    raise AssertionError('peer did not finish')


def hello_peer(binding, hello, sup_pid, sup_uid):
    def run(b):
        if isinstance(hello, bytes):
            b.send(hello)
        else:
            send(b, hello)
        try:
            receive(b, pid=sup_pid, uid=sup_uid, timeout=2, allow_root=True)
        except GenuineBoundaryError:
            return 3  # nothing was delivered
        return 0      # a packet (the credential) arrived
    return run


def deliver(binding, delivery, hello, *, pid_delta=0, uid_delta=0):
    a, b = channel_pair()
    pid, uid = fork_recorder(a, b, hello_peer(binding, hello, os.getpid(), os.getuid()))
    try:
        deliver_credential(a, delivery, binding=binding, recorder_pid=pid + pid_delta,
            recorder_uid=uid + uid_delta, timeout=5, wall=WALL)
        error = None
    except GenuineBoundaryError as e:
        error = e
    return error, reap(pid)


@pytest.mark.skipif(not LINUX, reason='Linux SCM_CREDENTIALS socket IPC')
def test_credential_is_sent_only_after_authenticated_recorder_hello():
    *_, binding, _ = packet()
    issuer = Ed25519PrivateKey.generate()
    delivery = make_delivery(binding, issuer)
    error, code = deliver(binding, delivery, good_hello(binding))
    assert error is None and code == 0


@pytest.mark.skipif(not LINUX, reason='Linux SCM_CREDENTIALS socket IPC')
@pytest.mark.parametrize('kind', ['pid', 'uid'])
def test_wrong_recorder_pid_or_uid_never_receives_the_token(kind):
    *_, binding, _ = packet()
    delivery = make_delivery(binding, Ed25519PrivateKey.generate())
    error, code = deliver(binding, delivery, good_hello(binding),
        pid_delta=1 if kind == 'pid' else 0, uid_delta=1 if kind == 'uid' else 0)
    assert str(error) == 'GEE_CREDENTIAL_DELIVERY_REJECTED' and error.__cause__ is None
    assert error.__context__ is None and TOKEN.decode() not in repr(error) and code == 3


@pytest.mark.skipif(not LINUX, reason='Linux SCM_CREDENTIALS socket IPC')
@pytest.mark.parametrize('recorder_uid', [0, -1, True, '1'])
def test_root_or_malformed_recorder_identity_is_rejected_before_any_io(recorder_uid):
    *_, binding, _ = packet()
    delivery = make_delivery(binding, Ed25519PrivateKey.generate())
    a, b = channel_pair()
    with pytest.raises(GenuineBoundaryError, match='DELIVERY_REJECTED'):
        deliver_credential(a, delivery, binding=binding, recorder_pid=os.getpid(), recorder_uid=recorder_uid)
    assert a.fileno() == -1
    b.close()


@pytest.mark.skipif(not LINUX, reason='Linux SCM_CREDENTIALS socket IPC')
@pytest.mark.parametrize('defect', ['stale', 'future', 'binding', 'extra_key', 'missing_key', 'action',
    'version', 'short_nonce', 'upper_nonce', 'bool_sent_at', 'dup_keys', 'non_canonical', 'empty'])
def test_stale_forged_or_malformed_hello_gets_no_credential(defect):
    *_, binding, _ = packet()
    delivery = make_delivery(binding, Ed25519PrivateKey.generate())
    h = good_hello(binding)
    hello = {
        'stale': {**h, 'sent_at': 900}, 'future': {**h, 'sent_at': 1200},
        'binding': {**h, 'binding': 'a' * 64}, 'extra_key': {**h, 'x': 1},
        'missing_key': {k: v for k, v in h.items() if k != 'sent_at'},
        'action': {**h, 'action': 'deliver_credential'}, 'version': {**h, 'version': 2},
        'short_nonce': {**h, 'nonce': 'ab'}, 'upper_nonce': {**h, 'nonce': 'A' * 64},
        'bool_sent_at': {**h, 'sent_at': True},
        'dup_keys': b'{"action":"credential_hello","action":"credential_hello"}',
        'non_canonical': json.dumps(h).encode(), 'empty': b'{}',
    }[defect]
    error, code = deliver(binding, delivery, hello)
    assert str(error) == 'GEE_CREDENTIAL_DELIVERY_REJECTED' and code == 3
    assert TOKEN.decode() not in repr(error) and error.__context__ is None


@pytest.mark.skipif(not LINUX, reason='Linux SCM_CREDENTIALS socket IPC')
@pytest.mark.parametrize('token', [b'synthetic-tok\xc3\xa9n-not-ascii-xx', b'synthetic token with spaces',
    b'short', b'x' * 8193, 'synthetic-supervisor-str-token'],
    ids=['non_ascii', 'space', 'short', 'oversized', 'str'])
def test_unsafe_token_bytes_are_never_sent_even_to_the_authenticated_recorder(token):
    *_, binding, _ = packet()
    delivery = replace(make_delivery(binding, Ed25519PrivateKey.generate()), token=token)
    # The peer is genuine and its hello is valid, so only the token check can stop delivery.
    error, code = deliver(binding, delivery, good_hello(binding))
    assert str(error) == 'GEE_CREDENTIAL_DELIVERY_REJECTED' and error.__context__ is None
    assert code == 3


@pytest.mark.skipif(not LINUX, reason='Linux SCM_CREDENTIALS socket IPC')
def test_replayed_hello_nonce_is_single_use():
    *_, binding, _ = packet()
    delivery = make_delivery(binding, Ed25519PrivateKey.generate())
    hello = good_hello(binding, 'c' * 64)
    error, code = deliver(binding, delivery, hello)
    assert error is None and code == 0
    error, code = deliver(binding, delivery, hello)
    assert str(error) == 'GEE_CREDENTIAL_DELIVERY_REJECTED' and code == 3


def recorder_side(binding, issuer_pub, sup_pid, sup_uid):
    def run(b):
        c = receive_credential(b, supervisor_pid=sup_pid, supervisor_uid=sup_uid, binding=binding,
            issuer_key=issuer_pub, timeout=5, wall=WALL)
        return 0 if c.headers(binding)['Authorization'] == 'Bearer ' + TOKEN.decode() else 5
    return run


def run_recorder_side(binding, issuer, mutate, *, delivery=None, pid_delta=0, uid_delta=0):
    a, b = channel_pair()
    pub = issuer.public_key().public_bytes_raw()
    pid, uid = fork_recorder(a, b, recorder_side(binding, pub, os.getpid() + pid_delta, os.getuid() + uid_delta))
    try:
        hello = receive(a, pid=pid, uid=uid, timeout=5)
        assert set(hello) == {'version', 'action', 'binding', 'nonce', 'sent_at'}
        out = mutate(credential_payload(delivery or make_delivery(binding, issuer), hello['nonce']))
        a.send(out) if isinstance(out, bytes) else send(a, out)
    finally:
        a.close()
    return reap(pid)


@pytest.mark.skipif(not LINUX, reason='Linux SCM_CREDENTIALS socket IPC')
def test_recorder_accepts_exact_supervisor_message_and_holds_token_in_memory_only():
    *_, binding, _ = packet()
    issuer = Ed25519PrivateKey.generate()
    assert run_recorder_side(binding, issuer, lambda p: p) == 0


@pytest.mark.skipif(not LINUX, reason='Linux SCM_CREDENTIALS socket IPC')
@pytest.mark.parametrize('defect', ['extra_key', 'missing_key', 'nonce_replay', 'binding', 'principal',
    'project', 'project_number', 'principal_id', 'token_swapped', 'token_short', 'expired', 'future_issued',
    'version', 'action', 'sig_short', 'token_non_ascii', 'token_space', 'dup_keys', 'non_canonical', 'empty'])
def test_recorder_rejects_inexact_unbound_or_forged_credential_messages(defect):
    *_, binding, _ = packet()
    issuer = Ed25519PrivateKey.generate()
    mutations = {
        'extra_key': lambda p: {**p, 'extra': 1},
        'missing_key': lambda p: {k: v for k, v in p.items() if k != 'signature'},
        'nonce_replay': lambda p: {**p, 'nonce': 'd' * 64},
        'binding': lambda p: {**p, 'binding_sha256': 'e' * 64},
        'principal': lambda p: {**p, 'principal': 'x@y.iam.gserviceaccount.com'},
        'project': lambda p: {**p, 'project_id': 'innate-beacon-483307-v1'},
        'project_number': lambda p: {**p, 'project_number': '1'},
        'principal_id': lambda p: {**p, 'principal_id': '1'},
        'token_swapped': lambda p: {**p, 'token': 'other-token-0123456789abcdef'},
        'token_short': lambda p: {**p, 'token': 'short'},
        'expired': lambda p: {**p, 'expires_at': 1049},
        'future_issued': lambda p: {**p, 'issued_at': 2000},
        'version': lambda p: {**p, 'version': 2}, 'action': lambda p: {**p, 'action': 'compute'},
        'sig_short': lambda p: {**p, 'signature': 'ab'},
        'token_non_ascii': lambda p: {**p, 'token': 'synthetic-tok\u00e9n-not-ascii-xx'},
        'token_space': lambda p: {**p, 'token': 'synthetic token with spaces'},
        'dup_keys': lambda p: b'{"action":"deliver_credential","action":"deliver_credential"}',
        'non_canonical': lambda p: json.dumps(p).encode(), 'empty': lambda p: b'{}',
    }
    assert run_recorder_side(binding, issuer, mutations[defect]) == 3


@pytest.mark.skipif(not LINUX, reason='Linux SCM_CREDENTIALS socket IPC')
def test_recorder_rejects_forged_broker_signature_and_stale_issue_time():
    *_, binding, _ = packet()
    issuer = Ed25519PrivateKey.generate()
    forged = make_delivery(binding, Ed25519PrivateKey.generate())
    assert run_recorder_side(binding, issuer, lambda p: p, delivery=forged) == 3
    stale = make_delivery(binding, issuer, issued_at=700)
    assert run_recorder_side(binding, issuer, lambda p: p, delivery=stale) == 3


@pytest.mark.skipif(not LINUX, reason='Linux SCM_CREDENTIALS socket IPC')
@pytest.mark.parametrize('kind', ['pid', 'uid'])
def test_recorder_rejects_a_valid_message_from_the_wrong_sender_identity(kind):
    *_, binding, _ = packet()
    code = run_recorder_side(binding, Ed25519PrivateKey.generate(), lambda p: p,
        pid_delta=1 if kind == 'pid' else 0, uid_delta=1 if kind == 'uid' else 0)
    assert code == 3


# --- RuntimeAttestation: kernel-measured process state; H3 stays NOT VERIFIED ---

def measurement(pid, uid, net, *, nnp=True, seccomp=2):
    return ProcessMeasurement(pid=pid, uid=uid, no_new_privs=nnp, seccomp_mode=seccomp, net_ns=f'net:[{net}]')


class FakeKernel:
    def __init__(self):
        self.state = {20001: measurement(20001, 10001, 111), 20002: measurement(20002, 10002, 222, seccomp=0)}
        self.supervisor = 'net:[333]'
    def measure(self, pid):
        if pid not in self.state:
            raise GenuineBoundaryError('GEE_RUNTIME_MEASUREMENT_REJECTED')
        return self.state[pid]
    def ns(self):
        return self.supervisor


def attest(binding, kernel, key, **change):
    args = dict(runtime_id=binding.runtime_id, image_id='sha256:' + 'a' * 64, network_policy_sha256='b' * 64,
        worker_pid=20001, recorder_pid=20002, supervisor_signer=key.sign, measure=kernel.measure,
        supervisor_ns=kernel.ns, wall=lambda: 1000)
    return create_runtime_attestation(**(args | change))


def verify(binding, kernel, key, attestation, **change):
    args = dict(supervisor_key=key.public_key().public_bytes_raw(), expected_image='sha256:' + 'a' * 64,
        expected_policy_sha256='b' * 64, binding=binding, worker_peer=(20001, 10001),
        recorder_peer=(20002, 10002), measure=kernel.measure, supervisor_ns=kernel.ns, wall=lambda: 1050)
    return verify_runtime_attestation(attestation, **(args | change))


def test_runtime_attestation_is_measured_and_still_labelled_not_verified():
    *_, binding, _ = packet()
    kernel, key = FakeKernel(), Ed25519PrivateKey.generate()
    a = attest(binding, kernel, key)
    assert verify(binding, kernel, key, a) is True
    assert H3_STATUS == 'NOT_VERIFIED'
    assert (a.image_identity, a.network_enforcement) == ('supervisor_declared', 'not_measured')
    assert 'isolation_proven' not in a.message().decode() and not hasattr(a, 'isolation_proven')
    # Self-reported isolation or identity values are no longer accepted at all.
    for declared in ({'isolation_proven': True}, {'worker_uid': 10001}, {'recorder_uid': 10002}):
        with pytest.raises(TypeError):
            attest(binding, kernel, key, **declared)
    # A verified attestation still cannot open the closed Live Gate.
    with pytest.raises(GenuineBoundaryError, match='SELECTIVE_EGRESS_NOT_VERIFIED'):
        require_selective_egress(a, binding)


@pytest.mark.parametrize('change', [
    {'worker': measurement(20001, 10001, 111, seccomp=0)},
    {'worker': measurement(20001, 10001, 111, seccomp=1)},
    {'worker': measurement(20001, 10001, 111, nnp=False)},
    {'recorder': measurement(20002, 10001, 222, seccomp=0)},
    {'recorder': measurement(20002, 10002, 111, seccomp=0)},
    {'recorder': measurement(20002, 10002, 333, seccomp=0)},
])
def test_create_rejects_measured_state_that_violates_isolation(change):
    *_, binding, _ = packet()
    kernel, key = FakeKernel(), Ed25519PrivateKey.generate()
    kernel.state[20001] = change.get('worker', kernel.state[20001])
    kernel.state[20002] = change.get('recorder', kernel.state[20002])
    with pytest.raises(GenuineBoundaryError, match='ISOLATION_REJECTED'):
        attest(binding, kernel, key)


def test_create_rejects_same_pid_unmeasurable_process_and_bad_image():
    *_, binding, _ = packet()
    kernel, key = FakeKernel(), Ed25519PrivateKey.generate()
    with pytest.raises(GenuineBoundaryError, match='ISOLATION_REJECTED'):
        attest(binding, kernel, key, recorder_pid=20001)
    with pytest.raises(GenuineBoundaryError, match='MEASUREMENT_REJECTED'):
        attest(binding, kernel, key, recorder_pid=99999)
    for image in ('latest', 'sha256:short', 'sha256:' + 'A' * 64):
        with pytest.raises(GenuineBoundaryError, match='CONFIGURATION_REJECTED'):
            attest(binding, kernel, key, image_id=image)


def test_verify_rejects_forged_tampered_stale_unbound_and_drifted_attestations():
    *_, binding, _ = packet()
    kernel, key = FakeKernel(), Ed25519PrivateKey.generate()
    a = attest(binding, kernel, key)
    with pytest.raises(GenuineBoundaryError, match='SIGNATURE_REJECTED'):
        verify(binding, kernel, Ed25519PrivateKey.generate(), a)
    for tampered in (a.model_copy(update={'image_id': 'sha256:' + '0' * 64}),
        a.model_copy(update={'network_policy_sha256': '0' * 64}),
        a.model_copy(update={'attested_at': 1040}),
        a.model_copy(update={'worker': measurement(20001, 10001, 111, seccomp=0)})):
        with pytest.raises(GenuineBoundaryError, match='SIGNATURE_REJECTED'):
            verify(binding, kernel, key, tampered)
    rejected = [
        dict(expected_image='sha256:' + '0' * 64), dict(expected_policy_sha256='0' * 64),
        dict(worker_peer=(20001, 10003)), dict(worker_peer=(20009, 10001)),
        dict(recorder_peer=(20002, 10009)), dict(recorder_peer=(20009, 10002)),
        dict(wall=lambda: 1301), dict(wall=lambda: 999), dict(supervisor_key=b'x' * 31),
        dict(worker_peer=[20001, 10001]),
    ]
    for change in rejected:
        with pytest.raises(GenuineBoundaryError, match='ATTESTATION_REJECTED'):
            verify(binding, kernel, key, a, **change)
    with pytest.raises(GenuineBoundaryError, match='ATTESTATION_REJECTED'):
        verify(binding.model_copy(update={'runtime_id': uuid4()}), kernel, key, a)
    with pytest.raises(GenuineBoundaryError, match='ATTESTATION_REJECTED'):
        verify(binding, kernel, key, 'attestation')
    # The processes changed after attestation: re-measurement must catch it.
    for pid, drifted in ((20001, measurement(20001, 10001, 111, seccomp=0)),
        (20001, measurement(20001, 10005, 111)), (20002, measurement(20002, 10002, 333, seccomp=0)),
        (20002, measurement(20002, 10002, 444, seccomp=0))):
        changed = FakeKernel(); changed.state[pid] = drifted
        with pytest.raises(GenuineBoundaryError, match='REJECTED'):
            verify(binding, changed, key, a)
    gone = FakeKernel(); del gone.state[20002]
    with pytest.raises(GenuineBoundaryError, match='MEASUREMENT_REJECTED'):
        verify(binding, gone, key, a)
    moved = FakeKernel(); moved.supervisor = 'net:[444]'
    with pytest.raises(GenuineBoundaryError, match='ATTESTATION_REJECTED'):
        verify(binding, moved, key, a)


@pytest.mark.skipif(not LINUX, reason='Linux /proc')
def test_measure_process_parses_kernel_proc_and_rejects_ambiguous_state(tmp_path):
    def proc(pid, uid='10001\t10001\t10001\t10001', seccomp='2', nnp='1', net='net:[4026531993]'):
        d = tmp_path / str(pid); (d / 'ns').mkdir(parents=True)
        (d / 'status').write_text(f'Name:\tx\nUid:\t{uid}\nNoNewPrivs:\t{nnp}\nSeccomp:\t{seccomp}\n')
        os.symlink(net, d / 'ns' / 'net')
    proc(5)
    m = measure_process(5, proc=str(tmp_path))
    assert (m.pid, m.uid, m.no_new_privs, m.seccomp_mode, m.net_ns) == (5, 10001, True, 2, 'net:[4026531993]')
    proc(6, nnp='0', seccomp='0'); assert measure_process(6, proc=str(tmp_path)).no_new_privs is False
    for n, kw in enumerate(({'uid': '10001\t10002\t10001\t10001'}, {'uid': '10001\t10001\t0\t10001'},
        {'uid': '0\t0\t0\t0'}, {'uid': '10001\t10001'}, {'seccomp': 'x'}, {'seccomp': '3'}, {'net': 'mnt:[1]'})):
        proc(10 + n, **kw)
        with pytest.raises(GenuineBoundaryError, match='MEASUREMENT_REJECTED'):
            measure_process(10 + n, proc=str(tmp_path))
    for bad in (0, -1, 999, True, '5', None):
        with pytest.raises(GenuineBoundaryError, match='MEASUREMENT_REJECTED'):
            measure_process(bad, proc=str(tmp_path))
    assert re.fullmatch(r'net:\[[0-9]+\]', supervisor_net_ns())


@pytest.mark.skipif(not LINUX or os.geteuid() == 0, reason='Linux non-root process self-measurement')
def test_measure_process_reads_the_real_kernel_state_of_this_process():
    m = measure_process(os.getpid())
    assert (m.pid, m.uid) == (os.getpid(), os.getuid())


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
