"""Isolated Phase4 API/storage/guard and affected-regression checks."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime-dir',type=Path,required=True)
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('phase4_units_base',Path(__file__).with_name('phase3_units.py'))
    old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
    import pytest
    original=pytest.main
    def run(argv,**kwargs):
        extra=[str(Path(__file__).resolve().parents[2]/f) for f in (
            'green-area-backend/tests/test_geotiff_upload_api.py','dev/gis_local/tests/test_geotiff_worker_guard.py')]
        return original([*argv,*extra],**kwargs)
    # Reuse the tested dotenv/nonlocal-socket suppression, output collection and
    # bounded temp handling; redirect only this phase's external output folder.
    old_main=Path.__truediv__
    def divide(path,other):
        return old_main(path,'phase4' if path==args.runtime_dir and other=='phase3' else other)
    with patch.object(pytest,'main',run),patch.object(Path,'__truediv__',divide):
        return old.main()


if __name__=='__main__':
    raise SystemExit(main())
