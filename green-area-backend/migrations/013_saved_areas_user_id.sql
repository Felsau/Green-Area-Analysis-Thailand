-- Migration 013: saved_areas — ผูกกับบัญชีผู้ใช้ (user_id) แทน/เสริม owner_token
-- รันบน Supabase SQL Editor หลัง 012
--
-- saved_areas เดิมผูก ownership กับ X-Owner-Token (localStorage ต่อเครื่อง) เท่านั้น
-- ย้ายเครื่องหรือล้าง localStorage แล้วเห็นพื้นที่เก่าไม่ได้ และลบบัญชีก็ไม่ลบพื้นที่
-- ที่บันทึกไว้ เพราะไม่มีอะไรผูกกับ auth.users เลย
--
-- user_id nullable และไม่ backfill จาก owner_token เพราะ token ไม่เคยผูกกับ identity
-- จริง · แถวใหม่หลัง migration นี้มี user_id เสมอเพราะ POST /saved-areas ต้องล็อกอิน
--
-- ON DELETE CASCADE ทำให้ลบบัญชีแล้วพื้นที่ที่บันทึกไว้ถูกลบตาม — ข้อความ "ลบบัญชี
-- ถาวร พื้นที่ที่บันทึกไว้ทั้งหมดจะถูกลบ" ใน AccountModal จึงเป็นจริง

ALTER TABLE saved_areas
  ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_saved_areas_user_id ON saved_areas(user_id);
