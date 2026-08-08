# Green Area Frontend

React 19 + Vite + DeckGL + MapLibre — แผนที่ 3D extrusion ของพื้นที่สีเขียวประเทศไทย

ดู [../README.md](../README.md) สำหรับ architecture และ setup ทั้งหมด — ไฟล์นี้เก็บเฉพาะ
รายละเอียดเฉพาะ frontend

## Scripts

```powershell
npm run dev       # dev server (Vite) → http://localhost:3000
npm start         # alias ของ dev
npm run build     # production bundle → build/
npm run preview   # serve production build เพื่อทดสอบ local
npm run lint      # eslint (flat config)
npm test          # run test suite once (vitest)
```

## โครงสร้าง

```
src/
  App.js                # entry — DeckGL setup + state composition
  App.test.js           # smoke test (renders + sidebar empty state)
  constants.js          # API_BASE, CURRENT_YEAR, PROVINCE_TH, MAP_STYLE
  setupTests.js         # jest-dom + TextEncoder polyfill + fetch mock
  components/
    AppHeader.js
    Sidebar.js          # tabs: stats / trend / compare / ranking / recommend
    MapTooltip.js
    Toast.js            # global error/info toast (pub/sub)
  hooks/
    useNdviCache.js     # โหลด /cache ตอน mount
    useProvinceData.js  # NDVI + LST ระดับจังหวัด
    useDistrictData.js  # NDVI + LST ระดับอำเภอ + ขอบเขตอำเภอ
    useTrendData.js     # trend หลายปี
    useCompareData.js   # เปรียบเทียบหลายจังหวัด
    useRankingData.js   # อันดับ m²/คน ในเขต built-up (urban subset)
    useRecommendData.js # AI heatmap + top spots + year picker
  utils/
    mapLayers.js        # buildMapLayers() — สร้าง DeckGL layers
    exportUtils.js      # PDF report (jsPDF + html2canvas + Sarabun TTF)
    toast.js            # pub/sub emitter
```

## Environment

ดู `.env.example` — คัดลอกเป็น `.env.local` แล้วใส่ค่าจริง

- `VITE_API_URL` (optional) — backend URL · default `http://localhost:8000`
  · ตั้งใน .env / .env.production หรือ env ของ Netlify/Vercel (Vite อ่าน prefix `VITE_`)
- `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` — ระบบล็อกอิน (Supabase Auth)
  · ต้องรัน `green-area-backend/migrations/010_create_profiles.sql` และตั้งค่า
  Auth ใน Supabase Dashboard ก่อนใช้งานได้จริง (สำคัญ: **ปิด** "Confirm email")
  — ดูรายละเอียดใน `.env.example`

## Auth

- Sign in / sign up / forgot·reset password ผ่าน Supabase Auth โดยตรง
  (`src/lib/supabaseClient.js`, `src/hooks/useAuth.js`) — ไม่ผ่าน backend ·
  **ไม่มีขั้นตอนยืนยันอีเมล** สมัครเสร็จเข้าแดชบอร์ดทันที (ต้องปิด "Confirm email"
  ใน Supabase Dashboard ด้วย) — อีเมลฉบับเดียวที่ส่งคือลิงก์รีเซ็ตรหัสผ่าน
- โปรไฟล์ (ชื่อที่แสดง, role) และการลบบัญชี ผ่าน backend (`/account/*`) ซึ่งถือ
  service-role key — ดู `green-area-backend/routers/account.py`
- เข้าสู่ระบบเป็นเงื่อนไขบังคับก่อนเข้าแดชบอร์ด (`src/components/auth/AuthGate.js`) —
  หน้า Landing ยังเป็นหน้าการตลาดก่อนล็อกอินเหมือนเดิม

## Error handling

ทุก hook ที่ fetch จะ `pushError(msg)` เมื่อ catch — `<Toast />` ใน App.js แสดง
top-right (auto-dismiss 5s)
