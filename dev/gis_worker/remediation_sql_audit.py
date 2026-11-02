"""Read-only post-migration SQL audit of the explicitly attested T3 local stack.

Only the external evidence JSON is written. No SQL RPC is invoked, no credentials
are read and every database query uses a READ ONLY transaction via the local guard.
Run after the operator has stopped its approved Worker containers.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("sql_audit_attested_local", HERE / "remediation_local.py")
LOCAL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LOCAL
SPEC.loader.exec_module(LOCAL)
REPO = HERE.parents[1]


AUDIT_SQL = """
SELECT jsonb_build_object(
 'environment',(SELECT to_jsonb(e) FROM gis.environment e WHERE singleton),
 'ledger',(SELECT jsonb_agg(to_jsonb(s) ORDER BY version) FROM gis.schema_migrations s),
 'tables',(SELECT jsonb_agg(jsonb_build_object('table',c.relname,'owner',pg_get_userbyid(c.relowner),
   'rls',c.relrowsecurity,'force_rls',c.relforcerowsecurity)) FROM pg_class c
   JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='gis' AND c.relkind='r'),
 'worker_role',(SELECT jsonb_build_object('superuser',rolsuper,'login',rolcanlogin,'bypass_rls',rolbypassrls,
   'create_role',rolcreaterole,'create_db',rolcreatedb,'replication',rolreplication,'inherit',rolinherit)
   FROM pg_roles WHERE rolname='gis_native_worker'),
 'outbound_worker_memberships',(SELECT count(*) FROM pg_auth_members WHERE member='gis_native_worker'::regrole),
 'direct_table_privileges',(SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE c.relkind IN ('r','p') AND n.nspname IN ('gis','public','auth')
    AND (has_table_privilege('gis_native_worker',c.oid,'SELECT')
      OR has_table_privilege('gis_native_worker',c.oid,'INSERT')
      OR has_table_privilege('gis_native_worker',c.oid,'UPDATE')
      OR has_table_privilege('gis_native_worker',c.oid,'DELETE'))),
 'public_gis_acl',(SELECT jsonb_agg(jsonb_build_object('function',p.proname,'owner',pg_get_userbyid(p.proowner),
   'native_execute',has_function_privilege('gis_native_worker',p.oid,'EXECUTE'),
   'anon_execute',has_function_privilege('anon',p.oid,'EXECUTE'),
   'authenticated_execute',has_function_privilege('authenticated',p.oid,'EXECUTE'),
   'service_execute',has_function_privilege('service_role',p.oid,'EXECUTE'),
   'legacy_worker_execute',has_function_privilege('gis_worker',p.oid,'EXECUTE')))
   FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname LIKE 'gis%'),
 'remediation_functions',(SELECT jsonb_agg(jsonb_build_object('function',n.nspname||'.'||p.proname,
   'owner',pg_get_userbyid(p.proowner),'definer',p.prosecdef,'config',p.proconfig,'body',p.prosrc,
   'native_execute',has_function_privilege('gis_native_worker',p.oid,'EXECUTE'),
   'anon_execute',has_function_privilege('anon',p.oid,'EXECUTE'),
   'authenticated_execute',has_function_privilege('authenticated',p.oid,'EXECUTE'),
   'service_execute',has_function_privilege('service_role',p.oid,'EXECUTE'),
   'legacy_worker_execute',has_function_privilege('gis_worker',p.oid,'EXECUTE')))
   FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE
   (n.nspname='gis' AND p.proname IN ('native_subject','validate_native_report','queue_protocol',
      'worker','worker_v2','check_native_catalog')) OR
   (n.nspname='public' AND p.proname='gis_worker_readiness_v2')),
 'native_triggers',(SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
   JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='gis'
   AND t.tgname='native_catalog_integrity' AND t.tgdeferrable AND t.tginitdeferred
   AND t.tgfoid='gis.check_native_catalog()'::regprocedure))
"""


def source_definitions():
    result = {}
    migrations = {}
    pattern = re.compile(r"CREATE(?: OR REPLACE)? FUNCTION ([a-z0-9_.]+)\([^$]+?AS \$f\$(.*?)\$f\$;", re.S)
    for number in (32, 33):
        path = next((REPO / "green-area-backend/migrations").glob(f"{number:03}_*.sql"))
        content = path.read_bytes()
        migrations[number] = hashlib.sha256(content).hexdigest()
        # read_text universal newlines is normalized identically to PostgreSQL bodies below.
        for name, body in pattern.findall(content.decode("utf-8-sig").replace("\r\n", "\n")):
            result[name] = body
    return result, migrations


def run(runtime_dir: Path):
    local = LOCAL.Local(runtime_dir)
    local.attest()
    local.check_frozen()
    expected, migrations = source_definitions()
    rows = []
    databases = {}

    def check(name, passed, database):
        rows.append({"name": name, "database": database, "status": "Pass" if passed else "Fail"})

    for database in ("postgres", "gis_t1_upgrade"):
        state = local.sql(AUDIT_SQL, database, read_only=True)
        marker = state["environment"]
        check("exact_local_identity", marker["runtime_instance"] == local.db.instance
              and marker["database_name"] == database and marker["cluster_name"] == "green-area-gis-t0", database)
        ledger = {row["version"]: row["sha256"] for row in state["ledger"]}
        for number, checksum in migrations.items():
            check(f"ledger_{number}_matches_exact_source", ledger.get(number) == checksum, database)
        for relative, checksum in local.frozen["files"].items():
            if relative.startswith("green-area-backend/migrations/"):
                number = int(Path(relative).name[:3])
                if 27 <= number <= 31:
                    check(f"ledger_{number}_preserved", ledger.get(number) == checksum, database)
        check("all_gis_tables_force_rls_owner_only", len(state["tables"]) == 11 and all(
            item["owner"] == "gis_owner" and item["rls"] and item["force_rls"] for item in state["tables"]), database)
        check("restricted_native_role", bool(state["worker_role"]) and not any(state["worker_role"].values())
              and state["outbound_worker_memberships"] == 0, database)
        check("no_direct_native_table_privileges", state["direct_table_privileges"] == 0, database)
        check("four_deferred_native_integrity_triggers", state["native_triggers"] == 4, database)
        for function in state["remediation_functions"]:
            body = function.pop("body").replace("\r\n", "\n")
            name = function["function"]
            function["body_sha256_normalized"] = hashlib.sha256(body.encode()).hexdigest()
            check(name + "_exact_reviewed_body", expected.get(name) == body, database)
            check(name + "_owner_and_search_path", function["owner"] == "gis_owner"
                  and function["definer"] and function["config"] == ["search_path=pg_catalog, gis"], database)
            if name.startswith("gis."):
                check(name + "_private_acl", not any(function[key] for key in (
                    "native_execute", "anon_execute", "authenticated_execute", "service_execute", "legacy_worker_execute")), database)
        check("all_expected_remediation_functions_present", len(state["remediation_functions"]) == len(expected), database)
        for function in state["public_gis_acl"]:
            name = function["function"]
            if name in ("gis_worker_v2", "gis_worker_readiness_v2"):
                check(name + "_least_privilege_acl", function["owner"] == "gis_owner"
                      and function["native_execute"] and not any(function[key] for key in (
                          "anon_execute", "authenticated_execute", "service_execute", "legacy_worker_execute")), database)
            elif name != "gis_identity_probe_t3":
                check(name + "_native_denied", not function["native_execute"], database)
        databases[database] = state
    report = {"type": "actual_attested_local_read_only_sql_audit", "sql_mutations": False,
              "source_fingerprint": LOCAL.fingerprint(), "results": rows,
              "counts": {status: sum(row["status"] == status for row in rows) for status in ("Pass", "Fail")},
              "databases": databases, "credentials_read": False}
    local.write("sql-audit.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    outcome = run(args.runtime_dir)
    print(json.dumps({"counts": outcome["counts"], "sql_mutations": False, "report": "sql-audit.json"}))
    raise SystemExit(1 if outcome["counts"]["Fail"] else 0)
