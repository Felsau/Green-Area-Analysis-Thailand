-- Migration 014: เก็บคุณภาพ/ความไม่แน่นอนของ NDVI composite (NFR-07)
-- รันบน Supabase SQL Editor หลัง 013
--
-- NDVI ทุกค่ามาจาก median composite ของ Sentinel-2 ทั้งปี — พื้นที่/ปีที่มีภาพปลอดเมฆ
-- น้อย (ภาคใต้ ฤดูฝน) ให้ค่าที่ความไม่แน่นอนสูงกว่ามาก แต่เดิมไม่มีที่เก็บข้อมูลนี้
--
-- เก็บเป็น jsonb ก้อนเดียวเพราะอ่าน/เขียนพร้อมกันเสมอ ไม่เคย query ทีละ field
-- โครงสร้างดู schemas.py::NDVIDataQuality · level = goal|threshold|below|none
-- ตามเกณฑ์ GCOS-245 (REQUIREMENTS [R33])
--
-- NULL = แถวที่คำนวณก่อน migration นี้ — _is_stale() จะ recompute ให้เองเมื่อมีคนเปิด

ALTER TABLE ndvi_annual
  ADD COLUMN IF NOT EXISTS data_quality JSONB;

ALTER TABLE district_ndvi_annual
  ADD COLUMN IF NOT EXISTS data_quality JSONB;
