-- Migration 010: profiles -- โปรไฟล์ผู้ใช้คู่กับ Supabase Auth (auth.users)
-- รันบน Supabase SQL Editor หลัง 009
--
-- Auth เองใช้ Supabase Auth (GoTrue) ตรง ๆ — ตารางนี้เก็บเฉพาะ field ที่แอปต้องใช้
-- เพิ่มจาก auth.users (ชื่อที่แสดง + role) โดย 1 แถวต่อ 1 user (id = auth.users.id)
--
-- role: 'user' (default) หรือ 'admin' — ตั้งโดย SQL ตรง ๆ ใน Supabase เท่านั้น
-- (ไม่มี self-serve promote เป็น admin จากแอป) เช่น:
--   UPDATE profiles SET role = 'admin' WHERE id = '<uuid ของ user>';
--
-- RLS: เปิดแต่ไม่มี policy update/insert/delete ให้ authenticated/anon เลย —
-- ทุก write (รวม role) ผ่าน backend ด้วย service-role key เท่านั้น (routers/account.py)
-- กัน client เรียก Supabase REST ตรง ๆ แล้วเปลี่ยน role ตัวเองเป็น admin

CREATE TABLE IF NOT EXISTS profiles (
  id           UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  display_name TEXT NOT NULL DEFAULT '',
  role         TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS profiles_select_own ON profiles;
CREATE POLICY profiles_select_own ON profiles
  FOR SELECT USING (auth.uid() = id);

-- Trigger: สร้างแถว profiles อัตโนมัติทุกครั้งที่มี user ใหม่สมัคร (auth.users insert)
-- display_name เริ่มจาก raw_user_meta_data.display_name (ที่ signUp ส่งมา) หรือ
-- ส่วนหน้า @ ของอีเมลถ้าไม่ได้ส่งมา
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
BEGIN
  INSERT INTO profiles (id, display_name)
  VALUES (NEW.id, COALESCE(NEW.raw_user_meta_data->>'display_name', split_part(NEW.email, '@', 1)))
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION handle_new_user();
