from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Annotated
from fastapi import Header, HTTPException, Query
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime
import httpx
import json
import logging
import os
import secrets
import time

load_dotenv()
logger = logging.getLogger(__name__)

CURRENT_YEAR = datetime.now().year
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")
WHO_STANDARD_M2 = 9

# ปี WorldPop (GP/100m/pop) ที่ใช้คำนวณประชากร — coverage ใน GEE = 2000–2020
# 2021 ไม่มีจริงสำหรับ THA → default 2020 (ปีล่าสุด) · override ผ่าน env ได้
# นิยามที่เดียวให้ทั้ง /recommend (scoring) และ /analysis/urban-subset ใช้ร่วมกัน กันค่า drift
WORLDPOP_YEAR = int(os.getenv("WORLDPOP_YEAR", "2020"))

# Cache schema version — bump เมื่อเปลี่ยน compute logic ที่ทำให้ค่าเก่าไม่ valid
# (เช่น เพิ่ม water mask, เปลี่ยน NDVI threshold)
# _is_stale() จะถือว่า row ที่ cache_version < CURRENT_CACHE_VERSION = stale
# v1 → v2: เปลี่ยน cloud masking จาก QA60 เป็น Cloud Score+ (gee_utils) → NDVI ทุกค่า
#          ที่ cache ด้วย QA60 (โดยเฉพาะปี 2022–2024 ที่ QA60 ว่าง) ถือว่า stale
CURRENT_CACHE_VERSION = 2

# Recommend cache version — แยกจาก CURRENT_CACHE_VERSION (NDVI/LST/urban) เพราะ
# compute logic ของ /recommend เปลี่ยนคนละจังหวะ · bump เมื่อแก้ priority/plantable/
# impact logic ที่ทำให้ค่า cache เก่าไม่ valid · v1 = plantability mask (ESA WorldCover)
# + Cloud Score+ NDVI + relative-LST anomaly · row เก่าถูก migration 008 ตั้งเป็น 0 → stale
# v1 → v2: unmask(0) ให้ ndvi_deficit → priority นิยามครบทุก pixel แม้ S2 median masked
#          (heatmap ไม่เป็นรู) ทำให้ top_locations/impact ที่ cache ด้วย v1 ต่างไป → stale
# v2 → v3: เพิ่มปัจจัยที่ 4 access_need (ระยะถึงพื้นที่สีเขียวเดิม) + rebalance default
#          weights → priority/top_locations เปลี่ยน → row ที่ cache ด้วย v2 stale
# v3 → v4: ปักหมุด scale ของ fastDistanceTransform (access_need) ให้ distance เป็นเมตรจริง
#          ไม่เพี้ยนตาม scale → access_need (จึง priority/top_locations) ที่ cache ด้วย v3 stale
# v4 → v5: top_locations เปลี่ยนวิธี sample — คัด priority เปอร์เซ็นไทล์สูง (เฉพาะ plantable)
#          ก่อนแล้วทุ่ม sample ลงโซน hotspot + seed คงที่ (เดิมสุ่มทั่ว geom จับ pixel สูงสุด
#          จริงพลาดในจังหวัดใหญ่) → top_locations ที่ cache ด้วย v4 ต่างไป → stale
# v5 → v6: เพิ่มปัจจัย peri-urban (โอกาสลดร้อนสูงสุดที่ขอบเมืองกำลังขยาย, จาก Moukomla
#          et al. 2026) เป็น slice คงที่ W_PERI ใน priority → heatmap/top_locations ที่
#          cache ด้วย v5 ต่างไป (+ factors เพิ่ม peri_urban) → stale
RECOMMEND_CACHE_VERSION = 6
MONTH_NAMES = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.',
               'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']

# ขอบเขตปีที่ยอมรับได้ — Sentinel-2 เริ่ม 2015, Landsat 8 เริ่ม 2013
# เลือก 1980 เป็น lower bound เผื่อ dataset อื่นในอนาคต, +1 เผื่อปีหน้าตอน rollover
YEAR_MIN = 1980
YEAR_MAX = CURRENT_YEAR + 1
YearParam = Annotated[int, Query(
    ge=YEAR_MIN, le=YEAR_MAX,
    description=f"ปี ค.ศ. ระหว่าง {YEAR_MIN}–{YEAR_MAX}",
)]

# น้ำหนัก priority (NDVI/LST/pop) — บังคับ 0–1 ตั้งแต่ชั้น validation กัน
# ค่าติดลบที่ผ่าน normalize_weights() (total > 0) แล้วได้ priority image พิกล
# โดยไม่มี error · ค่าจะถูก normalize ให้รวมเป็น 1 อีกชั้นใน scoring
WeightParam = Annotated[float, Query(
    ge=0, le=1,
    description="น้ำหนัก 0–1 (normalize รวมเป็น 1 อัตโนมัติ)",
)]


def require_admin(x_admin_token: str | None = Header(default=None)):
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=503,
                            detail="ADMIN_TOKEN ยังไม่ตั้งค่าใน .env — endpoint นี้ปิดใช้งาน")
    # ใช้ compare_digest กัน timing attack ที่เทียบ string ทีละ byte
    if not x_admin_token or not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY ไม่ถูกตั้งค่าใน .env")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# httpx exceptions ที่บ่งชี้ว่า connection ตายระหว่างทาง
# (Supabase / Cloudflare ตัด idle connection แต่ httpx ยัง pool ค้างไว้)
_TRANSIENT_ERRORS = (
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
)


def internal_error(message: str = "เกิดข้อผิดพลาดภายในระบบ — ดู logs สำหรับรายละเอียด"):
    """สร้าง HTTPException 500 ที่ไม่ leak stack trace/secrets ไป client
    เรียก helper นี้แทน `HTTPException(500, detail=str(e))` ทุกที่"""
    return HTTPException(status_code=500, detail=message)


def worldpop_unavailable_error(year: int = WORLDPOP_YEAR):
    """HTTPException 503 มาตรฐานเมื่อ WorldPop ไม่มีปีที่ตั้งไว้ใน GEE catalog.

    ข้อความเดียวกันทุก path (recommend / urban-subset / custom-area) กัน drift —
    WorldPop ขาด = config issue ฝั่ง server (WORLDPOP_YEAR) ไม่ใช่เรื่องของปีที่ผู้ใช้ขอ
    คู่กับ gee_utils.worldpop_pop_collection ที่ build collection"""
    return HTTPException(status_code=503, detail=(
        f"WorldPop ปี {year} ไม่มีในระบบ — ตั้งค่า WORLDPOP_YEAR "
        "เป็นปีที่มีข้อมูลใน GEE catalog (ปกติ 2000–2020)"
    ))


def supa_call(builder_fn, retries: int = 1):
    """เรียก Supabase พร้อม retry เมื่อเจอ stale connection.

    Args:
        builder_fn: callable(supabase_client) -> APIResponse
                    ต้องสร้าง query chain ใหม่ทุกครั้ง เพราะหลัง disconnect
                    client ตัวเก่าใช้ไม่ได้แล้ว
        retries:    จำนวนครั้งที่ retry เพิ่มเติม (default 1 → รวมทั้งหมด 2 ครั้ง)
    """
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return builder_fn(get_supabase())
        except _TRANSIENT_ERRORS as e:
            last_exc = e
            if attempt < retries:
                logger.warning("⚠️  Supabase %s: %s — recreate client + retry (%d/%d)",
                               type(e).__name__, e, attempt + 1, retries)
                # ทิ้ง client เก่าทั้ง connection pool แล้วสร้างใหม่ในรอบถัดไป
                get_supabase.cache_clear()
                time.sleep(0.3 * (attempt + 1))  # backoff สั้นๆ
                continue
            raise
    # ไม่ควรมาถึง — แต่กัน type checker
    raise last_exc  # type: ignore[misc]


def gather(*funcs):
    """รัน callable หลายตัวขนานกันใน thread แล้วคืนผลตามลำดับเดิม.

    ใช้กับ endpoint ที่ query DB หลายตารางแบบไม่พึ่งผลกัน (เช่น NDVI + LST รายอำเภอ) —
    httpx.Client ที่ supabase-py ใช้ thread-safe จึง share client ข้าม thread ได้ ·
    exception จาก func ใดๆ จะ propagate ออกมา (error handling เดิมไม่เปลี่ยน)
    """
    with ThreadPoolExecutor(max_workers=len(funcs)) as ex:
        futures = [ex.submit(fn) for fn in funcs]
        return [f.result() for f in futures]


def get_population(province_name: str, year: int) -> tuple[int | None, int | None]:
    """คืน (population, population_year) ของจังหวัด.

    ถ้าปีที่ขอไม่มีใน province_population → fallback ไปปีล่าสุดที่มี แล้ว *คืนปีจริง*
    ที่ใช้มาด้วย เพื่อให้ caller บอกผู้ใช้ได้ว่า m²/คน คำนวณบนประชากรปีไหน (NDVI อาจ
    เป็นคนละปี เช่น ขอ NDVI 2024 แต่ประชากรมีถึง 2022) · คืน (None, None) ถ้าไม่มี
    ข้อมูลประชากรของจังหวัดนี้เลย
    ใช้ supa_call เพื่อให้ได้ retry-on-disconnect — ไม่ต้องรับ Client มาเองแล้ว"""
    result = supa_call(lambda s: s.table("province_population")
                       .select("population,year")
                       .eq("province", province_name)
                       .eq("year", year)
                       .execute())
    if result.data:
        return result.data[0]["population"], year
    fallback = supa_call(lambda s: s.table("province_population")
                         .select("population,year")
                         .eq("province", province_name)
                         .order("year", desc=True)
                         .limit(1)
                         .execute())
    if fallback.data:
        return fallback.data[0]["population"], fallback.data[0]["year"]
    return None, None


BACKEND_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DATA_DIR = os.path.join(BACKEND_ROOT, 'data')
# legacy dev-local path — รองรับ monorepo workflow ที่ frontend/backend อยู่คู่กัน
LEGACY_FRONTEND_PUBLIC = os.path.join(BACKEND_ROOT, '..',
                                      'green-area-frontend', 'public')


def _validate_geojson_path(path: str) -> str:
    """Resolve + validate ว่าเป็นไฟล์ .json ที่อ่านได้ (ป้องกัน path traversal)"""
    resolved = os.path.realpath(path)
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"ไม่พบไฟล์: {path} (resolved: {resolved})")
    if not resolved.lower().endswith('.json'):
        raise ValueError(f"GeoJSON path ต้องลงท้ายด้วย .json: {resolved}")
    return resolved


def _resolve_geojson_path(env_var: str, fallback_name: str) -> str | None:
    """หา path ของ geojson ตามลำดับ:
       1) env var override → 2) backend/data/ → 3) ../green-area-frontend/public/ (legacy)

    ทุก path ผ่าน _validate_geojson_path กัน path traversal/symlink + ไฟล์ไม่ใช่ .json
    Return None ถ้าหาไม่เจอเลย (caller ตัดสินใจว่าจะ warn หรือ raise)
    """
    candidates = []
    override = os.getenv(env_var)
    if override:
        candidates.append(override)
    candidates.append(os.path.join(BACKEND_DATA_DIR, fallback_name))
    candidates.append(os.path.join(LEGACY_FRONTEND_PUBLIC, fallback_name))

    for cand in candidates:
        try:
            return _validate_geojson_path(cand)
        except (FileNotFoundError, ValueError):
            continue
    return None


def _load_province_geometries() -> dict:
    path = _resolve_geojson_path('THAILAND_GEOJSON_PATH', 'thailand.json')
    if not path:
        raise RuntimeError(
            "ไม่พบ thailand.json — วางที่ green-area-backend/data/thailand.json "
            "หรือตั้ง env THAILAND_GEOJSON_PATH"
        )
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    return {feat['properties']['name']: feat['geometry'] for feat in data['features']}


def _load_district_geometries() -> dict:
    path = _resolve_geojson_path('DISTRICTS_GEOJSON_PATH', 'thailand_districts.json')
    if not path:
        logger.warning("⚠️  thailand_districts.json ไม่พบ — รัน generate_districts.py ก่อน")
        return {}
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    result = {}
    for feat in data['features']:
        p = feat['properties'].get('province', '')
        d = feat['properties'].get('name', '')
        if p and d:
            result[(p, d)] = feat['geometry']
    return result


def load_thailand_geojson_raw() -> dict | None:
    """โหลด thailand.json ดิบ (ทั้ง FeatureCollection) — ใช้ใน maps.py สำหรับ render
    mini-map. กลับ None ถ้าไม่เจอไฟล์"""
    path = _resolve_geojson_path('THAILAND_GEOJSON_PATH', 'thailand.json')
    if not path:
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


PROVINCE_GEOMETRIES = _load_province_geometries()
logger.info("✅ โหลดขอบเขต %d จังหวัดจาก GADM", len(PROVINCE_GEOMETRIES))


def ensure_province(province_name: str) -> None:
    """Raise 404 ถ้าจังหวัดไม่อยู่ใน PROVINCE_GEOMETRIES.

    รวม guard ที่ทุก endpoint ระดับจังหวัดเคยเขียนซ้ำ ให้สถานะ/ข้อความ
    อยู่ที่เดียว — เรียกแทน `if province_name not in PROVINCE_GEOMETRIES: raise ...`
    """
    if province_name not in PROVINCE_GEOMETRIES:
        raise HTTPException(status_code=404, detail=f"ไม่พบจังหวัด '{province_name}'")

DISTRICT_GEOMETRIES = _load_district_geometries()
logger.info("✅ โหลดขอบเขต %d อำเภอ", len(DISTRICT_GEOMETRIES))


def get_province_geom(province_name: str) -> dict:
    """คืน geometry ของจังหวัด หรือ raise 404 ถ้าไม่เจอ.

    เหมือน ensure_province แต่คืน geom กลับมาด้วย — ใช้แทน pattern
    `geom = PROVINCE_GEOMETRIES.get(...); if not geom: raise 404` ที่ endpoint
    ระดับจังหวัดเขียนซ้ำ เมื่อยังต้องใช้ geom ต่อ
    """
    geom = PROVINCE_GEOMETRIES.get(province_name)
    if not geom:
        raise HTTPException(status_code=404, detail=f"ไม่พบจังหวัด '{province_name}'")
    return geom


def get_district_geom(province_name: str, district_name: str) -> dict:
    """คืน geometry ของอำเภอ หรือ raise 404 ถ้าไม่เจอ — คู่กับ get_province_geom."""
    geom = DISTRICT_GEOMETRIES.get((province_name, district_name))
    if not geom:
        raise HTTPException(
            status_code=404,
            detail=f"ไม่พบอำเภอ '{district_name}' ในจังหวัด '{province_name}'")
    return geom


def ensure_district(province_name: str, district_name: str) -> None:
    """Raise 404 ถ้าอำเภอไม่อยู่ใน DISTRICT_GEOMETRIES — คู่กับ ensure_province
    (validate อย่างเดียว ไม่คืน geom · ใช้ใน endpoint ที่ไม่ต้องใช้ geom เช่น timeseries)"""
    if (province_name, district_name) not in DISTRICT_GEOMETRIES:
        raise HTTPException(
            status_code=404,
            detail=f"ไม่พบอำเภอ '{district_name}' ในจังหวัด '{province_name}'")
