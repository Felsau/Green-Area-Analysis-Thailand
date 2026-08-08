-- Migration 019: ตัด saved_areas.owner_token ทิ้ง — เหลือ user_id เป็นเจ้าของอย่างเดียว
-- รันบน Supabase SQL Editor หลัง 018
--
-- owner_token เกิดตอนแอปยังไม่มี login (migration 005): UUID สุ่มใน localStorage ส่งมา
-- ทาง header X-Owner-Token ใช้ตัดสินสิทธิ์ลบ · migration 013 เพิ่ม user_id แล้วเก็บ
-- owner_token ไว้เป็น fallback ให้แถวเก่า
--
-- ตอนนี้ทั้งแอปบังคับล็อกอินหมดแล้ว POST /saved-areas ตั้ง user_id เสมอ fallback จึง
-- ไม่มีอะไรให้ fallback เหลือแต่ต้นทุน: ต้องเช็คสองทางทุก endpoint, เก็บ token เป็น
-- plaintext, และ RLS policy ในอนาคตเขียนยากเพราะ token ไม่ได้อยู่ใน JWT
--
-- ตรวจก่อนเขียน migration (31 ก.ค. 2569): ตารางว่างเปล่า ไม่มีข้อมูลผู้ใช้ให้เสีย
-- แต่ยังเขียนกันไว้เผื่อ instance อื่นมีแถวค้าง — รายงานจำนวนก่อนลบเสมอ
--
-- หมายเหตุ: คอมเมนต์ใน 005 ที่ว่า "GET คืน list แบบ shared" ล้าสมัยตั้งแต่ก่อนหน้านี้
-- แล้ว routers/saved.py คืนเฉพาะของเจ้าของเสมอ · ไม่แก้ไฟล์ 005 ย้อนหลังตามธรรมเนียม repo

BEGIN;

-- 1) แถวที่ไม่มี user_id จะเข้าถึงไม่ได้อีกเลยหลัง migration นี้
-- (list filter ด้วย user_id · get/delete เช็ค user_id) → ลบทิ้งดีกว่าปล่อยเป็นขยะ
-- ที่ลบไม่ออก · รายงานจำนวนก่อนเสมอ เผื่อรันบน instance ที่มีข้อมูลจริง
DO $$
DECLARE
    doomed INTEGER;
BEGIN
    SELECT count(*) INTO doomed FROM saved_areas WHERE user_id IS NULL;

    IF doomed > 0 THEN
        RAISE WARNING 'saved_areas: ลบ % แถวที่ไม่มี user_id (เข้าถึงไม่ได้อีกหลังตัด owner_token)',
                      doomed;
        DELETE FROM saved_areas WHERE user_id IS NULL;
    ELSE
        RAISE NOTICE 'saved_areas: ไม่มีแถวที่ต้องลบ — ทุกแถวมี user_id อยู่แล้ว';
    END IF;
END $$;

-- 2) ตัด constraint/index/column ที่ผูกกับ owner_token
-- DROP COLUMN ลบ constraint กับ index ที่อ้างคอลัมน์นี้ให้เองอยู่แล้ว แต่เขียนแยก
-- ให้อ่านออกว่าอะไรหายไปบ้าง (และ IF EXISTS ทำให้รันซ้ำได้)
ALTER TABLE saved_areas DROP CONSTRAINT IF EXISTS saved_areas_has_owner;  -- จาก 018
DROP INDEX IF EXISTS idx_saved_areas_owner;                               -- จาก 005
ALTER TABLE saved_areas DROP COLUMN IF EXISTS owner_token;

-- 3) user_id เป็นเจ้าของเพียงทางเดียว → บังคับ NOT NULL
-- ครอบคลุมกว่า CHECK แบบ OR ใน 018 (ซึ่งเป็น NOT VALID และถูกลบไปในขั้นที่ 2 แล้ว)
-- ON DELETE CASCADE จาก 013 ยังอยู่ → ลบบัญชี = พื้นที่ถูกลบตาม ไม่มีแถวกำพร้าเกิดใหม่ได้
ALTER TABLE saved_areas ALTER COLUMN user_id SET NOT NULL;

COMMENT ON COLUMN saved_areas.user_id IS
    'เจ้าของพื้นที่ — auth.users(id) ON DELETE CASCADE · เป็นทางเดียวที่ระบุเจ้าของ '
    'ตั้งแต่ migration 019 (เดิมมี owner_token จากยุคก่อนมี login คู่กัน)';

COMMIT;

-- ตรวจผล:
--   SELECT column_name, is_nullable FROM information_schema.columns
--    WHERE table_name = 'saved_areas' ORDER BY ordinal_position;
--   → ต้องไม่มี owner_token · user_id ต้องเป็น is_nullable = 'NO'
