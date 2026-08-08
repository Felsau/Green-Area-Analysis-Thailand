-- Migration 008: cache versioning ให้ planting_recommendations
-- รันบน Supabase SQL Editor หลัง 007
--
-- /recommend เพิ่ม plantability mask (ESA WorldCover) ที่ตัดน้ำ/อาคาร/ป่าเดิม/พื้นที่
-- ชุ่มน้ำออกจาก plantable area — แคชที่เขียนไว้ก่อนมี mask จึง overestimate จำนวนต้น
-- และ CO₂ แต่ cache นี้ไม่มี versioning จึงไม่ auto-invalidate
--
-- แถวเก่าได้ cache_version = 0 แล้วโค้ดเช็ค `>= RECOMMEND_CACHE_VERSION` จะถือว่า stale
-- ลบทิ้งแล้ว recompute เมื่อถูกเรียกครั้งถัดไป (lazy ไม่ recompute พร้อมกันทั้งหมด)
-- DEFAULT ตั้งเป็น 1 หลัง backfill เพื่อให้แถวที่ insert นอกแอปไม่ค้าง stale

-- 1) เพิ่ม column · DEFAULT 0 ตอนนี้ → row เดิมทุกแถวได้ค่า 0 (pre-mask)
ALTER TABLE planting_recommendations
    ADD COLUMN IF NOT EXISTS cache_version SMALLINT NOT NULL DEFAULT 0;

-- 2) เปลี่ยน default เป็น 1 สำหรับ row ที่จะ insert ต่อจากนี้ (row เดิมยังเป็น 0)
ALTER TABLE planting_recommendations
    ALTER COLUMN cache_version SET DEFAULT 1;

COMMENT ON COLUMN planting_recommendations.cache_version IS
    'เวอร์ชัน compute logic ของ /recommend · ตรงกับ RECOMMEND_CACHE_VERSION ใน dependencies.py · 0 = pre plantability-mask (stale)';
