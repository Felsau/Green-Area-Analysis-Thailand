"""Approved NDVI/LST method definitions (code-reviewed, never from API payload).

A definition is the minimum a scientific review signs off on: the method
versions it covers, the source hash scheme and the approved source hashes, the
collections, bands, masks, scale/offset, reducers, units, the scientific values
the legacy sources must still express, and the review reference.

Rules
* Only definitions in ``APPROVED`` exist. Unknown or unreviewed methods fail
  closed (``PROCESSING_METHOD_UNREVIEWED``); there is no "latest" fallback.
* The legacy sources on disk must match exactly one approved definition under
  that definition's declared hash scheme. A source change without a new
  reviewed definition fails closed (``PROCESSING_LEGACY_SOURCE_CHANGED``).
* Adding a definition never changes an existing one: old manifests, results
  and caches stay bound to the definition (and the v0 identity) they were
  produced under; nothing is re-labelled as a newer method.
* A new definition (for example after the Dashboard formula changes) also needs
  a forward SQL migration before the queue will accept manifests for it, because
  migrations 035/044 pin the legacy-v1 identity. See
  docs/gis/method-review-contract.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from gis_worker import source_integrity as si


class MethodError(ValueError):
    """Fixed public code only."""


@dataclass(frozen=True)
class MethodDefinition:
    method_id: str
    method_versions: tuple[str, ...]
    source_hash_scheme: str
    # repository-relative path -> approved hash under source_hash_scheme
    approved_sources: tuple[tuple[str, str], ...]
    # same reviewed text under the historical CRLF scheme (bound in SQL 035/044)
    legacy_identity_scheme: str
    legacy_identity: tuple[tuple[str, str], ...]
    collections: MappingProxyType
    bands: MappingProxyType
    masks: MappingProxyType
    scale_offset: MappingProxyType
    reducers: MappingProxyType
    units: MappingProxyType
    scientific_expected: MappingProxyType
    review_reference: str
    status: str = field(default='approved')

    def source_paths(self):
        return tuple(path for path, _ in self.approved_sources)


def _ro(value):
    return MappingProxyType(dict(value))


# Container file names used by the offline processing worker (/app/legacy/*).
LEGACY_FILE_NAMES = MappingProxyType({
    'gee_utils.py': 'gee_utils.py',
    'routers/ndvi/compute.py': 'ndvi_compute.py',
    'routers/lst.py': 'lst.py',
})

LEGACY_V1 = MethodDefinition(
    method_id='legacy-v1',
    method_versions=('ndvi-annual-legacy-v1', 'ndvi-monthly-legacy-v1',
                     'lst-annual-legacy-v1', 'lst-monthly-legacy-v1'),
    source_hash_scheme=si.SOURCE_TEXT_SCHEME,
    approved_sources=(
        ('gee_utils.py', '776173887a32ff9e4d96c1dbe0cb30d231c38877f708dc6dbc06b4d03e8dcffb'),
        ('routers/ndvi/compute.py', '5b1b0384b9edf905654bf4fe7c888a8201d059b918c98ba9ce45e7a607ecce9e'),
        ('routers/lst.py', 'cb0a6ab0e1c0bf6104f1dbc71fae29f7db0efbee268200bff06d16e664df2e01'),
    ),
    legacy_identity_scheme=si.LEGACY_CRLF_SCHEME,
    legacy_identity=(
        ('gee_utils.py', 'd1f25fdca1c0562379d5f98002e9bea0a3c94d36f71df6bea45ec6bf94a9a175'),
        ('routers/ndvi/compute.py', '87b22a35e9dd610e6359f375de5dd9cfebd666bdcee28a22363179155b1febcd'),
        ('routers/lst.py', '748dcc2d6cc33108bdb7f07effadc2bcbb202e6436703fec68d7d0017004176f'),
    ),
    collections=_ro({'ndvi': ('COPERNICUS/S2_SR_HARMONIZED', 'GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED'),
                     'lst': ('LANDSAT/LC08/C02/T1_L2', 'LANDSAT/LC09/C02/T1_L2')}),
    bands=_ro({'ndvi': ('B8', 'B4', 'cs'), 'lst': ('ST_B10', 'QA_PIXEL')}),
    masks=_ro({'ndvi_clear_score_gte': 0.6, 'ndvi_annual_scene_cloud_lt': 20,
               'ndvi_annual_fallback_cloud_lt': 80, 'ndvi_monthly_scene_cloud_lt': 80,
               'lst_scene_cloud_lt': 40, 'lst_qa_mask_bits': (3, 4),
               'ndvi_annual_mask_negative': True}),
    scale_offset=_ro({'ndvi_reflectance_divisor': 10000, 'lst_st_multiplier': 0.00341802,
                      'lst_st_offset_kelvin': 149.0, 'lst_celsius_subtract': 273.15}),
    reducers=_ro({'ndvi': 'median_bands_then_normalized_difference', 'lst': 'scale_then_median',
                  'region': 'mean_min_max', 'province_scale_m': 500, 'district_scale_m': 100}),
    units=_ro({'ndvi': 'unitless', 'lst': 'celsius'}),
    # What legacy_spec() must read from the reviewed sources (AST data only).
    scientific_expected=_ro({
        'ndvi_bands': ('B8', 'B4'), 'cs_threshold': 0.6, 'reflectance_divisor': 10000,
        'annual_cloud': 20, 'annual_cloud_fallback': 80, 'monthly_cloud': 80, 'lst_cloud': 40,
        'lst_mask_bits': (3, 4),
        'lst_operations': (('multiply', 0.00341802), ('add', 149.0), ('subtract', 273.15)),
    }),
    review_reference='docs/gis/a6-1-handoff.md (A6.1 legacy-v1 method contract); docs/gis/method-review-contract.md',
)

APPROVED = MappingProxyType({LEGACY_V1.method_id: LEGACY_V1})
_BY_VERSION = MappingProxyType({v: d for d in APPROVED.values() for v in d.method_versions})


def definition(method_id: str) -> MethodDefinition:
    value = APPROVED.get(method_id) if isinstance(method_id, str) else None
    if value is None or value.status != 'approved':
        raise MethodError('PROCESSING_METHOD_UNREVIEWED')
    return value


def definition_for_version(method_version: str) -> MethodDefinition:
    value = _BY_VERSION.get(method_version) if isinstance(method_version, str) else None
    if value is None or value.status != 'approved':
        raise MethodError('PROCESSING_METHOD_UNREVIEWED')
    return value


def legacy_identity_map(defn: MethodDefinition = LEGACY_V1) -> dict:
    """Container-name -> v0 identity, exactly as pinned in manifests (SQL 035)."""
    return {LEGACY_FILE_NAMES[path]: sha for path, sha in defn.legacy_identity}


def check_source_bytes(defn: MethodDefinition, sources: dict) -> None:
    """``sources``: repository-relative path -> raw bytes read from disk.

    Each file must match the definition's approved hash under its declared
    scheme; the v0 identity must be reproducible from the same text, which binds
    the old pinned values to the reviewed text instead of trusting them blindly.
    """
    if set(sources) != set(defn.source_paths()):
        raise MethodError('PROCESSING_LEGACY_SOURCE_CHANGED')
    identity = dict(defn.legacy_identity)
    for path, expected in defn.approved_sources:
        raw = sources[path]
        if not si.verify(raw, expected, defn.source_hash_scheme):
            raise MethodError('PROCESSING_LEGACY_SOURCE_CHANGED')
        if not si.verify(raw, identity[path], defn.legacy_identity_scheme):
            raise MethodError('PROCESSING_LEGACY_SOURCE_CHANGED')


def match_sources(sources: dict) -> MethodDefinition:
    """Exactly one approved definition must describe the sources on disk."""
    matches = []
    for defn in APPROVED.values():
        try:
            check_source_bytes(defn, sources)
        except MethodError:
            continue
        matches.append(defn)
    if len(matches) != 1:
        raise MethodError('PROCESSING_LEGACY_SOURCE_CHANGED')
    return matches[0]


def read_repository_sources(backend_root: Path, defn: MethodDefinition = LEGACY_V1) -> dict:
    return {path: si.read_regular_file(Path(backend_root) / path) for path in defn.source_paths()}
