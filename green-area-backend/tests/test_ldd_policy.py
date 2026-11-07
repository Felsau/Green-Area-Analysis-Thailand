"""ldd-policy-v2 pure rules: field profiles, code parsing, tiers. No native GIS."""
from types import MappingProxyType

import pytest

from gis_worker import ldd_policy as policy

LEGEND = {'U101': [1, 'x', 'x'], 'A101': [2, 'x', 'x'], 'A300': [2, 'x', 'x'], 'A400': [2, 'x', 'x'],
          'A300/A400': [2, 'x', 'x'], 'F100': [3, 'x', 'x'], 'W101': [4, 'x', 'x'], 'M101': [5, 'x', 'x']}
CLASSES = policy.main_classes(LEGEND)


def test_legend_pairing_is_derived_and_must_be_consistent():
    assert dict(CLASSES) == {'U': 1, 'A': 2, 'F': 3, 'W': 4, 'M': 5}
    with pytest.raises(policy.PolicyError, match='VALIDATION_ASSET_INVALID'):
        policy.main_classes({**LEGEND, 'U102': [2, 'x', 'x']})
    with pytest.raises(policy.PolicyError, match='VALIDATION_ASSET_INVALID'):
        policy.main_classes({'U101': [1, 'x', 'x']})


@pytest.mark.parametrize('names,mapping', [
    (['LUL1_CODE', 'LU_CODE', 'Shape_Area', 'OTHER'], {'main_code': 'LUL1_CODE', 'lu_code': 'LU_CODE', 'declared_area': 'Shape_Area'}),
    (['lul1_code', 'Lu_Code', 'SHAPE_AREA'], {'main_code': 'lul1_code', 'lu_code': 'Lu_Code', 'declared_area': 'SHAPE_AREA'}),
])
def test_profile_maps_actual_names_and_records_them(names, mapping):
    assert policy.resolve_profile(names) == ('ldd-lu-text-v1', mapping)


@pytest.mark.parametrize('names,code', [
    (['LUL1_CODE', 'LU_CODE'], 'ATTRIBUTES_MISSING'),
    (['LUL1_CODE', 'LU_CODE', 'AREA'], 'ATTRIBUTES_MISSING'),       # no guessing that AREA is Shape_Area
    (['LUL1_CODE', 'LU_CODE', 'Shape_Area', 'SHAPE_AREA'], 'FIELD_NAME_AMBIGUOUS'),
])
def test_missing_or_duplicate_fields_are_rejected(names, code):
    with pytest.raises(policy.PolicyError, match=code):
        policy.resolve_profile(names)


def test_two_matching_profiles_are_ambiguous_not_preferred(monkeypatch):
    twin = MappingProxyType({**policy.FIELD_PROFILES['ldd-lu-text-v1'],
                             'roles': MappingProxyType({'main_code': 'LUL1_CODE', 'lu_code': 'LU_CODE', 'declared_area': 'Shape_Area'})})
    monkeypatch.setattr(policy, 'FIELD_PROFILES', MappingProxyType({**policy.FIELD_PROFILES, 'twin-v1': twin}))
    with pytest.raises(policy.PolicyError, match='FIELD_MAPPING_AMBIGUOUS'):
        policy.resolve_profile(['LUL1_CODE', 'LU_CODE', 'Shape_Area'])


def test_declared_area_units_are_only_those_the_profile_states():
    assert policy.declared_area_units('ldd-lu-text-v1', 'EPSG:32647') == 'm2'
    assert policy.declared_area_units('ldd-lu-text-v1', 'EPSG:4326') is None


@pytest.mark.parametrize('lu,main,expected,normalised,reason', [
    ('U101', 'U', 'U', False, None),
    (' U101 ', ' U ', 'U', False, None),
    ('A101', 2, 'A', False, None),
    ('A101', 2.0, 'A', True, None),
    ('A101', '2', 'A', True, None),
    ('A300/A400', 'A', 'A', False, None),
    ('A101', 2.5, None, False, 'MAIN_CODE_UNRECOGNISED'),
    ('A101', True, None, False, 'MAIN_CODE_UNRECOGNISED'),
    ('A101', 'X', None, False, 'MAIN_CODE_UNRECOGNISED'),
    ('A101', 9, None, False, 'MAIN_CODE_UNRECOGNISED'),
    ('A101', 'U', None, False, 'LU_CODE_MAIN_CONFLICT'),
    ('U999', 'U', None, False, 'LU_CODE_NOT_IN_LEGEND'),
    ('U101/U999', 'U', None, False, 'LU_CODE_NOT_IN_LEGEND'),
    (2101, 2, None, False, 'NUMERIC_CODE_NO_APPROVED_CROSSWALK'),
    (2101.0, 2, None, False, 'NUMERIC_CODE_NO_APPROVED_CROSSWALK'),
    ('2101', 2, None, False, 'NUMERIC_CODE_NO_APPROVED_CROSSWALK'),
    (None, 'U', None, False, 'LU_CODE_UNRECOGNISED'),
    ('bogus/x', 'U', None, False, 'LU_CODE_UNRECOGNISED'),
])
def test_code_rules_text_integer_float_numeric_string(lu, main, expected, normalised, reason):
    result = policy.classify(lu, main, LEGEND, CLASSES)
    assert result['classification'] == expected and result['reason'] == reason
    if expected:
        assert result['normalised'] is normalised


@pytest.mark.parametrize('lu,main,expected,reason', [
    ('A300+A400', 'A', 'A', None),                        # "+" reads as "/" when every part is of the parcel's class
    (' A300+A400+A101 ', ' A ', 'A', None),
    ('A300+A400', 'U', None, 'LU_CODE_MAIN_CONFLICT'),    # right codes, wrong class for the parcel
    ('A300+U101', 'A', None, 'LU_CODE_MAIN_CONFLICT'),    # a "+" joining classes is never guessed
    ('A300+U101', 'U', None, 'LU_CODE_MAIN_CONFLICT'),
    ('A300+A999', 'A', None, 'LU_CODE_NOT_IN_LEGEND'),
    ('A300/A400+A101', 'A', None, 'LU_CODE_UNRECOGNISED'),   # the two separators are never mixed in one value
    ('A300+', 'A', None, 'LU_CODE_UNRECOGNISED'),
])
def test_a_plus_between_codes_is_a_composite_only_inside_one_class(lu, main, expected, reason):
    result = policy.classify(lu, main, LEGEND, CLASSES)
    assert result['classification'] == expected and result['reason'] == reason
    assert result['plus_separator'] is (expected is not None)
    if '+' in lu and reason != 'LU_CODE_UNRECOGNISED':
        assert result['composite'] is True


def test_the_slash_reading_does_not_set_the_plus_flag_and_plus_has_a_minor_code():
    assert policy.classify('A300/A400', 'A', LEGEND, CLASSES)['plus_separator'] is False
    assert policy.classify('A101', 'A', LEGEND, CLASSES)['plus_separator'] is False
    assert 'COMPOSITE_PLUS_SEPARATOR' in policy.MINOR
    assert policy.outcome({}, {'COMPOSITE_PLUS_SEPARATOR': 3}) == 'accepted_with_warnings'


def test_unknown_and_composite_values_are_kept_for_audit():
    result = policy.classify('U101/U999', 'U', LEGEND, CLASSES)
    assert result['composite'] is True and result['code_key'] == 'U101/U999'
    assert policy.classify(2101, 2, LEGEND, CLASSES)['code_key'] == '2101'
    assert policy.classify(None, 2, LEGEND, CLASSES)['code_key'] == 'null'
    assert len(policy.classify('U' * 500, 'U', LEGEND, CLASSES)['code_key']) == 40


def test_no_numeric_crosswalk_is_approved_without_provenance():
    assert dict(policy.CROSSWALKS) == {}


@pytest.mark.parametrize('inside,minor,review,share,expected', [
    (True, True, True, 0, None),
    (False, True, True, 0, 'BOUNDARY_OUTSIDE_MINOR'),
    (False, False, True, 0.01, 'BOUNDARY_OUTSIDE_REVIEW_REQUIRED'),
    (False, False, True, 0.2, 'OUTSIDE_PROVINCE'),
    (False, False, False, 0.0, 'OUTSIDE_PROVINCE'),
])
def test_boundary_tiers(inside, minor, review, share, expected):
    assert policy.boundary_tier(inside, minor, review, share) == expected


@pytest.mark.parametrize('before,after,kind,valid,empty,expected', [
    (10000, 10000, 'Polygon', True, False, None),
    (10000, 10000.5, 'MultiPolygon', True, False, None),
    (10000, 10020, 'Polygon', True, False, 'GEOMETRY_REPAIR_AREA_CHANGED'),
    (0, 5000, 'MultiPolygon', True, False, 'GEOMETRY_REPAIR_AREA_CHANGED'),
    (10000, 10000, 'GeometryCollection', True, False, 'GEOMETRY_REPAIR_TYPE_CHANGED'),
    (10000, 10000, 'LineString', True, False, 'GEOMETRY_REPAIR_TYPE_CHANGED'),
    (10000, 0, 'Polygon', True, True, 'GEOMETRY_INVALID'),
    (10000, 10000, 'Polygon', False, False, 'GEOMETRY_INVALID'),
])
def test_repair_acceptance(before, after, kind, valid, empty, expected):
    assert policy.repair_accepted(before, after, kind, valid, empty) == expected


def test_repair_limits_and_declared_area_tiers():
    assert not policy.repair_limit_exceeded(10, 20, 0.0, 1000.0)
    assert policy.repair_limit_exceeded(11, 20, 0.0, 1000.0)
    assert not policy.repair_limit_exceeded(100, 10000, 0.5, 1e6)
    assert policy.repair_limit_exceeded(101, 10000, 0.5, 1e6)
    assert policy.repair_limit_exceeded(1, 10000, 500.0, 1e6)
    assert policy.declared_area_tier(10000, 10000.5) is None
    assert policy.declared_area_tier(10050, 10000) == 'AREA_DECLARED_MINOR_DIFF'
    assert policy.declared_area_tier(11000, 10000) == 'AREA_DECLARED_MISMATCH_REVIEW_REQUIRED'


@pytest.mark.parametrize('errors,warnings,expected', [
    ({}, {}, 'accepted'),
    ({}, {'GEOMETRY_REPAIRED': 1}, 'accepted_with_warnings'),
    ({'UNKNOWN_CODE_REVIEW_REQUIRED': 1}, {}, 'review_required'),
    ({'UNKNOWN_CODE_REVIEW_REQUIRED': 1, 'OUTSIDE_PROVINCE': 1}, {}, 'rejected'),
    ({'SHAPEFILE_READ_ERROR': 1}, {}, 'rejected'),
])
def test_outcome_categories(errors, warnings, expected):
    assert policy.outcome(errors, warnings) == expected


def test_policy_codes_fit_the_migration_034_report_pattern():
    import re
    for code in policy.FATAL | policy.REVIEW | policy.MINOR:
        assert re.fullmatch(r'[A-Z0-9_]{1,60}', code)
    assert not (policy.FATAL & policy.REVIEW) and not (policy.MINOR & (policy.FATAL | policy.REVIEW))
