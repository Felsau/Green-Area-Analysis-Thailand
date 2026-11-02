"""Reproducible local baseline preservation evidence; synthetic rows only."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location("t1_preservation_db", Path(__file__).with_name("t1_database.py"))
dbmodule = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = dbmodule
spec.loader.exec_module(dbmodule)


def snapshot(db, database, stage):
    tables = json.loads(db.query(database, "SELECT jsonb_agg(tablename ORDER BY tablename) FROM pg_tables WHERE schemaname='public';", stage=stage).stdout)
    rows = {}
    for table in tables:
        # Names come only from the verified local PostgreSQL catalog.
        identifier = '"' + table.replace('"', '""') + '"'
        rows[table] = json.loads(db.query(database,
            "SELECT jsonb_build_object('rows',count(*),'hash',md5(COALESCE(string_agg(to_jsonb(t)::text,'|' ORDER BY to_jsonb(t)::text),''))) FROM public."
            + identifier + " t;", stage=stage).stdout)
    sql = """
SELECT jsonb_build_object(
 'columns',(SELECT jsonb_agg(jsonb_build_array(table_name,column_name,data_type,is_nullable,column_default) ORDER BY table_name,ordinal_position)
  FROM information_schema.columns WHERE table_schema='public'),
 'constraints',(SELECT jsonb_agg(jsonb_build_array(c.relname,k.conname,pg_get_constraintdef(k.oid)) ORDER BY c.relname,k.conname)
  FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'),
 'indexes',(SELECT jsonb_agg(jsonb_build_array(tablename,indexname,indexdef) ORDER BY tablename,indexname) FROM pg_indexes WHERE schemaname='public'),
 'legacy_functions',(SELECT jsonb_agg(jsonb_build_array(p.proname,md5(pg_get_functiondef(p.oid))) ORDER BY p.proname)
  FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname IN ('handle_new_user','set_profiles_updated_at')),
 'auth_trigger',(SELECT jsonb_agg(pg_get_triggerdef(oid) ORDER BY tgname) FROM pg_trigger WHERE tgrelid='auth.users'::regclass AND NOT tgisinternal),
 'rls',(SELECT jsonb_agg(jsonb_build_array(c.relname,c.relrowsecurity,c.relforcerowsecurity) ORDER BY c.relname)
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p')));
"""
    structure = json.loads(db.query(database, sql, stage=stage).stdout)
    return {"tables": rows, "legacy_structure": structure}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seed-upgrade", "before", "compare", "source-check"))
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--database", choices=sorted(dbmodule.DATABASES), default="gis_t1_upgrade")
    args = parser.parse_args()
    db = dbmodule.LocalDatabase(args.runtime_dir)
    if args.action == "source-check":
        original = json.loads((db.runtime.root / "t0-final-source-verification.json").read_text(encoding="utf-8"))
        changed = [item["path"] for item in original["artifacts"]
                   if dbmodule.sha((dbmodule.REPO / item["path"]).read_bytes()) != item["sha256"]]
        result = {"t0_original_files": len(original["artifacts"]), "changed": changed,
                  "legacy_sources": {p.name: dbmodule.sha(p.read_bytes()) for p in dbmodule.sources()}}
        db.write_json("source-preservation.json", result)
        if changed:
            raise dbmodule.SafetyError("T0_SOURCE_BYTES_CHANGED")
    elif args.action == "seed-upgrade":
        if args.database != "gis_t1_upgrade":
            raise dbmodule.SafetyError("SENTINELS_ONLY_IN_UPGRADE_DATABASE")
        db.query(args.database, """
BEGIN;
INSERT INTO public.ndvi_annual(province,year,ndvi_mean,cache_version) VALUES('Bangkok Metropolis',2025,0.42,9);
INSERT INTO public.province_lst_annual(province,year,lst_mean,cache_version) VALUES('Bangkok Metropolis',2025,31.25,9);
INSERT INTO public.district_ndvi_annual(province,district,year,ndvi_mean,cache_version)
 SELECT province,name_en,2025,0.37,9 FROM public.districts ORDER BY province,name_en LIMIT 1;
COMMIT;
""", stage="baseline")
        result = {"synthetic_sentinels_created": 3, "database": args.database}
    elif args.action == "before":
        result = snapshot(db, args.database, "baseline")
        path = db.evidence_dir / f"{args.database}-preservation-before.json"
        if path.exists():
            raise dbmodule.SafetyError("PRESERVATION_SNAPSHOT_ALREADY_EXISTS")
        db.write_json(path.name, result)
    else:
        before = json.loads((db.evidence_dir / f"{args.database}-preservation-before.json").read_text(encoding="utf-8"))
        after = snapshot(db, args.database, "gis")
        result = {"database": args.database, "all_16_table_data_unchanged": before["tables"] == after["tables"],
                  "legacy_columns_constraints_indexes_functions_auth_trigger_rls_unchanged": before["legacy_structure"] == after["legacy_structure"],
                  "before": before, "after": after}
        db.write_json(f"{args.database}-preservation-result.json", result)
        if not (result["all_16_table_data_unchanged"] and result["legacy_columns_constraints_indexes_functions_auth_trigger_rls_unchanged"]):
            raise dbmodule.SafetyError("LEGACY_PRESERVATION_MISMATCH")
    print(json.dumps({key: value for key, value in result.items() if key not in {"tables", "legacy_structure", "before", "after", "legacy_sources"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
