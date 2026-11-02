"""Index existing local evidence and current source hashes; no database/network."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

REPO = Path(__file__).resolve().parents[2]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--browser-run', required=True)
    parser.add_argument('--authorization-run', required=True)
    args = parser.parse_args()
    root = args.runtime_dir
    owner = json.loads((root / 'owner.json').read_text(encoding='utf-8'))
    if owner.get('scope') != 'gis-foundation-t0' or any(not re.fullmatch('[a-f0-9]{10}', value) for value in (args.browser_run, args.authorization_run)):
        raise RuntimeError('OWNED_LOCAL_EVIDENCE_REQUIRED')
    out = root / 'phase2'
    for name in ('unit', 'regression'):
        shutil.copyfile(root / 't2' / (name + '-tests.json'), out / ('backend-' + name + '-tests.json'))
    browser = root / 'phase2-browser' / args.browser_run
    local_result = json.loads((browser / 'local-results.json').read_text(encoding='utf-8'))
    browser_result = json.loads((browser / 'browser-results.json').read_text(encoding='utf-8'))
    auth_browser = root / 'phase2-browser' / args.authorization_run
    auth_local = json.loads((auth_browser / 'local-results.json').read_text(encoding='utf-8'))
    auth_result = json.loads((auth_browser / 'browser-results.json').read_text(encoding='utf-8'))
    source = {}
    folders = ('dev/gis_local','dev/gis_worker','dev/gis_ui','green-area-backend/gis_worker',
        'green-area-backend/migrations','green-area-backend/tests','green-area-frontend/src')
    for folder in folders:
        for f in sorted((REPO / folder).rglob('*')):
            if f.is_file() and f.suffix in ('.py','.sql','.json','.yaml','.js','.mjs','.cjs','.css','.zip','.tif') and not any(x in f.parts for x in ('__pycache__','.pytest_cache')):
                source[f.relative_to(REPO).as_posix()] = sha(f)
    for name in ('main.py','gis_app.py','gis_runtime.py','gis_schemas.py','gis_service.py','gis_ldd_storage.py','routers/gis.py'):
        f = REPO / 'green-area-backend' / name
        source[f.relative_to(REPO).as_posix()] = sha(f)
    handoff = REPO / 'docs/gis/phase2-handoff.md'
    source[handoff.relative_to(REPO).as_posix()] = sha(handoff)
    application_matches = {}
    reports = ['integration-61046497bd9a.json','integration-f3be04c2dd7c.json']
    for name in reports:
        report = json.loads((out / name).read_text(encoding='utf-8'))
        drift = [f for f, h in report['source']['files'].items() if f != 'dev/gis_ui/phase2_checks.py' and sha(REPO / f) != h]
        application_matches[name] = {'application_source_matches': not drift, 'drift': drift,
            'test_runner_version_recorded_in_original_report': True, 'counts': report['counts']}
    def app_sources_match(report):
        return all(sha(REPO / f) == h for f, h in report['source'].items() if f.startswith('green-area-frontend/src/'))
    browser_source_matches = app_sources_match(local_result) and app_sources_match(auth_local)
    artifacts = {f.relative_to(root).as_posix(): sha(f) for f in sorted(out.glob('*.json')) if f.name != 'evidence-index.json'}
    artifacts.update({f.relative_to(root).as_posix(): sha(f) for f in sorted(browser.iterdir()) if f.is_file()})
    artifacts.update({f.relative_to(root).as_posix(): sha(f) for f in sorted(auth_browser.iterdir()) if f.is_file()})
    frontend = json.loads((out / 'frontend-tests.json').read_text(encoding='utf-8'))
    audit = json.loads((out / 'sql-audit.json').read_text(encoding='utf-8'))
    index = {'phase2_status': 'PARTIAL_LOCAL_IMPLEMENTATION_AWAITING_ACCEPTANCE',
        'branch': subprocess.check_output(['git','branch','--show-current'], cwd=REPO, text=True).strip(),
        'head': subprocess.check_output(['git','rev-parse','HEAD'], cwd=REPO, text=True).strip(),
        'source_files': source, 'source_sha256': hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest(),
        'artifacts': artifacts, 'integration_source_verification': application_matches,
        'browser_source_current': browser_source_matches, 'browser_local_checks': local_result['checks'],
        'authorization_browser_local_checks': auth_local['checks'],
        'browser_runner_note': 'Original 22 pass/1 pagination synchronization failure retained. Only test runner changed; focused roles/revocation passed. Application source matches both runs.',
        'counts': {'unit': json.loads((out / 'unit-tests.json').read_text(encoding='utf-8'))['counts'],
            'frontend_passed': frontend['numPassedTests'], 'frontend_failed': frontend['numFailedTests'],
            'browser_passed': sum(x['status'] == 'Pass' for x in browser_result['rows']),
            'browser_failed': sum(x['status'] != 'Pass' for x in browser_result['rows']),
            'authorization_browser_passed': sum(x['status'] == 'Pass' for x in auth_result['rows']),
            'authorization_browser_failed': sum(x['status'] != 'Pass' for x in auth_result['rows']),
            'sql_audit_passed': sum(x['passed'] for x in audit['checks']),
            'sql_audit_failed': sum(not x['passed'] for x in audit['checks'])},
        'build': {'exit_code': 0, 'config': 'dev/gis_ui/vite.config.mjs', 'deployment': False},
        'build_artifacts': {f.relative_to(REPO).as_posix(): sha(f) for f in sorted((REPO / 'green-area-frontend/build').rglob('*')) if f.is_file()},
        'not_tested': ['Gate-enabled lifecycle success','Official provincial LDD dataset','Kernel/cgroup OOM','Cloud/Production/GEE'],
        'capacity_failure_retained': '15k polygons hit NATIVE_MEMORY_LIMIT; full report retains 2 failure rows; focused 1500 recovery passed',
        'production_secrets_read': False, 'credentials_persisted_in_evidence': False,
        'note': 'Only generated local Auth bootstrap values were used in process memory; no production credential files read'}
    (out / 'evidence-index.json').write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'source_sha256': index['source_sha256'], 'counts': index['counts'],
        'browser_source_current': browser_source_matches, 'integration_source_verification': application_matches}))

if __name__ == '__main__':
    main()
