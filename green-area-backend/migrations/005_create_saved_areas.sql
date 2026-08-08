-- Migration 005: ตาราง saved_areas — บันทึก polygon ที่ผู้ใช้วาดเอง + ผลวิเคราะห์
-- ต่างจาก cache tables อื่น: นี่คือ *ข้อมูลผู้ใช้* ไม่ใช่ cache → DELETE /cache ห้ามลบตารางนี้
-- (ไม่อยู่ใน CACHE_TABLES ของ main.py)
--
-- ownership แบบเบา (แอปยังไม่มี login): owner_token = UUID สุ่มที่ frontend เก็บใน
-- localStorage แล้วส่งมาทาง header X-Owner-Token · ใช้ตัดสินสิทธิ์ลบ (ลบได้เฉพาะของตัวเอง
-- หรือ admin) · GET คืน list แบบ shared (ทุกคนเห็น) พร้อม flag `mine`
--
-- structure JSONB:
--   geometry       = GeoJSON Polygon ที่วาด
--   analysis       = response ของ POST /analysis/custom-area (NDVI/green/WHO/LST)
--   recommendation = response ของ POST /recommend/custom-area (top spots/impact/species) — nullable

CREATE TABLE IF NOT EXISTS saved_areas (
  id             BIGSERIAL PRIMARY KEY,
  label          TEXT,
  geometry       JSONB NOT NULL,
  year           INTEGER NOT NULL,
  area_km2       NUMERIC,
  province       TEXT,
  analysis       JSONB,
  recommendation JSONB,
  owner_token    TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT saved_areas_year_range CHECK (year BETWEEN 1980 AND 2100)
);

-- list ใหม่สุดก่อน + filter ตามจังหวัด/เจ้าของ
CREATE INDEX IF NOT EXISTS idx_saved_areas_created  ON saved_areas(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_saved_areas_province ON saved_areas(province);
CREATE INDEX IF NOT EXISTS idx_saved_areas_owner    ON saved_areas(owner_token);
