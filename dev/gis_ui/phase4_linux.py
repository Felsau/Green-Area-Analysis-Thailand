"""Pinned, network-free Linux GeoTIFF scientific tests and synthetic fixtures.

Only the attested existing local GIS runtime is used. No migrations, dotenv,
database mutations, production paths or new images/dependencies are involved.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from uuid import uuid4

spec = importlib.util.spec_from_file_location('phase4_science_base', Path(__file__).with_name('phase3_local.py'))
p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p
spec.loader.exec_module(p)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('tests', 'fixtures'))
    parser.add_argument('--runtime-dir', type=Path, required=True)
    args = parser.parse_args()
    local = p.Phase3Local(args.runtime_dir)
    local.attest()
    output = local.db.runtime.root / 'phase4'
    output.mkdir(exist_ok=True)
    name = 'gis-phase4-science-' + uuid4().hex[:12]
    files = ['green-area-backend/gis_worker/geotiff_provider.py',
        'green-area-backend/gis_worker/geotiff_child.py',
        'green-area-backend/gis_worker/geotiff_worker.py',
        'green-area-backend/tests/test_geotiff_native.py', 'dev/gis_ui/phase4_linux.py']
    source = {f: hashlib.sha256((p.REPO / f).read_bytes()).hexdigest() for f in files}
    prefix = ("import sys,json,platform;sys.path.insert(0,'/work');"
        "import rasterio,numpy,pytest;"
        "print(json.dumps({'python':platform.python_version(),'rasterio':rasterio.__version__,"
        "'gdal':rasterio.__gdal_version__,'numpy':numpy.__version__}));")
    if args.action == 'tests':
        code = prefix + ("raise SystemExit(pytest.main(['-q','-p','no:cacheprovider','--basetemp','/tmp/tests',"
            "'/work/tests/test_geotiff_native.py']))")
        extra = []
    else:
        fixtures = output / 'fixtures'
        fixtures.mkdir(exist_ok=True)
        # No arbitrary output path is accepted: this fixed, owned runtime folder
        # is the only read/write mount, separate from repository and storage.
        extra = ['--mount', 'type=bind,src=' + str(fixtures) + ',dst=/fixtures']
        code = prefix + "\n" + '''
from pathlib import Path
import importlib.util,hashlib
spec=importlib.util.spec_from_file_location('geotiff_test_helper','/work/tests/test_geotiff_native.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
root=Path('/fixtures')
cases=[
 ('ndvi_valid','ndvi_ready',{},True,None,0),
 ('lst_celsius_valid','lst_celsius_ready',{},True,None,30),
 ('lst_kelvin_valid','lst_kelvin_ready',{},True,None,30),
 ('ndvi_range','ndvi_ready',{'values':[[1.5,0],[.5,-9999]]},False,'GEOTIFF_SCIENTIFIC_RANGE',None),
 ('ndvi_scaled','ndvi_ready',{'scale':.0001},False,'GEOTIFF_SCALE_OFFSET_UNSUPPORTED',None),
 ('raw_dn','ndvi_ready',{'dtype':'int16','values':[[1000,0],[5000,-9999]]},False,'GEOTIFF_DTYPE_UNSUPPORTED',None),
 ('wrong_units','lst_celsius_ready',{'units':'kelvin'},False,'GEOTIFF_UNITS_MISMATCH',None),
 ('wrong_crs','ndvi_ready',{'crs':'EPSG:3857'},False,'GEOTIFF_CRS_MISMATCH',None),
 ('wrong_bands','ndvi_ready',{'count':2},False,'GEOTIFF_BANDS_MISMATCH',None),
 ('no_data','ndvi_ready',{'values':[[-9999,-9999],[-9999,-9999]]},False,'GEOTIFF_NO_VALID_PIXELS',None),
 ('nan_pixels','ndvi_ready',{'values':[[float('nan'),0],[.5,-9999]]},False,'GEOTIFF_NONFINITE_PIXELS',None),
 ('missing_profile','ndvi_ready',{'profile_tag':''},False,'GEOTIFF_PROFILE_MISMATCH',None)]
manifest={'synthetic_only':True,'spatially_representative':False,'fixtures':{}}
for name,profile,kwargs,valid,code,mean in cases:
 path=root/(name+'.tif')
 if path.exists():raise RuntimeError('FIXTURE_ALREADY_EXISTS_NO_OVERWRITE')
 raw=helper.create_fixture(path,profile,**kwargs)
 manifest['fixtures'][name]={'filename':path.name,'sha256':hashlib.sha256(raw).hexdigest(),
  'byte_size':len(raw),'profile':profile,'metric':'ndvi' if profile=='ndvi_ready' else 'lst',
  'declared_crs':'EPSG:32647','expected_valid':valid,'expected_error':code,'expected_mean':mean}
path=root/'corrupt.tif'
if path.exists():raise RuntimeError('FIXTURE_ALREADY_EXISTS_NO_OVERWRITE')
# Classic byte-order/magic header, but an invalid TIFF directory.
raw=bytes([73,73,42,0,8,0,0,0,1,0])+bytes(16)
path.write_bytes(raw)
manifest['fixtures']['corrupt']={'filename':path.name,'sha256':hashlib.sha256(raw).hexdigest(),
 'byte_size':len(raw),'profile':'ndvi_ready','metric':'ndvi','declared_crs':'EPSG:32647',
 'expected_valid':False,'expected_error':'GEOTIFF_READ_ERROR','expected_mean':None}
target=root/'manifest.json'
if target.exists():raise RuntimeError('FIXTURE_ALREADY_EXISTS_NO_OVERWRITE')
target.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(json.dumps({'synthetic_fixtures':len(manifest['fixtures']),'manifest_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}))
'''
    args_docker = ['run', '--rm', '--name', name, '--entrypoint', '', '--network=none',
        '--memory=1g', '--memory-swap=1g', '--cpus=1', '--pids-limit=64', '--read-only', '--cap-drop=ALL',
        '--security-opt=no-new-privileges:true', '--user=65534:65534',
        '--tmpfs=/tmp:rw,nosuid,noexec,size=128m,mode=1777',
        '--mount', 'type=bind,src=' + str(p.REPO / 'green-area-backend/gis_worker') + ',dst=/work/gis_worker,readonly',
        '--mount', 'type=bind,src=' + str(p.REPO / 'green-area-backend/tests') + ',dst=/work/tests,readonly',
        '-e', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1', *extra,
        p.m.m.IMAGE, 'python3', '-I', '-B', '-c', code]
    result = local.db.runtime.docker(args_docker)
    local.attest()
    for file, digest in source.items():
        if hashlib.sha256((p.REPO / file).read_bytes()).hexdigest() != digest:
            raise RuntimeError('SCIENTIFIC_SOURCE_CHANGED_DURING_RUN')
    record = {'action': args.action, 'image': p.m.m.IMAGE, 'network': 'none',
        'output': result, 'source_files': source,
        'source_sha256': hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest(),
        'fixture_generator': 'green-area-backend/tests/test_geotiff_native.py:create_fixture',
        'cleanup': 'run --rm; pinned image retained; fixtures retained only in external owned runtime'}
    destination = output / ('linux-science.json' if args.action == 'tests' else 'linux-fixtures.json')
    destination.write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(result)


if __name__ == '__main__':
    main()
