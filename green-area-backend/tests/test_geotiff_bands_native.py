"""Known-answer tests for NDVI/LST computed from uploaded bands. Pinned Linux image only."""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from gis_worker import geotiff_provider as gt
from gis_worker.geotiff_bands import ST_OFFSET, ST_SCALE

# Inside Bangkok Metropolis (WGS84), small enough to stay inside the approximate boundary.
INSIDE = from_origin(100.50, 13.75, 0.001, 0.001)
FAR_AWAY = from_origin(90.0, 40.0, 0.001, 0.001)


def write(path, bands, descriptions, *, dtype='uint16', nodata=0, grid=INSIDE, crs='EPSG:4326', scales=None, offsets=None, tags=None):
    with rasterio.open(path, 'w', driver='GTiff', width=bands[0].shape[1], height=bands[0].shape[0], count=len(bands),
                       dtype=dtype, crs=crs, transform=grid, nodata=nodata) as dataset:
        for index, band in enumerate(bands, 1):
            dataset.write(band.astype(dtype), index)
            dataset.set_band_description(index, descriptions[index - 1])
        if scales:
            dataset.scales = scales
        if offsets:
            dataset.offsets = offsets
        if tags:
            dataset.update_tags(**tags)
    return path.read_bytes()


def request(raw, profile, crs='EPSG:4326'):
    metric, bands, units = gt.BAND_PROFILES[profile]
    return {'upload_id': '11111111-1111-4111-8111-111111111111', 'input_hash': 'a' * 64, 'input_revision': 1, 'attempt_number': 1,
            'province': 'Bangkok Metropolis', 'data_year': 2024,
            'manifest': {'schema_version': 4, 'provider': 'local_geotiff', 'provenance': 'local-geotiff-upload-v1', 'data_kind': 'raster',
                         'sha256': hashlib.sha256(raw).hexdigest(), 'byte_size': len(raw), 'crs': crs, 'profile': profile,
                         'metric': metric, 'bands': bands, 'units': units}}


def run(tmp_path, raw, profile, crs='EPSG:4326'):
    req = request(raw, profile, crs)
    (tmp_path / (req['manifest']['sha256'] + '.tif')).write_bytes(raw)
    report = gt.validate(req, storage_root=tmp_path)
    json.dumps(report, allow_nan=False)
    return report


def uniform(value, shape=(4, 4)):
    return np.full(shape, value)


def test_ndvi_known_answer_inside_the_province(tmp_path):
    raw = write(tmp_path / 's.tif', [uniform(1000), uniform(3000)], ('B4', 'B8'))
    report = run(tmp_path, raw, 'ndvi_bands')
    assert report['valid'] is True, report['errors']
    assert report['statistics']['mean'] == pytest.approx(0.5) and report['statistics']['min'] == pytest.approx(0.5)
    assert report['statistics']['valid_pixels'] == 16 and report['statistics']['band_count'] == 2
    assert report['statistics']['outside_area_pixels'] == 0
    assert report['metadata']['output_units'] == 'unitless' and report['metadata']['bands'] == ['B4', 'B8']
    assert report['coverage']['fraction_of_file'] == 1 and 0 < report['coverage']['fraction_of_province'] < 1
    codes = {w['code'] for w in report['warnings']}
    assert {'BOUNDARY_APPROXIMATE', 'ACQUISITION_DATE_DECLARED_NOT_VERIFIED', 'GEOTIFF_PARTIAL_PROVINCE_COVERAGE'} <= codes


def test_ndvi_scale_and_offset_from_the_file_are_applied_before_the_ratio(tmp_path):
    # Harmonized-style offset: reflectance = DN * 0.0001 - 0.1, so 2000 -> 0.1 and 4000 -> 0.3.
    raw = write(tmp_path / 's.tif', [uniform(2000), uniform(4000)], ('B4', 'B8'), scales=(0.0001, 0.0001), offsets=(-0.1, -0.1))
    report = run(tmp_path, raw, 'ndvi_bands')
    assert report['valid'] is True and report['statistics']['mean'] == pytest.approx(0.5)


def test_uniform_file_mean_stays_inside_extrema_as_the_database_requires(tmp_path):
    # 64x64 at this DN once gave a rounded mean below min, so SQL rejected the report.
    raw = write(tmp_path / 's.tif', [uniform(44000, (64, 64))], ('ST_B10',))
    stats = run(tmp_path, raw, 'lst_st_b10')['statistics']
    assert stats['min'] <= stats['mean'] <= stats['max']


def test_ndvi_excludes_nodata_negative_and_zero_sum_pixels(tmp_path):
    red = np.array([[1000, 0, 500, 200]], dtype='int16')
    nir = np.array([[3000, 3000, -100, -200]], dtype='int16')
    raw = write(tmp_path / 's.tif', [red, nir], ('B4', 'B8'), dtype='int16')
    report = run(tmp_path, raw, 'ndvi_bands')
    assert report['valid'] is True
    assert report['statistics']['valid_pixels'] == 1 and report['statistics']['nodata_pixels'] == 3
    assert report['statistics']['mean'] == pytest.approx(0.5)


def test_lst_known_answer_from_raw_digital_numbers(tmp_path):
    dn = 44000
    raw = write(tmp_path / 's.tif', [uniform(dn)], ('ST_B10',))
    report = run(tmp_path, raw, 'lst_st_b10')
    assert report['valid'] is True, report['errors']
    assert report['statistics']['mean'] == pytest.approx(dn * ST_SCALE + ST_OFFSET - 273.15)
    assert report['metadata']['output_units'] == 'celsius'


def test_lst_published_factors_in_the_file_are_not_applied_twice(tmp_path):
    dn = 44000
    raw = write(tmp_path / 's.tif', [uniform(dn)], ('ST_B10',), scales=(ST_SCALE,), offsets=(ST_OFFSET,))
    report = run(tmp_path, raw, 'lst_st_b10')
    assert report['valid'] is True and report['statistics']['mean'] == pytest.approx(dn * ST_SCALE + ST_OFFSET - 273.15)


def test_only_pixels_inside_the_province_are_counted(tmp_path):
    # 40 columns at 0.05 degrees spans far beyond Bangkok on both sides.
    grid = from_origin(99.5, 14.2, 0.05, 0.05)
    raw = write(tmp_path / 's.tif', [uniform(1000, (20, 40)), uniform(3000, (20, 40))], ('B4', 'B8'), grid=grid)
    report = run(tmp_path, raw, 'ndvi_bands')
    stats = report['statistics']
    assert report['valid'] is True, report['errors']
    assert 0 < stats['valid_pixels'] < stats['total_pixels'] and stats['outside_area_pixels'] > 0
    assert stats['valid_pixels'] + stats['nodata_pixels'] + stats['outside_area_pixels'] == stats['total_pixels']
    assert 0 < report['coverage']['fraction_of_file'] < 1


@pytest.mark.parametrize('kwargs,profile,code', [
    (dict(bands=[uniform(1000), uniform(3000)], descriptions=('B4', 'B8'), grid=FAR_AWAY), 'ndvi_bands', 'GEOTIFF_OUTSIDE_PROVINCE'),
    (dict(bands=[uniform(1000), uniform(3000)], descriptions=('B8', 'B4')), 'ndvi_bands', 'GEOTIFF_BANDS_MISMATCH'),
    (dict(bands=[uniform(1000)], descriptions=('B4',)), 'ndvi_bands', 'GEOTIFF_BANDS_MISMATCH'),
    (dict(bands=[uniform(0), uniform(0)], descriptions=('B4', 'B8')), 'ndvi_bands', 'GEOTIFF_NO_VALID_PIXELS'),
    (dict(bands=[uniform(1000), uniform(3000)], descriptions=('B4', 'B8'), nodata=None), 'ndvi_bands', 'GEOTIFF_NODATA_INVALID'),
    (dict(bands=[uniform(1000), uniform(3000)], descriptions=('B4', 'B8'), scales=(0.0001, 0.0002)), 'ndvi_bands', 'GEOTIFF_SCALE_OFFSET_UNSUPPORTED'),
    (dict(bands=[uniform(1000), uniform(3000)], descriptions=('B4', 'B8'), tags={'GIS_PROFILE': 'ndvi_ready'}), 'ndvi_bands', 'GEOTIFF_PROFILE_MISMATCH'),
    (dict(bands=[uniform(44000)], descriptions=('ST_B10',), dtype='float32'), 'lst_st_b10', 'GEOTIFF_DTYPE_UNSUPPORTED'),
    (dict(bands=[uniform(44000)], descriptions=('ST_B10',), scales=(0.01,)), 'lst_st_b10', 'GEOTIFF_SCALE_OFFSET_UNSUPPORTED'),
    (dict(bands=[uniform(1)], descriptions=('ST_B10',)), 'lst_st_b10', 'GEOTIFF_SCIENTIFIC_RANGE'),
])
def test_rejected_band_files_never_report_values(tmp_path, kwargs, profile, code):
    raw = write(tmp_path / 's.tif', kwargs.pop('bands'), kwargs.pop('descriptions'), **kwargs)
    report = run(tmp_path, raw, profile)
    assert report['valid'] is False and report['error_code'] == code
    assert report['statistics']['mean'] is None


def test_failure_report_has_the_band_profile_shape():
    raw = b'II*\0' + b'\0' * 20
    report = gt.report_failure(request(raw, 'ndvi_bands'), 'NATIVE_TIMEOUT')
    assert report['coverage'] is None and report['statistics']['outside_area_pixels'] == 0


def test_ready_profile_reports_keep_their_exact_shape():
    raw = b'II*\0' + b'\0' * 20
    req = request(raw, 'ndvi_bands')
    req['manifest'].update(profile='ndvi_ready', metric='ndvi', bands=['NDVI'], units='unitless')
    report = gt.report_failure(req, 'NATIVE_TIMEOUT')
    assert 'coverage' not in report and 'outside_area_pixels' not in report['statistics']
