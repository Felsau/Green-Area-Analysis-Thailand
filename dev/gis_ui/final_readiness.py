"""T5 final integration checks, not a schema/application implementation.

Reuses source-bound T3/T4 evidence. Adds only real local Auth/API negative-gate
and idempotency checks. No worker/container/resource creation, dotenv, cloud,
migration, ledger modification or changes to pre-existing users/catalog rows.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import secrets
import sys
from uuid import uuid4

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location('t5_attested_local', HERE.parent / 'gis_worker/remediation_local.py')
local_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = local_module
spec.loader.exec_module(local_module)
spec = importlib.util.spec_from_file_location('t5_read_only_audit', HERE.parent / 'gis_worker/remediation_sql_audit.py')
audit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audit
spec.loader.exec_module(audit)
sys.path.insert(0, str(REPO / 'green-area-backend'))
from fastapi.testclient import TestClient
from gis_app import create_app


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def canonical(value):
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return sorted((canonical(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    return value


def catalog(local):
    return local.sql("SELECT jsonb_build_object(" + ','.join(
        "'" + name + "',(SELECT md5(COALESCE(string_agg(to_jsonb(t)::text,'|' ORDER BY id),'')) FROM gis." + name + ' t)'
        for name in ('datasets', 'editions', 'jobs', 'attempts', 'results')) + ')', read_only=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir', type=Path, required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    local = local_module.Local(args.runtime_dir)
    local.attest()
    local.check_frozen()
    if local_module.fingerprint()['branch'] != local_module.GIS_BRANCH:
        raise RuntimeError('WRONG_BRANCH')
    output = local.db.runtime.root / 't5-final'
    output.mkdir(exist_ok=True)
    rows = []

    def check(name, passed):
        rows.append({'name': name, 'status': 'Pass' if passed else 'Fail'})
        print(json.dumps(rows[-1]), flush=True)
        if not passed:
            raise AssertionError(name)

    t3 = read(local.db.runtime.root / 't3-remediation/final-evidence-index.json')
    t4 = read(local.db.runtime.root / 't4-ui/a13e91f362/local-results.json')
    check('t3_reviewed_sources_unchanged', all(sha(REPO / p) == h for p, h in t3['source']['files'].items()))
    check('t4_application_test_sources_unchanged', all(sha(REPO / p) == h for p, h in t4['source'].items()))
    summary = read(REPO / 'docs/gis/t3-remediation-evidence.json')
    check('t3_evidence_artifact_hashes_match', all(sha(Path(summary['evidence_root']) / p) == h for p, h in summary['artifact_hashes'].items()))
    check('t3_exact_independent_review_hash', sha(Path(summary['independent_review']['artifact'])) == summary['independent_review']['sha256'])
    browser = read(local.db.runtime.root / 't4-ui/a13e91f362/browser-results.json')
    check('reused_t4_real_browser_16_pass', browser['mocked_api'] is False and len(browser['rows']) == 16 and all(r['status'] == 'Pass' for r in browser['rows']))
    check('reused_t4_preservation_pass', t4['smoke_exit'] == 0 and all(all(x.values()) if isinstance(x, dict) else x for x in t4['checks'].values()))
    reviewed = read(local.db.runtime.root / 't3-remediation/sql-audit.json')['databases']
    security = {}
    for database in ('postgres', 'gis_t1_upgrade'):
        state = local.sql(audit.AUDIT_SQL, database, read_only=True)
        for item in state['remediation_functions']:
            body = item.pop('body').replace('\r\n', '\n')
            item['body_sha256_normalized'] = hashlib.sha256(body.encode()).hexdigest()
        check(database + '_security_schema_ledger_equal_reviewed_t3', canonical(state) == canonical(reviewed[database]))
        check(database + '_activation_gate_closed', state['environment']['activation_enabled'] is False)
        check(database + '_worker_no_direct_table_privilege', state['direct_table_privileges'] == 0)
        security[database] = {'matches_reviewed_t3': True, 'gate_closed': True, 'ledger_rows': len(state['ledger'])}
    check('queue_idle_before_checks', local.sql("SELECT to_jsonb(count(*)) FROM gis.jobs WHERE state IN ('queued','running')", read_only=True) == 0)
    before = local.baseline()
    catalog_before = catalog(local)
    source_before = local_module.fingerprint()
    target = local.sql("SELECT jsonb_build_object('dataset',to_jsonb(d),'edition',to_jsonb(e)) "
        "FROM gis.datasets d JOIN gis.editions e ON e.dataset_id=d.id "
        "WHERE d.title LIKE 'T4 Synthetic %' AND e.state='validated' ORDER BY d.created_at DESC LIMIT 1", read_only=True)
    check('existing_synthetic_validated_target_available', isinstance(target, dict) and target['edition']['manifest']['provider'] == 'synthetic')
    anon, service = local.local_keys()
    operator = local.client(service)
    users = {}
    for name in ('admin', 'user'):
        email = 'gis-t5-' + name + '-' + uuid4().hex + '@example.invalid'
        password = secrets.token_urlsafe(30)
        created = operator.auth.admin.create_user({'email': email, 'password': password, 'email_confirm': True,
            'user_metadata': {'display_name': 'T5 synthetic ' + name}})
        client = local.client(anon)
        session = client.auth.sign_in_with_password({'email': email, 'password': password}).session
        users[name] = {'id': str(created.user.id), 'token': session.access_token, 'client': client}
    admin_id = local_module.t2.t1.literal(users['admin']['id'])
    local.sql("UPDATE public.profiles SET role='admin' WHERE id=" + admin_id + "::uuid AND role='user'", role='postgres')
    try:
        with TestClient(create_app(local.runtime()), base_url='http://127.0.0.1:55422') as api:
            def request(method, path, actor='admin', body=None, key=None, status=200, code=None):
                headers = {'Authorization': 'Bearer ' + users[actor]['token']}
                if method != 'GET':
                    headers['Idempotency-Key'] = key or str(uuid4())
                response = api.request(method, '/gis' + path, headers=headers, **({'json': body} if body is not None else {}))
                return response, response.status_code == status and (code is None or response.json().get('detail', {}).get('code') == code)

            check('missing_jwt_401', api.get('/gis/me').status_code == 401)
            parts = users['admin']['token'].split('.')
            parts[2] = ('A' if parts[2][0] != 'A' else 'B') + parts[2][1:]
            forged = api.get('/gis/me', headers={'Authorization': 'Bearer ' + '.'.join(parts)})
            check('real_auth_rejects_tampered_signature', forged.status_code == 401)
            response, ok = request('GET', '/me')
            check('admin_me_both_gates_closed', ok and response.json()['admin'] and response.json()['activation_enabled'] is False
                and response.json()['backend_activation_enabled'] is False and response.json()['database_activation_enabled'] is False)
            response, ok = request('GET', '/me', actor='user')
            check('normal_user_no_capabilities', ok and response.json()['capabilities'] == [])
            _, ok = request('GET', '/datasets', actor='user', status=403, code='GIS_FORBIDDEN')
            check('backend_normal_user_catalog_denied', ok)
            subject = users['user']['id']
            grant = {'user_id': subject, 'reason': 'T5 synthetic authorization check'}
            _, ok = request('POST', '/officers', actor='user', body=grant, status=403, code='GIS_FORBIDDEN')
            check('normal_user_self_grant_denied', ok)
            try:
                users['user']['client'].rpc('gis_read', {'p_actor': users['admin']['id'], 'p_kind': 'me', 'p_payload': {}}).execute()
                denied = False
            except Exception as error:
                denied = str(getattr(error, 'code', '')) == '42501'
            check('authenticated_jwt_cannot_call_service_rpc', denied)
            key = str(uuid4())
            first, ok = request('POST', '/officers', body=grant, key=key)
            check('admin_grant_synthetic_officer', ok)
            second, ok = request('POST', '/officers', body=grant, key=key)
            check('same_key_same_body_replays_same_result', ok and first.json() == second.json())
            _, ok = request('POST', '/officers', body={**grant, 'reason': 'different body'}, key=key, status=409, code='GIS_IDEMPOTENCY_CONFLICT')
            check('same_key_different_body_conflict_409', ok)
            receipt_count = local.sql("SELECT to_jsonb(count(*)) FROM gis.receipts WHERE actor_id=" + admin_id + '::uuid AND request_id='
                + local_module.t2.t1.literal(key) + '::uuid', read_only=True)
            check('idempotency_single_receipt', receipt_count == 1)
            response, ok = request('GET', '/me', actor='user')
            check('officer_has_catalog_without_admin_capabilities', ok and response.json()['officer'] and not response.json()['admin']
                and 'read_catalog' in response.json()['capabilities'] and 'grant_officer' not in response.json()['capabilities'])
            d, e = target['dataset'], target['edition']
            activation = {'edition_id': e['id'], 'expected_revision': d['revision'], 'expected_active_edition_id': d['active_edition_id'], 'reason': 'T5 closed gate verification'}
            withdrawal = {'expected_revision': e['input_revision'], 'expected_dataset_revision': d['revision'],
                'expected_active_edition_id': d['active_edition_id'], 'replacement_edition_id': None, 'reason': 'T5 closed gate verification'}
            for name, path, body in (
                ('activate', '/datasets/' + d['id'] + '/activation', activation),
                ('rollback', '/datasets/' + d['id'] + '/rollback', activation),
                ('withdraw', '/editions/' + e['id'] + '/withdrawal', withdrawal),
            ):
                _, ok = request('POST', path, body=body, status=503, code='GIS_ACTIVATION_DISABLED')
                check('admin_' + name + '_closed_gate_503', ok)
                _, ok = request('POST', path, actor='user', body=body, status=403, code='GIS_FORBIDDEN')
                check('officer_' + name + '_admin_only_403', ok)
            _, ok = request('POST', '/officers/' + subject + '/revocation', body={'reason': 'T5 synthetic authorization check complete'})
            check('admin_revoke_synthetic_officer', ok)
            _, ok = request('GET', '/datasets', actor='user', status=403, code='GIS_FORBIDDEN')
            check('revoked_officer_backend_denied', ok)
    finally:
        after = local.baseline()
        for database, old in before.items():
            new = after[database]
            check(database + '_ledger_preserved', old['ledger'] == new['ledger'])
            check(database + '_preexisting_profiles_preserved', all(new['profiles'].get(k) == h for k, h in old['profiles'].items()))
            check(database + '_legacy_tables_preserved', all(new['tables'].get(k) == h for k, h in old['tables'].items() if k != 'profiles'))
        check('catalog_jobs_results_attempts_unchanged', catalog_before == catalog(local))
        check('backend_sources_preserved', source_before == local_module.fingerprint())
        report = {'phase': 'T5 Local Synthetic Final Readiness', 'branch': source_before['branch'], 'head': source_before['head'],
            'counts': {status: sum(r['status'] == status for r in rows) for status in ('Pass', 'Fail')},
            'checks': rows, 'security': security,
            'reused_t3_source_sha256': t3['source']['sha256'], 'reused_t4_source_sha256': t4['source_sha256'],
            'sources': {'test_file': sha(Path(__file__)), 't3_files': t3['source']['files'], 't4_files': t4['source']},
            'mutations': 'Only two new synthetic Auth/profile fixtures, officer grant/revoke and idempotency receipts/audit; no existing user/catalog/schema/ledger changes',
            'new_cloud_resources': False, 'new_containers': False, 'migration_run': False,
            'not_tested': ['Gate-enabled activation/rollback/withdraw success', 'Live browser retry success', 'Live GeoTIFF browser E2E',
                'Auth refresh expiry/rotation', 'Kernel/cgroup OOM-kill', 'CPU-burn exhaustion', 'Real GIS/upload/storage/cloud/production']}
        (output / 'integration.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({'evidence': str(output / 'integration.json'), 'counts': report['counts']}), flush=True)
    return 1 if any(r['status'] == 'Fail' for r in rows) else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        print(json.dumps({'ok': False, 'code': 'T5_FINAL_CHECK_FAILED'}))
        sys.exit(1)
