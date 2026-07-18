"""Unit tests สำหรับ landuse.py (provider การใช้ที่ดิน) — pure helpers, ไม่แตะ GEE.

ครอบ: schema กลาง 5 ประเภทครบ/ไม่ซ้ำ · mapping DW→LDD ครบทุกคลาส DW ·
build_summary จัดรูป response ถูก (ครบ 5 แถวเสมอ, share รวม ~100, กัน div-zero)
รัน: cd green-area-backend && pytest tests/test_landuse.py -v
"""
from landuse import (LANDUSE_CATEGORIES, LANDUSE_PALETTE, CATEGORY_BY_VALUE,
                     DW_TO_LDD, build_summary, landuse_meta)

# Dynamic World V1 band 'label' มี 9 คลาส (0–8) — ถ้า DW เพิ่มคลาส mapping ต้องตาม
DW_CLASS_COUNT = 9


class TestSchema:
    def test_five_categories_with_contiguous_values(self):
        assert [c["value"] for c in LANDUSE_CATEGORIES] == [1, 2, 3, 4, 5]

    def test_codes_unique_and_match_ldd_main_types(self):
        assert [c["code"] for c in LANDUSE_CATEGORIES] == ["U", "A", "F", "W", "M"]

    def test_palette_follows_category_order(self):
        assert LANDUSE_PALETTE == [c["color"] for c in LANDUSE_CATEGORIES]

    def test_category_by_value_lookup(self):
        assert CATEGORY_BY_VALUE[3]["code"] == "F"
        # 0 = "ไม่ทราบ" (unmask ใน scoring) — ต้องไม่ใช่ประเภทจริง
        assert 0 not in CATEGORY_BY_VALUE


class TestDwMapping:
    def test_covers_every_dw_class(self):
        assert sorted(DW_TO_LDD) == list(range(DW_CLASS_COUNT))

    def test_targets_are_valid_categories(self):
        assert set(DW_TO_LDD.values()) <= set(CATEGORY_BY_VALUE)

    def test_key_classes_map_as_documented(self):
        assert DW_TO_LDD[6] == CATEGORY_BY_VALUE[DW_TO_LDD[6]]["value"] == 1  # built → U
        assert CATEGORY_BY_VALUE[DW_TO_LDD[4]]["code"] == "A"   # crops → เกษตร
        assert CATEGORY_BY_VALUE[DW_TO_LDD[1]]["code"] == "F"   # trees → ป่าไม้
        assert CATEGORY_BY_VALUE[DW_TO_LDD[0]]["code"] == "W"   # water → พื้นที่น้ำ


class TestBuildSummary:
    def test_all_categories_present_even_when_missing(self):
        out = build_summary({1: 2_000_000, 3: 8_000_000})  # แค่ U กับ F
        assert [c["code"] for c in out["classes"]] == ["U", "A", "F", "W", "M"]
        by_code = {c["code"]: c for c in out["classes"]}
        assert by_code["A"]["area_km2"] == 0
        assert by_code["A"]["share_pct"] == 0

    def test_share_and_area_math(self):
        out = build_summary({1: 2_000_000, 3: 8_000_000})
        by_code = {c["code"]: c for c in out["classes"]}
        assert out["total_km2"] == 10.0
        assert by_code["U"] == {"code": "U", "name_th": "ชุมชนและสิ่งปลูกสร้าง",
                                "name_en": "Urban and built-up land",
                                "color": "e5534b", "area_km2": 2.0, "share_pct": 20.0}
        assert by_code["F"]["share_pct"] == 80.0

    def test_share_sums_to_about_100(self):
        out = build_summary({1: 1e6, 2: 2e6, 3: 3e6, 4: 4e6, 5: 5e6})
        assert abs(sum(c["share_pct"] for c in out["classes"]) - 100) < 0.5

    def test_empty_input_no_division_error(self):
        out = build_summary({})
        assert out["total_km2"] == 0
        assert all(c["share_pct"] == 0 for c in out["classes"])

    def test_ignores_unknown_values(self):
        # ค่า 0 (ไม่ทราบ) หรือค่าแปลกปลอมจาก grouped reduce ต้องไม่ปนใน total
        out = build_summary({0: 5_000_000, 1: 1_000_000})
        assert out["total_km2"] == 1.0


class TestMeta:
    def test_meta_carries_source_and_data_year(self):
        meta = landuse_meta(2024)
        assert meta["source"] == "dynamic_world"
        assert meta["data_year"] == 2024
        assert "source_label" in meta
