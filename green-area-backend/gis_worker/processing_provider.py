"""Offline numeric scene adapter, never a Google Earth Engine client.

Inputs are four artificial pixels, repeated over a synthetic year template.
Province/district are workflow identities, not spatial sampling of those places.
Only fixed local source files are parsed as AST data: no imports/eval/exec, dotenv,
SDK initialization, credentials, database, URL, cache or live network access.
"""
from __future__ import annotations
import ast
from copy import deepcopy
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
import time
from statistics import mean, median
from uuid import UUID

from gis_worker import method_registry as methods
from gis_worker import source_integrity as si

ROOT = Path(__file__).resolve().parent
FIXTURE_ROOT = ROOT / 'processing_fixtures'
LEGACY_ROOT = Path('/app/legacy')
BUILD = 'gee-offline-v1'
OFFLINE_BOUNDARY_WAIT_SECONDS = 12
# v0 identity of the reviewed legacy-v1 sources, exactly as pinned in manifests
# by applied migration 035. Derived from the approved method definition; the
# files themselves are verified under source-text-lf-sha256-v1 (LF/CRLF safe).
LEGACY_SHA = methods.legacy_identity_map(methods.LEGACY_V1)
CATALOG = {
    ('ndvi', 'standard'): ('67d90bb99607073a2fcd61455c2b2bd13c98e0e53df6ada6bf4793f4830caabf', 2904),
    ('ndvi', 'no_data'): ('c15d94ae4183bbcdfa322245ae90598c9d527db5a9bce5b858dbf6a2c86c6a25', 2711),
    ('ndvi', 'transient_once'): ('1cb31c9db70e8e1e5feb5869f9b8f49f352d7e9429a62a096a61bb537621f5a2', 2910),
    ('lst', 'standard'): ('ea10c93aa944930f13de0898350261021c351f850f45db78ad238838318b9a1e', 2423),
    ('lst', 'no_data'): ('ccc7cfb27a3d8dd41e554d27b12b7b8a66a44ec8644af6e58c4ef911724678da', 2398),
    ('lst', 'transient_once'): ('5d55d3ce099d6916fb3aa68998f961c5a2fa05dae857e7708db3f3aef33929d3', 2429),
}
MANIFEST_KEYS = {'schema_version','provider','mode','provenance','data_kind','fixture_id','sha256','byte_size',
    'crs','bands','units','resolution','province','district','metric','data_year','month','scenario',
    'start_date','end_date','scale_m','processing_version','source_collections','cloud_mask','legacy_pipeline_sha256'}
HASH = re.compile(r'^[0-9a-f]{64}$')


class ProcessingError(ValueError):
    """Fixed safe code only; never native diagnostics or caller text."""


def require(value, code='PROCESSING_INPUT_INVALID'):
    if not value:
        raise ProcessingError(code)


def source_spec(metric, scenario):
    require((metric, scenario) in CATALOG)
    sha, size = CATALOG[(metric, scenario)]
    ndvi = metric == 'ndvi'
    return {'fixture_id': f'p3-{metric}-{scenario.replace("_", "-")}-v1', 'sha256': sha, 'byte_size': size,
        'crs': 'EPSG:32647', 'bands': ['B8','B4','cs'] if ndvi else ['ST_B10','QA_PIXEL'],
        'units': 'unitless' if ndvi else 'celsius', 'resolution': 10 if ndvi else 30,
        'source_collections': ['COPERNICUS/S2_SR_HARMONIZED','GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED'] if ndvi
            else ['LANDSAT/LC08/C02/T1_L2','LANDSAT/LC09/C02/T1_L2'],
        'cloud_mask': 's2-cloud-score-plus-0.6-scene20-fallback80-monthly80' if ndvi else 'landsat-qa-bits3-4-scene40',
        'legacy_pipeline_sha256': dict(LEGACY_SHA)}


def check_request(value):
    require(isinstance(value, dict) and set(value) == {'processing_id','manifest','input_hash','input_revision','attempt_number'})
    try:
        require(str(UUID(value['processing_id'])) == value['processing_id'])
    except (ValueError, TypeError, AttributeError):
        raise ProcessingError('PROCESSING_INPUT_INVALID') from None
    m = value['manifest']
    require(isinstance(m, dict) and set(m) == MANIFEST_KEYS)
    require(m['metric'] in ('ndvi','lst') and m['scenario'] in ('standard','no_data','transient_once'))
    require(type(m['schema_version']) is int and m['schema_version'] == 3
        and m['provider'] == 'offline_synthetic' and m['mode'] == 'offline_synthetic'
        and m['provenance'] == 'gis-processing-offline-v1' and m['data_kind'] == 'raster'
        and m['processing_version'] == BUILD)
    require(type(m['data_year']) is int and (2017 if m['metric'] == 'ndvi' else 2013) <= m['data_year'] <= date.today().year)
    require(type(m['month']) is int and 0 <= m['month'] <= 12)
    require(isinstance(m['province'], str) and 0 < len(m['province']) <= 120 and not any(ord(c)<32 for c in m['province']))
    require(m['district'] is None or (isinstance(m['district'], str) and 0 < len(m['district']) <= 120 and not any(ord(c)<32 for c in m['district'])))
    require(type(m['scale_m']) is int and m['scale_m'] == (500 if m['district'] is None else 100))
    start = date(m['data_year'], m['month'] or 1, 1)
    end = date(m['data_year'] + 1, 1, 1) if m['month'] in (0,12) else date(m['data_year'], m['month'] + 1, 1)
    require(m['start_date'] == start.isoformat() and m['end_date'] == end.isoformat())
    source = source_spec(m['metric'], m['scenario'])
    require(all(m[k] == v for k, v in source.items()))
    require(type(m['byte_size']) is int and type(m['resolution']) is int)
    require(isinstance(value['input_hash'], str) and HASH.fullmatch(value['input_hash'])
        and type(value['input_revision']) is int and value['input_revision'] == 1
        and type(value['attempt_number']) is int and 1 <= value['attempt_number'] <= 3)
    return value


def report_failure(request, code):
    check_request(request)
    require(isinstance(code, str) and re.fullmatch('[A-Z][A-Z0-9_]{0,59}', code))
    return {'schema_version': 1, 'provider_build': BUILD, 'mode': 'offline_synthetic', 'synthetic': True,
        'processing_id': request['processing_id'], 'artifact_sha256': request['manifest']['sha256'],
        'input_hash': request['input_hash'], 'input_revision': request['input_revision'], 'valid': False,
        'error_code': code, 'statistics': {'valid_pixels': 0, 'mean': None, 'min': None, 'max': None},
        'metadata': deepcopy(request['manifest'])}


def _constant(tree, name):
    values = [n.value.value for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
        and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
    require(len(values) == 1, 'PROCESSING_LEGACY_SPEC_INVALID')
    return values[0]


def _function(tree, name):
    values = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    require(len(values) == 1, 'PROCESSING_LEGACY_SPEC_INVALID')
    return values[0]


def _filters(function, field):
    return [call.args[1].value for call in ast.walk(function)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == 'lt'
        and len(call.args) == 2 and isinstance(call.args[0], ast.Constant) and call.args[0].value == field
        and isinstance(call.args[1], ast.Constant)]


def _legacy_sources(legacy_root):
    """Raw bytes of the fixed legacy files and the one approved definition they match."""
    raw = {}
    for path, container_name in methods.LEGACY_FILE_NAMES.items():
        file = Path(legacy_root) / container_name
        require(file.is_file() and not file.is_symlink(), 'PROCESSING_LEGACY_SOURCE_CHANGED')
        data = file.read_bytes()
        require(len(data) <= 200000, 'PROCESSING_LEGACY_SOURCE_CHANGED')
        raw[path] = data
    try:
        return methods.match_sources(raw), raw
    except (methods.MethodError, si.SourceIntegrityError):
        raise ProcessingError('PROCESSING_LEGACY_SOURCE_CHANGED') from None


def legacy_spec(legacy_root=LEGACY_ROOT, *, with_definition=False):
    """Read fixed, hash-bound calculation specifications as AST *data* only.

    The sources must match an approved method definition (hash scheme
    source-text-lf-sha256-v1) before any parsing, and the parsed values must
    equal that definition's reviewed scientific expectations.
    """
    defn, raw = _legacy_sources(legacy_root)
    want = defn.scientific_expected
    trees = {methods.LEGACY_FILE_NAMES[path]: ast.parse(data.decode('utf-8-sig')) for path, data in raw.items()}
    g, n, l = (trees[name] for name in ('gee_utils.py','ndvi_compute.py','lst.py'))
    score = _constant(g, '_CS_CLEAR_THRESHOLD')
    require(type(score) in (int,float) and 0 <= score <= 1 and score == want['cs_threshold'], 'PROCESSING_LEGACY_SPEC_INVALID')
    annual = _function(n, '_compute_ndvi_annual')
    monthly = _function(n, '_compute_ndvi_monthly')
    band_orders = []
    for f in (annual, monthly):
        for call in ast.walk(f):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == 'normalizedDifference':
                require(len(call.args) == 1 and isinstance(call.args[0], ast.List), 'PROCESSING_LEGACY_SPEC_INVALID')
                require(all(isinstance(v, ast.Constant) and isinstance(v.value, str) for v in call.args[0].elts), 'PROCESSING_LEGACY_SPEC_INVALID')
                band_orders.append([v.value for v in call.args[0].elts])
    require(band_orders and all(v == list(want['ndvi_bands']) for v in band_orders), 'PROCESSING_LEGACY_SPEC_INVALID')
    scale_function = _function(g, 'scale_lst')
    assignment = next((v for v in scale_function.body if isinstance(v, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'lst' for t in v.targets)), None)
    require(assignment is not None, 'PROCESSING_LEGACY_SPEC_INVALID')
    chain, node = [], assignment.value
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        require(len(node.args) == 1 and isinstance(node.args[0], ast.Constant), 'PROCESSING_LEGACY_SPEC_INVALID')
        chain.append((node.func.attr, node.args[0].value))
        node = node.func.value
    expected_chain = [('rename','LST'), *reversed(want['lst_operations']), ('select','ST_B10')]
    require(chain == expected_chain, 'PROCESSING_LEGACY_SPEC_INVALID')
    bits = []
    for call in ast.walk(_function(g, '_mask_landsat_clouds')):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == 'bitwiseAnd':
            require(len(call.args) == 1 and isinstance(call.args[0], ast.BinOp), 'PROCESSING_LEGACY_SPEC_INVALID')
            expr = call.args[0]
            require(isinstance(expr.op, ast.LShift) and isinstance(expr.left, ast.Constant) and expr.left.value == 1
                and isinstance(expr.right, ast.Constant) and type(expr.right.value) is int, 'PROCESSING_LEGACY_SPEC_INVALID')
            bits.append(expr.right.value)
    require(sorted(bits) == list(want['lst_mask_bits'])
        and _filters(_function(g, 'get_lst_col'),'CLOUD_COVER') == [want['lst_cloud']]
        and _filters(_function(l, '_compute_lst_monthly'),'CLOUD_COVER') == [want['lst_cloud']], 'PROCESSING_LEGACY_SPEC_INVALID')
    require(_filters(monthly,'CLOUDY_PIXEL_PERCENTAGE') == [want['monthly_cloud']], 'PROCESSING_LEGACY_SPEC_INVALID')
    divide = [c.args[0].value for c in ast.walk(_function(g,'_mask_s2_csplus')) if isinstance(c,ast.Call)
        and isinstance(c.func,ast.Attribute) and c.func.attr=='divide' and len(c.args)==1 and isinstance(c.args[0],ast.Constant)]
    require(divide == [want['reflectance_divisor']], 'PROCESSING_LEGACY_SPEC_INVALID')
    require(_constant(n,'S2_CLOUD_FILTER_PCT') == want['annual_cloud']
        and _constant(n,'S2_CLOUD_FILTER_FALLBACK_PCT') == want['annual_cloud_fallback'], 'PROCESSING_LEGACY_SPEC_INVALID')
    spec = {'ndvi_bands': band_orders[0], 'cs_threshold': score, 'reflectance_divisor': divide[0],
        'annual_cloud': _constant(n,'S2_CLOUD_FILTER_PCT'), 'annual_cloud_fallback': _constant(n,'S2_CLOUD_FILTER_FALLBACK_PCT'),
        'monthly_cloud': _filters(monthly,'CLOUDY_PIXEL_PERCENTAGE')[0],
        'lst_cloud': _filters(_function(g,'get_lst_col'),'CLOUD_COVER')[0],
        'lst_mask_bits': sorted(bits), 'lst_operations': list(reversed(chain))[1:-1]}
    return (spec, defn) if with_definition else spec


class LiveGeeAdapter:
    def compute(self, *_args, **_kwargs):
        # Intentionally fail before importing any legacy module/SDK/config.
        raise ProcessingError('GEE_LIVE_NOT_APPROVED')


class OfflineProcessingAdapter:
    def __init__(self, *, fixture_root=FIXTURE_ROOT, legacy_root=LEGACY_ROOT, boundary_wait=time.sleep):
        self.fixture_root, self.legacy_root = Path(fixture_root), Path(legacy_root)
        self._boundary_wait = boundary_wait

    def compute(self, request):
        check_request(request)
        m = request['manifest']
        path = self.fixture_root / f'processing_{m["metric"]}_{m["scenario"]}.json'
        require(path.is_file() and not path.is_symlink(), 'PROCESSING_FIXTURE_INVALID')
        raw = path.read_bytes()
        require(len(raw) == m['byte_size'] and hashlib.sha256(raw).hexdigest() == m['sha256'], 'PROCESSING_FIXTURE_INVALID')
        fixture = json.loads(raw)
        require(fixture.get('schema_version') == 1 and fixture.get('metric') == m['metric'] and fixture.get('scenario') == m['scenario']
            and fixture.get('synthetic_year_template') is True and fixture.get('spatially_representative') is False,
            'PROCESSING_FIXTURE_INVALID')
        spec, defn = legacy_spec(self.legacy_root, with_definition=True)
        # The request's pinned identity must be that of the definition matched on disk.
        require(m['legacy_pipeline_sha256'] == methods.legacy_identity_map(defn), 'PROCESSING_METHOD_UNREVIEWED')
        if m['scenario'] == 'transient_once' and request['attempt_number'] == 1:
            # Explicit synthetic cloud-boundary scenario: a fixed, bounded wait
            # followed by an outage. No delay/command is accepted in API input.
            # Later attempts still calculate the numeric scenes normally.
            self._boundary_wait(OFFLINE_BOUNDARY_WAIT_SECONDS)
            return report_failure(request, 'TRANSIENT_SYNTHETIC')
        scenes = [s for s in fixture['scenes'] if m['month'] == 0 or s['month'] == m['month']]
        require(len(scenes) <= 24, 'PROCESSING_FIXTURE_INVALID')
        if m['metric'] == 'ndvi':
            limit = spec['annual_cloud'] if m['month'] == 0 else spec['monthly_cloud']
            filtered = [s for s in scenes if s['cloud_pct'] < limit]
            if not filtered and m['month'] == 0:
                filtered = [s for s in scenes if s['cloud_pct'] < spec['annual_cloud_fallback']]
            values = []
            red, nir = spec['ndvi_bands'][1], spec['ndvi_bands'][0]
            for p in range(4):
                clear = [s for s in filtered if s['cs'][p] >= spec['cs_threshold']]
                if not clear:
                    continue
                a, b = (median(s[band][p] / spec['reflectance_divisor'] for s in clear) for band in (nir,red))
                # Earth Engine normalizedDifference masks negative inputs.
                if a < 0 or b < 0 or a + b == 0:
                    continue
                v = (a-b)/(a+b)
                if m['month'] != 0 or v >= 0:
                    values.append(v)
        else:
            filtered = [s for s in scenes if s['cloud_pct'] < spec['lst_cloud']]
            values = []
            for p in range(4):
                clear = [s for s in filtered if not any(s['QA_PIXEL'][p] & (1<<bit) for bit in spec['lst_mask_bits'])]
                if not clear:
                    continue
                scaled = []
                for scene in clear:
                    v = scene['ST_B10'][p]
                    for operation, value in spec['lst_operations']:
                        v = v * value if operation == 'multiply' else v + value if operation == 'add' else v - value
                    scaled.append(v)
                values.append(median(scaled))
        if not values:
            return report_failure(request, 'PROCESSING_NO_VALID_PIXELS')
        require(all(math.isfinite(v) for v in values), 'PROCESSING_NUMERIC_INVALID')
        digits = 4 if m['metric'] == 'ndvi' else 2
        result = report_failure(request, 'PROCESSING_NO_VALID_PIXELS')
        result.update(valid=True, error_code=None, statistics={'valid_pixels': len(values), 'mean': round(mean(values),digits),
            'min': round(min(values),digits), 'max': round(max(values),digits)})
        return result


def validate(request):
    check_request(request)
    try:
        return OfflineProcessingAdapter().compute(request)
    except ProcessingError as error:
        code = str(error)
        # Asset/source drift is an execution failure, not evidence that the
        # selected GIS data are invalid. Reuse the existing bounded retry class.
        if code in {'PROCESSING_LEGACY_SOURCE_CHANGED','PROCESSING_LEGACY_SPEC_INVALID','PROCESSING_FIXTURE_INVALID'}:
            code = 'NATIVE_PROCESS_FAILED'
        return report_failure(request, code)
    except MemoryError:
        return report_failure(request, 'NATIVE_MEMORY_LIMIT')
    except Exception:
        return report_failure(request, 'NATIVE_PROCESS_FAILED')
