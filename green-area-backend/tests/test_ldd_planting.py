"""Tests for the LDD planting filter: ldd_planting (pure), ldd.ldd_source_for,
and the LDD step of get_top_locations (GEE faked). No network, no GEE."""
import copy
from unittest.mock import MagicMock

import ee
import pytest

import ldd
from ldd_planting import (EXCLUDE, NEUTRAL, PREFER, apply_ldd_codes,
                          classify_code, split_code)


class TestSplitCode:
    def test_compound(self):
        assert split_code("A405/A411") == ["A405", "A411"]

    def test_tolerates_case_and_spaces(self):
        assert split_code(" u401 / a100 ") == ["U401", "A100"]

    @pytest.mark.parametrize("v", [None, "", "  ", "/"])
    def test_empty(self, v):
        assert split_code(v) == []


class TestClassifyCode:
    @pytest.mark.parametrize("code", [
        "U401", "U405", "W101", "W999", "A901", "A902", "F101", "F204",
        "U501", "U502", "U101"])
    def test_exclude(self, code):
        assert classify_code(code) == EXCLUDE

    @pytest.mark.parametrize("code", ["M101", "A100", "U500", "A300", "U200"])
    def test_prefer(self, code):
        assert classify_code(code) == PREFER

    @pytest.mark.parametrize("code", ["A101", "U301", "U201", "A405"])
    def test_neutral(self, code):
        assert classify_code(code) == NEUTRAL

    def test_u500_prefer_but_u501_u502_exclude(self):
        assert classify_code("U500") == PREFER
        assert classify_code("U501") == EXCLUDE
        assert classify_code("U502") == EXCLUDE

    @pytest.mark.parametrize("code,expected", [
        ("A405/A411", NEUTRAL),
        ("U201/A401", NEUTRAL),
        ("A100/U401", EXCLUDE),
        ("M101/A101", PREFER),
        ("U401/M101", EXCLUDE),
        ("A101/A901", EXCLUDE),
    ])
    def test_compound(self, code, expected):
        assert classify_code(code) == expected

    @pytest.mark.parametrize("v", [None, "", "   "])
    def test_missing_is_neutral(self, v):
        assert classify_code(v) == NEUTRAL

    def test_case_and_space_tolerant(self):
        assert classify_code(" u401 ") == EXCLUDE
        assert classify_code("m101") == PREFER


def _cands():
    return [{"lng": 100.0 + i, "lat": 13.0, "score": 1.0 - i / 10} for i in range(5)]


class TestApplyLddCodes:
    def test_order_drop_count_and_labels(self):
        codes = {0: {"code": "A101", "name_th": "na"},
                 1: {"code": "U401", "name_th": "airport"},
                 2: {"code": "M101", "name_th": "grass"},
                 3: {"code": "W101", "name_th": "water"},
                 4: {"code": "U201", "name_th": "village"}}
        kept, dropped = apply_ldd_codes(_cands(), codes, 2566)
        assert dropped == 2
        assert [k["lng"] for k in kept] == [100.0, 102.0, 104.0]
        assert kept[0]["ldd"] == {"code": "A101", "name_th": "na",
                                  "rule": NEUTRAL, "edition_year": 2566}
        assert kept[1]["ldd"]["rule"] == PREFER

    def test_missing_index_is_neutral_with_none_code(self):
        kept, dropped = apply_ldd_codes(
            _cands()[:2], {0: {"code": "A101", "name_th": "x"}}, 2567)
        assert dropped == 0
        assert kept[1]["ldd"] == {"code": None, "name_th": None,
                                  "rule": NEUTRAL, "edition_year": 2567}

    def test_every_kept_point_has_ldd_key(self):
        kept, _ = apply_ldd_codes(_cands(), {}, 2566)
        assert len(kept) == 5 and all("ldd" in k for k in kept)

    def test_inputs_not_mutated(self):
        c = _cands()
        before = copy.deepcopy(c)
        codes = {0: {"code": "A101", "name_th": "x"}}
        codes_before = copy.deepcopy(codes)
        apply_ldd_codes(c, codes, 2566)
        assert c == before and codes == codes_before

    def test_empty(self):
        assert apply_ldd_codes([], {}, 2566) == ([], 0)


class TestLddSourceFor:
    @pytest.fixture(autouse=True)
    def _empty_registry(self, monkeypatch):
        monkeypatch.setattr(ldd, "_registry", lambda: {})

    def test_registry_entry_with_defaults(self, monkeypatch):
        monkeypatch.setattr(ldd, "_registry", lambda: {
            "Nonthaburi": {"asset": "users/x/nonthaburi", "year_be": "2568"}})
        assert ldd.ldd_source_for("Nonthaburi") == {
            "asset": "users/x/nonthaburi", "year_be": 2568,
            "code_field": "LU_CODE", "name_field": "LU_DES_TH"}

    def test_registry_entry_custom_fields(self, monkeypatch):
        monkeypatch.setattr(ldd, "_registry", lambda: {
            "Nonthaburi": {"asset": "a", "year_be": 2568,
                           "code_field": "LU_ID", "name_field": "NAME"}})
        s = ldd.ldd_source_for("Nonthaburi")
        assert s["code_field"] == "LU_ID" and s["name_field"] == "NAME"

    def test_bangkok_env_fallback_set(self, monkeypatch):
        monkeypatch.setattr(ldd, "LDD_ASSET_ID", "users/x/bkk")
        assert ldd.ldd_source_for("Bangkok Metropolis") == {
            "asset": "users/x/bkk", "year_be": 2566,
            "code_field": "LU_CODE", "name_field": "LU_DES_TH"}

    def test_bangkok_env_fallback_unset(self, monkeypatch):
        monkeypatch.setattr(ldd, "LDD_ASSET_ID", None)
        assert ldd.ldd_source_for("Bangkok Metropolis") is None

    def test_registry_beats_env_for_bangkok(self, monkeypatch):
        monkeypatch.setattr(ldd, "LDD_ASSET_ID", "env-asset")
        monkeypatch.setattr(ldd, "_registry", lambda: {
            "Bangkok Metropolis": {"asset": "reg-asset", "year_be": 2568}})
        s = ldd.ldd_source_for("Bangkok Metropolis")
        assert s["asset"] == "reg-asset" and s["year_be"] == 2568

    def test_unknown_and_none(self, monkeypatch):
        monkeypatch.setattr(ldd, "LDD_ASSET_ID", "env-asset")
        assert ldd.ldd_source_for("Atlantis") is None
        assert ldd.ldd_source_for(None) is None
        assert ldd.ldd_source_for("") is None

    def test_entry_without_asset_ignored(self, monkeypatch):
        monkeypatch.setattr(ldd, "_registry", lambda: {"Phuket": {"year_be": 2568}})
        assert ldd.ldd_source_for("Phuket") is None

    def test_filter_meta(self):
        m = ldd.ldd_filter_meta({"year_be": 2568})
        assert m["edition_year"] == 2568 and m["source"] == "ldd"


class TestRegistryFile:
    def test_real_registry_is_valid_dict(self):
        ldd._registry.cache_clear()
        reg = ldd._registry()
        assert isinstance(reg, dict)
        for name, e in reg.items():
            assert e.get("asset") and int(e["year_be"]), name

    def test_missing_file_gives_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ldd, "_ASSET_REGISTRY", tmp_path / "nope.json")
        ldd._registry.cache_clear()
        try:
            assert ldd._registry() == {}
        finally:
            ldd._registry.cache_clear()


def test_codes_at_points_empty_input_skips_gee():
    src = {"asset": "a", "code_field": "c", "name_field": "n"}
    assert ldd.ldd_codes_at_points([], src) == {}


class TestGetTopLocationsLdd:
    """get_top_locations with the ee namespace replaced by a MagicMock and the
    GEE sampling helpers patched; only the LDD step is real."""

    SRC = {"asset": "a", "year_be": 2568, "code_field": "LU_CODE",
           "name_field": "LU_DES_TH"}

    @staticmethod
    def _feat(i):
        return {"geometry": {"coordinates": [100.0 + i * 0.1, 13.0]},
                "properties": {"priority": 0.9 - i * 0.01}}

    def _run(self, monkeypatch, codes=None, raises=None, source="default", n=3):
        from routers.recommend import scoring
        fake_ee = MagicMock()
        fake_ee.EEException = ee.EEException
        monkeypatch.setattr(scoring, "ee", fake_ee)
        priority = MagicMock()
        info = {"features": [self._feat(i) for i in range(6)]}
        (priority.addBands.return_value.updateMask.return_value.sample.return_value
         .sort.return_value.limit.return_value.getInfo.return_value) = info
        monkeypatch.setattr(scoring, "_plantable_at_points",
                            lambda c, p: {i: True for i in range(len(c))})
        calls = []

        def fake_codes(cands, src):
            calls.append((len(cands), src))
            if raises:
                raise raises
            return codes

        monkeypatch.setattr(scoring, "ldd_codes_at_points", fake_codes)
        src = self.SRC if source == "default" else source
        z = MagicMock()
        out = scoring.get_top_locations(priority, z, z, z, z, z, z, z, z, n=n,
                                        ldd_source=src)
        return out, calls

    def test_excluded_points_dropped_and_labelled(self, monkeypatch):
        codes = {0: {"code": "U401", "name_th": "a"}, 1: {"code": "A101", "name_th": "b"},
                 2: {"code": "W101", "name_th": "c"}, 3: {"code": "M101", "name_th": "d"},
                 4: {"code": "A101", "name_th": "e"}, 5: {"code": "A101", "name_th": "f"}}
        out, calls = self._run(monkeypatch, codes=codes)
        assert calls[0][0] == 6
        assert len(out) == 3
        assert [round(p["lng"], 1) for p in out] == [100.1, 100.3, 100.4]
        assert all(p["ldd"]["edition_year"] == 2568 for p in out)
        assert out[1]["ldd"]["rule"] == PREFER

    def test_gee_failure_continues_without_ldd(self, monkeypatch):
        out, _ = self._run(monkeypatch, raises=ee.EEException("boom"))
        assert len(out) == 3
        assert all("ldd" not in p for p in out)

    def test_non_ee_error_propagates(self, monkeypatch):
        with pytest.raises(RuntimeError):
            self._run(monkeypatch, raises=RuntimeError("bug"))

    def test_no_source_never_calls_ldd(self, monkeypatch):
        out, calls = self._run(monkeypatch, codes={}, source=None)
        assert calls == [] and len(out) == 3
        assert all("ldd" not in p for p in out)
