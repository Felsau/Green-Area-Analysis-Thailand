-- Migration 015: เก็บตัวชี้วัดเรือนยอด 30% ของกฎ 3-30-300 (FR-17)
-- รันบน Supabase SQL Editor หลัง 014
--
-- แยกจาก green_area_pct เพราะคนละนิยาม: green_area_pct มาจาก NDVI > 0.3 (พืชพรรณ
-- ทุกชนิดรวมนาข้าว/สนามหญ้า) ส่วน canopy มาจากคลาส "ต้นไม้" ของ land cover
-- (เฉพาะไม้ยืนต้น) → ตอบเกณฑ์ "30" ของ 3-30-300 [R2] · อำเภอเกษตรกรรมจะ green สูง
-- แต่ canopy ต่ำเป็นเรื่องปกติ ต้องอ่านคู่กัน
--
-- เก็บเป็น jsonb ก้อนเดียวเหมือน data_quality (014) · โครงสร้างดู schemas.py::CanopyCover
-- ค่าหลักมาจาก ESA WorldCover v200 ที่มี epoch เดียว (2021) จึงไม่ขยับตามปีที่เลือก —
-- เก็บ epoch_year ไว้ให้ UI กำกับได้ · trend มาจาก Dynamic World ซึ่งอ่านได้เฉพาะ
-- ทิศทาง เพราะ DW ตรวจไม่เจอเรือนยอดในเมือง (เหตุผลเต็มอยู่ใน canopy.py)
--
-- NULL = แถวที่คำนวณก่อน migration นี้ — _is_stale() จะ recompute ให้เองเมื่อมีคนเปิด

ALTER TABLE ndvi_annual
  ADD COLUMN IF NOT EXISTS canopy JSONB;

ALTER TABLE district_ndvi_annual
  ADD COLUMN IF NOT EXISTS canopy JSONB;
