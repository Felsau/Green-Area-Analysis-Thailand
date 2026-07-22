-- Migration 012: profiles — organization (หน่วยงาน, ไม่บังคับกรอก)
-- รันบน Supabase SQL Editor หลัง 011
--
-- Optional field เดียว ไม่มี validation พิเศษระดับ DB (length บังคับที่ Pydantic
-- ฝั่ง backend แทน — ดู routers/account.py MAX_NAME_LEN) เพราะเป็นแค่ metadata
-- แสดงผล ไม่ใช้ตัดสินสิทธิ์หรือ query กรองด้วย

ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS organization TEXT;

CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
BEGIN
  INSERT INTO profiles (id, display_name, accepted_terms_at, organization)
  VALUES (
    NEW.id,
    COALESCE(NEW.raw_user_meta_data->>'display_name', split_part(NEW.email, '@', 1)),
    NOW(),
    NULLIF(NEW.raw_user_meta_data->>'organization', '')
  )
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$;
