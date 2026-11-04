"""A6.1 mock bridge and scientific specification checks, never live parity."""
from copy import deepcopy
from datetime import date
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from gis_worker.gee_adapter import (AdapterError, ComputeFailure, LegacyBindings,
                                    LegacyReturn, SafeComputeAdapter)
from gis_worker.gee_contracts import Observation, Statistics, digest, method_for
from tests.test_gee_contracts import GEOMETRY, request


def observation(req, *, mean=None, min=None, max=None, valid_pixels=2, scenes=True, complete=True):
    method = method_for(req.product, req.period.month)
    if mean is None and valid_pixels:
        mean, min, max = (0.4921, 0.4286, 0.5556) if req.product == 'ndvi' else (29.66, 22.82, 36.5)
    return Observation(request_hash=req.request_hash(), geometry_sha256=req.boundary.geometry_sha256,
        product=req.product, method_version=req.method_version, period=req.period,
        collections=method.collections, scenes=({'collection': method.collections[0],
            'image_id': method.collections[0] + '/MOCK_SCENE_1', 'acquired': req.period.start},) if scenes else (),
        observations_complete=complete, valid_pixels=valid_pixels,
        raw_statistics=Statistics(mean=mean, min=min, max=max))


def returned(req, observed=None):
    obs = observed or observation(req)
    s = obs.raw_statistics
    digits = 4 if req.product == 'ndvi' else 2
    values = tuple(round(v, digits) if v is not None else 0 for v in (s.mean, s.min, s.max))
    if req.period.month:
        payload = [{'month_num': n, 'image_count': len(obs.scenes) if n == req.period.month else 0,
                    req.product: values[0] if n == req.period.month else None} for n in range(1, 13)]
    elif req.product == 'ndvi':
        payload = dict(zip(('ndvi_mean', 'ndvi_min', 'ndvi_max'), values))
    else:
        payload = values
    return LegacyReturn(payload, obs)


def adapter(req, result=None, *, helper=None, as_of=date(2026, 1, 1)):
    def injected(geometry, year, scale):
        assert geometry == GEOMETRY and year == req.period.year and scale == 500
        return result or returned(req)
    functions = {f'{p}_{f}': (helper or injected) if (p == req.product and f == ('monthly' if req.period.month else 'annual'))
                 else lambda *_: pytest.fail('Wrong scientific helper selected')
                 for p in ('ndvi', 'lst') for f in ('annual', 'monthly')}
    return SafeComputeAdapter(LegacyBindings(**functions), as_of=as_of)


def compute(req, **kwargs):
    return adapter(req, **kwargs).compute(req, GEOMETRY, expected_request_hash=req.request_hash())


@pytest.mark.parametrize('product', ['ndvi', 'lst'])
@pytest.mark.parametrize('month', range(13))
def test_summary_bridge_routes_all_periods_and_content_addresses_candidate(product, month):
    req = request(product, month)
    out = compute(req)
    assert out.content.status == 'candidate'
    assert out.content.execution == 'mock' and out.content.synthetic and not out.content.publishable
    assert out.content.endpoint_parity == 'summary_only'
    assert out.output_sha256 == digest(out.content.model_dump(mode='json')) != req.request_hash()
    assert out.candidate_identity.startswith('gee-candidate-v1:')
    assert out.content.method.units == ('unitless' if product == 'ndvi' else 'celsius')
    assert (out.content.statistics.min is None) == bool(month)


@pytest.mark.parametrize('scenes', [False, True])
def test_legacy_zero_coercion_does_not_convert_no_data_to_success(scenes):
    req = request()
    obs = observation(req, valid_pixels=0, scenes=scenes)
    out = compute(req, result=returned(req, obs))
    assert out.content.status == 'no_data' and out.candidate_identity is None
    assert out.content.statistics == Statistics()


def test_real_zero_is_preserved_when_valid_observations_exist():
    req = request()
    obs = observation(req).model_copy(update={'raw_statistics': Statistics(mean=0.0, min=0.0, max=0.0)})
    out = compute(req, result=returned(req, obs))
    assert out.content.status == 'candidate' and out.content.statistics.mean == 0.0


def test_unknown_pixel_count_is_not_invented():
    req = request(month=1)
    obs = observation(req).model_copy(update={'valid_pixels': None})
    out = compute(req, result=returned(req, obs))
    assert out.content.status == 'candidate' and out.content.observation.valid_pixels is None


def test_empty_scenes_with_positive_pixel_count_are_incomplete_not_no_data():
    req = request()
    obs = observation(req, scenes=False).model_copy(update={'raw_statistics': Statistics()})
    out = compute(req, result=returned(req, obs))
    assert out.content.status == 'incomplete'


def test_mutating_bridge_cannot_change_caller_geometry_or_accepted_scope():
    req = request()
    original = deepcopy(GEOMETRY)
    def mutate(geometry, *_):
        geometry['coordinates'][0][1][0] = 100.5
        return returned(req)
    with pytest.raises(AdapterError, match='GEE_OBSERVATION_IDENTITY_MISMATCH'):
        compute(req, helper=mutate)
    assert GEOMETRY == original


@pytest.mark.parametrize('change', ['missing_mean', 'missing_extrema', 'unknown_completeness', 'open_period', 'zero_pixels'])
def test_incomplete_never_becomes_candidate(change):
    req = request()
    obs = observation(req)
    as_of = date(2026, 1, 1)
    if change == 'missing_mean':
        obs = obs.model_copy(update={'raw_statistics': Statistics()})
    elif change == 'missing_extrema':
        obs = obs.model_copy(update={'raw_statistics': Statistics(mean=0.5)})
    elif change == 'unknown_completeness':
        obs = obs.model_copy(update={'observations_complete': False})
    elif change == 'open_period':
        as_of = date(2025, 6, 1)
    else:
        obs = obs.model_copy(update={'valid_pixels': 0})
    out = compute(req, result=returned(req, obs), as_of=as_of)
    assert out.content.status == 'incomplete' and out.content.statistics.mean is None


@pytest.mark.parametrize('field,value', [('request_hash', '0' * 64), ('geometry_sha256', '0' * 64),
    ('product', 'lst'), ('method_version', 'lst-annual-legacy-v1'), ('collections', ('OTHER',)),
    ('period', request(month=1).period)])
def test_observation_scope_product_method_and_period_mismatches_are_rejected(field, value):
    req = request()
    obs = observation(req).model_copy(update={field: value})
    with pytest.raises(AdapterError, match='GEE_OBSERVATION_IDENTITY_MISMATCH'):
        compute(req, result=returned(req, obs))


def test_geometry_and_hash_mismatch_precede_compute_and_preserve_input():
    req = request()
    calls = []
    a = adapter(req, helper=lambda *_: calls.append(True))
    with pytest.raises(AdapterError, match='GEE_REQUEST_IDENTITY_MISMATCH'):
        a.compute(req, GEOMETRY, expected_request_hash='0' * 64)
    wrong = deepcopy(GEOMETRY)
    wrong['coordinates'][0][1][0] = 100.5
    with pytest.raises(AdapterError, match='GEE_REQUEST_IDENTITY_MISMATCH'):
        a.compute(req, wrong, expected_request_hash=req.request_hash())
    assert not calls


@pytest.mark.parametrize('error,code', [(ComputeFailure(transient=True), 'GEE_TRANSIENT'),
    (ComputeFailure(), 'GEE_REJECTED'), (RuntimeError('PRIVATE_DIAGNOSTICS_MUST_NOT_LEAK'), 'COMPUTE_FAILED')])
def test_errors_are_safe_without_cache_or_storage_dependencies(error, code):
    req = request()
    def fail(*_):
        raise error
    out = compute(req, helper=fail)
    assert out.content.status == 'failed' and out.content.error_code == code
    assert out.content.observation is None and out.candidate_identity is None
    assert 'PRIVATE_DIAGNOSTICS' not in out.model_dump_json()


def test_summary_without_raw_observation_bridge_fails_closed():
    with pytest.raises(AdapterError, match='GEE_OBSERVATION_IDENTITY_MISMATCH'):
        compute(request(), helper=lambda *_: {'ndvi_mean': 0, 'ndvi_min': 0, 'ndvi_max': 0})


@pytest.mark.parametrize('month', [0, 2])
def test_changed_legacy_summary_rejected(month):
    req = request(month=month)
    value = returned(req)
    if month:
        value.payload[month - 1]['ndvi'] = 0.9
    else:
        value.payload['ndvi_mean'] = 0.9
    with pytest.raises(AdapterError, match='GEE_LEGACY_SUMMARY_MISMATCH'):
        compute(req, result=value)


def test_live_execution_stays_blocked_before_any_callback():
    with pytest.raises(AdapterError, match='GEE_LIVE_NOT_APPROVED'):
        SafeComputeAdapter(None, as_of=date(2026, 1, 1), execution='live')


@pytest.mark.parametrize('change', ['province', 'boundary_version', 'revision', 'method', 'period',
    'statistics', 'negative_annual', 'duplicate_scene', 'scene_date', 'scene_collection',
    'incomplete_as_candidate', 'null_unknown_as_nodata', 'nodata_incomplete_support'])
def test_rehashed_transport_cannot_forge_semantic_consistency(change):
    from pydantic import ValidationError
    from gis_worker.gee_contracts import ComputeOutput
    req = request()
    data = compute(req).model_dump(mode='json')
    c = data['content']
    if change == 'province': c['boundary']['province'] = 'Other Province'
    elif change == 'boundary_version': c['boundary']['boundary_version'] = 'v2'
    elif change == 'revision': c['input_revision'] = 2
    elif change == 'method': c['method']['scene_cloud_lt'] = 80
    elif change == 'period': c['period'] = request(month=1).period.model_dump(mode='json')
    elif change == 'statistics': c['statistics']['mean'] = 0.5
    elif change == 'negative_annual': c['observation']['raw_statistics'] = {'mean': -0.5, 'min': -0.5, 'max': -0.5}
    elif change == 'duplicate_scene': c['observation']['scenes'] *= 2
    elif change == 'scene_date': c['observation']['scenes'][0]['acquired'] = '2024-01-01'
    elif change == 'scene_collection':
        c['observation']['scenes'][0].update(collection='OTHER', image_id='OTHER/SCENE')
    elif change == 'incomplete_as_candidate': c['observation']['observations_complete'] = False
    else:
        c.update(status='no_data', error_code='NO_VALID_PIXELS', statistics={'mean': None, 'min': None, 'max': None})
        c['observation']['raw_statistics'] = {'mean': None, 'min': None, 'max': None}
        c['observation']['valid_pixels'] = None if change == 'null_unknown_as_nodata' else 0
        if change == 'nodata_incomplete_support': c['observation']['observations_complete'] = False
    data['output_sha256'] = digest(c)
    with pytest.raises(ValidationError):
        ComputeOutput.model_validate(data)


def test_method_parameters_match_actual_legacy_ast_without_importing_startup(tmp_path):
    from gis_worker.processing_provider import legacy_spec, LEGACY_SHA
    root = Path(__file__).resolve().parents[1]
    for target, source in [('gee_utils.py', 'gee_utils.py'), ('ndvi_compute.py', 'routers/ndvi/compute.py'), ('lst.py', 'routers/lst.py')]:
        (tmp_path / target).write_bytes((root / source).read_bytes())
    spec = legacy_spec(tmp_path)
    annual, monthly, lst = method_for('ndvi', 0), method_for('ndvi', 1), method_for('lst', 0)
    assert annual.bands[:2] == tuple(spec['ndvi_bands'])
    assert annual.clear_score_gte == monthly.clear_score_gte == spec['cs_threshold']
    assert annual.reflectance_divisor == spec['reflectance_divisor']
    assert annual.scene_cloud_lt == spec['annual_cloud']
    assert annual.fallback_cloud_lt == spec['annual_cloud_fallback']
    assert monthly.scene_cloud_lt == spec['monthly_cloud'] and monthly.fallback_cloud_lt is None
    assert annual.mask_negative_ndvi and not monthly.mask_negative_ndvi
    assert lst.qa_mask_bits == tuple(spec['lst_mask_bits']) and lst.scene_cloud_lt == spec['lst_cloud']
    assert [v for _, v in spec['lst_operations']] == [lst.st_multiplier, lst.st_offset_kelvin, lst.celsius_subtract]


def test_actual_legacy_lst_scale_runs_on_injected_image_without_sdk_or_network(monkeypatch):
    # Execute the unmodified safe utility with an inert ee module; never import
    # main/dependencies or initialize an SDK. Arithmetic is the actual old code.
    monkeypatch.setitem(sys.modules, 'ee', ModuleType('ee'))
    path = Path(__file__).resolve().parents[1] / 'gee_utils.py'
    spec = importlib.util.spec_from_file_location('a61_inert_gee_utils', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    class Image:
        def __init__(self, value, valid=True): self.value, self.valid = value, valid
        def select(self, name): return Image(0 if name == 'QA_PIXEL' else self.value, self.valid)
        def bitwiseAnd(self, x): return Image(int(self.value) & x)
        def eq(self, x): return Image(self.value == x)
        def And(self, x): return Image(self.value and x.value)
        def updateMask(self, x): return Image(self.value, x.value)
        def multiply(self, x): return Image(self.value * x, self.valid)
        def add(self, x): return Image(self.value + x, self.valid)
        def subtract(self, x): return Image(self.value - x, self.valid)
        def rename(self, _): return self
        def addBands(self, x): return x
    assert module.scale_lst(Image(45000)).value == pytest.approx(29.6609)


def test_fresh_import_blocks_sdk_startup_network_environment_and_writes():
    root = Path(__file__).resolve().parents[1]
    code = r'''
import sys, builtins, importlib.abc, os, socket
sys.path.insert(0, sys.argv[1])
import pydantic
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self, name, *args):
  if name.split('.')[0] in ('ee','dotenv','supabase','dependencies','main','routers','requests','httpx','google'):
   raise AssertionError('Forbidden import: ' + name)
sys.meta_path.insert(0,Deny())
def deny(*args, **kwargs): raise AssertionError('Forbidden startup operation')
builtins.open=deny
# Pydantic asks for its plugin switch while building every model. Return a
# fixed disable value; no ambient config or application credentials are read.
os.getenv=lambda key, default=None: '__all__' if key=='PYDANTIC_DISABLE_PLUGINS' else deny()
socket.socket=deny
import gis_worker.gee_contracts, gis_worker.gee_adapter
assert not any(n in sys.modules for n in ('ee','dotenv','supabase','dependencies','main'))
print('IMPORT_ISOLATION_PASS')
'''
    # Winsock/Python's Windows runtime needs SYSTEMROOT; no application env is inherited.
    done = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(root)],
                          capture_output=True, text=True, timeout=20,
                          env={'SYSTEMROOT': os.environ.get('SYSTEMROOT', r'C:\Windows')})
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == 'IMPORT_ISOLATION_PASS'
