"""Unit tests สำหรับตัวชี้วัดคุณภาพ/ความไม่แน่นอนของ NDVI composite (NFR-07).

เกณฑ์ที่ทดสอบอ้างอิงมาตรฐานภายนอก — GCOS-245 (2σ ≤ 5% Goal / ≤ 10% Threshold)
และนิยามฤดูกาลของกรมอุตุนิยมวิทยา · ทดสอบเฉพาะ pure helpers (ส่วนที่คุยกับ GEE
ใน _compute_ndvi_annual ไม่ครอบคลุมที่นี่)
รัน: cd green-area-backend && pytest tests/test_ndvi_quality.py -v
"""
import json
from datetime import datetime, timedelta, timezone

from routers.ndvi.compute import (
    S2_CLOUD_FILTER_PCT, S2_CLOUD_FILTER_FALLBACK_PCT,
    SENSOR_NDVI_SD, MEDIAN_SE_FACTOR, GCOS_GOAL_PCT, GCOS_THRESHOLD_PCT,
    season_of, summarize_acquisitions, composite_uncertainty, grade_uncertainty,
    build_data_quality)


def _ms(year, month, day=15):
    """epoch millis แบบเดียวกับ system:time_start ของ GEE (UTC)"""
    return int(datetime(year, month, day, 3, 30, tzinfo=timezone.utc).timestamp() * 1000)


# ── ฤดูกาลตามนิยาม TMD ───────────────────────────────────────────────────────
class TestSeasonOf:
    def test_boundaries_follow_tmd_mid_month_rule(self):
        assert season_of(2, 15) == "ฤดูหนาว"    # ยังเป็นฤดูหนาวถึงกลาง ก.พ.
        assert season_of(2, 16) == "ฤดูร้อน"
        assert season_of(5, 15) == "ฤดูร้อน"
        assert season_of(5, 16) == "ฤดูฝน"
        assert season_of(10, 15) == "ฤดูฝน"
        assert season_of(10, 16) == "ฤดูหนาว"

    def test_winter_wraps_new_year(self):
        assert season_of(12, 31) == "ฤดูหนาว"
        assert season_of(1, 1) == "ฤดูหนาว"


# ── summarize_acquisitions ───────────────────────────────────────────────────
class TestSummarizeAcquisitions:
    def test_empty_collection(self):
        out = summarize_acquisitions([])
        assert out["first_date"] is None and out["last_date"] is None
        assert out["months_covered"] == 0
        assert out["months_missing"] == list(range(1, 13))
        assert out["seasons_covered"] == []
        assert out["seasonally_representative"] is False

    def test_full_year_covers_all_three_seasons(self):
        out = summarize_acquisitions([_ms(2024, m) for m in range(1, 13)])
        assert out["months_covered"] == 12
        assert out["months_missing"] == []
        assert out["seasons_missing"] == []
        assert out["seasonally_representative"] is True
        assert out["first_date"] == "2024-01-15"
        assert out["last_date"] == "2024-12-15"

    def test_missing_rainy_season_is_not_representative(self):
        # ภาคใต้/ฤดูฝน — ไม่มีภาพผ่านเกณฑ์เลยช่วง มิ.ย.–ก.ย.
        times = [_ms(2024, m) for m in (1, 2, 3, 4, 11, 12)]
        out = summarize_acquisitions(times)
        assert out["seasons_missing"] == ["ฤดูฝน"]
        assert out["seasonally_representative"] is False

    def test_many_months_can_still_miss_a_season(self):
        # 8 เดือนแต่ทุกภาพอยู่นอกฤดูฝน (พ.ค. ต้นเดือน / ต.ค. ปลายเดือน) → นับเดือน
        # อย่างเดียวจะดู "ครอบคลุมดี" อย่างเข้าใจผิด แต่ฤดูฝนไม่มีภาพเลย
        times = ([_ms(2024, m) for m in (1, 2, 3, 4, 11, 12)]
                 + [_ms(2024, 5, 10), _ms(2024, 10, 20)])
        out = summarize_acquisitions(times)
        assert out["months_covered"] == 8
        assert out["seasons_missing"] == ["ฤดูฝน"]

    def test_unsorted_input_still_finds_span(self):
        times = [_ms(2024, 7, 20), _ms(2024, 2, 3), _ms(2024, 11, 28)]
        out = summarize_acquisitions(times)
        assert out["first_date"] == "2024-02-03"
        assert out["last_date"] == "2024-11-28"

    def test_past_year_is_year_complete(self):
        out = summarize_acquisitions([_ms(2024, m) for m in range(1, 13)])
        assert out["year_complete"] is True

    def test_current_year_is_not_year_complete(self):
        # ปีปัจจุบัน (ยังไม่ถึง 31 ธ.ค.) ต้องไม่ถูกนับว่า "จบปีแล้ว" แม้ภาพจะตกครบ
        # ทั้ง 3 หน้าต่างฤดู — เข้าใจผิดว่าข้อมูลทั้งปีสมบูรณ์ได้ถ้าไม่แยกสถานะนี้ไว้
        now = datetime.now(timezone.utc)
        recent_ms = int((now - timedelta(days=1)).timestamp() * 1000)
        out = summarize_acquisitions([recent_ms])
        assert out["year_complete"] is False

    def test_empty_collection_is_year_complete(self):
        # ไม่มีภาพเลย = ไม่มีปีให้บอกว่า "ยังไม่จบ" — ค่า default ต้องไม่ไป trigger
        # คำเตือน "ปีนี้ยังไม่จบ" ซ้ำกับข้อความ "ไม่มีภาพ" ที่ชัดเจนกว่าอยู่แล้ว
        assert summarize_acquisitions([])["year_complete"] is True


# ── ความไม่แน่นอน (standard error ของ median) ────────────────────────────────
class TestCompositeUncertainty:
    def test_matches_median_standard_error_formula(self):
        u = composite_uncertainty(0.10, 25)
        assert abs(u - MEDIAN_SE_FACTOR * 0.10 / 5) < 1e-9

    def test_more_observations_lower_uncertainty(self):
        assert composite_uncertainty(0.10, 100) < composite_uncertainty(0.10, 25)

    def test_sensor_floor_applies_when_measured_sd_is_smaller(self):
        # σ ที่วัดได้ต่ำกว่าความแม่นของเซนเซอร์ → ใช้พื้น SENSOR_NDVI_SD
        assert composite_uncertainty(0.001, 16) == composite_uncertainty(SENSOR_NDVI_SD, 16)

    def test_single_observation_is_not_reported_as_perfect(self):
        # n=1 → σ ที่วัดได้เป็น 0 เสมอ ถ้าไม่มีพื้นเซนเซอร์จะกลายเป็น "แม่นสมบูรณ์"
        u = composite_uncertainty(0.0, 1)
        assert u == MEDIAN_SE_FACTOR * SENSOR_NDVI_SD
        assert grade_uncertainty(u, 0.24)[0] == "below"

    def test_handles_none_from_reduce_region(self):
        assert composite_uncertainty(None, None) > 0


# ── การจัดระดับตามเกณฑ์ GCOS ────────────────────────────────────────────────
class TestGradeUncertainty:
    def test_goal_when_within_5_percent(self):
        ndvi = 0.60
        u = (GCOS_GOAL_PCT / 100) * ndvi / 2      # 2σ = 5% พอดี
        level, rel = grade_uncertainty(u, ndvi)
        assert level == "goal"
        assert abs(rel - GCOS_GOAL_PCT) < 1e-9

    def test_threshold_between_5_and_10_percent(self):
        ndvi = 0.60
        u = (0.08 * ndvi) / 2                     # 2σ = 8%
        assert grade_uncertainty(u, ndvi)[0] == "threshold"

    def test_below_when_worse_than_threshold(self):
        ndvi = 0.20
        u = (0.15 * ndvi) / 2                     # 2σ = 15%
        level, rel = grade_uncertainty(u, ndvi)
        assert level == "below"
        assert rel > GCOS_THRESHOLD_PCT

    def test_same_absolute_error_is_stricter_on_low_ndvi(self):
        # เกณฑ์ GCOS เป็นสัดส่วนของค่า — เมือง (NDVI ต่ำ) จึงผ่านยากกว่าป่าโดยธรรมชาติ
        u = 0.02
        assert grade_uncertainty(u, 0.70)[1] < grade_uncertainty(u, 0.20)[1]

    def test_zero_ndvi_does_not_divide_by_zero(self):
        # ต้องคืน None ไม่ใช่ inf — json.dumps(inf) ได้ `Infinity` ที่ jsonb/JSON ปฏิเสธ
        level, rel = grade_uncertainty(0.01, 0)
        assert level == "below"
        assert rel is None


# ── build_data_quality ───────────────────────────────────────────────────────
class TestBuildDataQuality:
    def test_composes_full_record(self):
        times = [_ms(2024, m) for m in range(1, 13)]
        dq = build_data_quality(times, 48.0, 12, 0.09, 0.58, S2_CLOUD_FILTER_PCT)
        assert dq["image_count"] == 12
        assert dq["cloud_filter_pct"] == S2_CLOUD_FILTER_PCT
        assert dq["clear_obs_mean"] == 48.0
        assert dq["clear_obs_min"] == 12
        assert dq["seasonally_representative"] is True
        assert dq["uncertainty"] > 0
        assert dq["level"] in ("goal", "threshold")
        assert "GCOS" in dq["note"]
        assert "ครบทั้ง 3 ฤดู" in dq["note"]

    def test_sparse_year_is_below_threshold(self):
        dq = build_data_quality([_ms(2016, 4, 12)], 1, 0, 0.0, 0.24,
                                S2_CLOUD_FILTER_PCT)
        assert dq["level"] == "below"
        assert dq["seasonally_representative"] is False
        assert "ฤดูฝน" in dq["note"]

    def test_handles_missing_reduce_results(self):
        # reduceRegion คืน None ได้ถ้า band ว่างทั้งพื้นที่ — ต้องไม่ระเบิด
        dq = build_data_quality([_ms(2024, 5)], None, None, None, 0.3,
                                S2_CLOUD_FILTER_PCT)
        assert dq["clear_obs_mean"] == 0
        assert dq["clear_obs_min"] == 0
        assert dq["uncertainty"] > 0

    def test_note_mentions_fallback_threshold(self):
        dq = build_data_quality([_ms(2024, m) for m in (1, 6, 11)], 6, 1, 0.08, 0.4,
                                S2_CLOUD_FILTER_FALLBACK_PCT)
        assert f"< {S2_CLOUD_FILTER_FALLBACK_PCT}%" in dq["note"]
        assert f"< {S2_CLOUD_FILTER_PCT}%" in dq["note"]   # บอกเกณฑ์ปกติด้วย

    def test_water_only_area_stays_json_serialisable(self):
        # polygon ที่เป็นน้ำทั้งผืน → ndvi_mean = 0 · ต้องไม่มี inf/NaN หลุดลง jsonb
        dq = build_data_quality([_ms(2024, 3), _ms(2024, 8)], 10, 4, 0.02, 0.0,
                                S2_CLOUD_FILTER_PCT)
        assert dq["uncertainty_2sigma_pct"] is None
        assert json.dumps(dq)          # ระเบิดถ้ามี Infinity
        assert "GCOS ไม่ได้" in dq["note"]

    def test_empty_year_is_level_none(self):
        dq = build_data_quality([], 0, 0, 0, 0, S2_CLOUD_FILTER_FALLBACK_PCT)
        assert dq["level"] == "none"
        assert dq["image_count"] == 0
        assert dq["first_date"] is None
        assert dq["uncertainty"] is None

    def test_in_progress_year_note_warns_numbers_will_shift(self):
        # ครบ 3 ฤดูตามนิยาม (มีภาพตกในหน้าต่างแต่ละฤดูบ้าง) แต่ปียังไม่จบจริง —
        # note ต้องเตือนแยกจาก "มีภาพครบทั้ง 3 ฤดู" ไม่ให้อ่านว่าข้อมูลทั้งปีสมบูรณ์
        now = datetime.now(timezone.utc)
        recent_ms = int((now - timedelta(days=1)).timestamp() * 1000)
        times = [_ms(now.year, 2), _ms(now.year, 6)] + [recent_ms]
        dq = build_data_quality(times, 20, 5, 0.05, 0.5, S2_CLOUD_FILTER_PCT)
        assert dq["year_complete"] is False
        assert "ยังไม่จบ" in dq["note"]

    def test_past_full_year_note_has_no_in_progress_warning(self):
        dq = build_data_quality([_ms(2024, m) for m in range(1, 13)], 48.0, 12,
                                0.09, 0.58, S2_CLOUD_FILTER_PCT)
        assert dq["year_complete"] is True
        assert "ยังไม่จบ" not in dq["note"]
