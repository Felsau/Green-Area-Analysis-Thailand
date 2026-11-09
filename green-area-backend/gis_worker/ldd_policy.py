"""Versioned LDD field-mapping, land-use code, area and geometry policies.

Pure Python: no native GIS import, file, network or database access. The native
validator (ldd_provider) and the preparation step (ldd_prepare_provider) both
call these functions, so validation, preparation and summaries apply one policy.

Nothing here guesses:
* Field profiles name exact source fields per role. A file must match exactly
  one approved profile; duplicate (case-folded) names or two matching profiles
  are rejected rather than resolved by preference.
* Text LU codes are looked up in the hash-pinned legend. The LUL1 main class may
  be a letter or the legend's own numeric class (int, integral float or numeric
  string) -- the letter<->number pairing is derived from the legend itself.
* Numeric LU codes are accepted only through an approved crosswalk with recorded
  provenance. None is approved yet, so they are counted as unknown and need
  review; they are never mapped to U/A/F/W/M by assumption.
* Area is computed from geometry in metres in a projected CRS. A declared area
  is compared only when the profile states its units for that CRS.
"""
from __future__ import annotations

import math
from pathlib import PurePosixPath
import re
from types import MappingProxyType

POLICY_VERSION = 'ldd-policy-v2'
AREA_METHOD = 'geometry-area-utm-v1'
GEOMETRY_POLICY = 'ldd-geometry-repair-v1'
BOUNDARY_POLICY = 'boundary-tolerance-m-v1'
CODE_POLICY = 'ldd-code-legend-v2'

# ---------------------------------------------------------------- field profiles
# role -> exact source field name (matched case-insensitively, duplicates rejected).
# 'absent' lists fields that must NOT be in the file, so every real layout matches one profile at most:
# 2567 layers carry both Shape_Area and AREA_SQM, 2568 layers carry AREA_SQM only, and six 2568 layers
# have no LUL1_CODE. A file that matches two profiles is still refused, never resolved by preference.
FIELD_PROFILES = MappingProxyType({
    'ldd-lu-text-v1': MappingProxyType({
        'roles': MappingProxyType({'main_code': 'LUL1_CODE', 'lu_code': 'LU_CODE', 'declared_area': 'Shape_Area'}),
        'absent': (),
        # Units of declared_area per source CRS; absent CRS -> units not verified.
        'declared_area_units': MappingProxyType({'EPSG:32647': 'm2', 'EPSG:32648': 'm2'}),
        'lu_code_kind': 'text',
        'provenance': 'LDD land use 2566 Bangkok layout (repository fixtures/legend source_sha256 '
                      '949639e52513f431255578c26125906122d689f8171a72d379086159f136e12a)',
        'review_reference': 'docs/gis/ldd-field-policy.md#ldd-lu-text-v1',
    }),
    'ldd-lu-area-sqm-v1': MappingProxyType({
        'roles': MappingProxyType({'main_code': 'LUL1_CODE', 'lu_code': 'LU_CODE', 'declared_area': 'AREA_SQM'}),
        'absent': ('Shape_Area',),
        'declared_area_units': MappingProxyType({'EPSG:32647': 'm2', 'EPSG:32648': 'm2'}),
        'lu_code_kind': 'text',
        'provenance': 'LDD land use 2568 layout without Shape_Area, recorded from 9 real central-region layers '
                      '(e.g. LU_SKM_2568 package sha256 b39404fa63880223d12b4b0dbcea11e120adb02bcfb5c5bbd7ee0c0d0508738f, '
                      'LU_AYU_2568 package sha256 20c349531fea8e73ec8ecf87174abe72f84f71bba790ba435c80e128604fd8b5)',
        'review_reference': 'docs/gis/ldd-field-policy.md#ldd-lu-area-sqm-v1',
    }),
    'ldd-lu-id-l1-area-sqm-v1': MappingProxyType({
        # LU_ID_L1 is the numeric level-1 class (1-5 = U A F W M). Used only where LUL1_CODE is missing:
        # in layers that have both, LUL1_CODE always agreed with LU_CODE while LU_ID_L1 held stray values.
        'roles': MappingProxyType({'main_code': 'LU_ID_L1', 'lu_code': 'LU_CODE', 'declared_area': 'AREA_SQM'}),
        'absent': ('Shape_Area', 'LUL1_CODE'),
        'declared_area_units': MappingProxyType({'EPSG:32647': 'm2', 'EPSG:32648': 'm2'}),
        'lu_code_kind': 'text',
        'provenance': 'LDD land use 2568 layout without LUL1_CODE, recorded from 6 real central-region layers '
                      '(e.g. LU_PTE_2568 package sha256 aef20813c2bf222213d1dd05398adfa90e28b83e31685104c6f90648721bd15c, '
                      'LU_ATG_2568 package sha256 a12f00e7a028bf50e09e81e1458cc9ae8ec3129b48d4edab01330b4c92ddf1e2)',
        'review_reference': 'docs/gis/ldd-field-policy.md#ldd-lu-id-l1-area-sqm-v1',
    }),
})
LEGACY_PROFILE = 'ldd-lu-text-v1'

# Numeric LU code -> legend text code. Each entry needs a verified source legend.
CROSSWALKS = MappingProxyType({})

# ---------------------------------------------------------------- package policy
# A province package from LDD carries more than the land-use layer: administrative
# boundary layers, spreadsheets, metadata and documents (Bangkok 2566 has 35 members
# and four shapefiles). The validator reads ONE layer. Every other member still counts
# against the size, ratio and path limits but is never decompressed, parsed or handed
# to GDAL; the layer is re-packed under fixed names before GDAL sees it.
LAND_USE_PREFIX = 'lu_'                                   # LDD names the layer LU_<province>_<year>.shp
LAYER_SUFFIXES = ('.shp', '.shx', '.dbf', '.prj', '.cpg')  # the only members that are ever read
# Nested archives must be unpacked first; the rest are programs, scripts, libraries and GDAL virtual
# datasets, which have no place in a data package even though they would not be read.
ARCHIVE_SUFFIXES = frozenset({'.zip', '.7z', '.rar', '.gz', '.tgz', '.tar', '.bz2', '.xz'})
BLOCKED_SUFFIXES = ARCHIVE_SUFFIXES | frozenset({
    '.exe', '.dll', '.com', '.bat', '.cmd', '.ps1', '.vbs', '.js', '.jar', '.msi', '.scr', '.lnk',
    '.sh', '.py', '.pyc', '.so', '.dylib', '.vrt'})


def select_land_use_layer(names):
    """Return the one land-use ``.shp`` among the file members of a package, else None.

    Single-shapefile ZIPs keep today's behaviour (any name). With several shapefiles exactly
    one must be named ``LU_*`` (any case); zero or several is None. Nothing is guessed.
    """
    shapes = [n for n in names if PurePosixPath(n).suffix.lower() == '.shp']
    if len(shapes) > 1:
        shapes = [n for n in shapes if PurePosixPath(n).name.casefold().startswith(LAND_USE_PREFIX)]
    return shapes[0] if len(shapes) == 1 else None

# ---------------------------------------------------------------- geometry policy
# The boundary asset is approximate (GADM level 1, 161 vertices for Bangkok). The
# legacy validator tolerated a 0.002 degree buffer (about 216-221 m here); the
# minor tier is kept at least that wide in metres so nothing it accepted is lost.
BOUNDARY_MINOR_M = 225.0
BOUNDARY_REVIEW_M = 1000.0        # beyond this nothing is accepted or reviewed
BOUNDARY_REVIEW_PART_MAX = 0.05   # share of a parcel beyond MINOR that may still be reviewed
DATASET_OUTSIDE_SHARE_MAX = 0.01  # area outside the raw boundary / total ...
DATASET_OUTSIDE_MIN_M2 = 10000.0  # ... and more than 1 ha in absolute terms, else review

REPAIR_AREA_REL_MAX = 0.001       # per parcel: |after-before| / before
REPAIR_AREA_ABS_MAX_M2 = 1.0      # ... or at most 1 m2
REPAIR_COUNT_SHARE_MAX = 0.01     # repaired parcels / all parcels, else review
REPAIR_COUNT_MIN_ALLOWED = 10     # small datasets may repair up to this many
REPAIR_TOTAL_AREA_REL_MAX = 0.0001

DECLARED_MATCH_REL, DECLARED_MATCH_ABS = 0.001, 1.0   # unchanged legacy tolerance
DECLARED_MINOR_REL = 0.01                             # above -> review

# ---------------------------------------------------------------- outcome codes
FATAL = frozenset({'GEOMETRY_ENGINE_UNSUPPORTED', 'NATIVE_PROCESS_FAILED', 'GEOMETRY_TYPE', 'GEOMETRY_EMPTY', 'GEOMETRY_INVALID', 'GEOMETRY_REPAIR_TYPE_CHANGED',
                   'GEOMETRY_REPAIR_AREA_CHANGED', 'OUTSIDE_PROVINCE', 'AREA_INVALID', 'ATTRIBUTES_MISSING',
                   'FIELD_NAME_AMBIGUOUS', 'FIELD_MAPPING_AMBIGUOUS', 'FEATURE_COUNT_MISMATCH'})
REVIEW = frozenset({'UNKNOWN_CODE_REVIEW_REQUIRED', 'BOUNDARY_OUTSIDE_REVIEW_REQUIRED',
                    'BOUNDARY_OUTSIDE_AREA_REVIEW_REQUIRED', 'AREA_DECLARED_MISMATCH_REVIEW_REQUIRED',
                    'GEOMETRY_REPAIR_LIMIT_REVIEW_REQUIRED'})
MINOR = frozenset({'GEOMETRY_REPAIRED', 'BOUNDARY_OUTSIDE_MINOR', 'AREA_DECLARED_MINOR_DIFF',
                   'DECLARED_AREA_UNITS_UNVERIFIED', 'NUMERIC_MAIN_CODE_NORMALISED', 'COMPOSITE_PLUS_SEPARATOR',
                   'CPG_ENCODING_ALIAS', 'CRS_VERTICAL_IGNORED'})
GEOMETRY_CODES = frozenset({'GEOMETRY_TYPE', 'GEOMETRY_EMPTY', 'GEOMETRY_INVALID', 'GEOMETRY_REPAIR_TYPE_CHANGED',
                            'GEOMETRY_REPAIR_AREA_CHANGED', 'OUTSIDE_PROVINCE', 'BOUNDARY_OUTSIDE_REVIEW_REQUIRED'})


class PolicyError(ValueError):
    """Fixed public code only."""


def outcome(errors, warnings):
    """Accepted / Accepted with Warnings / Review Required / Rejected."""
    codes = set(errors)
    if codes - REVIEW:
        return 'rejected'
    if codes:
        return 'review_required'
    if set(warnings) & MINOR:
        return 'accepted_with_warnings'
    return 'accepted'


# ---------------------------------------------------------------- fields
def resolve_profile(field_names):
    """Return (profile_id, {role: actual_field_name}) or raise PolicyError."""
    names = list(field_names)
    folded = [n.casefold() for n in names]
    if len(set(folded)) != len(folded):
        raise PolicyError('FIELD_NAME_AMBIGUOUS')
    actual = {n.casefold(): n for n in names}
    matches = []
    for profile_id, profile in FIELD_PROFILES.items():
        roles = profile['roles']
        if (all(field.casefold() in actual for field in roles.values())
                and not any(field.casefold() in actual for field in profile.get('absent', ()))):
            matches.append((profile_id, {role: actual[field.casefold()] for role, field in roles.items()}))
    if not matches:
        raise PolicyError('ATTRIBUTES_MISSING')
    if len(matches) > 1:
        raise PolicyError('FIELD_MAPPING_AMBIGUOUS')
    return matches[0]


def declared_area_units(profile_id, crs):
    return FIELD_PROFILES[profile_id]['declared_area_units'].get(crs)


# ---------------------------------------------------------------- .cpg and .prj variants (policy-v2 only)
# A closed list of .cpg texts that name a supported codec by another name. Five real LDD 2568 layers write
# "ANSI 874", the Windows code page that Python calls cp874. Case and repeated spaces are ignored; any other
# text still goes through the codec registry, and every text field is still decoded strictly.
CPG_ALIASES = MappingProxyType({'ansi 874': 'cp874'})


def cpg_alias(text):
    """Return the codec a .cpg text names by alias, else None."""
    return CPG_ALIASES.get(' '.join(text.split()).casefold()) if isinstance(text, str) else None


def horizontal_wkt(text):
    """Return the horizontal part of a .prj written as ``PROJCS[...],VERTCS[...]``, else None.

    ESRI software writes a 3D layer that way, without a COMPD_CS wrapper (real LDD 2568 Ang Thong and
    Suphan Buri). Only that exact shape is split: two top-level parts, a PROJCS or GEOGCS followed by one
    VERTCS. The vertical part does not change X/Y. Any other text is left alone and checked as written.
    """
    if not isinstance(text, str):
        return None
    parts, depth, start, quoted = [], 0, 0, False
    for i, ch in enumerate(text):
        if ch == '"':
            quoted = not quoted
        elif quoted:
            continue
        elif ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth < 0:
                return None
        elif ch == ',' and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    if depth or quoted:
        return None
    parts.append(text[start:])
    if len(parts) != 2:
        return None
    head, tail = (part.strip() for part in parts)
    if not (head.startswith(('PROJCS[', 'GEOGCS[')) and head.endswith(']')
            and tail.startswith('VERTCS[') and tail.endswith(']')):
        return None
    if any(word in head.upper() for word in ('VERTCS[', 'COMPD_CS[')):
        return None
    return head


# ---------------------------------------------------------------- codes
# A code, or up to eight codes joined by "/" or all joined by "+" (never both in one value). Real LDD files
# join with "/" in 36,000 parcels and with "+" in 731; every part of both is an official code.
_TEXT_CODE = re.compile(r'[UAFWM][0-9]{3}(?:/[UAFWM][0-9]{3}){0,7}|[UAFWM][0-9]{3}(?:\+[UAFWM][0-9]{3}){1,7}')
_NUMERIC_TEXT = re.compile(r'[0-9]{1,9}(?:\.0+)?')


def main_classes(legend):
    """Letter <-> numeric class pairing as recorded in the pinned legend."""
    pairs = {}
    for code, entry in legend.items():
        if '/' in code:
            continue
        letter, number = code[0], entry[0]
        if pairs.setdefault(letter, number) != number:
            raise PolicyError('VALIDATION_ASSET_INVALID')
    if sorted(pairs) != sorted('UAFWM') or len(set(pairs.values())) != 5:
        raise PolicyError('VALIDATION_ASSET_INVALID')
    return MappingProxyType(pairs)


def _integral(value):
    """int, integral float or numeric string -> int; anything else -> None."""
    if type(value) is bool:
        return None
    if type(value) is int:
        return value
    if type(value) is float:
        return int(value) if math.isfinite(value) and value.is_integer() else None
    if isinstance(value, str) and _NUMERIC_TEXT.fullmatch(value.strip()):
        return int(float(value.strip()))
    return None


def parse_main(value, classes):
    """Return (letter or None, normalised: bool)."""
    if isinstance(value, str) and value.strip() in classes:
        return value.strip(), False
    number = _integral(value)
    if number is not None:
        letters = [k for k, v in classes.items() if v == number]
        if len(letters) == 1:
            return letters[0], type(value) is not int
    return None, False


def classify(lu_value, main_value, legend, classes):
    """Return dict(classification, code_key, composite, reason, normalised)."""
    main, normalised = parse_main(main_value, classes)
    result = {'classification': None, 'code_key': _code_key(lu_value), 'composite': False,
              'reason': None, 'normalised': normalised, 'plus_separator': False}
    if main is None:
        result['reason'] = 'MAIN_CODE_UNRECOGNISED'
        return result
    if isinstance(lu_value, str) and _TEXT_CODE.fullmatch(lu_value.strip()):
        code = lu_value.strip()
        plus = '+' in code
        parts = code.split('+' if plus else '/')
        result['code_key'] = code
        result['composite'] = len(parts) > 1
        number = classes[main]
        if plus:
            # "+" reads as "/" only when every part is a legend code of the parcel's own class; a value joining
            # classes is never guessed, and it is reported (COMPOSITE_PLUS_SEPARATOR) so the reading stays visible.
            ok = all(p in legend and legend[p][0] == number for p in parts)
            result['plus_separator'] = ok
        elif code in legend:
            ok = legend[code][0] == number
        else:
            ok = len(parts) > 1 and all(p in legend and legend[p][0] == number for p in parts)
        if ok:
            result['classification'] = main
        else:
            result['reason'] = 'LU_CODE_NOT_IN_LEGEND' if not all(p in legend for p in parts) else 'LU_CODE_MAIN_CONFLICT'
        return result
    if isinstance(lu_value, str) and '/' in lu_value:
        result['composite'] = True
    if _integral(lu_value) is not None:
        result['reason'] = 'NUMERIC_CODE_NO_APPROVED_CROSSWALK'
    else:
        result['reason'] = 'LU_CODE_UNRECOGNISED'
    return result


def _code_key(value):
    """Bounded, lossless-enough display of the original value for audit."""
    if value is None:
        return 'null'
    text = value if isinstance(value, str) else repr(value)
    text = ''.join(c for c in text if c.isprintable())
    return text[:40]


# ---------------------------------------------------------------- geometry
def metric_crs(source_crs, lon):
    if source_crs in ('EPSG:32647', 'EPSG:32648'):
        return source_crs
    return 'EPSG:32647' if lon < 102 else 'EPSG:32648'


def boundary_tier(inside, within_minor, within_review, beyond_minor_share):
    if inside:
        return None
    if within_minor:
        return 'BOUNDARY_OUTSIDE_MINOR'
    if within_review and beyond_minor_share <= BOUNDARY_REVIEW_PART_MAX:
        return 'BOUNDARY_OUTSIDE_REVIEW_REQUIRED'
    return 'OUTSIDE_PROVINCE'


def repair_accepted(before_area, after_area, after_type, after_valid, after_empty):
    """Return None when the repair is within policy, else the fatal code."""
    if after_empty or not after_valid:
        return 'GEOMETRY_INVALID'
    if after_type not in ('Polygon', 'MultiPolygon'):
        return 'GEOMETRY_REPAIR_TYPE_CHANGED'
    if not (math.isfinite(before_area) and math.isfinite(after_area)) or before_area <= 0:
        return 'GEOMETRY_REPAIR_AREA_CHANGED'
    change = abs(after_area - before_area)
    if change > max(REPAIR_AREA_ABS_MAX_M2, before_area * REPAIR_AREA_REL_MAX):
        return 'GEOMETRY_REPAIR_AREA_CHANGED'
    return None


def repair_limit_exceeded(repaired, features, area_change, total_area):
    allowed = max(REPAIR_COUNT_MIN_ALLOWED, math.floor(features * REPAIR_COUNT_SHARE_MAX))
    return repaired > allowed or area_change > max(total_area * REPAIR_TOTAL_AREA_REL_MAX, REPAIR_AREA_ABS_MAX_M2)


def declared_area_tier(declared, area):
    if math.isclose(declared, area, rel_tol=DECLARED_MATCH_REL, abs_tol=DECLARED_MATCH_ABS):
        return None
    if area > 0 and abs(declared - area) / area <= DECLARED_MINOR_REL:
        return 'AREA_DECLARED_MINOR_DIFF'
    return 'AREA_DECLARED_MISMATCH_REVIEW_REQUIRED'


def policy_summary():
    return {'policy_version': POLICY_VERSION, 'area_method': AREA_METHOD, 'geometry_policy': GEOMETRY_POLICY,
            'boundary_policy': BOUNDARY_POLICY, 'code_policy': CODE_POLICY,
            'boundary_minor_m': BOUNDARY_MINOR_M, 'boundary_review_m': BOUNDARY_REVIEW_M,
            'boundary_review_part_max': BOUNDARY_REVIEW_PART_MAX, 'dataset_outside_share_max': DATASET_OUTSIDE_SHARE_MAX,
            'dataset_outside_min_m2': DATASET_OUTSIDE_MIN_M2, 'repair_method': 'shapely.make_valid(method=structure)',
            'repair_area_rel_max': REPAIR_AREA_REL_MAX, 'repair_area_abs_max_m2': REPAIR_AREA_ABS_MAX_M2,
            'repair_count_share_max': REPAIR_COUNT_SHARE_MAX, 'repair_count_min_allowed': REPAIR_COUNT_MIN_ALLOWED,
            'declared_match_rel': DECLARED_MATCH_REL, 'declared_minor_rel': DECLARED_MINOR_REL}
