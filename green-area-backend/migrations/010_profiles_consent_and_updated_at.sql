-- Migration 010: profiles — accepted_terms_at (หลักฐานยินยอมข้อกำหนด/PDPA) + updated_at
-- รันบน Supabase SQL Editor หลัง 009
--
-- accepted_terms_at: ตั้งค่าโดย trigger ตอนสร้างแถว (handle_new_user) เท่านั้น — ไม่รับ
-- ค่าจาก client เพื่อกัน client ปลอมเวลายินยอม · หน้า signup (frontend) บังคับติ๊ก
-- checkbox ก่อนเรียก signUp ได้ ดังนั้น "แถวถูกสร้าง" = "ผู้ใช้ยินยอมแล้ว" ในเส้นทางสมัคร
-- ปัจจุบัน (email/password ผ่านฟอร์มเดียว) — ถ้าเพิ่มเส้นทางสมัครอื่นในอนาคต (เช่น OAuth)
-- ต้องทบทวนสมมติฐานนี้ใหม่
--
-- updated_at: อัปเดตอัตโนมัติทุกครั้งที่แก้ profiles (เช่น เปลี่ยน display_name หรือ
-- promote role) ผ่าน trigger — ไม่ต้องพึ่ง backend set เอง กันลืมบางจุด

ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS accepted_terms_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- แถวเก่าก่อน migration นี้ไม่มีหลักฐานยินยอมจริง — ปล่อย accepted_terms_at เป็น NULL
-- (ไม่ backfill ด้วย NOW() เพราะนั่นจะเป็นการสร้างหลักฐานเท็จ)

CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
BEGIN
  INSERT INTO profiles (id, display_name, accepted_terms_at)
  VALUES (NEW.id, COALESCE(NEW.raw_user_meta_data->>'display_name', split_part(NEW.email, '@', 1)), NOW())
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION set_profiles_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS profiles_set_updated_at ON profiles;
CREATE TRIGGER profiles_set_updated_at
  BEFORE UPDATE ON profiles
  FOR EACH ROW EXECUTE FUNCTION set_profiles_updated_at();
