-- Migration 009: ndvi_annual.population_year — ปีของข้อมูลประชากรที่ใช้คำนวณ m²/คน
-- รันบน Supabase SQL Editor หลัง 008
--
-- get_population() จะ fallback ไป "ปีประชากรล่าสุดที่มี" ถ้าปีที่ขอไม่มีใน
-- province_population (seed data มักมีถึงปีล่าสุดไม่กี่ปี) → green_area_m2_per_person
-- อาจผสม NDVI ปีหนึ่งกับประชากรอีกปี (เช่น NDVI 2024 + ประชากร 2022) โดยผู้ใช้ไม่รู้
--
-- เก็บ "ปีจริง" ของประชากรไว้ใน column นี้ เพื่อให้ frontend แสดง note ได้ว่าค่า
-- ต่อหัวประชากรอ้างอิงประชากรปีไหน · API ส่งกลับใน NDVIResponse.population_year
--
-- nullable + ไม่ bump cache_version โดยตั้งใจ: ค่า NDVI ของ row เก่ายัง valid อยู่
-- (ไม่ต้อง recompute GEE) · row เก่าได้ population_year = NULL → frontend ซ่อน note,
-- row ใหม่ที่ app เขียนต่อจากนี้จะเติมค่าเอง · เติมเต็มขึ้นเรื่อยๆ ตอน cache refresh
ALTER TABLE ndvi_annual
    ADD COLUMN IF NOT EXISTS population_year INTEGER;

COMMENT ON COLUMN ndvi_annual.population_year IS
    'ปีของข้อมูลประชากรที่ใช้คำนวณ green_area_m2_per_person · อาจต่างจาก year ถ้า get_population fallback';
