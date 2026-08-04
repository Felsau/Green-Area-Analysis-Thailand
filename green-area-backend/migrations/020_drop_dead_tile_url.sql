-- Migration 020: ตัด planting_recommendations.tile_url ที่ไม่มีโค้ดอ่าน/เขียนแล้ว
-- รันบน Supabase SQL Editor หลัง 019
--
-- ── ทำไม ─────────────────────────────────────────────────────────────────────
-- คอลัมน์นี้เกิดพร้อมตารางใน 000_initial_schema.sql:143 ตอนที่ยังตั้งใจแคช XYZ tile
-- URL ของ heatmap ลง DB · migration 002 เพิ่ม expires_at มาคู่กันเพราะ URL ผูก
-- session token ของ Google Earth Engine ที่หมดอายุใน ~ชั่วโมง
--
-- migration 004 ตัด expires_at ทิ้งไปแล้วด้วยเหตุผลว่า tile URL ย้ายไปอยู่
-- in-process TTL cache (routers/recommend/tile_cache.py · TTL 30 นาที) — แต่รอบนั้น
-- ตัดแค่ expires_at ปล่อย tile_url ค้างไว้ กลายเป็นคอลัมน์ที่ไม่มีใครแตะมาตั้งแต่นั้น
--
-- ── ยืนยันว่าไม่มีโค้ดใช้ (1 ส.ค. 2569) ──────────────────────────────────────
--   เขียน: routers/recommend/endpoints.py:230-236 insert เฉพาะ province/district/
--          year/top_locations/impact/cache_version · บรรทัด 228 คอมเมนต์ระบุชัดว่า
--          "ไม่เก็บ tile_url ลง DB — URL ผูก GEE session ที่หมดอายุใน ~ชั่วโมง"
--   อ่าน:  cache-hit path (บรรทัด 181-183) เรียก get_cached_tile_url() จาก
--          tile_cache.py ไม่ใช่ row["tile_url"] · grep row["tile_url"] /
--          row.get("tile_url") / select("tile_url ทั้ง repo = 0 นัด
--          (endpoints.py ใช้ select("*") จึงดึงคอลัมน์นี้ติดมาด้วยแต่ทิ้งค่าเสมอ)
--
-- ไม่มีข้อมูลให้เสีย: ทุกแถวที่ insert หลัง 004 มี tile_url = NULL อยู่แล้ว ส่วนแถว
-- ก่อนหน้านั้นถ้ายังเหลือก็ถือเป็นขยะ — URL ใน DB หมดอายุตั้งแต่ไม่กี่ชั่วโมงหลัง
-- เขียน ใช้ต่อไม่ได้อยู่ดี · รายงานจำนวนก่อนลบเสมอ ไม่ลบเงียบ ๆ (ธรรมเนียมเดียวกับ 019)
--
-- ── ผลต่อเอกสาร ──────────────────────────────────────────────────────────────
-- ER diagram (ภาพร่างไดอะแกรมใหม่/scripts/gen_er.py) ตัดแถวนี้ออกพร้อมกัน — ก่อนหน้านี้
-- ไดอะแกรมวาดคอลัมน์ที่ไม่เคยมีข้อมูล ทำให้คนอ่านเข้าใจว่าระบบแคช tile URL ลงฐานข้อมูล

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
