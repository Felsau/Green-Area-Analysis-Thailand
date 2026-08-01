-- Migration 019: ตัด saved_areas.owner_token ทิ้ง — เหลือ user_id เป็นเจ้าของอย่างเดียว
-- รันบน Supabase SQL Editor หลัง 018
--
-- ── ทำไม ─────────────────────────────────────────────────────────────────────
-- owner_token เกิดตอนแอปยังไม่มี login (migration 005): UUID สุ่มใน localStorage
-- ส่งมาทาง header X-Owner-Token ใช้ตัดสินสิทธิ์ลบ · migration 013 เพิ่ม user_id
-- ผูกกับบัญชีจริงและเก็บ owner_token ไว้เป็น fallback ให้แถวเก่าที่ยังไม่มี user_id
--
-- ตอนนี้ทั้งแอปบังคับล็อกอินหมดแล้ว (App.js AuthGate + require_user ที่ include_router
-- ใน main.py) → POST /saved-areas ตั้ง user_id เสมอ ไม่มีทางเกิดแถวใหม่ที่ไม่มี user_id
-- fallback จึงไม่มีอะไรให้ fallback อีกแล้ว เหลือแต่ต้นทุน:
--   - dual ownership ที่ต้องเช็คสองทางทุก endpoint (routers/saved.py)
--   - token เก็บเป็น plaintext ในคอลัมน์ที่ไม่มีเหตุผลต้องมีอยู่
--   - RLS policy ในอนาคตเขียนยากขึ้นมาก เพราะ token ไม่ได้อยู่ใน JWT
--     ต้องส่งผ่าน current_setting() หรืออ้อมผ่าน Edge Function
--
-- ── ยืนยันว่าปลอดภัยจะตัด ────────────────────────────────────────────────────
-- ตรวจก่อนเขียน migration นี้ (31 ก.ค. 2569) บน instance หลัก:
--   orphan = 0 · legacy_only = 0 · has_user = 0 · total = 0
-- ตารางว่างเปล่า ไม่มีข้อมูลผู้ใช้ให้เสีย · แต่สคริปต์ยังเขียนแบบกันไว้เผื่อ instance
-- อื่น (dev/staging) มีแถวค้าง — จะรายงานจำนวนก่อนลบเสมอ ไม่ลบเงียบ ๆ
--
-- ── หมายเหตุประกอบ ───────────────────────────────────────────────────────────
-- คอมเมนต์ใน 005_create_saved_areas.sql:7 ที่ว่า "GET คืน list แบบ shared (ทุกคนเห็น)"
-- ล้าสมัยตั้งแต่ก่อน migration นี้แล้ว — routers/saved.py:11 คืนเฉพาะของเจ้าของเสมอ
-- ด้วยเหตุผลด้าน privacy (polygon ที่วาดอาจเป็นที่ดิน/บ้านผู้ใช้) · ไม่แก้ไฟล์ 005
-- ย้อนหลังตามธรรมเนียมของ repo นี้ (เทียบ 004 ที่ลบของ 002 โดยไม่แตะ 002)

BEGIN;

-- ── 1) แถวที่ไม่มี user_id จะเข้าถึงไม่ได้อีกเลยหลัง migration นี้ ────────────
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

-- ── 2) ตัด constraint/index/column ที่ผูกกับ owner_token ─────────────────────
-- DROP COLUMN ลบ constraint กับ index ที่อ้างคอลัมน์นี้ให้เองอยู่แล้ว แต่เขียนแยก
-- ให้อ่านออกว่าอะไรหายไปบ้าง (และ IF EXISTS ทำให้รันซ้ำได้)
ALTER TABLE saved_areas DROP CONSTRAINT IF EXISTS saved_areas_has_owner;  -- จาก 018
DROP INDEX IF EXISTS idx_saved_areas_owner;                               -- จาก 005
ALTER TABLE saved_areas DROP COLUMN IF EXISTS owner_token;

-- ── 3) user_id เป็นเจ้าของเพียงทางเดียว → บังคับ NOT NULL ────────────────────
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
