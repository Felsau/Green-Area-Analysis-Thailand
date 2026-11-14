"""Endpoint tests — ใช้ FastAPI TestClient + mock supa_call
รัน: cd green-area-backend && pytest tests/test_endpoints.py -v

mock ทุก call ไป Supabase เพื่อไม่ต้องใช้ DB จริงตอน test
GEE ไม่ถูกแตะใน endpoint set นี้ (compute หนักอยู่ใน /ndvi/* /lst/*)
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


def _fake_response(data, count=None):
    """จำลอง APIResponse ที่ supabase-py คืน — .data + .count (count="exact" query)
    count default = len(data) เพื่อให้ count-only endpoint (เช่น GET /) ใช้ได้"""
    return SimpleNamespace(data=data, count=len(data) if count is None else count)


@pytest.fixture
def client(monkeypatch):
    """TestClient ที่ patch ADMIN_TOKEN + supa_call ให้ไม่แตะ external

    override require_user ให้คืน fake user เสมอ (ไม่ต้องปลอม JWT/แตะ Supabase
    Auth จริงในเทสต์เหล่านี้ — เทสต์ endpoint ชุดนี้เช็ค business logic ไม่ใช่ auth
    เอง) · ทดสอบพฤติกรรม require_user/require_admin_or_user เองแยกใน
    test_auth_dependencies.py"""
    import main
    from dependencies import require_user
    monkeypatch.setattr("dependencies.ADMIN_TOKEN", "test-token")
    main.app.dependency_overrides[require_user] = lambda: {"id": "test-user-id", "email": "test@example.com"}
    yield TestClient(main.app), main
    main.app.dependency_overrides.pop(require_user, None)


# GET /
class TestRoot:
    def test_returns_status_message_and_counts(self, client, monkeypatch):
        c, main = client
        monkeypatch.setattr(main, "supa_call",
            lambda fn, **kw: _fake_response([{"province": "P", "year": 2024}] * 3))

        r = c.get("/")
        assert r.status_code == 200
        d = r.json()
        assert "Green Area API" in d["message"]
        assert d["cached_annual"] == 3
        assert d["cached_monthly"] == 3


# GET /compare
class TestCompare:
    def test_empty_provinces_returns_400(self, client):
        c, _ = client
        r = c.get("/compare?provinces=")
        assert r.status_code == 400
        assert "อย่างน้อย" in r.json()["detail"]

    def test_too_many_provinces_returns_400(self, client):
        # input cap — กัน abuse ที่ส่ง list ยาว (เช็คก่อน whitelist → 400 ไม่ใช่ 404)
        c, _ = client
        many = ",".join(f"P{i}" for i in range(60))
        r = c.get(f"/compare?provinces={many}")
        assert r.status_code == 400
        assert "สูงสุด" in r.json()["detail"]

    def test_unknown_province_returns_404(self, client):
        c, _ = client
        r = c.get("/compare?provinces=NotAProvince")
        assert r.status_code == 404
        assert "NotAProvince" in r.json()["detail"]

    def test_year_out_of_range_returns_422(self, client):
        # ใช้จังหวัดที่มีจริง (ตัวแรกใน geometry dict) เพื่อให้ผ่าน whitelist
        # แต่ year=1500 อยู่นอก YEAR_MIN/MAX → FastAPI raise 422 ก่อน
        c, _ = client
        from dependencies import PROVINCE_GEOMETRIES
        sample = next(iter(PROVINCE_GEOMETRIES))
        r = c.get(f"/compare?provinces={sample}&year=1500")
        assert r.status_code == 422

    def test_valid_province_returns_data(self, client, monkeypatch):
        c, main = client
        from dependencies import PROVINCE_GEOMETRIES
        sample = next(iter(PROVINCE_GEOMETRIES))
        monkeypatch.setattr(main, "supa_call",
            lambda fn, **kw: _fake_response([{
                "province": sample, "ndvi_mean": 0.45,
                "green_area_pct": 35.0, "green_area_km2": 1200,
                "green_area_m2_per_person": 12.5,
            }]))

        r = c.get(f"/compare?provinces={sample}")
        assert r.status_code == 200
        d = r.json()
        assert len(d["data"]) == 1
        assert d["data"][0]["available"] is True
        assert d["data"][0]["ndvi_mean"] == 0.45

    def test_missing_province_marked_unavailable(self, client, monkeypatch):
        """จังหวัดที่ขอแต่ไม่มี row ใน DB → available=False (ไม่ใช่ 404)"""
        c, main = client
        from dependencies import PROVINCE_GEOMETRIES
        sample = next(iter(PROVINCE_GEOMETRIES))
        monkeypatch.setattr(main, "supa_call",
            lambda fn, **kw: _fake_response([]))  # DB ว่าง

        r = c.get(f"/compare?provinces={sample}")
        assert r.status_code == 200
        assert r.json()["data"][0]["available"] is False


# DELETE /cache/{province_name} — fix #1
class TestClearProvinceCache:
    def test_no_token_returns_401(self, client):
        c, _ = client
        from dependencies import PROVINCE_GEOMETRIES
        sample = next(iter(PROVINCE_GEOMETRIES))
        r = c.delete(f"/cache/{sample}")
        assert r.status_code == 401

    def test_wrong_token_returns_401(self, client):
        c, _ = client
        from dependencies import PROVINCE_GEOMETRIES
        sample = next(iter(PROVINCE_GEOMETRIES))
        r = c.delete(f"/cache/{sample}", headers={"X-Admin-Token": "wrong"})
        assert r.status_code == 401

    def test_unknown_province_returns_404(self, client):
        """fix #1: admin พิมพ์ผิด → 404 ไม่ใช่ลบ 0 row เงียบๆ"""
        c, _ = client
        r = c.delete("/cache/NotAProvince",
                     headers={"X-Admin-Token": "test-token"})
        assert r.status_code == 404
        assert "NotAProvince" in r.json()["detail"]

    def test_valid_province_clears_all_tables(self, client, monkeypatch):
        c, main = client
        from dependencies import PROVINCE_GEOMETRIES
        sample = next(iter(PROVINCE_GEOMETRIES))
        calls = []
        monkeypatch.setattr(main, "supa_call",
            lambda fn, **kw: calls.append(fn) or _fake_response([]))

        r = c.delete(f"/cache/{sample}",
                     headers={"X-Admin-Token": "test-token"})
        assert r.status_code == 200
        assert sample in r.json()["message"]
        # ต้องลบครบทุกตารางใน CACHE_TABLES
        assert len(calls) == len(main.CACHE_TABLES)


# GET /cache
class TestCache:
    def test_returns_annual_and_monthly(self, client, monkeypatch):
        c, main = client
        monkeypatch.setattr(main, "supa_call",
            lambda fn, **kw: _fake_response([{"province": "P", "year": 2024}]))

        r = c.get("/cache")
        assert r.status_code == 200
        d = r.json()
        assert "annual" in d and "monthly" in d
        assert d["truncated"] is False

    def test_flags_truncation_at_the_row_cap(self, client, monkeypatch):
        # ถูกตัดต้องเห็นได้จาก response ไม่ใช่หายเงียบ
        c, main = client
        rows = [{"province": f"P{i}", "year": 2024} for i in range(main.CACHE_INSPECT_LIMIT)]
        monkeypatch.setattr(main, "supa_call", lambda fn, **kw: _fake_response(rows))

        d = c.get("/cache").json()
        assert d["truncated"] is True
        assert d["limit"] == main.CACHE_INSPECT_LIMIT


# GET /cache/ndvi-latest
class TestLatestNdviCache:
    def test_keeps_only_the_newest_year_per_province(self, client, monkeypatch):
        # แถวมาแบบ year desc (ตาม .order ใน endpoint) → แถวแรกของแต่ละจังหวัดชนะ
        c, main = client
        monkeypatch.setattr(main, "supa_call", lambda fn, **kw: _fake_response([
            {"province": "A", "year": 2025, "ndvi_mean": 0.55},
            {"province": "B", "year": 2025, "ndvi_mean": 0.31},
            {"province": "A", "year": 2024, "ndvi_mean": 0.42},
            {"province": "B", "year": 2023, "ndvi_mean": 0.28},
        ]))

        r = c.get("/cache/ndvi-latest")
        assert r.status_code == 200
        d = r.json()
        assert d["data"] == {"A": 0.55, "B": 0.31}
        assert d["count"] == 2

    def test_empty_cache_returns_empty_map(self, client, monkeypatch):
        c, main = client
        monkeypatch.setattr(main, "supa_call", lambda fn, **kw: _fake_response([]))

        d = c.get("/cache/ndvi-latest").json()
        assert d == {"count": 0, "data": {}}


# GET /cache/districts
class TestDistrictCache:
    def test_returns_annual_list(self, client, monkeypatch):
        c, main = client
        monkeypatch.setattr(main, "supa_call",
            lambda fn, **kw: _fake_response([
                {"province": "P", "district": "D", "year": 2024, "ndvi_mean": 0.5}
            ]))

        r = c.get("/cache/districts")
        assert r.status_code == 200
        assert len(r.json()["annual"]) == 1

    def test_filter_by_province_param_accepted(self, client, monkeypatch):
        c, main = client
        monkeypatch.setattr(main, "supa_call",
            lambda fn, **kw: _fake_response([]))

        r = c.get("/cache/districts?province=Bangkok")
        assert r.status_code == 200


# GET /analysis/ranking
# ที่มาข้อมูลเปลี่ยนเป็น urban_ndvi_annual (เขต built-up) — ดู main.py::get_ranking
class TestRanking:
    def test_computes_rank_and_who_reference_counts(self, client, monkeypatch):
        c, main = client
        data = [
            {"province": "A", "ndvi_mean_urban": 0.3, "green_share_in_urban_pct": 20,
             "green_in_urban_km2": 100, "urban_area_km2": 500,
             "population_urban": 1_000_000, "m2_per_person_urban": 5.0},
            {"province": "B", "ndvi_mean_urban": 0.6, "green_share_in_urban_pct": 60,
             "green_in_urban_km2": 500, "urban_area_km2": 500,
             "population_urban": 100_000, "m2_per_person_urban": 50.0},
        ]
        monkeypatch.setattr(main, "supa_call",
            lambda fn, **kw: _fake_response(data))

        r = c.get("/analysis/ranking?year=2024")
        assert r.status_code == 200
        d = r.json()
        assert d["total_cached"] == 2
        assert d["above_who_reference_count"] == 1
        assert d["below_who_reference_count"] == 1
        # เรียงจาก m²/คน น้อย → มาก, rank 1 = ขาดแคลนสุด
        assert d["data"][0]["province"] == "A"
        assert d["data"][0]["rank"] == 1
        assert d["data"][1]["province"] == "B"
        assert d["data"][1]["rank"] == 2

    def test_skips_rows_without_m2_per_person(self, client, monkeypatch):
        c, main = client
        data = [{
            "province": "A", "ndvi_mean_urban": 0.3, "green_share_in_urban_pct": 20,
            "green_in_urban_km2": 100, "urban_area_km2": 500,
            "population_urban": None, "m2_per_person_urban": None,
        }]
        monkeypatch.setattr(main, "supa_call",
            lambda fn, **kw: _fake_response(data))

        r = c.get("/analysis/ranking")
        assert r.status_code == 200
        d = r.json()
        assert d["total_cached"] == 0
        assert d["data"] == []


# GET /timelapse/ndvi/provinces
class TestTimelapse:
    def test_groups_data_by_province_and_year(self, client, monkeypatch):
        c, main = client
        rows = [
            {"province": "Bangkok", "year": 2020, "ndvi_mean": 0.30},
            {"province": "Bangkok", "year": 2021, "ndvi_mean": 0.32},
            {"province": "Chiang Mai", "year": 2020, "ndvi_mean": 0.55},
            {"province": "Chiang Mai", "year": 2022, "ndvi_mean": 0.58},
        ]
        monkeypatch.setattr(main, "supa_call",
            lambda fn, **kw: _fake_response(rows))

        r = c.get("/timelapse/ndvi/provinces?start_year=2020&end_year=2022")
        assert r.status_code == 200
        d = r.json()
        assert d["start_year"] == 2020 and d["end_year"] == 2022
        assert d["years"] == [2020, 2021, 2022]
        assert d["province_count"] == 2
        assert d["data"]["Bangkok"]["2020"] == 0.30
        assert d["data"]["Bangkok"]["2021"] == 0.32
        assert d["data"]["Chiang Mai"]["2022"] == 0.58
        # ปีที่ไม่มี row → key ไม่อยู่ใน dict (ไม่ใช่ null)
        assert "2021" not in d["data"]["Chiang Mai"]

    def test_skips_rows_with_null_ndvi(self, client, monkeypatch):
        c, main = client
        rows = [
            {"province": "Bangkok", "year": 2020, "ndvi_mean": None},
            {"province": "Bangkok", "year": 2021, "ndvi_mean": 0.32},
        ]
        monkeypatch.setattr(main, "supa_call",
            lambda fn, **kw: _fake_response(rows))

        r = c.get("/timelapse/ndvi/provinces?start_year=2020&end_year=2021")
        assert r.status_code == 200
        d = r.json()
        assert d["years"] == [2021]
        assert d["data"]["Bangkok"] == {"2021": 0.32}

    def test_start_after_end_returns_400(self, client):
        c, _ = client
        r = c.get("/timelapse/ndvi/provinces?start_year=2025&end_year=2020")
        assert r.status_code == 400

    def test_year_out_of_range_returns_422(self, client):
        c, _ = client
        r = c.get("/timelapse/ndvi/provinces?start_year=1800&end_year=2020")
        assert r.status_code == 422

    def test_empty_cache_returns_empty_data(self, client, monkeypatch):
        c, main = client
        monkeypatch.setattr(main, "supa_call",
            lambda fn, **kw: _fake_response([]))

        r = c.get("/timelapse/ndvi/provinces")
        assert r.status_code == 200
        d = r.json()
        assert d["years"] == []
        assert d["province_count"] == 0
        assert d["data"] == {}

    def test_lst_variant_reads_lst_mean(self, client, monkeypatch):
        """LST timelapse อ่านจาก province_lst_annual (column lst_mean) —
        โครง response เดียวกับ NDVI · row ที่ lst_mean=None ถูก skip"""
        c, main = client
        rows = [
            {"province": "Bangkok", "year": 2020, "lst_mean": 35.2},
            {"province": "Bangkok", "year": 2021, "lst_mean": None},
            {"province": "Chiang Mai", "year": 2020, "lst_mean": 29.8},
        ]
        monkeypatch.setattr(main, "supa_call",
            lambda fn, **kw: _fake_response(rows))

        r = c.get("/timelapse/lst/provinces?start_year=2020&end_year=2021")
        assert r.status_code == 200
        d = r.json()
        assert d["years"] == [2020]
        assert d["province_count"] == 2
        assert d["data"]["Bangkok"] == {"2020": 35.2}
        assert d["data"]["Chiang Mai"] == {"2020": 29.8}

    def test_lst_start_after_end_returns_400(self, client):
        c, _ = client
        r = c.get("/timelapse/lst/provinces?start_year=2025&end_year=2020")
        assert r.status_code == 400


# GET /analysis/cooling/{province}
def _cooling_rows(year, districts, ndvi, lst):
    """แถว district_ndvi_annual / district_lst_annual ของปีเดียว"""
    return ([{"district": d, "year": year, "ndvi_mean": v} for d, v in zip(districts, ndvi)],
            [{"district": d, "year": year, "lst_mean": v} for d, v in zip(districts, lst)])


def _cooling_supa(ndvi_rows, lst_rows):
    """endpoint เรียก supa_call 2 ครั้ง: ครั้งแรก NDVI, ครั้งสอง LST (ทุกปีของจังหวัด)"""
    state = {"n": 0}

    def fake(fn, **kw):
        state["n"] += 1
        return _fake_response(ndvi_rows if state["n"] == 1 else lst_rows)
    return fake


def _cooling_gradient(year, n, start=0):
    """n อำเภอที่ยิ่งเขียวยิ่งเย็นเป็นเส้นตรง (slope −10 °C ต่อ NDVI)"""
    names = [f"D{i}" for i in range(start, start + n)]
    ndvi = [0.1 + 0.6 * i / max(n - 1, 1) for i in range(n)]
    return _cooling_rows(year, names, ndvi, [35.0 - 10 * v for v in ndvi])


class TestCooling:
    BKK = "Bangkok Metropolis"   # 50 อำเภอ → ต้องมีอย่างน้อย 25
    PHUKET = "Phuket"            # 3 อำเภอ → ไม่มีวันถึงเกณฑ์ 10

    def test_required_districts_is_ten_and_half_the_province(self):
        from routers.maps.analysis.cooling import required_districts
        assert required_districts(3) == 10
        assert required_districts(20) == 10
        assert required_districts(21) == 11
        assert required_districts(50) == 25

    def test_unknown_province_returns_404(self, client):
        c, _ = client
        r = c.get("/analysis/cooling/NotAProvince")
        assert r.status_code == 404
        assert "NotAProvince" in r.json()["detail"]

    def test_enough_districts_reports_cooling_slope(self, client, monkeypatch):
        c, _ = client
        monkeypatch.setattr("routers.maps.analysis.cooling.supa_call",
                            _cooling_supa(*_cooling_gradient(2025, 30)))
        d = c.get(f"/analysis/cooling/{self.BKK}?year=2025").json()
        assert d["total_districts"] == 50
        assert d["required_districts"] == 25
        assert d["n_districts"] == 30
        assert d["sufficient"] is True
        assert d["regression"]["slope"] == pytest.approx(-10.0)
        assert "(ชัดเจน," in d["interpretation"]

    def test_too_few_districts_hides_a_flipped_slope(self, client, monkeypatch):
        """กรณีจริง 13 ก.ย. 2569: กทม. ปี 2026 มี 5 อำเภอ ได้ความชันเป็นบวก
        ต้องไม่คืนความชัน แต่ยังคืนจุดครบเพื่อให้กราฟแสดงค่าจริง"""
        c, _ = client
        names = ["A", "B", "C", "D", "E"]
        ndvi_rows, lst_rows = _cooling_rows(2026, names, [0.2, 0.3, 0.4, 0.5, 0.6],
                                            [30.0, 31.0, 32.0, 33.0, 34.0])
        monkeypatch.setattr("routers.maps.analysis.cooling.supa_call",
                            _cooling_supa(ndvi_rows, lst_rows))
        d = c.get(f"/analysis/cooling/{self.BKK}?year=2026").json()
        assert d["n_districts"] == 5
        assert d["sufficient"] is False
        assert d["regression"] is None
        assert len(d["points"]) == 5
        assert "5 จาก 50 อำเภอ" in d["interpretation"]
        assert "อย่างน้อย 25 อำเภอ" in d["interpretation"]
        assert "เชิงบวก" not in d["interpretation"]

    def test_no_year_picks_latest_sufficient_year(self, client, monkeypatch):
        c, _ = client
        n25, l25 = _cooling_gradient(2025, 30)
        n26, l26 = _cooling_gradient(2026, 5)
        monkeypatch.setattr("routers.maps.analysis.cooling.supa_call",
                            _cooling_supa(n25 + n26, l25 + l26))
        d = c.get(f"/analysis/cooling/{self.BKK}").json()
        assert d["year"] == 2025
        assert d["latest_sufficient_year"] == 2025
        assert d["sufficient"] is True

    def test_insufficient_year_points_to_a_sufficient_one(self, client, monkeypatch):
        c, _ = client
        n25, l25 = _cooling_gradient(2025, 30)
        n26, l26 = _cooling_gradient(2026, 5)
        monkeypatch.setattr("routers.maps.analysis.cooling.supa_call",
                            _cooling_supa(n25 + n26, l25 + l26))
        d = c.get(f"/analysis/cooling/{self.BKK}?year=2026").json()
        assert d["year"] == 2026
        assert d["regression"] is None
        assert d["latest_sufficient_year"] == 2025
        assert "ปี 2025 มีข้อมูลพอ" in d["interpretation"]

    def test_small_province_never_gets_a_slope(self, client, monkeypatch):
        c, _ = client
        monkeypatch.setattr("routers.maps.analysis.cooling.supa_call",
                            _cooling_supa(*_cooling_gradient(2025, 3)))
        d = c.get(f"/analysis/cooling/{self.PHUKET}?year=2025").json()
        assert d["total_districts"] == 3
        assert d["n_districts"] == 3
        assert d["regression"] is None
        assert d["latest_sufficient_year"] is None
        assert "จังหวัดนี้มี 3 อำเภอ" in d["interpretation"]

    def test_pairs_only_districts_present_in_both_tables(self, client, monkeypatch):
        c, _ = client
        ndvi_rows, lst_rows = _cooling_gradient(2025, 30)
        ndvi_rows.append({"district": "NoLst", "year": 2025, "ndvi_mean": 0.4})
        lst_rows.append({"district": "D0", "year": 2024, "lst_mean": 30.0})  # คนละปี
        monkeypatch.setattr("routers.maps.analysis.cooling.supa_call",
                            _cooling_supa(ndvi_rows, lst_rows))
        d = c.get(f"/analysis/cooling/{self.BKK}?year=2025").json()
        assert d["n_districts"] == 30

    def test_duplicate_cache_rows_count_once(self, client, monkeypatch):
        """แถวซ้ำใน cache เคยเกิดจริง (Yasothon/2026) — ต้องไม่ดันจำนวนอำเภอให้ถึงเกณฑ์"""
        c, _ = client
        ndvi_rows, lst_rows = _cooling_gradient(2025, 13)
        monkeypatch.setattr("routers.maps.analysis.cooling.supa_call",
                            _cooling_supa(ndvi_rows * 2, lst_rows))
        d = c.get(f"/analysis/cooling/{self.BKK}?year=2025").json()
        assert d["n_districts"] == 13
        assert d["regression"] is None

    def test_empty_cache_returns_null_regression(self, client, monkeypatch):
        c, _ = client
        monkeypatch.setattr("routers.maps.analysis.cooling.supa_call",
                            lambda fn, **kw: _fake_response([]))
        d = c.get(f"/analysis/cooling/{self.BKK}?year=2025").json()
        assert d["n_districts"] == 0
        assert d["regression"] is None
        assert d["points"] == []


# POST /analysis/custom-area
# ทดสอบเฉพาะ validation path ที่ตอบกลับ "ก่อน" แตะ GEE — compute path จริง
# (NDVI/LST/WorldPop) พึ่ง Earth Engine จึงไม่ครอบคลุมใน unit test ชุดนี้
class TestCustomArea:
    _SQUARE = [[100.0, 13.0], [100.1, 13.0], [100.1, 13.1], [100.0, 13.1], [100.0, 13.0]]

    def _body(self, ring, year=None):
        geom = {"type": "Polygon", "coordinates": [ring]}
        body = {"geometry": geom}
        if year is not None:
            body["year"] = year
        return body

    def test_missing_geometry_returns_422(self, client):
        # ขาด field geometry → Pydantic validation 422
        c, _ = client
        r = c.post("/analysis/custom-area", json={"year": 2024})
        assert r.status_code == 422

    def test_non_polygon_returns_400(self, client):
        c, _ = client
        r = c.post("/analysis/custom-area",
                   json={"geometry": {"type": "Point", "coordinates": [100.0, 13.0]}})
        assert r.status_code == 400
        assert "Polygon" in r.json()["detail"]

    def test_too_few_points_returns_400(self, client):
        c, _ = client
        tri = [[100.0, 13.0], [100.1, 13.0], [100.0, 13.0]]  # 2 จุดจริง
        r = c.post("/analysis/custom-area", json=self._body(tri))
        assert r.status_code == 400
        assert "3 จุด" in r.json()["detail"]

    def test_year_out_of_range_returns_422(self, client):
        c, _ = client
        r = c.post("/analysis/custom-area", json=self._body(self._SQUARE, year=1500))
        assert r.status_code == 422

    def test_area_too_large_returns_400(self, client):
        # กล่องครอบเกือบทั้งประเทศ → เกิน MAX_AREA_KM2
        c, _ = client
        huge = [[97.0, 6.0], [106.0, 6.0], [106.0, 20.0], [97.0, 20.0], [97.0, 6.0]]
        r = c.post("/analysis/custom-area", json=self._body(huge))
        assert r.status_code == 400
        assert "ใหญ่เกินไป" in r.json()["detail"]

    def test_out_of_range_coordinate_returns_400(self, client):
        c, _ = client
        bad = [[200.0, 13.0], [100.1, 13.0], [100.1, 13.1], [200.0, 13.0]]
        r = c.post("/analysis/custom-area", json=self._body(bad))
        assert r.status_code == 400


# POST /recommend/custom-area
# validation path เท่านั้น (ก่อนแตะ GEE) — เหมือน TestCustomArea
class TestCustomAreaRecommend:
    _SQUARE = [[100.0, 13.0], [100.1, 13.0], [100.1, 13.1], [100.0, 13.1], [100.0, 13.0]]

    def _body(self, ring, **extra):
        return {"geometry": {"type": "Polygon", "coordinates": [ring]}, **extra}

    def test_missing_geometry_returns_422(self, client):
        c, _ = client
        r = c.post("/recommend/custom-area", json={"year": 2024})
        assert r.status_code == 422

    def test_non_polygon_returns_400(self, client):
        c, _ = client
        r = c.post("/recommend/custom-area",
                   json={"geometry": {"type": "LineString", "coordinates": [[100, 13], [100.1, 13]]}})
        assert r.status_code == 400
        assert "Polygon" in r.json()["detail"]

    def test_too_few_points_returns_400(self, client):
        c, _ = client
        tri = [[100.0, 13.0], [100.1, 13.0], [100.0, 13.0]]
        r = c.post("/recommend/custom-area", json=self._body(tri))
        assert r.status_code == 400
        assert "3 จุด" in r.json()["detail"]

    def test_area_too_large_returns_400(self, client):
        c, _ = client
        huge = [[97.0, 6.0], [106.0, 6.0], [106.0, 20.0], [97.0, 20.0], [97.0, 6.0]]
        r = c.post("/recommend/custom-area", json=self._body(huge))
        assert r.status_code == 400
        assert "ใหญ่เกินไป" in r.json()["detail"]

    def test_weight_out_of_range_returns_422(self, client):
        # น้ำหนัก > 1 → Pydantic Field validation 422 ก่อนแตะ GEE
        c, _ = client
        r = c.post("/recommend/custom-area", json=self._body(self._SQUARE, w_ndvi=5))
        assert r.status_code == 422

    def test_year_out_of_range_returns_422(self, client):
        c, _ = client
        r = c.post("/recommend/custom-area", json=self._body(self._SQUARE, year=1500))
        assert r.status_code == 422


# saved-areas CRUD (/saved-areas)
class TestSavedAreas:
    _SQUARE = [[100.0, 13.0], [100.1, 13.0], [100.1, 13.1], [100.0, 13.1], [100.0, 13.0]]

    def _body(self, ring, **extra):
        return {"geometry": {"type": "Polygon", "coordinates": [ring]}, **extra}

    # validation (ก่อนแตะ DB)
    def test_create_missing_geometry_returns_422(self, client):
        c, _ = client
        r = c.post("/saved-areas", json={"year": 2024})
        assert r.status_code == 422

    def test_create_non_polygon_returns_400(self, client):
        c, _ = client
        r = c.post("/saved-areas", json={"geometry": {"type": "Point", "coordinates": [100, 13]}})
        assert r.status_code == 400

    def test_create_too_large_returns_400(self, client):
        c, _ = client
        huge = [[97.0, 6.0], [106.0, 6.0], [106.0, 20.0], [97.0, 20.0], [97.0, 6.0]]
        r = c.post("/saved-areas", json=self._body(huge))
        assert r.status_code == 400

    # create + list (mock DB)
    def test_create_returns_row_without_user_id(self, client, monkeypatch):
        c, _ = client
        monkeypatch.setattr("routers.saved.supa_call",
            lambda fn, **kw: _fake_response([{
                "id": 7, "label": "พื้นที่ทดสอบ", "year": 2024, "area_km2": 120.0,
                "province": None, "geometry": {"type": "Polygon", "coordinates": [self._SQUARE]},
                "user_id": "test-user-id", "created_at": "2024-01-01T00:00:00Z",
            }]))
        r = c.post("/saved-areas", json=self._body(self._SQUARE, label="พื้นที่ทดสอบ"))
        assert r.status_code == 200
        d = r.json()
        assert d["id"] == 7
        assert "user_id" not in d            # ห้าม leak
        assert d["mine"] is True             # บัญชีตรง → ของฉัน

    def test_list_marks_mine_and_hides_user_id(self, client, monkeypatch):
        # แถวที่สองเป็นของบัญชีอื่น — จริง ๆ query กรอง user_id ไว้แล้วจึงไม่ควรหลุดมา
        # แต่ยืนยันว่า _public คำนวณ `mine` จาก user_id ไม่ใช่แค่ตั้ง True ทื่อ ๆ
        c, _ = client
        monkeypatch.setattr("routers.saved.supa_call",
            lambda fn, **kw: _fake_response([
                {"id": 1, "label": "A", "user_id": "test-user-id", "geometry": {}},
                {"id": 2, "label": "B", "user_id": "someone-else", "geometry": {}},
            ]))
        r = c.get("/saved-areas")
        assert r.status_code == 200
        rows = r.json()["data"]
        assert all("user_id" not in row for row in rows)
        assert rows[0]["mine"] is True
        assert rows[1]["mine"] is False

    def test_list_returns_own_saved_areas(self, client, monkeypatch):
        # กรองด้วย user_id เสมอ เพราะ router บังคับ login แล้ว
        c, _ = client
        monkeypatch.setattr("routers.saved.supa_call",
            lambda fn, **kw: _fake_response([
                {"id": 1, "user_id": "test-user-id", "geometry": {}},
            ]))
        r = c.get("/saved-areas")
        assert r.status_code == 200
        rows = r.json()["data"]
        assert len(rows) == 1
        assert rows[0]["mine"] is True

    def test_list_has_no_shared_gallery(self, client, monkeypatch):
        # ไม่มี public gallery แล้ว — ?shared=true ไม่ใช่ query param ที่มีผลใดๆ
        # (FastAPI เพิกเฉยต่อ query param ที่ไม่รู้จัก) ยังคงคืนเฉพาะของเจ้าของ
        c, _ = client
        monkeypatch.setattr("routers.saved.supa_call",
            lambda fn, **kw: _fake_response([
                {"id": 1, "label": "A", "user_id": "test-user-id", "geometry": {}},
            ]))
        r = c.get("/saved-areas?shared=true")
        assert r.status_code == 200
        rows = r.json()["data"]
        assert len(rows) == 1
        assert rows[0]["mine"] is True

    # get-one authorization
    def test_get_one_not_found_returns_404(self, client, monkeypatch):
        c, _ = client
        monkeypatch.setattr("routers.saved.supa_call", lambda fn, **kw: _fake_response([]))
        r = c.get("/saved-areas/999")
        assert r.status_code == 404

    def test_get_one_wrong_owner_returns_403(self, client, monkeypatch):
        # id เป็น BIGSERIAL เดาเลขถัดไปได้ง่าย — ผู้ใช้ที่ล็อกอินอยู่แต่ไม่ใช่เจ้าของ
        # ห้ามอ่าน polygon/analysis ของคนอื่นได้แค่เพราะเดา id ถูก
        c, _ = client
        monkeypatch.setattr("routers.saved.supa_call",
            lambda fn, **kw: _fake_response([{"id": 1, "user_id": "other-user-id",
                                              "geometry": {}}]))
        r = c.get("/saved-areas/1")
        assert r.status_code == 403

    def test_get_one_owner_by_account_succeeds(self, client, monkeypatch):
        # fixture ล็อกอินเป็น user id "test-user-id" — แถวที่ user_id ตรงกันต้องอ่านได้
        # (บัญชีที่ล็อกอินเป็นทางเดียวที่ระบุเจ้าของ ตั้งแต่ migration 019)
        c, _ = client
        monkeypatch.setattr("routers.saved.supa_call",
            lambda fn, **kw: _fake_response([{"id": 1, "user_id": "test-user-id",
                                              "geometry": {}}]))
        r = c.get("/saved-areas/1")
        assert r.status_code == 200
        assert r.json()["id"] == 1

    def test_get_one_admin_override_succeeds(self, client, monkeypatch):
        c, _ = client
        monkeypatch.setattr("routers.saved.supa_call",
            lambda fn, **kw: _fake_response([{"id": 1, "user_id": "other-user-id",
                                              "geometry": {}}]))
        r = c.get("/saved-areas/1", headers={"X-Admin-Token": "test-token"})
        assert r.status_code == 200

    def test_owner_token_header_no_longer_grants_access(self, client, monkeypatch):
        # regression guard สำหรับ migration 019: X-Owner-Token เคยเป็นทางเข้าที่สอง
        # ตอนนี้ต้องถูกเพิกเฉยสิ้นเชิง — ส่งมาตรงกับค่าอะไรก็ไม่ช่วยให้เห็นของคนอื่น
        c, _ = client
        monkeypatch.setattr("routers.saved.supa_call",
            lambda fn, **kw: _fake_response([{"id": 1, "owner_token": "tok",
                                              "user_id": "other-user-id", "geometry": {}}]))
        r = c.get("/saved-areas/1", headers={"X-Owner-Token": "tok"})
        assert r.status_code == 403
        r = c.delete("/saved-areas/1", headers={"X-Owner-Token": "tok"})
        assert r.status_code == 403

    # delete authorization
    def test_delete_not_found_returns_404(self, client, monkeypatch):
        c, _ = client
        monkeypatch.setattr("routers.saved.supa_call", lambda fn, **kw: _fake_response([]))
        r = c.delete("/saved-areas/999")
        assert r.status_code == 404

    def test_delete_wrong_owner_returns_403(self, client, monkeypatch):
        c, _ = client
        monkeypatch.setattr("routers.saved.supa_call",
            lambda fn, **kw: _fake_response([{"id": 1, "user_id": "other-user-id"}]))
        r = c.delete("/saved-areas/1")
        assert r.status_code == 403

    def test_delete_owner_match_succeeds(self, client, monkeypatch):
        c, _ = client
        monkeypatch.setattr("routers.saved.supa_call",
            lambda fn, **kw: _fake_response([{"id": 1, "user_id": "test-user-id"}]))
        r = c.delete("/saved-areas/1")
        assert r.status_code == 200
        assert r.json()["id"] == 1

    def test_delete_admin_override_succeeds(self, client, monkeypatch):
        # owner ไม่ตรง แต่ admin token ตรง (fixture ตั้ง ADMIN_TOKEN=test-token) → ลบได้
        c, _ = client
        monkeypatch.setattr("routers.saved.supa_call",
            lambda fn, **kw: _fake_response([{"id": 1, "user_id": "other-user-id"}]))
        r = c.delete("/saved-areas/1", headers={"X-Admin-Token": "test-token"})
        assert r.status_code == 200


# Auth gating
# Business-logic tests ข้างบนใช้ fixture `client` ที่ override require_user ไว้ —
# ชุดนี้ใช้ TestClient แยกต่างหาก (ไม่ผ่าน override) เพื่อยืนยันว่า endpoint ที่
# ควรถูกล็อกจริง ๆ ปฏิเสธ request ที่ไม่มี token, และที่ตั้งใจเปิดสาธารณะไว้ยังเข้าได้
class TestAuthGating:
    def test_recommend_rejects_anonymous(self):
        import main
        from dependencies import PROVINCE_GEOMETRIES
        sample = next(iter(PROVINCE_GEOMETRIES))
        r = TestClient(main.app).get(f"/recommend/{sample}")
        assert r.status_code == 401

    def test_ndvi_rejects_anonymous(self):
        import main
        from dependencies import PROVINCE_GEOMETRIES
        sample = next(iter(PROVINCE_GEOMETRIES))
        r = TestClient(main.app).get(f"/ndvi/{sample}")
        assert r.status_code == 401

    def test_compare_rejects_anonymous(self):
        import main
        r = TestClient(main.app).get("/compare?provinces=Bangkok")
        assert r.status_code == 401

    def test_saved_areas_rejects_anonymous(self):
        import main
        r = TestClient(main.app).get("/saved-areas")
        assert r.status_code == 401

    def test_access_300m_rejects_anonymous(self):
        import main
        from dependencies import PROVINCE_GEOMETRIES
        sample = next(iter(PROVINCE_GEOMETRIES))
        r = TestClient(main.app).get(f"/analysis/access-300m/{sample}")
        assert r.status_code == 401

    def test_ranking_stays_public(self, monkeypatch):
        # Landing.js (หน้าก่อนล็อกอิน) พึ่ง endpoint นี้เป็น teaser — ต้องไม่ถูกล็อก
        import main
        monkeypatch.setattr(main, "supa_call", lambda fn, **kw: _fake_response([]))
        r = TestClient(main.app).get("/analysis/ranking")
        assert r.status_code == 200

    def test_health_stays_public(self):
        import main
        r = TestClient(main.app).get("/health")
        assert r.status_code == 200
