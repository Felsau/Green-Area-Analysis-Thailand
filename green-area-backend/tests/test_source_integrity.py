"""Source-text hash scheme (LF/CRLF) and approved method definitions.

Pure local checks: no SDK, network, credentials or database.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
from types import MappingProxyType

import pytest

from gis_worker import method_registry as methods
from gis_worker import processing_provider as p
from gis_worker import provider
from gis_worker import source_integrity as si
from gis_worker.gee_contracts import METHODS, method_for

BACKEND = Path(__file__).resolve().parents[1]
LEGACY = {'gee_utils.py': 'gee_utils.py', 'ndvi_compute.py': 'routers/ndvi/compute.py', 'lst.py': 'routers/lst.py'}


def lf(raw):
    return raw.replace(b'\r\n', b'\n')


def crlf(raw):
    return lf(raw).replace(b'\n', b'\r\n')


def legacy_dir(tmp_path, convert=lambda raw: raw, edit=None):
    for target, source in LEGACY.items():
        raw = convert((BACKEND / source).read_bytes())
        if edit and target in edit:
            raw = edit[target](raw)
        (tmp_path / target).write_bytes(raw)
    return tmp_path


def request(metric='ndvi'):
    from tests.test_processing_provider import request as make
    return make(metric=metric)


# ---- 1. scheme -------------------------------------------------------------

def test_same_text_lf_and_crlf_has_one_canonical_hash_but_two_raw_hashes():
    text = b'x = 1\nif x:\n    y = "a"\n'
    assert si.source_text_sha256(text) == si.source_text_sha256(crlf(text)) == hashlib.sha256(text).hexdigest()
    assert si.raw_sha256(text) != si.raw_sha256(crlf(text))
    assert si.legacy_crlf_sha256(text) == si.legacy_crlf_sha256(crlf(text)) == hashlib.sha256(crlf(text)).hexdigest()


@pytest.mark.parametrize('change', [
    lambda t: t.replace(b'= 1', b'= 2'),          # constant
    lambda t: t.replace(b'if x', b'if not x'),    # logic
    lambda t: t.replace(b'    y', b'     y'),     # whitespace is NOT normalised
    lambda t: t + b'# comment\n',                 # comments are NOT ignored
    lambda t: b'\xef\xbb\xbf' + t,                # BOM is NOT stripped
    lambda t: t.rstrip(b'\n'),                    # final newline counts
])
def test_any_real_text_change_still_changes_the_canonical_hash(change):
    text = b'x = 1\nif x:\n    y = "a"\n'
    assert si.source_text_sha256(change(text)) != si.source_text_sha256(text)
    assert si.source_text_sha256(crlf(change(text))) != si.source_text_sha256(text)


@pytest.mark.parametrize('raw', [b'a\rb\n', b'a\r', b'a\x00\n', b'\xff\xfe\n', 'é'.encode('latin-1')])
def test_lone_cr_nul_or_non_utf8_is_rejected_not_normalised(raw):
    with pytest.raises(si.SourceIntegrityError, match='SOURCE_TEXT_INVALID'):
        si.source_text_sha256(raw)
    assert si.verify(raw, si.raw_sha256(raw), si.SOURCE_TEXT_SCHEME) is False


def test_declared_scheme_is_exact_no_fallback_between_schemes():
    text = b'a\r\nb\r\n'
    assert si.verify(text, si.raw_sha256(text), si.RAW_BYTES_SCHEME)
    assert not si.verify(text, si.raw_sha256(text), si.SOURCE_TEXT_SCHEME)
    assert not si.verify(text, si.source_text_sha256(text), si.RAW_BYTES_SCHEME)
    with pytest.raises(si.SourceIntegrityError, match='HASH_SCHEME_UNKNOWN'):
        si.digest(text, 'sha256')


@pytest.mark.parametrize('name', ['ldd_valid.zip', 'ndvi_ready.tif'])
def test_raw_artifacts_reject_a_single_changed_byte_and_are_never_line_normalised(name):
    raw = (BACKEND / 'gis_worker/fixtures' / name).read_bytes()
    digest = si.raw_sha256(raw)
    for index in (0, len(raw) // 2, len(raw) - 1):
        changed = bytearray(raw)
        changed[index] ^= 1
        assert not si.verify(bytes(changed), digest, si.RAW_BYTES_SCHEME)
    if b'\n' in raw:
        assert not si.verify(raw.replace(b'\n', b'\r\n'), digest, si.RAW_BYTES_SCHEME)


# ---- 1b. legacy sources and the T3 registry on both checkouts ---------------

@pytest.mark.parametrize('convert', [lf, crlf], ids=['lf', 'crlf'])
def test_legacy_spec_and_numeric_results_identical_on_lf_and_crlf_checkouts(tmp_path, convert):
    root = legacy_dir(tmp_path, convert)
    spec, defn = p.legacy_spec(root, with_definition=True)
    assert defn is methods.LEGACY_V1
    assert spec == {'ndvi_bands': ['B8', 'B4'], 'cs_threshold': 0.6, 'reflectance_divisor': 10000,
                    'annual_cloud': 20, 'annual_cloud_fallback': 80, 'monthly_cloud': 80, 'lst_cloud': 40,
                    'lst_mask_bits': [3, 4],
                    'lst_operations': [('multiply', 0.00341802), ('add', 149.0), ('subtract', 273.15)]}
    result = p.OfflineProcessingAdapter(legacy_root=root).compute(request())
    assert result['valid'] and result['statistics'] == {'valid_pixels': 2, 'mean': 0.4921, 'min': 0.4286, 'max': 0.5556}


@pytest.mark.parametrize('convert', [lf, crlf], ids=['lf', 'crlf'])
@pytest.mark.parametrize('target,old,new', [
    ('gee_utils.py', b'0.00341802', b'0.00341803'),          # LST scale
    ('gee_utils.py', b'149.0', b'150.0'),                    # LST offset
    ('ndvi_compute.py', b"'B8', 'B4'", b"'B4', 'B8'"),       # NDVI band order
    ('lst.py', b'40', b'41'),                                # cloud filter
])
def test_formula_or_constant_change_is_rejected_on_both_checkouts(tmp_path, convert, target, old, new):
    source = (BACKEND / LEGACY[target]).read_bytes()
    assert old in source, 'test precondition: reviewed text contains the value'
    root = legacy_dir(tmp_path, convert, {target: lambda raw: raw.replace(old, new, 1)})
    with pytest.raises(p.ProcessingError, match='PROCESSING_LEGACY_SOURCE_CHANGED'):
        p.legacy_spec(root)


def test_mixed_or_lone_cr_legacy_file_is_rejected(tmp_path):
    root = legacy_dir(tmp_path, edit={'lst.py': lambda raw: lf(raw).replace(b'\n', b'\r', 3)})
    with pytest.raises(p.ProcessingError, match='PROCESSING_LEGACY_SOURCE_CHANGED'):
        p.legacy_spec(root)


@pytest.mark.parametrize('convert', [lf, crlf], ids=['lf', 'crlf'])
def test_t3_registry_text_verifies_on_both_checkouts_and_rejects_changes(tmp_path, monkeypatch, convert):
    root = provider.ROOT
    (tmp_path / 'registry.json').write_bytes(convert((root / 'registry.json').read_bytes()))
    (tmp_path / 'poc_validation.py').write_bytes(convert((root / 'poc_validation.py').read_bytes()))
    shutil.copytree(root / 'fixtures', tmp_path / 'fixtures')
    monkeypatch.setattr(provider, 'ROOT', tmp_path)
    assert provider.load_registry()['provider_build'] == provider.PROVIDER_BUILD
    raw = (tmp_path / 'registry.json').read_bytes()
    (tmp_path / 'registry.json').write_bytes(raw.replace(b'"synthetic_only": true', b'"synthetic_only": false'))
    with pytest.raises(provider.ProviderError, match='REGISTRY_INTEGRITY'):
        provider.load_registry()


def test_pinned_v0_registry_and_legacy_values_are_unchanged_and_bound_to_the_reviewed_text():
    # The historical values are not edited to make tests pass; they are derived.
    assert provider.REGISTRY_LEGACY_CRLF_SHA256 == 'a03a1fade69c0ca4df8d7ac7ad63c3b3c6af31444ef65f5773e5de7f56715cb9'
    raw = (provider.ROOT / 'registry.json').read_bytes()
    assert si.legacy_crlf_sha256(raw) == provider.REGISTRY_LEGACY_CRLF_SHA256
    assert si.source_text_sha256(raw) == provider.REGISTRY_SHA256
    assert p.LEGACY_SHA == {'gee_utils.py': 'd1f25fdca1c0562379d5f98002e9bea0a3c94d36f71df6bea45ec6bf94a9a175',
                            'ndvi_compute.py': '87b22a35e9dd610e6359f375de5dd9cfebd666bdcee28a22363179155b1febcd',
                            'lst.py': '748dcc2d6cc33108bdb7f07effadc2bcbb202e6436703fec68d7d0017004176f'}
    for path, legacy in methods.LEGACY_V1.legacy_identity:
        raw = (BACKEND / path).read_bytes()
        assert si.legacy_crlf_sha256(raw) == legacy
        assert si.source_text_sha256(raw) == dict(methods.LEGACY_V1.approved_sources)[path]


def test_applied_migrations_still_pin_the_unchanged_v0_identity():
    sql035 = (BACKEND / 'migrations/035_gis_processing_offline.sql').read_text(encoding='utf-8')
    sql044 = (BACKEND / 'migrations/044_gis_live_foundation.sql').read_text(encoding='utf-8')
    for _, legacy in methods.LEGACY_V1.legacy_identity:
        assert legacy in sql035 and legacy in sql044


# ---- 2. approved method definitions -----------------------------------------

def test_approved_legacy_definition_matches_the_contract_and_still_passes():
    defn = methods.definition('legacy-v1')
    assert METHODS == defn.method_versions
    for version in METHODS:
        assert methods.definition_for_version(version) is defn
    annual, monthly, lst = method_for('ndvi', 0), method_for('ndvi', 1), method_for('lst', 0)
    assert annual.collections == defn.collections['ndvi'] and lst.collections == defn.collections['lst']
    assert annual.bands == defn.bands['ndvi'] and lst.bands == defn.bands['lst']
    assert annual.units == defn.units['ndvi'] and lst.units == defn.units['lst']
    assert annual.clear_score_gte == defn.masks['ndvi_clear_score_gte']
    assert annual.scene_cloud_lt == defn.masks['ndvi_annual_scene_cloud_lt']
    assert annual.fallback_cloud_lt == defn.masks['ndvi_annual_fallback_cloud_lt']
    assert monthly.scene_cloud_lt == defn.masks['ndvi_monthly_scene_cloud_lt']
    assert lst.scene_cloud_lt == defn.masks['lst_scene_cloud_lt'] and lst.qa_mask_bits == defn.masks['lst_qa_mask_bits']
    assert annual.reflectance_divisor == defn.scale_offset['ndvi_reflectance_divisor']
    assert (lst.st_multiplier, lst.st_offset_kelvin, lst.celsius_subtract) == (
        defn.scale_offset['lst_st_multiplier'], defn.scale_offset['lst_st_offset_kelvin'],
        defn.scale_offset['lst_celsius_subtract'])
    assert annual.composite == defn.reducers['ndvi'] and lst.composite == defn.reducers['lst']
    assert annual.legacy_sources == defn.legacy_identity
    assert defn.source_hash_scheme == si.SOURCE_TEXT_SCHEME and defn.review_reference


@pytest.mark.parametrize('value', ['legacy-v2', 'ndvi-annual-legacy-v2', '', None, 'LEGACY-V1'])
def test_unknown_method_fails_closed(value):
    with pytest.raises(methods.MethodError, match='PROCESSING_METHOD_UNREVIEWED'):
        methods.definition(value)
    with pytest.raises(methods.MethodError, match='PROCESSING_METHOD_UNREVIEWED'):
        methods.definition_for_version(value)


def test_unreviewed_definition_fails_closed(monkeypatch):
    draft = replace(methods.LEGACY_V1, method_id='legacy-v2', status='draft',
                    method_versions=('ndvi-annual-legacy-v2',))
    monkeypatch.setattr(methods, 'APPROVED', MappingProxyType({**methods.APPROVED, 'legacy-v2': draft}))
    with pytest.raises(methods.MethodError, match='PROCESSING_METHOD_UNREVIEWED'):
        methods.definition('legacy-v2')


def _v2(tmp_path, monkeypatch, *, approve=True):
    """A hypothetical reviewed v2: the Dashboard changed one constant."""
    edit = {'gee_utils.py': lambda raw: raw.replace(b'0.00341802', b'0.00341801', 1)}
    root = legacy_dir(tmp_path, edit=edit)
    sources = {path: (root / name).read_bytes() for path, name in methods.LEGACY_FILE_NAMES.items()}
    v2 = replace(methods.LEGACY_V1, method_id='legacy-v2',
                 method_versions=tuple(v.replace('-v1', '-v2') for v in methods.LEGACY_V1.method_versions),
                 approved_sources=tuple((k, si.source_text_sha256(sources[k])) for k, _ in methods.LEGACY_V1.approved_sources),
                 legacy_identity=tuple((k, si.legacy_crlf_sha256(sources[k])) for k, _ in methods.LEGACY_V1.legacy_identity),
                 scale_offset=MappingProxyType({**methods.LEGACY_V1.scale_offset, 'lst_st_multiplier': 0.00341801}),
                 scientific_expected=MappingProxyType({**methods.LEGACY_V1.scientific_expected,
                     'lst_operations': (('multiply', 0.00341801), ('add', 149.0), ('subtract', 273.15))}),
                 review_reference='test-only', status='approved' if approve else 'draft')
    approved = {**methods.APPROVED, 'legacy-v2': v2} if approve else dict(methods.APPROVED)
    monkeypatch.setattr(methods, 'APPROVED', MappingProxyType(approved))
    return root, v2


def test_changed_source_without_a_new_reviewed_definition_is_rejected(tmp_path, monkeypatch):
    root, _ = _v2(tmp_path, monkeypatch, approve=False)
    with pytest.raises(p.ProcessingError, match='PROCESSING_LEGACY_SOURCE_CHANGED'):
        p.legacy_spec(root)


def test_new_definition_does_not_change_old_results_or_relabel_old_requests(tmp_path, monkeypatch):
    (tmp_path / 'v1').mkdir()
    (tmp_path / 'v2').mkdir()
    old_root = legacy_dir(tmp_path / 'v1')
    before = p.OfflineProcessingAdapter(legacy_root=old_root).compute(request('lst'))
    new_root, v2 = _v2(tmp_path / 'v2', monkeypatch)
    # v1 sources still resolve to v1 only, with identical results and identity.
    spec, defn = p.legacy_spec(old_root, with_definition=True)
    assert defn.method_id == 'legacy-v1'
    assert p.OfflineProcessingAdapter(legacy_root=old_root).compute(request('lst')) == before
    assert methods.legacy_identity_map(methods.LEGACY_V1) == p.LEGACY_SHA
    # v2 sources are a different, explicitly reviewed method ...
    assert p.legacy_spec(new_root, with_definition=True)[1].method_id == 'legacy-v2'
    # ... and an old (v1-pinned) request is never computed under v2.
    with pytest.raises(p.ProcessingError, match='PROCESSING_METHOD_UNREVIEWED'):
        p.OfflineProcessingAdapter(legacy_root=new_root).compute(request('lst'))


def test_two_definitions_claiming_the_same_sources_is_ambiguous_and_fails_closed(tmp_path, monkeypatch):
    twin = replace(methods.LEGACY_V1, method_id='legacy-twin', method_versions=('x-twin',))
    monkeypatch.setattr(methods, 'APPROVED', MappingProxyType({**methods.APPROVED, 'legacy-twin': twin}))
    with pytest.raises(p.ProcessingError, match='PROCESSING_LEGACY_SOURCE_CHANGED'):
        p.legacy_spec(legacy_dir(tmp_path))


@pytest.mark.parametrize('field', ['legacy_pipeline_sha256', 'processing_version'])
def test_approved_hashes_or_method_cannot_come_from_the_payload(field):
    value = request()
    value['manifest'][field] = {'gee_utils.py': '0' * 64} if field == 'legacy_pipeline_sha256' else 'legacy-v2'
    with pytest.raises(p.ProcessingError):
        p.check_request(value)
    for extra in ('approved_sources', 'method_definition', 'source_hash_scheme'):
        value = request()
        value['manifest'][extra] = 'payload'
        with pytest.raises(p.ProcessingError):
            p.check_request(value)


def test_definitions_are_immutable():
    with pytest.raises((AttributeError, TypeError)):
        methods.LEGACY_V1.approved_sources = ()
    with pytest.raises(TypeError):
        methods.APPROVED['legacy-v9'] = methods.LEGACY_V1
    with pytest.raises(TypeError):
        methods.LEGACY_V1.masks['lst_scene_cloud_lt'] = 99
    assert json.dumps(dict(methods.LEGACY_V1.scientific_expected), sort_keys=True)
