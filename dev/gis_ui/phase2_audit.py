"""Read-only ledger, RLS/ACL and frozen migration audit for both local databases."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('p2_audit_operator', Path(__file__).with_name('phase2_local.py'))
p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p
spec.loader.exec_module(p)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-dir', type=Path, required=True)
    args = parser.parse_args()
    local = p.Phase2Local(args.runtime_dir)
    local.attest()
    old = json.loads((args.runtime_dir / 't3-remediation/sql-audit.json').read_text())
    frozen = old['source_fingerprint']['files']
    migration_files = {f: hashlib.sha256((p.REPO / f).read_bytes()).hexdigest() == h for f, h in frozen.items()
        if f.startswith('green-area-backend/migrations/') and int(Path(f).name[:3]) <= 33}
    records, checks = {}, []
    for database in ('postgres', 'gis_t1_upgrade'):
        ledger = local.sql('SELECT jsonb_agg(to_jsonb(m) ORDER BY version) FROM gis.schema_migrations m', database, read_only=True)
        tables = local.sql("SELECT jsonb_agg(jsonb_build_object('name',c.relname,'owner',r.rolname,"
            "'rls',c.relrowsecurity,'forced',c.relforcerowsecurity,'policy_count',(SELECT count(*) FROM pg_policy WHERE polrelid=c.oid)) ORDER BY c.relname) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_roles r ON r.oid=c.relowner "
            "WHERE n.nspname='gis' AND c.relkind='r'", database, role='postgres', read_only=True)
        acl = local.sql("SELECT jsonb_agg(jsonb_build_object('name',pr.proname,'owner',r.rolname,'definer',pr.prosecdef,"
            "'config',pr.proconfig,'anon',has_function_privilege('anon',pr.oid,'EXECUTE'),"
            "'user',has_function_privilege('authenticated',pr.oid,'EXECUTE'),"
            "'service',has_function_privilege('service_role',pr.oid,'EXECUTE'),"
            "'worker',has_function_privilege('gis_native_worker',pr.oid,'EXECUTE')) ORDER BY pr.proname) "
            "FROM pg_proc pr JOIN pg_namespace n ON n.oid=pr.pronamespace JOIN pg_roles r ON r.oid=pr.proowner "
            "WHERE n.nspname='public' AND pr.proname IN ('gis_ldd_command','gis_ldd_read','gis_ldd_worker','gis_ldd_readiness')",
            database, role='postgres', read_only=True)
        direct = local.sql("SELECT to_jsonb(count(*)) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname IN ('gis','public') AND c.relkind='r' AND (has_table_privilege('gis_native_worker',c.oid,'SELECT') "
            "OR has_table_privilege('gis_native_worker',c.oid,'INSERT') OR has_table_privilege('gis_native_worker',c.oid,'UPDATE') "
            "OR has_table_privilege('gis_native_worker',c.oid,'DELETE'))", database, role='postgres', read_only=True)
        expected_acl = all(x['owner'] == 'gis_owner' and x['definer'] and x['config'] == ['search_path=pg_catalog, gis']
            and not x['anon'] and not x['user'] and x['worker'] == (x['name'] in ('gis_ldd_worker','gis_ldd_readiness'))
            and x['service'] == (x['name'] in ('gis_ldd_command','gis_ldd_read')) for x in acl)
        entries = [x for x in ledger if x['version'] <= 33]
        source_matches = all(hashlib.sha256(next((p.REPO / 'green-area-backend/migrations').glob(f"{x['version']:03d}_*.sql")).read_bytes()).hexdigest() == x['sha256'] for x in ledger)
        table = next(x for x in tables if x['name'] == 'ldd_uploads')
        checks.extend([{'name': database + '_' + name, 'passed': value} for name, value in {
            'prior_ledger_exact_including_timestamps': entries == old['databases'][database]['ledger'],
            'current_ledger_source_sha': source_matches,
            'eight_migrations_027_034': [x['version'] for x in ledger] == list(range(27,35)),
            'ldd_forced_rls_owner_only': table['owner'] == 'gis_owner' and table['rls'] and table['forced'] and table['policy_count'] == 1,
            'new_rpc_exact_acl': len(acl) == 4 and expected_acl,
            'worker_no_direct_tables': direct == 0}.items()])
        records[database] = {'ledger': ledger, 'tables': tables, 'new_rpc_acl': acl, 'native_direct_table_privileges': direct}
    checks.append({'name': 'migration_000_033_files_unchanged', 'passed': bool(migration_files) and all(migration_files.values())})
    result = {'read_only': True, 'checks': checks, 'migration_files': migration_files, 'databases': records}
    local.write('sql-audit.json', result)
    print(json.dumps({'checks': checks}))
    return not all(x['passed'] for x in checks)

if __name__ == '__main__':
    sys.exit(main())
