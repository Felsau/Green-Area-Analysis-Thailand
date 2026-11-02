"""Bounded local E2E: real Auth -> FastAPI -> SDK/PostgREST -> PostgreSQL.

Fixture budget: three new synthetic users, two datasets, four editions and four
jobs per run. Retain all rows. No signing-secret/environment/credential-file read.
Use only LocalT2's attested local SDK clients. Run on the idle synthetic queue.
Negative altered-claim JWTs are tampered signatures, NOT valid signed claims;
valid-signature expired/wrong-issuer fixtures are explicitly Not Tested here.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import logging
from pathlib import Path
import secrets
import sys
import time
from uuid import UUID, uuid4

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('t2_e2e_local', HERE / 't2_local.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class FixtureFailure(Exception):
    pass


class Suite:
    def __init__(self, root):
        self.local = module.LocalT2(root)
        self.run_id = str(uuid4())
        self.results, self.users, self.tokens, self.clients = [], {}, {}, {}
        self.jobs = set()
        self.created = {'datasets': 0, 'editions': 0}
        self.gate_changed = False
        self.client = self.gated_client = None
        self.started = time.monotonic()

    def record(self, name, passed, **safe):
        row = {'name': name, 'status': 'Pass' if passed else 'Fail', **safe}
        self.results.append(row)
        print(json.dumps(row), flush=True)
        return passed

    def sql(self, body, role='gis_owner'):
        if role not in ('gis_owner', 'gis_worker', 'postgres'):
            raise FixtureFailure()
        switch = '' if role == 'postgres' else 'SET LOCAL ROLE ' + role + ';'
        output = self.local.db.query('postgres', "BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='15s';"
            + switch + body + ';COMMIT;').stdout.strip()
        lines = [line for line in output.splitlines() if line.strip()]
        return json.loads(lines[-1]) if lines else None

    def request(self, method, path, *, actor='officer', body=None, key=True, token=None,
                client=None, headers=None, params=None, content=None):
        values = {}
        if token is not None:
            values['Authorization'] = 'Bearer ' + token
        elif actor is not None:
            values['Authorization'] = 'Bearer ' + self.tokens[actor]
        if key and method in ('POST', 'PATCH'):
            values['Idempotency-Key'] = str(uuid4()) if key is True else str(key)
        values.update(headers or {})
        options = {'headers': values}
        if body is not None:
            options['json'] = body
        if params is not None:
            options['params'] = params
        if content is not None:
            options['content'] = content
        return (client or self.client).request(method, path, **options)

    def expect(self, name, method, path, expected, *, predicate=None, required=False, **options):
        try:
            response = self.request(method, path, **options)
            passed = response.status_code == expected
            if passed and predicate is not None:
                passed = bool(predicate(response.json()))
            self.record(name, passed, expected_status=expected, actual_status=response.status_code)
            if required and not passed:
                raise FixtureFailure()
            return response
        except FixtureFailure:
            raise
        except Exception as error:
            self.record(name, False, error_type=type(error).__name__)
            if required:
                raise FixtureFailure() from None
            return None

    def setup(self):
        self.local.attest()
        state = self.sql("SELECT jsonb_build_object('active',(SELECT count(*) FROM gis.jobs WHERE state IN ('queued','running')),'gate',(SELECT activation_enabled FROM gis.environment))")
        if state['active'] or state['gate']:
            raise FixtureFailure()
        anon, service = self.local.local_keys()
        admin = self.local.client(service)
        for name in ('admin', 'officer', 'user'):
            email = 'gis-t2-' + name + '-' + self.run_id + '@example.invalid'
            password = secrets.token_urlsafe(30)
            metadata = {'display_name': 'T2 synthetic ' + name}
            if name == 'user':
                metadata.update({'role': 'admin', 'gis_officer': True})
            created = admin.auth.admin.create_user({'email': email, 'password': password,
                'email_confirm': True, 'user_metadata': metadata})
            self.users[name] = str(UUID(str(created.user.id)))
            login = self.local.client(anon)
            session = login.auth.sign_in_with_password({'email': email, 'password': password}).session
            if session is None:
                raise FixtureFailure()
            self.tokens[name] = session.access_token
            self.clients[name] = login
        # Only the exact new synthetic admin UUID is promoted, in the attested DB.
        self.sql("UPDATE public.profiles SET role='admin' WHERE id=" + module.t1.literal(self.users['admin']) + '::uuid', role='postgres')
        self.manifest = self.sql("SELECT manifest FROM gis.synthetic_fixtures WHERE id='ndvi-valid-v1'")
        if str(module.BACKEND) not in sys.path:
            sys.path.insert(0, str(module.BACKEND))
        from fastapi.testclient import TestClient
        from gis_app import create_app
        self.TestClient, self.create_app = TestClient, create_app
        self.client = TestClient(create_app(self.local.runtime(), rate_limit='10000/minute'), raise_server_exceptions=False)
        self.gated_client = TestClient(create_app(self.local.runtime(activation=True), rate_limit='10000/minute'), raise_server_exceptions=False)
        self.record('actual_local_auth_created_and_signed_in_three_synthetic_users', True)

    def free_dataset(self, title='T2 synthetic catalog'):
        value = self.sql("""SELECT jsonb_build_object('province',p.name_en,'data_year',y,'month',m,'kind','geotiff','purpose','ndvi')
FROM public.provinces p CROSS JOIN generate_series(1980,extract(year FROM clock_timestamp())::int) y
CROSS JOIN generate_series(0,12) m WHERE NOT EXISTS(SELECT 1 FROM gis.datasets d
 WHERE d.province=p.name_en AND d.data_year=y AND d.month=m AND d.kind='geotiff' AND d.purpose='ndvi')
ORDER BY (p.name_en='Bangkok Metropolis') DESC,p.name_en,y,m LIMIT 1""")
        if value is None:
            raise FixtureFailure()
        return {**value, 'title': title}

    def edition(self, dataset, name, manifest=None):
        if self.created['editions'] >= 4:
            raise FixtureFailure()
        response = self.expect(name, 'POST', '/gis/datasets/' + dataset['id'] + '/editions', 201,
            body={'manifest': manifest or self.manifest}, required=True)
        self.created['editions'] += 1
        return response.json()

    def enqueue(self, edition, name, key=True):
        if len(self.jobs) >= 4:
            raise FixtureFailure()
        response = self.expect(name, 'POST', '/gis/editions/' + edition['id'] + '/validation-jobs', 202,
            body={'expected_revision': edition['input_revision']}, key=key, required=True,
            predicate=lambda value: value['state'] == 'queued')
        value = response.json()
        self.jobs.add(value['id'])
        return value

    def worker(self, action, payload=None):
        encoded = module.t1.literal(json.dumps(payload or {}, separators=(',', ':')))
        return self.sql('SELECT public.gis_worker(' + module.t1.literal(action) + ',' + encoded + '::jsonb)', role='gis_worker')

    def claim(self, job):
        if job not in self.jobs:
            raise FixtureFailure()
        lease = self.worker('claim', {'worker_id': str(uuid4())})
        if not lease or lease.get('job_id') != job:
            raise FixtureFailure()
        return {key: lease[key] for key in ('job_id', 'worker_id', 'lease_token')}

    def complete_fixture(self, job):
        # Explicit manual SQL fixture setup; never API auto-completion or a worker.
        self.worker('complete', {**self.claim(job), 'report': {'valid': True,
            'fixture_id': 'ndvi-valid-v1', 'checks': ['synthetic_fixture_match', 'source_hash_match']}})

    def fail_fixture(self, job, code='invalid_data'):
        self.worker('fail', {**self.claim(job), 'error_code': code})

    def auth_cases(self):
        self.expect('missing_jwt_401', 'GET', '/gis/me', 401, actor=None)
        self.expect('malformed_jwt_401', 'GET', '/gis/me', 401, actor=None, token='not-valid-jwt')
        self.expect('valid_user_metadata_is_not_admin', 'GET', '/gis/me', 200, actor='user',
            predicate=lambda value: not value['admin'] and not value['officer'] and value['capabilities'] == [])
        self.expect('valid_admin_live_profile', 'GET', '/gis/me', 200, actor='admin', predicate=lambda value: value['admin'] is True)
        import jwt
        original = self.tokens['user'].split('.')
        claims = jwt.decode(self.tokens['user'], options={'verify_signature': False})
        now = int(time.time())
        changes = {
            'tampered_expired_claim_401': {**claims, 'iat': now-120, 'exp': now-60},
            'tampered_wrong_issuer_401': {**claims, 'iss': 'https://wrong-issuer.invalid/auth/v1'},
            'tampered_wrong_audience_401': {**claims, 'aud': 'service_role'},
            'tampered_wrong_role_401': {**claims, 'role': 'service_role'},
            'tampered_future_iat_401': {**claims, 'iat': now+600, 'exp': now+3600},
            'tampered_missing_exp_401': {key: value for key, value in claims.items() if key != 'exp'},
        }
        for name, value in changes.items():
            raw = json.dumps(value, separators=(',', ':')).encode()
            encoded = base64.urlsafe_b64encode(raw).decode().rstrip('=')
            token = original[0] + '.' + encoded + '.' + original[2]
            self.expect(name, 'GET', '/gis/me', 401, actor=None, token=token)
        invalid = jwt.encode(claims, secrets.token_urlsafe(40), algorithm='HS256')
        self.expect('invalid_signature_rejected_by_real_auth', 'GET', '/gis/me', 401, actor=None, token=invalid)
        self.expect('unsigned_jwt_401', 'GET', '/gis/me', 401, actor=None, token=jwt.encode(claims, '', algorithm='none'))
        self.expect('legacy_admin_header_not_authentication', 'GET', '/gis/me', 401, actor=None, headers={'X-Admin-Token': 'synthetic-untrusted'})
        self.expect('normal_user_catalog_forbidden', 'GET', '/gis/datasets', 403, actor='user')
        self.expect('normal_user_create_forbidden', 'POST', '/gis/datasets', 403, actor='user', body=self.free_dataset())
        self.expect('metadata_admin_cannot_self_grant', 'POST', '/gis/officers', 403, actor='user',
            body={'user_id': self.users['user'], 'reason': 'synthetic denied self grant'})
        self.expect('legacy_header_cannot_upgrade_user', 'POST', '/gis/officers', 403, actor='user',
            headers={'X-Admin-Token': 'synthetic-untrusted'}, body={'user_id': self.users['user'], 'reason': 'synthetic denied header'})
        self.expect('admin_grants_officer', 'POST', '/gis/officers', 200, actor='admin', required=True,
            body={'user_id': self.users['officer'], 'reason': 'T2 synthetic grant'})
        self.expect('officer_live_database_capabilities', 'GET', '/gis/me', 200,
            predicate=lambda value: value['officer'] and not value['admin'] and 'enqueue_validation' in value['capabilities'])
        self.expect('officer_cannot_grant', 'POST', '/gis/officers', 403, body={'user_id': self.users['user'], 'reason': 'synthetic denied grant'})
        self.expect('officer_cannot_list_admin_grants', 'GET', '/gis/officers', 403)
        self.expect('officer_cannot_revoke', 'POST', '/gis/officers/' + self.users['officer'] + '/revocation', 403, body={'reason': 'synthetic denied revoke'})
        for name, payload in [('gis_readiness', {}), ('gis_read', {'p_actor': self.users['admin'], 'p_kind': 'me', 'p_payload': {}}),
            ('gis_command', {'p_actor': self.users['admin'], 'p_request_id': str(uuid4()), 'p_operation': 'grant_officer',
                'p_payload': {'user_id': self.users['user'], 'reason': 'denied direct call'}, 'p_backend_sandbox': False})]:
            try:
                self.clients['user'].rpc(name, payload).execute()
                self.record('direct_authenticated_' + name + '_denied', False)
            except Exception as error:
                self.record('direct_authenticated_' + name + '_denied', str(getattr(error, 'code', '')) == '42501')
        try:
            self.clients['user'].schema('gis').table('datasets').select('id').execute()
            self.record('direct_private_schema_access_denied', False)
        except Exception as error:
            self.record('direct_private_schema_access_denied', str(getattr(error, 'code', '')) in ('42501', 'PGRST106', 'PGRST205'))

    def catalog_cases(self):
        self.expect('province_reference_real_rpc', 'GET', '/gis/provinces', 200,
            predicate=lambda value: len(value['data']) == 77)
        payload = self.free_dataset()
        self.dataset = self.expect('dataset_create', 'POST', '/gis/datasets', 201, body=payload, required=True).json()
        self.created['datasets'] += 1
        uri = '/gis/datasets/' + self.dataset['id']
        self.expect('dataset_detail_redacted', 'GET', uri, 200,
            predicate=lambda value: value['id'] == self.dataset['id'] and not any(key in value for key in ('created_by', 'actor_id', 'lease_token')))
        self.expect('duplicate_dataset_identity_conflict', 'POST', '/gis/datasets', 409, body=payload)
        self.expect('missing_idempotency_key_422', 'POST', '/gis/datasets', 422, body=payload, key=False)
        self.expect('malformed_idempotency_key_422', 'POST', '/gis/datasets', 422, body=payload, key='bad-key')
        for key, value in [('actor_id', self.users['admin']), ('role', 'admin'), ('state', 'validated')]:
            self.expect('body_' + key + '_forgery_rejected', 'POST', '/gis/datasets', 422, body={**payload, key: value})
        self.expect('strict_boolean_revision_rejected', 'PATCH', uri, 422, body={'expected_revision': True, 'title': 'invalid'})
        self.expect('stale_dataset_revision_409', 'PATCH', uri, 409, body={'expected_revision': 99, 'title': 'stale'})
        key = str(uuid4())
        edit = {'expected_revision': self.dataset['revision'], 'title': 'T2 edited title'}
        self.dataset = self.expect('dataset_title_update', 'PATCH', uri, 200, body=edit, key=key, required=True).json()
        self.expect('receipt_replay_precedes_stale_revision', 'PATCH', uri, 200, body=edit, key=key,
            predicate=lambda value: value['revision'] == self.dataset['revision'])
        self.expect('idempotency_changed_payload_conflict', 'PATCH', uri, 409, body={**edit, 'title': 'different'}, key=key)
        unknown = str(uuid4())
        for name, path in [('dataset', '/gis/datasets/'), ('edition', '/gis/editions/'), ('job', '/gis/jobs/')]:
            self.expect('missing_' + name + '_404', 'GET', path + unknown, 404)
        for name, path in [('editions', '/gis/datasets/' + unknown + '/editions'), ('history', '/gis/editions/' + unknown + '/history'),
            ('attempts', '/gis/jobs/' + unknown + '/attempts'), ('result', '/gis/jobs/' + unknown + '/result')]:
            self.expect('missing_parent_' + name + '_404', 'GET', path, 404)
        self.expect('invalid_uuid_path_422', 'GET', '/gis/jobs/not-uuid', 422)
        self.expect('unknown_query_key_422', 'GET', '/gis/datasets', 422, params={'actor_id': self.users['admin']})
        self.expect('bounded_page_limit_422', 'GET', '/gis/datasets', 422, params={'limit': 101})
        self.expect('malformed_cursor_422', 'GET', '/gis/datasets', 422, params={'cursor': 'invalid-cursor'})
        filters = {key: payload[key] for key in ('province', 'data_year', 'month', 'kind', 'purpose')}
        self.expect('datasets_exact_identity_filters', 'GET', '/gis/datasets', 200, params=filters,
            predicate=lambda value: len(value['data']) == 1 and value['data'][0]['id'] == self.dataset['id'])
        page = self.expect('dataset_cursor_first_page', 'GET', '/gis/datasets', 200, params={'limit': 1}, required=True).json()
        if page.get('next_cursor'):
            self.expect('dataset_cursor_next_page_no_duplicate', 'GET', '/gis/datasets', 200,
                params={'limit': 1, 'cursor': page['next_cursor']}, predicate=lambda value: bool(value['data']) and value['data'][0]['id'] != page['data'][0]['id'])
        self.main_edition = self.edition(self.dataset, 'edition_create')
        ep = '/gis/editions/' + self.main_edition['id']
        self.expect('edition_detail', 'GET', ep, 200, predicate=lambda value: value['state'] == 'draft')
        self.expect('edition_parent_list', 'GET', uri + '/editions', 200,
            predicate=lambda value: any(row['id'] == self.main_edition['id'] for row in value['data']))
        edit = {'expected_revision': self.main_edition['input_revision'], 'manifest': self.manifest}
        self.main_edition = self.expect('draft_edition_update', 'PATCH', ep, 200, body=edit, required=True).json()
        self.expect('stale_draft_revision_409', 'PATCH', ep, 409, body=edit)
        self.expect('remote_manifest_url_422', 'PATCH', ep, 422,
            body={'expected_revision': self.main_edition['input_revision'], 'manifest': {**self.manifest, 'url': 'https://example.invalid/file.tif'}})
        self.expect('unknown_fixture_manifest_422', 'POST', uri + '/editions', 422, body={'manifest': {**self.manifest, 'fixture_id': 'unknown-fixture'}})
        self.expect('nonfinite_manifest_422', 'POST', uri + '/editions', 422,
            content=json.dumps({'manifest': {**self.manifest, 'resolution': float('nan')}}), headers={'Content-Type': 'application/json'})
        self.clone = self.expect('clone_edition_new_draft', 'POST', ep + '/clone', 201,
            body={'expected_revision': self.main_edition['input_revision']}, required=True).json()
        self.created['editions'] += 1
        self.expect('edition_history_real_audit', 'GET', ep + '/history', 200,
            predicate=lambda value: any(row['operation'] == 'edit_edition' for row in value['data']))
        real = {key: value for key, value in self.manifest.items() if key != 'fixture_id'}
        real.update({'provider': 'real', 'sha256': 'a' * 64, 'provenance': 'T2 metadata only'})
        metadata = self.edition(self.dataset, 'real_metadata_draft_only', real)
        self.expect('real_metadata_cannot_enqueue', 'POST', '/gis/editions/' + metadata['id'] + '/validation-jobs', 422,
            body={'expected_revision': metadata['input_revision']})
        self.expect('hard_delete_not_exposed', 'DELETE', uri, 405)

    def concurrent_case(self):
        payload, key = self.free_dataset('T2 concurrent create'), str(uuid4())
        if self.created['datasets'] >= 2:
            raise FixtureFailure()
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                replies = list(pool.map(lambda _: self.request('POST', '/gis/datasets', body=payload, key=key), range(2)))
            passed = all(reply.status_code == 201 for reply in replies) and replies[0].json() == replies[1].json()
            self.record('concurrent_idempotency_same_actor_one_effect', passed)
            if passed:
                self.created['datasets'] += 1
                identity = replies[0].json()['id']
                counts = self.sql("SELECT jsonb_build_object('datasets',(SELECT count(*) FROM gis.datasets WHERE id=" + module.t1.literal(identity) +
                    "::uuid),'receipts',(SELECT count(*) FROM gis.receipts WHERE actor_id=" + module.t1.literal(self.users['officer']) +
                    '::uuid AND request_id=' + module.t1.literal(key) + "::uuid),'audits',(SELECT count(*) FROM gis.audit WHERE dataset_id=" + module.t1.literal(identity) + "::uuid AND operation='create_dataset'))")
                self.record('concurrent_single_row_receipt_audit', counts == {'datasets': 1, 'receipts': 1, 'audits': 1})
        except Exception as error:
            self.record('concurrent_idempotency_same_actor_one_effect', False, error_type=type(error).__name__)

    def jobs_cases(self):
        key = str(uuid4())
        job = self.enqueue(self.main_edition, 'enqueue_real_queued_job', key)
        ep = '/gis/editions/' + self.main_edition['id']
        jp = '/gis/jobs/' + job['id']
        rev = {'expected_revision': self.main_edition['input_revision']}
        self.expect('enqueue_idempotent_202', 'POST', ep + '/validation-jobs', 202, body=rev, key=key, predicate=lambda value: value['id'] == job['id'])
        self.expect('enqueue_semantic_dedup_202', 'POST', ep + '/validation-jobs', 202, body=rev, predicate=lambda value: value['id'] == job['id'])
        self.expect('queued_job_never_fake_succeeded', 'GET', jp, 200, predicate=lambda value: value['state'] == 'queued' and value['result'] is None)
        self.expect('pending_result_is_null', 'GET', jp + '/result', 200, predicate=lambda value: value['state'] == 'queued' and value['result'] is None)
        self.expect('pending_attempt_history_empty', 'GET', jp + '/attempts', 200, predicate=lambda value: value['data'] == [])
        self.expect('job_filter_by_parent_and_state', 'GET', '/gis/jobs', 200,
            params={'state': 'queued', 'dataset_id': self.dataset['id'], 'edition_id': self.main_edition['id']},
            predicate=lambda value: len(value['data']) == 1 and value['data'][0]['id'] == job['id'])
        self.expect('validating_input_edit_conflict', 'PATCH', ep, 409, body={**rev, 'manifest': self.manifest})
        self.expect('queued_retry_ineligible_409', 'POST', jp + '/retry', 409,
            body={**rev, 'input_hash': self.main_edition['input_hash'], 'reason': 'T2 denied queued retry'})
        self.complete_fixture(job['id'])
        self.record('manual_sql_success_fixture_not_api_or_python_worker', True)
        self.expect('stored_successful_result_read', 'GET', jp + '/result', 200,
            predicate=lambda value: value['state'] == 'succeeded' and value['result']['report']['valid'] is True)
        self.expect('job_detail_has_real_stored_result', 'GET', jp, 200, predicate=lambda value: value['result'] is not None)
        self.expect('attempts_redact_lease_and_worker', 'GET', jp + '/attempts', 200,
            predicate=lambda value: len(value['data']) == 1 and not any(key in value['data'][0] for key in ('lease_token', 'worker_id', 'actor_id')))
        self.expect('terminal_enqueue_semantic_dedup_200', 'POST', ep + '/validation-jobs', 200, body=rev, predicate=lambda value: value['id'] == job['id'])
        self.expect('validated_input_edit_conflict', 'PATCH', ep, 409, body={**rev, 'manifest': self.manifest})
        retry = self.enqueue(self.clone, 'retry_fixture_enqueue')
        for attempt in range(3):
            if attempt:
                self.sql('UPDATE gis.jobs SET available_at=clock_timestamp() WHERE id=' + module.t1.literal(retry['id']) + '::uuid')
            self.fail_fixture(retry['id'], 'transient')
        path = '/gis/jobs/' + retry['id'] + '/retry'
        payload = {'expected_revision': self.clone['input_revision'], 'input_hash': self.clone['input_hash'], 'reason': 'T2 bounded retry'}
        self.expect('retry_stale_hash_409', 'POST', path, 409, body={**payload, 'input_hash': '0' * 64})
        self.expect('retry_stale_revision_409', 'POST', path, 409, body={**payload, 'expected_revision': 99})
        key = str(uuid4())
        child = self.expect('explicit_retry_one_child_202', 'POST', path, 202, body=payload, key=key, required=True).json()
        self.jobs.add(child['id'])
        self.expect('explicit_retry_key_replays_202', 'POST', path, 202, body=payload, key=key, predicate=lambda value: value['id'] == child['id'])
        self.expect('explicit_retry_budget_conflict', 'POST', path, 409, body=payload)
        self.fail_fixture(child['id'])
        self.expect('failed_job_safe_error_code', 'GET', '/gis/jobs/' + child['id'] + '/result', 200,
            predicate=lambda value: value['state'] == 'failed' and value['result'] is None and value['error_code'] == 'invalid_data')
        self.expect('retry_child_chain_forbidden', 'POST', '/gis/jobs/' + child['id'] + '/retry', 409, body=payload)

    def activation_cases(self):
        dp = '/gis/datasets/' + self.dataset['id']
        data = self.expect('activation_fixture_current_dataset', 'GET', dp, 200, required=True).json()
        payload = {'edition_id': self.main_edition['id'], 'expected_revision': data['revision'],
            'expected_active_edition_id': None, 'reason': 'T2 synthetic activation'}
        self.expect('officer_cannot_activate', 'POST', dp + '/activation', 403, body=payload)
        self.expect('default_activation_gates_503', 'POST', dp + '/activation', 503, actor='admin', body=payload)
        self.expect('backend_on_database_gate_off_503', 'POST', dp + '/activation', 503, actor='admin', body=payload, client=self.gated_client)
        self.sql('UPDATE gis.environment SET activation_enabled=true')
        self.gate_changed = True
        self.expect('database_on_backend_gate_off_503', 'POST', dp + '/activation', 503, actor='admin', body=payload)
        active = self.expect('admin_synthetic_activation', 'POST', dp + '/activation', 200, actor='admin', body=payload, client=self.gated_client, required=True).json()
        self.expect('activation_stale_revision_409', 'POST', dp + '/activation', 409, actor='admin', body=payload, client=self.gated_client)
        second = self.edition(data, 'second_edition_for_rollback')
        second_job = self.enqueue(second, 'second_validation_fixture_enqueue')
        self.complete_fixture(second_job['id'])
        payload = {'edition_id': second['id'], 'expected_revision': active['revision'],
            'expected_active_edition_id': self.main_edition['id'], 'reason': 'T2 next synthetic edition'}
        self.expect('rollback_requires_prior_activation_history', 'POST', dp + '/rollback', 409, actor='admin', body=payload, client=self.gated_client)
        newer = self.expect('activate_new_preserves_old_edition', 'POST', dp + '/activation', 200, actor='admin', body=payload, client=self.gated_client, required=True).json()
        back = {'edition_id': self.main_edition['id'], 'expected_revision': newer['revision'],
            'expected_active_edition_id': second['id'], 'reason': 'T2 transactional rollback'}
        restored = self.expect('rollback_transactional_pointer', 'POST', dp + '/rollback', 200, actor='admin', body=back,
            client=self.gated_client, required=True, predicate=lambda value: value['active_edition_id'] == self.main_edition['id']).json()
        withdraw = {'expected_revision': self.main_edition['input_revision'], 'expected_dataset_revision': restored['revision'],
            'expected_active_edition_id': self.main_edition['id'], 'replacement_edition_id': None, 'reason': 'T2 explicitly clear pointer'}
        ep = '/gis/editions/' + self.main_edition['id'] + '/withdrawal'
        self.expect('officer_cannot_withdraw', 'POST', ep, 403, body=withdraw, client=self.gated_client)
        self.expect('admin_withdraw_clears_pointer', 'POST', ep, 200, actor='admin', body=withdraw, client=self.gated_client,
            predicate=lambda value: value['edition']['state'] == 'withdrawn' and value['dataset']['active_edition_id'] is None)
        self.sql('UPDATE gis.environment SET activation_enabled=false')
        self.gate_changed = False

    def tail_cases(self):
        self.expect('admin_grant_second_officer_for_page', 'POST', '/gis/officers', 200, actor='admin',
            body={'user_id': self.users['user'], 'reason': 'T2 temporary pagination grant'})
        page = self.expect('officer_cursor_first_page', 'GET', '/gis/officers', 200, actor='admin', params={'limit': 1}, required=True).json()
        self.record('officer_page_is_bounded_with_cursor', page['has_more'] is True and isinstance(page['next_cursor'], str))
        if page.get('next_cursor'):
            self.expect('officer_next_page_no_duplicate', 'GET', '/gis/officers', 200, actor='admin',
                params={'limit': 1, 'cursor': page['next_cursor']}, predicate=lambda value: bool(value['data']) and value['data'][0]['user_id'] != page['data'][0]['user_id'])
        self.expect('officer_dto_no_email_or_grantor', 'GET', '/gis/officers', 200, actor='admin',
            predicate=lambda value: all(set(row) <= {'id', 'user_id', 'created_at'} for row in value['data']))
        self.expect('admin_revoke_temporary_user_grant', 'POST', '/gis/officers/' + self.users['user'] + '/revocation', 200,
            actor='admin', body={'reason': 'T2 restore ordinary user'})
        self.expect('ordinary_user_rights_restored', 'GET', '/gis/datasets', 403, actor='user')
        dp = '/gis/datasets/' + self.dataset['id']
        current = self.expect('read_revision_before_officer_revoke', 'GET', dp, 200, required=True).json()
        body = {'expected_revision': current['revision'], 'title': 'T2 receipt before revocation'}
        key = str(uuid4())
        self.expect('create_receipt_before_revocation', 'PATCH', dp, 200, body=body, key=key, required=True)
        self.expect('admin_revokes_officer', 'POST', '/gis/officers/' + self.users['officer'] + '/revocation', 200,
            actor='admin', body={'reason': 'T2 permission revocation'}, required=True)
        self.expect('revoked_officer_me_updated', 'GET', '/gis/me', 200, predicate=lambda value: not value['officer'] and value['capabilities'] == [])
        self.expect('revoked_officer_catalog_denied', 'GET', '/gis/datasets', 403)
        self.expect('revoked_officer_receipt_replay_denied', 'PATCH', dp, 403, body=body, key=key)
        response = self.request('OPTIONS', '/gis/datasets', actor=None, headers={'Origin': 'http://localhost:3000',
            'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type,idempotency-key'})
        self.record('cors_local_origin_required_headers', response.status_code == 200 and response.headers.get('access-control-allow-origin') == 'http://localhost:3000')
        response = self.request('OPTIONS', '/gis/datasets', actor=None, headers={'Origin': 'https://untrusted.invalid',
            'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,idempotency-key'})
        self.record('cors_untrusted_origin_denied', 'access-control-allow-origin' not in response.headers)
        response = self.request('OPTIONS', '/gis/datasets', actor=None, headers={'Origin': 'http://localhost:3000',
            'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'x-admin-token'})
        self.record('cors_legacy_admin_header_denied', response.status_code == 400)
        self.expect('oversized_body_rejected', 'POST', '/gis/datasets', 422, actor=None, content='x' * 65537, headers={'Content-Type': 'application/json'})
        disabled = self.TestClient(self.create_app(), raise_server_exceptions=False)
        self.expect('default_disabled_app_503', 'GET', '/gis/me', 503, actor='admin', client=disabled)
        disabled.close()

    def cleanup(self):
        try:
            if self.gate_changed:
                self.sql('UPDATE gis.environment SET activation_enabled=false')
                self.gate_changed = False
            # Claim order is queue order, not UUID order. Refuse to interfere if
            # another producer has added work to this isolated test queue.
            active = self.sql("SELECT COALESCE(jsonb_agg(id),'[]'::jsonb) FROM gis.jobs WHERE state IN ('queued','running')")
            if set(active or []) - self.jobs:
                raise FixtureFailure()
            for job in sorted(self.jobs):
                self.sql("UPDATE gis.jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=" + module.t1.literal(job) + "::uuid AND state='running'")
            if self.jobs:
                self.worker('recover')
            for _ in range(len(self.jobs)):
                active = self.sql("SELECT COALESCE(jsonb_agg(id),'[]'::jsonb) FROM gis.jobs WHERE state IN ('queued','running')")
                if not active:
                    break
                if set(active) - self.jobs:
                    raise FixtureFailure()
                ids = ','.join(module.t1.literal(job) + '::uuid' for job in sorted(self.jobs))
                self.sql('UPDATE gis.jobs SET available_at=clock_timestamp() WHERE id IN (' + ids + ") AND state='queued'")
                lease = self.worker('claim', {'worker_id': str(uuid4())})
                if not lease or lease['job_id'] not in self.jobs:
                    raise FixtureFailure()
                self.worker('fail', {key: lease[key] for key in ('job_id', 'worker_id', 'lease_token')} | {'error_code': 'invalid_data'})
            if self.jobs:
                ids = ','.join(module.t1.literal(job) + '::uuid' for job in sorted(self.jobs))
                state = self.sql("SELECT jsonb_build_object('active',(SELECT count(*) FROM gis.jobs WHERE id IN (" + ids + ") AND state IN ('queued','running')),'gate',(SELECT activation_enabled FROM gis.environment))")
                self.record('owned_jobs_terminal_and_gate_restored', state['active'] == 0 and not state['gate'])
        except Exception as error:
            self.record('bounded_fixture_cleanup', False, error_type=type(error).__name__)
        for client in (self.client, self.gated_client):
            if client is not None:
                client.close()

    def run(self):
        try:
            self.setup()
            self.auth_cases()
            self.catalog_cases()
            self.concurrent_case()
            self.jobs_cases()
            self.activation_cases()
            self.tail_cases()
        except Exception as error:
            self.record('integration_dependency_failed', False, error_type=type(error).__name__)
        finally:
            self.cleanup()
        not_tested = ['Valid-signature expired/wrong-issuer/wrong-audience JWT integration fixtures (no signing-secret access)',
            'Actual Python Worker process lifecycle (T3)', 'Native GIS/scientific file validation',
            'Cloud/GEE/production/staging', 'Browser GIS UI (T4)']
        report = {'run_id': self.run_id, 'type': 'actual_local_supabase_e2e', 'results': self.results,
            'counts': {state: sum(row['status'] == state for row in self.results) for state in ('Pass', 'Fail')},
            'duration_seconds': round(time.monotonic()-self.started, 3), 'synthetic_users_retained': len(self.users),
            'synthetic_objects_retained': {**self.created, 'jobs': len(self.jobs)},
            'manual_sql_worker_calls_are_fixture_setup_only': True, 'signing_secret_accessed': False,
            'not_tested': not_tested, 'credentials_written_or_reported': False,
            'path': 'TestClient -> GISRuntime -> real Auth/PostgREST SDK -> local PostgreSQL'}
        filename = 'integration-' + self.run_id + '.json'
        self.local.write(filename, report)
        print(json.dumps({'report': filename, 'counts': report['counts']}), flush=True)
        return 1 if report['counts']['Fail'] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir', type=Path, required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    return Suite(args.runtime_dir).run()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print(json.dumps({'ok': False, 'code': 'T2_INTEGRATION_SETUP_FAILED', 'error_type': type(error).__name__}))
        sys.exit(1)
