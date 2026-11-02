"""Read-only Local Phase 4 schema/ACL/source/legacy audit; never reapplies SQL.

Run with no other process-owned worker active. Exact target attestation remains
strict. Only the resulting external phase4/sql-audit.json is written.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

spec = importlib.util.spec_from_file_location('phase4_audit_operator', Path(__file__).with_name('phase4_local.py'))
p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p
spec.loader.exec_module(p)


def function_bodies(sql):
    pattern = r'CREATE(?: OR REPLACE)? FUNCTION\s+([a-zA-Z_][\w.]+)\([^$]*?\bAS\s+(\$\w*\$)([\s\S]*?)\2;'
    return {name: body.replace('\r\n', '\n').strip() for name, _, body in re.findall(pattern, sql, re.I)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir', type=Path, required=True)
    args = parser.parse_args()
    local = p.Phase4Local(args.runtime_dir)
    local.attest()
    local.check_frozen()
    initial = json.loads((args.runtime_dir / 'phase4/initial-state.json').read_text(encoding='utf-8'))['baseline']
    frozen = json.loads((args.runtime_dir / 'phase3/evidence-index.json').read_text(encoding='utf-8'))['source_files']
    migration_files = {f: hashlib.sha256((p.REPO / f).read_bytes()).hexdigest() == digest for f, digest in frozen.items()
        if f.startswith('green-area-backend/migrations/') and int(Path(f).name[:3]) <= 35}
    migration = p.REPO / 'green-area-backend/migrations/036_gis_geotiff_upload.sql'
    migration_sha = hashlib.sha256(migration.read_bytes()).hexdigest()
    review = json.loads((args.runtime_dir / 'phase4/review-036.json').read_text(encoding='utf-8'))
    expected = function_bodies(migration.read_text(encoding='utf-8'))
    if len(expected) != 20:
        raise RuntimeError('EXACT_MIGRATION_FUNCTION_SET_REQUIRED')
    native = function_bodies((p.REPO / 'green-area-backend/migrations/032_gis_worker_remediation.sql').read_text(encoding='utf-8'))
    expected['gis.native_subject'] = native['gis.native_subject']
    names = ','.join("'" + name + "'" for name in expected)
    records, checks = {}, []
    current = local.baseline()
    for database in ('postgres', 'gis_t1_upgrade'):
        ledger = current[database]['ledger']
        table = local.sql("SELECT jsonb_build_object('owner',r.rolname,'rls',c.relrowsecurity,'forced',c.relforcerowsecurity,"
            "'policies',(SELECT jsonb_agg(jsonb_build_object('roles',roles,'cmd',cmd,'qual',qual,'check',with_check)) "
            "FROM pg_policies WHERE schemaname='gis' AND tablename='geotiff_uploads'),"
            "'constraints',(SELECT jsonb_agg(pg_get_constraintdef(oid) ORDER BY conname) FROM pg_constraint WHERE conrelid=c.oid)) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_roles r ON r.oid=c.relowner "
            "WHERE n.nspname='gis' AND c.relname='geotiff_uploads'", database, role='postgres', read_only=True)
        acl = local.sql("SELECT jsonb_agg(jsonb_build_object('name',pr.proname,'owner',r.rolname,'definer',pr.prosecdef,"
            "'config',pr.proconfig,'anon',has_function_privilege('anon',pr.oid,'EXECUTE'),"
            "'user',has_function_privilege('authenticated',pr.oid,'EXECUTE'),"
            "'service',has_function_privilege('service_role',pr.oid,'EXECUTE'),"
            "'worker',has_function_privilege('gis_native_worker',pr.oid,'EXECUTE')) ORDER BY pr.proname) "
            "FROM pg_proc pr JOIN pg_namespace n ON n.oid=pr.pronamespace JOIN pg_roles r ON r.oid=pr.proowner "
            "WHERE n.nspname='public' AND pr.proname IN ('gis_geotiff_command','gis_geotiff_read','gis_geotiff_worker','gis_geotiff_readiness')",
            database, role='postgres', read_only=True)
        functions = local.sql("SELECT jsonb_agg(jsonb_build_object('name',n.nspname||'.'||pr.proname,'owner',r.rolname,"
            "'definer',pr.prosecdef,'config',pr.proconfig,'body',pr.prosrc) ORDER BY n.nspname,pr.proname) "
            "FROM pg_proc pr JOIN pg_namespace n ON n.oid=pr.pronamespace JOIN pg_roles r ON r.oid=pr.proowner "
            "WHERE n.nspname||'.'||pr.proname IN (" + names + ')', database, role='postgres', read_only=True)
        direct = local.sql("SELECT jsonb_build_object('direct_tables',count(*) FILTER(WHERE n.nspname IN ('gis','public') AND "
            "has_table_privilege('gis_native_worker',c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')),"
            "'legacy_dml',count(*) FILTER(WHERE n.nspname='public' AND "
            "has_table_privilege('gis_native_worker',c.oid,'INSERT,UPDATE,DELETE,TRUNCATE'))) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind='r'", database, role='postgres', read_only=True)
        policies = table.get('policies') or []
        owner_only = len(policies) == 1 and policies[0] == {'roles': ['gis_owner'], 'cmd': 'ALL', 'qual': 'true', 'check': 'true'}
        exact_acl = len(acl) == 4 and all(x['owner'] == 'gis_owner' and x['definer'] and x['config'] == ['search_path=pg_catalog, gis']
            and not x['anon'] and not x['user'] and x['worker'] == (x['name'] in ('gis_geotiff_worker','gis_geotiff_readiness'))
            and x['service'] == (x['name'] in ('gis_geotiff_command','gis_geotiff_read')) for x in acl)
        function_records = []
        for entry in functions:
            body = entry.pop('body').replace('\r\n', '\n').strip()
            function_records.append({**entry, 'body_sha256': hashlib.sha256(body.encode()).hexdigest(),
                'body_matches_migration': body == expected[entry['name']]})
        constraints = table.get('constraints') or []
        current_tables = current[database]['tables']
        values = {
            'prior_ledger_exact_including_timestamps': [x for x in ledger if x['version'] <= 35] == initial[database]['ledger'],
            'current_ledger_source_sha': all(hashlib.sha256(next((p.REPO / 'green-area-backend/migrations').glob(f"{x['version']:03d}_*.sql")).read_bytes()).hexdigest() == x['sha256'] for x in ledger),
            'ten_migrations_027_036': [x['version'] for x in ledger] == list(range(27, 37)),
            'geotiff_forced_rls_owner_only': table['owner'] == 'gis_owner' and table['rls'] and table['forced'] and owner_only,
            'association_and_dedup_constraints': 'FOREIGN KEY (edition_id, dataset_id) REFERENCES gis.editions(id, dataset_id)' in constraints
                and 'UNIQUE (dataset_id, sha256, crs, profile)' in constraints,
            'new_rpc_exact_acl': exact_acl,
            'twenty_functions_and_jwt_body_exact': len(function_records) == 21 and all(x['body_matches_migration'] for x in function_records),
            'function_owner_security_definer_search_path': all(x['owner'] == 'gis_owner' and x['definer'] and x['config'] == ['search_path=pg_catalog, gis'] for x in function_records),
            'worker_no_direct_tables': direct['direct_tables'] == 0,
            'worker_no_legacy_dml': direct['legacy_dml'] == 0,
            'old_profiles_preserved': all(current[database]['profiles'].get(k) == digest for k, digest in initial[database]['profiles'].items()),
            'legacy_nonprofile_tables_preserved': all(current_tables.get(k) == value for k, value in initial[database]['tables'].items() if k != 'profiles'),
        }
        checks.extend({'name': database + '_' + name, 'passed': bool(value)} for name, value in values.items())
        records[database] = {'ledger': ledger, 'geotiff_table': table, 'new_rpc_acl': acl, 'functions': function_records,
            'worker_privileges': direct, 'public_nonprofile_tables': {k: v for k, v in current_tables.items() if k != 'profiles'},
            'old_profiles_checked': len(initial[database]['profiles'])}
    checks.extend([{'name': 'migration_000_035_files_unchanged', 'passed': bool(migration_files) and all(migration_files.values())},
        {'name': 'exact_preapply_review_sha', 'passed': review.get('independent_review') is True and review.get('unresolved_high_critical') == 0
            and review.get('files') == {migration.name: migration_sha}}])
    result = {'read_only_database': True, 'writes': 'external phase4/sql-audit.json only', 'migration_036_sha256': migration_sha,
        'checks': checks, 'migration_files': migration_files, 'databases': records,
        'source': {str(Path(__file__).relative_to(p.REPO).as_posix()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    local.write('sql-audit.json', result)
    print(json.dumps({'passed': sum(x['passed'] for x in checks), 'failed': sum(not x['passed'] for x in checks), 'checks': checks}))
    return not all(x['passed'] for x in checks)


if __name__ == '__main__':
    sys.exit(main())
