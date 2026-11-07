"""Phase 2 local-file/native validation; no database, service or network."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import stat
import zipfile

import pytest

from gis_worker import ldd_policy as policy
from gis_worker import ldd_provider as ldd
from gis_worker.ldd_worker import LddWorker, LddClient
from gis_worker.worker import WorkerError

FIXTURES = Path(__file__).resolve().parents[1] / 'gis_worker/fixtures'
ID = '11111111-1111-4111-8111-111111111111'


def request(raw=None, **values):
    raw = raw or (FIXTURES / 'ldd_valid.zip').read_bytes()
    return {'upload_id': ID, 'manifest': {'schema_version': 1, 'provider': 'real',
        'sha256': hashlib.sha256(raw).hexdigest(), 'byte_size': len(raw),
        'provenance': 'local-ldd-upload-v1', 'crs': 'EPSG:32647', 'data_kind': 'polygon',
        'attributes': list(ldd.REQUIRED_FIELDS)}, 'input_hash': 'a' * 64,
        'input_revision': 1, 'attempt_number': 1, 'province': 'Bangkok Metropolis',
        'data_year': 2026, 'encoding': 'auto', **values}


def store(tmp_path, raw, req=None):
    req = req or request(raw)
    (tmp_path / (req['manifest']['sha256'] + '.zip')).write_bytes(raw)
    return req


def archive(members, **kwargs):
    output = BytesIO()
    with zipfile.ZipFile(output, 'w', **kwargs) as z:
        for name, value in members:
            z.writestr(name, value)
    return output.getvalue()


def test_catalog_is_frozen_existing_96_codes_and_boundaries():
    legend = ldd._asset('ldd_codes.json', ldd.LEGEND_SHA256)
    assert len(legend['codes']) == 96
    assert ldd._main_code('U201/A401', 'U', legend['codes']) == 'U'
    assert ldd._main_code('A300/A400', 'A', legend['codes']) == 'A'
    assert ldd._main_code('A101/A401', 'A', legend['codes']) == 'A'
    assert ldd._main_code('U101/UNKNOWN', 'U', legend['codes']) is None
    assert ldd._main_code('U101', '', legend['codes']) is None
    assert ldd._main_code('U101', True, legend['codes']) is None
    assert len(ldd._asset('province_boundaries.json', ldd.BOUNDARY_SHA256)['features']) == 77   # the frozen GADM asset


OFFICIAL_OUTLINES = {
    'Bangkok Metropolis', 'Chachoengsao', 'Chai Nat', 'Chanthaburi', 'Chon Buri', 'Kanchanaburi', 'Nakhon Nayok',
    'Nakhon Pathom', 'Nonthaburi', 'Pathum Thani', 'Phetchaburi', 'Phra Nakhon Si Ayutthaya', 'Prachin Buri',
    'Prachuap Khiri Khan', 'Ratchaburi', 'Rayong', 'Sa Kaeo', 'Samut Prakan', 'Samut Sakhon', 'Samut Songkhram',
    'Saraburi', 'Sing Buri', 'Suphan Buri', 'Trat'}


def test_boundary_asset_replaces_only_the_provinces_a_package_supplied():
    shapely_geometry = pytest.importorskip('shapely.geometry')
    base = ldd._asset('province_boundaries.json', ldd.BOUNDARY_SHA256)
    asset = ldd._asset(ldd.BOUNDARY_LDD_ASSET, ldd.BOUNDARY_LDD_SHA256)
    assert asset['metadata']['version'] == 'ldd-boundaries-v1' and asset['metadata']['base_asset_sha256'] == ldd.BOUNDARY_SHA256
    old = {f['properties']['name']: f for f in base['features']}
    assert [f['properties']['name'] for f in asset['features']] == [f['properties']['name'] for f in base['features']] and len(old) == 77
    official = set()
    for feature in asset['features']:
        props, name = feature['properties'], feature['properties']['name']
        assert props['source'] in ldd.BOUNDARY_SOURCES
        shape = shapely_geometry.shape(feature['geometry'])
        assert shape.geom_type in ('Polygon', 'MultiPolygon') and shape.is_valid and not shape.is_empty
        if props['source'] == 'gadm-approx':
            assert feature['geometry'] == old[name]['geometry']          # the GADM outline is carried over untouched
            continue
        official.add(name)
        assert re.fullmatch('[0-9a-f]{64}', props['package_sha256']) and re.fullmatch('[0-9a-f]{64}', props['shp_sha256'])
        assert props['data_year_be'] in (2566, 2567, 2568)
        previous = shapely_geometry.shape(old[name]['geometry'])
        assert shape.intersection(previous).area / shape.union(previous).area > 0.9   # the same province, only more detailed
    assert official == OFFICIAL_OUTLINES and len(official) == 24


def test_migration_051_names_exactly_the_two_boundary_assets_the_code_pins():
    """A rebuilt asset or a changed constant must not drift away from the SQL that admits its hash."""
    migrations = Path(__file__).resolve().parents[1] / 'migrations'
    sql = (migrations / '051_gis_ldd_boundary_asset.sql').read_text(encoding='utf-8')
    previous = hashlib.sha256((migrations / '050_gis_ldd_report_audit.sql').read_bytes()).hexdigest()
    assert set(re.findall(r'[0-9a-f]{64}', sql)) == {ldd.BOUNDARY_LDD_SHA256, ldd.BOUNDARY_SHA256, previous}
    assert ldd.BOUNDARY_SHA256 in (migrations / '034_ldd_upload.sql').read_text(encoding='utf-8')
    assert hashlib.sha256((Path(ldd.__file__).parent / ldd.BOUNDARY_LDD_ASSET).read_bytes()).hexdigest() == ldd.BOUNDARY_LDD_SHA256
    assert not (Path(ldd.__file__).parent / ldd.BOUNDARY_LDD_ASSET).read_bytes().count(b'\n')   # immune to line-ending conversion


@pytest.mark.parametrize('change', [
    {'path': '/tmp/x'}, {'province': None}, {'encoding': 'latin-1'}, {'attempt_number': 4},
    {'input_revision': True}, {'input_hash': '../path'}, {'upload_id': '../../x'},
])
def test_arbitrary_paths_and_invalid_metadata_rejected(change):
    req = request()
    req.update(change)
    with pytest.raises(ldd.LddError, match='LDD_REQUEST_INVALID'):
        ldd.check_request(req)


@pytest.mark.parametrize('name', ['../x.shp', '/x.shp', 'C:/x.shp', 'a\\x.shp', 'a/./x.shp', 'a//x.shp'])
def test_zip_traversal_denied(name):
    raw = archive([(name, b'a')])
    if '\\' in name:
        # ZipInfo on Windows normalizes writes; patch both same-length header
        # names to represent an archive actually received from another OS.
        raw = archive([(name.replace('\\', '/'), b'a')]).replace(name.replace('\\', '/').encode(), name.encode())
    with pytest.raises(ldd.LddError, match='ZIP_PATH_UNSAFE'):
        ldd.guarded_zip(raw)


def test_symlink_zip_member_denied():
    member = zipfile.ZipInfo('x.shp')
    member.create_system = 3
    member.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ldd.LddError, match='ZIP_SYMLINK'):
        ldd.guarded_zip(archive([(member, b'/etc/passwd')]))


def test_duplicate_case_and_bomb_and_unsupported_members():
    with pytest.raises(ldd.LddError, match='ZIP_DUPLICATE_NAME'):
        ldd.guarded_zip(archive([('x.shp', b'a'), ('X.SHP', b'b')]))
    with pytest.raises(ldd.LddError, match='ZIP_COMPRESSION_RATIO'):
        ldd.guarded_zip(archive([('x.shp', b'0' * 200000)], compression=zipfile.ZIP_DEFLATED))
    with pytest.raises(ldd.LddError, match='UNSUPPORTED_ZIP_MEMBER'):
        ldd.guarded_zip(archive([('x.vrt', b'<VRT/>')]))


def test_size_limit_corruption_missing_components_and_sidecars():
    with pytest.raises(ldd.LddError, match='ZIP_SIZE_LIMIT'):
        ldd.guarded_zip(b'a' * (ldd.MAX_ZIP_BYTES + 1))
    with pytest.raises(ldd.LddError, match='ZIP_CORRUPT'):
        ldd.guarded_zip(b'PK\x03\x04invalid')
    with pytest.raises(ldd.LddError, match='MISSING_COMPONENT_SHX'):
        ldd._components({'a.shp': b'a'})
    files = ldd.guarded_zip(archive([(f'a.{ext}', b'x') for ext in ('shp', 'shx', 'dbf', 'prj', 'sbn', 'sbx', 'qix')]))
    assert len(ldd._components(files)[1]) == 7


# ---- province packages (policy v3, package handling): one land-use layer is read, nothing else is --------------

LAYER_DIR, LAYER = 'Landuse_TST_2566/', 'LU_TST_2566'
LAYER_NAMES = sorted(f'{LAYER_DIR}{LAYER}.{ext}' for ext in ('cpg', 'dbf', 'prj', 'shp', 'shx'))


def fixture_layer(prefix=LAYER_DIR, layer=LAYER, fixture='ldd_valid.zip'):
    """The components of a real fixture layer, renamed to sit in a package folder."""
    with zipfile.ZipFile(FIXTURES / fixture) as z:
        return [(f'{prefix}{layer}.{i.filename.rsplit(".", 1)[1]}', z.read(i)) for i in z.infolist()]


def package(extra=(), **kwargs):
    """What LDD ships: the layer plus boundary layers, a code table, metadata and documents."""
    others = [(f'{LAYER_DIR}LUCODE.xls', bytes(range(200))), (f'{LAYER_DIR}readme.docx', bytes(range(100, 250))),
              (f'{LAYER_DIR}{LAYER}.shp.xml', b'<metadata/>'), (f'{LAYER_DIR}{LAYER}.sbn', b'index'),
              (f'{LAYER_DIR}ขอบเขต/TST_Pro.shp', b'not a shapefile'), (f'{LAYER_DIR}ขอบเขต/TST_Pro.dbf', b'not a table')]
    return archive(fixture_layer(**kwargs) + others + list(extra), compression=zipfile.ZIP_DEFLATED)


@pytest.mark.parametrize('names,expected', [
    (['a/x.shp'], 'a/x.shp'),                                            # a single shapefile keeps today's behaviour
    (['LU_BKK_2566.shp', 'B_Pro.shp', 'B_Amp.shp'], 'LU_BKK_2566.shp'),
    (['d/lu_ptt_2568.SHP', 'd/prov_Pro.shp'], 'd/lu_ptt_2568.SHP'),      # any case
    (['x/ขอบเขต/กรุงเทพ_Pro.shp', 'x/LU_BKK_2566.shp'], 'x/LU_BKK_2566.shp'),
    (['A_Pro.shp', 'B_Amp.shp'], None),                                  # several, none of them land use
    (['LU_A_2566.shp', 'LU_A_2567.shp'], None),                          # two land-use layers: no guessing
    (['readme.docx', 'sheet.xls'], None), ([], None),
])
def test_the_land_use_layer_is_chosen_without_guessing(names, expected):
    assert policy.select_land_use_layer(names) == expected


def test_a_province_package_reads_only_the_land_use_layer(monkeypatch):
    raw = package()          # built first: writing a ZIP goes through ZipFile.open too
    opened = []
    real_open = zipfile.ZipFile.open

    def spy(self, item, *args, **kwargs):
        opened.append(item.filename if isinstance(item, zipfile.ZipInfo) else item)
        return real_open(self, item, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, 'open', spy)
    files = ldd.guarded_zip(raw, package=True)
    assert sorted(opened) == sorted(files) == LAYER_NAMES   # no other member is decompressed
    name, parts = ldd._components(files)
    assert name == f'{LAYER_DIR}{LAYER}.shp' and set(parts) == {'.shp', '.shx', '.dbf', '.prj', '.cpg'}
    with zipfile.ZipFile(BytesIO(ldd.layer_archive(parts))) as rebuilt:   # what GDAL is given
        assert rebuilt.namelist() == ['layer.shp', 'layer.shx', 'layer.dbf', 'layer.prj', 'layer.cpg']
        assert all(rebuilt.read('layer' + k) == v for k, v in parts.items())


def test_the_frozen_rule_still_refuses_a_package():
    with pytest.raises(ldd.LddError, match='UNSUPPORTED_ZIP_MEMBER'):
        ldd.guarded_zip(package())
    with pytest.raises(ldd.LddError, match='SHAPEFILE_DATASET_COUNT'):   # two shapefiles, no package rule
        ldd._components(ldd.guarded_zip(archive(fixture_layer() + [('other.shp', b'x'), ('other.shx', b'x'), ('other.dbf', b'x')]
                                                  + [('other.prj', b'x')], compression=zipfile.ZIP_DEFLATED)))


@pytest.mark.parametrize('name', ['tool.exe', 'run.py', 'layer.vrt', f'{LAYER_DIR}x.dll', 'go.sh', 'macro.vbs', 'a.JS',
                                  'inner.zip', f'{LAYER_DIR}ลพบุรี.ZIP', 'x.7z', 'x.tar', 'x.gz'])
def test_programs_scripts_virtual_datasets_and_nested_archives_are_refused_inside_a_package(name):
    with pytest.raises(ldd.LddError, match='UNSUPPORTED_ZIP_MEMBER'):
        ldd.guarded_zip(package([(name, b'x')]), package=True)


def test_every_member_is_still_checked_even_when_it_is_never_read():
    symlink = zipfile.ZipInfo(f'{LAYER_DIR}notes.txt')
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    for member, code in [
        ((symlink, b'/etc/passwd'), 'ZIP_SYMLINK'),
        ((f'{LAYER_DIR}../escape.xls', b'x'), 'ZIP_PATH_UNSAFE'),
        ((f'{LAYER_DIR}C:/escape.xls', b'x'), 'ZIP_PATH_UNSAFE'),
        ((f'{LAYER_DIR}readme.DOCX', b'x'), 'ZIP_DUPLICATE_NAME'),
        ((f'{LAYER_DIR}bomb.txt', b'0' * 200000), 'ZIP_COMPRESSION_RATIO'),
    ]:
        with pytest.raises(ldd.LddError, match=code):
            ldd.guarded_zip(package([member]), package=True)
    with pytest.raises(ldd.LddError, match='ZIP_MEMBER_LIMIT'):
        ldd.guarded_zip(package([(f'{LAYER_DIR}extra{i}.txt', bytes([i, 1, 2])) for i in range(60)]), package=True)


@pytest.mark.parametrize('members,code', [
    ([('A_Pro.shp', b'x'), ('B_Amp.shp', b'x')], 'SHAPEFILE_DATASET_COUNT'),               # several, none land use
    ([('LU_A_2566.shp', b'x'), ('LU_A_2567.shp', b'x')], 'SHAPEFILE_DATASET_COUNT'),       # two land-use layers
    ([('readme.docx', b'x'), ('sheet.xls', b'x')], 'SHAPEFILE_DATASET_COUNT'),             # no shapefile at all
])
def test_a_package_without_exactly_one_land_use_layer_is_refused(members, code):
    with pytest.raises(ldd.LddError, match=code):
        ldd.guarded_zip(archive(members), package=True)


def test_a_province_package_gives_the_same_result_as_its_layer_alone(tmp_path):
    pytest.importorskip('fiona')
    pytest.importorskip('rasterio')
    alone = ldd.validate(store(tmp_path, (FIXTURES / 'ldd_valid.zip').read_bytes()), storage_root=tmp_path)
    packed_raw = package()
    packed = ldd.validate(store(tmp_path, packed_raw), storage_root=tmp_path)
    assert alone['valid'] is True and packed['valid'] is True
    for key in ('valid', 'error_code', 'errors', 'warnings', 'statistics', 'checks', 'encoding', 'audit'):
        assert packed[key] == alone[key], key
    assert packed['artifact_sha256'] != alone['artifact_sha256']
    # The pre-v2 validator is frozen: it still refuses what only the package rule accepts.
    legacy = ldd.validate_legacy_v1(request(packed_raw), storage_root=tmp_path)
    assert legacy['valid'] is False and {'code': 'UNSUPPORTED_ZIP_MEMBER', 'count': 1} in legacy['errors']


def test_a_layer_in_a_legacy_encoded_folder_name_is_read(tmp_path):
    """Real LDD ZIPs name folders in Thai without the UTF-8 flag; GDAL never sees those names."""
    pytest.importorskip('fiona')
    pytest.importorskip('rasterio')
    placeholder = 'AAAAAA'
    thai = 'ขอบเขต'.encode('cp874')
    assert len(thai) == len(placeholder)
    raw = archive(fixture_layer(prefix=placeholder + '/', layer='LU_TST_2566')
                  + [(f'{placeholder}/BBBBBB_Pro.shp', b'not a shapefile')], compression=zipfile.ZIP_DEFLATED)
    raw = raw.replace(placeholder.encode(), thai)
    assert thai in raw
    result = ldd.validate(store(tmp_path, raw), storage_root=tmp_path)
    assert result['valid'] is True and result['statistics']['feature_count'] == 3


@pytest.mark.parametrize('fixture,outcome,accepted,review', [
    ('ldd_valid.zip', 'accepted', 3, 0), ('ldd_unknown.zip', 'review_required', None, None), ('ldd_missing_dbf.zip', 'rejected', 0, 0),
])
def test_report_audit_matches_the_rules_in_migration_050(tmp_path, fixture, outcome, accepted, review):
    pytest.importorskip('fiona')
    pytest.importorskip('rasterio')
    result = ldd.validate(store(tmp_path, (FIXTURES / fixture).read_bytes()), storage_root=tmp_path)
    audit = result['audit']
    assert set(audit) == {'policy_version', 'outcome', 'field_profile', 'field_mapping', 'declared_area_units', 'feature_outcomes',
                          'boundary', 'unknown_samples', 'repairs', 'repairs_total'}
    assert audit['outcome'] == outcome and audit['policy_version'] == 'ldd-policy-v2'
    assert set(audit['feature_outcomes']) == {'accepted', 'accepted_with_warnings', 'review_required', 'rejected'}
    assert set(audit['boundary']) == {'minor', 'review', 'fatal', 'outside_area_m2'}
    total = sum(audit['feature_outcomes'].values())
    if result['valid']:
        assert total == result['statistics']['feature_count'] and audit['field_mapping'] == {
            'main_code': 'LUL1_CODE', 'lu_code': 'LU_CODE', 'declared_area': 'Shape_Area'}
    else:
        assert total <= result['statistics']['feature_count']
    if accepted is not None:
        assert audit['feature_outcomes']['accepted'] == accepted and audit['feature_outcomes']['review_required'] == review
    if outcome == 'review_required':
        assert audit['feature_outcomes']['review_required'] > 0 and 0 < len(audit['unknown_samples']) <= 10
        assert {e['code'] for e in result['errors']} == {'UNKNOWN_CODE_REVIEW_REQUIRED'}
        sample = audit['unknown_samples'][0]
        assert set(sample) == {'value', 'main', 'reason', 'count', 'area_m2'} and re.fullmatch('[A-Z][A-Z0-9_]{0,59}', sample['reason'])
    assert len(json.dumps(result, allow_nan=False).encode()) <= 16384


def test_audit_is_dropped_rather_than_failing_when_the_report_would_be_too_large(tmp_path, monkeypatch):
    pytest.importorskip('fiona')
    pytest.importorskip('rasterio')
    monkeypatch.setattr(ldd, 'audit_summary', lambda details, total: {'padding': 'x' * 20000})
    result = ldd.validate(store(tmp_path, (FIXTURES / 'ldd_valid.zip').read_bytes()), storage_root=tmp_path)
    assert result['valid'] is True and 'audit' not in result


def test_resource_failures_carry_no_audit(tmp_path, monkeypatch):
    req = request((FIXTURES / 'ldd_valid.zip').read_bytes())
    failure = ldd.report_failure(req, 'NATIVE_MEMORY_LIMIT')
    monkeypatch.setattr(ldd, 'assess', lambda request, storage_root: (failure, {}))
    assert 'audit' not in ldd.validate(req, storage_root=tmp_path)


def test_native_hash_mismatch_and_missing_file_fail_safely(tmp_path):
    raw = (FIXTURES / 'ldd_valid.zip').read_bytes()
    req = request(raw)
    result = ldd.validate(req, storage_root=tmp_path)
    assert result['valid'] is False and result['error_code'] == 'LDD_FILE_UNAVAILABLE'
    store(tmp_path, bytes([raw[0] ^ 1]) + raw[1:], req)
    result = ldd.validate(req, storage_root=tmp_path)
    assert result['error_code'] == 'LDD_SHA256_MISMATCH' and result['observed_sha256'] != result['artifact_sha256']
    assert str(tmp_path) not in json.dumps(result)


@pytest.mark.parametrize('fixture,valid,code', [
    ('ldd_valid.zip', True, None), ('ldd_cp874.zip', True, None),
    ('ldd_composite_a.zip', True, None), ('ldd_unknown.zip', False, 'UNKNOWN_CODE_REVIEW_REQUIRED'),
    ('ldd_missing_dbf.zip', False, 'MISSING_COMPONENT_DBF'),
])
def test_actual_zip_validation_expected_results(tmp_path, fixture, valid, code):
    pytest.importorskip('fiona')
    pytest.importorskip('rasterio')
    raw = (FIXTURES / fixture).read_bytes()
    req = store(tmp_path, raw)
    result = ldd.validate(req, storage_root=tmp_path)
    assert result['valid'] is valid
    assert result['error_code'] == code
    assert len(json.dumps(result).encode()) <= 16384
    if valid:
        assert result['statistics']['feature_count'] == 3
        assert result['statistics']['total_area_m2'] == pytest.approx(6400)
        assert sum(result['statistics']['area_by_main_m2'].values()) == pytest.approx(6400)
        assert set(result['checks']) == set(ldd.CHECKS)
        assert result['observed_sha256'] == result['artifact_sha256']
    if fixture == 'ldd_cp874.zip':
        assert result['encoding'] == 'cp874'
    if fixture == 'ldd_composite_a.zip':
        assert result['statistics']['composite_feature_count'] >= 1
    if fixture == 'ldd_unknown.zip':
        assert result['statistics']['unknown_code_count'] > 0
        assert result['statistics']['unknown_area_m2'] > 0


def test_actual_crs_province_encoding_mismatch(tmp_path):
    pytest.importorskip('fiona')
    pytest.importorskip('rasterio')
    raw = (FIXTURES / 'ldd_valid.zip').read_bytes()
    req = store(tmp_path, raw)
    wrong_crs = deepcopy(req)
    wrong_crs['manifest']['crs'] = 'EPSG:32648'
    assert ldd.validate(wrong_crs, storage_root=tmp_path)['error_code'] == 'CRS_MISMATCH'
    wrong_province = {**req, 'province': 'Chiang Mai'}
    assert ldd.validate(wrong_province, storage_root=tmp_path)['error_code'] == 'OUTSIDE_PROVINCE'
    wrong_encoding = {**req, 'encoding': 'cp874'}
    assert ldd.validate(wrong_encoding, storage_root=tmp_path)['error_code'] == 'ENCODING_MISMATCH'


def ready():
    return {'status': 'ready', 'worker_role': 'gis_native_worker', 'subject': ID,
        'database_name': 'postgres', 'cluster_name': 'green-area-gis-t0', 'mode': 'local_synthetic',
        'contract_version': '1.0.0-ldd-local', 'migration_versions': list(range(27, 35)),
        'runtime_instance': 'a' * 32, 'baseline_fingerprint': 'b' * 64}


class Client:
    subject = ID
    expected = {'runtime_instance': 'a' * 32, 'baseline_fingerprint': 'b' * 64}

    def __init__(self, result=None):
        self.result = result or ready()
        self.calls = []

    def call(self, name, payload):
        self.calls.append((name, payload))
        return self.result if name == 'gis_ldd_readiness' else {'state': 'succeeded'}


def test_ldd_worker_separate_rpc_and_reused_fencing():
    client = Client()
    worker = LddWorker(client)
    worker.call('claim')
    assert [name for name, _ in client.calls] == ['gis_ldd_readiness', 'gis_ldd_worker']
    assert LddClient.RPC_NAMES == ('gis_ldd_worker', 'gis_ldd_readiness')
    assert worker.CHILD_SCRIPT == 'ldd_child.py'


@pytest.mark.parametrize('field,value', [('contract_version', 'other'), ('migration_versions', list(range(27, 34))), ('subject', 'other'), ('mode', 'production')])
def test_ldd_worker_target_guard_blocks_mutation(field, value):
    response = ready()
    response[field] = value
    client = Client(response)
    with pytest.raises(WorkerError, match='WORKER_TARGET_REJECTED'):
        LddWorker(client).call('claim')
    assert len(client.calls) == 1


def test_ldd_native_request_no_paths_or_extra_keys():
    req = request()
    job = {**req, 'id': ID, 'lease_token': ID}
    assert LddWorker(Client()).build_native_request(job) == req
    failure = LddWorker(Client()).failure_report(req, 'NATIVE_TIMEOUT')
    assert failure['valid'] is False and failure['error_code'] == 'NATIVE_TIMEOUT'
    assert not {'access_token', 'path', 'url'} & failure.keys()
