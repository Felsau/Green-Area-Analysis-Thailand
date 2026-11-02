"""Bounded scientific validation of immutable local GeoTIFF bytes.

Only ready single-band NDVI or LST profiles are supported. No GEE, calibration
guessing, network, Auth or database configuration is imported by this module.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
from uuid import UUID

BUILD = 'geotiff-local-v1'
STORAGE_ROOT = Path('/data/geotiff/objects')
MAX_FILE_BYTES = 20 * 1024**2
MAX_DIMENSION = 16384
MAX_PIXELS = 16000000
CHECKS = ('source_hash_match', 'tiff_structure', 'crs', 'bands', 'resolution',
          'dimensions', 'dtype', 'nodata', 'scale_offset', 'units',
          'scientific_range', 'metadata_consistency')
PROFILES = {
    'ndvi_ready': ('ndvi', 'NDVI', 'unitless', -1.0, 1.0),
    'lst_celsius_ready': ('lst', 'LST', 'celsius', -100.0, 100.0),
    'lst_kelvin_ready': ('lst', 'LST', 'kelvin', 173.15, 373.15),
}
HASH = re.compile(r'^[0-9a-f]{64}$')
CODE = re.compile(r'^[A-Z][A-Z0-9_]{0,59}$')


class GeoTiffError(ValueError):
    """Fixed public error code, never a native diagnostic or input value."""


def require(condition, code='GEOTIFF_REQUEST_INVALID'):
    if not condition:
        raise GeoTiffError(code)


def check_request(value):
    require(isinstance(value, dict) and set(value) == {
        'upload_id', 'manifest', 'input_hash', 'input_revision', 'attempt_number',
        'province', 'data_year'})
    try:
        require(str(UUID(value['upload_id'])) == value['upload_id'])
    except (TypeError, ValueError, AttributeError):
        raise GeoTiffError('GEOTIFF_REQUEST_INVALID') from None
    m = value['manifest']
    require(isinstance(m, dict) and set(m) == {
        'schema_version', 'provider', 'provenance', 'data_kind', 'sha256',
        'byte_size', 'crs', 'profile', 'metric', 'bands', 'units'})
    require(type(m['schema_version']) is int and m['schema_version'] == 4
            and m['provider'] == 'local_geotiff' and m['data_kind'] == 'raster'
            and m['provenance'] == 'local-geotiff-upload-v1'
            and isinstance(m['sha256'], str) and HASH.fullmatch(m['sha256'])
            and type(m['byte_size']) is int and 0 < m['byte_size'] <= MAX_FILE_BYTES
            and m['crs'] in ('EPSG:32647', 'EPSG:32648', 'EPSG:4326')
            and isinstance(m['profile'], str) and m['profile'] in PROFILES)
    metric, band, units, _, _ = PROFILES[m['profile']]
    require(m['metric'] == metric and m['bands'] == [band] and m['units'] == units)
    require(isinstance(value['input_hash'], str) and HASH.fullmatch(value['input_hash'])
            and type(value['input_revision']) is int and 1 <= value['input_revision'] <= 2147483647
            and type(value['attempt_number']) is int and 1 <= value['attempt_number'] <= 3
            and type(value['data_year']) is int and 1980 <= value['data_year'] <= 2200
            and isinstance(value['province'], str) and 0 < len(value['province']) <= 120)
    return value


def report_failure(request, code):
    check_request(request)
    require(isinstance(code, str) and CODE.fullmatch(code))
    m = request['manifest']
    return {'schema_version': 1, 'provider_build': BUILD, 'upload_id': request['upload_id'],
            'artifact_sha256': m['sha256'], 'observed_sha256': None,
            'byte_size': m['byte_size'], 'input_hash': request['input_hash'],
            'input_revision': request['input_revision'], 'province': request['province'],
            'data_year': request['data_year'], 'valid': False, 'checks': [],
            'errors': [{'code': code, 'count': 1}], 'warnings': [], 'error_code': code,
            'statistics': {'width': 0, 'height': 0, 'band_count': 0, 'total_pixels': 0,
                           'valid_pixels': 0, 'nodata_pixels': 0, 'nonfinite_pixels': 0,
                           'mean': None, 'min': None, 'max': None},
            'metadata': {k: None for k in ('crs', 'bands', 'resolution', 'dtype', 'nodata',
                        'units', 'scales', 'offsets', 'profile', 'output_units')}}


def _unsafe(path):
    return path.is_symlink() or (path.exists() and bool(getattr(path.lstat(), 'st_file_attributes', 0)
        & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)))


def _source_bytes(request, storage_root):
    root = Path(storage_root)
    require(root.is_dir() and not any(_unsafe(p) for p in (root, *root.parents))
            and root.resolve() == root.absolute(), 'GEOTIFF_STORAGE_UNAVAILABLE')
    path = root / (request['manifest']['sha256'] + '.tif')
    require(not _unsafe(path), 'GEOTIFF_FILE_UNSAFE')
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'GEOTIFF_FILE_UNSAFE')
            require(info.st_size == request['manifest']['byte_size']
                    and 0 < info.st_size <= MAX_FILE_BYTES, 'GEOTIFF_SIZE_MISMATCH')
            raw = stream.read(MAX_FILE_BYTES + 1)
        require(len(raw) == info.st_size, 'GEOTIFF_SIZE_MISMATCH')
        return raw
    except GeoTiffError:
        raise
    except OSError:
        raise GeoTiffError('GEOTIFF_FILE_UNAVAILABLE') from None


def _signature(raw):
    require(len(raw) >= 10 and raw[:4] in (b'II*\0', b'MM\0*'), 'GEOTIFF_TIFF_SIGNATURE')
    endian = '<' if raw[:2] == b'II' else '>'
    offset = struct.unpack_from(endian + 'I', raw, 4)[0]
    require(8 <= offset <= len(raw) - 2, 'GEOTIFF_TIFF_STRUCTURE')
    count = struct.unpack_from(endian + 'H', raw, offset)[0]
    require(0 < count <= 1024 and offset + 2 + count * 12 + 4 <= len(raw), 'GEOTIFF_TIFF_STRUCTURE')


def _tags(dataset):
    # Never return arbitrary TIFF metadata, which may contain URLs or private text.
    # GTiff is the sole enabled driver and bytes are opened through MemoryFile;
    # sidecars and URI-based datasets cannot be opened by this validation path.
    tags = dataset.tags()
    band_tags = dataset.tags(1)
    namespaces = dataset.tag_namespaces() + dataset.tag_namespaces(1)
    require(len(tags) + len(band_tags) <= 64 and len(namespaces) <= 16,
            'GEOTIFF_METADATA_LIMIT')
    for group in (tags, band_tags):
        for key, value in group.items():
            require(len(key) <= 128 and len(value) <= 4096, 'GEOTIFF_METADATA_LIMIT')
            require(not re.search(r'https?://|file:|/vsi|\\|\.\./', key + value, re.I),
                    'GEOTIFF_EXTERNAL_REFERENCE')
    return tags


def validate(request, *, storage_root=STORAGE_ROOT):
    check_request(request)
    report = report_failure(request, 'GEOTIFF_VALIDATION_FAILED')
    m, stats, metadata = request['manifest'], report['statistics'], report['metadata']
    try:
        raw = _source_bytes(request, storage_root)
        report['observed_sha256'] = hashlib.sha256(raw).hexdigest()
        require(report['observed_sha256'] == m['sha256'], 'GEOTIFF_SHA256_MISMATCH')
        report['checks'].append('source_hash_match')
        _signature(raw)
        # Native libraries are only loaded after byte bounds/hash checks and,
        # in production execution, after the child applies resource limits.
        import numpy as np
        import rasterio
        from rasterio.io import MemoryFile
        from rasterio.enums import MaskFlags
        from rasterio.windows import Window
        with rasterio.Env(GDAL_PAM_ENABLED='NO', GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',
                GDAL_GEOREF_SOURCES='INTERNAL', GDAL_NUM_THREADS='1', PROJ_NETWORK='OFF',
                GDAL_HTTP_TIMEOUT='1', GDAL_CACHEMAX=16 * 1024**2):
            with MemoryFile(raw) as memory:
                with memory.open(driver='GTiff') as dataset:
                    require(dataset.driver == 'GTiff' and not dataset.subdatasets
                            and dataset.files == [memory.name], 'GEOTIFF_TIFF_STRUCTURE')
                    require(not dataset.overviews(1), 'GEOTIFF_OVERVIEWS_UNSUPPORTED')
                    report['checks'].append('tiff_structure')
                    require(0 < dataset.width <= MAX_DIMENSION and 0 < dataset.height <= MAX_DIMENSION
                            and dataset.width * dataset.height <= MAX_PIXELS, 'GEOTIFF_DIMENSIONS_LIMIT')
                    stats.update(width=dataset.width, height=dataset.height,
                                 total_pixels=dataset.width * dataset.height)
                    report['checks'].append('dimensions')
                    epsg = dataset.crs.to_epsg() if dataset.crs else None
                    metadata['crs'] = 'EPSG:' + str(epsg) if epsg in (32647, 32648, 4326) else None
                    require(metadata['crs'] == m['crs'], 'GEOTIFF_CRS_MISMATCH')
                    report['checks'].append('crs')
                    require(dataset.count == 1 and dataset.descriptions == tuple(m['bands']), 'GEOTIFF_BANDS_MISMATCH')
                    stats['band_count'] = 1
                    metadata['bands'] = list(dataset.descriptions)
                    report['checks'].append('bands')
                    transform = dataset.transform
                    require(all(math.isfinite(v) for v in tuple(transform)) and transform.b == 0 and transform.d == 0
                            and transform.a > 0 and transform.e < 0, 'GEOTIFF_RESOLUTION_INVALID')
                    resolution = [float(v) for v in dataset.res]
                    lower, upper = (0.000001, 1) if epsg == 4326 else (0.01, 1000)
                    require(all(lower <= v <= upper for v in resolution), 'GEOTIFF_RESOLUTION_INVALID')
                    metadata['resolution'] = resolution
                    bounds = dataset.bounds
                    if epsg == 4326:
                        require(-180 <= bounds.left < bounds.right <= 180 and -90 <= bounds.bottom < bounds.top <= 90,
                                'GEOTIFF_BOUNDS_INVALID')
                    else:
                        require(0 <= bounds.left < bounds.right <= 1000000 and 0 <= bounds.bottom < bounds.top <= 10000000,
                                'GEOTIFF_BOUNDS_INVALID')
                    report['checks'].append('resolution')
                    dtype = dataset.dtypes[0]
                    metadata['dtype'] = dtype if dtype in ('float32', 'float64') else None
                    require(dtype in ('float32', 'float64'), 'GEOTIFF_DTYPE_UNSUPPORTED')
                    report['checks'].append('dtype')
                    _, _, units, minimum, maximum = PROFILES[m['profile']]
                    nodata = dataset.nodata
                    require(nodata is not None and math.isfinite(nodata) and abs(nodata) <= 1e30
                            and not minimum <= nodata <= maximum, 'GEOTIFF_NODATA_INVALID')
                    metadata['nodata'] = float(nodata)
                    require(dataset.mask_flag_enums == ([MaskFlags.nodata],), 'GEOTIFF_MASK_UNSUPPORTED')
                    report['checks'].append('nodata')
                    require(dataset.scales == (1.0,) and dataset.offsets == (0.0,), 'GEOTIFF_SCALE_OFFSET_UNSUPPORTED')
                    metadata.update(scales=[1], offsets=[0])
                    report['checks'].append('scale_offset')
                    require(dataset.units == (units,), 'GEOTIFF_UNITS_MISMATCH')
                    metadata.update(units=units, output_units='unitless' if m['metric'] == 'ndvi' else 'celsius')
                    report['checks'].append('units')
                    tags = _tags(dataset)
                    require(tags.get('GIS_PROFILE') == m['profile'], 'GEOTIFF_PROFILE_MISMATCH')
                    metadata['profile'] = tags['GIS_PROFILE']
                    report['checks'].append('metadata_consistency')
                    total = 0.0
                    low, high = math.inf, -math.inf
                    for row in range(0, dataset.height, 256):
                        for column in range(0, dataset.width, 256):
                            values = dataset.read(1, window=Window(column, row, min(256, dataset.width - column),
                                min(256, dataset.height - row)), masked=False)
                            missing = values == nodata
                            stats['nodata_pixels'] += int(np.count_nonzero(missing))
                            stats['nonfinite_pixels'] += int(np.count_nonzero(~np.isfinite(values)))
                            require(stats['nonfinite_pixels'] == 0, 'GEOTIFF_NONFINITE_PIXELS')
                            valid = values[~missing].astype('float64')
                            if valid.size:
                                require(bool(np.all(valid >= minimum) and np.all(valid <= maximum)), 'GEOTIFF_SCIENTIFIC_RANGE')
                                if m['profile'] == 'lst_kelvin_ready':
                                    valid = valid - 273.15
                                stats['valid_pixels'] += int(valid.size)
                                total += float(np.sum(valid, dtype='float64'))
                                low, high = min(low, float(valid.min())), max(high, float(valid.max()))
                    require(stats['valid_pixels'] > 0, 'GEOTIFF_NO_VALID_PIXELS')
                    stats.update(mean=total / stats['valid_pixels'], min=low, max=high)
                    report['checks'].append('scientific_range')
                    report.update(valid=True, errors=[], error_code=None,
                        warnings=[{'code': 'PROVINCE_AND_YEAR_DECLARED_NOT_SPATIALLY_VERIFIED', 'count': 1}])
    except GeoTiffError as error:
        code = str(error)
        report.update(valid=False, error_code=code, errors=[{'code': code, 'count': 1}])
    except MemoryError:
        return report_failure(request, 'NATIVE_MEMORY_LIMIT')
    except Exception:
        report.update(valid=False, error_code='GEOTIFF_READ_ERROR', errors=[{'code': 'GEOTIFF_READ_ERROR', 'count': 1}])
    if len(json.dumps(report, allow_nan=False).encode('utf-8')) > 16384:
        return report_failure(request, 'NATIVE_OUTPUT_LIMIT')
    return report
