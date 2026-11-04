"""A6.3 real loopback HTTP/Auth/Queue/Linux daemon E2E; no live GEE."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
from uuid import uuid4

HERE = Path(__file__).resolve().parent
s = importlib.util.spec_from_file_location('a63_existing_local', HERE / 'gee_mock_local.py')
p = importlib.util.module_from_spec(s)
sys.modules[s.name] = p
s.loader.exec_module(p)
sys.path.insert(0, str(p.REPO / 'green-area-backend'))
from gis_app import create_app
from gis_worker.gee_contracts import ComputeOutput
from gis_worker.gee_mock_fixtures import SPECS, case_for
from gis_worker.gee_mock_queue import report


class Local(p.GeeMockLocal):
    def __init__(self, root):
        super().__init__(root)
        self.output = self.db.runtime.root / 'a6-3-gee-e2e'
        self.output.mkdir(exist_ok=True)
        self.seed = uuid4().hex[:12]
        self.proof_a62()  # Immutable043 plus exact Local identity before any writes.
        self.legacy = self.output / ('legacy-' + self.seed)
        self.legacy.mkdir()
        for target, source in [('gee_utils.py', 'gee_utils.py'), ('ndvi_compute.py', 'routers/ndvi/compute.py'), ('lst.py', 'routers/lst.py')]:
            (self.legacy / target).write_bytes((p.REPO / 'green-area-backend' / source).read_bytes())
        self.cases = {key: case_for(key, self.seed, legacy_root=self.legacy) for key in SPECS}
        self.catalog = {}

    def register(self):
        quote = p.m.t2.t1.literal
        for key, value in self.cases.items():
            self.catalog[key] = self.sql('INSERT INTO gis.gee_mock_cases(value) VALUES(' + quote(json.dumps(value)) + '::jsonb) RETURNING to_jsonb(id)')

    def user(self, role='authenticated'):
        self.attest()
        anon, service = self.local_keys()
        operator = self.client(service)
        password, email = secrets.token_urlsafe(30), 'a63-' + uuid4().hex + '@example.invalid'
        created = operator.auth.admin.create_user({'email': email, 'password': password, 'email_confirm': True, 'role': role})
        client = self.client(anon)
        session = client.auth.sign_in_with_password({'email': email, 'password': password}).session
        if session is None:
            raise RuntimeError('A63_LOCAL_AUTH_REQUIRED')
        # repr=False; no keys/tokens/passwords are printed or persisted.
        return p.m.identity_module.WorkerIdentity(str(created.user.id), anon, session.access_token, session.refresh_token, client)


class MockContainer(p.m.ContainerWorker):
    """Reuse established signal/event/cleanup helpers and the same Linux daemon."""
    def __init__(self, local, identity):
        self.local, self.identity, self.events, self.errors = local, identity, [], []
        run = uuid4().hex
        name = 'gis-gee-mock-worker-' + run[:12]
        local.attest()
        image = p.m.t2.t1.runtime_module.GEE_MOCK_WORKER_IMAGE
        args = ['create', '-i', '--init', '--name', name, '--entrypoint', '', '--network', 'green-area-gis-t0-internal',
            '--memory=1g', '--memory-swap=1g', '--cpus=1', '--pids-limit=64', '--read-only', '--cap-drop=ALL',
            '--security-opt=no-new-privileges:true', '--user=65534:65534', '--tmpfs=/tmp:rw,nosuid,noexec,size=32m,mode=1777',
            '--mount', 'type=bind,src=' + str(p.REPO / 'green-area-backend/gis_worker') + ',dst=/app/gis_worker,readonly']
        for target, source in [('gee_utils.py', 'gee_utils.py'), ('ndvi_compute.py', 'routers/ndvi/compute.py'), ('lst.py', 'routers/lst.py')]:
            args += ['--mount', 'type=bind,src=' + str(p.REPO / 'green-area-backend' / source) + ',dst=/app/legacy/' + target + ',readonly']
        args += ['--workdir=/app/gis_worker', '--label', 'gis.a6.3.scope=gee-mock-worker', '--label', 'gis.a6.3.instance=' + local.db.instance,
                 '--label', 'gis.a6.3.run=' + run, '--label', 'com.docker.compose.project=green-area-gis-t0',
                 image, 'python3', '-I', '-B', '/app/gis_worker/gee_mock_worker.py']
        self.cid = local.db.runtime.docker(args).strip()
        self.policy = {'name': name, 'run_id': run, 'mock_adapter': True}
        local.db.runtime.verify_worker(self.cid, self.policy)
        local.approved[self.cid] = self.policy
        try:
            self._attach()
        except BaseException:
            # Only this constructor's exact, policy-verified container is removable.
            local.db.runtime.verify_worker(self.cid, self.policy)
            state = json.loads(local.db.runtime.docker(['inspect', '--format', '{{json .State}}', self.cid]))
            if state.get('Running'):
                local.db.runtime.docker(['kill', '--signal', 'SIGKILL', self.cid])
            proc = getattr(self, 'proc', None)
            if proc is not None:
                proc.wait(timeout=10)
            local.db.runtime.verify_worker(self.cid, self.policy)
            local.db.runtime.docker(['rm', self.cid])
            del local.approved[self.cid]
            local.attest()
            raise

    def _attach(self):
        local, identity = self.local, self.identity
        local.attest()
        self.proc = subprocess.Popen(local.db.runtime.base + ['start', '-a', '-i', self.cid], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=local.db.runtime.root, env=local.db.runtime.env)
        bootstrap = {'api_url': 'http://green-area-gis-t0-gateway:8000', 'subject': identity.subject,
            'anon_key': identity.anon_key, 'access_token': identity.access_token, 'refresh_token': identity.refresh_token,
            'runtime_instance': local.db.instance, 'baseline_fingerprint': p.m.t2.t1.legacy_fingerprint()}
        self.proc.stdin.write((json.dumps(bootstrap) + '\n').encode())
        self.proc.stdin.close()
        def collect():
            for raw in iter(lambda: self.proc.stdout.readline(4097), b''):
                try:
                    value = json.loads(raw)
                    if len(raw) > 4096 or set(value) - {'event', 'job_id', 'state', 'error_code'}:
                        raise ValueError()
                    if len(self.events) < 512:
                        self.events.append(value)
                except Exception:
                    if len(self.errors) < 512:
                        self.errors.append('WORKER_EVENT_REJECTED')
        self.reader = threading.Thread(target=collect, daemon=True)
        self.reader.start()


def run(local):
    import httpx
    import uvicorn
    source_paths = [p.REPO / path for path in (
        'dev/gis_local/gee_mock_e2e.py', 'dev/gis_local/manage.py', 'dev/gis_local/gee-mock-image.lock.json',
        'green-area-backend/gis_app.py', 'green-area-backend/gis_runtime.py', 'green-area-backend/gis_gee_mock.py',
        'green-area-backend/routers/gee_mock.py', 'green-area-backend/gis_worker/worker.py',
        'green-area-backend/gis_worker/gee_mock_worker.py', 'green-area-backend/gis_worker/gee_mock_child.py',
        'green-area-backend/gis_worker/gee_mock_fixtures.py')]
    fingerprint = {str(x.relative_to(p.REPO)).replace('\\', '/'): hashlib.sha256(x.read_bytes()).hexdigest() for x in source_paths}
    path = local.output / ('e2e-' + local.seed)
    path.with_suffix('.source.json').write_text(json.dumps(fingerprint, indent=2), encoding='utf-8')
    rows = []
    def record(name, passed):
        row = {'name': name, 'status': 'Pass' if passed else 'Fail'}
        rows.append(row)
        with path.with_suffix('.jsonl').open('a', encoding='utf-8') as out:
            out.write(json.dumps(row) + '\n')
        print(json.dumps(row), flush=True)
        if not passed:
            raise AssertionError(name)
    def wait(predicate, timeout=150):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(.4)
        raise RuntimeError('A63_LOCAL_WAIT_EXPIRED')

    local.register()
    officer = local.user()
    local.sql('INSERT INTO gis.officers(user_id) VALUES(' + p.m.t2.t1.literal(officer.subject) + ')')
    normal, id_a, id_b, id_c = local.user(), local.user('gis_gee_mock_worker'), local.user('gis_gee_mock_worker'), local.user('gis_gee_mock_worker')
    runtime = local.runtime(activation=False)
    app = create_app(runtime, rate_limit='10000/minute', gee_mock_catalog=local.catalog)
    # No default/public binding; refuse a pre-existing listener instead of killing it.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 55425))
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=55425, log_level='critical', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    workers = []
    try:
        thread.start()
        wait(lambda: server.started, timeout=20)
        client = httpx.Client(base_url='http://127.0.0.1:55425', trust_env=False, timeout=120,
                              headers={'Authorization': 'Bearer ' + officer.access_token})
        def create(key, idem=None, body=None, token=None):
            headers = {'Idempotency-Key': idem or str(uuid4())}
            if token:
                headers['Authorization'] = 'Bearer ' + token
            return client.post('/gis/mock-gee/jobs', headers=headers,
                               json=body or {'mode': 'gee_contract_mock', 'case_key': key})
        def view(job_id):
            response = client.get('/gis/mock-gee/jobs/' + job_id)
            if response.status_code != 200:
                raise RuntimeError('A63_STATUS_READ_FAILED')
            return response.json()
        def terminal(job_id):
            value = view(job_id)
            return value if value['job']['state'] in ('succeeded', 'failed') else None
        def raw_view(job_id):
            return runtime.rpc('gis_gee_mock_read', {'p_actor': officer.subject, 'p_job': job_id})

        options = client.get('/gis/mock-gee/options')
        record('real_http_auth_and_trusted_catalog_options', options.status_code == 200 and options.json()['case_keys'] == sorted(SPECS))
        record('normal_user_denied_mock_api', create('ndvi-annual', token=normal.access_token).status_code == 403)
        record('worker_token_denied_officer_api', create('ndvi-annual', token=id_a.access_token).status_code == 401)
        for key, value in [('mode', 'live_gee'), ('output', {}), ('worker_id', id_a.subject), ('case_id', str(uuid4())), ('path', '/private'), ('command', 'forbidden')]:
            record('http_rejects_' + key, create('ndvi-annual', body={'mode': 'gee_contract_mock', 'case_key': 'ndvi-annual', key: value}).status_code == 422)

        a = MockContainer(local, id_a)
        workers.append(a)
        b = MockContainer(local, id_b)
        workers.append(b)
        wait(lambda: a.has('ready') and b.has('ready'), timeout=30)
        record('two_real_linux_daemons_ready_with_restricted_jwts', not a.errors and not b.errors)
        idem = str(uuid4())
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: create('ndvi-annual', idem), range(2)))
        record('concurrent_http_requests_share_job', all(x.status_code == 202 for x in responses) and responses[0].json()['job_id'] == responses[1].json()['job_id'])
        job_id = responses[0].json()['job_id']
        value = wait(lambda: terminal(job_id))
        record('api_queue_daemon_adapter_candidate_ndvi_annual', value['job']['state'] == 'succeeded' and value['candidate']['output']['content']['statistics']['mean'] == .4921)
        record('two_daemons_claim_once_and_commit_single_attempt', len(value['attempts']) == 1 and sum(x.has('claimed', job_id) for x in (a, b)) == 1)
        record('response_strips_tokens_and_worker_authority', 'lease_token' not in json.dumps(value) and 'worker_id' not in json.dumps(value))
        record('same_case_new_key_reuses_committed_job', create('ndvi-annual').json()['job_id'] == job_id)
        b.close()
        workers.remove(b)
        record('real_idle_sigterm_stops_daemon_cleanly', b.has('stopped') and b.proc.returncode == 0)

        for key, expected in [('ndvi-monthly', .1614), ('lst-annual', 29.66), ('lst-monthly', 29.66)]:
            response = create(key)
            record(key + '_http_accepted', response.status_code == 202)
            value = wait(lambda: terminal(response.json()['job_id']))
            content = value['candidate']['output']['content'] if value['candidate'] else {}
            record(key + '_daemon_candidate_and_mock_label', value['job']['state'] == 'succeeded' and content['statistics']['mean'] == expected
                   and content['execution'] == 'mock' and content['synthetic'] is True and content['publishable'] is False)
            if key.endswith('monthly'):
                record(key + '_does_not_invent_monthly_extrema', content['statistics']['min'] is None and content['statistics']['max'] is None)

        for key, status in [('no-data', 'no_data'), ('all-masked', 'no_data'), ('partial', 'incomplete')]:
            response = create(key)
            value = wait(lambda: terminal(response.json()['job_id']))
            content = value['attempts'][-1]['validation_report']['output']['content']
            record(key + '_actual_child_failure_not_measurement', value['job']['state'] == 'failed' and value['candidate'] is None
                   and content['status'] == status and content['statistics']['mean'] is None)

        response = create('retry-once')
        value = wait(lambda: terminal(response.json()['job_id']))
        elapsed = (datetime.fromisoformat(value['attempts'][1]['started_at']) - datetime.fromisoformat(value['attempts'][0]['finished_at'])).total_seconds()
        record('actual_daemon_retry_backoff_then_single_candidate', [x['state'] for x in value['attempts']] == ['failed', 'succeeded'] and elapsed >= 5 and value['candidate'] is not None)
        response = create('retry-exhausted')
        exhausted_id = response.json()['job_id']
        value = wait(lambda: terminal(exhausted_id))
        record('actual_daemon_retry_exhaustion_without_candidate', value['job']['state'] == 'failed' and len(value['attempts']) == 3 and value['candidate'] is None)
        record('duplicate_request_does_not_reset_retry_budget', create('retry-exhausted').json()['job_id'] == exhausted_id)

        response = create('long-running')
        recovery_id = response.json()['job_id']
        wait(lambda: a.has('heartbeat', recovery_id), timeout=35)
        abandoned = raw_view(recovery_id)
        started = datetime.fromisoformat(abandoned['attempts'][0]['started_at'])
        renewed = datetime.fromisoformat(abandoned['job']['lease_until'])
        record('long_child_heartbeats_renew_actual_sql_lease', (renewed - started).total_seconds() > 63)
        a.signal('SIGKILL')
        a.proc.wait(timeout=10)
        a.close()
        workers.remove(a)
        record('real_container_sigkill_keeps_running_job_without_candidate', view(recovery_id)['job']['state'] == 'running' and view(recovery_id)['candidate'] is None)
        replacement = MockContainer(local, id_c)
        workers.append(replacement)
        print(json.dumps({'event': 'waiting_for_lease_expiry_and_replacement', 'job_id': recovery_id}), flush=True)
        wait(lambda: replacement.has('claimed', recovery_id), timeout=100)
        old_job = abandoned['job'] | {'request': local.cases['long-running']['request'], 'geometry': local.cases['long-running']['geometry'],
            'semantic_request_sha256': local.cases['long-running']['request_sha256'], 'attempt_number': 1}
        old_report = report(old_job, ComputeOutput.model_validate(local.cases['long-running']['output']))
        try:
            id_a.client.rpc('gis_gee_mock_worker', {'p_action': 'complete', 'p_payload': {'job_id': recovery_id,
                'lease_token': abandoned['job']['lease_token'], 'report': old_report}}).execute()
        except Exception as error:
            record('stale_killed_worker_completion_fenced', getattr(error, 'message', '') == 'GIS_STALE_LEASE')
        else:
            record('stale_killed_worker_completion_fenced', False)
        value = wait(lambda: terminal(recovery_id))
        record('replacement_daemon_recovers_with_exact_history_and_candidate', value['job']['state'] == 'succeeded'
               and [x['state'] for x in value['attempts']] == ['expired', 'succeeded'] and value['candidate'] is not None)
        current = raw_view(recovery_id)
        latest_token = current['attempts'][-1]['lease_token']
        payload = {'p_action': 'complete', 'p_payload': {'job_id': recovery_id, 'lease_token': latest_token, 'report': old_report}}
        with ThreadPoolExecutor(max_workers=2) as pool:
            acks = list(pool.map(lambda _: id_c.client.rpc('gis_gee_mock_worker', payload).execute().data, range(2)))
        record('concurrent_duplicate_acknowledgements_do_not_duplicate_candidate', all(x.get('replayed') is True for x in acks))
        history = client.get('/gis/mock-gee/jobs/' + recovery_id + '/history')
        record('authorized_history_contains_recovery_and_completion', history.status_code == 200
               and 'gee_mock.recover' in history.text and 'gee_mock.complete' in history.text)
        record('generic_existing_job_status_read_remains_compatible', client.get('/gis/jobs/' + recovery_id).status_code == 200)
        record('no_cloud_sdk_or_legacy_startup_imported', not any(x in sys.modules for x in ('ee', 'google.auth', 'dotenv', 'main', 'dependencies')))
        record('all_worker_events_are_bounded_and_safe', not any(x.errors for x in (a, b, replacement)))
        record('source_matches_entire_actual_process_run', all(hashlib.sha256((p.REPO / rel).read_bytes()).hexdigest() == sha for rel, sha in fingerprint.items()))
        client.close()
        result = {'seed': local.seed, 'rows': rows, 'passed': len(rows), 'failed': 0, 'source': fingerprint,
                  'real_http_auth_postgrest': True, 'real_linux_daemon_child': True, 'real_sigkill_recovery': True,
                  'real_sigterm': True, 'gee_calls': False, 'synthetic_only': True, 'frontend_changed': False}
    finally:
        for worker in workers:
            worker.close()
        server.should_exit = True
        if thread.is_alive():
            thread.join(timeout=15)
        local.attest()
    result['cleanup'] = {'owned_workers_removed': not local.approved, 'api_stopped': not thread.is_alive(), 'core_and_volumes_preserved': True}
    path.with_suffix('.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir', type=Path, required=True)
    args = parser.parse_args()
    for logger in ('httpx', 'httpcore', 'supabase_auth', 'postgrest'):
        logging.getLogger(logger).setLevel(logging.CRITICAL)
    def network(event, args):
        if event == 'socket.connect' and (not isinstance(args[1], tuple) or args[1][0] not in ('127.0.0.1', '::1')):
            raise RuntimeError('A63_EXTERNAL_NETWORK_FORBIDDEN')
        if event == 'socket.getaddrinfo' and args[0] not in ('127.0.0.1', '::1', 'localhost', b'127.0.0.1', b'::1'):
            raise RuntimeError('A63_EXTERNAL_DNS_FORBIDDEN')
    sys.addaudithook(network)
    value = run(Local(args.runtime_dir))
    print(json.dumps({'passed': value['passed'], 'failed': value['failed'], 'seed': value['seed'], 'cleanup': value['cleanup']}))
