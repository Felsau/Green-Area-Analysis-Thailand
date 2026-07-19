"""Unit tests สำหรับ ldd.py (provider การใช้ที่ดิน LDD) — pure helpers, ไม่แตะ GEE.

ครอบ: legend 96 ประเภทครบ/ถูกต้อง (l1_value ตกอยู่ใน schema กลาง 1–5) ·
_rollup_by_value รวมรหัสละเอียด → 5 ประเภทหลักถูก · build_detail จัดอันดับ/จัดรูปถูก ·
meta/availability/coverage · การเชื่อมกับ build_summary ของ landuse
รัน: cd green-area-backend && pytest tests/test_ldd.py -v
"""
from landuse import CATEGORY_BY_VALUE, build_summary
from ldd import (build_detail, ldd_meta, ldd_available, ldd_covers,
                 _rollup_by_value, _CODE_TO_ID, _ID_TO_CODE)
from ldd_codes import LDD_LU_CODES

VALID_VALUES = set(CATEGORY_BY_VALUE)  # {1,2,3,4,5}


class TestLegend:
    def test_has_all_codes(self):
        assert len(LDD_LU_CODES) == 96

    def test_every_l1_value_is_a_valid_main_type(self):
        # ทุก LU_CODE ต้องผูกกับประเภทหลัก 1–5 — ไม่งั้น build_detail จะหา color ไม่เจอ
        for code, (l1_value, th, en) in LDD_LU_CODES.items():
            assert l1_value in VALID_VALUES, code
            assert th and en, code

    def test_covers_all_five_main_types(self):
        assert {v for v, *_ in LDD_LU_CODES.values()} == VALID_VALUES

    def test_code_id_is_bijective_1_to_n(self):
        assert sorted(_CODE_TO_ID.values()) == list(range(1, len(LDD_LU_CODES) + 1))
        assert {_ID_TO_CODE[i] for i in _ID_TO_CODE} == set(LDD_LU_CODES)


class TestRollup:
    def test_sums_codes_into_main_types(self):
        # A101 (นาข้าว→2) + A502 (พืชผัก→2) รวมเป็นประเภท 2; U101 (→1) แยก
        by_value = _rollup_by_value({"A101": 3e6, "A502": 1e6, "U101": 5e6})
        assert by_value == {2: 4e6, 1: 5e6}

    def test_result_keys_within_schema(self):
        by_value = _rollup_by_value({c: 1.0 for c in LDD_LU_CODES})
        assert set(by_value) <= VALID_VALUES

    def test_feeds_build_summary_to_five_rows(self):
        # rollup → build_summary ต้องได้ครบ 5 แถวเหมือน provider DW (schema เดียวกัน)
        out = build_summary(_rollup_by_value({"U101": 2e6, "F301": 8e6}))
        assert [c["code"] for c in out["classes"]] == ["U", "A", "F", "W", "M"]


class TestBuildDetail:
    def test_orders_by_area_desc_and_limits_top(self):
        area = {"U101": 5e6, "A101": 9e6, "W101": 1e6}
        out = build_detail(area, top=2)
        assert [d["code"] for d in out] == ["A101", "U101"]  # 9,5 (1 ถูกตัด)

    def test_row_shape_and_color_from_main_type(self):
        out = build_detail({"A101": 4e6}, top=5)
        d = out[0]
        assert d["code"] == "A101" and d["l1_value"] == 2
        assert d["name_th"] == "นาข้าว"
        assert d["color"] == CATEGORY_BY_VALUE[2]["color"]
        assert d["area_km2"] == 4.0 and d["share_pct"] == 100.0

    def test_share_pct_relative_to_total(self):
        out = build_detail({"U101": 3e6, "A101": 1e6}, top=5)
        by_code = {d["code"]: d for d in out}
        assert by_code["U101"]["share_pct"] == 75.0
        assert by_code["A101"]["share_pct"] == 25.0

    def test_empty_input(self):
        assert build_detail({}) == []

    def test_no_division_error_on_zero_area(self):
        out = build_detail({"U101": 0.0}, top=5)
        assert out[0]["share_pct"] == 0


class TestMetaAndCoverage:
    def test_meta_marks_source_ldd_with_edition(self):
        meta = ldd_meta()
        assert meta["source"] == "ldd"
        assert meta["data_year"] == 2566 and meta["data_year_ce"] == 2023
        assert meta["source_label"] and meta["coverage"]

    def test_coverage_gate(self):
        assert ldd_covers("Bangkok Metropolis") is True
        assert ldd_covers("Chiang Mai") is False

    def test_available_reflects_env(self, monkeypatch):
        # ไม่ตั้ง env → provider ปิด (endpoint ตอบ 404 ที่ชัดแทนล่ม)
        monkeypatch.setattr("ldd.LDD_ASSET_ID", None)
        assert ldd_available() is False
        monkeypatch.setattr("ldd.LDD_ASSET_ID", "projects/x/assets/LU_BKK_2566")
        assert ldd_available() is True
