"""W4: apply 032 and 033 through the existing operator method (no CLI exists). No code is changed.
Usage: python -I -B dev/gis_local/t0-rebuild/run_032_033.py <repo> <runtime-dir> <32|33>"""
import importlib.util, json, sys
from pathlib import Path

repo, runtime, version = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
spec = importlib.util.spec_from_file_location('w4_remediation', repo / 'dev/gis_worker/remediation_local.py')
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
review = repo / f'dev/gis_local/t0-rebuild/migration-{version:03d}-independent-review.json'
local = m.Local(runtime)
local.migrate(review, version)
print(json.dumps({'version': version, 'record': json.loads((local.directory / f'migration-{version:03d}.json').read_text(encoding='utf-8'))}))
