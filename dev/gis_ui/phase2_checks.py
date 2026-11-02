"""Actual local Auth/API/private ZIP/SQL/Linux queue integration. Synthetic inputs only.

Retains new fixture accounts/rows and original ZIP objects. Does not migrate,
backdate leases, read dotenv, use cloud resources or enable activation gates.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import importlib.util
import json
import logging
from pathlib import Path
import secrets
import struct
import sys
import time
from uuid import uuid4
import zipfile

spec = importlib.util.spec_from_file_location('p2_local_operator', Path(__file__).with_name('phase2_local.py'))
p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p
spec.loader.exec_module(p)
m = p.m
REPO = p.REPO
FIXTURES = REPO / 'green-area-backend/gis_worker/fixtures'


def fingerprint():
    result = m.fingerprint()
    for name in ('phase2_local.py', 'phase2_checks.py'):
        path = Path(__file__).with_name(name)
        result['files'][path.relative_to(REPO).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    path = REPO / 'green-area-backend/gis_ldd_storage.py'
    result['files'][path.relative_to(REPO).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    result['sha256'] = hashlib.sha256(json.dumps(result['files'], sort_keys=True).encode()).hexdigest()
    return result


def repeated_fixture(repeats=5000):
    """Repeat all three known valid polygons, preserving scientific source values.

    Stored ZIP avoids a synthetic compression bomb. Large enough to observe an
    actual claim before killing a real worker; no special provider delay hook.
    """
    with zipfile.ZipFile(FIXTURES / 'ldd_valid.zip') as archive:
        values = {name: archive.read(name) for name in archive.namelist()}
    shp_name = next(n for n in values if n.endswith('.shp'))
    shx_name = next(n for n in values if n.endswith('.shx'))
    dbf_name = next(n for n in values if n.endswith('.dbf'))
    original = values[shp_name]
    records, cursor = [], 100
    while cursor < len(original):
        length = struct.unpack_from('>i', original, cursor + 4)[0] * 2
        records.append(original[cursor + 8:cursor + 8 + length])
        cursor += 8 + length
    shp = bytearray(original[:100])
    shx = bytearray(values[shx_name][:100])
    offset = 50
    for number, record in enumerate(records * repeats, 1):
        length = len(record) // 2
        shp.extend(struct.pack('>ii', number, length) + record)
        shx.extend(struct.pack('>ii', offset, length))
        offset += 4 + length
    struct.pack_into('>i', shp, 24, len(shp) // 2)
    struct.pack_into('>i', shx, 24, len(shx) // 2)
    dbf = values[dbf_name]
    count = struct.unpack_from('<I', dbf, 4)[0]
    header, record_len = struct.unpack_from('<HH', dbf, 8)
    fresh = bytearray(dbf[:header])
    struct.pack_into('<I', fresh, 4, count * repeats)
    fresh.extend(dbf[header:header + count * record_len] * repeats)
    fresh.extend(b'\x1a')
    values.update({shp_name: bytes(shp), shx_name: bytes(shx), dbf_name: bytes(fresh)})
    output = BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, raw in values.items():
            archive.writestr(name, raw)
    return output.getvalue()


class Suite:
    def __init__(self, root):
        self.local = p.Phase2Local(root).prepare()
        self.rows, self.workers, self.events = [], [], []
        self.source = fingerprint()
        self.before = self.local.baseline()
        self.run_id = uuid4().hex[:12]

    def record(self, name, passed, **evidence):
        row = {'name': name, 'status': 'Pass' if passed else 'Fail', **evidence}
        self.rows.append(row)
        print(json.dumps(row), flush=True)
        if not passed:
            raise AssertionError(name)

    def request(self, method, path, body=None, status=200, headers=None, **kwargs):
        response = self.api.request(method, path, json=body, headers={**(headers or self.headers),
            **({'Idempotency-Key': str(uuid4())} if method in ('POST', 'PATCH') else {})}, **kwargs)
        if response.status_code != status:
            value = response.json().get('detail', {})
            code = value.get('code', 'INPUT_VALIDATION') if isinstance(value, dict) else 'INPUT_VALIDATION'
            print(json.dumps({'status': response.status_code, 'expected': status, 'code': code}), flush=True)
            raise RuntimeError('LOCAL_API_STATUS_MISMATCH')
        return response.json()

    def setup(self):
        self.local.attest()
        self.record('initial_queue_idle', self.local.sql("SELECT to_jsonb(count(*)) FROM gis.jobs WHERE state IN ('queued','running')", read_only=True) == 0)
        anon, service = self.local.local_keys()
        operator = self.local.client(service)
        self.users = {}
        for role in ('admin', 'officer', 'normal'):
            email = 'gis-p2-' + role + '-' + self.run_id + '@example.invalid'
            password = secrets.token_urlsafe(30)
            user = operator.auth.admin.create_user({'email': email, 'password': password, 'email_confirm': True}).user
            client = self.local.client(anon)
            session = client.auth.sign_in_with_password({'email': email, 'password': password}).session
            self.users[role] = {'id': str(user.id), 'headers': {'Authorization': 'Bearer ' + session.access_token}}
        quote = m.t2.t1.literal
        self.local.sql("UPDATE public.profiles SET role='admin' WHERE id=" + quote(self.users['admin']['id']) + '::uuid', role='postgres')
        self.api = self.local.api()
        self.headers = self.users['admin']['headers']
        self.request('POST', '/gis/officers', {'user_id': self.users['officer']['id'], 'reason': 'Phase2 isolated synthetic test'})
        self.headers = self.users['officer']['headers']
        year = self.local.sql("SELECT to_jsonb(y) FROM generate_series(1980,2026)y WHERE NOT EXISTS(SELECT 1 FROM gis.datasets WHERE province='Bangkok Metropolis' AND data_year=y AND month=0 AND kind='ldd_shapefile' AND purpose='landuse') ORDER BY y LIMIT 1", read_only=True)
        self.dataset = self.request('POST', '/gis/datasets', {'province': 'Bangkok Metropolis', 'data_year': year,
            'month': 0, 'kind': 'ldd_shapefile', 'purpose': 'landuse', 'title': 'P2 SYNTHETIC upload ' + self.run_id}, status=201)
        self.identity = m.identity_module.provision(self.local)
        self.second = m.identity_module.provision(self.local)
        self.record('real_worker_jwt_ldd_readiness', self.identity.client.rpc('gis_ldd_readiness', {}).execute().data['subject'] == self.identity.subject)

    def upload(self, name='ldd_valid.zip', raw=None, key=None, status=201, headers=None, **query):
        raw = raw if raw is not None else (FIXTURES / name).read_bytes()
        response = self.api.post('/gis/datasets/' + self.dataset['id'] + '/ldd-uploads',
            content=raw, params={'expected_revision': 1, **query}, headers={**(headers or self.headers),
                'Content-Type': 'application/zip', 'Idempotency-Key': key or str(uuid4())})
        self.record('upload_' + name + '_' + str(len(self.rows)), response.status_code == status,
            http_status=response.status_code)
        return response.json()

    def enqueue(self, upload):
        return self.request('POST', '/gis/editions/' + upload['edition_id'] + '/validation-jobs', {'expected_revision': 1}, status=202)['id']

    def state(self, job):
        return self.local.sql("SELECT jsonb_build_object('state',j.state,'worker_id',j.worker_id,'lease_until',j.lease_until,'attempt_count',j.attempt_count,'input_hash',j.input_hash,'input_revision',j.input_revision,'edition_state',e.state,'active',d.active_edition_id,'attempts',(SELECT jsonb_agg(jsonb_build_object('state',a.state,'report',a.validation_report,'error_code',a.error_code) ORDER BY attempt_no) FROM gis.attempts a WHERE a.job_id=j.id),'result_count',(SELECT count(*) FROM gis.results WHERE job_id=j.id)) FROM gis.jobs j JOIN gis.editions e ON e.id=j.edition_id JOIN gis.datasets d ON d.id=e.dataset_id WHERE j.id=" + m.t2.t1.literal(job) + '::uuid', read_only=True)

    def rpc(self, action, payload=None, identity=None, name='gis_ldd_worker'):
        return (identity or self.identity).client.rpc(name, {'p_action': action, 'p_payload': payload or {}}).execute().data

    def denied(self, name, call, expected):
        try:
            call()
        except Exception as error:
            code = str(getattr(error, 'code', ''))
            message = str(getattr(error, 'message', ''))
            self.record(name, code in expected or message in expected)
            return
        self.record(name, False)

    def start(self, identity=None, legacy=False):
        worker = m.ContainerWorker(self.local, identity or self.identity) if legacy else p.LddContainer(self.local, identity or self.identity)
        self.workers.append(worker)
        m.wait_for(lambda: worker.has('ready') or worker.has('fatal'), 30)
        self.record(('v2' if legacy else 'ldd') + '_linux_worker_ready_' + str(len(self.rows)), worker.has('ready') and not worker.has('fatal'))
        return worker

    def close(self, worker):
        worker.close()
        self.events.extend(worker.events)
        self.workers.remove(worker)

    def uploads_security(self):
        raw = (FIXTURES / 'ldd_valid.zip').read_bytes()
        key = str(uuid4())
        good = self.upload(key=key)
        replay = self.upload(key=key)
        duplicate = self.upload(status=200)
        self.record('idempotency_and_hash_dedup_same_immutable_association', good == replay and good['upload_id'] == duplicate['upload_id'] and good['edition_id'] == duplicate['edition_id'])
        self.upload(name='ldd_missing_dbf.zip', key=key, status=409)
        path = self.local.store.objects / (good['sha256'] + '.zip')
        self.record('published_original_sha_size_bytes_unchanged', path.read_bytes() == raw and good['sha256'] == hashlib.sha256(raw).hexdigest() and good['byte_size'] == len(raw))
        metadata = self.request('GET', '/gis/ldd-uploads/' + good['upload_id'])
        self.record('authorized_upload_metadata_no_path_or_lease', metadata['sha256'] == good['sha256'] and 'path' not in metadata and 'lease_token' not in metadata)
        edition = self.request('GET', '/gis/editions/' + good['edition_id'])
        self.request('PATCH', '/gis/editions/' + good['edition_id'], {'expected_revision': 1, 'manifest': edition['manifest']}, status=409)
        self.request('POST', '/gis/editions/' + good['edition_id'] + '/clone', {'expected_revision': 1}, status=409)
        self.record('uploaded_manifest_edit_clone_immutable', True)
        self.upload(headers=self.users['normal']['headers'], status=403)
        unauth = self.api.post('/gis/datasets/' + self.dataset['id'] + '/ldd-uploads', content=raw,
            params={'expected_revision': 1}, headers={'Idempotency-Key': str(uuid4()), 'Content-Type': 'application/zip'})
        self.record('unauthenticated_binary_upload_denied', unauth.status_code == 401)
        for name in ('zip_traversal.zip', 'zip_symlink.zip'):
            self.upload(name, status=422)
        self.upload(raw=b'not a ZIP', status=422)
        self.upload(raw=raw, expected_revision=99, status=409)
        self.denied('worker_admin_rpc_denied', lambda: self.identity.client.rpc('gis_command', {'p_actor': self.identity.subject, 'p_request_id': str(uuid4()), 'p_operation': 'grant_officer', 'p_payload': {}}).execute(), {'42501'})
        self.denied('worker_service_upload_rpc_denied', lambda: self.identity.client.rpc('gis_ldd_command', {'p_actor': self.identity.subject, 'p_request_id': str(uuid4()), 'p_operation': 'upload', 'p_payload': {}}).execute(), {'42501'})
        self.denied('worker_legacy_table_read_denied', lambda: self.identity.client.table('profiles').select('id').limit(1).execute(), {'42501'})
        self.denied('worker_jwt_spoofing_denied', lambda: self.rpc('claim', {'worker_id': str(uuid4())}), {'GIS_WORKER_IDENTITY_MISMATCH', '42501'})
        job_id = self.enqueue(good)
        self.record('v2_claim_ignores_uploaded_ldd', self.rpc('claim', name='gis_worker_v2').get('job') is None and self.state(job_id)['attempt_count'] == 0)
        v1 = self.local.sql("SELECT public.gis_worker('claim'," + m.t2.t1.literal(json.dumps({'worker_id': str(uuid4())})) + '::jsonb)', role='gis_worker')
        self.record('v1_claim_ignores_uploaded_ldd', v1 is None and self.state(job_id)['attempt_count'] == 0)
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda identity: self.rpc('claim', identity=identity), (self.identity, self.second)))
        owners = [(identity, claim['job']) for identity, claim in zip((self.identity, self.second), claims) if claim.get('job')]
        self.record('concurrent_jwt_claim_exactly_once', len(owners) == 1 and owners[0][1]['id'] == job_id and self.state(job_id)['attempt_count'] == 1)
        identity, job = owners[0]
        from gis_worker.ldd_provider import report_failure
        request = {k: job[k] for k in ('upload_id', 'manifest', 'input_hash', 'input_revision', 'attempt_number', 'province', 'data_year', 'encoding')}
        report = report_failure(request, 'WORKER_SHUTDOWN')
        lease = {'job_id': job_id, 'lease_token': job['lease_token']}
        self.denied('empty_native_report_bypass_rejected', lambda: self.rpc('complete', {**lease, 'report': {}}, identity), {'GIS_LDD_REPORT_REQUIRED'})
        bad = {**report, 'artifact_sha256': '0' * 64}
        self.denied('artifact_hash_mismatch_rejected', lambda: self.rpc('complete', {**lease, 'report': bad}, identity), {'GIS_LDD_REPORT_INVALID'})
        bad = {**report, 'input_revision': 99}
        self.denied('input_revision_mismatch_rejected', lambda: self.rpc('complete', {**lease, 'report': bad}, identity), {'GIS_LDD_REPORT_INVALID'})
        self.denied('wrong_lease_complete_rejected', lambda: self.rpc('complete', {**lease, 'lease_token': str(uuid4()), 'report': report}, identity), {'GIS_STALE_LEASE'})
        self.rpc('fail', {**lease, 'error_code': 'transient', 'report': report}, identity)
        worker = self.start()
        state = m.wait_for(lambda: (s if (s := self.state(job_id))['state'] in ('succeeded', 'failed') else None), 55)
        self.record('actual_upload_api_queue_linux_result', state['state'] == 'succeeded' and state['edition_state'] == 'validated' and state['result_count'] == 1 and state['attempt_count'] == 2 and state['active'] is None)
        self.close(worker)
        self.good = good

    def science(self):
        worker = self.start()
        for fixture, valid, encoding in [('ldd_cp874.zip', True, 'cp874'), ('ldd_composite_a.zip', True, 'auto'),
                                         ('ldd_unknown.zip', False, 'auto'), ('ldd_missing_dbf.zip', False, 'auto')]:
            upload = self.upload(fixture, encoding=encoding)
            job = self.enqueue(upload)
            state = m.wait_for(lambda: (s if (s := self.state(job))['state'] in ('succeeded', 'failed') else None), 45)
            report = state['attempts'][-1]['report']
            self.record('native_validation_' + fixture, state['state'] == ('succeeded' if valid else 'failed') and report['valid'] is valid and state['result_count'] == (1 if valid else 0) and state['active'] is None)
            self.record('native_attempt_report_api_' + fixture, self.request('GET', '/gis/jobs/' + job + '/attempts')['data'][-1]['validation_report'] == report)
            if valid:
                result = self.request('GET', '/gis/jobs/' + job + '/result')['result']
                self.record('scientific_area_encoding_' + fixture, result['provider'] == 'local_ldd' and abs(report['statistics']['total_area_m2'] - 6400) < .001 and report['statistics']['feature_count'] == 3 and report['observed_sha256'] == upload['sha256'] and report['encoding'] == ('cp874' if encoding == 'cp874' else 'utf-8'))
            elif fixture == 'ldd_unknown.zip':
                self.record('unknown_codes_preserve_area_and_fail_review', report['statistics']['unknown_code_count'] > 0 and report['statistics']['unknown_area_m2'] > 0 and report['error_code'] == 'UNKNOWN_CODE_REVIEW_REQUIRED')
        self.close(worker)

    def compatibility(self):
        # Real V1 and V2 jobs coexist; LDD worker must not claim either.
        from gis_worker.provider import fixture_manifest
        first = self.local.sql("SELECT to_jsonb(f.manifest) FROM gis.synthetic_fixtures f WHERE id='ldd-valid-v1'", read_only=True)
        jobs = []
        for manifest in (first, fixture_manifest('t3-ldd-valid-v2')):
            edition = self.request('POST', '/gis/datasets/' + self.dataset['id'] + '/editions', {'manifest': manifest}, status=201)
            jobs.append(self.request('POST', '/gis/editions/' + edition['id'] + '/validation-jobs', {'expected_revision': 1}, status=202)['id'])
        self.record('ldd_claim_ignores_v1_v2', self.rpc('claim').get('job') is None and all(self.state(j)['attempt_count'] == 0 for j in jobs))
        lease = self.local.sql("SELECT public.gis_worker('claim'," + m.t2.t1.literal(json.dumps({'worker_id': str(uuid4())})) + '::jsonb)', role='gis_worker')
        self.record('v1_claim_preserved', lease['job_id'] == jobs[0])
        payload = {**{k: lease[k] for k in ('job_id', 'worker_id', 'lease_token')}, 'report': {'valid': True, 'fixture_id': 'ldd-valid-v1', 'checks': ['synthetic_fixture_match']}}
        self.local.sql("SELECT public.gis_worker('complete'," + m.t2.t1.literal(json.dumps(payload)) + '::jsonb)', role='gis_worker')
        worker = self.start(legacy=True)
        m.wait_for(lambda: self.state(jobs[1])['state'] == 'succeeded', 40)
        self.close(worker)
        self.record('v1_v2_compatibility_no_auto_activation', all(self.state(j)['state'] == 'succeeded' and self.state(j)['active'] is None for j in jobs))
        self.request('POST', '/gis/datasets/' + self.dataset['id'] + '/activation', {'edition_id': self.good['edition_id'], 'expected_revision': 1, 'expected_active_edition_id': None, 'reason': 'Gate remains closed'}, status=403)
        self.request('POST', '/gis/datasets/' + self.dataset['id'] + '/activation', {'edition_id': self.good['edition_id'], 'expected_revision': 1, 'expected_active_edition_id': None, 'reason': 'Gate remains closed'}, status=503, headers=self.users['admin']['headers'])
        self.record('officer_and_closed_admin_activation_gate_preserved', True)

    def recovery(self, repeats=500):
        raw = repeated_fixture(repeats)
        upload = self.upload(name='generated-' + str(3 * repeats) + '-synthetic-polygons.zip', raw=raw)
        job = self.enqueue(upload)
        worker = self.start()
        m.wait_for(lambda: worker.has('claimed', job), 25)
        # Kill immediately after observing a genuine claim. Read-only operator
        # attestation can take seconds; the lease remains available after kill.
        worker.signal('SIGKILL')
        worker.proc.wait(timeout=10)
        frozen = self.local.sql("SELECT jsonb_build_object('lease_token',lease_token,'worker_id',worker_id) FROM gis.jobs WHERE id=" + m.t2.t1.literal(job) + '::uuid', read_only=True)
        state = self.state(job)
        if state['state'] != 'running':
            self.rows.append({'name': 'actual_ldd_kill_recovery', 'status': 'Not Tested', 'reason': 'Native validation completed before process kill; no lease was backdated'})
            self.close(worker)
            return
        self.record('actual_ldd_worker_sigkill_running_lease_retained', worker.proc.returncode != 0 and frozen['worker_id'] == self.identity.subject)
        self.close(worker)
        replacement = self.start(self.second)
        state = m.wait_for(lambda: (s if (s := self.state(job))['attempt_count'] >= 2 else None), 95)
        self.record('replacement_recovers_actual_expired_ldd_lease', state['attempts'][0]['state'] == 'expired' and replacement.has('claimed', job))
        self.denied('old_worker_completion_fenced_after_replacement', lambda: self.rpc('complete', {'job_id': job, 'lease_token': frozen['lease_token'], 'report': {}}), {'GIS_STALE_LEASE'})
        state = m.wait_for(lambda: (s if (s := self.state(job))['state'] in ('succeeded', 'failed') else None), 100)
        self.record('replacement_native_validation_terminal_no_duplicate_result', state['state'] == 'succeeded' and state['result_count'] == 1 and state['attempt_count'] == 2 and state['active'] is None)
        self.close(replacement)

    def finish(self):
        for worker in list(self.workers):
            try:
                self.close(worker)
            except Exception:
                self.rows.append({'name': 'owned_worker_cleanup', 'status': 'Fail'})
        after = self.local.baseline()
        for db, before in self.before.items():
            current = after[db]
            self.rows.append({'name': 'legacy_and_ledger_preservation_' + db, 'status': 'Pass' if before['ledger'] == current['ledger'] and all(current['profiles'].get(k) == v for k, v in before['profiles'].items()) and all(current['tables'].get(k) == v for k, v in before['tables'].items() if k != 'profiles') else 'Fail'})
        self.local.check_frozen()
        self.rows.append({'name': 'source_unchanged_during_execution', 'status': 'Pass' if self.source == fingerprint() else 'Fail'})
        self.rows.append({'name': 'owned_workers_removed', 'status': 'Pass' if not self.local.approved else 'Fail'})
        result = {'type': 'actual_local_auth_api_private_storage_linux_worker_sql_integration', 'synthetic_fixtures_only': True,
            'run_id': self.run_id, 'sections': self.sections, 'source': self.source, 'results': self.rows, 'worker_events': self.events,
            'counts': {status: sum(r['status'] == status for r in self.rows) for status in ('Pass', 'Fail', 'Not Tested')},
            'cloud_access': False, 'credentials_persisted': False, 'activation_gate_enabled': False,
            'cleanup': 'Owned workers removed; new synthetic fixture accounts, database rows and immutable originals retained'}
        self.local.write('integration-' + self.run_id + '.json', result)
        self.local.write('integration-latest.json', result)
        print(json.dumps({'counts': result['counts'], 'source_sha256': self.source['sha256']}), flush=True)

    def run(self, recovery_only=False):
        self.sections = 'recovery_only' if recovery_only else 'full'
        try:
            self.setup()
            if not recovery_only:
                self.uploads_security()
                self.science()
                self.compatibility()
            self.recovery()
        except Exception as error:
            self.rows.append({'name': 'suite_execution', 'status': 'Fail', 'error_type': type(error).__name__})
            print(json.dumps(self.rows[-1]), flush=True)
        finally:
            self.finish()
        return not any(row['status'] == 'Fail' for row in self.rows)


if __name__ == '__main__':
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--recovery-only', action='store_true')
    args = parser.parse_args()
    sys.exit(0 if Suite(args.runtime_dir).run(args.recovery_only) else 1)
