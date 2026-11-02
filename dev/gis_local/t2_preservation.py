"""Reuse T1 snapshots; allow only newly created synthetic profiles in API tests."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('before','after'))
    parser.add_argument('--runtime-dir',type=Path,required=True)
    args=parser.parse_args()
    local_module=load('t2_preservation_local',HERE/'t2_local.py')
    previous=load('t2_preservation_t1',HERE/'t1_preservation.py')
    local=local_module.LocalT2(args.runtime_dir);local.attest()
    result=previous.snapshot(local.db,'postgres','gis')
    profiles=local.db.query('postgres',"SELECT COALESCE(jsonb_object_agg(id::text,md5(to_jsonb(t)::text)),'{}'::jsonb) FROM public.profiles t;").stdout
    result['existing_profile_rows']=json.loads(profiles)
    target=local.directory/'pre-api-preservation.json'
    if args.action=='before':
        if target.exists():raise RuntimeError('REFUSE_REPLACE_PRE_API_SNAPSHOT')
        local.write(target.name,result)
        print(json.dumps({'pre_api_snapshot':True,'existing_profiles':len(result['existing_profile_rows'])}))
    else:
        before=json.loads(target.read_text(encoding='utf-8'))
        unchanged_tables=all(row==result['tables'][name] for name,row in before['tables'].items() if name!='profiles')
        unchanged_profiles=all(value==result['existing_profile_rows'].get(key) for key,value in before['existing_profile_rows'].items())
        output={'legacy_15_non_profile_tables_unchanged':unchanged_tables,
            'preexisting_profile_rows_unchanged':unchanged_profiles,
            'legacy_structure_unchanged':before['legacy_structure']==result['legacy_structure'],
            'new_synthetic_profile_rows':len(result['existing_profile_rows'])-len(before['existing_profile_rows'])}
        local.write('post-api-preservation.json',output)
        print(json.dumps(output))
        if not (unchanged_tables and unchanged_profiles and output['legacy_structure_unchanged']):sys.exit(1)


if __name__=='__main__':main()
