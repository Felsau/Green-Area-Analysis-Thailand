-- Migration 002 · เพิ่ม CHECK constraints + cache metadata (cache_version, expires_at)
-- รันบน Supabase SQL Editor หลัง 001
--
-- สิ่งที่ทำ:
--   1. เพิ่ม CHECK constraints บน year/NDVI/LST/percent ตาม domain ของข้อมูล
--      (ป้องกัน insert ค่าผิด — ตอนนี้ backend validate อยู่แล้ว แต่ DB เป็นแนวสุดท้าย)
--   2. เพิ่ม cache_version (default 1 = ตรงกับ CURRENT_CACHE_VERSION) สำหรับ NDVI tables — ใช้แทน heuristic _is_stale
--      backend อนาคตจะอัปเดต stale logic ให้ตรวจ version แทน
--   3. เพิ่ม expires_at บน tile-URL cache (planting_recommendations)
--      — tile URL ใช้ session token GEE ที่หมดอายุภายในไม่กี่ชั่วโมง
--   4. เพิ่ม index บน column ที่ใช้ filter บ่อย
--   5. เพิ่ม FK soft link จาก ndvi_annual.province → province_population
--      (ไม่บังคับ FK constraint จริง เพราะ population เป็น seed data ที่อาจมาไม่ครบ
--       — ใช้ index ช่วย JOIN/lookup แทน)

-- CHECK constraints
-- ใช้ DO block เพื่อให้ idempotent (ALTER ... ADD CONSTRAINT ไม่มี IF NOT EXISTS)
DO $$
BEGIN
  -- year range (1980–2100 = ครอบคลุมตลอดอายุโปรเจกต์)
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ndvi_annual_year_range') THEN
    ALTER TABLE ndvi_annual ADD CONSTRAINT ndvi_annual_year_range
      CHECK (year BETWEEN 1980 AND 2100);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ndvi_monthly_year_range') THEN
    ALTER TABLE ndvi_monthly ADD CONSTRAINT ndvi_monthly_year_range
      CHECK (year BETWEEN 1980 AND 2100);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'district_ndvi_annual_year_range') THEN
    ALTER TABLE district_ndvi_annual ADD CONSTRAINT district_ndvi_annual_year_range
      CHECK (year BETWEEN 1980 AND 2100);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'district_ndvi_monthly_year_range') THEN
    ALTER TABLE district_ndvi_monthly ADD CONSTRAINT district_ndvi_monthly_year_range
      CHECK (year BETWEEN 1980 AND 2100);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'province_lst_annual_year_range') THEN
    ALTER TABLE province_lst_annual ADD CONSTRAINT province_lst_annual_year_range
      CHECK (year BETWEEN 1980 AND 2100);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'province_lst_monthly_year_range') THEN
    ALTER TABLE province_lst_monthly ADD CONSTRAINT province_lst_monthly_year_range
      CHECK (year BETWEEN 1980 AND 2100);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'district_lst_annual_year_range') THEN
    ALTER TABLE district_lst_annual ADD CONSTRAINT district_lst_annual_year_range
      CHECK (year BETWEEN 1980 AND 2100);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'district_lst_monthly_year_range') THEN
    ALTER TABLE district_lst_monthly ADD CONSTRAINT district_lst_monthly_year_range
      CHECK (year BETWEEN 1980 AND 2100);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'urban_ndvi_year_range') THEN
    ALTER TABLE urban_ndvi_annual ADD CONSTRAINT urban_ndvi_year_range
      CHECK (year BETWEEN 1980 AND 2100);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'planting_recs_year_range') THEN
    ALTER TABLE planting_recommendations ADD CONSTRAINT planting_recs_year_range
      CHECK (year BETWEEN 1980 AND 2100);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pop_year_range') THEN
    ALTER TABLE province_population ADD CONSTRAINT pop_year_range
      CHECK (year BETWEEN 1980 AND 2100);
  END IF;

  -- NDVI range: ทางทฤษฎี [-1, 1] · ในทาง land กรณีจริง [-0.5, 1]
  -- ใช้ -1, 1 เพื่อ allow น้ำ/cloud artifact ที่จะถูก mask ใน application layer
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ndvi_annual_ndvi_range') THEN
    ALTER TABLE ndvi_annual ADD CONSTRAINT ndvi_annual_ndvi_range
      CHECK (ndvi_mean IS NULL OR (ndvi_mean BETWEEN -1 AND 1));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'district_ndvi_ndvi_range') THEN
    ALTER TABLE district_ndvi_annual ADD CONSTRAINT district_ndvi_ndvi_range
      CHECK (ndvi_mean IS NULL OR (ndvi_mean BETWEEN -1 AND 1));
  END IF;

  -- LST range: บนผิวโลก พื้นที่ไทย [-10, 70] °C ครอบคลุม edge cases ทุกกรณี
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'province_lst_range') THEN
    ALTER TABLE province_lst_annual ADD CONSTRAINT province_lst_range
      CHECK (lst_mean IS NULL OR (lst_mean BETWEEN -10 AND 70));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'district_lst_range') THEN
    ALTER TABLE district_lst_annual ADD CONSTRAINT district_lst_range
      CHECK (lst_mean IS NULL OR (lst_mean BETWEEN -10 AND 70));
  END IF;

  -- Percent range
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ndvi_annual_pct_range') THEN
    ALTER TABLE ndvi_annual ADD CONSTRAINT ndvi_annual_pct_range
      CHECK (green_area_pct IS NULL OR (green_area_pct BETWEEN 0 AND 100));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'district_ndvi_pct_range') THEN
    ALTER TABLE district_ndvi_annual ADD CONSTRAINT district_ndvi_pct_range
      CHECK (green_area_pct IS NULL OR (green_area_pct BETWEEN 0 AND 100));
  END IF;

  -- Population ต้องไม่ติดลบ
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pop_nonneg') THEN
    ALTER TABLE province_population ADD CONSTRAINT pop_nonneg
      CHECK (population >= 0);
  END IF;
END $$;

-- Cache versioning + expiry
-- cache_version: bump เลขนี้ใน backend เมื่อเปลี่ยน compute logic
-- (เช่น เพิ่ม water mask, เปลี่ยน threshold) → backend lookup จะถือว่า row เก่า stale
ALTER TABLE ndvi_annual          ADD COLUMN IF NOT EXISTS cache_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE district_ndvi_annual ADD COLUMN IF NOT EXISTS cache_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE ndvi_monthly         ADD COLUMN IF NOT EXISTS cache_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE district_ndvi_monthly ADD COLUMN IF NOT EXISTS cache_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE province_lst_annual  ADD COLUMN IF NOT EXISTS cache_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE district_lst_annual  ADD COLUMN IF NOT EXISTS cache_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE province_lst_monthly ADD COLUMN IF NOT EXISTS cache_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE district_lst_monthly ADD COLUMN IF NOT EXISTS cache_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE urban_ndvi_annual    ADD COLUMN IF NOT EXISTS cache_version INTEGER NOT NULL DEFAULT 1;

-- expires_at: ใช้กับ tile URL ที่ผูก GEE session token (หมดอายุภายใน ~ชั่วโมง)
-- backend อนาคตจะลบ row ที่ NOW() > expires_at อัตโนมัติ
ALTER TABLE planting_recommendations ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

-- Indexes สำหรับ query ที่ใช้บ่อย
-- province_population: lookup population ตาม (province, year) ทำบ่อยใน get_ndvi
CREATE INDEX IF NOT EXISTS idx_pop_province_year      ON province_population(province, year);
-- district_ndvi/lst: filter ตาม province + year ทำใน get_district_summary
CREATE INDEX IF NOT EXISTS idx_district_ndvi_prov_year ON district_ndvi_annual(province, year);
CREATE INDEX IF NOT EXISTS idx_district_lst_prov_year  ON district_lst_annual(province, year);
-- planting_recommendations: lookup ตาม (province, district, year) ทำใน recommend.py
CREATE INDEX IF NOT EXISTS idx_planting_lookup        ON planting_recommendations(province, district, year);
CREATE INDEX IF NOT EXISTS idx_planting_expires       ON planting_recommendations(expires_at) WHERE expires_at IS NOT NULL;
-- urban_ndvi: lookup ตาม (province, district, year)
CREATE INDEX IF NOT EXISTS idx_urban_lookup           ON urban_ndvi_annual(province, district, year);
