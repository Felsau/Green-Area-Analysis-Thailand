"""Unit tests สำหรับ site-metric table routing (routers.recommend.endpoints)
ไม่แตะ DB จริง — fake supabase client บันทึกชื่อตารางที่ถูก query
รัน: cd green-area-backend && pytest tests/test_recommend_metrics.py -v

ครอบ fix: district recommend ต้องอ่าน NDVI/LST จากตาราง *ระดับอำเภอ*
(ไม่ใช่ค่าเฉลี่ยทั้งจังหวัด) เพื่อจัดอันดับพันธุ์ไม้ตามสภาพอำเภอจริง
"""
from types import SimpleNamespace

from routers.recommend.endpoints import _metric_tables, _site_metrics


# _metric_tables (pure routing)
class TestMetricTables:
    def test_province_level_uses_province_tables(self):
        assert _metric_tables(None) == ("province_lst_annual", "ndvi_annual")

    def test_district_level_uses_district_tables(self):
        assert _metric_tables("Mueang") == ("district_lst_annual", "district_ndvi_annual")


# _site_metrics (query routing via fake client)
class _FakeQuery:
    """บันทึก eq() filters + คืน data ว่าง (พอสำหรับเช็ค routing)"""
    def __init__(self, sink):
        self._sink = sink

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._sink["eq"][col] = val
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class _FakeClient:
    def __init__(self, sink):
        self._sink = sink

    def table(self, name):
        self._sink["tables"].append(name)
        return _FakeQuery(self._sink)


def _patch_supa(monkeypatch):
    sink = {"tables": [], "eq": {}}
    import routers.recommend.endpoints as ep
    monkeypatch.setattr(ep, "supa_call", lambda fn, **kw: fn(_FakeClient(sink)))
    return sink


class TestSiteMetricsRouting:
    def test_district_queries_district_tables_with_district_filter(self, monkeypatch):
        sink = _patch_supa(monkeypatch)
        _site_metrics("Chiang Mai", "Mueang Chiang Mai", 2024)
        assert "district_lst_annual" in sink["tables"]
        assert "district_ndvi_annual" in sink["tables"]
        # district path ต้อง filter ด้วย district ด้วย (ไม่งั้นได้แถวมั่ว)
        assert sink["eq"].get("district") == "Mueang Chiang Mai"
        assert sink["eq"].get("province") == "Chiang Mai"

    def test_province_queries_province_tables_without_district_filter(self, monkeypatch):
        sink = _patch_supa(monkeypatch)
        _site_metrics("Chiang Mai", None, 2024)
        assert "province_lst_annual" in sink["tables"]
        assert "ndvi_annual" in sink["tables"]
        assert "district" not in sink["eq"]   # province path ไม่ filter district

    def test_returns_none_pair_when_cache_empty(self, monkeypatch):
        _patch_supa(monkeypatch)   # execute() คืน data=[] เสมอ
        assert _site_metrics("Chiang Mai", None, 2024) == (None, None)

    def test_swallows_db_errors_to_none(self, monkeypatch):
        import routers.recommend.endpoints as ep
        def _boom(fn, **kw):
            raise RuntimeError("db down")
        monkeypatch.setattr(ep, "supa_call", _boom)
        # DB ล่ม → คืน (None, None) เพื่อให้ species fallback ลำดับภาค (ไม่ทำ endpoint พัง)
        assert _site_metrics("Chiang Mai", "Mueang", 2024) == (None, None)
