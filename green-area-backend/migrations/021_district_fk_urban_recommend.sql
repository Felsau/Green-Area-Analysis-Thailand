-- Migration 021: composite FK (province, district) → districts(province, name_en)
-- ให้ urban_ndvi_annual และ planting_recommendations — เหมือนที่ migration 007
-- ทำให้ 4 ตาราง district_* ไปแล้ว แต่ตกสองตารางนี้เพราะสร้างทีหลัง
-- รันบน Supabase SQL Editor หลัง 020
--
-- ── ทำไม ─────────────────────────────────────────────────────────────────────
-- ทั้งสองตารางมีคอลัมน์ district (NULL = แถวระดับจังหวัด, มีค่า = แถวระดับอำเภอ —
-- ดูคอมเมนต์ใน 000_initial_schema.sql) แต่ไม่เคยมี FK คุมว่าคู่ (province, district)
-- ต้องมีจริงใน districts เหมือนตาราง district_* — พิมพ์ชื่ออำเภอผิด/เว้นวรรคต่างจาก
-- thailand_districts.json จะเงียบ ไม่มีอะไรฟ้อง (composite key ไม่ตรงกับที่แอปใช้จริง
-- ใน routers/maps/analysis/urban.py และ routers/recommend/endpoints.py)
--
-- FOREIGN KEY แบบ MATCH SIMPLE (ค่าเริ่มต้นของ Postgres) จะไม่เช็คแถวที่ district
-- เป็น NULL อยู่แล้ว — แถวระดับจังหวัดจึงไม่กระทบ
--
-- ── ยืนยันว่าไม่มีแถวกำพร้าก่อนใส่ FK (4 ส.ค. 2569) ────────────────────────────
--   urban_ndvi_annual: 4 แถว มี district ไม่ว่าง 1 แถว — ตรงกับ districts ทั้งหมด
--   planting_recommendations: 5 แถว มี district ไม่ว่าง 2 แถว — ตรงกับ districts ทั้งหมด
--   (เช็คด้วยการ join กับ districts(province, name_en) ตรงๆ ผ่าน Supabase client)

BEGIN;

DO $$
DECLARE
  t TEXT;
  tables TEXT[] := ARRAY['urban_ndvi_annual', 'planting_recommendations'];
  cname TEXT;
BEGIN
  FOREACH t IN ARRAY tables LOOP
    cname := 'fk_' || t || '_district';
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = cname) THEN
      EXECUTE format(
        'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (province, district) '
        'REFERENCES districts(province, name_en)', t, cname);
    END IF;
  END LOOP;
END $$;

COMMIT;

-- ตรวจผล — ต้องเห็น fk_urban_ndvi_annual_district และ
-- fk_planting_recommendations_district:
--   SELECT conname, conrelid::regclass FROM pg_constraint
--    WHERE conname LIKE 'fk_%_district' ORDER BY conname;
