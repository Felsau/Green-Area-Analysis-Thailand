"""A6 egress proof operator (Windows host, Docker Desktop). Never a Live launcher.

Builds an offline image FROM the pinned mock base (no RUN/pull/network), then runs a
throwaway topology and records supervisor-side evidence:

  gis-a6-egress-int-<run>  Docker ``internal`` network: relay + recorder-probe
  gis-a6-egress-out-<run>  ordinary bridge, relay only, ONLY with --forward-tls
  green-area-gis-t0-internal (existing, if the T0 core is running): recorder-probe
                           and worker-probe join it to reach the SQL gateway

Default mode is dry-run: the relay never opens an upstream socket, so nothing is
sent to Google. ``--forward-tls`` performs one TLS handshake per pinned host
through the relay (no HTTP request, no credential) and must be separately approved.

Only resources labelled ``gis.a6.egress.run=<run>`` are created and removed here.
No host firewall, existing container, volume, database or credential is touched.
Evidence goes outside the repository under ROOT/a6-egress/run-<run>/.
"""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[2]
BASE = 'sha256:7557955c9e2c8611ea1396ddef6d8629c2ee1e7f193e85f0c65bcf5db9566674'
BASE_TAG = 'gis-gee-mock:20261104-a63'
DOCKER = Path('C:/Users/chaya/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe')
ROOT = Path('C:/Users/chaya/.codex/visualizations/2026/10/04/01a107d9-ff44-7731-8bc3-91814ffd8d51')
OUTPUT = ROOT / 'a6-egress'
T0_NETWORK = 'green-area-gis-t0-internal'
T0_GATEWAY = 'green-area-gis-t0-gateway'
LABEL = 'gis.a6.egress.run'
ENTRYPOINT = ['/usr/local/bin/python3', '-I', '-B', '/app/egress_entry.py']
HOSTS = ('earthengine.googleapis.com', 'storage.googleapis.com')
LIMITS = {'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
    'SecurityOpt': ['no-new-privileges:true'], 'PidsLimit': 32, 'Memory': 268435456,
    'MemorySwap': 268435456, 'NanoCpus': 500000000, 'PublishAllPorts': False}
WORKER_FILES = ('__init__.py', 'gee_egress_relay.py', 'gee_egress_probe.py')


def docker(args, *, timeout=90, input=None):
    result = subprocess.run([str(DOCKER), '--host', 'npipe:////./pipe/dockerDesktopLinuxEngine',
        '--config', str(ROOT / 't0-local-supabase-20261027-v2/docker-config'), *args],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=timeout, input=input)
    if result.returncode:
        raise RuntimeError('EGRESS_DOCKER_FAILED: ' + result.stderr[-2000:])
    return result.stdout


def docker_popen(args):
    return subprocess.Popen([str(DOCKER), '--host', 'npipe:////./pipe/dockerDesktopLinuxEngine',
        '--config', str(ROOT / 't0-local-supabase-20261027-v2/docker-config'), *args],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding='utf-8', errors='replace')


def sources():
    paths = [REPO / 'green-area-backend/gis_worker' / f for f in WORKER_FILES]
    here = Path(__file__)
    paths += [here, here.with_name('gee_egress.Dockerfile'), here.with_name('gee_egress_entry.py')]
    return {p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def tree_hash(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def build():
    if json.loads(docker(['image', 'inspect', BASE_TAG]))[0]['Id'] != BASE:
        raise RuntimeError('EGRESS_BASE_DRIFT')
    base = json.loads(docker(['image', 'inspect', BASE]))[0]
    if base['Os'] != 'linux' or base['Architecture'] != 'amd64':
        raise RuntimeError('EGRESS_PLATFORM')
    OUTPUT.mkdir(exist_ok=True)
    manifest = sources()
    tree = tree_hash(manifest)
    tag = 'gis-gee-egress:offline-' + tree[:12]
    context = OUTPUT / ('context-' + tree[:12])
    if not context.exists():
        context.mkdir()
        (context / 'gis_worker').mkdir()
        for name in WORKER_FILES:
            shutil.copyfile(REPO / 'green-area-backend/gis_worker' / name, context / 'gis_worker' / name)
        shutil.copyfile(Path(__file__).with_name('gee_egress.Dockerfile'), context / 'Dockerfile')
        shutil.copyfile(Path(__file__).with_name('gee_egress_entry.py'), context / 'egress_entry.py')
        (context / 'source-manifest.json').write_text(json.dumps(manifest, indent=2))
    docker(['build', '--pull=false', '--network=none', '--build-arg', 'SOURCE_TREE_SHA256=' + tree,
        '-t', tag, str(context)], timeout=180)
    image = json.loads(docker(['image', 'inspect', tag]))[0]
    if (image['RootFS']['Layers'][:len(base['RootFS']['Layers'])] != base['RootFS']['Layers']
        or image['Config']['User'] != '65534:65534'
        or image['Config']['Entrypoint'] != ENTRYPOINT
        or image['Config']['Labels'].get('gis.a6.egress.source') != tree):
        raise RuntimeError('EGRESS_IMAGE_DRIFT')
    lock = {'mode': 'offline-egress-proof', 'live_enabled': False, 'image_id': image['Id'],
        'tag': tag, 'source': manifest, 'source_tree_sha256': tree, 'base_image': BASE}
    (OUTPUT / 'image-lock.json').write_text(json.dumps(lock, indent=2))
    return {'image_id': image['Id'], 'tag': tag, 'source_tree_sha256': tree, 'live_enabled': False}


def resolve_pins(resolver=socket.getaddrinfo):
    """Supervisor DNS snapshot (host resolver, NOT authenticated DNS)."""
    pins = {}
    for host in HOSTS:
        ips = sorted({info[4][0] for info in resolver(host, 443, socket.AF_INET, socket.SOCK_STREAM)})
        ips = [ip for ip in ips if ipaddress.IPv4Address(ip).is_global][:8]
        if not ips:
            raise RuntimeError('EGRESS_PIN_RESOLUTION_FAILED')
        pins[host] = ips
    return pins


def verify_container(info, *, image_id, role, networks):
    """Exact supervisor check of what Docker actually created. Returns measurements."""
    c, h = info.get('Config', {}), info.get('HostConfig', {})
    attached = info.get('NetworkSettings', {}).get('Networks') or {}
    problems = []
    if info.get('Image') != image_id:
        problems.append('image')
    if c.get('User') != '65534:65534' or c.get('Entrypoint') != ENTRYPOINT or c.get('Cmd') != [role]:
        problems.append('command')
    if c.get('Env') not in (None, []) and any(not e.startswith(('PATH=', 'LANG=', 'GPG_KEY=', 'PYTHON'))
        for e in c.get('Env')):
        problems.append('environment')
    for key, value in LIMITS.items():
        if h.get(key) != value:
            problems.append(key)
    if h.get('CapAdd') or h.get('PortBindings') or h.get('Devices') or info.get('Mounts'):
        problems.append('privileges_or_mounts')
    if h.get('PidMode') not in ('', None) or h.get('IpcMode') not in ('private', 'shareable', None):
        problems.append('namespaces')
    if set(attached) != set(networks):
        problems.append('networks')
    measured = {'image_id': info.get('Image'), 'user': c.get('User'), 'role': role,
        'networks': {n: attached.get(n, {}).get('IPAddress') for n in sorted(attached)},
        'read_only': h.get('ReadonlyRootfs'), 'cap_drop': h.get('CapDrop'), 'cap_add': h.get('CapAdd'),
        'privileged': h.get('Privileged'), 'security_opt': h.get('SecurityOpt'),
        'published_ports': h.get('PortBindings') or {}}
    return measured, problems


def verify_network(info, *, name, internal):
    problems = []
    if info.get('Name') != name or info.get('Internal') is not internal or info.get('Driver') != 'bridge':
        problems.append('network_' + name)
    measured = {'name': info.get('Name'), 'internal': info.get('Internal'), 'driver': info.get('Driver'),
        'members': sorted(v.get('Name', '') for v in (info.get('Containers') or {}).values())}
    return measured, problems


def evaluate(*, probes, measured_problems, relay_events, pins, forward):
    """Overall verdict from probe results, supervisor measurements and relay log."""
    failed = list(measured_problems)
    for name, result in probes.items():
        if not isinstance(result, dict) or result.get('verdict') != 'PASS':
            failed.append('probe_' + name)
    for event in relay_events:
        if event.get('event') == 'connection':
            if event.get('upstream') not in pins.get(event.get('host'), []):
                failed.append('relay_upstream_outside_pins')
            if not forward and event.get('outcome') != 'dry_run':
                failed.append('relay_dialed_in_dry_run')
    if not any(e.get('event') == 'listening' for e in relay_events):
        failed.append('relay_not_listening')
    return {'verdict': 'FAIL' if failed else 'PASS', 'failed': sorted(set(failed))}


def _inspect(kind, name):
    return json.loads(docker([kind, 'inspect', name]))[0]


def _t0_gateway():
    try:
        network = _inspect('network', T0_NETWORK)
        gateway = _inspect('container', T0_GATEWAY)
    except RuntimeError:
        return None, None
    if not gateway.get('State', {}).get('Running'):
        return network, None
    return network, gateway['NetworkSettings']['Networks'].get(T0_NETWORK, {}).get('IPAddress') or None


def probe(*, forward=False):
    lock = json.loads((OUTPUT / 'image-lock.json').read_text())
    if lock['source'] != sources() or lock['mode'] != 'offline-egress-proof' or lock['live_enabled'] is not False:
        raise RuntimeError('EGRESS_SOURCE_LOCK_DRIFT')
    image = lock['image_id']
    run = secrets.token_hex(6)
    out = OUTPUT / ('run-' + run)
    out.mkdir(parents=True)
    pins = resolve_pins()
    containers, networks, relay_lines = [], [], []
    measured, problems, probes = {}, [], {}
    relay_proc = None
    t0_network, gateway_ip = _t0_gateway()
    try:
        internal = 'gis-a6-egress-int-' + run
        docker(['network', 'create', '--internal', '--driver', 'bridge', '--label', f'{LABEL}={run}', internal])
        networks.append(internal)
        if forward:
            egress = 'gis-a6-egress-out-' + run
            docker(['network', 'create', '--driver', 'bridge', '--label', f'{LABEL}={run}', egress])
            networks.append(egress)

        def create(role, network):
            name = f'gis-a6-egress-{role}-{run}'
            cid = docker(['create', '--name', name, '--label', f'{LABEL}={run}', '--network', network,
                '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
                '--user=65534:65534', '--pids-limit=32', '--memory=256m', '--memory-swap=256m',
                '--cpus=0.5', '--ulimit', 'core=0:0', '--log-driver', 'none', '-i', image, role]).strip()
            containers.append(cid)
            return cid

        relay = create('relay', internal)
        if forward:
            docker(['network', 'connect', networks[1], relay])
        recorder = create('probe-recorder', internal)
        if gateway_ip:
            docker(['network', 'connect', T0_NETWORK, recorder])
        worker = create('probe-worker', T0_NETWORK if gateway_ip else 'none')

        expected = {relay: ('relay', networks[:2] if forward else [internal]),
            recorder: ('probe-recorder', [internal] + ([T0_NETWORK] if gateway_ip else [])),
            worker: ('probe-worker', [T0_NETWORK] if gateway_ip else ['none'])}
        for cid, (role, nets) in expected.items():
            measured[role], p = verify_container(_inspect('container', cid), image_id=image, role=role, networks=nets)
            problems += [f'{role}:{x}' for x in p]
        for name, is_internal in [(internal, True)] + ([(networks[1], False)] if forward else []) \
                + ([(T0_NETWORK, True)] if gateway_ip else []):
            measured['network:' + name], p = verify_network(_inspect('network', name), name=name, internal=is_internal)
            problems += p
        # Docker assigns IPs only when a container starts, so start the relay first
        # (it blocks reading its config line) and read its address from the engine.
        relay_proc = docker_popen(['start', '--attach', '--interactive', relay])
        relay_ip, end = None, time.monotonic() + 30
        while time.monotonic() < end:
            info = _inspect('container', relay)
            relay_ip = info['NetworkSettings']['Networks'].get(internal, {}).get('IPAddress') or None
            if info['State'].get('Running') and relay_ip:
                break
            if info['State'].get('Status') == 'exited':
                break
            time.sleep(.5)
        if not relay_ip:
            raise RuntimeError('EGRESS_RELAY_NO_ADDRESS: ' + (relay_proc.stderr.read(2000) if relay_proc.poll() is not None else ''))
        measured['relay'], p = verify_container(info, image_id=image, role='relay', networks=expected[relay][1])
        problems += [f'relay(started):{x}' for x in p]

        relay_config = {'version': 1, 'mode': 'forward' if forward else 'dry_run', 'bind_ip': relay_ip,
            'expires_at': int(time.time()) + 300, 'routes': pins}
        relay_proc.stdin.write(json.dumps(relay_config) + '\n')
        relay_proc.stdin.flush()
        ready = threading.Event()

        def pump():
            for line in relay_proc.stdout:
                relay_lines.append(line.strip())
                if '"listening"' in line:
                    ready.set()
        threading.Thread(target=pump, daemon=True).start()
        if not ready.wait(30):
            err = relay_proc.stderr.read(2000) if relay_proc.poll() is not None else 'still running'
            raise RuntimeError('EGRESS_RELAY_NOT_READY: ' + err)

        for cid, role in ((recorder, 'probe-recorder'), (worker, 'probe-worker')):
            config = {'version': 1, 'role': role, 'relay_ip': relay_ip, 'gateway_ip': gateway_ip,
                'pins': pins, 'tls_handshake': forward and role == 'probe-recorder'}
            raw = docker(['start', '--attach', '--interactive', cid], input=json.dumps(config) + '\n', timeout=180)
            try:
                probes[role] = json.loads(raw.strip().splitlines()[-1])
            except (ValueError, IndexError):
                probes[role] = {'verdict': 'NO_OUTPUT'}
    finally:
        for cid in containers:
            try:
                docker(['rm', '--force', cid])
            except RuntimeError:
                pass
        if relay_proc is not None:
            try:
                relay_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                relay_proc.kill()
        for name in reversed(networks):
            try:
                docker(['network', 'rm', name])
            except RuntimeError:
                pass
    relay_events = []
    for line in relay_lines:
        try:
            relay_events.append(json.loads(line))
        except ValueError:
            pass
    result = evaluate(probes=probes, measured_problems=problems, relay_events=relay_events,
        pins=pins, forward=forward)
    topology = {k: v for k, v in measured.items()}
    evidence = {'schema_version': 1, 'run': run, 'mode': 'forward_tls' if forward else 'dry_run',
        'live_enabled': False, 'credentials_used': False, 'google_contacted': bool(forward),
        'image': {'id': image, 'tag': lock['tag'], 'source_tree_sha256': lock['source_tree_sha256'],
            'measured_by': 'supervisor docker inspect'},
        't0_gateway_present': bool(gateway_ip), 'pins': pins, 'pins_source': 'host resolver (unauthenticated)',
        'measured': topology, 'measured_topology_sha256': hashlib.sha256(
            json.dumps(topology, sort_keys=True).encode()).hexdigest(),
        'probes': probes, 'relay_events': relay_events, 'h3_status': 'NOT_VERIFIED', **result}
    (out / 'evidence.json').write_text(json.dumps(evidence, indent=2, sort_keys=True))
    return {'run': run, 'evidence': str(out / 'evidence.json'), 'verdict': result['verdict'],
        'failed': result['failed'], 'mode': evidence['mode'], 't0_gateway_present': bool(gateway_ip)}


def cleanup():
    """Remove only leftovers that carry this launcher's label."""
    removed = []
    for cid in docker(['ps', '-aq', '--filter', 'label=' + LABEL]).split():
        docker(['rm', '--force', cid])
        removed.append(cid[:12])
    for nid in docker(['network', 'ls', '-q', '--filter', 'label=' + LABEL]).split():
        docker(['network', 'rm', nid])
        removed.append(nid[:12])
    return {'removed': removed}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'probe', 'cleanup'])
    parser.add_argument('--forward-tls', action='store_true',
        help='APPROVAL REQUIRED: one TLS handshake per pinned Google host via the relay; no request/credential')
    args = parser.parse_args()
    if args.action == 'build':
        print(json.dumps(build(), indent=2))
    elif args.action == 'probe':
        print(json.dumps(probe(forward=args.forward_tls), indent=2))
    else:
        print(json.dumps(cleanup(), indent=2))
    sys.exit(0)
