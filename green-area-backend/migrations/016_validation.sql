-- Migration 016: เก็บผลตรวจสอบความถูกต้องเทียบ ESA WorldCover (NFR-08)
-- รันบน Supabase SQL Editor หลัง 015
--
-- แยกเป็น 2 คอลัมน์คนละตารางเพราะอายุการใช้งานต่างกัน:
--   provinces.worldcover_green_pct  ค่าอ้างอิงจาก ESA WorldCover (epoch 2021) ไม่ขึ้น
--     กับปีและไม่ขึ้นกับ Sentinel-2 = คงที่ต่อจังหวัด · แพงสุด (~17.5 วิ/จังหวัด) ถ้า
--     คิดสดทุก cache miss จะดัน NDVI compute ทะลุงบ 60 วิ ของ NFR-01 จึง backfill
--     ครั้งเดียวแทน (backfill_worldcover_reference.py)
--   ndvi_annual.validation  ผลเทียบของปีนั้น ขึ้นกับ NDVI จึงเก็บรายปีเหมือน 014/015
--
-- validation เป็น jsonb ด้วยเหตุผลเดียวกับ 014/015 · โครงสร้างดู
-- schemas.py::GreenAreaValidation · error_pp = net_pp + reference_scale_delta_pp
--
-- เก็บระดับจังหวัดอย่างเดียว ไม่เพิ่มให้ district_ndvi_annual — `_is_stale` ใช้ร่วมกัน
-- ทั้งสองระดับ ถ้าใส่เงื่อนไข validation ตรง ๆ แถวอำเภอจะ stale ตลอดกาล เพราะ path
-- อำเภอไม่ได้คำนวณ field นี้ → ฝั่ง Python ใช้ `require_validation=True` เฉพาะ path จังหวัด
--
-- NULL = แถวที่คำนวณก่อน migration นี้ — recompute ให้เองเมื่อมีคนเปิดจังหวัดนั้น

ALTER TABLE ndvi_annual
  ADD COLUMN IF NOT EXISTS validation JSONB;

ALTER TABLE provinces
  ADD COLUMN IF NOT EXISTS worldcover_green_pct DOUBLE PRECISION;

COMMENT ON COLUMN provinces.worldcover_green_pct IS
  '% พื้นที่สีเขียวตาม ESA WorldCover v200 (fractional 10 ม.) — คงที่ ไม่ขึ้นกับปี · '
  'เติมด้วย backfill_worldcover_reference.py · NULL = ยังไม่ backfill (NFR-08 จะไม่แสดง)';
