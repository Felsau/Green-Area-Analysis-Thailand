"""Credential-free LDD preparation and independent byte-for-byte verification.

ldd-source-area-v1 (pinned by migrations 038/039) preserves source features and
declared Shape_Area. It is kept byte-for-byte and gated by the frozen legacy
validator it was reviewed with, so editions prepared earlier still re-verify.
A dataset that only ldd-policy-v2 accepts (repaired geometry, normalised codes,
...) fails closed with PREPARE_METHOD_V2_REQUIRED instead of mixing policies.

ldd-geometry-area-v2 uses the validator's own derived geometry and geometry
area (one policy for validation, preparation and summary) and keeps the source
geometry of every repaired parcel. The queue cannot request it until a forward
migration allows it (docs/gis/ldd-field-policy.md). No clipping, simplification,
dropped parcel or claim of a complete province inventory in either method.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from uuid import UUID

from gis_worker import ldd_provider as ldd

METHOD = 'ldd-source-area-v1'
METHOD_V2 = 'ldd-geometry-area-v2'
METHODS = (METHOD, METHOD_V2)
VERIFIER = 'ldd-trusted-bytes-v1'
MAX_ARTIFACT = 20 * 1024**2
NAMES = {'ldd_geometry': 'geometry.json', 'ldd_summary': 'summary.json'}


def require(ok, code):
    if not ok:
        raise ldd.LddError(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def check_request(value):
    require(isinstance(value, dict) and set(value) == {'validation', 'dataset_id', 'edition_id', 'validation_result_id',
        'job_id', 'method_version'}, 'PREPARE_REQUEST_INVALID')
    ldd.check_request(value['validation'])
    for key in ('dataset_id', 'edition_id', 'validation_result_id', 'job_id'):
        try:
            require(str(UUID(value[key])) == value[key], 'PREPARE_REQUEST_INVALID')
        except (ValueError, TypeError, AttributeError):
            raise ldd.LddError('PREPARE_REQUEST_INVALID') from None
    require(value['method_version'] in METHODS, 'PREPARE_METHOD_UNSUPPORTED')
    return value


def stage_key(request):
    check_request(request)
    return request['job_id'] + '-' + str(request['validation']['attempt_number'])


def read_regular(path, maximum=MAX_ARTIFACT):
    path = Path(path)
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'PREPARE_UNSAFE_PATH')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= maximum, 'PREPARE_FILE_LIMIT')
        raw = stream.read(maximum + 1)
        require(len(raw) == info.st_size, 'PREPARE_FILE_CHANGED')
        return raw


def build(request, *, source_root=ldd.STORAGE_ROOT):
    """Reopen original ZIP and derive deterministic artifacts, never trust output."""
    check_request(request)
    validation = request['validation']
    if request['method_version'] == METHOD_V2:
        result, details = ldd.assess(validation, storage_root=source_root, collect=True)
        require(result['valid'], result.get('error_code') or 'PREPARE_INVALID_SOURCE')
        return _build_v2(request, result, details)
    result = ldd.validate_legacy_v1(validation, storage_root=source_root)
    if not result['valid']:
        require(not ldd.validate(validation, storage_root=source_root)['valid'], 'PREPARE_METHOD_V2_REQUIRED')
        raise ldd.LddError(result.get('error_code') or 'PREPARE_INVALID_SOURCE')
    raw = ldd._source_bytes(validation, source_root)
    require(hashlib.sha256(raw).hexdigest() == validation['manifest']['sha256'], 'LDD_SHA256_MISMATCH')
    name, parts = ldd._components(ldd.guarded_zip(raw))
    import fiona
    from fiona.io import ZipMemoryFile
    from fiona.transform import transform_geom
    from fiona.model import to_dict
    from shapely.geometry import shape
    legend = ldd._asset('ldd_codes.json', ldd.LEGEND_SHA256)['codes']
    meta = {k: request[k] for k in ('dataset_id', 'edition_id', 'validation_result_id', 'method_version')}
    meta.update(schema_version=1, province=validation['province'], data_year=validation['data_year'], month=0,
        input_hash=validation['input_hash'], input_revision=validation['input_revision'],
        source_sha256=validation['manifest']['sha256'], boundary_sha256=ldd.BOUNDARY_SHA256,
        legend_sha256=ldd.LEGEND_SHA256, display_crs='EPSG:4326', area_units='m2',
        coverage_mode='validated_source_footprint', complete_province_inventory=False,
        warnings=['BOUNDARY_APPROXIMATE', 'DATA_YEAR_METADATA_DECLARED', 'NOT_COMPLETE_PROVINCE_INVENTORY'])
    features = []
    by_code, by_main = defaultdict(float), {key: 0.0 for key in 'UAFWM'}
    total = 0.0
    with fiona.Env(GDAL_PAM_ENABLED='NO', GDAL_VRT_ENABLE_PYTHON='NO', GDAL_DISABLE_READDIR_ON_OPEN='YES'):
        with ZipMemoryFile(raw) as memory:
            with memory.open(name, enabled_drivers=['ESRI Shapefile'], encoding=result['encoding']) as collection:
                for number, feature in enumerate(collection):
                    props = {k.casefold(): v for k, v in dict(feature['properties']).items()}
                    code, main, area = props['lu_code'], props['lul1_code'], props['shape_area']
                    classification = ldd._main_code(code, main, legend)
                    require(classification is not None, 'UNKNOWN_CODE_REVIEW_REQUIRED')
                    geometry = to_dict(transform_geom(validation['manifest']['crs'], 'EPSG:4326', feature['geometry']))
                    geographic = shape(geometry)
                    require(not geographic.is_empty and geographic.is_valid, 'PREPARE_GEOMETRY_INVALID')
                    features.append({'type': 'Feature', 'id': number,
                        'properties': {'LU_CODE': code, 'LUL1_CODE': main, 'Shape_Area': area}, 'geometry': geometry})
                    by_code[code] += area
                    by_main[classification] += area
                    total += area
    require(len(features) == result['statistics']['feature_count'], 'PREPARE_FEATURE_MISMATCH')
    geometry = {'type': 'FeatureCollection', 'metadata': meta, 'features': features}
    summary = {'schema_version': 1, 'metadata': meta, 'feature_count': len(features), 'total_area_m2': total,
        'area_by_code_m2': dict(sorted(by_code.items())), 'area_by_main_m2': by_main}
    outputs = {'ldd_geometry': canonical(geometry), 'ldd_summary': canonical(summary)}
    require(all(0 < len(v) <= MAX_ARTIFACT for v in outputs.values()), 'PREPARE_ARTIFACT_LIMIT')
    return outputs


# v2 display coordinates (EPSG:4326) are rounded to 6 decimals (about 0.11 m): every vertex is kept, the file is
# about 40 % smaller and fits the 20 MiB artifact limit to about 25,000 parcels. Areas still come from the
# unrounded geometry that validation measured. A parcel that rounding would make invalid (7 to 32 per real
# central-region province) keeps full precision, so no parcel is altered beyond rounding or dropped.
DISPLAY_DECIMALS = 6


def _rounded(value, digits):
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, (list, tuple)):
        return [_rounded(v, digits) for v in value]
    return value


def _build_v2(request, result, details):
    from fiona.model import to_dict
    from fiona.transform import transform_geom
    from shapely.geometry import shape
    validation = request['validation']
    source_crs = validation['manifest']['crs']
    meta = {k: request[k] for k in ('dataset_id', 'edition_id', 'validation_result_id', 'method_version')}
    meta.update(schema_version=2, province=validation['province'], data_year=validation['data_year'], month=0,
        input_hash=validation['input_hash'], input_revision=validation['input_revision'],
        source_sha256=validation['manifest']['sha256'], boundary_sha256=result['boundary_sha256'],
        legend_sha256=ldd.LEGEND_V2_SHA256, display_crs='EPSG:4326', area_units='m2',
        area_method=ldd.policy.AREA_METHOD, policy=details['policy'], validation_outcome=details['outcome'],
        field_profile=details['field_profile'], field_mapping=details['field_mapping'],
        declared_area_units=details['declared_area_units'], repairs=details['repairs'],
        repaired_feature_count=sum(1 for f in details['features'] if f['repair']),
        boundary=details['boundary'], source_geometry_preserved='source_zip_and_repaired_parcels',
        coverage_mode='validated_source_footprint', complete_province_inventory=False,
        warnings=[w['code'] for w in result['warnings']] + ['NOT_COMPLETE_PROVINCE_INVENTORY'])
    features, by_code, by_main, total = [], defaultdict(float), {key: 0.0 for key in 'UAFWM'}, 0.0
    full_precision = []
    for f in details['features']:
        require(f['classification'] is not None and f['derived'] is not None, 'PREPARE_FEATURE_MISMATCH')
        properties = {'LU_CODE': f['lu_code'], 'LUL1_CODE': f['main_code'], 'declared_area': f['declared_area'],
                      'area_m2': f['area_m2'], 'classification': f['classification'], 'repaired': f['repair'] is not None}
        output = to_dict(transform_geom(f['metric_crs'], 'EPSG:4326', f['derived']))
        check = shape(output)
        require(not check.is_empty and check.is_valid and check.geom_type in ('Polygon', 'MultiPolygon'),
                'PREPARE_GEOMETRY_INVALID')
        rounded = {'type': output['type'], 'coordinates': _rounded(output['coordinates'], DISPLAY_DECIMALS)}
        kept = shape(rounded)
        if not kept.is_empty and kept.is_valid and kept.geom_type == check.geom_type:
            output = rounded
        else:
            full_precision.append(f['index'])
        feature = {'type': 'Feature', 'id': f['index'], 'properties': properties, 'geometry': output}
        if f['repair']:
            feature['source_geometry'] = to_dict(transform_geom(source_crs, 'EPSG:4326', f['source']))
            feature['repair'] = f['repair']
        features.append(feature)
        by_code[f['code_key']] += f['area_m2']
        by_main[f['classification']] += f['area_m2']
        total += f['area_m2']
    meta['display_coordinates'] = {'crs': 'EPSG:4326', 'decimals': DISPLAY_DECIMALS,
                                   'full_precision_feature_count': len(full_precision),
                                   'full_precision_features': full_precision[:100]}
    stats = result['statistics']
    require(len(features) == stats['feature_count'], 'PREPARE_FEATURE_MISMATCH')
    require(abs(total - stats['total_area_m2']) <= 1e-6 * max(1.0, total)
            and all(abs(by_main[k] - stats['area_by_main_m2'][k]) <= 1e-6 * max(1.0, total) for k in by_main),
            'PREPARE_AREA_POLICY_MISMATCH')
    geometry = {'type': 'FeatureCollection', 'metadata': meta, 'features': features}
    summary = {'schema_version': 2, 'metadata': meta, 'feature_count': len(features), 'total_area_m2': total,
        'area_by_code_m2': dict(sorted(by_code.items())), 'area_by_main_m2': by_main}
    outputs = {'ldd_geometry': canonical(geometry), 'ldd_summary': canonical(summary)}
    require(all(0 < len(v) <= MAX_ARTIFACT for v in outputs.values()), 'PREPARE_ARTIFACT_LIMIT')
    return outputs


def descriptors(outputs):
    return {kind: {'sha256': hashlib.sha256(raw).hexdigest(), 'byte_size': len(raw)} for kind, raw in outputs.items()}


def failure(request, code):
    check_request(request)
    require(isinstance(code, str) and re.fullmatch('[A-Z][A-Z0-9_]{0,59}', code), 'PREPARE_REQUEST_INVALID')
    return {'schema_version': 1, 'method_version': request['method_version'], 'valid': False, 'error_code': code,
        'dataset_id': request['dataset_id'], 'edition_id': request['edition_id'], 'job_id': request['job_id'],
        'validation_result_id': request['validation_result_id'], 'source_sha256': request['validation']['manifest']['sha256'],
        'input_hash': request['validation']['input_hash'], 'input_revision': request['validation']['input_revision'], 'artifacts': {}}


def prepare(request, *, source_root=ldd.STORAGE_ROOT, staging_root=Path('/data/prepare')):
    check_request(request)
    outputs = build(request, source_root=source_root)
    root = Path(staging_root)
    require(root.is_dir() and not root.is_symlink() and root.resolve() == root.absolute(), 'PREPARE_STORAGE_INVALID')
    used, entries = 0, 0
    for path in root.rglob('*'):
        entries += 1
        require(entries <= 4096 and not path.is_symlink(), 'PREPARE_STORAGE_LIMIT')
        if path.is_file():
            require(path.stat().st_nlink == 1, 'PREPARE_STORAGE_INVALID')
            used += path.stat().st_size
    require(used + sum(map(len, outputs.values())) <= 256 * 1024**2, 'PREPARE_STORAGE_LIMIT')
    directory = root / stage_key(request)
    if not directory.exists():
        directory.mkdir(mode=0o700)
    require(not directory.is_symlink() and directory.resolve().parent == root.resolve(), 'PREPARE_STORAGE_INVALID')
    for kind, raw in outputs.items():
        path = directory / NAMES[kind]
        if path.exists():
            require(read_regular(path) == raw, 'PREPARE_IMMUTABLE_CONFLICT')
        else:
            with path.open('xb') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
    report = failure(request, 'PREPARE_UNVERIFIED')
    report.update(valid=True, error_code=None, artifacts=descriptors(outputs))
    return report


def verify(request, *, source_root=ldd.STORAGE_ROOT, staging_root=Path('/data/prepare')):
    """Independent verifier recomputes ALL expected bytes from original source."""
    expected = build(request, source_root=source_root)
    directory = Path(staging_root) / stage_key(request)
    actual = {kind: read_regular(directory / name) for kind, name in NAMES.items()}
    require(actual == expected, 'PREPARE_ARTIFACT_MISMATCH')
    result = failure(request, 'PREPARE_UNVERIFIED')
    result.update(valid=True, error_code=None, artifacts=descriptors(actual), verifier_version=VERIFIER)
    return result
