-- Migration 021: composite FK (province, district) → districts(province, name_en)
-- ให้ urban_ndvi_annual และ planting_recommendations — เหมือนที่ migration 007
-- ทำให้ 4 ตาราง district_* ไปแล้ว แต่ตกสองตารางนี้เพราะสร้างทีหลัง
-- รันบน Supabase SQL Editor หลัง 020
--
-- ทั้งสองตารางมีคอลัมน์ district (NULL = ระดับจังหวัด) แต่ไม่เคยมี FK คุมว่าคู่
-- (province, district) ต้องมีจริงใน districts เหมือนตาราง district_* — พิมพ์ชื่ออำเภอ
-- ผิดหรือเว้นวรรคต่างจาก thailand_districts.json จะเงียบ ไม่มีอะไรฟ้อง
--
-- MATCH SIMPLE (ค่าเริ่มต้น) ไม่เช็คแถวที่ district เป็น NULL — ระดับจังหวัดไม่กระทบ
-- ตรวจก่อนใส่ FK (4 ส.ค. 2569): ไม่มีแถวกำพร้าในทั้งสองตาราง

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
