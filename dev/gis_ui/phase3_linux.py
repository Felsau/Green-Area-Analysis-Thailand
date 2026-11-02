"""Network-free Linux scientific/unit check using the already pinned GIS image."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from uuid import uuid4

spec = importlib.util.spec_from_file_location('phase3_operator', Path(__file__).with_name('phase3_local.py'))
p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p
spec.loader.exec_module(p)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-dir', type=Path, required=True)
    args = parser.parse_args()
    local = p.Phase3Local(args.runtime_dir)
    local.attest()
    name = 'gis-phase3-science-' + uuid4().hex[:12]
    code = ("import sys,json,platform;sys.path.insert(0,'/work');"
        "import rasterio,fiona,shapely,numpy,pytest;"
        "print(json.dumps({'python':platform.python_version(),'rasterio':rasterio.__version__,"
        "'rasterio_gdal':rasterio.__gdal_version__,'fiona':fiona.__version__,"
        "'fiona_gdal':fiona.__gdal_version__,'shapely':shapely.__version__,'numpy':numpy.__version__}));"
        "raise SystemExit(pytest.main(['-q','-p','no:cacheprovider','--basetemp','/tmp/tests',"
        "'/work/tests/test_processing_provider.py','/work/tests/test_gis_worker_unit.py','/work/tests/test_gis_native_provider.py']))")
    result = local.db.runtime.docker(['run', '--rm', '--name', name, '--entrypoint', '', '--network=none',
        '--memory=1g', '--memory-swap=1g', '--cpus=1', '--pids-limit=64', '--read-only', '--cap-drop=ALL',
        '--security-opt=no-new-privileges:true', '--user=65534:65534',
        '--tmpfs=/tmp:rw,nosuid,noexec,size=128m,mode=1777',
        '--mount', 'type=bind,src=' + str(p.REPO / 'green-area-backend/gis_worker') + ',dst=/work/gis_worker,readonly',
        '--mount', 'type=bind,src=' + str(p.REPO / 'green-area-backend/tests') + ',dst=/work/tests,readonly',
        '--mount', 'type=bind,src=' + str(p.REPO / 'green-area-backend/gee_utils.py') + ',dst=/work/gee_utils.py,readonly',
        '--mount', 'type=bind,src=' + str(p.REPO / 'green-area-backend/routers/ndvi/compute.py') + ',dst=/work/routers/ndvi/compute.py,readonly',
        '--mount', 'type=bind,src=' + str(p.REPO / 'green-area-backend/routers/lst.py') + ',dst=/work/routers/lst.py,readonly',
        '--mount', 'type=bind,src=' + str(p.REPO / 'green-area-backend/gee_utils.py') + ',dst=/app/legacy/gee_utils.py,readonly',
        '--mount', 'type=bind,src=' + str(p.REPO / 'green-area-backend/routers/ndvi/compute.py') + ',dst=/app/legacy/ndvi_compute.py,readonly',
        '--mount', 'type=bind,src=' + str(p.REPO / 'green-area-backend/routers/lst.py') + ',dst=/app/legacy/lst.py,readonly',
        '-e', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1', p.m.m.IMAGE, 'python3', '-I', '-B', '-c', code])
    local.attest()
    local.write('linux-science.json', {'image': p.m.m.IMAGE, 'network': 'none', 'output': result,
        'cleanup': 'run --rm; pinned image retained', 'source': p.m.m.fingerprint()})
    print(result)

if __name__ == '__main__':
    main()
