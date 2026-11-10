"""Seed a new T0 runtime dir with the files the attested operators read from fixed places (W4 rebuild, GIS_BRANCH).

Writes, and never overwrites:
  <runtime>/t3-remediation/initial-source-state.json  from remediation_local.fingerprint(), the function the operators use
  <runtime>/phase2/evidence-index.json                copy of phase2-evidence-index.json (phase3_local check_frozen)
  <runtime>/phase3/evidence-index.json                copy of phase3-evidence-index.json (phase4_audit)
  <runtime>/phase4/review-036.json                    copy of review-036.json (phase4_audit)
  <runtime>/a4-geotiff-prepare/before.json            copy of a4-geotiff-prepare-before.json (041 proof reads its sql)
  <runtime>/a4-2-geotiff-publication/before.json      copy of a4-2-geotiff-publication-before.json (042 proof reads its sql)
The 032-036 review records stay here and are passed to the operators with --review.
Touches no container, volume or database. Run it on the local branch named by GIS_BRANCH, before migrating 032.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
COPIES = {
    'phase2/evidence-index.json': 'phase2-evidence-index.json',
    'phase3/evidence-index.json': 'phase3-evidence-index.json',
    'phase4/review-036.json': 'review-036.json',
    'a4-geotiff-prepare/before.json': 'a4-geotiff-prepare-before.json',
    'a4-2-geotiff-publication/before.json': 'a4-2-geotiff-publication-before.json',
}
STATE = 't3-remediation/initial-source-state.json'


def remediation():
    spec = importlib.util.spec_from_file_location('seed_runtime_remediation', REPO / 'dev/gis_worker/remediation_local.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def seed(runtime: Path, m=None) -> dict:
    m = m or remediation()
    runtime = runtime.resolve()
    if not runtime.is_dir():
        raise RuntimeError('RUNTIME_DIR_MISSING')
    targets = [runtime / STATE, *(runtime / rel for rel in COPIES)]
    existing = [str(t) for t in targets if t.exists()]
    if existing:
        raise RuntimeError('REFUSING_TO_OVERWRITE: ' + ', '.join(existing))
    fp = m.fingerprint()
    if fp['branch'] != m.GIS_BRANCH:
        raise RuntimeError('WRONG_BRANCH')
    written = {}
    state = runtime / STATE
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({'branch': fp['branch'], 'head': fp['head'], 'files': fp['files']}, indent=2), encoding='utf-8')
    written[STATE] = hashlib.sha256(state.read_bytes()).hexdigest()
    for rel, name in COPIES.items():
        target = runtime / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / name, target)
        written[rel] = hashlib.sha256(target.read_bytes()).hexdigest()
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir', type=Path, required=True)
    print(json.dumps(seed(parser.parse_args().runtime_dir), indent=2))


if __name__ == '__main__':
    main()
