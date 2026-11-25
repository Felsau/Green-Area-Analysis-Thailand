"""C17 survey (read-only): which gadm-approx province of the C7 asset could stand in for GADM_PROVINCE.

For every province whose source is gadm-approx in the boundary asset the clone pins (= C7, sha 49473e7e...) and whose
bbox centre is west of 102 E (UTM 47, the zone the test helpers use), the module tests/test_ldd_policy_native.py is
imported, GADM_PROVINCE is set in memory only (the file is never edited), and the three tests that use it are called
directly with fixtures built by the module's own outline_of() and a fresh tmp_path each time:
  test_parcel_accepted_by_the_old_0002_degree_buffer_is_not_newly_rejected
  test_a_province_without_a_package_outline_keeps_the_gadm_label
  test_v1_rebuild_keeps_the_frozen_legacy_rules_for_existing_editions
Also recorded: whether edge_cases() finds a vertex, and how far (degrees) the farthest corner of its legacy_edge
square lies from the GADM outline (the pre-v2 validator accepts up to a 0.002 degree buffer).
Usage: python -B c17-gadm-province-survey.py <clone-c17>\green-area-backend <out.json>
"""
import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
B = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2])
sys.path[:0] = [str(B), str(B / 'tests')]
import test_ldd_policy_native as t  # noqa: E402
from gis_worker import ldd_provider as ldd  # noqa: E402
from fiona.transform import transform_geom  # noqa: E402
from shapely.geometry import mapping, shape  # noqa: E402

TESTS = ('test_parcel_accepted_by_the_old_0002_degree_buffer_is_not_newly_rejected',
         'test_a_province_without_a_package_outline_keeps_the_gadm_label',
         'test_v1_rebuild_keeps_the_frozen_legacy_rules_for_existing_editions')
asset = ldd._asset(ldd.BOUNDARY_LDD_ASSET, ldd.BOUNDARY_LDD_SHA256)
base = {f['properties']['name']: f['geometry'] for f in ldd._asset('province_boundaries.json', ldd.BOUNDARY_SHA256)['features']}
original = t.GADM_PROVINCE
bkk = t.outline_of(t.PROVINCE)
rows = []


def short(exc):
    tb = traceback.extract_tb(exc.__traceback__)
    here = [f for f in tb if f.filename.endswith('test_ldd_policy_native.py')]
    where = f'line {here[-1].lineno}' if here else ''
    return f'{type(exc).__name__}: {str(exc).splitlines()[0][:120] if str(exc) else ""} ({where})'


for f in asset['features']:
    p = f['properties']
    if p['source'] != 'gadm-approx':
        continue
    minx, miny, maxx, maxy = shape(f['geometry']).bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    if cx >= 102:
        continue
    name = p['name']
    t.GADM_PROVINCE = name                      # in memory only
    row = {'province': name, 'bbox_centre_lon': round(cx, 4), 'bbox_centre_lat': round(cy, 4)}
    try:
        gadm = t.outline_of(name)
    except BaseException as exc:  # noqa: BLE001
        row['outline_of'] = short(exc)
        rows.append(row)
        continue
    try:
        cases = t.edge_cases(gadm)
        row['edge_cases'] = 'found'
        geo = shape(transform_geom('EPSG:32647', 'EPSG:4326', mapping(cases['legacy_edge'])))
        g = shape(base[name])
        row['legacy_edge_farthest_deg'] = round(max(g.distance(shape({'type': 'Point', 'coordinates': c}))
                                                    for c in geo.exterior.coords), 6)
        row['legacy_edge_distance_m'] = round(gadm['exact'].distance(cases['legacy_edge']), 1)
    except BaseException as exc:  # noqa: BLE001  (pytest.fail raises an OutcomeException)
        if isinstance(exc, KeyboardInterrupt):
            raise
        row['edge_cases'] = 'not found: ' + short(exc)
    results = {}
    for test in TESTS:
        fn = getattr(t, test)
        tmp = Path(tempfile.mkdtemp(prefix='c17survey-'))
        try:
            kwargs = {'tmp_path': tmp, 'gadm': gadm}
            if 'bkk' in fn.__code__.co_varnames[:fn.__code__.co_argcount]:
                kwargs['bkk'] = bkk
            fn(**kwargs)
            results[test] = 'pass'
        except BaseException as exc:  # noqa: BLE001
            if isinstance(exc, KeyboardInterrupt):
                raise
            results[test] = short(exc)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    row['tests'] = results
    row['all_three_pass'] = all(v == 'pass' for v in results.values())
    rows.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)
t.GADM_PROVINCE = original
summary = {'asset_sha256': ldd.BOUNDARY_LDD_SHA256, 'gadm_province_in_file': original, 'provinces_tried': len(rows),
           'all_three_pass': [r['province'] for r in rows if r.get('all_three_pass')], 'rows': rows}
OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
print('ALL THREE PASS:', summary['all_three_pass'])
