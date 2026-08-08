-- Migration 017: ปิดช่องโหว่ UNIQUE ที่ NULL เลี่ยงได้ (urban_ndvi_annual, planting_recommendations)
-- รันบน Supabase SQL Editor หลัง 016
--
-- ทั้งสองตารางใช้ `district IS NULL` แทนความหมาย "ระดับจังหวัด" แล้วกันข้อมูลซ้ำด้วย
-- UNIQUE(province, district, year) แต่ UNIQUE ของ PostgreSQL เป็น NULLS DISTINCT
-- โดยปริยาย — สอง NULL ไม่เท่ากัน ข้อจำกัดจึงคุมได้เฉพาะแถวระดับอำเภอ ส่วนแถวระดับ
-- จังหวัดของ (province, year) เดียวกัน INSERT ซ้ำได้ไม่จำกัด
--
-- ผลที่แย่กว่าข้อมูลซ้ำคือ ON CONFLICT ไม่ยิงกับแถวเหล่านั้น และ endpoint ที่อ่านด้วย
-- .limit(1) จะได้แถวไหนก็ได้แล้วแต่ planner · urban.py กับ recommend/endpoints.py
-- เขียนแคชด้วย .insert() ธรรมดา แถวระดับจังหวัดจึงเพิ่มใหม่ทุก cache miss
--
-- PG 15 เพิ่ม UNIQUE NULLS NOT DISTINCT ที่ตรงกับความหมายที่ตั้งใจพอดี เลือกวิธีนี้แทน
-- partial unique index สองอัน ซึ่ง ON CONFLICT ต้องระบุ predicate ให้ตรงทุกจุดที่เรียก
--
-- ลำดับ: ลบแถวซ้ำ (เก็บแถวใหม่สุด) → สลับ constraint → ทิ้ง index ที่ซ้ำ
-- รันซ้ำได้ ถ้ามี constraint แบบนี้อยู่แล้วจะข้ามตารางนั้นไป (ตรวจจาก
-- pg_index.indnullsnotdistinct — PG เก็บแฟล็กนี้ที่ index ไม่ใช่ที่ constraint)

BEGIN;

-- ตรวจเวอร์ชันก่อน เพราะ NULLS NOT DISTINCT ไม่มีใน PG 14 และต่ำกว่า
DO $$
BEGIN
    IF current_setting('server_version_num')::int < 150000 THEN
        RAISE EXCEPTION 'migration 017 ต้องใช้ PostgreSQL 15 ขึ้นไป (พบ %)',
                        current_setting('server_version');
    END IF;
END $$;

-- 1) ลบแถวซ้ำระดับจังหวัด (district IS NULL) ที่หลุดเข้ามาก่อนหน้านี้
WITH ranked AS (
    SELECT id,
           row_number() OVER (PARTITION BY province, district, year
                              ORDER BY created_at DESC NULLS LAST, id DESC) AS rn
      FROM urban_ndvi_annual
)
DELETE FROM urban_ndvi_annual u
      USING ranked r
      WHERE u.id = r.id AND r.rn > 1;

WITH ranked AS (
    SELECT id,
           row_number() OVER (PARTITION BY province, district, year
                              ORDER BY created_at DESC NULLS LAST, id DESC) AS rn
      FROM planting_recommendations
)
DELETE FROM planting_recommendations p
      USING ranked r
      WHERE p.id = r.id AND r.rn > 1;

-- 2) สลับ constraint
-- หมายเหตุ: PostgreSQL เก็บแฟล็ก NULLS NOT DISTINCT ไว้ที่ *index*
-- (pg_index.indnullsnotdistinct — เพิ่มใน PG 15) ไม่ใช่ที่ pg_constraint
-- จึงต้อง join ผ่าน pg_constraint.conindid
DO $$
DECLARE
    tbl     text;
    con     text;
    already boolean;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['urban_ndvi_annual', 'planting_recommendations'] LOOP

        -- หา unique constraint ที่คุม (province, district, year)
        -- ค้นจาก *ชุดคอลัมน์* ไม่ยึดชื่อ เผื่อ PostgreSQL ตั้งชื่อไม่เหมือนกัน
        SELECT c.conname, i.indnullsnotdistinct
          INTO con, already
          FROM pg_constraint c
          JOIN pg_index i ON i.indexrelid = c.conindid
         WHERE c.conrelid = tbl::regclass
           AND c.contype = 'u'
           AND (SELECT array_agg(a.attname::text ORDER BY a.attname)
                  FROM unnest(c.conkey) k
                  JOIN pg_attribute a
                    ON a.attrelid = c.conrelid AND a.attnum = k)
               = ARRAY['district', 'province', 'year'];

        IF con IS NULL THEN
            RAISE NOTICE '%: ไม่พบ unique constraint (province, district, year) — ข้าม', tbl;
            CONTINUE;
        END IF;

        IF already THEN
            RAISE NOTICE '%: constraint % เป็น NULLS NOT DISTINCT อยู่แล้ว — ข้าม', tbl, con;
            CONTINUE;
        END IF;

        EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', tbl, con);
        EXECUTE format(
            'ALTER TABLE %I ADD CONSTRAINT %I '
            'UNIQUE NULLS NOT DISTINCT (province, district, year)',
            tbl, tbl || '_area_year_key');
        RAISE NOTICE '%: เปลี่ยน % → %_area_year_key (NULLS NOT DISTINCT)', tbl, con, tbl;
    END LOOP;
END $$;

-- 3) index เดิมซ้ำกับ index ที่ unique constraint สร้างให้ (คอลัมน์ชุดเดียวกัน)
-- ปลอดภัยแม้ขั้นที่ 2 จะข้าม เพราะ unique constraint (เดิมหรือใหม่) มี index ของมันเองเสมอ
DROP INDEX IF EXISTS idx_urban_lookup;
DROP INDEX IF EXISTS idx_planting_lookup;

COMMIT;

-- ตรวจผล:
--   SELECT c.conrelid::regclass AS tbl, c.conname, i.indnullsnotdistinct
--     FROM pg_constraint c
--     JOIN pg_index i ON i.indexrelid = c.conindid
--    WHERE c.conrelid IN ('urban_ndvi_annual'::regclass,
--                         'planting_recommendations'::regclass)
--      AND c.contype = 'u';
--   → ต้องได้ indnullsnotdistinct = true ทั้งสองแถว
