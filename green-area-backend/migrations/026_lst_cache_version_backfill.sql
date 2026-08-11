-- Migration 026: เลื่อน cache_version ของตาราง LST จาก 1 → 2
-- รันบน Supabase SQL Editor หลัง 025 · ต้องรัน "ก่อน" deploy โค้ดที่เติม guard
--
-- ที่มา: ทั้ง 4 ตาราง LST เขียน cache_version ตอน insert แต่ไม่เคยมีโค้ดอ่านกลับมา
-- เทียบเลย (ต่างจาก ndvi_annual ที่เช็คผ่าน _is_stale และ urban/access ที่เช็คตรง ๆ)
-- รอบนี้เติม guard ให้ครบ — แต่ถ้าเติมเฉย ๆ แถว v1 ที่ค้างอยู่จะถูกมองว่า stale
-- ทั้งหมดแล้วโดน recompute ผ่าน GEE ทั้งที่ค่าที่ได้จะเท่าเดิมเป๊ะ
--
-- เหตุผลที่ค่าเท่าเดิม: CURRENT_CACHE_VERSION v1→v2 คือการเปลี่ยน cloud masking ของ
-- *Sentinel-2* จาก QA60 เป็น Cloud Score+ (ดู gee_utils.clean_s2_collection) ซึ่ง
-- ไม่เกี่ยวกับ LST เลย — LST มาจาก Landsat 8/9 ที่ mask ด้วย QA_PIXEL bit 3/4
-- (gee_utils._mask_landsat_clouds) และไม่ได้ถูกแก้ในรอบนั้นหรือรอบไหนเลย
-- แถว v1 กับ v2 ของตาราง LST จึงคำนวณด้วย logic เดียวกันทุกประการ
--
-- ⚠️ ห้ามทำแบบเดียวกันกับ ndvi_monthly / district_ndvi_monthly — สองตารางนั้นใช้
--    clean_s2_collection จริง (_compute_ndvi_monthly) ค่าที่ cache ด้วย v1 มาจาก
--    QA60 ที่เลิกใช้แล้ว ต้องปล่อยให้ recompute ใหม่ ไม่ใช่เลื่อน version หนี

BEGIN;

DO $$
DECLARE
    t TEXT;
    moved INTEGER;
    total INTEGER := 0;
BEGIN
    FOREACH t IN ARRAY ARRAY['province_lst_annual', 'province_lst_monthly',
                             'district_lst_annual', 'district_lst_monthly']
    LOOP
        EXECUTE format(
            'UPDATE %I SET cache_version = 2 WHERE cache_version IS NULL OR cache_version < 2', t);
        GET DIAGNOSTICS moved = ROW_COUNT;
        total := total + moved;
        RAISE NOTICE '%: เลื่อน cache_version → 2 จำนวน % แถว', t, moved;
    END LOOP;
    RAISE NOTICE 'รวมทั้งสิ้น % แถว (ค่าที่เก็บไว้ไม่เปลี่ยน — แค่ติดป้ายเวอร์ชันให้ตรงความจริง)', total;
END $$;

COMMIT;

-- ตรวจผล — ทั้ง 4 ตารางต้องไม่เหลือแถว cache_version < 2:
--   SELECT 'province_lst_annual'  AS t, count(*) FROM province_lst_annual  WHERE cache_version < 2
--   UNION ALL SELECT 'province_lst_monthly',  count(*) FROM province_lst_monthly  WHERE cache_version < 2
--   UNION ALL SELECT 'district_lst_annual',   count(*) FROM district_lst_annual   WHERE cache_version < 2
--   UNION ALL SELECT 'district_lst_monthly',  count(*) FROM district_lst_monthly  WHERE cache_version < 2;
--
-- ส่วน ndvi_monthly / district_ndvi_monthly ต้อง "ยังเหลือ" แถว v1 อยู่ (ตั้งใจ —
-- จะถูก recompute ทีละแถวเมื่อมีคนเปิดดู หลัง deploy โค้ดที่เติม guard แล้ว):
--   SELECT count(*) FROM ndvi_monthly WHERE cache_version < 2;           -- คาดว่า 63
--   SELECT count(*) FROM district_ndvi_monthly WHERE cache_version < 2;  -- คาดว่า 3
