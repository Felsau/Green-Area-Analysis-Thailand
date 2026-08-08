-- Migration 024: สร้าง UNIQUE NULLS NOT DISTINCT ให้ urban_ndvi_annual
-- รันบน Supabase SQL Editor หลัง 023 · ต้อง PostgreSQL 15+
--
-- migration 017 ตั้งใจให้ตารางนี้ได้ constraint แบบ NULLS NOT DISTINCT แต่ DO block
-- ของมันเขียนไว้ให้ *สลับ* constraint เดิมเท่านั้น — พอหา unique constraint บน
-- (province, district, year) ไม่เจอ ก็ CONTINUE ข้ามไปพร้อม RAISE NOTICE
-- ตารางนี้ไม่มี constraint นั้นอยู่จริง (ทั้งที่ 000_initial_schema.sql เขียน
-- UNIQUE(province, district, year) ไว้) 017 จึงเป็น no-op สำหรับตารางนี้
-- ส่วน planting_recommendations มี constraint เดิมอยู่ 017 เลยสลับให้สำเร็จ
--
-- ยืนยันด้วยการทดลอง 8 ส.ค. 2569 หลังรัน 017 แล้ว: insert แถวซ้ำทั้งระดับจังหวัด
-- (district NULL) และระดับอำเภอ ผ่านทั้งคู่ = ไม่มี unique constraint เลยแม้แบบธรรมดา
-- ผลจริงที่เกิดแล้ว: Yasothon/2026 ได้ 3 แถวซ้ำจากการรันสคริปต์วอร์มแคช 3 รอบ
-- โดยฐานข้อมูลไม่ฟ้อง — โค้ดอ่านแคชด้วย .limit(1) จึงได้แถวไหนก็ได้แล้วแต่ planner
--
-- ตรวจแล้วว่าไม่มีคีย์ซ้ำค้างอยู่ (155 แถว) จึงเพิ่ม constraint ได้ตรง ๆ แต่ยังใส่
-- ขั้นลบซ้ำไว้ให้รันบน instance อื่นได้ปลอดภัย — รายงานจำนวนก่อนลบเสมอ

BEGIN;

DO $$
BEGIN
    IF current_setting('server_version_num')::int < 150000 THEN
        RAISE EXCEPTION 'migration 024 ต้องใช้ PostgreSQL 15 ขึ้นไป (พบ %)',
                        current_setting('server_version');
    END IF;
END $$;

-- 1) ลบแถวซ้ำถ้ามี เก็บแถวใหม่สุดไว้ (ธรรมเนียมเดียวกับ 017)
DO $$
DECLARE
    dupes INTEGER;
BEGIN
    WITH ranked AS (
        SELECT id,
               row_number() OVER (PARTITION BY province, district, year
                                  ORDER BY created_at DESC NULLS LAST, id DESC) AS rn
          FROM urban_ndvi_annual
    )
    DELETE FROM urban_ndvi_annual u
          USING ranked r
          WHERE u.id = r.id AND r.rn > 1;

    GET DIAGNOSTICS dupes = ROW_COUNT;
    IF dupes > 0 THEN
        RAISE WARNING 'urban_ndvi_annual: ลบแถวซ้ำ % แถว (เก็บแถวใหม่สุดของแต่ละคีย์)', dupes;
    ELSE
        RAISE NOTICE 'urban_ndvi_annual: ไม่มีแถวซ้ำ';
    END IF;
END $$;

-- 2) เพิ่ม constraint (ข้ามถ้ามีอยู่แล้ว — รันซ้ำได้)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM pg_constraint c
          JOIN pg_index i ON i.indexrelid = c.conindid
         WHERE c.conrelid = 'urban_ndvi_annual'::regclass
           AND c.contype = 'u'
           AND i.indnullsnotdistinct
           AND (SELECT array_agg(a.attname::text ORDER BY a.attname)
                  FROM unnest(c.conkey) k
                  JOIN pg_attribute a
                    ON a.attrelid = c.conrelid AND a.attnum = k)
               = ARRAY['district', 'province', 'year']
    ) THEN
        RAISE NOTICE 'urban_ndvi_annual: มี constraint NULLS NOT DISTINCT อยู่แล้ว — ข้าม';
    ELSE
        ALTER TABLE urban_ndvi_annual
            ADD CONSTRAINT urban_ndvi_annual_area_year_key
            UNIQUE NULLS NOT DISTINCT (province, district, year);
        RAISE NOTICE 'urban_ndvi_annual: เพิ่ม urban_ndvi_annual_area_year_key แล้ว';
    END IF;
END $$;

COMMIT;

-- ตรวจผล — ต้องได้ indnullsnotdistinct = true:
--   SELECT c.conname, i.indnullsnotdistinct
--     FROM pg_constraint c
--     JOIN pg_index i ON i.indexrelid = c.conindid
--    WHERE c.conrelid = 'urban_ndvi_annual'::regclass AND c.contype = 'u';
