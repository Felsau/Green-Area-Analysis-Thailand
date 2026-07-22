-- Migration 013: saved_areas — ผูกกับบัญชีผู้ใช้ (user_id) แทน/เสริม owner_token
-- รันบน Supabase SQL Editor หลัง 012
--
-- ทั้งแอปบังคับล็อกอินก่อนเข้าถึง dashboard อยู่แล้ว (ดู App.js AuthGate) แต่
-- saved_areas เดิมผูก ownership กับ X-Owner-Token (localStorage ต่อเครื่อง) เท่านั้น
-- ทำให้ย้ายเครื่อง/ล้าง localStorage แล้วเห็นพื้นที่เก่าไม่ได้ และลบบัญชีก็ไม่ลบ
-- พื้นที่ที่บันทึกไว้จริง (ไม่มีอะไรผูกกับ auth.users เลย)
--
-- user_id nullable — ไม่ backfill จาก owner_token เพราะ token ไม่เคยผูกกับ identity
-- จริง (map เจ้าของจริงไม่ได้) แถวเก่ายังเข้าถึง/ลบได้ผ่าน owner_token เดิมต่อไป
-- (ดู routers/saved.py) แถวใหม่ทุกแถวหลัง migration นี้จะมี user_id เสมอเพราะ
-- POST /saved-areas ต้องล็อกอิน
--
-- ON DELETE CASCADE: ลบบัญชี (auth.admin.delete_user) → พื้นที่ที่ผูกกับ user_id
-- นี้ถูกลบตามอัตโนมัติ (ดู routers/account.py delete_me) ทำให้ข้อความ "ลบบัญชีถาวร —
-- พื้นที่ที่บันทึกไว้ทั้งหมดจะถูกลบ" ใน AccountModal เป็นจริงตามนั้น

ALTER TABLE saved_areas
  ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_saved_areas_user_id ON saved_areas(user_id);
