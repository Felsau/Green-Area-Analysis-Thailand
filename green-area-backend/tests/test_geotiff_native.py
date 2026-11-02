"""Real tiny TIFF fixtures, numeric expectations, and fail-closed native guards.

Fixtures are created under pytest's private directory, never in the immutable
V1/V2 fixture catalog. No database, Auth, network or Cloud is used here.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin, Affine

from gis_worker import geotiff_provider as gt
from gis_worker.geotiff_worker import GeoTiffClient, GeoTiffWorker
from gis_worker.worker import WorkerError

ID = '11111111-1111-4111-8111-111111111111'


def write_tiff(path, profile='ndvi_ready', *, values=None, dtype='float32', crs='EPSG:32647',
        nodata=-9999, count=1, transform=None, scale=1, offset=0, units=None,
        description=None, profile_tag=None, tags=None, internal_mask=False, overviews=False):
    """Trusted fixture helper; no parameters are accepted by the HTTP API."""
    metric, band, expected_units, _, _ = gt.PROFILES[profile]
    if values is None:
        values = [[-.5, 0], [.5, -9999]] if metric == 'ndvi' else (
            [[293.15, 303.15], [313.15, -9999]] if profile == 'lst_kelvin_ready' else [[20, 30], [40, -9999]])
    values = np.array(values, dtype=dtype)
    with rasterio.open(path, 'w', driver='GTiff', width=values.shape[1], height=values.shape[0],
            count=count, dtype=dtype, crs=crs, transform=transform or from_origin(500000, 1500000, 30, 30),
            nodata=nodata) as out:
        for i in range(1, count + 1):
            out.write(values, i)
            out.set_band_description(i, band if description is None else description)
            out.set_band_unit(i, expected_units if units is None else units)
        out.scales = tuple(scale for _ in range(count))
        out.offsets = tuple(offset for _ in range(count))
        out.update_tags(GIS_PROFILE=profile if profile_tag is None else profile_tag,
            GIS_TEST_DATA='synthetic_fixture_v1', **(tags or {}))
        if internal_mask:
            out.write_mask(np.array([[255, 255], [255, 0]], dtype='uint8'))
        if overviews:
            out.build_overviews([2])
    return path.read_bytes()


create_fixture = write_tiff


def request(raw, profile='ndvi_ready', crs='EPSG:32647'):
    metric, band, units, _, _ = gt.PROFILES[profile]
    return {'upload_id': ID, 'manifest': {'schema_version': 4, 'provider': 'local_geotiff',
        'provenance': 'local-geotiff-upload-v1', 'data_kind': 'raster',
        'sha256': hashlib.sha256(raw).hexdigest(), 'byte_size': len(raw), 'crs': crs,
        'profile': profile, 'metric': metric, 'bands': [band], 'units': units},
        'input_hash': 'a' * 64, 'input_revision': 1, 'attempt_number': 1,
        'province': 'Bangkok Metropolis', 'data_year': 2026}


def stored(tmp_path, raw, profile='ndvi_ready', crs='EPSG:32647'):
    req = request(raw, profile, crs)
    path = tmp_path / (req['manifest']['sha256'] + '.tif')
    path.write_bytes(raw)
    return req


@pytest.mark.parametrize('profile,expected', [('ndvi_ready', 0), ('lst_celsius_ready', 30), ('lst_kelvin_ready', 30)])
def test_real_profiles_and_expected_numeric_results(tmp_path, profile, expected):
    raw = write_tiff(tmp_path / 'source.tif', profile)
    req = stored(tmp_path, raw, profile)
    report = gt.validate(req, storage_root=tmp_path)
    assert report['valid'], report
    assert set(report['checks']) == set(gt.CHECKS)
    assert report['observed_sha256'] == hashlib.sha256(raw).hexdigest()
    assert report['statistics']['mean'] == pytest.approx(expected, abs=2e-5)
    assert report['statistics']['valid_pixels'] == 3
    assert report['statistics']['nodata_pixels'] == 1
    assert report['statistics']['nonfinite_pixels'] == 0
    assert report['statistics']['width'] == report['statistics']['height'] == 2
    assert report['metadata']['dtype'] == 'float32'
    assert report['metadata']['resolution'] == [30, 30]
    assert report['metadata']['units'] == gt.PROFILES[profile][2]
    assert report['metadata']['output_units'] == ('unitless' if profile == 'ndvi_ready' else 'celsius')
    assert report['metadata']['scales'] == [1] and report['metadata']['offsets'] == [0]
    assert 'activated' not in report and 'published' not in report
    assert raw == (tmp_path / 'source.tif').read_bytes()
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize('kwargs,code', [
    ({'crs': None}, 'GEOTIFF_CRS_MISMATCH'),
    ({'crs': 'EPSG:3857'}, 'GEOTIFF_CRS_MISMATCH'),
    ({'crs': 'EPSG:32648'}, 'GEOTIFF_CRS_MISMATCH'),
    ({'count': 2}, 'GEOTIFF_BANDS_MISMATCH'),
    ({'description': 'B8'}, 'GEOTIFF_BANDS_MISMATCH'),
    ({'description': ''}, 'GEOTIFF_BANDS_MISMATCH'),
    ({'dtype': 'int16'}, 'GEOTIFF_DTYPE_UNSUPPORTED'),
    ({'dtype': 'uint16', 'nodata': 65535, 'values': [[100, 200], [300, 65535]]}, 'GEOTIFF_DTYPE_UNSUPPORTED'),
    ({'nodata': None}, 'GEOTIFF_NODATA_INVALID'),
    ({'nodata': float('nan')}, 'GEOTIFF_NODATA_INVALID'),
    ({'nodata': -np.finfo('float32').max}, 'GEOTIFF_NODATA_INVALID'),
    ({'nodata': 0}, 'GEOTIFF_NODATA_INVALID'),
    ({'scale': .0001}, 'GEOTIFF_SCALE_OFFSET_UNSUPPORTED'),
    ({'offset': -273.15}, 'GEOTIFF_SCALE_OFFSET_UNSUPPORTED'),
    ({'units': 'kelvin'}, 'GEOTIFF_UNITS_MISMATCH'),
    ({'profile_tag': 'raw_dn'}, 'GEOTIFF_PROFILE_MISMATCH'),
    ({'tags': {'source': 'https://example.invalid/raster.tif'}}, 'GEOTIFF_EXTERNAL_REFERENCE'),
    ({'tags': {'source': '../secret'}}, 'GEOTIFF_EXTERNAL_REFERENCE'),
    ({'tags': {'source': 'x' * 4097}}, 'GEOTIFF_METADATA_LIMIT'),
    ({'internal_mask': True}, 'GEOTIFF_MASK_UNSUPPORTED'),
    ({'overviews': True}, 'GEOTIFF_OVERVIEWS_UNSUPPORTED'),
    ({'transform': from_origin(500000, 1500000, 1001, 30)}, 'GEOTIFF_RESOLUTION_INVALID'),
    ({'transform': Affine(30, 1, 500000, 0, -30, 1500000)}, 'GEOTIFF_RESOLUTION_INVALID'),
    ({'transform': Affine(30, 0, 500000, 0, 30, 1500000)}, 'GEOTIFF_RESOLUTION_INVALID'),
    ({'values': [[-.2, .3], [1.01, -9999]]}, 'GEOTIFF_SCIENTIFIC_RANGE'),
    ({'values': [[-.2, .3], [-1.01, -9999]]}, 'GEOTIFF_SCIENTIFIC_RANGE'),
    ({'values': [[float('nan'), .3], [.8, -9999]]}, 'GEOTIFF_NONFINITE_PIXELS'),
    ({'values': [[float('inf'), .3], [.8, -9999]]}, 'GEOTIFF_NONFINITE_PIXELS'),
    ({'values': [[-9999, -9999], [-9999, -9999]]}, 'GEOTIFF_NO_VALID_PIXELS'),
])
def test_metadata_and_scientific_negative_cases(tmp_path, kwargs, code):
    raw = write_tiff(tmp_path / 'source.tif', **kwargs)
    report = gt.validate(stored(tmp_path, raw), storage_root=tmp_path)
    assert not report['valid'] and report['error_code'] == code, report
    assert report['statistics']['mean'] is None
    assert len(json.dumps(report, allow_nan=False).encode()) < 16384


@pytest.mark.parametrize('profile,values', [
    ('lst_celsius_ready', [[293.15, 303.15], [313.15, -9999]]),
    ('lst_kelvin_ready', [[20, 30], [40, -9999]]),
    ('ndvi_ready', [[1000, 2000], [3000, -9999]]),
])
def test_kelvin_celsius_raw_dn_misinterpretation_rejected(tmp_path, profile, values):
    raw = write_tiff(tmp_path / 'source.tif', profile, values=values)
    report = gt.validate(stored(tmp_path, raw, profile), storage_root=tmp_path)
    assert not report['valid'] and report['error_code'] == 'GEOTIFF_SCIENTIFIC_RANGE'


@pytest.mark.parametrize('crs,transform', [
    ('EPSG:4326', from_origin(100, 14, .01, .01)),
    ('EPSG:32648', from_origin(500000, 1500000, 30, 30)),
])
def test_supported_crs_read_from_file(tmp_path, crs, transform):
    raw = write_tiff(tmp_path / 'source.tif', crs=crs, transform=transform)
    assert gt.validate(stored(tmp_path, raw, crs=crs), storage_root=tmp_path)['valid']


@pytest.mark.parametrize('raw', [b'<VRTDataset>http://example.invalid</VRTDataset>', b'II+\0' + bytes(64),
    b'II*\0\xff\xff\xff\xff' + bytes(32), b'not tiff', b'MM\0*\0\0\0\x08\xff\xff'])
def test_corrupt_and_other_raster_formats_fail_closed(tmp_path, raw):
    report = gt.validate(stored(tmp_path, raw), storage_root=tmp_path)
    assert not report['valid'] and report['error_code'] in ('GEOTIFF_TIFF_SIGNATURE', 'GEOTIFF_TIFF_STRUCTURE')


@pytest.mark.parametrize('change', [
    {'path': '../secret'}, {'url': 'https://example.invalid'}, {'command': 'id'},
    {'sql': 'SELECT 1'}, {'upload_id': '../x'}, {'input_revision': True},
    {'input_revision': 0}, {'attempt_number': 4}, {'input_hash': '../x'},
    {'province': ''}, {'data_year': True},
])
def test_untrusted_request_extras_and_invalid_identity_rejected(tmp_path, change):
    req = request(b'ignored')
    req.update(change)
    with pytest.raises(gt.GeoTiffError, match='GEOTIFF_REQUEST_INVALID'):
        gt.check_request(req)


@pytest.mark.parametrize('change', [
    {'schema_version': 1}, {'provider': 'real'}, {'profile': 'raw_dn'}, {'sha256': '../x'},
    {'byte_size': 0}, {'byte_size': gt.MAX_FILE_BYTES + 1}, {'crs': 'EPSG:3857'},
    {'bands': ['B8', 'B4']}, {'units': 'kelvin'}, {'metric': 'lst'},
    {'file': '/tmp/x'}, {'scale': .0001},
])
def test_manifest_is_exact_server_contract(change):
    req = request(b'ignored')
    req['manifest'].update(change)
    with pytest.raises(gt.GeoTiffError, match='GEOTIFF_REQUEST_INVALID'):
        gt.check_request(req)


def test_hash_and_size_checked_before_native_parser(tmp_path):
    raw = write_tiff(tmp_path / 'source.tif')
    req = stored(tmp_path, raw)
    path = tmp_path / (req['manifest']['sha256'] + '.tif')
    path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    report = gt.validate(req, storage_root=tmp_path)
    assert report['error_code'] == 'GEOTIFF_SHA256_MISMATCH'
    assert report['observed_sha256'] != req['manifest']['sha256']
    path.write_bytes(raw[:-1])
    assert gt.validate(req, storage_root=tmp_path)['error_code'] == 'GEOTIFF_SIZE_MISMATCH'


def test_wrong_source_link_missing_and_hardlink_rejected(tmp_path):
    req = request(b'fake bytes')
    assert gt.validate(req, storage_root=tmp_path)['error_code'] == 'GEOTIFF_FILE_UNAVAILABLE'
    original = tmp_path / 'private'
    original.write_bytes(b'fake bytes')
    target = tmp_path / (req['manifest']['sha256'] + '.tif')
    os.link(original, target)
    assert gt.validate(req, storage_root=tmp_path)['error_code'] == 'GEOTIFF_FILE_UNSAFE'


def test_windowed_scan_aggregate_and_bounds(tmp_path):
    values = np.full((300, 300), .5, dtype='float32')
    values[0, 0] = -9999
    raw = write_tiff(tmp_path / 'source.tif', values=values)
    report = gt.validate(stored(tmp_path, raw), storage_root=tmp_path)
    assert report['valid'] and report['statistics']['valid_pixels'] == 89999
    assert report['statistics']['total_pixels'] == 90000 and report['statistics']['mean'] == .5


def test_failure_report_has_no_raw_diagnostics():
    req = request(b'ignored')
    report = gt.report_failure(req, 'NATIVE_TIMEOUT')
    assert report['statistics']['mean'] is None and report['metadata']['dtype'] is None
    assert 'token' not in json.dumps(report).lower()
    with pytest.raises(gt.GeoTiffError):
        gt.report_failure(req, 'path /private/secret')


def test_worker_reuses_common_lifecycle_and_exact_rpc():
    assert GeoTiffClient.RPC_NAMES == ('gis_geotiff_worker', 'gis_geotiff_readiness')
    assert GeoTiffWorker.CHILD_SCRIPT == 'geotiff_child.py'
    class Client:
        subject = ID
        expected = {'runtime_instance': 'a' * 32, 'baseline_fingerprint': 'a' * 64}
        def call(self, name, payload):
            return {'status': 'ready', 'worker_role': 'gis_native_worker', 'subject': ID,
                'database_name': 'postgres', 'cluster_name': 'green-area-gis-t0',
                'mode': 'local_synthetic', 'contract_version': '1.0.0-geotiff-local',
                'migration_versions': list(range(27, 37)), **self.expected}
    worker = GeoTiffWorker(Client())
    worker.readiness()
    worker.client.expected['database_name'] = 'production'
    with pytest.raises(WorkerError, match='WORKER_TARGET_REJECTED'):
        worker.readiness()
