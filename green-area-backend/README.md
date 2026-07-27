# Green Area Backend

FastAPI + Google Earth Engine + Supabase cache

ดู [../README.md](../README.md) สำหรับ architecture และ setup ทั้งหมด — ไฟล์นี้เก็บเฉพาะ
รายละเอียดเฉพาะ backend

## Auth

ทุก endpoint ข้อมูล (NDVI/LST/recommend/maps/analysis/saved) ต้องแนบ
`Authorization: Bearer <supabase-access-token>` — token ออกโดย Supabase Auth ฝั่ง
frontend (supabase-js) · backend verify ในเครื่องด้วย JWKS (ไม่ยิง network ทุก request)
แล้ว fallback ไป `auth.get_user()` ถ้าเป็นโปรเจกต์ legacy HS256 (ดู `dependencies.py::require_user`)

ยกเว้น: `/health`, `/`, `/analysis/ranking` (teaser หน้า Landing ก่อนล็อกอิน) · endpoint
admin (`DELETE /cache`) รับได้ทั้ง `X-Admin-Token` หรือ user ที่มี `profiles.role = 'admin'`

## Endpoints (สรุป)

| Method | Path | อธิบาย |
|---|---|---|
| GET | `/ndvi/{province}` | NDVI annual ของจังหวัด + dense forest + green/person |
| GET | `/ndvi/{province}/monthly` | NDVI 12 เดือน |
| GET | `/ndvi/{province}/compare` | เทียบ NDVI 2 ปี (สำหรับ swipe/diff) |
| GET | `/ndvi/{province}/districts/{district}` · `/.../monthly` | NDVI ของอำเภอ (annual / 12 เดือน) |
| GET | `/lst/{province}` · `/lst/{province}/monthly` | Land Surface Temperature (annual / 12 เดือน) |
| GET | `/lst/{province}/districts/{district}` · `/.../monthly` | LST อำเภอ (annual / monthly) |
| GET | `/recommend/{province}` | AI Priority heatmap + top-N spots (พร้อมป้ายการใช้ที่ดิน + พันธุ์ไม้) |
| GET | `/recommend/{province}/districts/{district}` | AI Recommend ระดับอำเภอ |
| POST | `/recommend/custom-area` | AI Recommend บน polygon ที่ผู้ใช้วาดเอง |
| GET | `/analysis/landuse/{province}?source=dynamic_world\|ldd` | สัดส่วนการใช้ที่ดิน 5 ประเภท (Dynamic World / LDD) |
| GET | `/analysis/urban-subset/{province}` | NDVI + green/person ในเขต built-up (WorldCover) |
| GET | `/analysis/districts/{province}` | NDVI + green/person รายอำเภอทั้งจังหวัด |
| GET | `/analysis/cooling/{province}` | ศักยภาพลดความร้อน (NDVI ↔ LST) |
| GET | `/analysis/context/{province}` | บริบทจังหวัด (mini-map + สถิติสรุป) |
| GET | `/analysis/timeseries/{province}` | NDVI+LST รายปีจาก cache + Mann-Kendall + forecast 3 ปี (95% PI) |
| POST | `/analysis/custom-area` | วิเคราะห์ polygon ที่วาดเอง — NDVI/green/ป่าทึบ + ประชากร (WorldPop จริง) + WHO m²/คน + LST |
| GET | `/analysis/ranking?year=2026` | อันดับจังหวัดตาม green/person (WHO) — **ไม่ต้องล็อกอิน** (teaser) |
| GET | `/maps/{province}/ndvi-tiles` · `lst-tiles` · `landuse-tiles` | raster tile URL (XYZ) ซ้อนบนแผนที่ |
| GET | `/maps/{province}/ndvi-diff-tiles` · `lst-diff-tiles` | tile ส่วนต่าง 2 ปี (swipe compare) |
| GET | `/maps/{province}/ndvi-thumb` · `lst-thumb` · `/maps/thailand-thumb` | PNG thumbnail (matplotlib) |
| GET | `/timelapse/ndvi/provinces` · `/timelapse/lst/provinces` | ค่า annual ทุกจังหวัดใน range — time-lapse animation |
| GET | `/compare?provinces=A,B&year=2026` | เปรียบเทียบหลายจังหวัด |
| POST | `/saved-areas` | บันทึก polygon ที่วาด + ผลวิเคราะห์ (ผูก `user_id` ของผู้ใช้ที่ล็อกอิน) |
| GET | `/saved-areas` · `/saved-areas/{id}` | รายการ / รายละเอียดพื้นที่ที่บันทึก (flag `mine`) |
| DELETE | `/saved-areas/{id}` | ลบพื้นที่ — เฉพาะเจ้าของ (`user_id` / owner-token legacy) หรือ admin |
| GET | `/account/me` | โปรไฟล์ผู้ใช้ปัจจุบัน (display_name, role, organization) |
| PATCH | `/account/me` | แก้ display_name / organization |
| DELETE | `/account/me` | ลบบัญชีถาวร (auth.users + profiles + saved_areas ที่ผูกไว้) |
| GET | `/cache` · `/cache/districts` | ดูสถานะ cache |
| DELETE | `/cache` · `/cache/{province}` | ล้าง cache (`X-Admin-Token: $ADMIN_TOKEN` หรือ user role=admin) |
| GET | `/health` | liveness probe (ไม่แตะ DB/GEE) — สำหรับ load-balancer |

API docs interactive: `http://localhost:8000/docs`

## Logging

ทุก module ใช้ `logging.getLogger(__name__)` กำหนด level ผ่าน `LOG_LEVEL` env
(`INFO` / `DEBUG` / `WARNING`) — config ถูกตั้งใน `main.py` พร้อม UTF-8 stream เพื่อ
รองรับ emoji + ไทย บน Windows console

## Schema

ตาราง Supabase ทั้งหมดอยู่ใน `migrations/000_initial_schema.sql` รัน migration เพิ่มเติม
(ถ้ามี) ตามลำดับเลข

`provinces` (migration 006) เป็นตารางอ้างอิงที่ normalize ชื่อไทย + ภาค ของ 77 จังหวัด
ไว้ที่เดียว (single source of truth) แล้วตารางข้อมูลอื่น FK → `provinces(name_en)` ·
`species.py::_region_for` อ่านภาคจากตารางนี้ก่อน (fallback ไป `PROVINCE_REGION` hardcoded
ถ้า DB ยังไม่มีข้อมูล)

`districts` (migration 007) เป็นตารางอ้างอิงระดับอำเภอ (928 อำเภอ + พื้นที่ km²) ·
4 ตารางอำเภอทำ composite FK `(province, district)` → `districts(province, name_en)` ·
ไม่ต้องแก้ logic เดิม (FK ระดับ DB) — `district` ยังเป็น text เหมือนเดิม

`ndvi_annual` / `district_ndvi_annual` มีคอลัมน์ `data_quality` (jsonb, migration 014)
เก็บคุณภาพของ median composite ที่ใช้คำนวณ NDVI ปีนั้น — จำนวนภาพ, observation
ปลอดเมฆเฉลี่ย/ต่ำสุดต่อ pixel, σ ของ NDVI ในปี, ความไม่แน่นอนของค่ากลาง
(standard error ของ median = 1.2533·σ/√n · σ มีพื้นขั้นต่ำ 0.06 NDVI จาก RMSE
การ validate Sentinel-2 กับเซนเซอร์ภาคพื้นดิน), เดือน/ฤดูที่มี-ไม่มีภาพ และระดับ
`goal`/`threshold`/`below` ตามเกณฑ์ **GCOS-245** (FAPAR: 2σ ≤ 5% Goal · ≤ 10%
Threshold) — ฤดูใช้นิยามกรมอุตุนิยมวิทยา · ส่งกลับพร้อมค่า NDVI ทุก endpoint
(ดู `schemas.py::NDVIDataQuality` · ที่มาของทุกเกณฑ์อยู่ใน `REQUIREMENTS.md` `[R33]`–`[R35]`)

`ndvi_annual` / `district_ndvi_annual` มีคอลัมน์ `canopy` (jsonb, migration 015) เก็บ
ตัวชี้วัดเรือนยอดไม้เทียบเกณฑ์ **30% ของกฎ 3-30-300** (FR-17 · `[R2]`) — สร้างใน
`canopy.py::build_canopy` โดย `canopy_area_bands` เกาะ `reduceRegion` ก้อนเดียวกับ NDVI
จึงไม่เพิ่ม round-trip ไป GEE · **ต่างจาก `green_area_pct`**: ตัวนั้นคือ NDVI > 0.3 =
พืชพรรณทุกชนิด (ตอบ WHO m²/คน) ส่วนตัวนี้นับเฉพาะคลาสต้นไม้จากการจำแนก land cover

- **ค่าระดับ** มาจาก ESA WorldCover v200 ซึ่งมี epoch เดียว (2021) → *ไม่เปลี่ยนตามปีที่
  เลือก* จึงต้องแสดง `epoch_year` คู่กับตัวเลขเสมอ
- **แนวโน้ม** (`canopy.trend`) มาจาก Dynamic World เทียบปีฐาน 2021 — DW ตรวจไม่เจอเรือนยอด
  ในเขตเมือง (วัดจริง: ปทุมวัน 1.7% vs WorldCover 14.6%) จึงอ่านได้เฉพาะ *ทิศทาง*
  ไม่ใช่ระดับ · ตารางเทียบเต็มอยู่ใน docstring ของ `canopy.py` และ `REQUIREMENTS.md` §5
- `_fractional_area` รวมสัดส่วนเรือนยอดที่ 10 ม. ด้วย `reduceResolution` ก่อนย่อลง scale
  ที่ reduce — ไม่งั้น pyramid แบบ MODE จะกลืนเรือนยอดกระจัดกระจายในเมืองหายไปทั้งหมด

(ดู `schemas.py::CanopyCover` / `CanopyTrend`)

## ออกแบบ cache (สรุป)

- ทุก endpoint ที่ trigger GEE compute ราคาแพง → check cache ก่อน
- Cache key = `(province, district?, year)` — district nullable
- Stale check ใน `routers/ndvi/compute.py::_is_stale` — invalidate row ที่คำนวณก่อนยุค water mask
  และ row ที่ยังไม่มี `data_quality` (ก่อน migration 014) หรือ `canopy` (ก่อน migration 015)
  → recompute เองเมื่อมีคนเปิดจังหวัด/อำเภอนั้น · **ต้องรัน migration ก่อน deploy**
  ไม่งั้น row เดิมจะถูกลบทิ้งแล้ว insert ใหม่ไม่ผ่านเพราะยังไม่มีคอลัมน์
- AI Recommend + raster overlay tile URL หมดอายุพร้อม GEE session — มี in-process TTL
  cache 30 นาที (thread-safe `ttl_cache.py::TTLCache` ใช้ร่วมกันทั้ง
  `routers/recommend/tile_cache.py` และ `routers/maps/tiles.py`) ลดต้นทุน cache hit จาก ~30s → <50ms

## Tests

รันด้วย `.venv/bin/pytest tests/ -v` (รันใน CI ทุก push/PR · ดู
`../.github/workflows/ci.yml`)

| ไฟล์ | ครอบคลุม |
|---|---|
| `tests/test_stats_utils.py` | `linregress` (slope/r) + Mann-Kendall trend significance + `forecast_linear` (OLS projection + 95% prediction interval) |
| `tests/test_pure_helpers.py` | `_is_stale` (cache invalidation), WHO status (9 m²/คน), normalize weights, validate geojson path, estimate impact (จำนวนต้นไม้ / cooling / CO₂ / รถยนต์ + สัมประสิทธิ์พันธุ์ไม้ไทย), validate polygon + geodesic area (custom-area) |
| `tests/test_recommend_metrics.py` | recommend compute payload — อ่านตารางถูกระดับ (province vs district + district filter) + คืน `None` เมื่อ cache ว่าง/DB error |
| `tests/test_ndvi_quality.py` | คุณภาพ/ความไม่แน่นอนของ NDVI composite — สรุปช่วงวัน/เดือน/ฤดู (นิยาม TMD) จาก `system:time_start`, standard error ของ median + พื้น σ ของเซนเซอร์ (กันเคส n=1 ดูแม่นสมบูรณ์), จัดระดับตามเกณฑ์ GCOS-245, ข้อความเตือนเมื่อใช้เกณฑ์เมฆสำรอง |
| `tests/test_landuse.py` · `test_ldd.py` | mapping Dynamic World 9 คลาส → 5 ประเภท LDD + ตาราง 96 ประเภท LDD 1:25,000 + guidance ต่อประเภท |
| `tests/test_auth_dependencies.py` | `require_user` (verify JWT local/fallback, token หมดอายุ/ปลอม) + `require_admin_or_user` (admin token / role=admin) |
| `tests/test_keyed_lock.py` | per-key compute lock — กัน GEE cache stampede (ล็อกต่อ key ไม่บล็อกทั้งระบบ) |
| `tests/test_endpoints.py` | API endpoints (`/`, `/compare`, `/cache`, `/analysis/ranking`, `/timelapse` ทั้ง NDVI/LST, `/analysis/cooling`, POST `/analysis/custom-area` + `/recommend/custom-area` validation, `/saved-areas` CRUD + ownership/admin auth) + auth gate (endpoint ที่ต้องล็อกอิน reject anonymous · `/ranking` + `/health` ยัง public) ผ่าน FastAPI `TestClient` + mock `supa_call` |
| `tests/test_ttl_cache.py` | `TTLCache` (shared tile-URL cache) — hit/miss, TTL expiry, size-bounded eviction, thread-safe concurrent `set()` |

Pure helpers ทดสอบได้โดยไม่ต้องมี credential · endpoint tests mock ทุก call ไป
Supabase/GEE จึงไม่แตะ external service จริง
