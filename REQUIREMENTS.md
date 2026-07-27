# Requirement Specification — Green Area Analysis Thailand

> เอกสารข้อกำหนดความต้องการของระบบ (Software Requirements) สำหรับวิทยานิพนธ์
> รวม **ความต้องการที่พัฒนาแล้ว** (FR-01…16, NFR-01…06) และ
> **ข้อเสนอเพิ่มเติมที่อ้างอิงงานวิจัย** (FR-17…26, NFR-07…08)
>
> แต่ละข้อกำกับแหล่งอ้างอิงด้วย `[R#]` → ดูรายการเต็มใน [§7 บรรณานุกรม](#7-บรรณานุกรม-references)
>
> _หมายเหตุด้านความถูกต้อง: บรรณานุกรมระบุชื่อเรื่อง/แหล่งตีพิมพ์/ปี/URL ที่ตรวจสอบแล้ว
> สำหรับบางรายการที่ยังไม่ทราบชื่อผู้แต่ง/เลขหน้าครบ ให้เปิดลิงก์ DOI ยืนยันก่อนนำลง
> บรรณานุกรมฉบับสมบูรณ์ของเล่มวิทยานิพนธ์_

---

## 1. ขอบเขตของเอกสาร

ระบบ **Green Area Analysis Thailand** เป็นเว็บแอปพลิเคชันวิเคราะห์พื้นที่สีเขียวและ
ปรากฏการณ์เกาะความร้อนเมือง (Urban Heat Island) จากภาพดาวเทียม ครอบคลุม 77 จังหวัด
928 อำเภอ ของประเทศไทย พร้อมอัลกอริทึมแนะนำพื้นที่ปลูกต้นไม้ (AI Priority) และ
รายงาน PDF

เอกสารนี้แบ่งความต้องการเป็น 2 กลุ่ม:
- **กลุ่ม A — พัฒนาแล้ว** (baseline ของวิทยานิพนธ์)
- **กลุ่ม B — ข้อเสนอตามงานวิจัย** (ต่อยอดเพื่อยกระดับงานให้ตรงกับ frontier ปัจจุบัน)

---

## 2. มาตรฐานและกรอบอ้างอิงหลัก

| มาตรฐาน/กรอบ | ใช้กับ | อ้างอิง |
|---|---|---|
| WHO — พื้นที่สีเขียวขั้นต่ำ ~9 ม²/คน | ranking, urban subset | `[R1]` |
| **3–30–300 rule** (ต้นไม้ในสายตา 3 ต้น · canopy 30% · สวนใน 300 ม.) | benchmark ระดับย่าน | `[R2]` |
| Multi-objective tree-planting prioritization | สูตร Priority Score | `[R3] [R4] [R5]` |
| Tree Equity Score (canopy + ความร้อน + ตัวชี้วัดสังคม) | ดัชนีความเป็นธรรม | `[R6]` |
| i-Tree Eco — การตีมูลค่าบริการนิเวศ | แบบจำลองผลกระทบ | `[R7]` |
| Network-based / 2SFCA accessibility | การเข้าถึงพื้นที่สีเขียว | `[R8] [R9]` |
| Bowler et al. 2010 — cooling effect ของพื้นที่สีเขียว | ΔLST estimation | `[R10]` |
| IPCC 2019 Guidelines — carbon sequestration | CO₂ estimation | `[R11]` |
| Chave et al. 2014 allometry + EPA 2023 vehicle baseline | kg CO₂/ต้น/ปี, equivalent cars | `[R25] [R26]` |
| NDVI formula (Rouse et al. — normalized difference NIR/Red) | สูตรคำนวณ NDVI | `[R23] [R24]` |
| Google Cloud Score+ — per-pixel cloud masking (Sentinel-2) | วิธีวิทยา cloud-free compositing | `[R12]` |
| GCOS-245 — required measurement uncertainty ของ ECV ด้านพืชพรรณ (FAPAR: Goal 5% · Threshold 10% ที่ 2σ) | เกณฑ์ตัดระดับคุณภาพ NDVI | `[R33]` |
| QA4EO (CEOS/GEO) — ผลิตภัณฑ์ EO ต้องแนบ Quality Indicator ที่สาวกลับหามาตรฐานได้ | หลักการของการรายงานคุณภาพข้อมูล | `[R34]` |
| กรมอุตุนิยมวิทยา — นิยาม 3 ฤดูของประเทศไทย | ตรวจความเป็นตัวแทนฤดูกาลของ composite | `[R35]` |
| ESA WorldCover v200 — built-up & validation | urban subset, accuracy | `[R13]` |
| Landsat Collection 2 Level-2 ST product (single-channel algorithm) | คำนวณ LST จาก `ST_B10` | `[R14] [R15]` |
| Mann-Kendall trend test | นัยสำคัญแนวโน้ม NDVI/LST รายปี | `[R16] [R17]` |
| Sentinel-2 (NDVI จาก B8/B4, 10 m) | แหล่งข้อมูล NDVI หลัก | `[R27]` |
| Google Earth Engine | compute backend ของทั้งระบบ | `[R28]` |
| WorldPop (ประชากร 100 m) | ปัจจัย `pop_need` ใน Priority Score | `[R29]` |
| GADM v4.1 (ขอบเขตการปกครอง) | clip จังหวัด/อำเภอ 77/928 | `[R30]` |
| Landsat C2 L2 Product Guide (`ST_B10`) | ระเบียบวิธีข้อมูล LST | `[R31]` |
| Dynamic World V1 (land cover 10 m รายวัน, deep learning) | ชั้นการใช้ที่ดิน provider แรก + `isa_frac` ของปัจจัย peri-urban | `[R36]` |
| SRTM 30 m (ความสูง/ความชัน) | ตัดพื้นที่ลาดชัน > 30° ออกจาก plantable mask | `[R37]` |
| LDD 1:25,000 — สภาพการใช้ที่ดินกรมพัฒนาที่ดิน | schema กลาง U/A/F/W/M + provider ที่สองของชั้นการใช้ที่ดิน | `[R38]` |
| FAO GAUL 2015 level-2 | แหล่งขอบเขตอำเภอสำรอง (`generate_districts.py`) | `[R39]` |

---

## 3. Functional Requirements

### 3.1 กลุ่ม A — พัฒนาแล้ว (Baseline)

| ID | Requirement | อ้างอิง |
|---|---|---|
| FR-01 | คำนวณค่า NDVI รายปีและรายเดือน ระดับจังหวัดและอำเภอ | `[R12] [R23] [R24]` |
| FR-02 | คำนวณค่า LST (Land Surface Temperature) รายปีและรายเดือน ระดับจังหวัดและอำเภอ | `[R14] [R15]` |
| FR-03 | แสดงแผนที่ NDVI/LST แบบ 3D extrusion ผ่าน deck.gl | — |
| FR-04 | เปรียบเทียบหลายจังหวัดพร้อมกัน | — |
| FR-05 | จัดอันดับจังหวัดตามค่าพื้นที่สีเขียวต่อคน เทียบมาตรฐาน WHO | `[R1]` |
| FR-06 | คำนวณ AI Priority Score และแสดงเป็น Heatmap layer | `[R3]` |
| FR-07 | แสดง 10 พิกัดที่ควรปลูกต้นไม้มากที่สุด พร้อม priority score | `[R3]` |
| FR-08 | แนะนำพันธุ์ไม้พื้นถิ่นตาม 6 ภูมิภาค พร้อมเหตุผลทางนิเวศ (22 ชนิด) | `[R5]` |
| FR-09 | ประมาณการ CO₂ sequestration และ cooling effect (ΔLST) | `[R10] [R11] [R19] [R22] [R25] [R26]` |
| FR-10 | Time-lapse animation แสดง NDVI ย้อนหลังหลายปี (ตั้งแต่ พ.ศ. 2558) | — |
| FR-11 | Time-series chart + แนวโน้ม (Mann-Kendall) + forecast | `[R16] [R17]` |
| FR-12 | Urban Subset — clip ค่าด้วย ESA WorldCover Built-up | `[R13]` |
| FR-13 | ส่งออก PDF Report คุณภาพระดับวิทยานิพนธ์ | — |
| FR-14 | ปรับ Weight ของปัจจัยใน Priority Score ผ่าน UI | `[R3]` |
| FR-15 | Cache invalidation (admin only) ด้วย ADMIN_TOKEN | — |
| FR-16 | Rate limiting 60 requests/IP/นาที | — |

### 3.2 กลุ่ม B — ข้อเสนอเพิ่มเติมตามงานวิจัย

> หลักการ: ปัจจัยที่เพิ่มเข้าสู่ Priority Score เป็นแบบ **additive** (เติมปัจจัยใหม่
> เข้ากับ NDVI deficit / LST / population เดิม) เพื่อให้โมเดลยิ่ง rich ขึ้น ไม่ใช่ลด

**ธีม 1 — มาตรฐาน 3-30-300 (เสริม WHO)**

| ID | Requirement | เหตุผล/อ้างอิง |
|---|---|---|
| FR-17 | แสดงตัวชี้วัด **30% tree canopy cover** ต่ออำเภอ คู่กับ WHO m²/คน **(มีแล้ว)** | 3-30-300 เป็น benchmark ใหม่ที่หลักฐานเชิงประจักษ์รองรับ `[R2]` |
| FR-18 | คำนวณ **% ประชากรที่อยู่ภายใน 300 ม.** จากพื้นที่สีเขียวสาธารณะ | เกณฑ์ "300" ของ 3-30-300 `[R2]` |

**ธีม 2 — มิติการเข้าถึง (Accessibility)**

| ID | Requirement | เหตุผล/อ้างอิง |
|---|---|---|
| FR-19 | Layer การเข้าถึง: % ประชากรที่เดินถึงสวนภายใน 300/500 ม. (network distance) | network analysis แม่นกว่า buffer/per-capita `[R8] [R9] [R18]` |
| FR-20 | (ขั้นสูง) ใช้ **2SFCA** ถ่วงทั้ง supply (ขนาดสวน) และ demand (ความหนาแน่นประชากร) | วิธีมาตรฐานในงานวิจัย accessibility `[R9] [R18]` |

**ธีม 3 — มิติความเป็นธรรม/เปราะบาง (Equity) — additive เข้า Priority**

| ID | Requirement | เหตุผล/อ้างอิง |
|---|---|---|
| FR-21 | **เพิ่ม** ปัจจัย equity/heat-vulnerability (สัดส่วนผู้สูงอายุ-เด็ก, heat exposure) เข้าสูตร Priority | prioritization ควรให้น้ำหนักชุมชนเปราะบาง `[R3] [R6] [R21]` |
| FR-22 | คำนวณ **Green/Tree Equity Score (0–100)** ต่ออำเภอ (canopy + LST + ตัวชี้วัดสังคม) | เทียบ benchmark สากลได้ `[R6] [R20] [R21]` |

**ธีม 4 — บริการนิเวศเต็มรูป (i-Tree)**

| ID | Requirement | เหตุผล/อ้างอิง |
|---|---|---|
| FR-23 | เพิ่มประมาณการ **ดูดซับมลพิษอากาศ** (PM2.5, O₃, NO₂) ต่อปี | i-Tree Eco ครอบคลุม air pollution removal `[R7]` |
| FR-24 | เพิ่มประมาณการ **ลด stormwater runoff** (การดักน้ำฝน) | บริการนิเวศหลักใน i-Tree `[R7]` |
| FR-25 | **ตีมูลค่าเป็นเงิน (บาท/ปี)** ของบริการนิเวศรวม | เสริมน้ำหนักเชิงนโยบาย/งบประมาณ `[R7]` |

**ธีม 5 — ความเป็นไปได้ในการปลูก (Feasibility)**

| ID | Requirement | เหตุผล/อ้างอิง |
|---|---|---|
| FR-26 | **เพิ่ม** ปัจจัย *ease of implementation* (พื้นที่ปลูกได้จริง/ข้อจำกัดการใช้ที่ดิน) เข้า priority | 1 ใน 4 องค์ประกอบหลักของ prioritization `[R3] [R4]` |

---

## 4. Non-Functional Requirements

### 4.1 กลุ่ม A — พัฒนาแล้ว

| ID | หมวด | Requirement |
|---|---|---|
| NFR-01 | Performance | API response < 2 วินาที (cache hit), ≤ 60 วินาที (cache miss + GEE compute) |
| NFR-02 | Scalability | รองรับ concurrent อย่างน้อย 100 sessions ผ่าน rate limit + cache |
| NFR-03 | Usability | ใช้งานได้โดยไม่มีพื้นฐาน GIS, รองรับไทย/อังกฤษ, มี tooltip อธิบายค่า |
| NFR-04 | Reliability | cache fallback เมื่อ GEE quota หมด, retry-on-disconnect, logging ทุก endpoint |
| NFR-05 | Security | CORS, admin token auth, service-role key อยู่ใน env ไม่อยู่ใน source |
| NFR-06 | Maintainability | แยก routers/helpers/business logic, type-hint + Pydantic, OpenAPI /docs |

### 4.2 กลุ่ม B — ข้อเสนอตามงานวิจัย

| ID | หมวด | Requirement | อ้างอิง |
|---|---|---|---|
| NFR-07 | Data Quality | รายงาน **ความไม่แน่นอน/คุณภาพ NDVI** ต่ออำเภอ (จำนวนภาพ cloud-free, ช่วงฤดูที่ใช้ composite) พร้อมค่าความไม่แน่นอนเชิงปริมาณเทียบเกณฑ์ GCOS **(มีแล้ว)** | `[R12] [R33] [R34] [R35]` |
| NFR-08 | Accuracy / Validation | **ตรวจสอบความถูกต้อง** ของ green area เทียบ ESA WorldCover และรายงานค่าความคลาดเคลื่อน (เป้า ±10%) | `[R13]` |

---

## 5. ข้อจำกัดและสมมติฐาน (Constraints & Assumptions)

- **Cloud cover** ภาคใต้/พื้นที่ฝนชุก ภาพ Sentinel-2 ที่ผ่าน filter น้อย ค่า NDVI บางเดือน
  ความไม่แน่นอนสูง — ระบบ fallback ใช้ภาพ cloud cover ≤ 80% `[R12]`
- **WorldPop** ข้อมูลประชากรถึงปี 2021 — เทียบ WHO ปีปัจจุบันอาจคลาดเคลื่อนจาก demographic change
- **Priority Score เป็น proxy** อิง remote sensing ไม่ใช่ ground truth — ไม่ครอบคลุมสิทธิ์ที่ดิน/
  วิศวกรรม การปลูกจริงต้องสำรวจหน้างาน (จึงเป็นที่มาของ FR-26) `[R4]`
- **Cooling effect** ค่า ΔLST ใช้ค่าเฉลี่ยจาก meta-analysis ของ Bowler et al. 2010 `[R10]`
- **ESA WorldCover** เป็น snapshot ปี 2021 ใช้เป็น proxy เขตเมืองทุกปีที่วิเคราะห์ `[R13]` —
  ตัวชี้วัดเรือนยอด 30% ของ FR-17 ก็อิงชุดนี้ ค่าจึงไม่เปลี่ยนตามปีที่ผู้ใช้เลือก (UI/รายงาน
  กำกับปีข้อมูลไว้ทุกที่ที่แสดงค่า)
- **สองชุดข้อมูล land cover ไม่ตรงกันในเขตเมือง** วัดเทียบเมื่อ 2026-07-27 (ปี 2024, scale
  100 ม.) พบว่า Dynamic World `[R36]` ให้ค่าเรือนยอดต่ำกว่า ESA WorldCover `[R13]` มากใน
  พื้นที่เมือง (ปทุมวัน 1.7% vs 14.6% · เมืองเชียงใหม่ 4.1% vs 29.1%) แต่ตรงกันในพื้นที่ป่า
  (เขาใหญ่ 98.3% vs 97.4%) เพราะ band `label` ของ DW เป็น argmax ต่อ pixel 10 ม. — pixel
  เมืองที่ปนต้นไม้กับอาคารถูกจำแนกเป็นสิ่งปลูกสร้าง ต้นไม้ริมถนน/สวนหย่อมจึงหายไป · FR-17
  จึงใช้ WorldCover เป็นค่าระดับ และใช้ DW เฉพาะบอก *ทิศทาง* การเปลี่ยนแปลงระหว่างปี
  (วิธีเดียวกันทั้งสองปี อคติหักลบกัน) — ความต่างนี้คือสิ่งที่ NFR-08 ต้องรายงานเชิงปริมาณ
- **การอ่านข้อมูล 10 ม. ที่ scale หยาบ** band แบบคลาสถูกย่อด้วย pyramid policy = MODE ทำให้
  เรือนยอดกระจัดกระจายหายไป · `canopy.py::_fractional_area` จึงรวมสัดส่วนที่ระดับ 10 ม.
  ด้วย `reduceResolution` ก่อนย่อ (ปทุมวัน: 14.6% แบบ fractional vs 12.6% ถ้าอ่านผ่าน pyramid)

---

## 6. การสืบสาวความต้องการ (Traceability — ย่อ)

| Requirement | งานวิจัย/มาตรฐาน | จุดในระบบ (ปัจจุบัน/เป้าหมาย) |
|---|---|---|
| FR-06, FR-07, FR-14 | `[R3]` multi-objective | `routers/recommend/scoring.py` |
| FR-06, FR-07 (peri-urban) | `[R32]` Moukomla 2026 — ISA→SUHI, ปลูกขอบเมืองคุ้มสุด | `scoring.py` `peri_urban_need_image` + `gee_utils.dynamic_world_built` (มีแล้ว) |
| FR-17 | `[R2]` 3-30-300 (เกณฑ์ 30%) · `[R13]` WorldCover · `[R36]` Dynamic World | `canopy.py` `build_canopy` + `canopy_area_bands` (เกาะ reduceRegion เดิมของ `routers/ndvi/compute.py` ไม่เพิ่ม round-trip) → เก็บใน `ndvi_annual.canopy` / `district_ndvi_annual.canopy` (migration 015) · แสดงบน StatsTab (`CanopyNote`) + คอลัมน์ Canopy % ในตารางรายอำเภอ + ตาราง "เรือนยอดไม้ (3-30-300)" ในรายงาน PDF/CSV **(มีแล้ว)** |
| FR-18 | `[R2]` 3-30-300 (เกณฑ์ 300 ม.) | (ใหม่) reuse `scoring.access_need_image` + WorldPop |
| FR-19, FR-20 | `[R8] [R9] [R18]` accessibility | (ใหม่) layer + GEE/network |
| FR-21, FR-22 | `[R6] [R20] [R21]` Tree Equity | (ใหม่) เพิ่ม factor ใน scoring |
| FR-23–25 | `[R7]` i-Tree | `impact.py` `estimate_impact` → `ecosystem_services` (air pollution PM2.5/O₃/NO₂ + stormwater + มูลค่าบาท/ปี) **(มีแล้ว)** |
| FR-01 | `[R12] [R23] [R24]` NDVI formula + cloud masking | `gee_utils.py` + `routers/ndvi/compute.py` (มีแล้ว) |
| FR-02 | `[R14] [R15]` LST algorithm | `gee_utils.py` (มีแล้ว) |
| FR-09 | `[R10] [R11] [R19] [R22] [R25] [R26]` | `impact.py` `estimate_impact` (มีแล้ว) |
| FR-11 | `[R16] [R17]` Mann-Kendall | `stats_utils.py` (มีแล้ว) |
| NFR-07 | `[R12] [R33] [R34] [R35]` | `routers/ndvi/compute.py` `build_data_quality` (+ `summarize_acquisitions`, `composite_uncertainty`, `grade_uncertainty`, `season_of`) → เก็บใน `ndvi_annual.data_quality` / `district_ndvi_annual.data_quality` (migration 014) แสดงบน StatsTab + ตาราง "คุณภาพข้อมูล NDVI" ในรายงาน PDF/CSV **(มีแล้ว)** |
| NFR-08 | `[R13]` | validation report เทียบ ESA WorldCover (ยังไม่ทำ) |
| FR-07 (พื้นที่ปลูกได้จริง) | `[R13] [R37]` WorldCover + ความชัน SRTM | `routers/recommend/scoring.py` `plantable_mask` (ตัดชัน > 30°) (มีแล้ว) |
| ชั้น "การใช้ที่ดิน" (ยังไม่มีรหัส FR) | `[R36] [R38]` Dynamic World + LDD 1:25,000 | `landuse.py` (provider DW) · `ldd.py` (provider LDD, เปิดด้วย env `LDD_LANDUSE_ASSET`) · `routers/maps/analysis/landuse.py`, `routers/maps/tiles.py` (มีแล้ว) |
| ข้อมูลขอบเขตอำเภอ | `[R30] [R39]` GADM v4.1 + FAO GAUL 2015 | `generate_districts.py` (มีแล้ว) |

---

## 7. บรรณานุกรม (References)

**[R1]** World Health Organization, Regional Office for Europe. *Urban green spaces and health — a review of evidence* (และ *Urban green spaces: a brief for action*). Copenhagen: WHO Europe, 2016–2017. — มาตรฐานที่อ้างถึงบ่อยว่าควรมีพื้นที่สีเขียวขั้นต่ำ ~9 ม²/คน.
https://www.who.int/europe/publications/i/item/9789289052498

**[R2]** Konijnendijk, C. C. (2023). *Evidence-based guidelines for greener, healthier, more resilient neighbourhoods: Introducing the 3–30–300 rule.* **Journal of Forestry Research**, 34, 821–830. https://doi.org/10.1007/s11676-022-01523-z · PubMed: 36042873 · **ลงบรรณานุกรมบทที่ 1 แล้ว** (ขอบเขตข้อ 3.1)

**[R3]** *A multi-objective decision support framework to prioritize tree planting locations in urban areas.* **Landscape and Urban Planning** (2021). https://www.sciencedirect.com/science/article/abs/pii/S0169204621001353

**[R4]** Nyelele, C., et al. *A comparison of tree planting prioritization frameworks (i-Tree Landscape vs. spatial decision support tool).* USDA Forest Service / **Urban Forestry & Urban Greening** (2022). https://www.fs.usda.gov/nrs/pubs/jrnl/2022/nrs_2022_nyelele_001.pdf

**[R5]** *Towards "Right Tree, Right Place" in urban environments: A systematic review of decision-support methods and tools for urban tree planting.* **Urban Forestry & Urban Greening** (2026). https://www.sciencedirect.com/science/article/pii/S1618866726000750

**[R6]** American Forests. *Tree Equity Score — methodology & nationwide scores* (ผสาน tree canopy, surface temperature, income, employment, race, age, health). https://www.americanforests.org/tools-research-reports-and-guides/tree-equity-score/ · https://www.treeequityscore.org/

**[R7]** US Forest Service. *i-Tree Eco* — quantifying air-pollution removal, carbon storage/sequestration, stormwater runoff reduction และการตีมูลค่า. https://www.itreetools.org/ · กรณีศึกษา: *Quantifying Regulating Ecosystem Services of Urban Trees using i-Tree Eco.* **Forests** 15(8):1446 (2024). https://www.mdpi.com/1999-4907/15/8/1446

**[R8]** *Network-based assessment of urban forest and green space accessibility in six major cities (London, New York, Paris, Tokyo, Seoul, Beijing).* **Urban Forestry & Urban Greening** (2025). https://www.sciencedirect.com/science/article/abs/pii/S1618866725001153

**[R9]** *GIS-based analysis for assessing the accessibility at hierarchical levels of urban green spaces* (รวมแนวทาง network analysis และ 2SFCA). **Urban Forestry & Urban Greening** (2016). https://www.sciencedirect.com/science/article/abs/pii/S161886671630019X

**[R10]** Bowler, D. E., Buyung-Ali, L., Knight, T. M., & Pullin, A. S. (2010). *Urban greening to cool towns and cities: A systematic review of the empirical evidence.* **Landscape and Urban Planning**, 97(3), 147–155. https://doi.org/10.1016/j.landurbplan.2010.05.006

**[R11]** IPCC (2019). *2019 Refinement to the 2006 IPCC Guidelines for National Greenhouse Gas Inventories* — Vol. 4 (AFOLU). https://www.ipcc-nggip.iges.or.jp/public/2019rf/

**[R12]** Pasquarella, V. J., Brown, C. F., Czerwinski, W., & Rucklidge, W. J. (2023). *Comprehensive Quality Assessment of Optical Satellite Imagery Using Weakly Supervised Video Learning.* **IEEE/CVF CVPR Workshops (EarthVision)**, 2125–2135. https://doi.org/10.1109/CVPRW59228.2023.00206 — เปเปอร์ต้นตำรับของ **Cloud Score+** (`GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED`, band `cs`) ที่ระบบใช้ mask เมฆ Sentinel-2 จริงใน `gee_utils.py` (แทน QA60 ที่ ESA เลิกเติมข้อมูลช่วง ม.ค.2022–ก.พ.2024) · เอกสารประกอบ: Pasquarella, V. (2023). *All Clear with Cloud Score+.* Google Earth Medium. https://medium.com/google-earth/all-clear-with-cloud-score-bd6ee2e2235e · Dataset catalog: https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_CLOUD_SCORE_PLUS_V1_S2_HARMONIZED
> _แก้ไข 2026-07-02: อ้างอิงเดิม ("SCL + s2cloudless") ไม่ตรงกับ implementation จริง (Cloud Score+) — แทนที่ด้วยเปเปอร์ที่ถูกต้อง_

**[R13]** Zanaga, D., et al. *ESA WorldCover 10 m v200* (2021). European Space Agency. https://esa-worldcover.org/ · https://doi.org/10.5281/zenodo.7254221

**[R14]** Malakar, N. K., Hulley, G. C., Hook, S. J., Laraby, K., Cook, M., & Schott, J. R. (2018). *An Operational Land Surface Temperature Product for Landsat Thermal Data: Methodology and Validation.* **IEEE Transactions on Geoscience and Remote Sensing**, 56(10), 5717–5735. https://doi.org/10.1109/TGRS.2018.2824828 — อัลกอริทึม single-channel ที่ USGS ใช้ผลิต band `ST_B10` (Landsat Collection 2 Level-2) ซึ่งระบบดึงมาใช้ตรงในการคำนวณ LST (`gee_utils.py`).

**[R15]** *On the Suitability of Different Satellite Land Surface Temperature Products to Study Surface Urban Heat Islands.* **Remote Sensing**, 16(20), 3765 (2024). https://doi.org/10.3390/rs16203765 — เปรียบเทียบผลิตภัณฑ์ LST 5 แบบ รวม Landsat 8/9 Collection 2 ST สำหรับวิเคราะห์ urban heat island (กรณีศึกษา Madrid/Paris) ยืนยันความเหมาะสมของ ST_B10 กับงานลักษณะนี้.

**[R16]** Mehmood, K., Anees, S. A., Muhammad, S., Hussain, K., Shahzad, F., Liu, Q., Ansari, M. J., Alharbi, S. A., & Khan, W. R. (2024). *Analyzing vegetation health dynamics across seasons and regions through NDVI and climatic variables.* **Scientific Reports**, 14, 11775. https://doi.org/10.1038/s41598-024-62464-7 — ใช้ Mann-Kendall trend test วิเคราะห์แนวโน้ม NDVI ระดับจังหวัด รูปแบบใกล้เคียงกับการใช้งานใน `stats_utils.py`.

**[R17]** Mann, H. B. (1945). *Nonparametric Tests Against Trend.* **Econometrica**, 13(3), 245–259. https://www.jstor.org/stable/1907187 · Kendall, M. G. (1975). *Rank Correlation Methods* (4th ed.). London: Griffin. — ที่มาทางสถิติดั้งเดิมของ Mann-Kendall trend test.

**[R18]** Shin, J., & Park, J. (2026). *An Application of the Grid-Based Two-Step Floating Catchment Area Method to Assess the Spatial Accessibility of Green Spaces in Seoul, South Korea.* **ISPRS International Journal of Geo-Information**, 15(2), 71. https://doi.org/10.3390/ijgi15020071 — เสนอ grid-based G2SFCA ปรับปรุงจาก 2SFCA มาตรฐาน สำหรับวัด accessibility ของพื้นที่สีเขียว อัปเดตต่อจาก `[R9]` · **ลงบรรณานุกรมบทที่ 1 แล้ว** (ขอบเขตข้อ 3.2). _(ชื่อผู้แต่งยืนยันจากหน้า DOI ของ MDPI เมื่อ 2026-07-27)_

**[R19]** *The cooling effect of urban green spaces as nature-based solutions for mitigating urban heat: insights from a decade-long systematic review.* **Climate Risk Management** (2025), e00731 (เปิดอ่านผ่าน DOAJ/ScienceDirect pii S2212096325000452). — สังเคราะห์งานวิจัย 84 ฉบับ (2014–2024) รายงานช่วง cooling effect 1–7°C อัปเดตหลักฐานเชิงปริมาณต่อจาก Bowler et al. 2010 `[R10]`. _(รายชื่อผู้แต่งเต็มยังไม่ยืนยันอัตโนมัติ — ตรวจสอบก่อนลงบรรณานุกรมฉบับสมบูรณ์)_

**[R20]** American Forests (2024). *Tree Equity Score Methodology.* https://www.treeequityscore.org/methodology — เอกสารระเบียบวิธีฉบับล่าสุด คำนวณ TES = 100(1 − GapScore × E) จาก 7 ตัวแปร (อายุ, การจ้างงาน, สุขภาพ, ความร้อน/สภาพภูมิอากาศ, รายได้, ภาษา, เชื้อชาติ) แทนที่เวอร์ชันเดิมใน `[R6]` · **ลงบรรณานุกรมบทที่ 1 แล้ว** (ขอบเขตข้อ 3.3).

**[R21]** Fulton, A. J., Ries, P. D., & Riley, G. E. (2025). *Where Are the Benefits of Trees Needed Most? A Comparison of Equity-Based Mapping Tools in Austin, Texas.* **Arboriculture & Urban Forestry**, 52(4). https://doi.org/10.48044/jauf.2025.020 — เปรียบเทียบ Tree Equity Score กับเครื่องมือ equity-mapping อื่น กรณีศึกษาจริง.

**[R22]** Dong, H., Tang, L., Liu, J., Hu, X., & Shao, G. (2025). *Remote sensing of urban tree carbon stocks: A methodological review.* **ISPRS Journal of Photogrammetry and Remote Sensing**, 227. — ทบทวนวิธี remote-sensing สำหรับประเมิน carbon stock ของต้นไม้ในเมือง เสริม IPCC 2019 `[R11]` ด้วยมุมมองเฉพาะ remote sensing. _(เลขหน้ายังไม่ยืนยันอัตโนมัติ — ตรวจสอบก่อนลงบรรณานุกรมฉบับสมบูรณ์)_

**[R23]** Rouse, J. W. Jr., Haas, R. H., Schell, J. A., & Deering, D. W. (1973/1974). *Monitoring Vegetation Systems in the Great Plains with ERTS.* Third Earth Resources Technology Satellite-1 Symposium, NASA SP-351, pp. 309–317. https://ntrs.nasa.gov/citations/19740022614 — ต้นตำรับสูตร NDVI = (NIR − Red)/(NIR + Red) ที่ระบบใช้คำนวณผ่าน `normalizedDifference(['B8','B4'])`.

**[R24]** Lee, J., Lim, J., Lee, J., Park, J., & Won, M. (2024). *Ground-Based NDVI Network: Early Validation Practice with Sentinel-2 in South Korea.* **Sensors**, 24(6), 1892. https://doi.org/10.3390/s24061892 — validate ค่า NDVI จาก Sentinel-2 (band B8/B4) เทียบกับเซนเซอร์ภาคพื้นดิน 8 จุด ยืนยันความแม่นยำของสูตรที่ใช้กับข้อมูลดาวเทียมชุดเดียวกับระบบนี้.

**[R25]** Chave, J., Réjou-Méchain, M., Búrquez, A., et al. (2014). *Improved allometric models to estimate the aboveground biomass of tropical trees.* **Global Change Biology**, 20(10), 3177–3190. https://doi.org/10.1111/gcb.12629 — โมเดล pan-tropical allometry ที่ `green-area-backend/impact.py` ใช้เป็นฐานคำนวณค่า kg CO₂/ต้น/ปี ต่อชนิดพันธุ์ไม้ (พบว่าใช้จริงในโค้ดแต่ยังไม่เคยขึ้นบรรณานุกรมมาก่อน).

**[R26]** U.S. Environmental Protection Agency (2023). *Greenhouse Gas Emissions from a Typical Passenger Vehicle.* EPA-420-F-23-014. Washington, DC: U.S. EPA. — ค่าอ้างอิง 4.6 ตัน CO₂/คัน/ปี ที่ `impact.py` ใช้แปลงผล CO₂ ที่ดูดซับได้เป็น "เทียบเท่ารถยนต์ที่ลดได้" (`equivalent_cars_off_road`).

### แหล่งข้อมูล/แพลตฟอร์มหลัก (Data Sources & Platform)

**[R27]** Drusch, M., Del Bello, U., Carlier, S., Colin, O., et al. (2012). *Sentinel-2: ESA's Optical High-Resolution Mission for GMES Operational Services.* **Remote Sensing of Environment**, 120, 25–36. https://doi.org/10.1016/j.rse.2011.11.026 — ภารกิจดาวเทียม Sentinel-2 (`COPERNICUS/S2_SR_HARMONIZED`, band B8/B4) ที่ระบบใช้เป็นแหล่งข้อมูลหลักคำนวณ NDVI (`gee_utils.py`, `routers/ndvi/compute.py`).

**[R28]** Gorelick, N., Hancher, M., Dixon, M., Ilyushchenko, S., Thau, D., & Moore, R. (2017). *Google Earth Engine: Planetary-scale geospatial analysis for everyone.* **Remote Sensing of Environment**, 202, 18–27. https://doi.org/10.1016/j.rse.2017.06.031 — แพลตฟอร์มประมวลผลภูมิสารสนเทศที่ระบบใช้เป็น compute backend ทั้งหมด (NDVI/LST/priority/urban subset).

**[R29]** Tatem, A. J. (2017). *WorldPop, open data for spatial demography.* **Scientific Data**, 4, 170004. https://doi.org/10.1038/sdata.2017.4 — ชุดข้อมูลประชากรเชิงพื้นที่ (WorldPop, 100 m) ที่ `routers/recommend/scoring.py` ใช้เป็นปัจจัย `pop_need` ใน Priority Score.

**[R30]** Hijmans, R. J., Garcia, N., & Wieczorek, J. (2021). *GADM database of Global Administrative Areas, version 4.1.* University of California, Berkeley. https://gadm.org/ — ขอบเขตการปกครอง (77 จังหวัด / 928 อำเภอ) ที่ระบบใช้ clip ข้อมูลและ generate districts (`generate_districts.py`).

**[R31]** U.S. Geological Survey (2022). *Landsat 8-9 Collection 2 Level 2 Science Product Guide.* Version 5.0. Sioux Falls, SD: USGS EROS Center. — เอกสารระเบียบวิธีของ Landsat Collection 2 Level-2 (band `ST_B10`) ที่ระบบดึงมาคำนวณ LST (`gee_utils.py`) ใช้คู่กับอัลกอริทึม `[R14]`.

**[R32]** Moukomla, S., Meeprom, P., & Intarat, K. (2026). *Impact of Impervious Surface Expansion on Urban Thermal Environment Across Tropical Southeast Asian Megacities: Reliable Assessment Through Foundation Model Embeddings.* **Earth**, 7(3), 76. https://doi.org/10.3390/earth7030076 — **นำมาใช้แล้ว:** เป็นฐานของปัจจัยที่ 5 "peri-urban cooling opportunity" ใน Priority Score · ข้อค้นพบที่นำมาใช้: การเพิ่มพื้นที่สีเขียวน่าจะลดความร้อนได้คุ้มสุดที่ "ขอบเมืองกำลังขยาย" (pervious→mixed) และอิ่มตัวที่ใจกลางเมือง — สนับสนุนด้วย stratified Pearson r = 0.65/0.51 (โล่ง/ผสม) vs −0.14 (ทึบเต็ม) ส่วน 5.5 (Discussion) · implement ใน `routers/recommend/scoring.py` (`peri_urban_need_image` — trapezoid บน Dynamic World built-probability ผ่าน `gee_utils.dynamic_world_built`) ถ่วงน้ำหนักคงที่ 15% แบบ additive (ไม่ลดปัจจัยเดิม 4 ตัว) · ใช้กรอบนิยาม SUHI urban ISA≥50% / rural ≤10% ตาม Imhoff et al. (2010).
> _หมายเหตุ: งานวิจัยรายงาน "ความสัมพันธ์เชิงสถิติ" (correlation) ระหว่าง ISA fraction กับ LST ไม่ได้ทดลองปลูกจริง และเตือนเองว่า correlation ไม่พิสูจน์ causation — น้ำหนัก 15% และปัจจัยเดิม 4 ตัวเป็นการออกแบบของโครงการ ไม่ได้มาจากงานวิจัย (งานวิจัยให้เพียงแนวคิดว่าขอบเมืองสำคัญ)_

**[R36]** Brown, C. F., Brumby, S. P., Guzder-Williams, B., Birch, T., Hyde, S. B., Mazzariello, J., et al. (2022). *Dynamic World, Near real-time global 10 m land use land cover mapping.* **Scientific Data**, 9, 251. https://doi.org/10.1038/s41597-022-01307-4 — ชุดข้อมูล land cover 10 m จากโมเดล deep learning บน Sentinel-2 (`GOOGLE/DYNAMICWORLD/V1`) ที่ระบบใช้ 2 ทาง: (1) band `built` เฉลี่ยรายปีเป็น ISA proxy ของปัจจัย peri-urban ตาม `[R32]` (`gee_utils.dynamic_world_built` → `isa_frac`) · (2) provider แรกของชั้น "การใช้ที่ดิน" โดย map 9 คลาสของ DW เข้า 5 ประเภทหลักของ LDD `[R38]` (`landuse.py` `DW_TO_LDD`).

**[R37]** Farr, T. G., Rosen, P. A., Caro, E., Crippen, R., Duren, R., Hensley, S., et al. (2007). *The Shuttle Radar Topography Mission.* **Reviews of Geophysics**, 45(2), RG2004. https://doi.org/10.1029/2005RG000183 · ชุดข้อมูล: NASA JPL (2013). *NASA Shuttle Radar Topography Mission Global 1 arc second* (SRTMGL1 v003). https://doi.org/10.5067/MEaSUREs/SRTM/SRTMGL1.003 — แบบจำลองความสูง 30 m (`USGS/SRTMGL1_003`) ที่ `routers/recommend/scoring.py` `plantable_mask` แปลงเป็นความชันด้วย `ee.Terrain.slope` แล้วตัดพื้นที่ชันเกิน `MAX_SLOPE_DEG` = 30° (≈58% grade) ออกจากพื้นที่ที่แนะนำให้ปลูก.

**[R38]** กรมพัฒนาที่ดิน กระทรวงเกษตรและสหกรณ์. *ข้อมูลสภาพการใช้ที่ดิน มาตราส่วน 1:25,000 — กรุงเทพมหานคร พ.ศ. 2566* (shapefile `LU_BKK_2566`, 11,073 polygon). https://www.ldd.go.th/ — ข้อมูลราชการ land *use* จากการสำรวจภาคสนาม ที่ระบบใช้ 2 ทาง: (1) **schema กลาง** ของชั้นการใช้ที่ดินทั้งระบบ — 5 ประเภทหลัก U ชุมชน · A เกษตรกรรม · F ป่าไม้ · W แหล่งน้ำ · M เบ็ดเตล็ด (`landuse.LANDUSE_CATEGORIES`) พร้อมรหัสละเอียด 96 ประเภท (`ldd_codes.py`) · (2) **provider ที่สอง** ของชั้นนั้น (`ldd.py`) อ่านจาก GEE FeatureCollection asset ผ่าน env `LDD_LANDUSE_ASSET` — สรุปพื้นที่จาก `Shape_Area` ของ polygon จริงจึงตรงกับเอกสาร LDD ไม่ใช่ประมาณจาก pixel · edition ปัจจุบันครอบคลุมเฉพาะกรุงเทพฯ ปี 2566 (ดู `data/ldd/README.md`).

**[R39]** Food and Agriculture Organization of the United Nations (2015). *Global Administrative Unit Layers (GAUL) 2015.* Rome: FAO. — ชั้นขอบเขตการปกครองระดับ 2 (`FAO/GAUL/2015/level2`) ที่ `generate_districts.py` ใช้เป็นเส้นทางดึงขอบเขตอำเภอผ่าน GEE (ใช้คู่/สำรองกับ GADM `[R30]` ซึ่งเป็นแหล่งหลัก) — ชื่ออำเภอที่ได้เป็นภาษาอังกฤษ จึง patch ชื่อไทยทับภายหลังในสคริปต์เดียวกัน.

### มาตรฐานคุณภาพข้อมูล (Data Quality Standards)

**[R33]** Global Climate Observing System (2022). *The 2022 GCOS ECVs Requirements* (GCOS-245). Geneva: WMO. https://library.wmo.int/records/item/58111-the-2022-gcos-ecvs-requirements — ตาราง requirement ของ ECV แต่ละตัว · ใช้ค่าของ **FAPAR** (ECV ด้านพืชพรรณที่ใกล้ NDVI ที่สุด และ NDVI ถูกใช้เป็น proxy อย่างแพร่หลาย): required measurement uncertainty **Goal 5%** ของค่า · **Threshold 10%** (ที่ 2σ, สำหรับค่า ≥ 0.05) โดย GCOS นิยาม Goal = ระดับที่ดีจนไม่ต้องพัฒนาต่อ, Threshold = ขั้นต่ำที่ข้อมูลยังมีประโยชน์ · ระบบใช้เป็นเกณฑ์ตัดระดับใน `routers/ndvi/compute.py::grade_uncertainty`
> _ข้อจำกัดที่ต้องระบุในเล่ม: NDVI ไม่ได้เป็น ECV ในตัวเอง การใช้เกณฑ์ของ FAPAR จึงเป็นการ **เทียบเคียง** และเป็นเกณฑ์ระดับ climate record ซึ่งเข้มกว่าที่งานจัดอันดับพื้นที่สีเขียวเชิงนโยบายต้องการ_

**[R34]** Group on Earth Observations / Committee on Earth Observation Satellites. *A Quality Assurance Framework for Earth Observation (QA4EO) — Principles* (v4.0) · guideline QA4EO-QAEO-GEN-DQK-001. https://qa4eo.org/ — หลักการ: ข้อมูลและผลิตภัณฑ์ที่ได้จากข้อมูล EO ทุกชิ้นต้องแนบ **Quality Indicator** ที่มาจากการประเมินเชิงปริมาณและสาวกลับไปหามาตรฐานที่ตกลงร่วมกันได้ · เป็นเหตุผลเชิงมาตรฐานของการมี NFR-07 และของการเปิดเผยสูตร/ค่าคงที่ทั้งหมดที่ใช้ตัดระดับ

**[R35]** กรมอุตุนิยมวิทยา. *ฤดูกาลของประเทศไทย.* https://www.tmd.go.th/ — แบ่งเป็น 3 ฤดู: ฤดูร้อน (กลาง ก.พ.–กลาง พ.ค.) · ฤดูฝน (กลาง พ.ค.–กลาง ต.ค.) · ฤดูหนาว (กลาง ต.ค.–กลาง ก.พ.) · ใช้ตรวจว่า composite รายปีมีภาพครบทุกฤดูหรือไม่ (แทนการนับจำนวนเดือนแบบตั้งเกณฑ์เอง) — TMD ประกาศวันเริ่มฤดูจริงเป็นรายปี ระบบใช้ "กลางเดือน = วันที่ 16" เป็นค่าประมาณคงที่ (`TMD_SEASONS`)

---

_อัปเดตล่าสุด: 2026-07-27 · **FR-17 (ตัวชี้วัดเรือนยอด 30% ของกฎ 3-30-300) implement แล้ว** —
ทุกจังหวัด/อำเภอมีค่าเรือนยอดปกคลุมเทียบเกณฑ์ 30% พร้อมระยะห่างจากเกณฑ์ (จุด% และ km²)
ทั้งบนหน้าจอ รายงาน PDF และ CSV · ค่าระดับมาจาก ESA WorldCover `[R13]` ส่วนแนวโน้มรายปี
มาจาก Dynamic World `[R36]` หลังวัดเทียบแล้วพบว่า DW ตรวจไม่เจอเรือนยอดในเขตเมือง
(ดู §5 ข้อจำกัด) · ก่อนหน้าในวันเดียวกัน ยืนยันชื่อผู้แต่งของ `[R18]` (Shin, J., & Park, J.) จากหน้า DOI ของ MDPI
— รายการนี้เคยกำกับไว้ว่ายังไม่ทราบชื่อผู้แต่ง · กำกับ `[R2]` `[R18]` `[R20]` ว่า "ลงบรรณานุกรมบทที่ 1 แล้ว"
หลังเติมการอ้างอิงให้มาตรฐาน 3-30-300 / 2SFCA / Tree Equity Score ในขอบเขตข้อ 3.1–3.3 ของรูปเล่ม ·
ก่อนหน้า (2026-07-26) เพิ่ม `[R36]`–`[R39]` (Dynamic World, SRTM, LDD 1:25,000, FAO GAUL 2015)
— ชุดข้อมูลที่ระบบเรียกใช้จริงในโค้ดอยู่แล้วแต่ยังไม่เคยขึ้นบรรณานุกรม จัดไว้ในหมวด
"แหล่งข้อมูล/แพลตฟอร์ม" (เลขต่อท้าย R35 แต่จัดกลุ่มตามหมวด) — **รวมอ้างอิง 39 รายการ** ·
ก่อนหน้า (2026-07-25) NFR-07 (คุณภาพ/ความไม่แน่นอนของ NDVI composite) implement แล้ว —
ทุกค่า NDVI มีจำนวนภาพ, observation ปลอดเมฆต่อ pixel, ค่าความไม่แน่นอน (standard error ของ
ค่ามัธยฐาน) และความครบของฤดูกาลกำกับ ทั้งบนหน้าจอ รายงาน PDF และ CSV · เพิ่ม `[R33]`–`[R35]`
(GCOS-245, QA4EO, กรมอุตุนิยมวิทยา) เป็นเกณฑ์ตัดระดับแทนค่าที่ตั้งเอง — รวมอ้างอิง 35 รายการ ·
ก่อนหน้า (2026-07-07) เลื่อน `[RW1]` → `[R32]` (Moukomla et al. 2026, Earth 7(3):76) เป็น "ใช้แล้ว" หลัง implement ปัจจัย peri-urban ใน `scoring.py` — รวมอ้างอิงที่ใช้จริงเป็น 32 รายการ · ก่อนหน้า (2026-07-06) เพิ่ม `[R27]`–`[R31]` (แหล่งข้อมูล/แพลตฟอร์ม) · ใช้คู่กับ Proposal (presentation/generate_proposal_pdf.py) ข้อ 7.4.3–7.4.4_
