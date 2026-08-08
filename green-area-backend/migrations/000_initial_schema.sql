-- Migration 000 · Schema เริ่มต้นทั้งหมดของ Green Area Analysis
-- รวบรวมมาจากที่กระจายอยู่ใน generate_districts.py, maps.py, และ insert payloads
-- รันทีเดียวบน Supabase SQL Editor ตอนตั้งโปรเจกต์ใหม่
--
-- โครงสร้าง (11 ตาราง):
--   NDVI:           ndvi_annual, ndvi_monthly, district_ndvi_annual, district_ndvi_monthly
--   LST:            province_lst_annual, province_lst_monthly, district_lst_annual, district_lst_monthly
--   Urban subset:   urban_ndvi_annual            (WorldCover + WorldPop)
--   AI Recommend:   planting_recommendations
--   Population:     province_population          (seed data)

-- NDVI · Province annual
CREATE TABLE IF NOT EXISTS ndvi_annual (
  id BIGSERIAL PRIMARY KEY,
  province TEXT NOT NULL,
  year INTEGER NOT NULL,
  ndvi_mean FLOAT,
  ndvi_min FLOAT,
  ndvi_max FLOAT,
  green_area_pct FLOAT,
  green_area_km2 FLOAT,
  dense_area_pct FLOAT,      -- NDVI > 0.5 (ดูใน migration 001)
  dense_area_km2 FLOAT,
  total_area_km2 FLOAT,
  green_area_m2_per_person FLOAT,
  population INTEGER,
  who_status TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(province, year)
);

-- NDVI · Province monthly
CREATE TABLE IF NOT EXISTS ndvi_monthly (
  id BIGSERIAL PRIMARY KEY,
  province TEXT NOT NULL,
  year INTEGER NOT NULL,
  monthly_data JSONB,         -- [{month: 1, ndvi: 0.42}, ...]
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(province, year)
);

-- NDVI · District annual
CREATE TABLE IF NOT EXISTS district_ndvi_annual (
  id BIGSERIAL PRIMARY KEY,
  province TEXT NOT NULL,
  district TEXT NOT NULL,
  year INTEGER NOT NULL,
  ndvi_mean FLOAT,
  ndvi_min FLOAT,
  ndvi_max FLOAT,
  green_area_pct FLOAT,
  green_area_km2 FLOAT,
  dense_area_pct FLOAT,
  dense_area_km2 FLOAT,
  total_area_km2 FLOAT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(province, district, year)
);

-- NDVI · District monthly
CREATE TABLE IF NOT EXISTS district_ndvi_monthly (
  id BIGSERIAL PRIMARY KEY,
  province TEXT NOT NULL,
  district TEXT NOT NULL,
  year INTEGER NOT NULL,
  monthly_data JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(province, district, year)
);

-- LST · Province annual / monthly
CREATE TABLE IF NOT EXISTS province_lst_annual (
  id BIGSERIAL PRIMARY KEY,
  province TEXT NOT NULL,
  year INTEGER NOT NULL,
  lst_mean FLOAT,
  lst_min FLOAT,
  lst_max FLOAT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(province, year)
);

CREATE TABLE IF NOT EXISTS province_lst_monthly (
  id BIGSERIAL PRIMARY KEY,
  province TEXT NOT NULL,
  year INTEGER NOT NULL,
  monthly_data JSONB,         -- [{month: 1, lst: 32.1}, ...]
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(province, year)
);

-- LST · District annual / monthly
CREATE TABLE IF NOT EXISTS district_lst_annual (
  id BIGSERIAL PRIMARY KEY,
  province TEXT NOT NULL,
  district TEXT NOT NULL,
  year INTEGER NOT NULL,
  lst_mean FLOAT,
  lst_min FLOAT,
  lst_max FLOAT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(province, district, year)
);

CREATE TABLE IF NOT EXISTS district_lst_monthly (
  id BIGSERIAL PRIMARY KEY,
  province TEXT NOT NULL,
  district TEXT NOT NULL,
  year INTEGER NOT NULL,
  monthly_data JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(province, district, year)
);

-- Urban subset · พืชพรรณ/ประชากรเฉพาะเขต built-up (WorldCover + WorldPop)
CREATE TABLE IF NOT EXISTS urban_ndvi_annual (
  id BIGSERIAL PRIMARY KEY,
  province TEXT NOT NULL,
  district TEXT,              -- NULL = ระดับจังหวัด, มีค่า = ระดับอำเภอ
  year INTEGER NOT NULL,
  worldcover_year INTEGER,    -- proxy ของ built-up (เปลี่ยนช้า — fix 2021)
  worldpop_year INTEGER,      -- ปีล่าสุดของ WorldPop global = 2020
  total_area_km2 NUMERIC,
  urban_area_km2 NUMERIC,
  urban_share_pct NUMERIC,
  ndvi_mean_urban NUMERIC,
  green_in_urban_km2 NUMERIC,
  green_share_in_urban_pct NUMERIC,
  population_urban INTEGER,
  m2_per_person_urban NUMERIC,
  who_urban_pass BOOLEAN,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(province, district, year)
);

-- AI Recommend · Priority heatmap + top spots
CREATE TABLE IF NOT EXISTS planting_recommendations (
  id BIGSERIAL PRIMARY KEY,
  province TEXT NOT NULL,
  district TEXT,              -- NULL = ระดับจังหวัด
  year INTEGER NOT NULL,
  tile_url TEXT,              -- XYZ tile URL (GEE session — refresh ตอน serve)
  top_locations JSONB,        -- [{lng, lat, score}, ...]
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(province, district, year)
);

-- Population seed (ใช้คำนวณ green/person เทียบค่าอ้างอิง WHO 9 m²)
-- โหลด CSV จาก worldbank/census ใส่ก่อนใช้งาน
CREATE TABLE IF NOT EXISTS province_population (
  id BIGSERIAL PRIMARY KEY,
  province TEXT NOT NULL,
  year INTEGER NOT NULL,
  population INTEGER NOT NULL,
  UNIQUE(province, year)
);

-- Index แนะนำสำหรับ query ที่ใช้บ่อย
CREATE INDEX IF NOT EXISTS idx_ndvi_annual_year          ON ndvi_annual(year);
CREATE INDEX IF NOT EXISTS idx_district_ndvi_annual_prov ON district_ndvi_annual(province);
