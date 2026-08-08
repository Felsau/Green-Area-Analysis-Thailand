-- Migration 020: ตัด planting_recommendations.tile_url ที่ไม่มีโค้ดอ่าน/เขียนแล้ว
-- รันบน Supabase SQL Editor หลัง 019
--
-- คอลัมน์นี้เกิดพร้อมตารางใน 000_initial_schema.sql ตอนที่ยังตั้งใจแคช XYZ tile URL
-- ของ heatmap ลง DB · migration 004 ตัด expires_at ที่มาคู่กันทิ้งไปแล้วเพราะ tile URL
-- ย้ายไป in-process TTL cache (recommend/tile_cache.py) แต่รอบนั้นปล่อย tile_url ค้างไว้
--
-- ตรวจแล้ว (1 ส.ค. 2569) ไม่มีโค้ดอ่านหรือเขียนคอลัมน์นี้เลย — endpoints.py insert
-- เฉพาะ province/district/year/top_locations/impact/cache_version ส่วน cache-hit path
-- เรียก get_cached_tile_url() ไม่ใช่ row["tile_url"]
--
-- ไม่มีข้อมูลให้เสีย ทุกแถวหลัง 004 มีค่า NULL อยู่แล้ว ส่วนแถวเก่ากว่านั้นก็เป็น URL
-- ที่หมดอายุไปนานแล้ว · รายงานจำนวนก่อนลบเสมอ (ธรรมเนียมเดียวกับ 019)
-- ER diagram ใน gen_er.py ตัดแถวนี้ออกพร้อมกัน

BEGIN;

DO $$
DECLARE
    filled INTEGER;
BEGIN
    -- คอลัมน์อาจถูกตัดไปแล้วถ้ารันซ้ำ — เช็คก่อนค่อยนับ
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'planting_recommendations'
                  AND column_name = 'tile_url') THEN
        EXECUTE 'SELECT count(*) FROM planting_recommendations WHERE tile_url IS NOT NULL'
           INTO filled;
        IF filled > 0 THEN
            RAISE WARNING 'planting_recommendations: ตัด tile_url ที่ยังมีค่าอยู่ % แถว '
                          '(URL ผูก GEE session — หมดอายุไปนานแล้ว ใช้ต่อไม่ได้)', filled;
        ELSE
            RAISE NOTICE 'planting_recommendations: tile_url เป็น NULL ทุกแถว — ตัดได้ปลอดภัย';
        END IF;
    ELSE
        RAISE NOTICE 'planting_recommendations: ไม่มีคอลัมน์ tile_url อยู่แล้ว — ข้าม';
    END IF;
END $$;

ALTER TABLE planting_recommendations DROP COLUMN IF EXISTS tile_url;

COMMIT;

-- ตรวจผล — ต้องไม่มี tile_url ในรายการ:
--   SELECT column_name FROM information_schema.columns
--    WHERE table_name = 'planting_recommendations' ORDER BY ordinal_position;
