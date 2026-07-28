"""Unit tests สำหรับ NFR-08 — validation ของ green_area_pct เทียบ ESA WorldCover.

เป้าหมายคือ ±10 จุด% (VALIDATION_TARGET_PP) ตามที่ระบุใน REQUIREMENTS.md §4.2
ทดสอบเฉพาะ pure helper (build_validation) — ส่วนที่คุยกับ GEE
(worldcover_green_area_band) ไม่ครอบคลุมที่นี่ เหมือน test_canopy.py
รัน: cd green-area-backend && pytest tests/test_validation.py -v
"""
import json

from validation import (BREAKDOWN_MIN_PP, VALIDATION_TARGET_PP, build_breakdown,
                        build_validation)

KM2 = 1_000_000    # m² ต่อ 1 km²
TOTAL = 100 * KM2  # พื้นที่สมมติ 100 km² — 1 km² = 1 จุด%


def _validation(ndvi_pct=20.0, wc_km2=18.0, year=2021, breakdown=None):
    """wc_km2 บนพื้นที่สมมติ 100 km² → 1 km² = 1% พอดี จึงส่งเป็น pct ได้ตรง"""
    return build_validation(ndvi_pct, wc_km2, year, breakdown=breakdown)


def _sums(**class_km2):
    """สร้าง extra_area_sums จำลอง — key เช่น fn_40=13.1 (หน่วย km² = จุด%)"""
    return {k: v * KM2 for k, v in class_km2.items()}


class TestErrorCalculation:
    def test_ndvi_higher_than_worldcover_is_positive_error(self):
        out = _validation(ndvi_pct=20.0, wc_km2=18.0)
        assert out["ndvi_green_pct"] == 20.0
        assert out["worldcover_green_pct"] == 18.0
        assert out["error_pp"] == 2.0

    def test_ndvi_lower_than_worldcover_is_negative_error(self):
        out = _validation(ndvi_pct=15.0, wc_km2=18.0)
        assert out["error_pp"] == -3.0

    def test_exact_match_has_zero_error(self):
        out = _validation(ndvi_pct=18.0, wc_km2=18.0)
        assert out["error_pp"] == 0.0
        assert out["within_target"] is True


class TestTargetThreshold:
    def test_within_target_passes(self):
        out = _validation(ndvi_pct=25.0, wc_km2=18.0)  # +7 pp
        assert out["within_target"] is True
        assert "ผ่าน" in out["note"]

    def test_exactly_at_target_boundary_passes(self):
        # เกณฑ์คือ "ไม่เกิน ±10 จุด%" ค่าที่เท่าเกณฑ์พอดีต้องนับว่าผ่าน
        out = _validation(ndvi_pct=28.0, wc_km2=18.0)  # +10 pp พอดี
        assert out["error_pp"] == VALIDATION_TARGET_PP
        assert out["within_target"] is True

    def test_beyond_target_fails(self):
        out = _validation(ndvi_pct=29.0, wc_km2=18.0)  # +11 pp
        assert out["within_target"] is False
        assert "ไม่ผ่าน" in out["note"]

    def test_negative_beyond_target_also_fails(self):
        out = _validation(ndvi_pct=6.0, wc_km2=18.0)  # -12 pp
        assert out["within_target"] is False

    def test_target_pp_reported_alongside_result(self):
        assert _validation()["target_pp"] == VALIDATION_TARGET_PP == 10.0


class TestEpochYearNote:
    def test_same_year_as_epoch_does_not_warn(self):
        out = _validation(year=2021)
        assert "epoch" not in out["note"]  # ไม่ต้องมีคำเตือนถ้าปีตรงกัน

    def test_different_year_warns_about_epoch_mismatch(self):
        out = _validation(year=2025)
        assert "epoch" in out["note"]
        assert "2025" in out["note"]

    def test_worldcover_epoch_year_always_reported(self):
        assert _validation(year=2025)["worldcover_epoch_year"] == 2021


class TestUnavailable:
    def test_missing_ndvi_pct_marks_unavailable(self):
        out = build_validation(None, 18.0, 2021)
        assert out["available"] is False
        assert out["error_pp"] is None and out["within_target"] is None

    def test_missing_worldcover_marks_unavailable(self):
        """เกิดได้จริงเมื่อจังหวัดยังไม่ถูก backfill ค่าอ้างอิง — ต้องไม่ระเบิด"""
        out = _validation(wc_km2=None)
        assert out["available"] is False

    def test_zero_total_area_does_not_divide_by_zero(self):
        assert build_breakdown(_sums(fn_40=5.0), 0) is None


class TestBreakdown:
    def test_false_negative_and_false_positive_totalled_separately(self):
        out = build_breakdown(_sums(fn_40=13.1, fn_10=1.0, fp_50=2.0), TOTAL)
        assert out["false_negative_pp"] == 14.1
        assert out["false_positive_pp"] == 2.0

    def test_dominant_is_the_largest_contributor(self):
        out = build_breakdown(_sums(fn_40=13.1, fn_10=1.0, fp_50=2.0), TOTAL)
        assert out["dominant"]["code"] == 40
        assert out["dominant"]["kind"] == "false_negative"
        assert out["dominant"]["pp"] == 13.1

    def test_by_class_sorted_largest_first(self):
        out = build_breakdown(_sums(fn_40=5.0, fn_10=1.0, fp_50=9.0), TOTAL)
        assert [c["pp"] for c in out["by_class"]] == [9.0, 5.0, 1.0]

    def test_classes_are_named_in_thai(self):
        out = build_breakdown(_sums(fn_40=13.1), TOTAL)
        assert "เกษตร" in out["dominant"]["name"]

    def test_negligible_classes_dropped_from_listing_but_kept_in_totals(self):
        """คลาสระดับ noise ไม่ต้องรกตาราง แต่ยอดรวมต้องไม่หาย ไม่งั้นกระทบยอดไม่ลง"""
        tiny = BREAKDOWN_MIN_PP / 2
        out = build_breakdown(_sums(fn_40=5.0, fn_90=tiny), TOTAL)
        assert [c["code"] for c in out["by_class"]] == [40]
        assert out["false_negative_pp"] == round(5.0 + tiny, 1)

    def test_missing_sums_returns_none(self):
        assert build_breakdown({}, TOTAL) is None
        assert build_breakdown(_sums(fn_40=5.0), 0) is None


class TestBreakdownReconciles:
    """หัวใจของการแยกสาเหตุ: ตัวเลขต้องกระทบยอดกันครบ ไม่ใช่ประมาณคนละชุด

        error_pp = net_pp + reference_scale_delta_pp
        net_pp   = Σ false_positive − Σ false_negative

    delta คือส่วนต่างของค่าอ้างอิง WorldCover ระหว่างโดเมน fractional (10 ม.) กับ
    plain (scale วิเคราะห์) — ต้องรายงาน ไม่ใช่ซุกไว้ (ดู validation.py)
    """

    def test_full_identity_holds_when_ndvi_under_reports(self):
        # เคสเกษตร (อำนาจเจริญ ของจริง): NDVI 82.8% · WC fractional 96.9%
        # → error −14.1 · โดเมน plain: WC 97.7% → net −14.9 · delta +0.8
        sums = _sums(fn_40=15.0, fn_10=1.4, fp_50=1.2, fp_60=0.3,
                     worldcover_green_area=96.9, worldcover_green_area_plain=97.7)
        breakdown = build_breakdown(sums, TOTAL)
        out = _validation(ndvi_pct=82.8, wc_km2=96.9, breakdown=breakdown)
        assert breakdown["net_pp"] == -14.9
        assert breakdown["reference_scale_delta_pp"] == 0.8
        assert out["error_pp"] == -14.1
        assert round(breakdown["net_pp"]
                     + breakdown["reference_scale_delta_pp"], 1) == out["error_pp"]

    def test_full_identity_holds_when_ndvi_over_reports(self):
        # เคสเมือง (กรุงเทพฯ): NDVI เขียวกว่า WC → error บวก จาก fp_50 (Built-up)
        sums = _sums(fp_50=16.0, fp_80=1.0, fn_10=0.1,
                     worldcover_green_area=45.1, worldcover_green_area_plain=45.1)
        breakdown = build_breakdown(sums, TOTAL)
        out = _validation(ndvi_pct=62.0, wc_km2=45.1, breakdown=breakdown)
        assert breakdown["net_pp"] == 16.9
        assert breakdown["reference_scale_delta_pp"] == 0.0
        assert round(breakdown["net_pp"]
                     + breakdown["reference_scale_delta_pp"], 1) == out["error_pp"] == 16.9
        assert breakdown["dominant"]["code"] == 50

    def test_delta_is_none_when_reference_terms_missing(self):
        assert build_breakdown(_sums(fn_40=5.0), TOTAL)["reference_scale_delta_pp"] is None

    def test_reference_from_backfill_matches_inline_computation(self):
        """request path ส่งค่าอ้างอิงเป็น pct ที่ backfill ไว้ · สคริปต์คิดสดใส่มาใน sums
        — สองทางต้องให้ผลเท่ากันเป๊ะ ไม่งั้นเลขบนจอกับในรูปเล่มจะไม่ตรงกัน"""
        common = dict(fn_40=15.0, fp_50=1.2, worldcover_green_area_plain=97.7)
        inline = build_breakdown(_sums(**common, worldcover_green_area=96.9), TOTAL)
        backfilled = build_breakdown(_sums(**common), TOTAL, worldcover_green_pct=96.9)
        assert inline == backfilled
        assert backfilled["reference_scale_delta_pp"] == 0.8


class TestBreakdownInNote:
    def test_note_names_the_dominant_cause(self):
        breakdown = build_breakdown(_sums(fn_40=13.1), TOTAL)
        note = _validation(breakdown=breakdown)["note"]
        assert "เกษตร" in note and "13.1" in note

    def test_note_explains_direction_of_the_dominant_cause(self):
        fn_note = _validation(breakdown=build_breakdown(_sums(fn_40=13.1), TOTAL))["note"]
        fp_note = _validation(breakdown=build_breakdown(_sums(fp_50=13.1), TOTAL))["note"]
        assert "WorldCover นับเป็นสีเขียวแต่ NDVI ไม่นับ" in fn_note
        assert "NDVI นับเป็นสีเขียวแต่ WorldCover ไม่นับ" in fp_note

    def test_note_unchanged_when_no_breakdown(self):
        assert "ต้นเหตุหลัก" not in _validation(breakdown=None)["note"]


class TestEndpointHelper:
    """`_build_validation` ของ path จังหวัด — ต้องถอนค่ากลางออกจาก result ก่อน insert"""

    def _result(self, **extra):
        return {"green_area_pct": 82.8, "ndvi_mean": 0.5,
                "extra_area_sums": _sums(fn_40=15.0, fp_50=1.2,
                                         worldcover_green_area_plain=97.7),
                "total_area_m2_raw": TOTAL, **extra}

    def test_raw_fields_are_stripped_from_result(self):
        """ndvi_annual ไม่มีคอลัมน์รองรับสองตัวนี้ — หลุดไปกับ insert = ทั้ง request พัง"""
        from routers.ndvi.endpoints import _build_validation
        result = self._result()
        _build_validation(result, 96.9, 2021)
        assert "extra_area_sums" not in result
        assert "total_area_m2_raw" not in result

    def test_builds_validation_matching_the_headline_error(self):
        from routers.ndvi.endpoints import _build_validation
        out = _build_validation(self._result(), 96.9, 2021)
        assert out["error_pp"] == -14.1
        assert out["breakdown"]["dominant"]["code"] == 40

    def test_returns_none_when_reference_not_backfilled_yet(self):
        """จังหวัดที่ยังไม่รัน backfill — ข้ามเงียบ ๆ ไม่ทำให้ endpoint พัง"""
        from routers.ndvi.endpoints import _build_validation
        result = self._result()
        assert _build_validation(result, None, 2021) is None
        assert "extra_area_sums" not in result   # ยังต้องถอนอยู่ดี

    def test_returns_none_when_sums_missing(self):
        from routers.ndvi.endpoints import _build_validation
        assert _build_validation({"green_area_pct": 82.8}, 96.9, 2021) is None


class TestPayloadShape:
    def test_keys_are_stable_between_available_and_not(self):
        assert set(_validation().keys()) == set(_validation(wc_km2=None).keys())

    def test_json_serialisable_for_reporting(self):
        for out in (_validation(), _validation(wc_km2=None), _validation(ndvi_pct=0.0, wc_km2=0.0)):
            assert json.loads(json.dumps(out, ensure_ascii=False)) == out

    def test_note_cites_the_requirement_and_both_numbers(self):
        note = _validation(ndvi_pct=20.0, wc_km2=18.0)["note"]
        assert "NFR-08" in note
        assert "20.0" in note and "18.0" in note
