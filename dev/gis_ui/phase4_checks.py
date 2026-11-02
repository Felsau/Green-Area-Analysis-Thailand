"""Actual local GeoTIFF Auth/API/storage/queue/Linux acceptance checks.

Only newly-created synthetic identities/jobs are used. Existing public/GIS
rows, cache, immutable objects, source and migration ledger are preserved.
Recovery begins with a manual authorized claim; it is NOT a SIGKILL test.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import secrets
import sys
from uuid import uuid4

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('p4_operator', HERE / 'phase4_local.py')
p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p
spec.loader.exec_module(p)
spec = importlib.util.spec_from_file_location('p4_reuse_checks', HERE / 'phase3_checks.py')
previous = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = previous
spec.loader.exec_module(previous)
m, REPO = p.m, p.REPO


def fingerprint():
    result = previous.fingerprint()
    for rel in ('dev/gis_ui/phase4_local.py', 'dev/gis_ui/phase4_checks.py',
                'green-area-backend/gis_geotiff_storage.py'):
        result['files'][rel] = hashlib.sha256((REPO / rel).read_bytes()).hexdigest()
    result['sha256'] = hashlib.sha256(json.dumps(result['files'], sort_keys=True).encode()).hexdigest()
    return result


class Suite(previous.Suite):
    def __init__(self, root):
        self.local = p.Phase4Local(root).prepare()
        self.source = fingerprint()
        self.before = self.local.baseline()
        self.gis_before = self.catalog_hashes()
        self.cache_before = self.cache()
        self.rows, self.workers, self.events, self.jobs = [], [], [], []
        self.run_id = uuid4().hex[:12]
        self.fixture_root = self.local.db.runtime.root / 'phase4/fixtures'
        self.fixture_manifest = json.loads((self.fixture_root / 'manifest.json').read_text(encoding='utf-8'))

    def catalog_hashes(self):
        result = {}
        for database in ('postgres', 'gis_t1_upgrade'):
            tables = self.local.sql("SELECT jsonb_agg(tablename ORDER BY tablename) FROM pg_tables WHERE schemaname='gis'", database, role='postgres', read_only=True)
            parts = []
            for table in tables:
                ident = '"' + table.replace('"', '""') + '"'
                parts.append(m.t2.t1.literal(table) + ",(SELECT COALESCE(jsonb_agg(md5(to_jsonb(t)::text) ORDER BY md5(to_jsonb(t)::text)),'[]'::jsonb) FROM gis." + ident + ' t)')
            result[database] = self.local.sql('SELECT jsonb_build_object(' + ','.join(parts) + ')', database, role='postgres', read_only=True)
        return result

    def setup(self):
        self.record('initial_queue_idle', self.local.sql("SELECT to_jsonb(count(*)) FROM gis.jobs WHERE state IN ('queued','running')", read_only=True) == 0)
        anon, service = self.local.local_keys()
        self.operator = self.local.client(service)
        self.users = {}
        for role in ('admin', 'officer', 'normal'):
            email = 'gis-p4-' + role + '-' + self.run_id + '@example.invalid'
            password = secrets.token_urlsafe(30)
            user = self.operator.auth.admin.create_user({'email': email, 'password': password, 'email_confirm': True}).user
            client = self.local.client(anon)
            session = client.auth.sign_in_with_password({'email': email, 'password': password}).session
            self.users[role] = {'id': str(user.id), 'headers': {'Authorization': 'Bearer ' + session.access_token}}
        self.local.sql("UPDATE public.profiles SET role='admin' WHERE id=" + m.t2.t1.literal(self.users['admin']['id']) + '::uuid', role='postgres')
        self.api = self.local.api()
        self.headers = self.users['admin']['headers']
        self.request('POST', '/gis/officers', {'user_id': self.users['officer']['id'], 'reason': 'Phase4 synthetic acceptance'})
        self.headers = self.users['officer']['headers']
        self.identity = m.identity_module.provision(self.local)
        self.second = m.identity_module.provision(self.local)
        ready = self.identity.client.rpc('gis_geotiff_readiness', {}).execute().data
        self.record('real_least_privilege_geotiff_jwt_ready', ready['subject'] == self.identity.subject and ready['contract_version'] == '1.0.0-geotiff-local')
        year = self.local.sql("SELECT to_jsonb(y) FROM generate_series(1980,2026)y WHERE NOT EXISTS(SELECT 1 FROM gis.datasets WHERE province='Bangkok Metropolis' AND data_year=y AND kind='geotiff') ORDER BY y LIMIT 1", read_only=True)
        if year is None:
            raise RuntimeError('UNUSED_LOCAL_DATASET_YEAR_REQUIRED')
        self.datasets = {}
        for metric in ('ndvi', 'lst'):
            self.datasets[metric] = self.request('POST', '/gis/datasets', {'province': 'Bangkok Metropolis', 'data_year': year,
                'month': 0, 'kind': 'geotiff', 'purpose': metric, 'title': 'P4 SYNTHETIC TIFF ' + metric + ' ' + self.run_id}, status=201)
        self.record('new_synthetic_metric_datasets_created', self.datasets['ndvi']['id'] != self.datasets['lst']['id'])

    def rpc(self, action, payload=None, identity=None, name='gis_geotiff_worker'):
        return (identity or self.identity).client.rpc(name, {'p_action': action, 'p_payload': payload or {}}).execute().data

    def upload(self, name, *, key=None, status=201, headers=None, dataset=None, changes=None):
        fixture = self.fixture_manifest['fixtures'][name]
        raw = (self.fixture_root / fixture['filename']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != fixture['sha256'] or len(raw) != fixture['byte_size']:
            raise RuntimeError('SYNTHETIC_FIXTURE_HASH_DRIFT')
        ds = dataset or self.datasets[fixture['metric']]
        query = {'expected_revision': ds['revision'], 'profile': fixture['profile'], 'crs': fixture['declared_crs'], **(changes or {})}
        response = self.api.post('/gis/datasets/' + ds['id'] + '/geotiff-uploads', params=query, content=raw,
            headers={**(self.headers if headers is None else headers), 'Idempotency-Key': key or str(uuid4()), 'Content-Type': 'image/tiff'})
        if response.status_code != status:
            code = response.json().get('detail', {}).get('code', 'UNKNOWN')
            print(json.dumps({'local_status': response.status_code, 'expected': status, 'code': code}), flush=True)
            raise RuntimeError('GEOTIFF_UPLOAD_STATUS_MISMATCH')
        return response.json()

    def enqueue(self, upload):
        job = self.request('POST', '/gis/editions/' + upload['edition_id'] + '/validation-jobs', {'expected_revision': 1}, status=202)
        self.jobs.append(job['id'])
        return job

    def start(self, identity=None, kind='geotiff'):
        identity = identity or self.identity
        factory = {'geotiff': p.GeoTiffContainer, 'processing': p.p.ProcessingContainer,
                   'ldd': p.p.m.LddContainer, 'v2': m.ContainerWorker}[kind]
        worker = factory(self.local, identity)
        self.workers.append(worker)
        m.wait_for(lambda: worker.has('ready') or worker.has('fatal'), 30)
        self.record(kind + '_linux_worker_ready_' + str(len(self.rows)), worker.has('ready') and not worker.has('fatal'))
        return worker

    @staticmethod
    def native_request(claim):
        return {k: claim[k] for k in ('upload_id', 'manifest', 'input_hash', 'input_revision', 'attempt_number', 'province', 'data_year')}

    def authorization_and_recovery(self):
        self.upload('ndvi_valid', status=401, headers={})
        self.upload('ndvi_valid', status=403, headers=self.users['normal']['headers'])
        self.upload('ndvi_valid', status=422, dataset=self.datasets['lst'])
        self.upload('ndvi_valid', status=409, changes={'expected_revision': 2})
        self.record('unauthorized_wrong_metric_and_revision_uploads_rejected', True)
        for name, rpc, parameters in (
            ('worker_admin_rpc_denied', 'gis_command', {'p_actor': self.identity.subject, 'p_request_id': str(uuid4()), 'p_operation': 'grant_officer', 'p_payload': {}}),
            ('worker_upload_service_rpc_denied', 'gis_geotiff_command', {'p_actor': self.identity.subject, 'p_request_id': str(uuid4()), 'p_operation': 'preflight', 'p_payload': {}}),
            ('worker_upload_read_service_rpc_denied', 'gis_geotiff_read', {'p_actor': self.identity.subject, 'p_upload_id': str(uuid4())})):
            self.denied(name, lambda rpc=rpc, parameters=parameters: self.identity.client.rpc(rpc, parameters).execute(), {'42501'})
        self.denied('worker_direct_legacy_read_denied', lambda: self.identity.client.table('profiles').select('id').limit(1).execute(), {'42501'})
        self.denied('worker_legacy_cache_write_denied', lambda: self.identity.client.table('ndvi_annual').update({'ndvi_mean': .5}).eq('province', 'P4_UNMATCHABLE_SYNTHETIC').execute(), {'42501'})
        self.denied('worker_jwt_subject_spoof_rejected', lambda: self.rpc('claim', {'worker_id': str(uuid4())}), {'GIS_WORKER_IDENTITY_MISMATCH', '42501'})
        key = str(uuid4())
        uploaded = self.upload('ndvi_valid', key=key)
        same = self.upload('ndvi_valid', key=key)
        dedup = self.upload('ndvi_valid', status=200)
        self.record('upload_same_key_and_new_key_dedup_one_immutable_association', uploaded['upload_id'] == same['upload_id'] == dedup['upload_id'] and uploaded['edition_id'] == dedup['edition_id'])
        job = self.enqueue(uploaded)
        self.first_upload, self.first_job = uploaded, job
        for rpc in ('gis_ldd_worker', 'gis_worker_v2', 'gis_processing_worker'):
            self.record(rpc + '_does_not_claim_geotiff', self.rpc('claim', name=rpc).get('job') is None)
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda identity: self.rpc('claim', identity=identity), (self.identity, self.second)))
        owners = [(identity, claim['job']) for identity, claim in zip((self.identity, self.second), claims) if claim.get('job')]
        self.record('concurrent_claim_exactly_once', len(owners) == 1 and owners[0][1]['id'] == job['id'])
        owner, claim = owners[0]
        self.claim_owner = owner
        other = self.second if owner is self.identity else self.identity
        lease = {'job_id': job['id'], 'lease_token': claim['lease_token']}
        self.denied('different_jwt_subject_cannot_heartbeat_owner_lease', lambda: self.rpc('heartbeat', {**lease, 'progress': 5}, identity=other), {'GIS_STALE_LEASE'})
        self.denied('wrong_lease_complete_fenced', lambda: self.rpc('complete', {'job_id': job['id'], 'lease_token': str(uuid4()), 'report': {}}, identity=owner), {'GIS_STALE_LEASE'})
        from gis_worker.geotiff_provider import CHECKS, report_failure
        failure = report_failure(self.native_request(claim), 'GEOTIFF_TEST_FAILURE')
        wrong = deepcopy(failure)
        wrong['input_hash'] = '0' * 64
        self.denied('report_wrong_input_hash_rejected', lambda: self.rpc('complete', {**lease, 'report': wrong}, identity=owner), {'GIS_GEOTIFF_REPORT_INVALID'})
        wrong = deepcopy(failure)
        wrong['input_revision'] = 2
        self.denied('report_wrong_input_revision_rejected', lambda: self.rpc('complete', {**lease, 'report': wrong}, identity=owner), {'GIS_GEOTIFF_REPORT_INVALID'})
        forged = deepcopy(failure)
        forged.update(valid=True, error_code=None, errors=[], checks=list(CHECKS), observed_sha256=claim['manifest']['sha256'])
        forged['statistics'].update(width=2, height=2, band_count=1, total_pixels=4, valid_pixels=3, nodata_pixels=1, mean=100, min=-.5, max=.5)
        forged['metadata'].update(crs='EPSG:32647', bands=['NDVI'], resolution=[30, 30], dtype='float32', nodata=-9999,
            units='unitless', scales=[1], offsets=[0], profile='ndvi_ready', output_units='unitless')
        self.denied('forged_success_scientific_report_rejected', lambda: self.rpc('complete', {**lease, 'report': forged}, identity=owner), {'GIS_GEOTIFF_SCIENTIFIC_INVARIANT'})
        heartbeat = self.rpc('heartbeat', {**lease, 'progress': 5}, identity=owner)
        self.record('manual_claim_heartbeat_real_sql_lease', heartbeat['progress'] == 5 and self.state(job['id'])['state'] == 'running')
        replacement = self.start(other)
        state = self.terminal(job['id'], 115)
        self.record('natural_expiry_replacement_recovery_actual_linux_validation', state['state'] == 'succeeded' and state['attempt_count'] == 2
            and state['attempts'][0]['state'] == 'expired' and state['result_count'] == 1 and state['result']['provider'] == 'local_geotiff')
        self.denied('expired_original_token_completion_rejected', lambda: self.rpc('complete', {**lease, 'report': forged}, identity=owner), {'GIS_STALE_LEASE'})
        self.record('passed_geotiff_stays_draft_null_pointer_not_eligible', state['edition_state'] == 'draft' and state['validated_result'] is None and state['active'] is None and state['eligible'] is False)
        self.verify_report('ndvi_valid', job)
        self.close(replacement)

    def verify_report(self, name, job):
        expected = self.fixture_manifest['fixtures'][name]
        state = self.state(job['id'])
        attempts = self.request('GET', '/gis/jobs/' + job['id'] + '/attempts')['data']
        report = attempts[-1]['validation_report']
        if expected['expected_valid']:
            result = self.request('GET', '/gis/jobs/' + job['id'] + '/result')
            self.record(name + '_native_report_expected_science', state['state'] == 'succeeded' and state['result_count'] == 1
                and report['valid'] is True and abs(report['statistics']['mean'] - expected['expected_mean']) < 2e-5
                and report['statistics']['valid_pixels'] == 3 and report['metadata']['scales'] == [1]
                and report['metadata']['offsets'] == [0] and result['result']['report'] == report)
        else:
            self.record(name + '_native_invalid_report_safe_failure', state['state'] == 'failed' and state['result_count'] == 0
                and report['valid'] is False and report['error_code'] == expected['expected_error']
                and report['statistics']['mean'] is None and state['edition_state'] == 'draft' and state['active'] is None)
        upload = self.local.sql("SELECT to_jsonb(u) FROM gis.geotiff_uploads u WHERE edition_id=" + m.t2.t1.literal(job['edition_id']) + '::uuid', read_only=True)
        path = self.local.geotiff_store.objects / (upload['sha256'] + '.tif')
        self.record(name + '_immutable_bytes_and_bound_metadata', path.is_file() and not path.is_symlink()
            and path.stat().st_size == expected['byte_size'] and hashlib.sha256(path.read_bytes()).hexdigest() == expected['sha256']
            and report['artifact_sha256'] == upload['sha256'] and report['input_hash'] == job['input_hash']
            and report['input_revision'] == job['input_revision'])

    def http_limits(self):
        before = {file.name: (file.stat().st_size, hashlib.sha256(file.read_bytes()).hexdigest()) for file in self.local.geotiff_store.objects.iterdir()}
        fixture = self.fixture_manifest['fixtures']['ndvi_valid']
        response = self.api.post('/gis/datasets/' + self.datasets['ndvi']['id'] + '/geotiff-uploads',
            params={'expected_revision': 1, 'profile': 'ndvi_ready', 'crs': 'EPSG:32647'},
            content=b'II*\0' + bytes(8), headers={**self.headers, 'Content-Type': 'image/tiff',
                'Content-Length': str(20 * 1024**2 + 1), 'Idempotency-Key': str(uuid4())})
        after = {file.name: (file.stat().st_size, hashlib.sha256(file.read_bytes()).hexdigest()) for file in self.local.geotiff_store.objects.iterdir()}
        self.record('http_oversize_declared_length_413_no_object_mutation', response.status_code == 413 and before == after)

    def science(self, include_first=False):
        queued = []
        for name in self.fixture_manifest['fixtures']:
            if name == 'ndvi_valid' and not include_first:
                continue
            uploaded = self.upload(name)
            metadata = self.request('GET', '/gis/geotiff-uploads/' + uploaded['upload_id'])
            self.record(name + '_upload_read_association', metadata['edition_id'] == uploaded['edition_id']
                and metadata['dataset_id'] == self.datasets[self.fixture_manifest['fixtures'][name]['metric']]['id'])
            queued.append((name, self.enqueue(uploaded)))
        worker = self.start()
        for name, job in queued:
            self.terminal(job['id'])
            self.verify_report(name, job)
        self.close(worker)

    def isolation(self):
        # The existing implementation exercises fresh real LDD and native V2 jobs
        # using their actual workers and fixed fixture catalog, not SQL patches.
        start_index = len(self.rows)
        previous.Suite.isolation(self)
        for row in self.rows[start_index:]:
            row['name'] = row['name'].replace('processing_claim_ignores_ldd_and_native_v2', 'geotiff_claim_ignores_ldd_and_native_v2').replace('after_035', 'after_036')
        year = self.local.sql("SELECT to_jsonb(y) FROM generate_series(2017,2026)y WHERE NOT EXISTS(SELECT 1 FROM gis.processing_requests WHERE province='Bangkok Metropolis' AND data_year=y) ORDER BY y LIMIT 1", read_only=True)
        body = {'province': 'Bangkok Metropolis', 'district': None, 'metric': 'ndvi', 'data_year': year,
                'month': 0, 'mode': 'offline_synthetic', 'scenario': 'standard', 'expected_revision': 1}
        job = self.request('POST', '/gis/processing-jobs', body, status=202)
        self.jobs.append(job['id'])
        self.record('geotiff_claim_ignores_processing', self.rpc('claim').get('job') is None and self.state(job['id'])['attempt_count'] == 0)
        worker = self.start(kind='processing')
        state = self.terminal(job['id'])
        self.record('processing_pipeline_preserved_after_036', state['state'] == 'succeeded' and state['result']['provider'] == 'offline_processing' and state['edition_state'] == 'draft')
        self.close(worker)
        self.rows.append({'name': 'v1_actual_worker_e2e', 'status': 'Not Tested',
            'reason': 'No V1 Python daemon exists; existing V1 protocol delegates remain unchanged. V2/LDD/processing actual worker E2E covered.'})

    def finish(self):
        for worker in list(self.workers):
            try:
                self.close(worker)
            except Exception:
                self.rows.append({'name': 'owned_worker_cleanup', 'status': 'Fail'})
        after = self.local.baseline()
        for database, before in self.before.items():
            now = after[database]
            self.rows.append({'name': 'legacy_and_ledger_preservation_' + database, 'status': 'Pass' if
                before['ledger'] == now['ledger'] and all(now['profiles'].get(k) == v for k, v in before['profiles'].items())
                and all(now['tables'].get(k) == v for k, v in before['tables'].items() if k != 'profiles') else 'Fail'})
        after_gis = self.catalog_hashes()
        for database, tables in self.gis_before.items():
            same = all(not (Counter(rows) - Counter(after_gis[database].get(table, []))) for table, rows in tables.items())
            self.rows.append({'name': 'preexisting_gis_catalog_rows_preserved_' + database, 'status': 'Pass' if same else 'Fail'})
        checkpoint = json.loads((self.local.directory / 'initial-state.json').read_text(encoding='utf-8'))['baseline']
        self.rows.append({'name': 'pre036_ledger_entries_and_timestamps_preserved', 'status': 'Pass' if all(
            checkpoint[d]['ledger'] == [row for row in after[d]['ledger'] if row['version'] <= 35] for d in checkpoint) else 'Fail'})
        self.local.check_frozen()
        self.rows.append({'name': 'legacy_cache_values_unchanged', 'status': 'Pass' if self.cache_before == self.cache() else 'Fail'})
        self.rows.append({'name': 'source_unchanged_during_execution', 'status': 'Pass' if self.source == fingerprint() else 'Fail'})
        self.rows.append({'name': 'owned_workers_removed', 'status': 'Pass' if not self.local.approved else 'Fail'})
        pending = self.local.sql("SELECT to_jsonb(count(*)) FROM gis.jobs WHERE state IN ('queued','running')", read_only=True)
        self.rows.append({'name': 'queue_idle_after_tests', 'status': 'Pass' if pending == 0 else 'Fail'})
        equivalence = {}
        prior_path = self.local.directory / 'integration-3e15370a577f.json'
        if prior_path.exists():
            prior = json.loads(prior_path.read_text(encoding='utf-8'))
            equivalence = {'prior_record': prior_path.name,
                'other_application_sql_native_sources_unchanged': all(self.source['files'].get(file) == digest
                    for file, digest in prior['source']['files'].items() if file != 'dev/gis_ui/phase4_checks.py'),
                'changed_test_helper_only': [file for file, digest in prior['source']['files'].items()
                    if self.source['files'].get(file) != digest] == ['dev/gis_ui/phase4_checks.py']}
        result = {'type': 'actual_local_geotiff_auth_storage_queue_linux', 'run_id': self.run_id, 'source': self.source,
            'sections': self.sections, 'source_equivalence_to_prior_security_recovery_run': equivalence,
            'synthetic_only': True, 'results': self.rows, 'worker_events': self.events,
            'counts': {s: sum(r['status'] == s for r in self.rows) for s in ('Pass', 'Fail', 'Not Tested')},
            'fixture_manifest_sha256': hashlib.sha256((self.fixture_root / 'manifest.json').read_bytes()).hexdigest(),
            'recovery_scope': 'Manual authorized SQL RPC claim+heartbeat, natural lease expiry, actual replacement Linux Worker. Not a new-provider SIGKILL test.',
            'cloud_access': False, 'credentials_persisted': False,
            'cleanup': 'Owned worker containers removed; synthetic rows/original files/core volumes retained; no SQL state patches'}
        self.local.write('integration-' + self.run_id + '.json', result)
        print(json.dumps({'evidence': str(self.local.directory / ('integration-' + self.run_id + '.json')), 'counts': result['counts']}), flush=True)

    def run(self, remaining_only=False):
        self.sections = 'focused_science_compat_after_result_envelope_test_fix' if remaining_only else 'full'
        try:
            self.setup()
            if not remaining_only:
                self.authorization_and_recovery()
            self.http_limits()
            self.science(include_first=remaining_only)
            self.isolation()
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
    parser.add_argument('--remaining-only', action='store_true')
    args = parser.parse_args()
    try:
        sys.exit(0 if Suite(args.runtime_dir).run(args.remaining_only) else 1)
    except Exception as error:
        print(json.dumps({'ok': False, 'error_type': type(error).__name__, 'code': 'PHASE4_INTEGRATION_FAILED'}))
        sys.exit(1)
