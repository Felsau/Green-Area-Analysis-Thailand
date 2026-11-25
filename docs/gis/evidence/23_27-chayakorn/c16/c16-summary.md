# C16 · รายการเสนอแก้ชื่อไทยในไฟล์ของระบบ (สัปดาห์ที่ 4, 23–27 พ.ย. 2569)

จัดทำ 24/11/2569 โดยชยากร · **ข้อมูลจริง (ไฟล์ของระบบที่ 7501cc8 + OCHA cod-ab-tha) · อ่านอย่างเดียว · ไม่ได้แก้ไฟล์ของระบบ**

## วิธี
- เทียบ `NL_NAME_1` 77 แถวใน `green-area-backend/data/thailand.json` กับ `adm1_name1` ของ OCHA
- เทียบ `name_th` 928 แถวใน `data/thailand_districts.json` กับ `adm2_name1`
- จับคู่ด้วยกฎของ C5 (`make_norms(False)` และ `match`) จาก `git show C5:…/c5_name_map.py` (blob `bffbed4e9298` ตัวเดียวกับที่ C9 ใช้) ผลตรงกับ C9:
  - จังหวัด: ไทย 70 · อังกฤษ 6
  - อำเภอ: ไทย 871 · อังกฤษ 5 · มีแถวในระบบที่ถูกจับคู่ซ้ำ 1 แถว
- **กรุงเทพฯ:** กฎจับไม่ได้เพราะ NL_NAME_1 ในระบบเป็น "จังหวัดเชียงใหม่" จึงจับคู่จังหวัดด้วย PCODE TH10 (หมายเหตุอยู่ในแถว) จากนั้นจับคู่ 50 เขตด้วยกฎ C5 ได้ด้วยชื่อไทยครบ 50
- **แถวของระบบหนึ่งแถวจับคู่กับแถวของ OCHA ได้แค่แถวเดียว:**
  - มีการชนกัน 1 จุด: ระบบ BangSai (บางซ้าย) ถูก TH1413 บางซ้าย จับด้วยชื่อไทย และถูก TH1404 บางไทร จับด้วยชื่ออังกฤษ
  - จึงเก็บคู่ที่ชื่อไทยตรงกัน (TH1413) ส่วน TH1404 บางไทรถือเป็นแถวฝั่งเดียว (`missing_in_system`) ไม่ได้เสนอแก้บางซ้าย
- **ชนิดของแถว:**
  - prefix: ต่างแค่คำนำหน้า จังหวัด/อำเภอ/เขต
  - spelling: เท่ากันหลัง normalise ของ C5 หรือต่างกันไม่เกิน 2 ตัวอักษร
  - wrong: อื่น ๆ
  - missing_in_system และ not_in_ocha

## ผล (c16-name-fixes.csv · 131 แถว)
| ไฟล์ | wrong | prefix | spelling | missing_in_system | not_in_ocha |
|---|---|---|---|---|---|
| thailand.json (NL_NAME_1) | **5** | 68 | 0 | 0 | 0 |
| thailand_districts.json (name_th) | **2** | 50 | 0 | **3** | **3** |

- **wrong 7 แถว:**
  - NL_NAME_1: กรุงเทพฯ "จังหวัดเชียงใหม่" → กรุงเทพมหานคร (TH10 จับคู่ด้วย PCODE) · ชัยภูมิ "จังหวัดชัยนาท" → ชัยภูมิ (TH36) · เพชรบูรณ์ "อำเภอเมืองเพชรบูรณ์" → เพชรบูรณ์ (TH67) · กาญจนบุรี "อำเภอเมืองกาญจนบุรี" → กาญจนบุรี (TH71) · นครปฐม "อำเภอเมืองนครปฐม" → นครปฐม (TH73)
  - name_th: Takhli "ท่าตะโก" → ตาคลี (TH6007) · PhayuhaKhiri "ลาดยาว" → พยุหะคีรี (TH6010)
  - ทั้ง 6 แถวที่ไม่ใช่กรุงเทพฯ จับคู่ด้วยชื่ออังกฤษ และไม่มีคู่ที่ชื่อไทยตรงสำหรับแถวของระบบนั้น
    - "ท่าตะโก" กับ "ลาดยาว" มีคู่ไทยกับอีกแถวของระบบ (ThaTako, LatYao) ซึ่งจับคู่ทั้งไทยและอังกฤษอยู่แล้ว
- **prefix 118 แถว:** NL_NAME_1 มี "จังหวัด" นำหน้า 68 จังหวัด และ name_th ของกรุงเทพฯ มี "เขต" นำหน้าครบ 50 เขต
  - OCHA ไม่มีคำนำหน้า · เป็นรูปแบบการเขียน ไม่ใช่ชื่อผิด (จะปรับหรือไม่ให้หัวหน้าตัดสิน)
  - อีก 4 จังหวัด (70 + 6 + 1 − 73) ชื่อตรงกับ OCHA อยู่แล้ว
- **missing_in_system 3 แถว (ไม่เพิ่มรูปเส้นเขต):**
  - บางไทร TH1404 (พระนครศรีอยุธยา)
  - กัลยาณิวัฒนา TH5025 (เชียงใหม่)
  - นครศรีธรรมราช TH8001 (Mueang Nakhon Si Thammarat)
- **not_in_ocha 3 แถว:**
  - ทะเลสาบสงขลา 2 แถว (SongkhlaLake ในพัทลุงและสงขลา)
  - เมืองนครศรีธรรมราช (MuangNakhonSiThammarat)
- **นครศรีธรรมราช:** แถวฝั่งเดียวสองแถวต่างกันแค่คำว่า "เมือง" น่าจะเป็นอำเภอเดียวกัน แต่กฎ C5 ไม่จับคู่ จึงไม่ได้เสนอแก้ (จดหมายเหตุไว้ทั้งสองแถว)
- spelling 0 แถว: ไม่มีคู่ที่ต่างกันเล็กน้อย

## สำเนาของไฟล์ (SHA256 ที่ 7501cc8)
| ไฟล์ | ไบต์ | SHA256 |
|---|---|---|
| `green-area-backend/data/thailand.json` | 1,017,305 | `ac2b28255f22861ab644bf083fa40f28dd9da1294648d4b01cfc6f9cdc156a21` |
| `green-area-frontend/public/thailand.json` | 1,017,305 | `ac2b28255f22861ab644bf083fa40f28dd9da1294648d4b01cfc6f9cdc156a21` |
| `green-area-backend/gis_worker/province_boundaries.json` | 1,017,305 | `ac2b28255f22861ab644bf083fa40f28dd9da1294648d4b01cfc6f9cdc156a21` |
| `green-area-backend/data/thailand_districts.json` | 2,631,549 | `f4231a763fd925d76a9dc20d6515177c5c7d9629b80e82a8d89d525782f8768d` |
| `green-area-frontend/public/thailand_districts.json` | 2,631,549 | `f4231a763fd925d76a9dc20d6515177c5c7d9629b80e82a8d89d525782f8768d` |

- **ไฟล์จังหวัดทั้ง 3 ไฟล์เหมือนกันทุกไบต์** และไฟล์อำเภอทั้ง 2 ไฟล์ก็เหมือนกันทุกไบต์
- **`province_boundaries.json` ถูกล็อก hash ไว้ใน migration 034** (`034_ldd_upload.sql` บรรทัด 106) และใน `BOUNDARY_SHA256` (`ldd_provider.py` บรรทัด 29)
  - **ห้ามแก้ไฟล์นี้ตอนแก้ชื่อ** ถ้าแก้ ตัวตรวจจะหยุดด้วย VALIDATION_ASSET_INVALID และรายงานเดิมจะไม่ตรงกับฐานข้อมูล
  - ไฟล์ใน `data/` เป็นคนละไฟล์ แก้ได้โดยไม่กระทบ แต่ hash จะไม่เท่ากับ `province_boundaries.json` อีกต่อไป
- **ถ้าแก้ไฟล์ใน `data/` ต้องแก้ไฟล์ใน `public/` ด้วย:** `tests/test_geodata_assets.py` บรรทัด 81–87 บังคับให้ sha ของสองสำเนาเท่ากัน
- ถ้าเพิ่มอำเภอที่ขาด เทสต์จะล้มที่ `test_district_count` (928) และ `test_districts_grouped_under_their_province` (เชียงใหม่ 24 อำเภอ บรรทัด 107) และตาราง `public.districts` ที่ migration 007 seed ไว้ 928 แถวก็ต้องตามไปด้วย

## จุดในโค้ดที่อ่านช่องชื่อ (backend, frontend, dev · ไม่รวม .json)
**ช่อง `NL_NAME_1`: ไม่มีโค้ดที่อ่านเลย** (`git grep -i NL_NAME` เจอแค่หลักฐาน C9)
- ชื่อจังหวัดภาษาไทยบนหน้าจอมาจากตาราง `public.provinces.name_th` (seed ใน `migrations/006_create_provinces.sql`) ซึ่งถูกแล้วทั้ง 5 จังหวัด

**อ่าน `name_th` จาก `thailand_districts.json`:**
| ไฟล์:บรรทัด | ใช้ทำอะไร |
|---|---|
| `green-area-frontend/src/Dashboard.js:204` | ตั้งชื่ออำเภอที่เลือกบนแผนที่ (`name_th || name`) |
| `green-area-frontend/src/utils/mapLayers/districtLayers.js:55` และ `:65` | ชื่ออำเภอใน tooltip และข้อมูลที่ส่งเมื่อคลิกชั้นอำเภอ |
| `dev/gis_ui/phase5_ui_checks.cjs:46` | ตัวตรวจ UI อ่านชื่ออำเภอจาก `/thailand_districts.json` |
| `green-area-backend/add_district_th_names.py:234–278` | สคริปต์ที่เขียน `name_th` ลงไฟล์ (ต้นทางของชื่อที่ผิด) |
| `green-area-backend/generate_districts.py:217–218` | สร้างไฟล์ใหม่แล้วเรียก `add_district_th_names` ต่อ |
| `green-area-backend/tests/test_geodata_assets.py:116–122` | ตรวจว่าทุกอำเภอมี `name_th` |

**`name_th` ของข้อมูลอื่น (ไม่เกี่ยวกับสองไฟล์นี้):**
- ตาราง `public.provinces` และ `public.districts`: `migrations/006`, `007` (เว้น name_th ไว้ backfill), `027:70`, `030:99`, `035:4` `:671–672`
  - หน้าจัดการ GIS อ่านจาก API นี้: `GisManagement.js:125` `:127` `:180` `:653`
- ชื่อชั้นการใช้ที่ดินและ legend: `landuse.py:22–30` `:129`, `ldd.py:143–146`, `ldd_codes.py:7`, `data/ldd/generate_ldd_codes.py`, `gis_ldd_publication.py:56` `:94`, `routers/maps/tiles.py:173`, `routers/recommend/scoring.py:480`, `routers/recommend/species.py:226`
  - frontend: `MapLegend.js`, `LandusePanel.js`, `ImpactSection.js`, `RecommendTab.js:159`, `publishedAnalysis.js:25`, `reportPdf/recommend.js`
- ชื่อพันธุ์ไม้: `impact.py`, `validate_species.py`, `validate_recommend.py`, `prototype_species_envelope.py`, `make_species_evidence_doc.py`, `refresh_species_verification.py`, `SpeciesSection.js`, `utils/export/csv.js:242` และเทสต์ที่เกี่ยวข้อง

## หน้าจอที่กระทบถ้าแก้
- **แก้ name_th 2 อำเภอ (ตาคลี พยุหะคีรี):** ชื่ออำเภอที่เลือกบน Dashboard และ tooltip ของชั้นอำเภอบนแผนที่
  - ตอนนี้คลิกอำเภอตาคลีจะแสดง "ท่าตะโก" และพยุหะคีรีจะแสดง "ลาดยาว"
- **แก้ NL_NAME_1:** ไม่พบหน้าจอที่แสดงช่องนี้ ต่างกันแค่ในไฟล์ข้อมูล
- **แก้ prefix:** name_th ของกรุงเทพฯ ที่มี "เขต" แสดงอยู่บน Dashboard และ tooltip ถ้าตัดออก หน้าจอจะแสดงต่างจากเดิม

## ยังไม่ได้ตรวจ
- ไม่ได้เปิดหน้าจอจริงเพื่อดูชื่อที่แสดง (ดูจากโค้ดอย่างเดียว)
- ไม่ได้ตรวจว่า `public.districts.name_th` ในฐานข้อมูลจริงมีค่าอะไร (007 เว้นไว้ให้ backfill)
- ไม่ได้ตรวจการเข้าถึง properties แบบไดนามิกที่ไม่ได้เขียนชื่อช่องตรง ๆ

## ไฟล์ใน `docs/gis/evidence/23_27-chayakorn/c16/`
`c16_name_fixes.py` · `c16-name-fixes.csv` (UTF-8 มี BOM เปิดใน Excel ได้) · `c16-stats.json` · `c16-summary.md`
