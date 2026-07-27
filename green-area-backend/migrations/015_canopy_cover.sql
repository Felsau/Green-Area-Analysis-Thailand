-- Migration 015: เก็บตัวชี้วัดเรือนยอด 30% ของกฎ 3-30-300 (FR-17)
-- รันบน Supabase SQL Editor หลัง 014
--
-- ทำไมเป็นคอลัมน์ใหม่แทนการใช้ green_area_pct เดิม: คนละนิยาม วัดคนละแบบ
--   green_area_pct  NDVI > 0.3 ของ composite Sentinel-2 = พืชพรรณทุกชนิด (รวมนาข้าว
--                   สนามหญ้า) → ตอบมาตรฐาน WHO 9 m²/คน
--   canopy          คลาส "ต้นไม้" จากการจำแนก land cover = เฉพาะเรือนยอดไม้ยืนต้น
--                   → ตอบเกณฑ์ "30" ของ 3-30-300 [R2]
-- อำเภอเกษตรกรรมจะ green สูงแต่ canopy ต่ำเป็นเรื่องปกติ — ต้องอ่านคู่กัน
--
-- เก็บเป็น jsonb ก้อนเดียวด้วยเหตุผลเดียวกับ data_quality (migration 014): เป็นชุด
-- metadata ที่อ่าน/เขียนพร้อมกันเสมอ ไม่เคย query ทีละ field และปรับ field ภายในได้
-- โดยไม่ต้อง migrate ซ้ำ
--
-- ค่าหลักมาจาก ESA WorldCover v200 ซึ่งมี epoch เดียว (2021) จึง *ไม่ขยับตามปีที่
-- ผู้ใช้เลือก* — เก็บ epoch_year/epoch_offset_years ไว้ด้วยเพื่อให้ UI กำกับได้เสมอ
-- ส่วนการเปลี่ยนแปลงรายปีอยู่ใน trend (Dynamic World) ซึ่งอ่านได้เฉพาะ *ทิศทาง*
-- เพราะ DW ตรวจไม่เจอเรือนยอดในเมือง (เหตุผลเต็ม + ตารางเทียบอยู่ใน canopy.py)
--
-- โครงสร้าง (ดู schemas.py::CanopyCover · สร้างใน canopy.py::build_canopy):
--   {"available": true, "canopy_pct": 14.6, "canopy_km2": 1.40,
--    "target_pct": 30.0, "meets_target": false, "gap_pct": 15.4,
--    "source": "ESA WorldCover v200", "epoch_year": 2021, "epoch_offset_years": 3,
--    "trend": {"source": "Dynamic World V1", "year": 2024, "baseline_year": 2021,
--              "canopy_pct": 4.7, "baseline_pct": 4.4, "change_pp": 0.3,
--              "direction": "stable", "coverage_pct": 100.0, "note": "..."},
--    "label": "ต่ำกว่าเกณฑ์ 30% ⚠️ (14.6% — ขาดอีก 15.4 จุด%)", "note": "..."}
-- trend = null เมื่อปีนั้นไม่มีภาพ Dynamic World (ปีก่อน 2015 หรือปีอนาคต) —
-- ค่าหลักยังใช้ได้เพราะ WorldCover เป็นข้อมูลคงที่ ไม่ขึ้นกับปี
--
-- NULL = row ที่คำนวณก่อน migration นี้ — _is_stale() ถือว่า stale แล้ว recompute
-- ให้เองเมื่อมีคนเปิดจังหวัด/อำเภอนั้น (backfill ด้วยมือไม่ได้ ต้องเรียก GEE ใหม่)

ALTER TABLE ndvi_annual
  ADD COLUMN IF NOT EXISTS canopy JSONB;

ALTER TABLE district_ndvi_annual
  ADD COLUMN IF NOT EXISTS canopy JSONB;
