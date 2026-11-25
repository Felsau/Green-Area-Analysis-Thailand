# C18 · แก้ชื่อไทยของตาคลีและพยุหะคีรีในระบบหลัก (สัปดาห์ที่ 4, 23–27 พ.ย. 2569)

จัดทำ 25/11/2569 โดยชยากร · **ข้อมูลจริง (ไฟล์อำเภอของระบบ · OCHA tha_admin2 ชุดเดียวกับ C15 · kongvut ปัจจุบัน) · รันในเครื่อง (local) · ไม่ได้ deploy · ไม่ได้แตะ Supabase จริง**

## Commit และ tag (worktree `<worktree-c18>` · บรานช์ `23_27-chayakorn-c18` จาก `c944540` = origin/main ตอนเริ่ม)
| | hash | ข้อความ |
|---|---|---|
| commit | `7658e54ffbe084d750937f83b7313e739e860cd2` | fix(districts): correct the Thai names of Takhli and Phayuha Khiri |
| tag C18 (annotated) | object `170fad832eba40427b14f6099bee1dace4e6dbb4` → `7658e54` | C18: Thai names of Takhli and Phayuha Khiri fixed in both district files |

- 3 ไฟล์: `green-area-backend/add_district_th_names.py` (+4 บรรทัด) · `green-area-backend/data/thailand_districts.json` · `green-area-frontend/public/thailand_districts.json`
- ไฟล์อำเภอ: 2,631,549 → 2,631,552 ไบต์ · SHA256 `f4231a76…` → `67f3bc8ecf235603df11705164d12639929cc327f036e2b67c5c426313aac1b5` (สองสำเนาเท่ากัน)
- ยังไม่ push

## 1. ตรวจรูปก่อนแก้ (`c18_shape_check.py` · `c18-shape-check.csv` `.json`)
% = พื้นที่รูปในระบบที่ทับกับรูปของ OCHA ÷ พื้นที่รูปในระบบ · คำนวณใน UTM 47N (กฎ `ldd_policy.metric_crs`) · ไม่มีรูปใดต้องซ่อม

| รูปในระบบ (name_th เดิม) | TH6007 ตาคลี | TH6008 ท่าตะโก | TH6010 พยุหะคีรี | TH6011 ลาดยาว |
|---|---|---|---|---|
| Takhli (ท่าตะโก) | **94.87%** | 0.00% | 0.37% | 0.00% |
| ThaTako (ท่าตะโก) | 0.00% | **92.35%** | 0.09% | 0.00% |
| LatYao (ลาดยาว) | 0.00% | 0.00% | 0.00% | **95.50%** |
| PhayuhaKhiri (ลาดยาว) | 0.86% | 0.21% | **93.41%** | 0.00% |

- ทั้ง 4 อำเภอทับกับอำเภอของ OCHA ที่ชื่ออังกฤษตรงกันเกิน 90% จึงทำต่อ · รูปถูก ผิดแค่ชื่อไทย
- **BangSai ของพระนครศรีอยุธยา (รายงานอย่างเดียว ไม่แก้):** ทับ TH1404 บางไทร **59.52%** และ TH1413 บางซ้าย **34.27%** ของรูปในระบบ
  - กลับกัน รูปในระบบครอบ TH1404 ได้ 97.80% และ TH1413 ได้ 87.56% · รูป BangSai ในระบบ (405.5 ตร.กม.) จึงเป็นรูปที่รวมสองอำเภอไว้ด้วยกัน
  - ตอนนี้ name_th = บางซ้าย (มาจากแถว kongvut 1413 ที่ทับแถว 1404 ในชั้น strict) แต่พื้นที่ส่วนใหญ่เป็นบางไทร

## 2. หาสาเหตุ (`c18_kongvut_check.py` · `c18-kongvut-check*.json` · `c18-run.log`)
- ดาวน์โหลด 25 พ.ย. 2569 15:07:56 UTC (HTTP 200) จาก URL ตาม `KONGVUT_PROVINCE` / `KONGVUT_DISTRICT` ในสคริปต์ ไว้ใน `<gis-w4-kongvut>` (ไม่คัดลอกเข้า repo)
  - `province.json` 21,205 ไบต์ SHA256 `8696f01825cde1443f4dacb5efd4d16bd460cbc910870434a524496ef71065b0` · 77 จังหวัด
  - `district.json` 310,074 ไบต์ SHA256 `0682df1dd2d462f98526fde22343902eeeed7fbaff01cdd608090087412a3200` · 930 อำเภอ · ไม่มีแถวที่มี `deleted_at`
- import เฉพาะ `strict()` `loose()` `MANUAL_OVERRIDES` `PROVINCE_EN_OVERRIDES` จากสคริปต์ (ไม่เรียก `main()`) แล้วสร้าง lookup เองตามลำดับของสคริปต์: แถวหลังทับแถวหน้า · ชั้น manual → strict → loose → global · อ่าน `name.th` / `name.en` ของรูปแบบใหม่
- **ได้ชื่อไทยตรงกับไฟล์ปัจจุบันครบ 928 อำเภอ** ต่างกันแค่คำว่า "เขต" ของกรุงเทพฯ 45 เขต (kongvut ใหม่แยก "เขต" ไปไว้ใน `prefix`) · อีก 5 เขตมาจากชั้น manual ที่มี "เขต" อยู่แล้ว
  - ชั้นที่ใช้: manual 83 · strict 765 · loose 80 · global 0 · ไม่ตรง 0
- **ชื่ออังกฤษซ้ำกันในจังหวัดเดียวกันใน kongvut (3 คู่):**

| จังหวัด | แถวแรก | แถวหลัง (ชนะใน lookup) |
|---|---|---|
| นครสวรรค์ | 6007 "Takhli" = ตาคลี | **6008 "Takhli" = ท่าตะโก** (ชื่ออังกฤษผิด ควรเป็น Tha Tako) |
| นครสวรรค์ | 6010 "Phayuha Khiri" = พยุหะคีรี | **6011 "Phayuha Khiri" = ลาดยาว** (ชื่ออังกฤษผิด ควรเป็น Lat Yao) |
| พระนครศรีอยุธยา | 1404 "Bang Sai" = บางไทร | 1413 "Bang Sai" = บางซ้าย (สองอำเภอสะกดอังกฤษเหมือนกันจริง) |

  - ทั้ง 3 คู่ชนกันทั้งในคีย์ `strict()` และ `loose()` ด้วย
- **ตาคลีและพยุหะคีรีได้ชื่อมาจากชั้น strict:** คีย์ `("Nakhon Sawan","takhli")` ได้แถว 6008 (ท่าตะโก) และ `("Nakhon Sawan","phayuhakhiri")` ได้แถว 6011 (ลาดยาว) เพราะแถวหลังทับแถวหน้า
  - ท่าตะโกกับลาดยาวเองมี override ในชั้น manual อยู่แล้ว (`thatako`, `latyao`) จึงไม่ผิด · ผลคือไฟล์มีชื่อไทยซ้ำในนครสวรรค์ 2 คู่ (ท่าตะโก ×2 · ลาดยาว ×2)
- ลองเพิ่ม override 2 ตัว (`--extra-manual`): ต่างจากไฟล์เดิมแค่ 2 อำเภอนี้ (manual 85 · strict 763) และหลังแก้ สคริปต์ที่ commit แล้วกับไฟล์ที่แก้แล้วตรงกันครบ (ต่างแค่ "เขต" 45 เขตเหมือนเดิม)
- **`add_district_th_names.py` รันกับข้อมูล kongvut ปัจจุบันไม่ได้แล้ว:** kongvut เปลี่ยนรูปแบบเป็น `name: {th, en}` ไม่มี `name_en` / `name_th` สคริปต์จะหยุดด้วย `KeyError: 'name_en'` ที่บรรทัด `en = p["name_en"].strip()` (บรรทัด 224 ของ c944540) ก่อนเขียนไฟล์ใด ๆ · ถ้าแก้ให้อ่านรูปแบบใหม่ เขตของกรุงเทพฯ 45 เขตจะเสียคำว่า "เขต" · C18 ไม่ได้แก้ส่วนนี้

## 3. แก้
- เพิ่ม `("Nakhon Sawan", "takhli"): "ตาคลี"` และ `("Nakhon Sawan", "phayuhakhiri"): "พยุหะคีรี"` ใน `MANUAL_OVERRIDES` (ต่อจาก `latyao` / `thatako`) พร้อมคอมเมนต์ 2 บรรทัด · ไม่ได้รันสคริปต์ทั้งตัว
- แก้ json ด้วย `c18_fix_names.py`: ตรวจว่า `json.dumps(ensure_ascii=False, separators=(",", ":"))` ของไฟล์เดิมได้ไบต์เดิมทุกไบต์ ตรวจค่าเดิมทั้ง 2 ค่า แล้วแก้ 2 ค่าและเขียนกลับแบบเดียวกัน ไม่มีตัวขึ้นบรรทัดท้ายไฟล์

## 4. ตรวจผล (`c18_verify_fix.py` · `c18-verify-fix.log` · `c18-backend.log` `.xml`)
- สองสำเนาเหมือนกันทุกไบต์ · เทียบกับ c944540 ต่างกันแค่ 2 จุด: `"name_th":"ลาดยาว"` → `"พยุหะคีรี"` (PhayuhaKhiri) และ `"name_th":"ท่าตะโก"` → `"ตาคลี"` (Takhli) · ไม่มี CR ไม่มีตัวขึ้นบรรทัดท้ายไฟล์ · blob ที่ commit มี SHA256 เท่ากับไฟล์
- 928 อำเภอ · **ไม่มีชื่อไทยซ้ำกันภายในจังหวัดเดียวกันทั้งไฟล์** (ก่อนแก้ซ้ำ 2 คู่ในนครสวรรค์)
- **ชุด backend ทั้งหมดใน worktree: 666 passed / 0 failed / 0 skipped** (7.0 วินาที) · ใช้ venv ของ C6 เพราะ `requirements.txt` และ `requirements.in` ของ main ตรงกับ C6 ทุกไบต์ (main ไม่มี `requirements-native.txt`)
  - รวม `tests/test_geodata_assets.py` ที่ตรวจว่าสองสำเนาตรงกันและทุกอำเภอมี name_th

## 5. จุดที่อ่านหรือเก็บ name_th ของอำเภอ
**โค้ด (worktree):**
- frontend อ่านจาก `/thailand_districts.json` (`src/hooks/useDistrictData.js:30`) แล้วใช้ name_th เป็นชื่อที่แสดง:
  - `src/utils/mapLayers/districtLayers.js:75` ป้ายบนแผนที่ (`labelFor`)
  - `src/utils/mapLayers/districtLayers.js:210` ชื่อใน sidebar ตอนคลิก (`setSelectedDistrict`)
  - `src/utils/mapLayers/districtLayers.js:220` tooltip ตอนชี้
  - `src/Dashboard.js:178` ชื่อตอนเปิดจาก URL (`setSelectedDistrict`)
  - ค่า `selectedDistrict` ถูกส่งต่อไปแสดงใน Sidebar แท็บต่าง ๆ CSV และรายงาน PDF
- การเรียก API และแคชใช้ชื่ออังกฤษทั้งหมด (`selectedDistrictEN`, คีย์ `province::name`, endpoint `/ndvi|/lst/{province}/districts/{district}`) · backend ไม่มีโค้ดใดอ่าน name_th ของอำเภอ (name_th ใน backend เป็นของ landuse และพันธุ์ไม้)
- ฐาน: `public.districts.name_th` จาก migration 007 (คอมเมนต์บอกว่า "เว้นไว้ backfill" แต่ไม่มี migration หรือโค้ดใดเขียนค่านี้)

**T0 (SELECT แบบ READ ONLY ทั้งสองฐาน · `c18_t0_readonly.sql` · `c18-t0-readonly.log`):**
- `public.districts` 928 แถว · **name_th ไม่เป็น NULL 0 แถว** · Takhli / ThaTako / LatYao / PhayuhaKhiri ทุกแถว name_th ว่าง
- คอลัมน์ `district` ใน 7 ตาราง (access_300m, district_lst_annual, district_lst_monthly, district_ndvi_annual, district_ndvi_monthly, planting_recommendations, urban_ndvi_annual): ทุกตาราง 0 แถว · ไม่มีค่าที่เป็นอักษรไทย

**สรุป:** ไม่ต้องแก้ข้อมูลในฐาน และไม่ต้องเพิ่ม cache_version เพราะไม่มีคำตอบ API ใดเก็บชื่อไทยของอำเภอ · ชื่อใหม่จะขึ้นเมื่อ deploy frontend ที่มีไฟล์ใหม่ (เบราว์เซอร์หรือ CDN อาจถือไฟล์เดิมไว้จนหมดอายุแคช HTTP · ยังไม่ได้ตรวจ)

SQL สำรอง เผื่อฐานจริงมีคน backfill name_th ไว้เอง (ยังไม่ได้ตรวจฐานจริง · **ห้ามรันโดยไม่ได้รับอนุมัติ**):
```sql
-- ตรวจก่อน (READ ONLY)
BEGIN READ ONLY;
SELECT province, name_en, name_th FROM public.districts
 WHERE province = 'Nakhon Sawan' AND name_en IN ('Takhli', 'PhayuhaKhiri');
ROLLBACK;
-- แก้เฉพาะเมื่อผลข้างบนเป็นค่าผิด (แก้ได้แค่แถวที่ยังเป็นค่าผิดเท่านั้น)
UPDATE public.districts SET name_th = 'ตาคลี'
 WHERE province = 'Nakhon Sawan' AND name_en = 'Takhli' AND name_th = 'ท่าตะโก';
UPDATE public.districts SET name_th = 'พยุหะคีรี'
 WHERE province = 'Nakhon Sawan' AND name_en = 'PhayuhaKhiri' AND name_th = 'ลาดยาว';
```

## 6. ภาพ (`c18_draw.py`)
- `c18-nakhon-sawan-before.png` (ไฟล์ของ c944540) และ `c18-nakhon-sawan-after.png` (หลังแก้): 15 อำเภอจาก `green-area-frontend/public/thailand_districts.json` ป้าย name_th และชื่ออังกฤษ · สีส้ม = Takhli และ PhayuhaKhiri
- ฟอนต์ Leelawadee UI · เปิดดูแล้วป้ายไทยอ่านได้ ไม่เป็น ??? หรือกล่องสี่เหลี่ยม
- ก่อนแก้: Takhli ขึ้น "ท่าตะโก" และ PhayuhaKhiri ขึ้น "ลาดยาว" (ซ้ำกับอำเภอจริง) · หลังแก้: "ตาคลี" และ "พยุหะคีรี"
- หมายเหตุ: matplotlib ไม่จัดรูปอักษรไทยเหมือนเบราว์เซอร์ สระบนล่างอาจเยื้องเล็กน้อย แต่อ่านได้

## ยังไม่ได้ตรวจ
- ยังไม่ได้เปิดหน้าเว็บจริงหรือ build frontend ดูป้ายบนแผนที่ (ดูแค่ภาพจาก matplotlib) และยังไม่ได้รันเทสต์ frontend
- ยังไม่ได้ตรวจ `public.districts.name_th` และแคชในฐานจริง (Supabase) · ตรวจแค่ T0
- ไม่ได้แก้ BangSai และไม่ได้แก้สคริปต์ให้อ่าน kongvut รูปแบบใหม่
- ยังไม่มีคนอื่นตรวจโค้ด · ยังไม่ push และยังไม่เปิด PR เข้า main

## ไฟล์ใน `docs/gis/evidence/23_27-chayakorn/c18/`
`c18-summary.md` · `c18_shape_check.py` · `c18_kongvut_check.py` · `c18_fix_names.py` · `c18_verify_fix.py` · `c18_draw.py` · `c18_t0_readonly.sql` ·
`c18-shape-check.csv` · `c18-shape-check.json` · `c18-kongvut-check.json` · `c18-kongvut-check-with-c18-overrides.json` · `c18-kongvut-check-after.json` ·
`c18-run.log` · `c18-verify-fix.log` · `c18-backend.log` · `c18-backend.xml` · `c18-t0-readonly.log` · `c18-nakhon-sawan-before.png` · `c18-nakhon-sawan-after.png`
