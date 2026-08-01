-- Migration 018: เปิด RLS ทุกตาราง (deny-all) + บังคับให้ saved_areas มีเจ้าของ
-- รันบน Supabase SQL Editor หลัง 017
--
-- ── ปัญหา ────────────────────────────────────────────────────────────────────
-- Supabase grant สิทธิ์ให้ role `anon` / `authenticated` กับตารางใน schema public
-- โดยปริยาย และ PostgREST เปิด REST endpoint ให้ทุกตารางอัตโนมัติ → ตารางที่ไม่ได้
-- ENABLE ROW LEVEL SECURITY จะ SELECT/INSERT/UPDATE/DELETE ได้จากภายนอกทั้งหมด
-- ด้วย anon key เพียงอย่างเดียว
--
-- anon key ไม่ใช่ความลับ — มันถูก build ลง JS bundle ตั้งแต่ต้น (VITE_SUPABASE_ANON_KEY
-- ใน lib/supabaseClient.js) ซึ่งเป็นวิธีมาตรฐานของ Supabase และปลอดภัย *ก็ต่อเมื่อ*
-- RLS ทำหน้าที่กั้นอยู่ ตอนนี้มีแค่ `profiles` ตารางเดียวที่เปิด RLS (migration 010)
-- ที่เหลือ 14 ตารางเปิดโล่ง — รวมถึง `saved_areas` ที่เป็นข้อมูลผู้ใช้จริง (polygon
-- ที่วาดเอง อาจเป็นที่ดิน/บ้าน — ดู docstring ใน routers/saved.py) ใครก็อ่านพิกัด
-- ของทุกคนหรือ DELETE ทิ้งทั้งตารางได้ โดยไม่ต้องล็อกอิน
--
-- ── ทำไม deny-all (เปิด RLS แต่ไม่ใส่ policy เลย) ────────────────────────────
-- ไม่มีอะไรในระบบเข้าถึงตารางเหล่านี้ด้วย anon key เลย:
--   - backend ใช้ service-role key (dependencies.py::get_supabase) ซึ่ง Supabase
--     ตั้ง BYPASSRLS ไว้ที่ตัว role → RLS ไม่มีผลกับ backend ทุกกรณี
--   - frontend ใช้ anon key เฉพาะ Supabase Auth (GoTrue) ไม่มี .from() สักจุด
--     (มีแค่ lib/supabaseClient.js + hooks/useAuth.js) ข้อมูลทั้งหมดวิ่งผ่าน FastAPI
-- policy ที่ใส่เพิ่มจึงมีแต่จะเพิ่มพื้นที่ให้พลาด — ปิดหมดคือสถานะที่ตรงกับการใช้งานจริง
--
-- ผลข้างเคียงที่ตั้งใจ: ถ้าวันหนึ่งอยากให้ frontend ยิง Supabase ตรงเพื่อลด latency
-- ต้องมาเพิ่ม policy ที่ตารางนั้นก่อน (ตั้งใจให้เป็น explicit opt-in) เช่น
--   CREATE POLICY provinces_public_read ON provinces FOR SELECT TO anon USING (true);
--
-- ── ทำไมไม่ REVOKE grant ทิ้งด้วย ────────────────────────────────────────────
-- RLS พอแล้วสำหรับ PostgREST และย้อนกลับง่ายกว่า (ALTER TABLE ... DISABLE ROW LEVEL
-- SECURITY) ส่วน REVOKE ต้องไล่ GRANT คืนทีละตารางถ้าเปลี่ยนใจ · service_role มี
-- grant ของตัวเองอยู่แล้วจึงไม่กระทบ backend ไม่ว่าทางไหน
--
-- รันซ้ำได้: ENABLE ROW LEVEL SECURITY idempotent ในตัว · CHECK อยู่ใน DO block

BEGIN;

-- ── 1) เปิด RLS ทุกตาราง ─────────────────────────────────────────────────────
-- `profiles` ไม่อยู่ในลิสต์ — เปิดไปแล้วใน 010 พร้อม policy profiles_select_own
-- (เจ้าของอ่านโปรไฟล์ตัวเองได้ ส่วน write ผ่าน backend เท่านั้น) อย่าแตะซ้ำ
DO $$
DECLARE
    t TEXT;
    tables TEXT[] := ARRAY[
        -- cache / fact tables (คำนวณใหม่ได้ ไม่มีข้อมูลผู้ใช้)
        'ndvi_annual', 'ndvi_monthly', 'district_ndvi_annual', 'district_ndvi_monthly',
        'province_lst_annual', 'province_lst_monthly', 'district_lst_annual',
        'district_lst_monthly', 'urban_ndvi_annual', 'planting_recommendations',
        -- reference / seed data
        'provinces', 'districts', 'province_population',
        -- ข้อมูลผู้ใช้ ← ตัวที่เร่งด่วนที่สุดในลิสต์นี้
        'saved_areas'
    ];
BEGIN
    FOREACH t IN ARRAY tables LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    END LOOP;
    RAISE NOTICE 'เปิด RLS แล้ว % ตาราง (deny-all — ไม่มี policy ให้ anon/authenticated)',
                 array_length(tables, 1);
END $$;

-- ── 2) saved_areas ต้องมีเจ้าของเสมอ ─────────────────────────────────────────
-- ตอนนี้ทั้ง user_id และ owner_token เป็น nullable ทั้งคู่ → แถวที่ NULL ทั้งสอง
-- ตัวจะไม่มีใครเป็นเจ้าของ: list ไม่เจอ (filter ด้วย user_id) และ DELETE ไม่ผ่าน
-- (is_owner เป็น false เสมอ) เหลือแต่ admin ที่ลบได้ → กลายเป็นขยะที่ลบไม่ออก
--
-- ใช้ OR ไม่ใช่ num_nonnulls(...) = 1 โดยตั้งใจ: แถวที่ POST หลัง migration 013
-- มีทั้ง user_id และ owner_token พร้อมกันเป็นเรื่องปกติ (saved.py::create_saved_area
-- เขียนทั้งสองค่า) constraint แบบ "ต้องมีอย่างเดียว" จะปฏิเสธ insert ปกติทั้งหมด
--
-- NOT VALID: บังคับกับ INSERT/UPDATE ต่อจากนี้ แต่ไม่สแกนแถวเดิม — ไม่ให้ migration
-- ล้มเพราะข้อมูลเก่าที่อาจกำพร้าอยู่ก่อนแล้ว · migration 019 (ตัด owner_token) จะ
-- ล้างแถวกำพร้าแล้วเปลี่ยนเป็น user_id NOT NULL ซึ่งครอบคลุมกว่านี้
DO $$
DECLARE
    orphans INTEGER;
BEGIN
    SELECT count(*) INTO orphans
      FROM saved_areas
     WHERE user_id IS NULL AND owner_token IS NULL;

    IF orphans > 0 THEN
        RAISE WARNING 'saved_areas: มี % แถวที่ไม่มีเจ้าของอยู่ก่อนแล้ว — '
                      'constraint เป็น NOT VALID จึงไม่ block · ดูรายการด้วย '
                      'SELECT id, label, created_at FROM saved_areas '
                      'WHERE user_id IS NULL AND owner_token IS NULL', orphans;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'saved_areas_has_owner') THEN
        ALTER TABLE saved_areas ADD CONSTRAINT saved_areas_has_owner
            CHECK (user_id IS NOT NULL OR owner_token IS NOT NULL) NOT VALID;
    END IF;
END $$;

COMMIT;

-- ตรวจผล — ต้องไม่เหลือตารางไหนที่ rowsecurity = false:
--   SELECT tablename, rowsecurity
--     FROM pg_tables WHERE schemaname = 'public' ORDER BY rowsecurity, tablename;
--
-- ตรวจว่าไม่มี policy หลุดมา (ควรเจอแค่ profiles_select_own):
--   SELECT tablename, policyname FROM pg_policies WHERE schemaname = 'public';
--
-- ทดสอบจากภายนอกด้วย anon key จริง (ต้องได้ [] ไม่ใช่ข้อมูล):
--   curl "$SUPABASE_URL/rest/v1/saved_areas?select=id" \
--        -H "apikey: $ANON_KEY" -H "Authorization: Bearer $ANON_KEY"
