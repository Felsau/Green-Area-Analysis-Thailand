"""A6.2 local SQL/Auth/RPC integration, not API/daemon/native/GEE E2E."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import secrets
import socket
import sys
import time
from uuid import uuid4

HERE = Path(__file__).resolve().parent
s = importlib.util.spec_from_file_location('a62_checks_operator', HERE / 'gee_mock_local.py')
p = importlib.util.module_from_spec(s)
sys.modules[s.name] = p
s.loader.exec_module(p)
sys.path.insert(0, str(p.REPO / 'green-area-backend'))
from gis_worker.gee_adapter import LegacyBindings, LegacyReturn, SafeComputeAdapter
from gis_worker.gee_contracts import LiveRequest, Observation, Statistics, geometry_digest, method_for
from gis_worker.gee_mock_queue import MockQueueHooks, mock_case, report

GEOMETRY = {'type': 'Polygon', 'coordinates': [[[100, 13], [101, 13], [101, 14], [100, 13]]]}


def fixture(run, *, product='ndvi', month=0, scenario='candidate'):
    request = LiveRequest(request_id=uuid4(), input_revision=1, product=product,
        boundary={'province': 'Bangkok Metropolis', 'boundary_version': 'a62-mock-' + run,
                  'geometry_sha256': geometry_digest(GEOMETRY)},
        period={'year': 2025, 'month': month, 'start': date(2025, month or 1, 1),
                'end_exclusive': date(2026, 1, 1) if month in (0, 12) else date(2025, month + 1, 1)},
        method_version=method_for(product, month).version)
    empty = scenario == 'no_data'
    stats = Statistics() if empty else Statistics(mean=0.25, min=0.2, max=0.3) if product == 'ndvi' else Statistics(mean=30.0, min=20.0, max=40.0)
    method = method_for(product, month)
    obs = Observation(request_hash=request.request_hash(), geometry_sha256=request.boundary.geometry_sha256,
        product=product, method_version=method.version, period=request.period, collections=method.collections,
        scenes=({'collection': method.collections[0], 'image_id': method.collections[0] + '/A62_MOCK', 'acquired': request.period.start},),
        observations_complete=scenario != 'incomplete', valid_pixels=0 if empty else 2, raw_statistics=stats)
    if month:
        payload = [{'month_num': n, 'image_count': 1 if n == month else 0, product: stats.mean if n == month else None} for n in range(1, 13)]
    elif product == 'ndvi':
        payload = dict(zip(('ndvi_mean', 'ndvi_min', 'ndvi_max'), (stats.mean or 0, stats.min or 0, stats.max or 0)))
    else:
        payload = (stats.mean or 0, stats.min or 0, stats.max or 0)
    fn = lambda *_: LegacyReturn(payload, obs)
    adapter = SafeComputeAdapter(LegacyBindings(fn, fn, fn, fn), as_of=date(2026, 1, 1))
    output = adapter.compute(request, GEOMETRY, expected_request_hash=request.request_hash())
    return mock_case(request, GEOMETRY, output), output


def check(local):
    local.proof_a62()
    run = uuid4().hex[:12]
    rows = []
    source_start = {str(x.relative_to(p.REPO)).replace('\\', '/'): hashlib.sha256(x.read_bytes()).hexdigest()
                    for x in [p.MIGRATION, HERE / 'gee_mock_local.py', Path(__file__), p.REPO / 'green-area-backend/gis_worker/gee_mock_queue.py']}
    (local.output / ('checks-' + run + '-source.json')).write_text(json.dumps(source_start, indent=2), encoding='utf-8')
    def record(name, passed):
        row = {'name': name, 'status': 'Pass' if passed else 'Fail'}
        rows.append(row)
        with (local.output / ('checks-' + run + '.jsonl')).open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row) + '\n')
        print(json.dumps(row), flush=True)
        if not passed:
            raise AssertionError(name)
    def denied(name, call, codes=('P0001', '42501', 'PGRST106', 'PGRST205', '23514')):
        try:
            call()
        except Exception as error:
            code = str(getattr(error, 'code', ''))
            record(name, code in codes)
        else:
            record(name, False)
    def sql_denied(name, body):
        value = local.sql(body, check=False)
        record(name, value.returncode != 0 and 'GIS_' in value.stderr)
    def wait(predicate, timeout=90):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            value = predicate()
            if value:
                return value
            time.sleep(1)
        raise RuntimeError('A62_LOCAL_WAIT_EXPIRED')
    quote = p.m.t2.t1.literal
    anon, service = local.local_keys()
    operator = local.client(service)
    def user(role):
        password = secrets.token_urlsafe(30)
        email = 'a62-' + uuid4().hex + '@example.invalid'
        created = operator.auth.admin.create_user({'email': email, 'password': password,
                                                  'email_confirm': True, 'role': role})
        client = local.client(anon)
        session = client.auth.sign_in_with_password({'email': email, 'password': password}).session
        if session is None:
            raise RuntimeError('A62_LOCAL_AUTH_REQUIRED')
        return str(created.user.id), client
    officer, normal = user('authenticated')
    # Only this new synthetic account; no old profile or privilege is changed.
    local.sql('INSERT INTO gis.officers(user_id) VALUES(' + quote(officer) + ')')
    workers = [user('gis_gee_mock_worker') for _ in range(2)]
    def hooks(identity):
        subject, client = identity
        return MockQueueHooks(lambda name, body: client.rpc(name, body).execute().data,
            subject=subject, runtime_instance=local.db.instance, baseline_fingerprint=p.m.t2.t1.legacy_fingerprint())
    a, b = map(hooks, workers)
    record('actual_gotrue_jwt_selects_separate_mock_worker_role', a.readiness()['subject'] == workers[0][0] and b.readiness()['subject'] == workers[1][0])
    record('normal_auth_account_is_not_a_worker', normal.auth.get_user().user.role == 'authenticated')
    denied('normal_user_cannot_claim_mock_jobs', lambda: normal.rpc('gis_gee_mock_worker', {'p_action': 'claim', 'p_payload': {}}).execute())
    worker_client = workers[0][1]
    for name, payload in (
        ('gis_processing_worker', {'p_action': 'claim', 'p_payload': {}}),
        ('gis_worker_v2', {'p_action': 'claim', 'p_payload': {}}),
        ('gis_gee_mock_command', {'p_actor': officer, 'p_request_id': str(uuid4()), 'p_operation': 'create', 'p_payload': {}, 'p_backend_mock': True}),
        ('gis_command', {'p_actor': officer, 'p_request_id': str(uuid4()), 'p_operation': 'grant_officer', 'p_payload': {}, 'p_backend_sandbox': False})):
        denied('worker_denied_' + name, lambda n=name, v=payload: worker_client.rpc(n, v).execute())
    denied('worker_denied_private_candidate_table', lambda: worker_client.schema('gis').table('gee_candidates').select('*').execute())
    denied('worker_denied_legacy_cache_write', lambda: worker_client.table('ndvi_annual').update({'ndvi_mean': 0}).eq('id', 0).neq('id', 0).execute())
    denied('worker_payload_identity_is_not_authority', lambda: a.call('claim', {'worker_id': workers[1][0]}))
    denied('worker_payload_actor_rejected', lambda: a.call('claim', {'actor': officer}))
    for trigger_name in ('handle_new_user', 'set_profiles_updated_at'):
        denied('legacy_trigger_not_exposed_as_rpc_' + trigger_name,
               lambda n=trigger_name: worker_client.rpc(n, {}).execute(), codes=('PGRST202',))

    for db in p.DATABASES:
        state = local.sql("SELECT jsonb_build_object('tables',(SELECT jsonb_agg(jsonb_build_array(c.relname,c.relrowsecurity,c.relforcerowsecurity,has_table_privilege('gis_gee_mock_worker',c.oid,'SELECT,INSERT,UPDATE,DELETE'))) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='gis' AND c.relname IN ('gee_mock_cases','gee_mock_requests','gee_candidates')),'privileged',(SELECT rolsuper OR rolbypassrls OR rolcanlogin OR rolcreatedb OR rolcreaterole OR rolreplication OR rolinherit FROM pg_roles WHERE rolname='gis_gee_mock_worker'),'rpc',(SELECT jsonb_agg(p.proname ORDER BY p.proname) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prorettype<>'trigger'::regtype AND has_function_privilege('gis_gee_mock_worker',p.oid,'EXECUTE')))", db, read_only=True)
        record(db + '_forced_rls_no_direct_table_privileges', len(state['tables']) == 3 and all(x[1:] == [True, True, False] for x in state['tables']))
        record(db + '_worker_least_privilege_rpc_and_role', state['privileged'] is False and state['rpc'] == ['gis_gee_mock_readiness', 'gis_gee_mock_worker'])

    def seed(month=0, scenario='candidate', product='ndvi'):
        value, output = fixture(run, month=month, scenario=scenario, product=product)
        case = local.sql('INSERT INTO gis.gee_mock_cases(value) VALUES(' + quote(json.dumps(value)) + '::jsonb) RETURNING to_jsonb(id)')
        return case, output
    def enqueue(case, key=None):
        return operator.rpc('gis_gee_mock_command', {'p_actor': officer, 'p_request_id': key or str(uuid4()),
            'p_operation': 'create', 'p_payload': {'case_id': case}, 'p_backend_mock': True}).execute().data
    def state(job_id):
        return operator.rpc('gis_gee_mock_read', {'p_actor': officer, 'p_job': job_id}).execute().data

    case, output = seed()
    key = str(uuid4())
    created = enqueue(case, key)
    job_id = created['body']['job_id']
    record('create_idempotency_receipt_replays_same_job', enqueue(case, key)['body'] == created['body'])
    record('new_idempotency_key_does_not_duplicate_case_job', enqueue(case)['body'] == created['body'])
    denied('command_cannot_forge_actor_in_payload', lambda: operator.rpc('gis_gee_mock_command', {'p_actor': officer, 'p_request_id': str(uuid4()), 'p_operation': 'create', 'p_payload': {'case_id': case, 'actor': officer}, 'p_backend_mock': True}).execute())
    denied('internal_command_requires_explicit_mock_gate', lambda: operator.rpc('gis_gee_mock_command', {'p_actor': officer, 'p_request_id': str(uuid4()), 'p_operation': 'create', 'p_payload': {'case_id': case}, 'p_backend_mock': False}).execute())
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda worker: worker.call('claim')['job'], (a, b)))
    record('concurrent_claims_take_job_once', sum(j is not None for j in claims) == 1)
    winner_index = 0 if claims[0] else 1
    winner, other = (a, b) if winner_index == 0 else (b, a)
    job = claims[winner_index]
    record('claim_bound_to_request_and_geometry', job['id'] == job_id and job['request']['mode'] == 'live_gee' and job['semantic_request_sha256'] == output.content.request_hash)
    good = report(job, output)
    lease = {'job_id': job_id, 'lease_token': job['lease_token']}
    denied('wrong_worker_subject_cannot_complete', lambda: other.call('complete', lease | {'report': good}))
    for field, value in [('input_hash', '0' * 64), ('input_revision', 2), ('semantic_request_sha256', '0' * 64), ('protocol', 'gee_offline')]:
        denied('wrong_' + field + '_rejected', lambda f=field, v=value: winner.call('complete', lease | {'report': good | {f: v}}))
    forged = deepcopy(good)
    forged['output']['content']['execution'] = 'live'
    denied('forged_live_result_rejected', lambda: winner.call('complete', lease | {'report': forged}))
    forged = deepcopy(good)
    forged['output']['content']['statistics']['mean'] = 0.99
    denied('forged_candidate_science_rejected', lambda: winner.call('complete', lease | {'report': forged}))
    denied('wrong_fencing_token_rejected', lambda: winner.call('complete', lease | {'lease_token': str(uuid4()), 'report': good}))
    before_lease = state(job_id)['job']['lease_until']
    time.sleep(1)
    heartbeat = winner.call('heartbeat', lease | {'progress': 25})
    record('heartbeat_renews_lease', heartbeat['lease_until'] > before_lease)
    with ThreadPoolExecutor(max_workers=2) as pool:
        completions = list(pool.map(lambda _: winner.complete(job, output), range(2)))
    record('concurrent_completion_is_idempotent', all(x['state'] == 'succeeded' for x in completions) and sum(bool(x.get('replayed')) for x in completions) == 1)
    saved = state(job_id)
    record('candidate_stored_with_actual_attempt_result_and_worker', saved['candidate']['output'] == output.model_dump(mode='json') and saved['candidate']['worker_id'] == workers[winner_index][0] and len(saved['attempts']) == 1)
    record('candidate_json_hash_distinct_from_semantic_request', saved['candidate']['output_sha256'] == output.output_sha256 and saved['candidate']['semantic_request_sha256'] != output.output_sha256)
    eligibility = local.sql("SELECT jsonb_build_array(gis.eligible(" + quote(job['edition_id']) + ',' + quote(job['dataset_id']) + '),gis.publication_ready(' + quote(job['edition_id']) + ',' + quote(job['dataset_id']) + '))', read_only=True)
    record('candidate_is_neither_eligible_nor_publishable', eligibility == [False, False])
    sql_denied('candidate_update_forbidden_even_for_owner', 'UPDATE gis.gee_candidates SET output=output WHERE job_id=' + quote(job_id))
    sql_denied('candidate_cannot_be_promoted_to_validated', "UPDATE gis.editions SET state='validated',validated_result_id=" + quote(saved['candidate']['result_id']) + ' WHERE id=' + quote(job['edition_id']))
    sql_denied('candidate_cannot_replace_active_pointer', 'UPDATE gis.datasets SET active_edition_id=' + quote(job['edition_id']) + ',revision=revision+1 WHERE id=' + quote(job['dataset_id']))

    for month, scenario in ((1, 'no_data'), (2, 'incomplete')):
        c, out = seed(month, scenario)
        jid = enqueue(c)['body']['job_id']
        claimed = a.call('claim')['job']
        record(scenario + '_job_claimed', claimed['id'] == jid)
        result = a.complete(claimed, out)
        row = state(jid)
        record(scenario + '_records_failure_not_candidate_or_zero', result['state'] == 'failed' and row['candidate'] is None and row['attempts'][0]['validation_report']['output']['content']['statistics']['mean'] is None)

    c, out = seed(3, product='lst')
    jid = enqueue(c)['body']['job_id']
    result = a.complete(a.call('claim')['job'], out)
    record('lst_monthly_candidate_keeps_celsius_and_mean_only', result['state'] == 'succeeded' and state(jid)['candidate']['output']['content']['statistics'] == {'mean': 30.0, 'min': None, 'max': None})

    c, out = seed(4)
    jid = enqueue(c)['body']['job_id']
    for attempt in range(1, 4):
        claimed = wait(lambda: a.call('claim')['job'])
        record('retry_attempt_' + str(attempt), claimed['id'] == jid and claimed['attempt_number'] == attempt)
        result = a.call('fail', {'job_id': jid, 'lease_token': claimed['lease_token'], 'error_code': 'transient',
                                'report': report(claimed, infrastructure_error='NATIVE_TIMEOUT')})
    record('retry_budget_terminal_at_three_without_candidate', result['state'] == 'failed' and state(jid)['candidate'] is None and len(state(jid)['attempts']) == 3)
    record('new_create_key_cannot_reset_retry_budget', enqueue(c)['body']['job_id'] == jid and a.call('claim')['job'] is None)

    c, out = seed(5)
    jid = enqueue(c)['body']['job_id']
    abandoned = a.call('claim')['job']
    print(json.dumps({'event': 'waiting_for_actual_lease_expiry', 'job_id': jid}), flush=True)
    # Client A ceases heartbeats; no owner SQL shortens the real 60-second lease.
    wait(lambda: b.call('recover')['recovered'] == 1, timeout=85)
    denied('expired_original_completion_rejected', lambda: a.complete(abandoned, out))
    replacement = wait(lambda: b.call('claim')['job'])
    denied('stale_token_after_replacement_rejected', lambda: a.complete(abandoned, out))
    b.complete(replacement, out)
    row = state(jid)
    record('actual_lease_expiry_recovery_preserves_history_single_candidate', [x['state'] for x in row['attempts']] == ['expired', 'succeeded'] and row['candidate']['worker_id'] == workers[1][0])

    # A real old-protocol request/result proves SQL compatibility without starting
    # an unrelated worker daemon or live compute. The numeric provider is unchanged.
    province = local.sql("SELECT to_jsonb(name_en) FROM public.provinces p WHERE NOT EXISTS(SELECT 1 FROM gis.processing_requests q WHERE q.province=p.name_en AND q.data_year=2018 AND q.month=9 AND q.metric='ndvi') ORDER BY name_en LIMIT 1", read_only=True)
    offline = operator.rpc('gis_processing_command', {'p_actor': officer, 'p_request_id': str(uuid4()), 'p_operation': 'create',
        'p_payload': {'province': province, 'district': None, 'metric': 'ndvi', 'data_year': 2018, 'month': 9, 'mode': 'offline_synthetic', 'scenario': 'standard', 'expected_revision': 1}, 'p_backend_sandbox': False}).execute().data
    record('mock_worker_does_not_claim_offline_jobs', a.call('claim')['job'] is None)
    native = p.m.identity_module.provision(local)
    denied('native_worker_does_not_gain_mock_protocol_rpc', lambda: native.client.rpc('gis_gee_mock_worker', {'p_action': 'claim', 'p_payload': {}}).execute())
    old_job = native.client.rpc('gis_processing_worker', {'p_action': 'claim', 'p_payload': {}}).execute().data['job']
    from gis_worker.processing_provider import OfflineProcessingAdapter
    old_sources = local.output / ('legacy-' + run)
    old_sources.mkdir()
    for target, source in [('gee_utils.py', 'gee_utils.py'), ('ndvi_compute.py', 'routers/ndvi/compute.py'), ('lst.py', 'routers/lst.py')]:
        (old_sources / target).write_bytes((p.REPO / 'green-area-backend' / source).read_bytes())
    old_report = OfflineProcessingAdapter(legacy_root=old_sources).compute({k: old_job[k] for k in ('processing_id', 'manifest', 'input_hash', 'input_revision', 'attempt_number')})
    old_done = native.client.rpc('gis_processing_worker', {'p_action': 'complete', 'p_payload': {'job_id': old_job['id'], 'lease_token': old_job['lease_token'], 'report': old_report}}).execute().data
    record('old_offline_protocol_still_commits_unchanged_scientific_result', old_done['state'] == 'succeeded' and old_report['statistics']['mean'] == 0.1614 and old_report['synthetic'] is True)
    record('all_test_jobs_terminal_broad_activation_gate_closed', local.sql("SELECT jsonb_build_array((SELECT count(*) FROM gis.jobs WHERE state IN ('queued','running')),(SELECT activation_enabled FROM gis.environment))", read_only=True) == [0, False])
    record('tested_source_unchanged_during_integration', all(hashlib.sha256((p.REPO / name).read_bytes()).hexdigest() == sha for name, sha in source_start.items()))
    result = {'run': run, 'rows': rows, 'passed': len(rows), 'failed': 0, 'live_gee': False,
              'worker_daemon_started': False, 'real_lease_expiry': True, 'mock_fixtures_only': True,
              'source': source_start}
    (local.output / ('checks-' + run + '.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir', type=Path, required=True)
    args = parser.parse_args()
    for name in ('httpx', 'httpcore', 'supabase_auth', 'postgrest'):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    def no_external(event, args):
        if event == 'socket.connect':
            endpoint = args[1]
            if not isinstance(endpoint, tuple) or endpoint[0] not in ('127.0.0.1', '::1'):
                raise RuntimeError('A62_EXTERNAL_NETWORK_FORBIDDEN')
        if event == 'socket.getaddrinfo' and args[0] not in ('127.0.0.1', '::1', 'localhost'):
            raise RuntimeError('A62_EXTERNAL_DNS_FORBIDDEN')
    sys.addaudithook(no_external)
    outcome = check(p.GeeMockLocal(args.runtime_dir))
    print(json.dumps({'passed': outcome['passed'], 'failed': outcome['failed'], 'run': outcome['run']}))
