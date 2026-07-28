"""Unit tests สำหรับตัวชี้วัดเรือนยอด 30% ของกฎ 3-30-300 (FR-17).

เกณฑ์ 30% มาจาก Konijnendijk (2023) `[R2]` ตรง ๆ · ค่าหลักมาจาก ESA WorldCover
(epoch 2021) ส่วน Dynamic World ทำหน้าที่บอกทิศทางการเปลี่ยนแปลงเท่านั้น —
เหตุผลของการแบ่งบทบาทนี้อยู่ใน docstring ของ canopy.py
ทดสอบเฉพาะ pure helpers (ส่วนที่คุยกับ GEE — canopy_area_bands — ไม่ครอบคลุมที่นี่)
รัน: cd green-area-backend && pytest tests/test_canopy.py -v
"""
import json

from canopy import (CANOPY_TARGET_PCT, DW_MIN_COVERAGE_PCT, TREND_STABLE_PP,
                    WORLDCOVER_EPOCH_YEAR, build_canopy)

KM2 = 1_000_000            # m² ต่อ 1 km²
TOTAL = 100 * KM2          # พื้นที่สมมติ 100 km² — 1 km² = 1%
BASE_YEAR = WORLDCOVER_EPOCH_YEAR


def _canopy(wc_km2=14.6, dw_km2=4.7, dw_base_km2=4.7, coverage=1.0,
            total_m2=TOTAL, year=BASE_YEAR + 3):
    """เรียก build_canopy ด้วยหน่วย km² ที่อ่านง่ายกว่า m² ดิบจาก reduceRegion"""
    def km2(v):
        return None if v is None else v * KM2
    return build_canopy(km2(wc_km2), km2(dw_km2), total_m2 * coverage,
                        km2(dw_base_km2), total_m2, year)


# ── เกณฑ์ผ่าน/ไม่ผ่าน 30% (ค่าหลัก = WorldCover) ─────────────────────────────
class TestTarget:
    def test_target_is_the_published_rule(self):
        assert CANOPY_TARGET_PCT == 30.0

    def test_headline_number_comes_from_worldcover_not_dynamic_world(self):
        """DW ต่ำกว่าจริงในเมือง — ถ้าหลุดมาเป็นค่าหลักเมื่อไร ตัวนี้จะจับได้"""
        out = _canopy(wc_km2=14.6, dw_km2=1.7)
        assert out["canopy_pct"] == 14.6
        assert out["source"] == "ESA WorldCover v200"

    def test_below_target_reports_gap(self):
        out = _canopy(wc_km2=14.6)
        assert out["available"] is True
        assert out["meets_target"] is False
        assert out["gap_pct"] == 15.4
        assert "ต่ำกว่าเกณฑ์ 30%" in out["label"]

    def test_exactly_at_target_passes(self):
        # เกณฑ์คือ "อย่างน้อย 30%" — ค่าที่เท่าเกณฑ์พอดีต้องนับว่าผ่าน
        out = _canopy(wc_km2=30.0)
        assert out["meets_target"] is True
        assert out["gap_pct"] == 0.0

    def test_above_target_reports_zero_gap_not_negative(self):
        out = _canopy(wc_km2=45.0)
        assert out["meets_target"] is True
        assert out["gap_pct"] == 0.0
        assert "ผ่านเกณฑ์ 30%" in out["label"]

    def test_zero_canopy_is_reported_not_treated_as_missing(self):
        out = _canopy(wc_km2=0.0)
        assert out["available"] is True
        assert out["canopy_pct"] == 0.0
        assert out["gap_pct"] == 30.0

    def test_area_reported_in_km2(self):
        assert _canopy(wc_km2=14.6)["canopy_km2"] == 14.6


# ── epoch ของ WorldCover (ค่าหลักไม่ขยับตามปีที่เลือก) ───────────────────────
class TestEpoch:
    def test_offset_from_selected_year_is_reported(self):
        out = _canopy(year=BASE_YEAR + 4)
        assert out["epoch_year"] == BASE_YEAR
        assert out["epoch_offset_years"] == 4
        assert "ไม่ใช่รายปี" in out["note"]

    def test_same_year_as_epoch_does_not_warn(self):
        out = _canopy(year=BASE_YEAR)
        assert out["epoch_offset_years"] == 0
        assert "ไม่ใช่รายปี" not in out["note"]

    def test_canopy_pct_does_not_change_with_year(self):
        """ค่าหลักเป็น epoch เดียว — ปีต่างกันต้องได้เลขเดิม (จึงต้องกำกับ epoch เสมอ)"""
        assert _canopy(year=2018)["canopy_pct"] == _canopy(year=2025)["canopy_pct"]


# ── trend จาก Dynamic World ──────────────────────────────────────────────────
class TestTrend:
    def test_increase_detected(self):
        trend = _canopy(dw_km2=6.0, dw_base_km2=4.5)["trend"]
        assert trend["change_pp"] == 1.5
        assert trend["direction"] == "increase"
        assert "เพิ่มขึ้น" in trend["note"]

    def test_decrease_detected(self):
        trend = _canopy(dw_km2=3.0, dw_base_km2=4.5)["trend"]
        assert trend["change_pp"] == -1.5
        assert trend["direction"] == "decrease"

    def test_small_change_reads_as_stable(self):
        trend = _canopy(dw_km2=4.5 + TREND_STABLE_PP / 2, dw_base_km2=4.5)["trend"]
        assert trend["direction"] == "stable"

    def test_trend_warns_that_level_is_not_trustworthy(self):
        """เหตุผลทั้งหมดที่ DW ไม่ได้เป็นค่าหลัก ต้องติดไปกับตัวเลขเสมอ"""
        assert "ทิศทางการเปลี่ยนแปลง" in _canopy()["trend"]["note"]

    def test_trend_dropped_when_coverage_too_low(self):
        out = _canopy(coverage=(DW_MIN_COVERAGE_PCT - 10) / 100)
        assert out["trend"] is None
        assert out["available"] is True     # ค่าหลักยังใช้ได้ ไม่ขึ้นกับ DW

    def test_trend_kept_when_coverage_just_above_floor(self):
        out = _canopy(coverage=(DW_MIN_COVERAGE_PCT + 10) / 100)
        assert out["trend"]["coverage_pct"] == DW_MIN_COVERAGE_PCT + 10
        assert "ครอบคลุม" in out["trend"]["note"]

    def test_year_without_dynamic_world_keeps_headline_number(self):
        """ปีก่อน 2015 ไม่มี DW — canopy ยังรายงานได้เพราะ WorldCover เป็นค่าคงที่"""
        out = _canopy(dw_km2=None, coverage=0.0, year=2010)
        assert out["trend"] is None
        assert out["available"] is True
        assert out["canopy_pct"] == 14.6


# ── กรณีไม่มีข้อมูล ──────────────────────────────────────────────────────────
class TestUnavailable:
    def test_missing_worldcover_marks_unavailable(self):
        out = _canopy(wc_km2=None)
        assert out["available"] is False
        assert out["canopy_pct"] is None and out["meets_target"] is None

    def test_zero_total_area_does_not_divide_by_zero(self):
        assert build_canopy(0, 0, 0, 0, 0, 2024)["available"] is False


# ── รูปทรง payload ที่ลง jsonb / ส่งกลับ client ──────────────────────────────
class TestPayloadShape:
    def test_keys_are_stable_between_available_and_not(self):
        """frontend อ่านทางเดียวได้ ไม่ต้องเช็คว่า key มีไหมก่อนทุกครั้ง"""
        assert set(_canopy().keys()) == set(_canopy(wc_km2=None).keys())

    def test_json_serialisable_for_jsonb_column(self):
        for out in (_canopy(), _canopy(wc_km2=None), _canopy(coverage=0.0)):
            assert json.loads(json.dumps(out, ensure_ascii=False)) == out

    def test_note_cites_the_rule_and_the_data_epoch(self):
        note = _canopy()["note"]
        assert "3-30-300" in note
        assert str(WORLDCOVER_EPOCH_YEAR) in note
