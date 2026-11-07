"""Bounded LDD file validation against immutable, locally stored ZIP bytes.

This module has no Auth, database, network or service configuration. File names
are derived only from a validated SHA256 supplied by the trusted queue RPC.
"""
from __future__ import annotations

import codecs
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import unicodedata
from uuid import UUID
import zipfile

from gis_worker import ldd_policy as policy

ROOT = Path(__file__).resolve().parent
STORAGE_ROOT = Path('/data/ldd')
BUILD = 'ldd-local-v1'
# GADM level 1, frozen: the pre-v2 validator, GeoTIFF province clipping and failure reports pin it, and
# migration 034 accepted only this hash.
BOUNDARY_SHA256 = 'ac2b28255f22861ab644bf083fa40f28dd9da1294648d4b01cfc6f9cdc156a21'
# Policy v2 validation: the province layer shipped in the LDD package of each province that supplied
# one (source ldd-package), the same GADM outline elsewhere (source gadm-approx). Built by
# dev/gis_local/build_ldd_boundaries.py. Migration 051 lets the database accept this hash too.
BOUNDARY_LDD_ASSET = 'province_boundaries_ldd.json'
BOUNDARY_LDD_SHA256 = '1b6cf62b8f43504078c51c9ca3e94f6fffe56c2ca1b3765674d5aa2d7c62e1ac'
BOUNDARY_SOURCES = ('gadm-approx', 'ldd-package')
LEGEND_SHA256 = '34069bca1cf06474fab22f8b7211f91d4dc5d4deb37c0fec414efd05c63afbde'
MAX_ZIP_BYTES = 20 * 1024**2
MAX_EXPANDED_BYTES = 80 * 1024**2
MAX_MEMBER_BYTES = 20 * 1024**2
MAX_FEATURES = 100000
MAX_COORDINATES = 1000000
# Logical attribute roles bound into the upload manifest by migration 034. The
# actual source field names come from an approved ldd_policy field profile.
REQUIRED_FIELDS = ('LUL1_CODE', 'LU_CODE', 'Shape_Area')
CHECKS = ('source_hash_match', 'archive_safety', 'components', 'crs', 'geometry',
          'attributes', 'encoding', 'ldd_codes', 'province_bounds', 'dataset_association')
HASH = re.compile(r'^[0-9a-f]{64}$')
AUDIT_MAX_SAMPLES, AUDIT_MAX_REPAIRS = 10, 20
ENCODINGS = ('auto', 'utf-8', 'cp874', 'tis-620')


class LddError(ValueError):
    """Only a fixed public code, never a native error or input/path value."""


def require(condition, code):
    if not condition:
        raise LddError(code)


def check_request(value):
    require(isinstance(value, dict) and set(value) == {
        'upload_id', 'manifest', 'input_hash', 'input_revision', 'attempt_number',
        'province', 'data_year', 'encoding'}, 'LDD_REQUEST_INVALID')
    try:
        require(str(UUID(value['upload_id'])) == value['upload_id'], 'LDD_REQUEST_INVALID')
    except (ValueError, TypeError, AttributeError):
        raise LddError('LDD_REQUEST_INVALID') from None
    manifest = value['manifest']
    require(isinstance(manifest, dict) and set(manifest) == {
        'schema_version', 'provider', 'sha256', 'byte_size', 'provenance', 'crs',
        'data_kind', 'attributes'}, 'LDD_REQUEST_INVALID')
    require(type(manifest['schema_version']) is int and manifest['schema_version'] == 1
            and manifest['provider'] == 'real' and manifest['data_kind'] == 'polygon'
            and manifest['provenance'] == 'local-ldd-upload-v1'
            and isinstance(manifest['sha256'], str) and HASH.fullmatch(manifest['sha256'])
            and type(manifest['byte_size']) is int and 0 < manifest['byte_size'] <= MAX_ZIP_BYTES
            and manifest['crs'] in ('EPSG:32647', 'EPSG:32648', 'EPSG:4326')
            and manifest['attributes'] == list(REQUIRED_FIELDS), 'LDD_REQUEST_INVALID')
    require(isinstance(value['input_hash'], str) and HASH.fullmatch(value['input_hash'])
            and type(value['input_revision']) is int and 1 <= value['input_revision'] <= 2147483647
            and type(value['attempt_number']) is int and 1 <= value['attempt_number'] <= 3
            and type(value['data_year']) is int and 1980 <= value['data_year'] <= 2200
            and isinstance(value['province'], str) and 0 < len(value['province']) <= 120
            and value['encoding'] in ENCODINGS, 'LDD_REQUEST_INVALID')
    return value


def report_failure(request, code):
    check_request(request)
    require(isinstance(code, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,59}', code), 'LDD_REQUEST_INVALID')
    m = request['manifest']
    return {'schema_version': 1, 'provider_build': BUILD, 'upload_id': request['upload_id'],
            'artifact_sha256': m['sha256'], 'byte_size': m['byte_size'],
            'input_hash': request['input_hash'], 'input_revision': request['input_revision'],
            'province': request['province'], 'data_year': request['data_year'],
            'crs': m['crs'], 'encoding': request['encoding'], 'valid': False,
            'checks': [], 'errors': [{'code': code, 'count': 1}], 'warnings': [],
            'statistics': {'feature_count': 0, 'total_area_m2': 0, 'unknown_area_m2': 0,
                           'unknown_code_count': 0, 'composite_feature_count': 0,
                           'geometry_error_count': 0, 'area_by_main_m2': {k: 0 for k in 'UAFWM'}},
            'error_code': code, 'observed_sha256': None, 'boundary_sha256': BOUNDARY_SHA256}


def _source_bytes(request, storage_root):
    # storage_root is a trusted host-test parameter; queue/API JSON cannot set it.
    root = Path(storage_root)
    require(root.is_dir() and not root.is_symlink() and root.resolve() == root.absolute(), 'LDD_STORAGE_UNAVAILABLE')
    path = root / (request['manifest']['sha256'] + '.zip')
    require(not path.is_symlink(), 'LDD_FILE_UNSAFE')
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            meta = os.fstat(stream.fileno())
            require(stat.S_ISREG(meta.st_mode), 'LDD_FILE_UNSAFE')
            require(meta.st_size == request['manifest']['byte_size'] and meta.st_size <= MAX_ZIP_BYTES, 'LDD_SIZE_MISMATCH')
            raw = stream.read(MAX_ZIP_BYTES + 1)
        require(len(raw) == meta.st_size, 'LDD_SIZE_MISMATCH')
        return raw
    except LddError:
        raise
    except OSError:
        raise LddError('LDD_FILE_UNAVAILABLE') from None


def _layer_members(items):
    """The land-use layer's components among the file members of a package (policy.select_land_use_layer)."""
    layer = policy.select_land_use_layer([item.filename for item in items])
    require(layer is not None, 'SHAPEFILE_DATASET_COUNT')
    stem = str(PurePosixPath(layer).with_suffix('')).casefold()
    return [item for item in items
            if PurePosixPath(item.filename).suffix.lower() in policy.LAYER_SUFFIXES
            and str(PurePosixPath(item.filename).with_suffix('')).casefold() == stem]


def layer_archive(parts):
    """The land-use layer alone as a new in-memory ZIP with fixed ASCII member names.

    GDAL then never sees the rest of the package, its folder names or its member encodings.
    """
    output = BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_STORED) as archive:
        for suffix in policy.LAYER_SUFFIXES:
            if suffix in parts:
                archive.writestr(zipfile.ZipInfo('layer' + suffix, date_time=(1980, 1, 1, 0, 0, 0)), parts[suffix])
    return output.getvalue()


def guarded_zip(raw, *, package=False):
    """Check every member of an LDD ZIP and return the bytes of the files that will be read.

    ``package=False`` is the frozen pre-v2 rule: every file member must be a shapefile component and
    all are read. ``package=True`` accepts a province package: the path, size and ratio checks still
    run for every member, but only the one land-use layer's components are decompressed and returned.
    The other members (boundary layers, spreadsheets, documents) are never opened.
    """
    require(0 < len(raw) <= MAX_ZIP_BYTES, 'ZIP_SIZE_LIMIT')
    require(raw[:4] == b'PK\x03\x04', 'ZIP_CORRUPT')
    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            members = archive.infolist()
            require(0 < len(members) <= 64, 'ZIP_MEMBER_LIMIT')
            require(len(archive.comment) <= 1024, 'ZIP_COMMENT_LIMIT')
            seen, total = set(), 0
            for item in members:
                name = item.filename
                parts = name.split('/')
                require(item.orig_filename == name and len(name) <= 200 and name == name.strip()
                        and '\\' not in name and ':' not in name and '\x00' not in name
                        and not name.startswith('/') and not any(p in ('.', '..') for p in parts)
                        and all(p for p in (parts[:-1] if item.is_dir() else parts)), 'ZIP_PATH_UNSAFE')
                normalized = unicodedata.normalize('NFC', name).casefold()
                require(normalized not in seen, 'ZIP_DUPLICATE_NAME')
                seen.add(normalized)
                mode = item.external_attr >> 16
                require(not stat.S_ISLNK(mode), 'ZIP_SYMLINK')
                require(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), 'ZIP_SPECIAL_FILE')
                require(not item.flag_bits & 1, 'ZIP_ENCRYPTED')
                require(item.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'ZIP_COMPRESSION_UNSUPPORTED')
                require(0 <= item.file_size <= MAX_MEMBER_BYTES, 'ZIP_MEMBER_SIZE_LIMIT')
                total += item.file_size
                require(total <= MAX_EXPANDED_BYTES, 'ZIP_EXPANDED_SIZE_LIMIT')
                if item.file_size:
                    require(item.compress_size > 0 and item.file_size / item.compress_size <= 100, 'ZIP_COMPRESSION_RATIO')
                if not item.is_dir():
                    suffix = PurePosixPath(name).suffix.lower()
                    if package:
                        require(suffix not in policy.BLOCKED_SUFFIXES, 'UNSUPPORTED_ZIP_MEMBER')
                    else:
                        require(suffix in ('.shp', '.shx', '.dbf', '.prj', '.cpg', '.sbn', '.sbx', '.qix'), 'UNSUPPORTED_ZIP_MEMBER')
            readable = [item for item in members if not item.is_dir()]
            if package:
                readable = _layer_members(readable)
            files, actual_total = {}, 0
            for item in readable:
                chunks, actual = [], 0
                with archive.open(item) as stream:
                    while chunk := stream.read(65536):
                        actual += len(chunk)
                        actual_total += len(chunk)
                        require(actual <= min(MAX_MEMBER_BYTES, item.file_size), 'ZIP_MEMBER_SIZE_LIMIT')
                        require(actual_total <= MAX_EXPANDED_BYTES, 'ZIP_EXPANDED_SIZE_LIMIT')
                        chunks.append(chunk)
                require(actual == item.file_size, 'ZIP_SIZE_MISMATCH')
                files[item.filename] = b''.join(chunks)
            return files
    except LddError:
        raise
    except (zipfile.BadZipFile, EOFError, OSError, RuntimeError, NotImplementedError):
        raise LddError('ZIP_CORRUPT') from None


def _components(files):
    shapes = [name for name in files if PurePosixPath(name).suffix.lower() == '.shp']
    require(len(shapes) == 1, 'SHAPEFILE_DATASET_COUNT')
    stem = str(PurePosixPath(shapes[0]).with_suffix('')).casefold()
    result = {}
    for name, data in files.items():
        p = PurePosixPath(name)
        require(str(p.with_suffix('')).casefold() == stem, 'SHAPEFILE_COMPONENT_STEM')
        require(p.suffix.lower() not in result, 'ZIP_DUPLICATE_NAME')
        result[p.suffix.lower()] = data
    for ext in ('.shp', '.shx', '.dbf', '.prj'):
        require(ext in result, 'MISSING_COMPONENT_' + ext[1:].upper())
    require(len(result['.prj']) <= 65536 and len(result.get('.cpg', b'')) <= 64, 'METADATA_SIZE_LIMIT')
    return shapes[0], result


def _record_count(shp, shx, dbf):
    require(len(shp) >= 100 and len(shx) >= 100 and len(dbf) >= 33, 'SHAPEFILE_TRUNCATED')
    for data in (shp, shx):
        require(struct.unpack_from('>i', data, 0)[0] == 9994, 'SHAPEFILE_HEADER')
        require(struct.unpack_from('>i', data, 24)[0] * 2 == len(data), 'SHAPEFILE_LENGTH')
        require(struct.unpack_from('<i', data, 32)[0] in (5, 15, 25), 'GEOMETRY_TYPE')
    offsets, cursor = [], 100
    while cursor < len(shp):
        require(len(offsets) < MAX_FEATURES and cursor + 8 <= len(shp), 'FEATURE_COUNT_LIMIT')
        words = struct.unpack_from('>i', shp, cursor + 4)[0]
        require(words >= 2 and cursor + 8 + words * 2 <= len(shp), 'SHAPEFILE_TRUNCATED')
        offsets.append((cursor // 2, words))
        cursor += 8 + words * 2
    require(cursor == len(shp) and len(shx) - 100 == len(offsets) * 8, 'SHAPEFILE_COUNT_MISMATCH')
    for i, expected in enumerate(offsets):
        require(struct.unpack_from('>ii', shx, 100 + i * 8) == expected, 'SHX_INDEX_MISMATCH')
    count = struct.unpack_from('<I', dbf, 4)[0]
    header_len, record_len = struct.unpack_from('<HH', dbf, 8)
    require(0 < count == len(offsets) <= MAX_FEATURES, 'DBF_COUNT_MISMATCH')
    require(header_len >= 33 and record_len > 0 and len(dbf) >= header_len + count * record_len, 'DBF_TRUNCATED')
    require(all(dbf[header_len + i * record_len] != 42 for i in range(count)), 'DELETED_DBF_RECORD')
    return count, header_len, record_len


def _encoding(components, requested, count, header_len, record_len):
    def normalize(value):
        try:
            result = codecs.lookup(value).name
        except (LookupError, TypeError):
            raise LddError('ENCODING_UNSUPPORTED') from None
        require(result in ENCODINGS[1:], 'ENCODING_UNSUPPORTED')
        return result
    declared = None
    if '.cpg' in components:
        try:
            declared = normalize(components['.cpg'].decode('ascii', errors='strict').strip())
        except UnicodeError:
            raise LddError('ENCODING_INVALID') from None
    require(requested != 'auto' or declared is not None, 'ENCODING_UNSPECIFIED')
    encoding = declared if requested == 'auto' else normalize(requested)
    require(declared is None or declared == encoding, 'ENCODING_MISMATCH')
    dbf, fields, descriptor, offset = components['.dbf'], [], 32, 1
    while descriptor + 32 <= header_len and dbf[descriptor] != 13:
        width = dbf[descriptor + 16]
        require(width > 0, 'DBF_FIELD_LAYOUT_INVALID')
        fields.append((chr(dbf[descriptor + 11]), offset, width))
        descriptor += 32
        offset += width
    require(descriptor < len(dbf) and dbf[descriptor] == 13 and offset == record_len, 'DBF_FIELD_LAYOUT_INVALID')
    try:
        for i in range(count):
            row = dbf[header_len + i * record_len:header_len + (i + 1) * record_len]
            for kind, start, width in fields:
                if kind == 'C':
                    row[start:start + width].decode(encoding, errors='strict')
    except UnicodeError:
        raise LddError('ENCODING_INVALID') from None
    return encoding


def _asset(name, expected):
    path = ROOT / name
    require(path.is_file() and not path.is_symlink(), 'VALIDATION_ASSET_INVALID')
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, 'VALIDATION_ASSET_INVALID')
    return json.loads(raw)


def _main_code(code, main, legend):
    if type(main) is int:
        main = {1: 'U', 2: 'A', 3: 'F', 4: 'W', 5: 'M'}.get(main)
    if isinstance(main, str):
        main = main.strip()
    if not isinstance(code, str) or not isinstance(main, str) or main not in tuple('UAFWM'):
        return None
    code = code.strip()
    if not re.fullmatch(r'[UAFWM][0-9]{3}(?:/[UAFWM][0-9]{3}){0,7}', code):
        return None
    numeric = {'U': 1, 'A': 2, 'F': 3, 'W': 4, 'M': 5}
    if code in legend:
        return main if legend[code][0] == numeric[main] else None
    parts = code.split('/')
    if len(parts) > 1 and all(p in legend and legend[p][0] == numeric[main] for p in parts):
        return main
    return None


def _coordinates(value, depth=0):
    require(depth <= 5 and isinstance(value, (list, tuple)), 'COORDINATES_INVALID')
    if value and isinstance(value[0], (float, int)):
        require(len(value) in (2, 3) and all(type(x) in (float, int) and math.isfinite(x) and abs(x) <= 1e8 for x in value), 'COORDINATES_INVALID')
        return 1
    total = 0
    for item in value:
        total += _coordinates(item, depth + 1)
        require(total <= MAX_COORDINATES, 'COORDINATE_COUNT_LIMIT')
    return total


def _fixed_main_code(main):
    """Legacy fixed LUL1 integer pairing; must equal the legend-derived pairing."""
    return {1: 'U', 2: 'A', 3: 'F', 4: 'W', 5: 'M'}.get(main) if type(main) is int else main


def _repair(geometry):
    from shapely import make_valid
    try:
        return make_valid(geometry, method='structure', keep_collapsed=False)
    except TypeError:  # shapely < 2.1: never fall back to a different repair method
        raise LddError('GEOMETRY_ENGINE_UNSUPPORTED') from None


def _reason(geometry):
    from shapely.validation import explain_validity
    text = explain_validity(geometry)
    return re.sub(r'[^A-Za-z ]', '', text.split('[', 1)[0]).strip()[:40] or 'Invalid'


def audit_summary(details, repairs_total):
    """Closed, bounded projection of ``details`` for the stored report (migration 050)."""
    repair_keys = ('feature', 'reason', 'area_before_m2', 'area_after_m2', 'type_before', 'type_after')
    return {'policy_version': details['policy']['policy_version'], 'outcome': details['outcome'],
            'field_profile': details['field_profile'], 'field_mapping': details['field_mapping'],
            'declared_area_units': details['declared_area_units'],
            'feature_outcomes': dict(details['feature_outcomes']),
            'boundary': {'minor': details['boundary']['minor'], 'review': details['boundary']['review'],
                         'fatal': details['boundary']['fatal'],
                         'outside_area_m2': round(details['boundary']['outside_area_m2'], 3)},
            'unknown_samples': [{**entry, 'area_m2': round(entry['area_m2'], 3)}
                                for entry in details['unknown_samples'].values()][:AUDIT_MAX_SAMPLES],
            'repairs': [{key: repair[key] for key in repair_keys} for repair in details['repairs'][:AUDIT_MAX_REPAIRS]],
            'repairs_total': repairs_total}


def validate(request, *, storage_root=STORAGE_ROOT):
    report, details = assess(request, storage_root=storage_root)
    # A resource or output failure says nothing about the file, so it carries no audit.
    if report.get('error_code') in ('NATIVE_MEMORY_LIMIT', 'NATIVE_OUTPUT_LIMIT', 'NATIVE_PROCESS_FAILED'):
        return report
    repairs_total = next((w['count'] for w in report['warnings'] if w['code'] == 'GEOMETRY_REPAIRED'), len(details['repairs']))
    audited = {**report, 'audit': audit_summary(details, repairs_total)}
    return audited if len(json.dumps(audited, allow_nan=False).encode()) <= 16384 else report


def assess(request, *, storage_root=STORAGE_ROOT, collect=False):
    """Validate under ldd-policy-v2 and return (SQL 034 report, audit details).

    The report keeps the exact migration-034 shape. Field mapping, policy
    versions, repairs, unknown-code samples and per-feature derived geometry
    are in ``details`` (used by preparation and the local inventory tool).
    """
    check_request(request)
    report = report_failure(request, 'VALIDATION_FAILED')
    report['errors'] = []
    report['boundary_sha256'] = BOUNDARY_LDD_SHA256   # the asset this validation reads (failure reports name the GADM one)
    errors, warnings = {}, {}
    details = {'policy': policy.policy_summary(), 'outcome': 'rejected', 'field_profile': None,
               'field_mapping': None, 'source_fields': None, 'declared_area_units': None,
               'boundary_source': 'gadm-approx',
               'repairs': [], 'unknown_samples': {}, 'boundary': {'minor': 0, 'review': 0, 'fatal': 0,
               'outside_area_m2': 0.0}, 'features': [] if collect else None,
               'feature_outcomes': {k: 0 for k in ('accepted', 'accepted_with_warnings', 'review_required', 'rejected')}}

    def error(code, count=1):
        if code in errors or len(errors) < 20:
            errors[code] = errors.get(code, 0) + count

    def warn(code, count=1):
        if code in warnings or len(warnings) < 16:
            warnings[code] = warnings.get(code, 0) + count

    try:
        raw = _source_bytes(request, storage_root)
        observed = hashlib.sha256(raw).hexdigest()
        report['observed_sha256'] = observed
        require(observed == request['manifest']['sha256'], 'LDD_SHA256_MISMATCH')
        report['checks'].append('source_hash_match')
        files = guarded_zip(raw, package=True)
        report['checks'].append('archive_safety')
        _, parts = _components(files)
        count, header_len, record_len = _record_count(parts['.shp'], parts['.shx'], parts['.dbf'])
        report['checks'].append('components')
        encoding = _encoding(parts, request['encoding'], count, header_len, record_len)
        report['encoding'] = encoding
        report['checks'].append('encoding')
        # GDAL gets the land-use layer alone, under fixed names. The package, the other members and
        # the bytes already checked are released first, so a large layer is held only once or twice.
        layer, prj = layer_archive(parts), parts['.prj']
        files = parts = raw = None
        # Import native dependencies only inside the resource-limited child.
        import fiona
        from fiona.io import ZipMemoryFile
        from fiona.transform import transform_geom
        from rasterio.crs import CRS
        from shapely.geometry import mapping, shape
        from shapely import prepare as prepare_geometry
        try:
            crs = CRS.from_wkt(prj.decode('utf-8-sig', errors='strict'))
        except Exception:
            raise LddError('CRS_INVALID') from None
        source_crs = request['manifest']['crs']
        require(crs.to_epsg() in (32647, 32648, 4326) and crs.to_string() == source_crs, 'CRS_MISMATCH')
        report['checks'].append('crs')
        boundaries = _asset(BOUNDARY_LDD_ASSET, BOUNDARY_LDD_SHA256)
        boundary = next((f for f in boundaries['features'] if f['properties']['name'] == request['province']), None)
        require(boundary is not None, 'PROVINCE_UNKNOWN')
        details['boundary_source'] = boundary['properties'].get('source')
        require(details['boundary_source'] in BOUNDARY_SOURCES, 'VALIDATION_ASSET_INVALID')
        legend = _asset('ldd_codes.json', LEGEND_SHA256)['codes']
        try:
            classes = policy.main_classes(legend)
        except policy.PolicyError:
            raise LddError('VALIDATION_ASSET_INVALID') from None
        require(all(_fixed_main_code(v) == k for k, v in classes.items()), 'VALIDATION_ASSET_INVALID')
        report['checks'].append('dataset_association')
        zones = {}

        def zone(name_):
            # Approximate repository boundary, measured in metres in the parcel's
            # UTM zone; never an arbitrary user-provided AOI or remote shape.
            if name_ not in zones:
                exact = shape(transform_geom('EPSG:4326', name_, boundary['geometry']))
                require(not exact.is_empty and exact.is_valid, 'VALIDATION_ASSET_INVALID')
                minor, review = exact.buffer(policy.BOUNDARY_MINOR_M), exact.buffer(policy.BOUNDARY_REVIEW_M)
                for g in (exact, minor, review):
                    prepare_geometry(g)
                zones[name_] = (exact, minor, review)
            return zones[name_]

        stats = report['statistics']
        coordinate_count = 0
        repaired_change = 0.0
        with fiona.Env(GDAL_PAM_ENABLED='NO', GDAL_VRT_ENABLE_PYTHON='NO', GDAL_DISABLE_READDIR_ON_OPEN='YES'):
            with ZipMemoryFile(layer) as memory:
                with memory.open('layer.shp', enabled_drivers=['ESRI Shapefile'], encoding=encoding) as collection:
                    schema = dict(collection.schema['properties'])
                    try:
                        profile_id, mapping_ = policy.resolve_profile(schema)
                    except policy.PolicyError as exc:
                        raise LddError(str(exc)) from None
                    details['field_profile'] = profile_id
                    details['field_mapping'] = mapping_
                    details['source_fields'] = {k: str(v)[:20] for k, v in list(schema.items())[:64]}
                    units = policy.declared_area_units(profile_id, source_crs)
                    details['declared_area_units'] = units
                    report['checks'].append('attributes')
                    for feature in collection:
                        index = stats['feature_count']
                        stats['feature_count'] += 1
                        require(stats['feature_count'] <= MAX_FEATURES, 'FEATURE_COUNT_LIMIT')
                        props = dict(feature['properties'])
                        require(all(not isinstance(v, bytes) and not (isinstance(v, str) and '\ufffd' in v) for v in props.values()), 'ENCODING_INVALID')
                        geom_json = feature['geometry']
                        issues, area, derived, repair, notes = [], 0.0, None, None, set()
                        if geom_json is None or geom_json['type'] not in ('Polygon', 'MultiPolygon'):
                            issues.append('GEOMETRY_TYPE')
                        else:
                            coordinate_count += _coordinates(geom_json['coordinates'])
                            require(coordinate_count <= MAX_COORDINATES, 'COORDINATE_COUNT_LIMIT')
                            geom = shape(geom_json)
                            if geom.is_empty:
                                issues.append('GEOMETRY_EMPTY')
                            else:
                                minx, _, maxx, _ = geom.bounds
                                metric = policy.metric_crs(source_crs, (minx + maxx) / 2)
                                projected = geom if metric == source_crs else shape(transform_geom(source_crs, metric, geom_json))
                                if not geom.is_valid or not projected.is_valid:
                                    fixed = _repair(projected)
                                    code = policy.repair_accepted(projected.area, fixed.area, fixed.geom_type,
                                                                  fixed.is_valid, fixed.is_empty)
                                    if code:
                                        issues.append(code)
                                    else:
                                        repair = {'feature': index, 'method': 'shapely.make_valid(structure)',
                                                  'reason': _reason(projected), 'area_before_m2': round(projected.area, 3),
                                                  'area_after_m2': round(fixed.area, 3),
                                                  'type_before': projected.geom_type, 'type_after': fixed.geom_type}
                                        repaired_change += abs(fixed.area - projected.area)
                                        warn('GEOMETRY_REPAIRED'); notes.add('GEOMETRY_REPAIRED')
                                        if len(details['repairs']) < 50:
                                            details['repairs'].append(repair)
                                        projected = fixed
                                if not issues:
                                    area = projected.area
                                    if not (math.isfinite(area) and 0 < area <= 1e12):
                                        issues.append('AREA_INVALID'); area = 0.0
                                if not issues:
                                    exact, minor, review = zone(metric)
                                    inside = exact.covers(projected)
                                    tier = None
                                    if not inside:
                                        within_minor = minor.covers(projected)
                                        within_review = within_minor or review.covers(projected)
                                        beyond = 0.0 if within_minor else projected.difference(minor).area / area
                                        tier = policy.boundary_tier(False, within_minor, within_review, beyond)
                                        details['boundary']['outside_area_m2'] += projected.difference(exact).area
                                    if tier == 'BOUNDARY_OUTSIDE_MINOR':
                                        details['boundary']['minor'] += 1
                                        warn(tier); notes.add(tier)
                                    elif tier:
                                        details['boundary']['review' if tier in policy.REVIEW else 'fatal'] += 1
                                        issues.append(tier)
                                    derived = projected
                        for code in issues:
                            error(code)
                        problems = set(issues)
                        if any(code in policy.GEOMETRY_CODES for code in issues):
                            stats['geometry_error_count'] += 1
                        declared = props[mapping_['declared_area']]
                        if type(declared) not in (int, float) or not math.isfinite(declared) or declared < 0:
                            error('AREA_INVALID'); problems.add('AREA_INVALID')
                        elif derived is not None:
                            # Without stated units the value is still checked as m2: a match
                            # shows the units, a mismatch is flagged (never silently ignored).
                            tier = policy.declared_area_tier(declared, area)
                            if tier and units != 'm2':
                                warn('DECLARED_AREA_UNITS_UNVERIFIED'); notes.add('DECLARED_AREA_UNITS_UNVERIFIED')
                            if tier == 'AREA_DECLARED_MINOR_DIFF':
                                warn(tier); notes.add(tier)
                            elif tier:
                                error(tier); problems.add(tier)
                        stats['total_area_m2'] += area
                        require(stats['total_area_m2'] <= 1e12, 'AREA_LIMIT')
                        code_value, main_value = props[mapping_['lu_code']], props[mapping_['main_code']]
                        result = policy.classify(code_value, main_value, legend, classes)
                        if result['composite']:
                            stats['composite_feature_count'] += 1
                        if result['normalised']:
                            warn('NUMERIC_MAIN_CODE_NORMALISED'); notes.add('NUMERIC_MAIN_CODE_NORMALISED')
                        if result['classification'] is None:
                            stats['unknown_code_count'] += 1
                            stats['unknown_area_m2'] += area
                            error('UNKNOWN_CODE_REVIEW_REQUIRED'); problems.add('UNKNOWN_CODE_REVIEW_REQUIRED')
                            key = result['code_key'] + '|' + result['reason']
                            samples = details['unknown_samples']
                            if key in samples or len(samples) < 10:
                                entry = samples.setdefault(key, {'value': result['code_key'], 'main': policy._code_key(main_value),
                                                                 'reason': result['reason'], 'count': 0, 'area_m2': 0.0})
                                entry['count'] += 1
                                entry['area_m2'] += area
                        else:
                            stats['area_by_main_m2'][result['classification']] += area
                        details['feature_outcomes'][policy.outcome(problems, notes)] += 1
                        if collect:
                            details['features'].append({'index': index, 'classification': result['classification'],
                                'code_key': result['code_key'], 'lu_code': code_value, 'main_code': main_value,
                                'declared_area': declared, 'area_m2': area, 'metric_crs': None if derived is None else metric,
                                'derived': None if derived is None else mapping(derived),
                                'source': geom_json if repair else None, 'repair': repair})
        require(stats['feature_count'] == count, 'FEATURE_COUNT_MISMATCH')
        total = stats['total_area_m2']
        outside = details['boundary']['outside_area_m2']
        if total > 0 and outside > total * policy.DATASET_OUTSIDE_SHARE_MAX and outside > policy.DATASET_OUTSIDE_MIN_M2:
            error('BOUNDARY_OUTSIDE_AREA_REVIEW_REQUIRED')
        if policy.repair_limit_exceeded(warnings.get('GEOMETRY_REPAIRED', 0), stats['feature_count'], repaired_change, total):
            error('GEOMETRY_REPAIR_LIMIT_REVIEW_REQUIRED')
        if not stats['geometry_error_count'] and not (set(errors) & {'BOUNDARY_OUTSIDE_AREA_REVIEW_REQUIRED',
                'GEOMETRY_REPAIR_LIMIT_REVIEW_REQUIRED'}):
            report['checks'].extend(('geometry', 'province_bounds'))
        if not stats['unknown_code_count']:
            report['checks'].append('ldd_codes')
    except LddError as exc:
        error(str(exc))
    except MemoryError:
        return report_failure(request, 'NATIVE_MEMORY_LIMIT'), details
    except Exception as exc:
        # GDAL/OGR/GEOS/PROJ failures describe the file; anything else is our fault.
        native = type(exc).__module__.split('.')[0] in ('fiona', 'rasterio', 'shapely', 'pyproj')
        error('SHAPEFILE_READ_ERROR' if native else 'NATIVE_PROCESS_FAILED')
    ordered = sorted(errors.items(), key=lambda item: item[0] in policy.REVIEW)  # fatal first, stable
    report['errors'] = [{'code': code, 'count': n} for code, n in ordered]
    # The outline is either the approximate GADM one or the data producer's own; never presented as independent.
    outline = 'BOUNDARY_FROM_DATA_PRODUCER' if details['boundary_source'] == 'ldd-package' else 'BOUNDARY_APPROXIMATE'
    base = [{'code': outline, 'count': 1}, {'code': 'DATA_YEAR_METADATA_DECLARED', 'count': 1}]
    markers = [{'code': 'LDD_POLICY_V2', 'count': 1}]
    if details['field_profile']:
        markers.append({'code': 'FIELD_PROFILE_' + details['field_profile'].upper().replace('-', '_'), 'count': 1})
    report['warnings'] = base + markers + [{'code': code, 'count': n} for code, n in warnings.items()]
    details['outcome'] = policy.outcome(errors, warnings)
    report['valid'] = not errors
    report['error_code'] = ordered[0][0] if ordered else None
    if len(json.dumps(report, allow_nan=False).encode()) > 16384:
        return report_failure(request, 'NATIVE_OUTPUT_LIMIT'), details
    return report, details


def validate_legacy_v1(request, *, storage_root=STORAGE_ROOT):
    """Frozen pre-policy-v2 validator, kept verbatim for ldd-source-area-v1.

    Used only to rebuild/verify v1 preparation artifacts, so editions prepared
    before ldd-policy-v2 keep re-verifying byte-for-byte under the rules they
    were produced with. New validation results always come from assess().
    """
    check_request(request)
    report = report_failure(request, 'VALIDATION_FAILED')
    report['errors'] = []
    errors = {}

    def error(code):
        if code in errors or len(errors) < 20:
            errors[code] = errors.get(code, 0) + 1

    try:
        raw = _source_bytes(request, storage_root)
        observed = hashlib.sha256(raw).hexdigest()
        report['observed_sha256'] = observed
        require(observed == request['manifest']['sha256'], 'LDD_SHA256_MISMATCH')
        report['checks'].append('source_hash_match')
        files = guarded_zip(raw)
        report['checks'].append('archive_safety')
        name, parts = _components(files)
        count, header_len, record_len = _record_count(parts['.shp'], parts['.shx'], parts['.dbf'])
        report['checks'].append('components')
        encoding = _encoding(parts, request['encoding'], count, header_len, record_len)
        report['encoding'] = encoding
        report['checks'].append('encoding')
        # Import native dependencies only inside the resource-limited child.
        import fiona
        from fiona.io import ZipMemoryFile
        from fiona.transform import transform_geom
        from rasterio.crs import CRS
        from shapely.geometry import shape
        try:
            crs = CRS.from_wkt(parts['.prj'].decode('utf-8-sig', errors='strict'))
        except Exception:
            raise LddError('CRS_INVALID') from None
        require(crs.to_epsg() in (32647, 32648, 4326) and crs.to_string() == request['manifest']['crs'], 'CRS_MISMATCH')
        report['checks'].append('crs')
        boundaries = _asset('province_boundaries.json', BOUNDARY_SHA256)
        boundary = next((f for f in boundaries['features'] if f['properties']['name'] == request['province']), None)
        require(boundary is not None, 'PROVINCE_UNKNOWN')
        # This repository boundary is approximate; tolerate only ~200 m at a
        # province edge, never an arbitrary user-provided AOI or remote shape.
        aoi = shape(boundary['geometry']).buffer(0.002)
        require(not aoi.is_empty and aoi.is_valid, 'VALIDATION_ASSET_INVALID')
        legend = _asset('ldd_codes.json', LEGEND_SHA256)['codes']
        report['checks'].append('dataset_association')
        report['warnings'] = [{'code': 'BOUNDARY_APPROXIMATE', 'count': 1}, {'code': 'DATA_YEAR_METADATA_DECLARED', 'count': 1}]
        stats = report['statistics']
        coordinate_count = 0
        with fiona.Env(GDAL_PAM_ENABLED='NO', GDAL_VRT_ENABLE_PYTHON='NO', GDAL_DISABLE_READDIR_ON_OPEN='YES'):
            with ZipMemoryFile(raw) as memory:
                with memory.open(name, enabled_drivers=['ESRI Shapefile'], encoding=encoding) as collection:
                    keys = {k.casefold(): k for k in collection.schema['properties']}
                    require(all(k.casefold() in keys for k in REQUIRED_FIELDS), 'ATTRIBUTES_MISSING')
                    report['checks'].append('attributes')
                    for feature in collection:
                        stats['feature_count'] += 1
                        require(stats['feature_count'] <= MAX_FEATURES, 'FEATURE_COUNT_LIMIT')
                        props = dict(feature['properties'])
                        require(all(not isinstance(v, bytes) and not (isinstance(v, str) and '\ufffd' in v) for v in props.values()), 'ENCODING_INVALID')
                        geom_json = feature['geometry']
                        geometry_ok, area = True, 0.0
                        if geom_json is None or geom_json['type'] not in ('Polygon', 'MultiPolygon'):
                            error('GEOMETRY_TYPE'); geometry_ok = False
                        else:
                            coordinate_count += _coordinates(geom_json['coordinates'])
                            require(coordinate_count <= MAX_COORDINATES, 'COORDINATE_COUNT_LIMIT')
                            geom = shape(geom_json)
                            if geom.is_empty or not geom.is_valid:
                                error('GEOMETRY_INVALID'); geometry_ok = False
                            else:
                                metric_crs = 'EPSG:32647' if geom.centroid.x < 102 else 'EPSG:32648'
                                projected = geom if crs.to_epsg() != 4326 else shape(transform_geom('EPSG:4326', metric_crs, geom_json))
                                area = projected.area
                                require(math.isfinite(area) and 0 < area <= 1e12, 'AREA_INVALID')
                                geographic = shape(transform_geom(crs.to_string(), 'EPSG:4326', geom_json))
                                if not aoi.covers(geographic):
                                    error('OUTSIDE_PROVINCE'); geometry_ok = False
                        if not geometry_ok:
                            stats['geometry_error_count'] += 1
                        declared_area = props[keys['shape_area']]
                        if type(declared_area) not in (int, float) or not math.isfinite(declared_area) or declared_area < 0:
                            error('AREA_INVALID')
                        elif not math.isclose(declared_area, area, rel_tol=0.001, abs_tol=1):
                            error('AREA_MISMATCH')
                        stats['total_area_m2'] += area
                        require(stats['total_area_m2'] <= 1e12, 'AREA_LIMIT')
                        code, main = props[keys['lu_code']], props[keys['lul1_code']]
                        classification = _main_code(code, main, legend)
                        if isinstance(code, str) and '/' in code:
                            stats['composite_feature_count'] += 1
                        if classification is None:
                            stats['unknown_code_count'] += 1
                            stats['unknown_area_m2'] += area
                            error('UNKNOWN_CODE_REVIEW_REQUIRED')
                        else:
                            stats['area_by_main_m2'][classification] += area
        require(stats['feature_count'] == count, 'FEATURE_COUNT_MISMATCH')
        if not stats['geometry_error_count']:
            report['checks'].extend(('geometry', 'province_bounds'))
        if not stats['unknown_code_count']:
            report['checks'].append('ldd_codes')
        report['valid'] = not errors
        report['error_code'] = next(iter(errors), None)
    except LddError as exc:
        error(str(exc))
    except MemoryError:
        return report_failure(request, 'NATIVE_MEMORY_LIMIT')
    except Exception:
        error('SHAPEFILE_READ_ERROR')
    report['errors'] = [{'code': code, 'count': count} for code, count in errors.items()]
    if errors:
        report['valid'] = False
        report['error_code'] = next(iter(errors))
    if len(json.dumps(report, allow_nan=False).encode()) > 16384:
        return report_failure(request, 'NATIVE_OUTPUT_LIMIT')
    return report
