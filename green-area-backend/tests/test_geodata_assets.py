"""ไฟล์ขอบเขต GeoJSON ต้องอยู่ในตำแหน่งที่ deploy จริงหยิบไปได้ — ไม่ใช่แค่มีบนเครื่อง dev.

ทำไมต้องมีชุดนี้: thailand_districts.json เคยถูก .gitignore ไว้ และ thailand.json มีแต่
ใน green-area-frontend/public/ ผลคือทุก deploy ที่ build จาก git โดยตรงพังเงียบ ๆ
  - `docker build ./green-area-backend` → build context ไม่มีโฟลเดอร์ frontend เลย
    → _load_province_geometries() raise RuntimeError ตอน import = container บูตไม่ขึ้น
  - Render blueprint (clone ทั้ง repo) → thailand.json เจอผ่าน legacy path แต่
    thailand_districts.json ไม่มีในgit → DISTRICT_GEOMETRIES = {} = endpoint อำเภอ 404 ทุกตัว
เทสต์ในชุดนี้จับสภาพนั้นได้ตอน CI แทนที่จะไปเจอตอน deploy

หมายเหตุ: ทั้งชุดอ่านไฟล์จาก repo ตรง ๆ ไม่แตะ GEE/Supabase
"""
import hashlib
import json
import os

import pytest

from dependencies import (BACKEND_DATA_DIR, LEGACY_FRONTEND_PUBLIC,
                          PROVINCE_GEOMETRIES, DISTRICT_GEOMETRIES,
                          _resolve_geojson_path)

# จำนวนที่ประกาศไว้ในระบบ — ต้องตรงกับ TOTAL_DISTRICTS ใน frontend/src/constants.js
EXPECTED_PROVINCES = 77
EXPECTED_DISTRICTS = 928

BACKEND_THAILAND = os.path.join(BACKEND_DATA_DIR, 'thailand.json')
BACKEND_DISTRICTS = os.path.join(BACKEND_DATA_DIR, 'thailand_districts.json')
FRONTEND_THAILAND = os.path.join(LEGACY_FRONTEND_PUBLIC, 'thailand.json')
FRONTEND_DISTRICTS = os.path.join(LEGACY_FRONTEND_PUBLIC, 'thailand_districts.json')


def _sha256(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _features(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)['features']


class TestBackendDataDir:
    """data/ ต้องมีไฟล์ครบ — นี่คือโฟลเดอร์เดียวที่อยู่ใน build context ของ Dockerfile"""

    def test_thailand_json_present(self):
        assert os.path.isfile(BACKEND_THAILAND), (
            "ไม่พบ green-area-backend/data/thailand.json — Docker image จะบูตไม่ขึ้น "
            "(RuntimeError ตอน import dependencies)")

    def test_districts_json_present(self):
        assert os.path.isfile(BACKEND_DISTRICTS), (
            "ไม่พบ green-area-backend/data/thailand_districts.json — "
            "endpoint ระดับอำเภอทุกตัวจะคืน 404")

    def test_province_count(self):
        assert len(_features(BACKEND_THAILAND)) == EXPECTED_PROVINCES

    def test_district_count(self):
        assert len(_features(BACKEND_DISTRICTS)) == EXPECTED_DISTRICTS


class TestFrontendPublicDir:
    """frontend/public/ ต้องมีไฟล์ครบ — vite copy ลง build/ ให้ browser fetch เอง
    (useDistrictData.js เรียก fetch('/thailand_districts.json'))"""

    def test_thailand_json_present(self):
        assert os.path.isfile(FRONTEND_THAILAND)

    def test_districts_json_present(self):
        assert os.path.isfile(FRONTEND_DISTRICTS), (
            "ไม่พบ green-area-frontend/public/thailand_districts.json — "
            "เลือกอำเภอบนแผนที่จะพังทั้งฟีเจอร์ (fetch ได้ 404)")


class TestCopiesInSync:
    """สองสำเนาต้อง byte-identical — generate_districts.py/add_district_th_names.py
    เขียนทั้งสองที่พร้อมกัน ถ้าไฟล์ต่างกันคือมีใคร regenerate แค่ที่เดียว แล้ว
    backend กับ browser จะเห็นชุดอำเภอไม่ตรงกัน"""

    def test_thailand_json_identical(self):
        assert _sha256(BACKEND_THAILAND) == _sha256(FRONTEND_THAILAND), (
            "thailand.json สองสำเนาไม่ตรงกัน — copy ทับให้ตรงกันก่อน commit")

    def test_districts_json_identical(self):
        assert _sha256(BACKEND_DISTRICTS) == _sha256(FRONTEND_DISTRICTS), (
            "thailand_districts.json สองสำเนาไม่ตรงกัน — รัน generate_districts.py "
            "แล้วต่อด้วย add_district_th_names.py (เขียนครบทั้งสองที่ในรอบเดียว)")


class TestLoadedGeometries:
    """ผลลัพธ์ที่โมดูลโหลดไว้จริงตอน import — ไม่ใช่แค่ไฟล์มีอยู่"""

    def test_provinces_loaded(self):
        assert len(PROVINCE_GEOMETRIES) == EXPECTED_PROVINCES

    def test_districts_loaded(self):
        assert len(DISTRICT_GEOMETRIES) == EXPECTED_DISTRICTS, (
            "DISTRICT_GEOMETRIES ว่าง/ไม่ครบ = endpoint อำเภอจะ 404")

    def test_districts_keyed_by_province_and_name(self):
        # key เป็น (province, name) โดย name เป็นชื่ออังกฤษแบบไม่มีช่องว่าง (GADM)
        assert ('Chiang Mai', 'ChomThong') in DISTRICT_GEOMETRIES

    def test_districts_grouped_under_their_province(self):
        chiang_mai = [d for (p, d) in DISTRICT_GEOMETRIES if p == 'Chiang Mai']
        assert len(chiang_mai) == 24

    def test_every_district_province_is_a_known_province(self):
        """province ของทุกอำเภอต้อง match ชื่อใน thailand.json — ถ้าไม่ตรง
        get_district_geom() จะหาไม่เจอทั้งที่ไฟล์มีข้อมูลอยู่"""
        unknown = sorted({p for (p, _) in DISTRICT_GEOMETRIES
                          if p not in PROVINCE_GEOMETRIES})
        assert not unknown, f"จังหวัดที่ไม่รู้จัก: {unknown}"

    def test_every_district_has_thai_name(self):
        """name_th ต้องถูก patch ครบ — add_district_th_names.py เป็นขั้นสุดท้ายของ
        pipeline ถ้าลืมรัน สำเนาที่ deploy ไปจะโชว์ชื่ออังกฤษบน UI ไทย"""
        missing = [f['properties'].get('name')
                   for f in _features(BACKEND_DISTRICTS)
                   if not f['properties'].get('name_th')]
        assert not missing, f"อำเภอที่ไม่มี name_th: {missing[:10]}"

    def test_backend_prefers_data_dir_over_legacy_path(self):
        """resolution order ต้องหยิบ data/ ก่อน ../green-area-frontend/public/ —
        data/ เป็นที่เดียวที่มีอยู่ใน Docker image"""
        resolved = _resolve_geojson_path('THAILAND_GEOJSON_PATH', 'thailand.json')
        assert os.path.realpath(resolved) == os.path.realpath(BACKEND_THAILAND)


class TestEnvOverrideFailsLoudly:
    """env override ที่ตั้งมาแต่ path ผิด ต้อง raise ไม่ใช่เงียบแล้ว fallback

    ถ้า fallback เงียบ ผู้ดูแลที่พิมพ์ path ผิดจะเห็นระบบทำงานปกติแล้วเข้าใจว่าตั้งค่า
    สำเร็จ ทั้งที่ระบบอ่านไฟล์อื่นอยู่"""

    def test_missing_file_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv('THAILAND_GEOJSON_PATH', str(tmp_path / 'nope.json'))
        with pytest.raises(RuntimeError, match='THAILAND_GEOJSON_PATH'):
            _resolve_geojson_path('THAILAND_GEOJSON_PATH', 'thailand.json')

    def test_wrong_extension_raises(self, monkeypatch, tmp_path):
        bad = tmp_path / 'boundaries.txt'
        bad.write_text('{}', encoding='utf-8')
        monkeypatch.setenv('DISTRICTS_GEOJSON_PATH', str(bad))
        with pytest.raises(RuntimeError, match='DISTRICTS_GEOJSON_PATH'):
            _resolve_geojson_path('DISTRICTS_GEOJSON_PATH', 'thailand_districts.json')

    def test_error_names_the_bad_path_and_how_to_recover(self, monkeypatch, tmp_path):
        bogus = str(tmp_path / 'typo.json')
        monkeypatch.setenv('THAILAND_GEOJSON_PATH', bogus)
        with pytest.raises(RuntimeError) as exc:
            _resolve_geojson_path('THAILAND_GEOJSON_PATH', 'thailand.json')
        assert bogus in str(exc.value)          # บอกว่าค่าที่ตั้งไว้คืออะไร
        assert 'unset' in str(exc.value)        # บอกทางออก

    def test_valid_override_is_used(self, monkeypatch):
        """override ที่ถูกต้องยังต้องทำงานเหมือนเดิม (ไม่ได้ปิดฟีเจอร์นี้ทิ้ง)"""
        monkeypatch.setenv('THAILAND_GEOJSON_PATH', FRONTEND_THAILAND)
        resolved = _resolve_geojson_path('THAILAND_GEOJSON_PATH', 'thailand.json')
        assert os.path.realpath(resolved) == os.path.realpath(FRONTEND_THAILAND)

    def test_unset_falls_back_silently_as_before(self, monkeypatch):
        """ไม่ตั้ง env = fallback ตามลำดับเดิม ไม่ raise"""
        monkeypatch.delenv('THAILAND_GEOJSON_PATH', raising=False)
        assert _resolve_geojson_path('THAILAND_GEOJSON_PATH', 'thailand.json')
