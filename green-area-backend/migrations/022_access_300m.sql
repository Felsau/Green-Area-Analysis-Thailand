-- Migration 022: access_300m — cache ของ FR-18 (% ประชากรในระยะ 300 ม. จากพื้นที่สีเขียว)
-- รันบน Supabase SQL Editor หลัง 021 (ไม่บังคับ — routers/maps/analysis/access.py
-- ทำงานได้โดยไม่มีตารางนี้อยู่แล้ว แค่คำนวณใหม่ทุกครั้งแทนที่จะ cache)
--
-- ── ทำไม ─────────────────────────────────────────────────────────────────────
-- GET /analysis/access-300m/{province} คำนวณ fastDistanceTransform + WorldPop sum
-- สด (~5–15 วิ) ทุกครั้งถ้าไม่มีตารางนี้ให้ cache — เหมือน urban_ndvi_annual ก่อน
-- migration ตัวมันจะมี (ดู comment ในไฟล์ access.py สำหรับ DDL ที่ endpoint คาดหวัง)
--
-- ── NULLS NOT DISTINCT ตั้งแต่ต้น ─────────────────────────────────────────────
-- urban_ndvi_annual สร้างด้วย UNIQUE ธรรมดาตอนแรก (migration 000) แล้วมาแก้เป็น
-- NULLS NOT DISTINCT ทีหลังใน migration 017 หลังเจอบั๊กจริง (แถวระดับจังหวัด
-- district=NULL ซ้ำกันได้เพราะ Postgres UNIQUE เห็น NULL แต่ละอันเป็นคนละค่า) ·
-- ตารางนี้เจอ pattern เดียวกัน (district NULL = ระดับจังหวัด) จึงใส่ให้ถูกตั้งแต่แรก
-- ต้อง PostgreSQL 15+ (เหมือน migration 017 — โปรเจกต์นี้ยืนยันแล้วว่าเป็น PG15+)

BEGIN;

CREATE TABLE IF NOT EXISTS access_300m (
  id BIGSERIAL PRIMARY KEY,
  province TEXT NOT NULL,
  district TEXT,              -- NULL = ระดับจังหวัด, มีค่า = ระดับอำเภอ
  year INTEGER NOT NULL,
  distance_m NUMERIC,         -- เกณฑ์ระยะที่ใช้ (300 — เผื่ออนาคตอยากลองค่าอื่น)
  worldpop_year INTEGER,
  population_total INTEGER,
  population_within INTEGER,
  pct_within NUMERIC,
  cache_version INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE NULLS NOT DISTINCT (province, district, year)
);

-- composite FK ให้แถวระดับอำเภอ — เหมือน migration 021 (urban_ndvi_annual/
-- planting_recommendations) กัน district พิมพ์ผิด/เว้นวรรคต่างจาก districts จริง
-- MATCH SIMPLE (ค่าเริ่มต้น) ไม่เช็คแถวที่ district เป็น NULL — ระดับจังหวัดไม่กระทบ
ALTER TABLE access_300m
  ADD CONSTRAINT fk_access_300m_district
  FOREIGN KEY (province, district) REFERENCES districts(province, name_en);

ALTER TABLE access_300m ENABLE ROW LEVEL SECURITY;
-- deny-all เหมือนตารางอื่นทั้งหมด (migration 018) — backend ใช้ service-role
-- (BYPASSRLS) เท่านั้น ไม่มี path ไหนให้ anon key เขียน/อ่านตารางนี้ตรง ๆ

COMMIT;
