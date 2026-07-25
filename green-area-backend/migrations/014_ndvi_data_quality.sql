-- Migration 014: เก็บคุณภาพ/ความไม่แน่นอนของ NDVI composite (NFR-07)
-- รันบน Supabase SQL Editor หลัง 013
--
-- ค่า NDVI ทุกค่ามาจาก median composite ของภาพ Sentinel-2 ทั้งปี — พื้นที่/ปีที่มี
-- ภาพปลอดเมฆน้อย (ภาคใต้ ฤดูฝน) ให้ค่าที่ความไม่แน่นอนสูงกว่ามาก แต่เดิมไม่มีที่เก็บ
-- ข้อมูลนี้เลย · เก็บเป็น jsonb ก้อนเดียวเพราะเป็นชุด metadata ที่อ่าน/เขียนพร้อมกัน
-- เสมอ (ไม่เคย query ทีละ field) และยังปรับ field ภายในได้โดยไม่ต้อง migrate ซ้ำ
--
-- โครงสร้าง (ดู schemas.py::NDVIDataQuality · สร้างใน routers/ndvi/compute.py):
--   {"image_count": 65, "cloud_filter_pct": 20, "clear_obs_mean": 21.6,
--    "clear_obs_min": 14, "ndvi_sd_mean": 0.06, "uncertainty": 0.0162,
--    "uncertainty_2sigma_pct": 8.6, "first_date": "2024-01-01",
--    "last_date": "2024-12-31", "months_covered": 9, "months_missing": [7,8,9],
--    "seasons_covered": ["ฤดูร้อน","ฤดูฝน","ฤดูหนาว"], "seasons_missing": [],
--    "seasonally_representative": true, "level": "threshold",
--    "label": "ผ่านเกณฑ์ Threshold (GCOS)", "note": "median composite จากภาพ ..."}
-- level = goal | threshold | below | none ตามเกณฑ์ GCOS-245 (ดู REQUIREMENTS [R33])
--
-- NULL = row ที่คำนวณก่อน migration นี้ — _is_stale() ถือว่า stale แล้ว recompute
-- ให้เองเมื่อมีคนเปิดจังหวัด/อำเภอนั้น (ไม่ต้อง backfill ด้วยมือ · backfill ไม่ได้จริง
-- เพราะต้องเรียก GEE ใหม่อยู่ดี)

ALTER TABLE ndvi_annual
  ADD COLUMN IF NOT EXISTS data_quality JSONB;

ALTER TABLE district_ndvi_annual
  ADD COLUMN IF NOT EXISTS data_quality JSONB;
