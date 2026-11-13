"""Cache-version invalidation tests สำหรับ router ที่อ่าน/เขียน cache (NDVI + LST).

ปิดช่องที่เคยหลุด: ทั้ง 4 endpoint ของ LST และ 2 endpoint รายเดือนของ NDVI เขียน
`cache_version` ตอน insert แต่ไม่เคยอ่านกลับมาเทียบเลย — แถวที่ cache ไว้ก่อน bump
version จึงถูก serve ตลอดกาลโดยไม่มีวัน recompute (วัดจริงบน Supabase 11 ส.ค. 2569:
ndvi_monthly 63/67 แถวยังเป็น v1 ที่คำนวณด้วย QA60 ซึ่งเลิกใช้ไปแล้ว)

เทสต์ชุดนี้ล็อกพฤติกรรมที่ถูกต้องไว้ 3 อย่างต่อ endpoint:
  1. แถวที่ version ปัจจุบัน → serve จาก cache ไม่แตะ compute
  2. แถวที่ version เก่า → *ลบทิ้ง* แล้ว recompute (ต้องลบก่อน ไม่งั้น insert ชน
     UNIQUE(province[,district],year) — ยืนยันแล้วว่า constraint ทั้ง 6 ตารางบังคับใช้จริง)
  3. แถวที่ไม่มีคอลัมน์ cache_version เลย (schema ก่อน migration) → นับเป็นเก่า

ใช้ FakeSupabase ที่มี state จริงแทนการ stub ค่าคืนทีละ call เพราะต้องพิสูจน์ลำดับ
delete → insert ไม่ใช่แค่ว่า compute ถูกเรียก
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from dependencies import (CURRENT_CACHE_VERSION, NDVI_ANNUAL_CACHE_VERSION,
                          DISTRICT_GEOMETRIES,
                          PROVINCE_GEOMETRIES, require_user)

PROVINCE = next(iter(PROVINCE_GEOMETRIES))

# thailand_districts.json ถูก gitignore (green-area-frontend/.gitignore) จึงไม่มีใน CI
# → DISTRICT_GEOMETRIES ว่าง · ห้าม next(iter(...)) ตรง ๆ เพราะจะ StopIteration ตอน
# import แล้วพังทั้งไฟล์ (ไม่ใช่แค่เคสอำเภอ) · เคสระดับอำเภอ skip ไปเมื่อไม่มีไฟล์
_dist_entry = next(iter(DISTRICT_GEOMETRIES), None)
HAS_DISTRICTS = _dist_entry is not None
DIST_PROVINCE, DISTRICT = _dist_entry if _dist_entry else (PROVINCE, "—")

needs_districts = pytest.mark.skipif(
    not HAS_DISTRICTS,
    reason="ไม่มี thailand_districts.json (gitignored) — รัน generate_districts.py ก่อน")

YEAR = 2025
STALE = CURRENT_CACHE_VERSION - 1

_MONTHLY = [{"month": "ม.ค.", "month_num": 1, "ndvi": 0.4, "image_count": 3}]
_DATA_QUALITY = {"image_count": 10, "cloud_filter_pct": 20,
                 "clear_obs_mean": 8.0, "clear_obs_min": 1,
                 "level": "threshold", "label": "พอใช้", "note": "test"}
_CANOPY = {"available": False, "target_pct": 30.0, "source": "ESA WorldCover",
           "epoch_year": 2021, "epoch_offset_years": 4,
           "label": "ไม่มีข้อมูล", "note": "test"}
_VALIDATION = {"available": False, "target_pp": 10.0, "year": YEAR,
               "worldcover_epoch_year": 2021, "note": "test"}


class _FakeQuery:
    """Query builder ปลอมที่รองรับ chain แบบเดียวกับ postgrest-py เท่าที่ router ใช้"""

    def __init__(self, table, store, log):
        self._table, self._store, self._log = table, store, log
        self._op = None
        self._filters = {}
        self._payload = None

    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def is_(self, col, val):
        self._filters[col] = None if val == "null" else val
        return self

    def limit(self, _n):
        return self

    def order(self, *_a, **_k):
        return self

    def _matches(self, row):
        return all(row.get(k) == v for k, v in self._filters.items())

    def execute(self):
        rows = self._store.setdefault(self._table, [])
        if self._op == "select":
            return SimpleNamespace(data=[r for r in rows if self._matches(r)])
        if self._op == "delete":
            gone = [r for r in rows if self._matches(r)]
            self._store[self._table] = [r for r in rows if not self._matches(r)]
            self._log.append(("delete", self._table, gone))
            return SimpleNamespace(data=gone)
        if self._op == "insert":
            row = {"id": len(rows) + 100, "created_at": "2026-01-01T00:00:00Z",
                   **self._payload}
            rows.append(row)
            self._log.append(("insert", self._table, row))
            return SimpleNamespace(data=[row])
        raise AssertionError(f"unsupported op {self._op}")


class FakeSupabase:
    def __init__(self, store, log):
        self._store, self._log = store, log

    def table(self, name):
        return _FakeQuery(name, self._store, self._log)


@pytest.fixture
def env(monkeypatch):
    """คืน helper ที่ seed cache row ได้ + บันทึก insert/delete + นับการ compute"""
    import main
    import routers.lst as lst_mod
    import routers.ndvi.endpoints as ndvi_mod

    store, log, calls = {}, [], []
    fake = FakeSupabase(store, log)

    def fake_supa_call(builder_fn, **_kw):
        return builder_fn(fake)

    for mod in (ndvi_mod, lst_mod):
        monkeypatch.setattr(mod, "supa_call", fake_supa_call)

    # compute ปลอม — นับว่าถูกเรียกกี่ครั้ง โดยไม่แตะ GEE
    def _ndvi_monthly(*_a, **_k):
        calls.append("ndvi_monthly")
        return _MONTHLY

    def _lst_monthly(*_a, **_k):
        calls.append("lst_monthly")
        return [{"month": "ม.ค.", "month_num": 1, "lst": 30.0, "image_count": 2}]

    monkeypatch.setattr(ndvi_mod, "_compute_ndvi_monthly", _ndvi_monthly)
    monkeypatch.setattr(lst_mod, "_compute_lst_monthly", _lst_monthly)

    def _ndvi_annual(*_a, **_k):
        calls.append("ndvi_annual")
        return {"ndvi_mean": 0.65, "ndvi_min": 0.1, "ndvi_max": 0.8,
                "green_area_pct": 40.0, "green_area_km2": 40.0,
                "dense_area_pct": 10.0, "dense_area_km2": 10.0,
                "total_area_km2": 100.0, "green_area_m2_raw": 40_000_000,
                "data_quality": _DATA_QUALITY,
                "canopy": _CANOPY}

    monkeypatch.setattr(ndvi_mod, "_compute_ndvi_annual", _ndvi_annual)
    monkeypatch.setattr(ndvi_mod, "_worldcover_reference_pct", lambda _p: None)
    monkeypatch.setattr(ndvi_mod, "_build_validation",
                        lambda *_a, **_k: _VALIDATION)
    monkeypatch.setattr(ndvi_mod, "get_population", lambda *_a: (1000, 2020))

    # LST annual ใช้ get_lst_col + reduce_lst แทน helper ก้อนเดียว
    monkeypatch.setattr(lst_mod, "get_lst_col",
                        lambda *_a, **_k: SimpleNamespace(size=lambda: SimpleNamespace(getInfo=lambda: 5)))

    def _reduce(*_a, **_k):
        calls.append("lst_annual")
        return (30.0, 25.0, 35.0)

    monkeypatch.setattr(lst_mod, "reduce_lst", _reduce)
    monkeypatch.setattr(lst_mod.ee, "Geometry", lambda g: g)

    main.app.dependency_overrides[require_user] = lambda: {"id": "u", "email": "e@x.com"}
    client = TestClient(main.app)
    yield SimpleNamespace(client=client, store=store, log=log, calls=calls)
    main.app.dependency_overrides.pop(require_user, None)


def _seed(env, table, row):
    env.store.setdefault(table, []).append({"id": 1, "created_at": "2025-01-01T00:00:00Z", **row})


def _inserts(env, table):
    return [r for op, t, r in env.log if op == "insert" and t == table]


def _deletes(env, table):
    return [r for op, t, rows in env.log if op == "delete" and t == table for r in rows]


# ---- NDVI รายปี (จังหวัด) — เกณฑ์พืชพรรณหนาแน่น ----
class TestNdviAnnualDenseThresholdCache:
    URL = f"/ndvi/{PROVINCE}?year={YEAR}"
    TABLE = "ndvi_annual"

    def _row(self, version):
        return {"province": PROVINCE, "year": YEAR,
                "ndvi_mean": 0.65, "ndvi_min": 0.1, "ndvi_max": 0.8,
                "green_area_pct": 40.0, "green_area_km2": 40.0,
                "dense_area_pct": 20.0, "dense_area_km2": 20.0,
                "total_area_km2": 100.0,
                "data_quality": _DATA_QUALITY,
                "canopy": _CANOPY,
                "validation": _VALIDATION,
                "cache_version": version}

    def test_current_row_returns_dense_values_without_compute(self, env):
        _seed(env, self.TABLE, self._row(NDVI_ANNUAL_CACHE_VERSION))
        r = env.client.get(self.URL)
        assert r.status_code == 200
        assert r.json()["from_cache"] is True
        assert r.json()["dense_area_pct"] == 20.0
        assert r.json()["dense_area_km2"] == 20.0
        assert env.calls == []

    def test_old_threshold_row_recomputed_and_new_values_cached(self, env):
        _seed(env, self.TABLE, self._row(CURRENT_CACHE_VERSION))
        r = env.client.get(self.URL)
        assert r.status_code == 200
        assert r.json()["from_cache"] is False
        assert r.json()["dense_area_pct"] == 10.0
        assert env.calls == ["ndvi_annual"]
        assert _deletes(env, self.TABLE)
        assert _inserts(env, self.TABLE)[0]["cache_version"] == NDVI_ANNUAL_CACHE_VERSION
        again = env.client.get(self.URL)
        assert again.status_code == 200
        assert again.json()["from_cache"] is True
        assert again.json()["dense_area_pct"] == 10.0
        assert env.calls == ["ndvi_annual"]


@needs_districts
class TestDistrictNdviAnnualDenseThresholdCache:
    URL = f"/ndvi/{DIST_PROVINCE}/districts/{DISTRICT}?year={YEAR}"
    TABLE = "district_ndvi_annual"

    def test_old_threshold_row_recomputed_and_then_served_from_cache(self, env):
        _seed(env, self.TABLE,
              {"province": DIST_PROVINCE, "district": DISTRICT, "year": YEAR,
               "ndvi_mean": 0.65, "ndvi_min": 0.1, "ndvi_max": 0.8,
               "green_area_pct": 40.0, "green_area_km2": 40.0,
               "dense_area_pct": 20.0, "dense_area_km2": 20.0,
               "total_area_km2": 100.0, "data_quality": _DATA_QUALITY,
               "canopy": _CANOPY, "cache_version": CURRENT_CACHE_VERSION})
        r = env.client.get(self.URL)
        assert r.status_code == 200
        assert r.json()["from_cache"] is False
        assert r.json()["dense_area_pct"] == 10.0
        assert _deletes(env, self.TABLE)
        assert _inserts(env, self.TABLE)[0]["cache_version"] == NDVI_ANNUAL_CACHE_VERSION
        again = env.client.get(self.URL)
        assert again.status_code == 200
        assert again.json()["from_cache"] is True
        assert again.json()["dense_area_pct"] == 10.0
        assert env.calls == ["ndvi_annual"]


# ---- NDVI รายเดือน (จังหวัด) ----
class TestNdviMonthlyCacheVersion:
    URL = f"/ndvi/{PROVINCE}/monthly?year={YEAR}"
    TABLE = "ndvi_monthly"

    def test_current_version_served_from_cache_without_compute(self, env):
        _seed(env, self.TABLE, {"province": PROVINCE, "year": YEAR,
                                "monthly_data": _MONTHLY,
                                "cache_version": CURRENT_CACHE_VERSION})
        r = env.client.get(self.URL)
        assert r.status_code == 200
        assert r.json()["from_cache"] is True
        assert env.calls == [], "แถวที่ version ปัจจุบันต้องไม่ trigger compute"

    def test_stale_version_row_deleted_then_recomputed(self, env):
        _seed(env, self.TABLE, {"province": PROVINCE, "year": YEAR,
                                "monthly_data": [{"stale": True}],
                                "cache_version": STALE})
        r = env.client.get(self.URL)
        assert r.status_code == 200
        assert r.json()["from_cache"] is False
        assert env.calls == ["ndvi_monthly"], "แถวเก่าต้องถูก recompute"
        assert _deletes(env, self.TABLE), "ต้องลบแถวเก่าก่อน ไม่งั้น insert ชน UNIQUE"
        # แถวใหม่ต้องติดป้าย version ปัจจุบัน ไม่งั้นจะ stale ซ้ำรอบหน้า
        assert _inserts(env, self.TABLE)[0]["cache_version"] == CURRENT_CACHE_VERSION
        # ที่สำคัญที่สุด: ต้องไม่เหลือแถวเก่าค้างอยู่ในตาราง
        assert all(row["cache_version"] == CURRENT_CACHE_VERSION
                   for row in env.store[self.TABLE])

    def test_row_without_cache_version_treated_as_stale(self, env):
        # schema ก่อน migration ไม่มีคอลัมน์นี้ — .get(...,1) ต้องทำให้นับเป็นเก่า
        _seed(env, self.TABLE, {"province": PROVINCE, "year": YEAR,
                                "monthly_data": [{"stale": True}]})
        r = env.client.get(self.URL)
        assert r.status_code == 200
        assert r.json()["from_cache"] is False
        assert env.calls == ["ndvi_monthly"]


# ---- NDVI รายเดือน (อำเภอ) ----
@needs_districts
class TestDistrictNdviMonthlyCacheVersion:
    URL = f"/ndvi/{DIST_PROVINCE}/districts/{DISTRICT}/monthly?year={YEAR}"
    TABLE = "district_ndvi_monthly"

    def _row(self, **extra):
        return {"province": DIST_PROVINCE, "district": DISTRICT, "year": YEAR,
                "monthly_data": _MONTHLY, **extra}

    def test_current_version_served_from_cache(self, env):
        _seed(env, self.TABLE, self._row(cache_version=CURRENT_CACHE_VERSION))
        r = env.client.get(self.URL)
        assert r.status_code == 200
        assert r.json()["from_cache"] is True
        assert env.calls == []

    def test_stale_version_deleted_then_recomputed(self, env):
        _seed(env, self.TABLE, self._row(cache_version=STALE))
        r = env.client.get(self.URL)
        assert r.status_code == 200
        assert r.json()["from_cache"] is False
        assert _deletes(env, self.TABLE)
        assert _inserts(env, self.TABLE)[0]["cache_version"] == CURRENT_CACHE_VERSION


# ---- LST ----
class TestLstCacheVersion:
    """ทั้ง 4 endpoint ของ LST ใช้แพตเทิร์นเดียวกัน — วนเทสต์ตารางละชุด"""

    PROVINCE_CASES = [
        (f"/lst/{PROVINCE}?year={YEAR}", "province_lst_annual",
         {"province": PROVINCE, "year": YEAR, "lst_mean": 30.0, "lst_min": 25.0, "lst_max": 35.0}),
        (f"/lst/{PROVINCE}/monthly?year={YEAR}", "province_lst_monthly",
         {"province": PROVINCE, "year": YEAR, "monthly_data": _MONTHLY}),
    ]
    # แยกจาก PROVINCE_CASES เพราะต้อง skip ทั้งชุดเมื่อไม่มีไฟล์ขอบเขตอำเภอ
    DISTRICT_CASES = [
        (f"/lst/{DIST_PROVINCE}/districts/{DISTRICT}?year={YEAR}", "district_lst_annual",
         {"province": DIST_PROVINCE, "district": DISTRICT, "year": YEAR,
          "lst_mean": 30.0, "lst_min": 25.0, "lst_max": 35.0}),
        (f"/lst/{DIST_PROVINCE}/districts/{DISTRICT}/monthly?year={YEAR}", "district_lst_monthly",
         {"province": DIST_PROVINCE, "district": DISTRICT, "year": YEAR,
          "monthly_data": _MONTHLY}),
    ]
    ALL_CASES = PROVINCE_CASES + DISTRICT_CASES

    def _check_hit(self, env, url, table, row):
        _seed(env, table, {**row, "cache_version": CURRENT_CACHE_VERSION})
        r = env.client.get(url)
        assert r.status_code == 200
        assert r.json()["from_cache"] is True
        assert env.calls == [], f"{table}: แถว version ปัจจุบันต้องไม่ recompute"

    def _check_stale(self, env, url, table, row):
        _seed(env, table, {**row, "cache_version": STALE})
        r = env.client.get(url)
        assert r.status_code == 200
        assert r.json()["from_cache"] is False, f"{table}: แถวเก่าต้องถูก recompute"
        assert _deletes(env, table), f"{table}: ต้องลบแถวเก่าก่อน insert"
        assert _inserts(env, table)[0]["cache_version"] == CURRENT_CACHE_VERSION
        assert all(r_["cache_version"] == CURRENT_CACHE_VERSION for r_ in env.store[table])

    def _check_missing_version(self, env, url, table, row):
        _seed(env, table, dict(row))
        r = env.client.get(url)
        assert r.status_code == 200
        assert r.json()["from_cache"] is False

    @pytest.mark.parametrize("url,table,row", PROVINCE_CASES,
                             ids=[c[1] for c in PROVINCE_CASES])
    def test_province_cache_behaviour(self, env, url, table, row):
        self._check_hit(env, url, table, row)

    @pytest.mark.parametrize("url,table,row", PROVINCE_CASES,
                             ids=[c[1] for c in PROVINCE_CASES])
    def test_province_stale_deleted_then_recomputed(self, env, url, table, row):
        self._check_stale(env, url, table, row)

    @pytest.mark.parametrize("url,table,row", PROVINCE_CASES,
                             ids=[c[1] for c in PROVINCE_CASES])
    def test_province_missing_version_is_stale(self, env, url, table, row):
        self._check_missing_version(env, url, table, row)

    @needs_districts
    @pytest.mark.parametrize("url,table,row", DISTRICT_CASES,
                             ids=[c[1] for c in DISTRICT_CASES])
    def test_district_cache_behaviour(self, env, url, table, row):
        self._check_hit(env, url, table, row)

    @needs_districts
    @pytest.mark.parametrize("url,table,row", DISTRICT_CASES,
                             ids=[c[1] for c in DISTRICT_CASES])
    def test_district_stale_deleted_then_recomputed(self, env, url, table, row):
        self._check_stale(env, url, table, row)

    @needs_districts
    @pytest.mark.parametrize("url,table,row", DISTRICT_CASES,
                             ids=[c[1] for c in DISTRICT_CASES])
    def test_district_missing_version_is_stale(self, env, url, table, row):
        self._check_missing_version(env, url, table, row)


# ---- cache miss ปกติ (ไม่มีแถวเลย) ----
class TestColdCacheWritesCurrentVersion:
    """ทุก path ที่ insert ใหม่ต้องติดป้าย version ปัจจุบันเสมอ — กันการถอยกลับไป
    insert โดยไม่ใส่ cache_version ซึ่งจะทำให้แถวใหม่ stale ทันทีที่เขียน"""

    def _check_insert(self, env, url, table):
        r = env.client.get(url)
        assert r.status_code == 200
        assert r.json()["from_cache"] is False
        inserted = _inserts(env, table)
        assert len(inserted) == 1, f"{table}: ต้อง insert แถวใหม่ 1 แถว"
        assert inserted[0]["cache_version"] == CURRENT_CACHE_VERSION

    @pytest.mark.parametrize("url,table", [
        (f"/ndvi/{PROVINCE}/monthly?year={YEAR}", "ndvi_monthly"),
        (f"/lst/{PROVINCE}?year={YEAR}", "province_lst_annual"),
        (f"/lst/{PROVINCE}/monthly?year={YEAR}", "province_lst_monthly"),
    ])
    def test_province_insert_carries_current_cache_version(self, env, url, table):
        self._check_insert(env, url, table)

    @needs_districts
    @pytest.mark.parametrize("url,table", [
        (f"/ndvi/{DIST_PROVINCE}/districts/{DISTRICT}/monthly?year={YEAR}", "district_ndvi_monthly"),
        (f"/lst/{DIST_PROVINCE}/districts/{DISTRICT}?year={YEAR}", "district_lst_annual"),
        (f"/lst/{DIST_PROVINCE}/districts/{DISTRICT}/monthly?year={YEAR}", "district_lst_monthly"),
    ])
    def test_district_insert_carries_current_cache_version(self, env, url, table):
        self._check_insert(env, url, table)
