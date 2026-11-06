"""GEE Dashboard processing provider (scope 2.1.15, migration 048).

A GIS officer's processing request in mode ``gee_dashboard`` is computed by the SAME
code path the Dashboard uses (routers.ndvi.endpoints / routers.lst): it queries
Google Earth Engine with the backend's own project credentials and writes that path's
own cache row for exactly the requested scope and period. The trend and monthly views
read those rows, so a finished job adds or refreshes one time-series point and never
deletes other periods.

This module is pure: the legacy endpoint calls are injected (``LegacyEndpoints``), so
tests run without Google, Supabase or credentials. Reports carry only summary values
and image metadata; exception text, URLs and credentials are never copied into them.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import re
from uuid import UUID

BUILD = 'gee-dashboard-v1'
MANIFEST_KEYS = {'schema_version', 'provider', 'mode', 'provenance', 'data_kind', 'province', 'district',
    'metric', 'data_year', 'month', 'start_date', 'end_date', 'scale_m', 'processing_version',
    'source_collections', 'cloud_mask', 'cache_table', 'requested_on'}
REQUEST_KEYS = {'processing_id', 'manifest', 'input_hash', 'input_revision', 'attempt_number'}
HASH = re.compile(r'^[0-9a-f]{64}$')
DATE = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
BOUNDS = {'ndvi': (-1.0, 1.0), 'lst': (-60.0, 90.0)}
# Error codes the queue treats as transient (bounded retry), see worker.INFRA.
TRANSIENT = 'NATIVE_PROCESS_FAILED'
NO_DATA = 'PROCESSING_NO_VALID_PIXELS'
IMPLAUSIBLE = 'PROCESSING_RESULT_IMPLAUSIBLE'
MAX_DATA_QUALITY_BYTES = 6000


class DashboardProcessingError(ValueError):
    """Fixed safe code only."""


def cache_table(metric, district, month):
    base = ('ndvi' if metric == 'ndvi' else 'province_lst') if district is None else \
        ('district_ndvi' if metric == 'ndvi' else 'district_lst')
    return base + ('_annual' if month == 0 else '_monthly')


def _require(value):
    if not value:
        raise DashboardProcessingError('PROCESSING_INPUT_INVALID')


def _text(value):
    return isinstance(value, str) and 0 < len(value) <= 120 and not any(ord(c) < 32 for c in value)


def check_request(value):
    """Exact shape of a claimed gee_dashboard job; SQL048 built the manifest."""
    _require(isinstance(value, dict) and set(value) == REQUEST_KEYS)
    try:
        _require(str(UUID(value['processing_id'])) == value['processing_id'])
    except (ValueError, TypeError, AttributeError):
        raise DashboardProcessingError('PROCESSING_INPUT_INVALID') from None
    m = value['manifest']
    _require(isinstance(m, dict) and set(m) == MANIFEST_KEYS)
    _require(type(m['schema_version']) is int and m['schema_version'] == 9 and m['provider'] == 'gee_dashboard'
        and m['mode'] == 'gee_dashboard' and m['provenance'] == 'gis-processing-gee-dashboard-v1'
        and m['data_kind'] == 'summary' and m['processing_version'] == BUILD)
    _require(m['metric'] in ('ndvi', 'lst') and _text(m['province']) and (m['district'] is None or _text(m['district'])))
    _require(type(m['data_year']) is int and 2013 <= m['data_year'] <= 2200)
    _require(type(m['month']) is int and 0 <= m['month'] <= 12)
    _require(m['cache_table'] == cache_table(m['metric'], m['district'], m['month']))
    _require(isinstance(m['requested_on'], str) and DATE.fullmatch(m['requested_on']))
    _require(isinstance(value['input_hash'], str) and HASH.fullmatch(value['input_hash'])
        and type(value['input_revision']) is int and value['input_revision'] == 1
        and type(value['attempt_number']) is int and 1 <= value['attempt_number'] <= 3)
    return value


def _report(request, *, valid, error_code, stats, observation, cache):
    return {'schema_version': 1, 'provider_build': BUILD, 'mode': 'gee_dashboard', 'synthetic': False,
        'processing_id': request['processing_id'], 'input_hash': request['input_hash'],
        'input_revision': request['input_revision'], 'valid': valid, 'error_code': error_code,
        'statistics': {'valid_pixels': None, **stats}, 'metadata': deepcopy(request['manifest']),
        'observation': observation, 'cache': cache}


def report_failure(request, code):
    check_request(request)
    if not (isinstance(code, str) and re.fullmatch('[A-Z][A-Z0-9_]{0,59}', code)):
        code = TRANSIENT
    return _report(request, valid=False, error_code=code,
        stats={'mean': None, 'min': None, 'max': None}, observation=None, cache=None)


def _number(value):
    return type(value) in (int, float) and not isinstance(value, bool) and math.isfinite(value)


def _compact_quality(value):
    if not isinstance(value, dict):
        return None
    try:
        raw = json.dumps(value, allow_nan=False, sort_keys=True, separators=(',', ':'), default=str)
    except (TypeError, ValueError):
        return None
    return json.loads(raw) if len(raw.encode()) <= MAX_DATA_QUALITY_BYTES else None


class NoData(Exception):
    """The Dashboard path found no usable imagery for this scope/period (HTTP 404)."""


class LegacyEndpoints:
    """Binds the real Dashboard endpoint functions. Imported only inside the host worker.

    Each call returns the endpoint's own response dict and, as a side effect of that
    unchanged code, inserts or keeps the matching cache row for the requested period.
    """
    def __init__(self):
        from fastapi import HTTPException
        from routers.ndvi import endpoints as ndvi
        from routers import lst
        self.http_error = HTTPException
        self.calls = {
            ('ndvi', False, False): lambda p, d, y: ndvi.get_ndvi(p, year=y),
            ('ndvi', False, True): lambda p, d, y: ndvi.get_ndvi_monthly(p, year=y),
            ('ndvi', True, False): lambda p, d, y: ndvi.get_district_ndvi(p, d, year=y),
            ('ndvi', True, True): lambda p, d, y: ndvi.get_district_ndvi_monthly(p, d, year=y),
            ('lst', False, False): lambda p, d, y: lst.get_lst(p, year=y),
            ('lst', False, True): lambda p, d, y: lst.get_lst_monthly(p, year=y),
            ('lst', True, False): lambda p, d, y: lst.get_district_lst(p, d, year=y),
            ('lst', True, True): lambda p, d, y: lst.get_district_lst_monthly(p, d, year=y),
        }

    def __call__(self, metric, province, district, year, monthly):
        try:
            return self.calls[(metric, district is not None, monthly)](province, district, year)
        except self.http_error as error:
            if getattr(error, 'status_code', None) == 404:
                raise NoData() from None
            raise


def compute(request, endpoints):
    """Run one claimed job through ``endpoints(metric, province, district, year, monthly)``."""
    check_request(request)
    m = request['manifest']
    metric, month = m['metric'], m['month']
    try:
        response = endpoints(metric, m['province'], m['district'], m['data_year'], month != 0)
    except NoData:
        return report_failure(request, NO_DATA)
    except Exception:
        # Upstream messages may contain URLs/project names; keep only a fixed code.
        return report_failure(request, TRANSIENT)
    if not isinstance(response, dict):
        return report_failure(request, TRANSIENT)
    lo, hi = BOUNDS[metric]
    from_cache = response.get('from_cache') is True
    cached_at = response.get('cached_at') if isinstance(response.get('cached_at'), str) else None
    if month == 0:
        key = 'ndvi' if metric == 'ndvi' else 'lst'
        mean, low, high = (response.get(f'{key}_{s}') for s in ('mean', 'min', 'max'))
        if not all(_number(v) for v in (mean, low, high)):
            return report_failure(request, NO_DATA)
        if not (lo <= low <= mean <= high <= hi):
            return report_failure(request, IMPLAUSIBLE)
        stats = {'mean': mean, 'min': low, 'max': high}
        observation = {'from_cache': from_cache, 'cached_at': cached_at, 'image_count': None,
            'data_quality': _compact_quality(response.get('data_quality'))}
    else:
        rows = response.get('monthly')
        row = next((r for r in rows if isinstance(r, dict) and r.get('month_num') == month), None) \
            if isinstance(rows, list) else None
        if row is None:
            return report_failure(request, TRANSIENT)
        value, count = row.get('ndvi' if metric == 'ndvi' else 'lst'), row.get('image_count')
        if not _number(value) or type(count) is not int or count <= 0:
            return report_failure(request, NO_DATA)
        if not lo <= value <= hi or count > 999999:
            return report_failure(request, IMPLAUSIBLE)
        stats = {'mean': value, 'min': None, 'max': None}
        observation = {'from_cache': from_cache, 'cached_at': cached_at, 'image_count': count, 'data_quality': None}
    cache = {'table': m['cache_table'], 'province': m['province'], 'district': m['district'],
        'year': m['data_year'], 'month': month, 'written': True}
    report = _report(request, valid=True, error_code=None, stats=stats, observation=observation, cache=cache)
    if len(json.dumps(report, allow_nan=False).encode()) > 16000:
        report['observation']['data_quality'] = None
    return report
