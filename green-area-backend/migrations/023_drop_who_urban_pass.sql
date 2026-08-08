-- Migration 023: ตัด urban_ndvi_annual.who_urban_pass
-- รันบน Supabase SQL Editor หลัง 022
--
-- คอลัมน์นี้เก็บผลตัดสิน m2_per_person_urban >= 9 เป็น BOOLEAN ซึ่งเป็น verdict
-- ผ่าน/ไม่ผ่าน WHO แบบเดียวกับที่เลิกใช้ไปแล้วใน commit cfbc558 · ตรวจแล้วไม่มีโค้ด
-- ไหนอ่านค่านี้เลย (urban.py ตัด key ออกจาก insert แล้ว) · ER diagram ใน
-- gen_er.py ตัดแถวนี้ออกพร้อมกัน

BEGIN;

DO $$
DECLARE
    total_rows INTEGER;
    true_rows INTEGER;
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'urban_ndvi_annual'
                  AND column_name = 'who_urban_pass') THEN
        EXECUTE 'SELECT count(*), count(*) FILTER (WHERE who_urban_pass)
                   FROM urban_ndvi_annual'
           INTO total_rows, true_rows;
        RAISE NOTICE 'urban_ndvi_annual: ตัด who_urban_pass — % แถวทั้งหมด (% เป็น TRUE) '
                     '— ไม่มีโค้ดอ่านคอลัมน์นี้ ตัดได้ปลอดภัย', total_rows, true_rows;
    ELSE
        RAISE NOTICE 'urban_ndvi_annual: ไม่มีคอลัมน์ who_urban_pass อยู่แล้ว — ข้าม';
    END IF;
END $$;

ALTER TABLE urban_ndvi_annual DROP COLUMN IF EXISTS who_urban_pass;

COMMIT;

-- ตรวจผล — ต้องไม่มี who_urban_pass ในรายการ:
--   SELECT column_name FROM information_schema.columns
--    WHERE table_name = 'urban_ndvi_annual' ORDER BY ordinal_position;
