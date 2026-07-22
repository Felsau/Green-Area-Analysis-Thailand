# Green Area Analysis · Thailand

[![CI](https://github.com/Felsau/Project/actions/workflows/ci.yml/badge.svg)](https://github.com/Felsau/Project/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

แดชบอร์ดวิเคราะห์พื้นที่สีเขียวของประเทศไทย ดึงข้อมูลจาก Google Earth Engine
แล้วประมวลผล NDVI / LST / Urban-subset / การใช้ที่ดิน + แนะนำพื้นที่ที่ควรปลูกต้นไม้
(AI Recommend) พร้อมประเมินคุณค่าเชิงนิเวศแบบ i-Tree · เข้าใช้งานผ่านระบบล็อกอิน
(Supabase Auth)

วิทยานิพนธ์ระดับปริญญาตรี · นักศึกษา **Felsau**

---

## Features

- **NDVI / พื้นที่สีเขียว** — รายปี + 12 เดือน · ระดับจังหวัด และอำเภอ · ป่าทึบ (dense forest) + พื้นที่สีเขียวต่อคน (m²/คน) เทียบเกณฑ์ WHO 9 m²
- **LST (อุณหภูมิพื้นผิว)** — รายปี + รายเดือน · คู่กับ NDVI เพื่อดูความสัมพันธ์พื้นที่สีเขียว ↔ ความร้อน (UHI)
- **Land use (การใช้ที่ดิน)** — 5 ประเภทหลักตามกรมพัฒนาที่ดิน (LDD): ชุมชน · เกษตร · ป่าไม้ · น้ำ · เบ็ดเตล็ด · เลือกแหล่งข้อมูลได้ระหว่าง **Dynamic World** (รายปี ทั้งประเทศ) กับ **LDD 1:25,000** (รายจังหวัด, 96 ประเภทละเอียด — ถ้าตั้ง GEE asset)
- **AI Recommend** — heatmap ลำดับความสำคัญพื้นที่ควรปลูก (NDVI deficit + LST anomaly + ความหนาแน่นประชากร + การเข้าถึงพื้นที่สีเขียว + peri-urban) · top-N จุด พร้อมป้ายประเภทการใช้ที่ดิน + แนวทางปลูก + พันธุ์ไม้ไทยที่เหมาะกับพื้นที่
- **i-Tree ecosystem services** — ประเมินจำนวนต้นไม้ / การลดความร้อน / CO₂ / มลพิษอากาศ / การหน่วงน้ำฝน + มูลค่าเป็นบาท
- **แผนที่ interactive** — raster tiles (NDVI / LST / land use) ซ้อนบนแผนที่ 3D (DeckGL) · swipe เปรียบเทียบ 2 ปี · time-lapse animation
- **วาดพื้นที่เอง (custom area)** — วาด polygon บนแผนที่แล้ววิเคราะห์ NDVI/ประชากร/WHO/LST/AI Recommend เฉพาะพื้นที่นั้น · บันทึกไว้ในบัญชีได้
- **รายงาน PDF** — สรุปผลวิเคราะห์ + บริบทการใช้ที่ดิน export เป็น PDF/CSV
- **บัญชีผู้ใช้** — สมัคร/ยืนยันอีเมล (OTP)/ล็อกอิน/ลืมรหัสผ่าน (Supabase Auth) · โปรไฟล์ (ชื่อ, หน่วยงาน) · ลบบัญชีถาวร · role `admin` สำหรับล้าง cache

---

## Architecture

```
┌──────────────────┐        ┌────────────────┐        ┌──────────────────┐
│  React 19 + Deck │  HTTP  │  FastAPI       │  REST  │  Google Earth    │
│  GL + MapLibre   │ <────> │  (uvicorn)     │ <────> │  Engine          │
└────────┬─────────┘        └───────┬────────┘        └──────────────────┘
         │                          │
         │ supabase-js              │ supabase-py (service-role)
         │ (auth: sign-in/JWT)      │ verify JWT (JWKS) + cache read/write
         ▼                          ▼
    ┌─────────────────────────────────────────┐
    │  Supabase                               │
    │  · Auth (GoTrue)  — บัญชีผู้ใช้ + JWT      │
    │  · Postgres       — cache 15 ตาราง       │
    └─────────────────────────────────────────┘
```

- **Frontend** ([green-area-frontend/](green-area-frontend/)) — React 19 + Vite, DeckGL 3D extrusion + raster tiles, MapLibre GL, Turf.js (วาด polygon), Recharts, jsPDF + html2canvas (รายงาน), supabase-js (auth)
- **Backend** ([green-area-backend/](green-area-backend/)) — FastAPI, supabase-py, earthengine-api, PyJWT (verify Supabase token ในเครื่องด้วย JWKS), matplotlib + Pillow (thumbnails), slowapi (rate limit)
- **Database / Auth** — Supabase: Auth (GoTrue) จัดการบัญชีผู้ใช้ + ออก JWT · Postgres 15 ตาราง — cache หลีกเลี่ยง GEE compute ซ้ำ (NDVI/LST/urban/recommend รายจังหวัด+รายอำเภอ) + ตารางอ้างอิง `provinces` / `districts` / `province_population` (normalize ชื่อไทย/ภาค/พื้นที่/ประชากร) + `saved_areas` (พื้นที่ที่ผู้ใช้วาดเอง) + `profiles` (โปรไฟล์ + role ผูกกับ `auth.users`)

---

## Quick start

### 1) Supabase setup

- สร้าง project ใหม่ใน https://supabase.com
- เปิด SQL Editor รัน migration ตามลำดับ (ดู [green-area-backend/migrations/](green-area-backend/migrations/)):
  - `000_initial_schema.sql` (สร้างตาราง cache + reference ทั้งหมด)
  - `001_add_dense_area_columns.sql` (เพิ่ม column dense forest)
  - `002_constraints_and_cache_meta.sql` (CHECK constraints + cache_version + index)
  - `003_add_impact_column.sql` (เพิ่ม column impact ใน planting_recommendations)
  - `004_drop_unused_expires_at.sql` (ลบ expires_at ที่เลิกใช้ — tile URL ย้ายไป in-process cache)
  - `005_create_saved_areas.sql` (ตาราง saved_areas — บันทึก polygon ที่วาดเอง + ผลวิเคราะห์)
  - `006_create_provinces.sql` (ตารางอ้างอิง provinces + seed 77 จังหวัด + FK — normalize ชื่อไทย/ภาค)
  - `007_create_districts.sql` (ตารางอ้างอิง districts + seed 928 อำเภอ + พื้นที่ + composite FK)
  - `008_recommend_cache_version.sql` (cache_version ใน planting_recommendations)
  - `009_add_population_year.sql` (เพิ่ม population_year ใน ndvi_annual — บอกปีประชากรที่ใช้คำนวณ m²/คน)
  - `010_create_profiles.sql` (สร้างตาราง `profiles` + trigger สร้างแถวอัตโนมัติเมื่อมีผู้ใช้สมัคร — คู่กับ Supabase Auth)
  - `011_profiles_consent_and_updated_at.sql` (accepted_terms_at หลักฐานยินยอม PDPA + updated_at)
  - `012_profiles_organization.sql` (เพิ่ม column organization — หน่วยงาน, ไม่บังคับ)
  - `013_saved_areas_user_id.sql` (ผูก saved_areas กับ user_id — ลบบัญชีแล้วพื้นที่ที่บันทึกถูกลบตาม)
- **ตั้งค่า Supabase Auth (จำเป็นสำหรับระบบล็อกอิน)** — ในหน้า Dashboard:
  1. **Authentication → Providers → Email** — เปิด "Confirm email"
  2. **Authentication → Email Templates → "Confirm signup"** — template default เป็น magic link · เปลี่ยนให้แสดง `{{ .Token }}` (OTP 6 หลัก) เพราะหน้า verify ของแอปรอรับเป็นรหัส เช่น `<p>รหัสยืนยัน GreenLens: {{ .Token }}</p>`
  3. **Authentication → URL Configuration → Site URL / Redirect URLs** — ใส่ URL ของแอป (`http://localhost:3000` สำหรับ dev) ให้ลิงก์รีเซ็ตรหัสผ่านเด้งกลับมาถูก
- เอา `URL`, `service_role` key (backend) และ `anon` key (frontend) จากหน้า Project Settings → API

### 2) Backend

```powershell
cd green-area-backend
python -m venv venv
venv\Scripts\activate          # Mac/Linux: source venv/bin/activate
pip install -r requirements.txt

# สร้าง .env (ดูตัวอย่างใน .env.example)
copy .env.example .env
# แก้ค่า SUPABASE_URL, SUPABASE_KEY (service_role), GEE_PROJECT, ADMIN_TOKEN

# โหลด GEE credentials (ทำครั้งเดียว)
earthengine authenticate

# Generate ขอบเขตอำเภอ (ทำครั้งเดียว — สร้าง thailand_districts.json
# พร้อมใส่ชื่ออำเภอภาษาไทย name_th ให้อัตโนมัติ เพื่อให้ป้ายบนแผนที่อ่านเป็นไทย)
python generate_districts.py

# Run
uvicorn main:app --reload
# → http://localhost:8000/docs (Swagger)
```

### 3) Frontend

```powershell
cd green-area-frontend
npm install

# สร้าง .env.local (gitignored) แล้วใส่ค่า Supabase — ดู .env.example
copy .env.example .env.local
# แก้ VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY (anon key ปลอดภัยที่จะ ship ลง browser)
# VITE_API_URL default = http://localhost:8000

npm run dev        # Vite dev server
# → http://localhost:3000
```

---

## รันด้วย Docker

ต้องทำ [Supabase setup](#1-supabase-setup) และ `earthengine authenticate` บนเครื่อง (host) มาก่อน 1 ครั้ง — GEE credentials จะถูก mount เข้า container จาก `~/.config/earthengine`

```bash
cd green-area-backend
copy .env.example .env    # Mac/Linux: cp .env.example .env
# แก้ค่า SUPABASE_URL, SUPABASE_KEY, GEE_PROJECT, ADMIN_TOKEN
cd ..

docker compose up --build
# Backend  → http://localhost:8000/docs
# Frontend → http://localhost:3000
```

`docker-compose.yml` รัน backend ด้วย `uvicorn --reload` และ frontend ด้วย Vite dev server (mount source เข้า container ทั้งคู่ → แก้โค้ดแล้ว hot-reload ได้เหมือน local dev)

Production image ของ frontend (`green-area-frontend/Dockerfile`, target `production`) build เป็น static bundle เสิร์ฟด้วย nginx:

```bash
docker build --target production --build-arg VITE_API_URL=https://your-backend.example.com -t green-area-frontend ./green-area-frontend
```

---

## Environment variables

### Backend (`.env`)

| Variable | จำเป็น | อธิบาย |
|---|---|---|
| `SUPABASE_URL` | ✅ | URL ของ Supabase project |
| `SUPABASE_KEY` | ✅ | `service_role` key (ไม่ใช่ `anon`) — ใช้ query cache, verify token, ลบบัญชี |
| `GEE_PROJECT` | ✅ | Google Cloud project ที่เปิดใช้ Earth Engine |
| `ADMIN_TOKEN` | ⚠️ | ใช้ลบ cache (`DELETE /cache`) — production ต้องเป็น secret สุ่ม ≥ 16 ตัว ไม่งั้น backend refuse start |
| `ALLOWED_ORIGINS` | ⚠️ | CORS origin (default `http://localhost:3000`) — production ต้องใส่ URL ของ frontend |
| `WORLDPOP_YEAR` | – | ปี WorldPop ที่ใช้คำนวณประชากร (default `2020`, ช่วงที่มี 2000–2020) |
| `LDD_LANDUSE_ASSET` | – | GEE FeatureCollection asset ของ LDD 1:25,000 (เช่น `projects/xxx/assets/LU_BKK_2566`) — ไม่ตั้ง = ปุ่ม "LDD ราชการ" ปิด ใช้ Dynamic World แทน (ดู [data/ldd/README.md](green-area-backend/data/ldd/README.md)) |
| `RATE_LIMIT` | – | rate limit ต่อ IP (slowapi format, default `60/minute`) |
| `SLOW_REQUEST_MS` | – | threshold log request ช้า (default `5000`) |
| `LOG_LEVEL` | – | `INFO` (default), `DEBUG`, `WARNING` |
| `THAILAND_GEOJSON_PATH` / `DISTRICTS_GEOJSON_PATH` | – | override path ของ geojson (ดู Deploy notes) |

### Frontend (`.env.local`)

| Variable | จำเป็น | อธิบาย |
|---|---|---|
| `VITE_SUPABASE_URL` | ✅ | URL ของ Supabase project (เดียวกับ backend) |
| `VITE_SUPABASE_ANON_KEY` | ✅ | `anon`/publishable key — ปลอดภัยที่จะ ship ลง browser (RLS คุมสิทธิ์) |
| `VITE_API_URL` | – | URL ของ backend (default `http://localhost:8000`) |

---

## โครงสร้างที่สำคัญ

```
green-area-backend/
  main.py                  # FastAPI app · auth gate ทุก router · /compare /cache /ranking /timelapse
  dependencies.py          # Supabase client, verify JWT (JWKS + fallback), geometry loader, retry
  schemas.py               # Pydantic response models
  gee_utils.py             # cloud mask (Cloud Score+), LST/WorldPop collection, reduce helpers
  landuse.py · ldd.py      # provider การใช้ที่ดิน — Dynamic World + LDD (schema กลาง 5 ประเภท)
  ldd_codes.py             # ตาราง 96 ประเภท LDD 1:25,000 (จับกลุ่มเข้า 5 ประเภทหลัก)
  impact.py                # i-Tree ecosystem services (ต้นไม้/cooling/CO₂/มลพิษ/น้ำฝน + มูลค่า)
  stats_utils.py           # linregress, Mann-Kendall, forecast (95% PI)
  polygon_utils.py         # validate polygon + geodesic area (custom-area)
  ttl_cache.py · keyed_lock.py  # in-process TTL cache (tile URL) + per-key compute lock
  generate_districts.py    # one-time: สร้าง thailand_districts.json (+ add_district_th_names.py)
  migrations/              # SQL schema สำหรับ Supabase (000–013)
  routers/
    account.py             # /account/me — โปรไฟล์ (GET/PATCH) + ลบบัญชี (DELETE)
    saved.py               # /saved-areas — CRUD พื้นที่ที่วาดเอง (ผูก user_id + owner-token fallback)
    ndvi/                  # /ndvi · monthly · district variants (endpoints.py + compute.py)
    lst.py                 # /lst · LST annual + monthly (จังหวัด/อำเภอ)
    maps/
      thumbs.py            # /maps/*-thumb (matplotlib PNG thumbnails)
      tiles.py             # /maps/*-tiles (NDVI/LST/landuse + diff tiles สำหรับ swipe)
      analysis/            # /analysis/* — districts · urban · timeseries · cooling · context · landuse · custom-area
    recommend/             # /recommend · AI priority heatmap (endpoints + scoring + species + tile_cache)

green-area-frontend/
  src/
    App.js                 # entry + DeckGL + AuthGate + hook orchestration
    constants.js           # API_BASE, CURRENT_YEAR, PROVINCE_TH, map styles
    lib/supabaseClient.js  # supabase-js singleton (auth session)
    hooks/                 # useAuth, useProvinceData, useDistrictData, useLanduseData,
                           #   useRecommendData, useRasterOverlay, useSavedAreas, ... (21 hooks)
    components/
      auth/                # AuthGate, SignIn/SignUp/Forgot/Reset screens, LegalModal
      tabs/                # Stats · Trend · Cooling · Compare · Recommend + sub-panels
      draw/                # DrawToolbar, DrawResultCard (custom area)
      ui/                  # Accordion, ExportBar, Metric, Pill (design tokens)
      Landing, AppHeader, Sidebar, MapLegend, SavedAreasPanel, AccountModal, UserMenu, ...
    utils/
      apiClient.js         # authenticated fetch (แนบ Supabase access token)
      export/, reportPdf/  # PDF/CSV report (code-split ออกจาก main bundle)
      mapLayers/, fetchTiles.js, ownerToken.js, ...
  public/
    thailand.json          # ขอบเขตจังหวัด (GADM 4.1)
    thailand_districts.json # ขอบเขตอำเภอ — generate ด้วย generate_districts.py
```

รายการ endpoint ทั้งหมดดู [green-area-backend/README.md](green-area-backend/README.md#endpoints-สรุป) หรือ Swagger ที่ `/docs`

---

## Tests

```powershell
# Frontend (Vitest)
cd green-area-frontend
npm test

# Backend (pytest)
cd green-area-backend
pytest tests/ -v
```

- **Frontend** — smoke render + colorUtils + formatArea + CSV/PDF export helpers + hooks
  (`useProvinceData`, `useDistrictData`) + `ImpactSection`
- **Backend** — pure helpers (stats, WHO status, impact, land use, polygon), auth
  dependencies (verify JWT / admin-or-user), keyed lock, TTL cache, และ endpoint tests ผ่าน
  FastAPI `TestClient` + mock `supa_call` (ดู [green-area-backend/README.md](green-area-backend/README.md#tests))

CI รันทั้งสอง suite + lint (ruff / eslint) + build (vite) + pip-audit ทุก push/PR
(ดู [.github/workflows/ci.yml](.github/workflows/ci.yml))

---

## Deploy notes

- **Frontend** → Vercel/Netlify (Vite static · build `npm run build` → `build/`)
  - ตั้ง env `VITE_API_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` ใน dashboard
  - อย่าลืมเพิ่ม URL production เข้า **Supabase → Authentication → URL Configuration** (Redirect URLs)
- **Backend** → Render/Railway (Python web service)
  - Build: `pip install -r requirements.txt`
  - Start: `uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'`
    - `--proxy-headers` จำเป็นเมื่ออยู่หลัง reverse proxy เพื่อให้ rate-limit เห็น IP จริงของผู้ใช้ (มี [`Procfile`](green-area-backend/Procfile) ให้ใช้แล้ว)
    - production ต้องตั้ง `ADMIN_TOKEN` เป็น secret สุ่มยาว ≥ 16 ตัว — ไม่งั้น backend จะ refuse start
  - ตั้ง `ALLOWED_ORIGINS` ให้ตรงกับ frontend URL
- **Frontend** security headers ตั้งไว้ใน [`vercel.json`](green-area-frontend/vercel.json) / [`netlify.toml`](green-area-frontend/netlify.toml) · CSP เป็น Report-Only — ทดสอบใน browser แล้วค่อยเปลี่ยนเป็น enforcing
- **GeoJSON** (`thailand.json` / `thailand_districts.json`) ระหว่าง 2 service — backend หาตามลำดับ:
  1. ENV `THAILAND_GEOJSON_PATH` / `DISTRICTS_GEOJSON_PATH` (override)
  2. `green-area-backend/data/` (production — copy 2 ไฟล์เข้า image)
  3. `../green-area-frontend/public/` (legacy dev-local แบบ monorepo)

---

## License & data attribution

- **โค้ด** — MIT License (ดู [LICENSE](LICENSE))
- **ข้อมูล/dataset** — แต่ละชุดมี license ของตัวเอง ผู้ใช้ต้องปฏิบัติตามเมื่อนำไปใช้/เผยแพร่ต่อ:
  - Sentinel-2 (ESA Copernicus) · Landsat 8/9 (USGS/NASA, public domain)
  - ESA WorldCover v200 (CC BY 4.0) · WorldPop (CC BY 4.0) · Dynamic World (CC BY 4.0)
  - LDD land use (กรมพัฒนาที่ดิน — ผู้ใช้จัดหา/อัปโหลด GEE asset เอง)
  - GADM 4.1 boundaries (academic/non-commercial) · CARTO + OpenStreetMap basemaps (© OSM, ODbL)
- รายละเอียด dataset + ระเบียบวิธี + อ้างอิงเชิงวิชาการ ดูได้ในเว็บที่ปุ่ม **ⓘ ข้อมูลและระเบียบวิธี** (มุมขวาบน)
