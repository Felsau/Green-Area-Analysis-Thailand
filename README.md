# Green Area Analysis · Thailand

[![CI](https://github.com/Felsau/Project/actions/workflows/ci.yml/badge.svg)](https://github.com/Felsau/Project/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

แดชบอร์ดวิเคราะห์พื้นที่สีเขียวของประเทศไทย ดึงข้อมูลจาก Google Earth Engine
แล้วประมวลผล NDVI / LST / Urban-subset + แนะนำพื้นที่ที่ควรปลูกต้นไม้ (AI Recommend)

วิทยานิพนธ์ระดับปริญญาตรี · นักศึกษา **Felsau**

---

## Architecture

```
┌──────────────────┐        ┌────────────────┐        ┌──────────────────┐
│  React 19 + Deck │  HTTP  │  FastAPI       │  REST  │  Google Earth    │
│  GL + MapLibre   │ <────> │  (uvicorn)     │ <────> │  Engine          │
└──────────────────┘        └───────┬────────┘        └──────────────────┘
                                    │
                                    │ supabase-py
                                    ▼
                            ┌────────────────┐
                            │  Supabase      │  (Postgres + Storage)
                            │  cache 11 ตาราง │
                            └────────────────┘
```

- **Frontend** ([green-area-frontend/](green-area-frontend/)) — React 19, DeckGL 3D extrusion, MapLibre GL, jsPDF + html2canvas รายงาน
- **Backend** ([green-area-backend/](green-area-backend/)) — FastAPI, supabase-py, earthengine-api, matplotlib (thumbnails)
- **Database** — Supabase (Postgres) 14 ตาราง: cache 11 ตาราง (ดู [migrations/000_initial_schema.sql](green-area-backend/migrations/000_initial_schema.sql)) เพื่อหลีกเลี่ยง GEE compute ซ้ำซ้อน + ตารางอ้างอิง `provinces` / `districts` (normalize ชื่อไทย/ภาค/พื้นที่อำเภอ) + `saved_areas` (พื้นที่ที่ผู้ใช้วาดเอง)

---

## Quick start

### 1) Supabase setup
- สร้าง project ใหม่ใน https://supabase.com
- เปิด SQL Editor รัน migration ตามลำดับ:
  - `green-area-backend/migrations/000_initial_schema.sql` (สร้างตารางทั้งหมด)
  - `001_add_dense_area_columns.sql` (เพิ่ม column dense forest)
  - `002_constraints_and_cache_meta.sql` (CHECK constraints + cache_version + index)
  - `003_add_impact_column.sql` (เพิ่ม column impact ใน planting_recommendations)
  - `004_drop_unused_expires_at.sql` (ลบ expires_at ที่เลิกใช้ — tile URL ย้ายไป in-process cache)
  - `005_create_saved_areas.sql` (ตาราง saved_areas — บันทึก polygon ที่วาดเอง + ผลวิเคราะห์)
  - `006_create_provinces.sql` (ตารางอ้างอิง provinces + seed 77 จังหวัด + FK — normalize ชื่อไทย/ภาค)
  - `007_create_districts.sql` (ตารางอ้างอิง districts + seed 928 อำเภอ + พื้นที่ + composite FK)
  - `008_recommend_cache_version.sql` (cache_version ใน planting_recommendations — invalidate row ก่อนมี plantability mask)
  - `009_add_population_year.sql` (เพิ่ม population_year ใน ndvi_annual — บอกปีประชากรที่ใช้คำนวณ m²/คน)
- เอา `URL` และ `service_role` key จากหน้า Project Settings → API

### 2) Backend
```powershell
cd green-area-backend
python -m venv venv
venv\Scripts\activate          # Mac/Linux: source venv/bin/activate
pip install -r requirements.txt

# สร้าง .env (ดูตัวอย่างใน .env.example)
copy .env.example .env
# แก้ค่า SUPABASE_URL, SUPABASE_KEY, GEE_PROJECT, ADMIN_TOKEN

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

## Environment variables (backend `.env`)

| Variable | จำเป็น | อธิบาย |
|---|---|---|
| `SUPABASE_URL` | ✅ | URL ของ Supabase project |
| `SUPABASE_KEY` | ✅ | `service_role` key (ไม่ใช่ `anon`) |
| `GEE_PROJECT` | ✅ | Google Cloud project ที่เปิดใช้ Earth Engine |
| `ADMIN_TOKEN` | ⚠️ | ใช้ลบ cache (`DELETE /cache`) — ถ้าไม่ตั้ง endpoint จะถูก reject |
| `ALLOWED_ORIGINS` | ⚠️ | CORS origin (default = `http://localhost:3000`) — production ต้องใส่ URL ของ Vercel/Render |
| `LOG_LEVEL` | – | `INFO` (default), `DEBUG`, `WARNING` |

---

## โครงสร้างที่สำคัญ

```
green-area-backend/
  main.py                  # FastAPI app + logging config + endpoint /compare /cache /ranking
  dependencies.py          # Supabase client, geometry loader, retry-on-disconnect
  gee_utils.py             # cloud mask, LST collection, reduce helpers
  generate_districts.py    # one-time: สร้าง thailand_districts.json (เรียก add_district_th_names.py ใส่ name_th อัตโนมัติ)
  add_district_th_names.py # patch ชื่ออำเภอภาษาไทย (name_th) ลง thailand_districts.json
  migrations/              # SQL schema สำหรับ Supabase
  routers/
    ndvi/                  # /ndvi · /ndvi/{p}/monthly · district variants (endpoints.py + compute.py)
    lst.py                 # /lst · LST annual + monthly
    maps/                  # /maps/* thumbnails (thumbs.py) + /analysis/* (districts/urban/timeseries/cooling/context)
    recommend/             # /recommend · AI priority heatmap (endpoints + scoring + species + tile_cache)

green-area-frontend/
  src/
    App.js                 # entry + DeckGL setup
    constants.js           # API_BASE, CURRENT_YEAR, PROVINCE_TH, etc.
    components/            # Landing (หน้าแรก), AppHeader, Sidebar, MapTooltip, Toast
    hooks/                 # useNdviCache, useProvinceData, useDistrictData, ...
    utils/                 # mapLayers, exportUtils (PDF), toast (pub/sub)
  public/
    thailand.json          # ขอบเขตจังหวัด (GADM 4.1)
    thailand_districts.json # ขอบเขตอำเภอ — generate ด้วย generate_districts.py
```

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

- **Frontend** — smoke render + colorUtils + reportPdf helpers + hooks
  (`useProvinceData`, `useDistrictData`)
- **Backend** — pure helpers (stats, WHO status, impact), endpoint tests ผ่าน
  FastAPI `TestClient` + mock `supa_call` (ดู [green-area-backend/README.md](green-area-backend/README.md#tests))

ทั้งสอง suite รันอัตโนมัติใน CI ทุก push/PR (ดู [.github/workflows/ci.yml](.github/workflows/ci.yml))

---

## Deploy notes

- **Frontend** → Vercel/Netlify (Vite static · build `npm run build` → `build/`)
  - ตั้ง env `VITE_API_URL` = URL ของ backend ใน dashboard (เดิมชื่อ `REACT_APP_API_URL`)
- **Backend** → Render/Railway (Python web service)
  - Build: `pip install -r requirements.txt`
  - Start: `uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'`
    - `--proxy-headers` จำเป็นเมื่ออยู่หลัง reverse proxy เพื่อให้ rate-limit เห็น IP จริงของผู้ใช้ ไม่ใช่ IP ของ proxy (มี [`Procfile`](green-area-backend/Procfile) ให้ใช้แล้ว)
    - production ต้องตั้ง `ADMIN_TOKEN` เป็น secret สุ่มยาว ≥ 16 ตัว — ไม่งั้น backend จะ refuse ที่จะ start
- ตั้ง `ALLOWED_ORIGINS` ให้ตรงกับ frontend URL
- **Frontend** security headers ตั้งไว้ใน [`vercel.json`](green-area-frontend/vercel.json) / [`netlify.toml`](green-area-frontend/netlify.toml) · CSP เป็น Report-Only — ทดสอบใน browser แล้วค่อยเปลี่ยนเป็น enforcing
- คั่น `thailand.json` กับ `thailand_districts.json` ระหว่าง 2 service — backend จะหาตามลำดับ:
  1. ENV `THAILAND_GEOJSON_PATH` / `DISTRICTS_GEOJSON_PATH` (override)
  2. `green-area-backend/data/` (production — copy 2 ไฟล์เข้า image)
  3. `../green-area-frontend/public/` (legacy dev-local แบบ monorepo)

---

## License & data attribution

- **โค้ด** — MIT License (ดู [LICENSE](LICENSE))
- **ข้อมูล/dataset** — แต่ละชุดมี license ของตัวเอง ผู้ใช้ต้องปฏิบัติตามเมื่อนำไปใช้/เผยแพร่ต่อ:
  - Sentinel-2 (ESA Copernicus) · Landsat 8/9 (USGS/NASA, public domain)
  - ESA WorldCover v200 (CC BY 4.0) · WorldPop (CC BY 4.0)
  - GADM 4.1 boundaries (academic/non-commercial) · CARTO + OpenStreetMap basemaps (© OSM, ODbL)
- รายละเอียด dataset + ระเบียบวิธี + อ้างอิงเชิงวิชาการ ดูได้ในเว็บที่ปุ่ม **ⓘ ข้อมูลและระเบียบวิธี** (มุมขวาบน)
