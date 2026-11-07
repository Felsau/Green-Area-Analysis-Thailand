"""ldd-policy-v2 on real Shapefile bytes written by fiona (synthetic parcels only).

Expected results are fixed geometry: 100 m x 100 m squares in EPSG:32647 are
exactly 10 000 m2. Boundary cases are placed relative to the pinned Bangkok
boundary asset and their preconditions are asserted, never assumed.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import tempfile
import zipfile

import pytest

fiona = pytest.importorskip('fiona')
pytest.importorskip('rasterio')
shapely_geometry = pytest.importorskip('shapely.geometry')

from fiona.crs import CRS as FionaCRS  # noqa: E402
from fiona.transform import transform_geom  # noqa: E402
from shapely.geometry import box, mapping, shape  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from gis_worker import ldd_policy as policy  # noqa: E402
from gis_worker import ldd_prepare_provider as prep  # noqa: E402
from gis_worker import ldd_provider as ldd  # noqa: E402

ID = '11111111-1111-4111-8111-111111111111'
PROVINCE = 'Bangkok Metropolis'   # the validator reads the producer's own outline for it (source ldd-package)
GADM_PROVINCE = 'Chiang Mai'      # no package supplied an outline: assess() reads the same GADM geometry as the pre-v2 validator
TEXT = {'LUL1_CODE': 'str:4', 'LU_CODE': 'str:20', 'Shape_Area': 'float'}


def make_zip(features, *, schema=None, crs=32647):
    schema = schema or TEXT
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'parcels.shp'
        with fiona.open(path, 'w', driver='ESRI Shapefile', crs=FionaCRS.from_epsg(crs), encoding='utf-8',
                        schema={'geometry': 'Polygon', 'properties': schema}) as sink:
            for geometry, properties in features:
                sink.write({'geometry': geometry, 'properties': properties})
        output = BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            for part in sorted(Path(folder).iterdir()):
                archive.writestr(part.name, part.read_bytes())
        return output.getvalue()


def request(raw, crs='EPSG:32647', province=PROVINCE):
    return {'upload_id': ID, 'manifest': {'schema_version': 1, 'provider': 'real',
        'sha256': hashlib.sha256(raw).hexdigest(), 'byte_size': len(raw), 'provenance': 'local-ldd-upload-v1',
        'crs': crs, 'data_kind': 'polygon', 'attributes': list(ldd.REQUIRED_FIELDS)},
        'input_hash': 'a' * 64, 'input_revision': 1, 'attempt_number': 1, 'province': province,
        'data_year': 2025, 'encoding': 'auto'}


def run(tmp_path, raw, crs='EPSG:32647', collect=False, province=PROVINCE):
    req = request(raw, crs, province)
    (tmp_path / (req['manifest']['sha256'] + '.zip')).write_bytes(raw)
    return ldd.assess(req, storage_root=tmp_path, collect=collect)


def outline_of(name, asset=(None, None)):
    """The outline in UTM 47N, from the asset assess() reads unless another (file, hash) is given."""
    boundaries = ldd._asset(asset[0] or ldd.BOUNDARY_LDD_ASSET, asset[1] or ldd.BOUNDARY_LDD_SHA256)
    feature = next(f for f in boundaries['features'] if f['properties']['name'] == name)
    exact = shape(transform_geom('EPSG:4326', 'EPSG:32647', feature['geometry']))
    return {'exact': exact, 'minor': exact.buffer(policy.BOUNDARY_MINOR_M),
            'review': exact.buffer(policy.BOUNDARY_REVIEW_M), 'inside': exact.representative_point()}


@pytest.fixture(scope='module')
def bkk():
    return outline_of(PROVINCE)


@pytest.fixture(scope='module')
def gadm():
    return outline_of(GADM_PROVINCE)


def square(cx, cy, half=50.0):
    return box(cx - half, cy - half, cx + half, cy + half)


def inside_square(bkk, dx=0.0, half=50.0):
    p = bkk['inside']
    g = square(p.x + dx, p.y, half)
    assert bkk['exact'].covers(g)
    return g


def edge_cases(bkk):
    """Find a boundary vertex whose outward offsets satisfy each tier."""
    exact, minor, review, inside = bkk['exact'], bkk['minor'], bkk['review'], bkk['inside']
    polygons = getattr(exact, 'geoms', [exact])
    ring = max(polygons, key=lambda g: g.area).exterior.coords
    for x, y in list(ring)[::7]:
        ux, uy = x - inside.x, y - inside.y
        n = math.hypot(ux, uy)
        ux, uy = ux / n, uy / n
        slightly = square(x + ux * 80, y + uy * 80, 10)
        legacy_edge = square(x + ux * 214, y + uy * 214, 2)
        far = square(x + ux * 5000, y + uy * 5000, 10)
        core = square(x - ux * 700, y - uy * 700, 100)
        spur = square(x + ux * 500, y + uy * 500, 5)
        reviewed = unary_union([core, spur])
        if (not exact.covers(slightly) and minor.covers(slightly) and not review.intersects(far)
                and not exact.intersects(legacy_edge) and minor.covers(legacy_edge) and exact.distance(legacy_edge) > 200
                and exact.covers(core) and not minor.covers(spur) and review.covers(spur)
                and reviewed.geom_type == 'MultiPolygon'):
            return {'slightly': slightly, 'far': far, 'reviewed': reviewed, 'legacy_edge': legacy_edge}
    pytest.fail('no boundary vertex satisfied the preconditions')


def parcel(geometry, main='U', code='U101', area=None):
    geometry = geometry if isinstance(geometry, dict) else mapping(geometry)
    return geometry, {'LUL1_CODE': main, 'LU_CODE': code, 'Shape_Area': shape(geometry).area if area is None else area}


def codes(items):
    return {item['code']: item['count'] for item in items}


# ------------------------------------------------------------ area and mapping

def test_geometry_area_expected_results_and_policy_markers(tmp_path, bkk):
    raw = make_zip([parcel(inside_square(bkk)), parcel(inside_square(bkk, 300), 'A', 'A101')])
    report, details = run(tmp_path, raw)
    assert report['valid'] and report['error_code'] is None and set(report['checks']) == set(ldd.CHECKS)
    assert report['statistics']['total_area_m2'] == pytest.approx(20000, abs=1e-6)
    assert report['statistics']['area_by_main_m2'] == pytest.approx({'U': 10000, 'A': 10000, 'F': 0, 'W': 0, 'M': 0})
    assert {'LDD_POLICY_V2', 'FIELD_PROFILE_LDD_LU_TEXT_V1'} <= set(codes(report['warnings']))
    assert details['outcome'] == 'accepted'
    assert details['policy']['area_method'] == 'geometry-area-utm-v1'


def test_explicit_mapping_accepts_other_letter_case_and_records_source_names(tmp_path, bkk):
    schema = {'lul1_code': 'str:4', 'Lu_Code': 'str:20', 'SHAPE_AREA': 'float'}
    geometry = mapping(inside_square(bkk))
    raw = make_zip([(geometry, {'lul1_code': 'U', 'Lu_Code': 'U101', 'SHAPE_AREA': 10000.0})], schema=schema)
    report, details = run(tmp_path, raw)
    assert report['valid']
    assert details['field_mapping'] == {'main_code': 'lul1_code', 'lu_code': 'Lu_Code', 'declared_area': 'SHAPE_AREA'}
    assert set(details['source_fields']) == set(schema)


@pytest.mark.parametrize('schema', [
    {'LUL1_CODE': 'str:4', 'LU_CODE': 'str:20'},
    {'LUL1_CODE': 'str:4', 'LU_CODE': 'str:20', 'AREA_RAI': 'float'},
])
def test_missing_mapping_field_is_rejected_not_guessed(tmp_path, bkk, schema):
    props = {k: ('U' if k == 'LUL1_CODE' else 'U101' if k == 'LU_CODE' else 6.25) for k in schema}
    report, details = run(tmp_path, make_zip([(mapping(inside_square(bkk)), props)], schema=schema))
    assert not report['valid'] and report['error_code'] == 'ATTRIBUTES_MISSING'
    assert details['outcome'] == 'rejected'


# The real layouts, reduced to the fields that decide the profile (types as in the real DBF headers).
L2567 = {'LUL1_CODE': 'str:4', 'LU_CODE': 'str:20', 'LU_ID_L1': 'float', 'Shape_Area': 'float', 'AREA_SQM': 'int'}
L2568 = {'LUL1_CODE': 'str:4', 'LU_CODE': 'str:20', 'LU_ID_L1': 'float', 'AREA_SQM': 'int', 'AREA_RAI': 'int'}
L2568_NO_LUL1 = {'LU_CODE': 'str:14', 'LU_ID_L1': 'float', 'AREA_SQM': 'int', 'AREA_RAI': 'int'}


@pytest.mark.parametrize('schema,profile,fields', [
    (L2567, 'ldd-lu-text-v1', {'main_code': 'LUL1_CODE', 'lu_code': 'LU_CODE', 'declared_area': 'Shape_Area'}),
    (L2568, 'ldd-lu-area-sqm-v1', {'main_code': 'LUL1_CODE', 'lu_code': 'LU_CODE', 'declared_area': 'AREA_SQM'}),
    (L2568_NO_LUL1, 'ldd-lu-id-l1-area-sqm-v1', {'main_code': 'LU_ID_L1', 'lu_code': 'LU_CODE', 'declared_area': 'AREA_SQM'}),
])
def test_2567_and_2568_layouts_each_resolve_to_one_profile(tmp_path, bkk, schema, profile, fields):
    values = {'LUL1_CODE': 'A', 'LU_CODE': 'A101', 'LU_ID_L1': 2.0, 'Shape_Area': 10000.0, 'AREA_SQM': 10000, 'AREA_RAI': 6}
    raw = make_zip([(mapping(inside_square(bkk)), {k: values[k] for k in schema})], schema=schema)
    report, details = run(tmp_path, raw)
    assert report['valid'] and details['field_profile'] == profile and details['field_mapping'] == fields
    assert report['statistics']['area_by_main_m2']['A'] == pytest.approx(10000) and details['declared_area_units'] == 'm2'
    warnings = codes(report['warnings'])
    assert 'FIELD_PROFILE_' + profile.upper().replace('-', '_') in warnings
    assert 'AREA_DECLARED_MINOR_DIFF' not in warnings                       # AREA_SQM is whole square metres
    # LU_ID_L1 is a float in the real files, so reading it as the main class is shown, not hidden.
    assert ('NUMERIC_MAIN_CODE_NORMALISED' in warnings) is (profile == 'ldd-lu-id-l1-area-sqm-v1')


@pytest.mark.parametrize('level_1,reason', [(1.0, 'LU_CODE_MAIN_CONFLICT'), (521.0, 'MAIN_CODE_UNRECOGNISED'),
                                            (0.0, 'MAIN_CODE_UNRECOGNISED')])
def test_a_level_1_id_that_disagrees_with_the_code_is_reviewed_not_trusted(tmp_path, bkk, level_1, reason):
    props = {'LU_CODE': 'A101', 'LU_ID_L1': level_1, 'AREA_SQM': 10000, 'AREA_RAI': 6}
    report, details = run(tmp_path, make_zip([(mapping(inside_square(bkk)), props)], schema=L2568_NO_LUL1))
    assert not report['valid'] and report['error_code'] == 'UNKNOWN_CODE_REVIEW_REQUIRED' and details['outcome'] == 'review_required'
    (sample,) = details['unknown_samples'].values()
    assert sample['reason'] == reason and sample['count'] == 1


def test_area_sqm_is_compared_with_the_geometry_like_shape_area(tmp_path, bkk):
    props = {'LU_CODE': 'A101', 'LU_ID_L1': 2.0, 'AREA_SQM': 11000, 'AREA_RAI': 7}
    report, details = run(tmp_path, make_zip([(mapping(inside_square(bkk)), props)], schema=L2568_NO_LUL1))
    assert report['error_code'] == 'AREA_DECLARED_MISMATCH_REVIEW_REQUIRED' and details['outcome'] == 'review_required'


@pytest.mark.parametrize('declared,valid,warning,error', [
    (10000.0, True, None, None),
    (10050.0, True, 'AREA_DECLARED_MINOR_DIFF', None),
    (11000.0, False, None, 'AREA_DECLARED_MISMATCH_REVIEW_REQUIRED'),
])
def test_declared_area_is_compared_against_geometry_area(tmp_path, bkk, declared, valid, warning, error):
    report, details = run(tmp_path, make_zip([parcel(inside_square(bkk), area=declared)]))
    assert report['valid'] is valid and report['error_code'] == error
    assert report['statistics']['total_area_m2'] == pytest.approx(10000, abs=1e-6)  # geometry, not declared
    if warning:
        assert warning in codes(report['warnings'])
    if error:
        assert details['outcome'] == 'review_required'


def wgs84_zip(bkk, declared):
    geographic = transform_geom('EPSG:32647', 'EPSG:4326', mapping(inside_square(bkk)))
    return make_zip([(geographic, {'LUL1_CODE': 'U', 'LU_CODE': 'U101', 'Shape_Area': declared})], crs=4326)


def test_wgs84_source_area_in_metres_declared_m2_matches_without_warning(tmp_path, bkk):
    report, details = run(tmp_path, wgs84_zip(bkk, 10000.0), crs='EPSG:4326')
    assert report['valid'] and details['outcome'] == 'accepted'
    assert report['statistics']['total_area_m2'] == pytest.approx(10000, rel=1e-4)
    assert details['declared_area_units'] is None
    assert 'DECLARED_AREA_UNITS_UNVERIFIED' not in codes(report['warnings'])


def test_wgs84_declared_area_in_other_units_is_flagged_not_ignored(tmp_path, bkk):
    report, details = run(tmp_path, wgs84_zip(bkk, 0.0000008), crs='EPSG:4326')
    assert not report['valid'] and report['error_code'] == 'AREA_DECLARED_MISMATCH_REVIEW_REQUIRED'
    assert 'DECLARED_AREA_UNITS_UNVERIFIED' in codes(report['warnings']) and details['outcome'] == 'review_required'


# ------------------------------------------------------------ codes

@pytest.mark.parametrize('schema,main,code,expected_main,valid,reason', [
    ({'LUL1_CODE': 'int', 'LU_CODE': 'str:20', 'Shape_Area': 'float'}, 1, 'U101', 'U', True, None),
    ({'LUL1_CODE': 'float', 'LU_CODE': 'str:20', 'Shape_Area': 'float'}, 2.0, 'A101', 'A', True, None),
    ({'LUL1_CODE': 'str:4', 'LU_CODE': 'str:20', 'Shape_Area': 'float'}, '2', 'A101', 'A', True, None),
    ({'LUL1_CODE': 'str:4', 'LU_CODE': 'str:20', 'Shape_Area': 'float'}, 'A', 'A300/A400', 'A', True, None),
    ({'LUL1_CODE': 'int', 'LU_CODE': 'int', 'Shape_Area': 'float'}, 2, 2101, None, False, 'NUMERIC_CODE_NO_APPROVED_CROSSWALK'),
    ({'LUL1_CODE': 'int', 'LU_CODE': 'str:20', 'Shape_Area': 'float'}, 2, '2101', None, False, 'NUMERIC_CODE_NO_APPROVED_CROSSWALK'),
    ({'LUL1_CODE': 'str:4', 'LU_CODE': 'str:20', 'Shape_Area': 'float'}, 'U', 'U101/U999', None, False, 'LU_CODE_NOT_IN_LEGEND'),
])
def test_text_integer_float_numeric_codes(tmp_path, bkk, schema, main, code, expected_main, valid, reason):
    geometry = mapping(inside_square(bkk))
    raw = make_zip([(geometry, {'LUL1_CODE': main, 'LU_CODE': code, 'Shape_Area': 10000.0})], schema=schema)
    report, details = run(tmp_path, raw)
    assert report['valid'] is valid
    stats = report['statistics']
    if valid:
        assert stats['area_by_main_m2'][expected_main] == pytest.approx(10000)
    else:
        assert report['error_code'] == 'UNKNOWN_CODE_REVIEW_REQUIRED' and details['outcome'] == 'review_required'
        assert stats['unknown_code_count'] == 1 and stats['unknown_area_m2'] == pytest.approx(10000)
        (sample,) = details['unknown_samples'].values()
        assert sample['reason'] == reason and sample['count'] == 1 and sample['value'] == str(code)
    if isinstance(code, str) and '/' in code:
        assert stats['composite_feature_count'] == 1  # composite never lost, known or not


def test_codes_of_the_official_table_outside_the_first_legend_are_accepted(tmp_path, bkk):
    first = ldd._asset('ldd_codes.json', ldd.LEGEND_SHA256)['codes']
    assert 'A205' not in first and 'A302' not in first
    raw = make_zip([parcel(inside_square(bkk), 'A', 'A205'), parcel(inside_square(bkk, 300), 'A', 'A205/A302')])
    report, details = run(tmp_path, raw)
    assert report['valid'] and details['outcome'] == 'accepted' and report['statistics']['unknown_code_count'] == 0
    assert report['statistics']['area_by_main_m2']['A'] == pytest.approx(20000) and report['statistics']['composite_feature_count'] == 1
    # The frozen pre-v2 validator keeps the first legend, so it still refuses what only the second one knows.
    legacy = ldd.validate_legacy_v1(request(raw), storage_root=tmp_path)
    assert legacy['valid'] is False and legacy['error_code'] == 'UNKNOWN_CODE_REVIEW_REQUIRED'


def test_a_plus_between_codes_of_one_class_is_accepted_with_a_visible_warning(tmp_path, bkk):
    raw = make_zip([parcel(inside_square(bkk), 'A', 'A101+A202'), parcel(inside_square(bkk, 300), 'A', 'A101/A202')])
    report, details = run(tmp_path, raw)
    assert report['valid'] and report['statistics']['unknown_code_count'] == 0
    assert report['statistics']['composite_feature_count'] == 2 and report['statistics']['area_by_main_m2']['A'] == pytest.approx(20000)
    assert codes(report['warnings'])['COMPOSITE_PLUS_SEPARATOR'] == 1          # only the "+" parcel, the "/" one is plain
    assert details['outcome'] == 'accepted_with_warnings'
    assert details['feature_outcomes'] == {'accepted': 1, 'accepted_with_warnings': 1, 'review_required': 0, 'rejected': 0}


def test_a_plus_joining_classes_is_reviewed_not_guessed(tmp_path, bkk):
    raw = make_zip([parcel(inside_square(bkk), 'A', 'M201+A101'), parcel(inside_square(bkk, 300))])
    report, details = run(tmp_path, raw)
    assert not report['valid'] and report['error_code'] == 'UNKNOWN_CODE_REVIEW_REQUIRED' and details['outcome'] == 'review_required'
    (sample,) = details['unknown_samples'].values()
    assert sample['value'] == 'M201+A101' and sample['reason'] == 'LU_CODE_MAIN_CONFLICT' and sample['count'] == 1
    assert 'COMPOSITE_PLUS_SEPARATOR' not in codes(report['warnings'])


# ------------------------------------------------------------ boundary

def test_slightly_outside_is_a_warning_far_outside_is_rejected(tmp_path, bkk):
    cases = edge_cases(bkk)
    big = inside_square(bkk, half=400)  # keeps the dataset outside-area share small
    report, details = run(tmp_path, make_zip([parcel(big), parcel(cases['slightly'])]))
    assert report['valid'] and 'BOUNDARY_OUTSIDE_MINOR' in codes(report['warnings'])
    assert details['outcome'] == 'accepted_with_warnings' and details['boundary']['minor'] == 1
    assert details['feature_outcomes'] == {'accepted': 1, 'accepted_with_warnings': 1, 'review_required': 0, 'rejected': 0}
    far_dir = tmp_path / 'far'; far_dir.mkdir()
    report, details = run(far_dir, make_zip([parcel(big), parcel(cases['far'])]))
    assert not report['valid'] and report['error_code'] == 'OUTSIDE_PROVINCE' and details['outcome'] == 'rejected'
    assert details['feature_outcomes'] == {'accepted': 1, 'accepted_with_warnings': 0, 'review_required': 0, 'rejected': 1}
    assert report['statistics']['geometry_error_count'] == 1 and report['statistics']['feature_count'] == 2


def test_small_part_beyond_tolerance_needs_review(tmp_path, bkk):
    cases = edge_cases(bkk)
    big = inside_square(bkk, half=400)
    report, details = run(tmp_path, make_zip([parcel(big), parcel(cases['reviewed'])]))
    assert not report['valid'] and report['error_code'] == 'BOUNDARY_OUTSIDE_REVIEW_REQUIRED'
    assert details['outcome'] == 'review_required'


def test_dataset_outside_share_needs_both_share_and_absolute_area(tmp_path, bkk, monkeypatch):
    cases = edge_cases(bkk)
    raw = make_zip([parcel(cases['slightly'])])  # only parcel, partly outside: share high, area < 1 ha
    report, details = run(tmp_path, raw)
    assert report['valid'] and details['outcome'] == 'accepted_with_warnings'
    monkeypatch.setattr(policy, 'DATASET_OUTSIDE_MIN_M2', 0.0)
    again = tmp_path / 'again'; again.mkdir()
    report, details = run(again, raw)
    assert not report['valid'] and report['error_code'] == 'BOUNDARY_OUTSIDE_AREA_REVIEW_REQUIRED'
    assert details['outcome'] == 'review_required'


def test_parcel_accepted_by_the_old_0002_degree_buffer_is_not_newly_rejected(tmp_path, gadm):
    # Same GADM outline for both validators, so the comparison is like with like. For a province whose
    # outline comes from a package the two differ by design (see the official-outline tests below).
    cases = edge_cases(gadm)
    big = inside_square(gadm, half=400)
    raw = make_zip([parcel(big), parcel(cases['legacy_edge'])])
    report, details = run(tmp_path, raw, province=GADM_PROVINCE)
    assert report['valid'] and 'BOUNDARY_OUTSIDE_MINOR' in codes(report['warnings'])
    req = request(raw, province=GADM_PROVINCE)
    assert ldd.validate_legacy_v1(req, storage_root=tmp_path)['valid'] is True


# ------------------------------------------------------------ boundary asset: producer outline vs GADM

def square_in(region, half=50.0):
    """A 100 m square lying inside `region`, at the representative point of its largest piece."""
    pieces = sorted(getattr(region, 'geoms', [region]), key=lambda g: -g.area)
    p = pieces[0].representative_point()
    g = square(p.x, p.y, half)
    assert region.covers(g)
    return g


def test_the_producers_outline_decides_for_a_province_a_package_supplied(tmp_path, bkk):
    gadm_bkk = outline_of(PROVINCE, ('province_boundaries.json', ldd.BOUNDARY_SHA256))
    only_official = square_in(bkk['exact'].difference(gadm_bkk['minor']))   # inside the producer's outline, > 225 m outside GADM
    raw = make_zip([parcel(only_official)])
    report, details = run(tmp_path, raw)
    assert report['valid'] and details['outcome'] == 'accepted'
    assert details['boundary_source'] == 'ldd-package' and report['boundary_sha256'] == ldd.BOUNDARY_LDD_SHA256
    warned = codes(report['warnings'])
    assert 'BOUNDARY_FROM_DATA_PRODUCER' in warned and 'BOUNDARY_APPROXIMATE' not in warned
    # The frozen pre-v2 validator reads the GADM outline and puts the same parcel outside the province.
    legacy = ldd.validate_legacy_v1(request(raw), storage_root=tmp_path)
    assert legacy['valid'] is False and {'code': 'OUTSIDE_PROVINCE', 'count': 1} in legacy['errors']
    assert legacy['boundary_sha256'] == ldd.BOUNDARY_SHA256
    assert ldd.report_failure(request(raw), 'NATIVE_MEMORY_LIMIT')['boundary_sha256'] == ldd.BOUNDARY_SHA256


def test_the_producers_outline_is_stricter_where_gadm_was_generous(tmp_path, bkk):
    gadm_bkk = outline_of(PROVINCE, ('province_boundaries.json', ldd.BOUNDARY_SHA256))
    only_gadm = square_in(gadm_bkk['exact'].difference(bkk['minor']))        # inside GADM, > 225 m outside the producer's outline
    raw = make_zip([parcel(only_gadm)])
    report, details = run(tmp_path, raw)
    assert not report['valid'] and report['error_code'] == 'OUTSIDE_PROVINCE' and details['outcome'] == 'rejected'
    assert ldd.validate_legacy_v1(request(raw), storage_root=tmp_path)['valid'] is True


def test_a_province_without_a_package_outline_keeps_the_gadm_label(tmp_path, gadm):
    report, details = run(tmp_path, make_zip([parcel(inside_square(gadm))]), province=GADM_PROVINCE)
    assert report['valid'] and details['boundary_source'] == 'gadm-approx'
    assert report['boundary_sha256'] == ldd.BOUNDARY_LDD_SHA256
    warned = codes(report['warnings'])
    assert 'BOUNDARY_APPROXIMATE' in warned and 'BOUNDARY_FROM_DATA_PRODUCER' not in warned


def test_an_asset_feature_with_an_unknown_source_is_refused(tmp_path, bkk, monkeypatch):
    real = ldd._asset

    def tampered(name, expected):
        data = real(name, expected)
        if name == ldd.BOUNDARY_LDD_ASSET:
            for feature in data['features']:
                if feature['properties']['name'] == PROVINCE:
                    feature['properties']['source'] = 'somewhere-else'
        return data

    monkeypatch.setattr(ldd, '_asset', tampered)
    report, _ = run(tmp_path, make_zip([parcel(inside_square(bkk))]))
    assert not report['valid'] and report['error_code'] == 'VALIDATION_ASSET_INVALID'


# ------------------------------------------------------------ repair

def spike(bkk):
    p = bkk['inside']
    x, y = p.x, p.y
    # 100 m square with a zero-width spike: invalid, repairable without area change.
    return {'type': 'Polygon', 'coordinates': [[(x, y), (x + 100, y), (x + 100, y + 100), (x + 50, y + 100),
                                                (x + 50, y + 150), (x + 50, y + 100), (x, y + 100), (x, y)]]}


def bowtie(bkk, dx=0.0):
    p = bkk['inside']
    x, y = p.x + dx, p.y
    return {'type': 'Polygon', 'coordinates': [[(x, y), (x + 100, y + 100), (x + 100, y), (x, y + 100), (x, y)]]}


def test_repairable_geometry_is_repaired_logged_and_original_kept(tmp_path, bkk):
    assert not shape(spike(bkk)).is_valid
    raw = make_zip([parcel(spike(bkk), area=10000.0), parcel(inside_square(bkk, 400))])
    report, details = run(tmp_path, raw, collect=True)
    assert report['valid'] and codes(report['warnings'])['GEOMETRY_REPAIRED'] == 1
    (repair,) = details['repairs']
    assert repair['feature'] == 0 and repair['area_before_m2'] == pytest.approx(10000)
    assert repair['area_after_m2'] == pytest.approx(10000) and repair['reason']
    assert details['features'][0]['source'] is not None and details['features'][1]['source'] is None
    assert details['outcome'] == 'accepted_with_warnings'
    assert report['statistics']['geometry_error_count'] == 0


def test_unrepairable_or_area_changing_repair_is_rejected(tmp_path, bkk):
    report, details = run(tmp_path, make_zip([parcel(bowtie(bkk), area=10000.0)]))
    assert not report['valid'] and report['error_code'] == 'GEOMETRY_REPAIR_AREA_CHANGED'
    assert report['statistics']['geometry_error_count'] == 1 and details['outcome'] == 'rejected'


def test_repair_that_changes_geometry_type_is_rejected(tmp_path, bkk, monkeypatch):
    from shapely.geometry import LineString
    monkeypatch.setattr(ldd, '_repair', lambda g: LineString([(0, 0), (1, 1)]))
    report, _ = run(tmp_path, make_zip([parcel(spike(bkk), area=10000.0)]))
    assert not report['valid'] and report['error_code'] == 'GEOMETRY_REPAIR_TYPE_CHANGED'


def test_null_geometry_is_fatal_and_never_dropped(tmp_path, bkk):
    report, _ = run(tmp_path, make_zip([(None, {'LUL1_CODE': 'U', 'LU_CODE': 'U101', 'Shape_Area': 1.0}),
                                       parcel(inside_square(bkk))]))
    assert not report['valid'] and report['error_code'] == 'GEOMETRY_TYPE'
    assert report['statistics']['feature_count'] == 2


def test_too_many_repairs_needs_review(tmp_path, bkk):
    p = bkk['inside']
    features = []
    for i in range(policy.REPAIR_COUNT_MIN_ALLOWED + 1):
        g = spike({'inside': type(p)(p.x + 200 * (i % 6), p.y + 200 * (i // 6))})
        assert bkk['exact'].covers(shape(g).buffer(0))
        features.append(parcel(g, area=10000.0))
    report, details = run(tmp_path, make_zip(features))
    assert not report['valid'] and report['error_code'] == 'GEOMETRY_REPAIR_LIMIT_REVIEW_REQUIRED'
    assert details['outcome'] == 'review_required' and report['statistics']['geometry_error_count'] == 0


# ------------------------------------------------------------ validation -> prepare -> summary

def prepare_request(raw, method):
    from tests.test_ldd_prepare_native import request as packet
    return packet(raw, method_version=method)


def stage(tmp_path, raw):
    source, staging = tmp_path / 'source', tmp_path / 'stage'
    source.mkdir(); staging.mkdir()
    (source / (hashlib.sha256(raw).hexdigest() + '.zip')).write_bytes(raw)
    return source, staging


def test_v1_preparation_refuses_datasets_that_need_the_new_policy(tmp_path, bkk):
    raw = make_zip([parcel(spike(bkk), area=10000.0), parcel(inside_square(bkk, 400))])
    source, staging = stage(tmp_path, raw)
    with pytest.raises(ldd.LddError, match='PREPARE_METHOD_V2_REQUIRED'):
        prep.prepare(prepare_request(raw, prep.METHOD), source_root=source, staging_root=staging)


def test_v2_preparation_uses_the_same_derived_geometry_and_area_as_validation(tmp_path, bkk):
    raw = make_zip([parcel(spike(bkk), area=10000.0), parcel(inside_square(bkk, 400), 'A', 'A101', area=10050.0)])
    source, staging = stage(tmp_path, raw)
    packet = prepare_request(raw, prep.METHOD_V2)
    report, _ = ldd.assess(packet['validation'], storage_root=source)
    outputs = prep.build(packet, source_root=source)
    summary, geometry = json.loads(outputs['ldd_summary']), json.loads(outputs['ldd_geometry'])
    assert summary['total_area_m2'] == pytest.approx(report['statistics']['total_area_m2'], abs=1e-6)
    assert summary['area_by_main_m2'] == pytest.approx(report['statistics']['area_by_main_m2'])
    assert summary['area_by_code_m2'] == pytest.approx({'A101': 10000, 'U101': 10000})
    meta = summary['metadata']
    assert meta['method_version'] == 'ldd-geometry-area-v2' and meta['area_method'] == 'geometry-area-utm-v1'
    assert meta['boundary_sha256'] == ldd.BOUNDARY_LDD_SHA256 == report['boundary_sha256']   # the asset validation read
    assert meta['legend_sha256'] == ldd.LEGEND_V2_SHA256                                       # and the legend it read
    assert meta['field_mapping']['declared_area'] == 'Shape_Area' and meta['repaired_feature_count'] == 1
    assert meta['validation_outcome'] == 'accepted_with_warnings'
    first, second = geometry['features']
    assert first['properties']['repaired'] is True and 'source_geometry' in first and first['repair']['feature'] == 0
    assert shape(first['geometry']).is_valid and not shape(first['source_geometry']).is_valid
    assert second['properties']['declared_area'] == 10050.0 and second['properties']['area_m2'] == pytest.approx(10000)
    candidate = prep.prepare(packet, source_root=source, staging_root=staging)
    verified = prep.verify(packet, source_root=source, staging_root=staging)
    assert candidate['valid'] and verified['artifacts'] == candidate['artifacts']
    assert candidate['method_version'] == prep.METHOD_V2


def _coordinates(value):
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], (int, float)):
        yield from value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _coordinates(item)


def test_v2_display_coordinates_are_rounded_and_areas_still_come_from_validation(tmp_path, bkk):
    raw = make_zip([parcel(inside_square(bkk)), parcel(inside_square(bkk, 400), 'A', 'A101')])
    source, staging = stage(tmp_path, raw)
    packet = prepare_request(raw, prep.METHOD_V2)
    outputs = prep.build(packet, source_root=source)
    summary, geometry = json.loads(outputs['ldd_summary']), json.loads(outputs['ldd_geometry'])
    display = summary['metadata']['display_coordinates']
    assert display == {'crs': 'EPSG:4326', 'decimals': 6, 'full_precision_feature_count': 0, 'full_precision_features': []}
    assert geometry['metadata'] == summary['metadata']
    for feature in geometry['features']:
        assert all(round(x, 6) == x for x in _coordinates(feature['geometry']['coordinates']))
        assert shape(feature['geometry']).is_valid and feature['properties']['area_m2'] == pytest.approx(10000)
    assert summary['total_area_m2'] == pytest.approx(20000)        # measured on the unrounded geometry


def test_a_parcel_that_rounding_would_break_keeps_full_precision(tmp_path, bkk, monkeypatch):
    # 0 decimals collapse a 100 m square to a point: both parcels must keep their full coordinates.
    monkeypatch.setattr(prep, 'DISPLAY_DECIMALS', 0)
    raw = make_zip([parcel(inside_square(bkk)), parcel(inside_square(bkk, 400), 'A', 'A101')])
    source, staging = stage(tmp_path, raw)
    packet = prepare_request(raw, prep.METHOD_V2)
    candidate = prep.prepare(packet, source_root=source, staging_root=staging)
    verified = prep.verify(packet, source_root=source, staging_root=staging)
    assert candidate['valid'] and verified['artifacts'] == candidate['artifacts']   # the rule is deterministic
    geometry = json.loads(prep.build(packet, source_root=source)['ldd_geometry'])
    display = geometry['metadata']['display_coordinates']
    assert display['decimals'] == 0 and display['full_precision_feature_count'] == 2
    assert sorted(display['full_precision_features']) == [0, 1]
    assert all(shape(f['geometry']).is_valid and shape(f['geometry']).area > 0 for f in geometry['features'])


def test_v1_artifacts_of_existing_fixtures_are_byte_identical():
    from tests.test_ldd_prepare_native import ROOT as fixtures, request as packet
    expected = {
        'ldd_valid.zip': ('c8201dded27c987f7d2979cf78b33fcb987289bf8acbbed56ad836d43a623085',
                          '9d57111775a67c2da96f935aa955f7c8a8b8ea7b8802095e7cbd05826865137e'),
        'ldd_cp874.zip': ('65714f002d624392227ee79623562bccfb041e5aaa4f720b209643adfa195942',
                          'bc49944b33fd1d7b88d2460a9cf816af385309a5b088ff2d4517787b2ca54071'),
        'ldd_composite_a.zip': ('dc9834599c074d81a726524be2a2c0429d68c157fa30cb6f9bad20f5722fe8e9',
                                '700f5d113826fc2d5f05ea836a542cf3b28a2dc0d89d9f97975264e1543d6103'),
    }
    with tempfile.TemporaryDirectory() as folder:
        for name, (geometry_sha, summary_sha) in expected.items():
            raw = (fixtures / name).read_bytes()
            (Path(folder) / (hashlib.sha256(raw).hexdigest() + '.zip')).write_bytes(raw)
            outputs = prep.build(packet(raw), source_root=Path(folder))
            assert hashlib.sha256(outputs['ldd_geometry']).hexdigest() == geometry_sha
            assert hashlib.sha256(outputs['ldd_summary']).hexdigest() == summary_sha


def test_v1_rebuild_keeps_the_frozen_legacy_rules_for_existing_editions(tmp_path, bkk, gadm):
    # EPSG:4326 with Shape_Area in m2 and a parcel 214 m outside were v1-preparable before. The legacy
    # rules read the GADM outline, so the edge case is cut against a province that still has it.
    cases = edge_cases(gadm)
    for name, raw, crs, province in (
            ('wgs', wgs84_zip(bkk, 10000.0), 'EPSG:4326', PROVINCE),
            ('edge', make_zip([parcel(inside_square(gadm, half=400)), parcel(cases['legacy_edge'])]), 'EPSG:32647', GADM_PROVINCE)):
        folder = tmp_path / name; folder.mkdir()
        source, staging = stage(folder, raw)
        packet = prepare_request(raw, prep.METHOD)
        packet['validation']['manifest']['crs'] = crs
        packet['validation']['province'] = province
        candidate = prep.prepare(packet, source_root=source, staging_root=staging)
        verified = prep.verify(packet, source_root=source, staging_root=staging)
        assert candidate['valid'] and verified['artifacts'] == candidate['artifacts']


def test_repair_never_falls_back_to_another_method(tmp_path, bkk, monkeypatch):
    import shapely
    def old_make_valid(geometry, **kwargs):
        if kwargs:
            raise TypeError('method= unsupported')
        return geometry
    monkeypatch.setattr(shapely, 'make_valid', old_make_valid)
    report, _ = run(tmp_path, make_zip([parcel(spike(bkk), area=10000.0)]))
    assert not report['valid'] and report['error_code'] == 'GEOMETRY_ENGINE_UNSUPPORTED'


def test_internal_errors_are_not_reported_as_file_defects(tmp_path, bkk, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError('bug')
    monkeypatch.setattr(policy, 'classify', broken)
    report, details = run(tmp_path, make_zip([parcel(inside_square(bkk))]))
    assert not report['valid'] and report['error_code'] == 'NATIVE_PROCESS_FAILED'
    assert details['outcome'] == 'rejected'
