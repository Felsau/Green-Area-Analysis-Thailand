"""Unit tests สำหรับ gee_utils — ส่วนที่เป็น logic ล้วน ไม่ต่อ GEE จริง
รัน: cd green-area-backend && pytest tests/test_gee_utils.py -v

`reduce_lst` สร้าง ee.Reducer ตอนถูกเรียก จึงต้องสวม ee ปลอมให้ก่อน (ไม่งั้นต้อง
ee.Initialize ซึ่งทำให้เทสต์ต้องมี credential + ยิงเน็ต)
"""
import os

import pytest

import gee_utils
from gee_utils import _LANDSAT_CLOUD_BITMASK, reduce_lst


class _FakeReducer:
    """ee.Reducer ปลอม — combine() คืนตัวเองเพื่อให้ chain ต่อได้เรื่อย ๆ"""
    def combine(self, *args, **kwargs):
        return self


class _FakeReducerFactory:
    mean = staticmethod(lambda: _FakeReducer())
    min = staticmethod(lambda: _FakeReducer())
    max = staticmethod(lambda: _FakeReducer())


class _FakeEe:
    Reducer = _FakeReducerFactory


class _FakeReduceResult:
    def __init__(self, stats):
        self._stats = stats

    def getInfo(self):
        return self._stats


class _FakeImage:
    def __init__(self, stats):
        self._stats = stats

    def reduceRegion(self, **kwargs):
        return _FakeReduceResult(self._stats)


class _FakeCol:
    def __init__(self, stats):
        self._stats = stats

    def median(self):
        return _FakeImage(self._stats)


@pytest.fixture
def fake_ee(monkeypatch):
    monkeypatch.setattr(gee_utils, "ee", _FakeEe)


class TestReduceLst:
    def test_rounds_to_two_decimals(self, fake_ee):
        col = _FakeCol({"LST_mean": 31.4159, "LST_min": 24.111, "LST_max": 42.987})
        assert reduce_lst(col, geom=None, scale=100) == (31.42, 24.11, 42.99)

    # regression: เดิมใช้ `stats.get(...) or 0` ทำให้ "ไม่มีข้อมูล" กลายเป็น 0.0 °C
    # ซึ่งหน้าเว็บแสดงเป็นค่าที่วัดได้จริง (ดู degC ใน StatsTab.js ฝั่ง frontend)
    def test_missing_keys_return_none_not_zero(self, fake_ee):
        col = _FakeCol({})
        assert reduce_lst(col, geom=None, scale=100) == (None, None, None)

    def test_none_value_stays_none_per_field(self, fake_ee):
        col = _FakeCol({"LST_mean": 30.0, "LST_min": None, "LST_max": 40.0})
        assert reduce_lst(col, geom=None, scale=100) == (30.0, None, 40.0)

    # 0.0 °C เป็นค่าที่วัดได้จริง (แม้แทบเป็นไปไม่ได้ในไทย) ต้องไม่ถูกกลบเป็น None
    def test_zero_celsius_is_kept_as_a_value(self, fake_ee):
        col = _FakeCol({"LST_mean": 0.0, "LST_min": 0.0, "LST_max": 0.0})
        assert reduce_lst(col, geom=None, scale=100) == (0.0, 0.0, 0.0)


class TestLandsatCloudBitmask:
    # Landsat C2 L2 QA_PIXEL: bit 1 Dilated Cloud · 2 Cirrus · 3 Cloud · 4 Cloud Shadow
    # เดิม mask แค่ bit 3/4 → ขอบเมฆกับเมฆบางรั่วเข้า median ของ LST (เมฆเย็นกว่าผิวดิน)
    def test_covers_all_four_cloud_bits(self):
        assert _LANDSAT_CLOUD_BITMASK == (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4)
        assert _LANDSAT_CLOUD_BITMASK == 0b11110

    def test_leaves_non_cloud_bits_alone(self):
        # bit 0 Fill · 5 Snow · 6 Clear · 7 Water — ไม่ใช่เมฆ ต้องไม่ถูก mask ที่นี่
        for bit in (0, 5, 6, 7):
            assert _LANDSAT_CLOUD_BITMASK & (1 << bit) == 0

    def test_bit_list_matches_bitmask(self):
        assert gee_utils._LANDSAT_CLOUD_BITS == (1, 2, 3, 4)


# เกณฑ์เมฆต้องนิยามที่เดียว
# เดิมค่านี้กระจายอยู่ 6 จุดและ drift จนไม่ตรงกัน (20% ที่ NDVI รายปี · 80% ที่
# ndvi_deficit ของคะแนนความสำคัญ/urban/tiles/thumbs/กราฟรายเดือน) → ค่าที่หน้าเว็บ
# แสดง กับค่าที่ระบบใช้ตัดสินว่า "ขาดต้นไม้" มาจาก composite คนละชุด · ชุดนี้กันไม่ให้
# มีใครเขียน filter เองอีกโดยไม่ผ่าน gee_utils.s2_clean_collection
class TestCloudFilterIsSingleSourced:
    FILTER_KEY = "CLOUDY_PIXEL_PERCENTAGE"

    def _py_sources(self):
        import os
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        skip = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "tests"}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for fn in filenames:
                if fn.endswith(".py"):
                    yield os.path.join(dirpath, fn)

    def test_only_gee_utils_filters_on_cloud_percentage(self):
        import io
        offenders = []
        for path in self._py_sources():
            if os.path.basename(path) == "gee_utils.py":
                continue
            with io.open(path, encoding="utf-8") as f:
                if self.FILTER_KEY in f.read():
                    offenders.append(os.path.relpath(path))
        assert offenders == [], (
            "ต้องเรียก gee_utils.s2_clean_collection แทนการ filter เมฆเอง: "
            + ", ".join(offenders))

    def test_fallback_is_looser_than_primary(self):
        from gee_utils import S2_CLOUD_FILTER_FALLBACK_PCT, S2_CLOUD_FILTER_PCT
        assert 0 < S2_CLOUD_FILTER_PCT < S2_CLOUD_FILTER_FALLBACK_PCT <= 100

    def test_ndvi_compute_reexports_the_same_constants(self):
        # build_data_quality รายงานค่านี้ให้ผู้ใช้ — ต้องเป็นตัวเดียวกับที่ filter จริง
        from routers.ndvi import compute
        import gee_utils
        assert compute.S2_CLOUD_FILTER_PCT is gee_utils.S2_CLOUD_FILTER_PCT
        assert (compute.S2_CLOUD_FILTER_FALLBACK_PCT
                is gee_utils.S2_CLOUD_FILTER_FALLBACK_PCT)


# เกณฑ์คะแนน "ควรปลูกจริง" — ตัวคูณของทุกตัวเลขผลกระทบ
# วัดจริง 15 ก.ย. 2569: ที่ 0.5 ขอนแก่นผ่านเกณฑ์แค่ 0.13% ของพื้นที่ที่ปลูกได้
# (9.3 จาก 7,420 km²) เพราะ 0.5 สูงกว่าเปอร์เซ็นไทล์ที่ 99 ของจังหวัดชนบททุกแห่ง
class TestPriorityThreshold:
    def test_below_observed_p99_of_rural_provinces(self):
        from impact import PRIORITY_THRESHOLD
        # p99 ที่วัดได้: น่าน 0.420 · ขอนแก่น 0.428 · เชียงใหม่ 0.459 — เกณฑ์ต้องต่ำกว่า
        # ค่าต่ำสุดในกลุ่มนี้ ไม่งั้นจังหวัดชนบทจะไม่เหลือพื้นที่ให้แนะนำเลย
        assert PRIORITY_THRESHOLD < 0.420

    def test_not_so_low_that_it_selects_most_of_the_land(self):
        from impact import PRIORITY_THRESHOLD
        # p50 ที่วัดได้อยู่ราว 0.20–0.24 — เกณฑ์ต้องสูงกว่าค่ากลางอย่างชัดเจน
        # ไม่งั้น "ลำดับความสำคัญ" จะกลายเป็น "เกือบทุกที่"
        assert PRIORITY_THRESHOLD > 0.25

    def test_single_source_of_truth(self):
        from impact import IMPACT_DEFAULTS, PRIORITY_THRESHOLD
        assert IMPACT_DEFAULTS["priority_threshold"] == PRIORITY_THRESHOLD

    def test_response_carries_the_caveat(self):
        from impact import PRIORITY_THRESHOLD, estimate_impact
        meth = estimate_impact(1_000_000, [])["methodology"]
        assert meth["priority_threshold"] == PRIORITY_THRESHOLD
        note = meth["priority_threshold_note"]
        # ต้องบอกทั้ง "ไม่ใช่พื้นที่ทั้งหมด" และ "ไม่ได้มาจากงานวิจัย"
        assert "ไม่ใช่พื้นที่ที่ปลูกได้ทั้งหมด" in note
        assert "ไม่ได้มาจากงานวิจัย" in note
