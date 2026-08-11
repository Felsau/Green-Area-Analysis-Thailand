-- Migration 025: ตัด ndvi_annual.who_status
-- รันบน Supabase SQL Editor หลัง 024
--
-- คอลัมน์นี้เก็บข้อความบรรยาย m²/คน เทียบค่าอ้างอิง WHO (ไม่ใช่ verdict ผ่าน/ไม่ผ่าน —
-- นั่นคือ who_urban_pass ที่ตัดไปแล้วใน migration 023) แต่ไม่มีที่ไหนอ่านค่านี้แล้ว
-- (frontend คิดสดจาก green_area_m2_per_person ทุกจุด — ดูคอมเมนต์ใน StatsTab.js /
-- DrawResultCard.js / export/csv.js) ตรวจแล้วไม่มี backend endpoint ไหน select หรือ
-- คืนค่านี้กลับไปแล้วเช่นกัน (main.py::compare, main.py::get_cache,
-- ndvi/endpoints.py::get_ndvi/get_ndvi_compare, custom.py::analyze_custom_area)
-- compute_who_status() ยังคำนวณข้อความนี้อยู่ (คืน tuple ที่สอง) แต่ caller ทุกจุด
-- ทิ้งค่านั้นแล้วเป็น `_who_status`

BEGIN;

DO $$
DECLARE
    total_rows INTEGER;
    non_null_rows INTEGER;
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'ndvi_annual'
                  AND column_name = 'who_status') THEN
        EXECUTE 'SELECT count(*), count(who_status) FROM ndvi_annual'
           INTO total_rows, non_null_rows;
        RAISE NOTICE 'ndvi_annual: ตัด who_status — % แถวทั้งหมด (% มีค่า) '
                     '— ไม่มีโค้ดอ่านคอลัมน์นี้ ตัดได้ปลอดภัย', total_rows, non_null_rows;
    ELSE
        RAISE NOTICE 'ndvi_annual: ไม่มีคอลัมน์ who_status อยู่แล้ว — ข้าม';
    END IF;
END $$;

ALTER TABLE ndvi_annual DROP COLUMN IF EXISTS who_status;

COMMIT;

-- ตรวจผล — ต้องไม่มี who_status ในรายการ:
--   SELECT column_name FROM information_schema.columns
--    WHERE table_name = 'ndvi_annual' ORDER BY ordinal_position;
