-- Migration 016: เก็บผลตรวจสอบความถูกต้องเทียบ ESA WorldCover (NFR-08)
-- รันบน Supabase SQL Editor หลัง 015
--
-- ── ทำไมแยกเป็น 2 คอลัมน์คนละตาราง ──────────────────────────────────────────
-- ตัวชี้วัดของ NFR-08 ประกอบจากสองโดเมนที่มีอายุการใช้งานต่างกันมาก:
--
--   provinces.worldcover_green_pct   % พื้นที่สีเขียวตาม ESA WorldCover (คลาส
--     10/20/30/40/90/95) อ่านแบบ fractional ที่ 10 ม. · WorldCover เป็น epoch เดียว
--     (2021) ค่านี้จึง **ไม่ขึ้นกับปีและไม่ขึ้นกับ Sentinel-2** = คงที่ต่อจังหวัด
--     ตลอดไป · เป็นก้อนที่แพงที่สุด (วัดจริง ~17.5 วิ/จังหวัด) ถ้าคิดสดทุก cache miss
--     จะดัน NDVI compute (~50 วิ) ทะลุงบ 60 วิ ของ NFR-01 → backfill ครั้งเดียวแทน
--     (ดู backfill_worldcover_reference.py)
--
--   ndvi_annual.validation           ผลเทียบของ *ปีนั้น* — ขึ้นกับ NDVI ของปี จึงต้อง
--     เก็บรายปีคู่กับ row เดิม เหมือน data_quality (014) และ canopy (015)
--
-- ── ทำไม validation เป็น jsonb ──────────────────────────────────────────────
-- เหตุผลเดียวกับ 014/015: อ่าน/เขียนพร้อมกันเสมอ ไม่เคย query ทีละ field และปรับ
-- field ภายใน (เช่นเพิ่มคลาสใน by_class) ได้โดยไม่ต้อง migrate ซ้ำ
--
-- โครงสร้าง (ดู schemas.py::GreenAreaValidation · สร้างใน validation.py):
--   {"available": true, "ndvi_green_pct": 82.8, "worldcover_green_pct": 96.9,
--    "error_pp": -14.1, "target_pp": 10.0, "within_target": false, "year": 2021,
--    "worldcover_epoch_year": 2021,
--    "breakdown": {"false_negative_pp": 16.4, "false_positive_pp": 1.4,
--                  "net_pp": -14.9, "reference_scale_delta_pp": 0.8,
--                  "by_class": [{"code": 40, "name": "พื้นที่เกษตร (Cropland)",
--                                "kind": "false_negative", "pp": 15.7}, ...],
--                  "dominant": {...}},
--    "note": "..."}
--
-- การกระทบยอด: error_pp = breakdown.net_pp + breakdown.reference_scale_delta_pp
-- (ตรวจแล้วทั้ง 77 จังหวัด คลาดเคลื่อนคงเหลือสูงสุด 0.10 จุด% = การปัดเศษ)
--
-- ── ขอบเขต: ระดับจังหวัดเท่านั้น ────────────────────────────────────────────
-- ไม่เพิ่มคอลัมน์ให้ district_ndvi_annual — บริบทที่ตัวเลขนี้ต้องอ่านคู่ (WHO m²/คน)
-- อยู่ระดับจังหวัด · และ `_is_stale` ใช้ร่วมกันทั้งสองระดับ ถ้าใส่เงื่อนไข validation
-- ลงไปตรง ๆ row ของอำเภอจะกลายเป็น stale ตลอดกาล (path อำเภอไม่ได้คำนวณ field นี้)
-- → ฝั่ง Python จึงใช้ `_is_stale(row, require_validation=True)` เฉพาะ path จังหวัด
--
-- NULL = row ที่คำนวณก่อน migration นี้ — recompute ให้เองเมื่อมีคนเปิดจังหวัดนั้น

ALTER TABLE ndvi_annual
  ADD COLUMN IF NOT EXISTS validation JSONB;

ALTER TABLE provinces
  ADD COLUMN IF NOT EXISTS worldcover_green_pct DOUBLE PRECISION;

COMMENT ON COLUMN provinces.worldcover_green_pct IS
  '% พื้นที่สีเขียวตาม ESA WorldCover v200 (fractional 10 ม.) — คงที่ ไม่ขึ้นกับปี · '
  'เติมด้วย backfill_worldcover_reference.py · NULL = ยังไม่ backfill (NFR-08 จะไม่แสดง)';
