-- Migration 003: เพิ่มคอลัมน์ impact ใน planting_recommendations
-- เก็บผลคำนวณ CO₂ + ΔLST + จำนวนต้นไม้ของ AI Recommend คู่กับ top_locations
-- ไม่ต้อง recompute ทุก request · โครงสร้าง JSONB ดู impact.py::build_impact
ALTER TABLE planting_recommendations ADD COLUMN IF NOT EXISTS impact JSONB;
