# ข้อมูลการใช้ที่ดิน LDD → GEE asset (provider ที่สอง)

`ldd.py` เป็น provider ตัวที่สองของชั้น "การใช้ที่ดิน" (ต่อจาก Dynamic World) โดยอ่าน
polygon การใช้ประโยชน์ที่ดินของ **กรมพัฒนาที่ดิน (LDD) 1:25,000** จาก **GEE
FeatureCollection asset** แล้ว rasterize เข้าค่า `landuse` 1–5 (schema กลาง U/A/F/W/M)
เหมือน Dynamic World ทุกอย่างหลัง `ee.Image` จึงใช้ร่วมกัน

Backend จะเปิด provider นี้เมื่อ **ตั้ง env `LDD_LANDUSE_ASSET`** เท่านั้น — ไม่ตั้ง =
ปุ่ม "LDD ราชการ" ในหน้า Stats จะไม่โผล่ ระบบใช้ Dynamic World ตามเดิม

---

## ข้อมูลต้นทาง

- Shapefile: `LU_BKK_2566.shp` (กรุงเทพฯ ปี พ.ศ. 2566 · 11,073 polygon · UTM Zone 47N)
- อยู่ในไฟล์ `Landuse_Bangkok_2566_.zip` (โฟลเดอร์ `Landuse_Bangkok_2566/`)
- คอลัมน์ (DBF) ที่โค้ดใช้ — มากับ shapefile อยู่แล้ว ไม่ต้องแก้:
  | property | ใช้ทำอะไร |
  |---|---|
  | `LUL1_CODE` | ประเภทหลัก `U/A/F/W/M` → map เป็นค่า 1–5 (`_L1_TO_VALUE`) |
  | `LU_CODE` | รหัสละเอียด 96 ประเภท → breakdown `detail` (ดู `ldd_codes.py`) |
  | `Shape_Area` | พื้นที่ polygon (ตร.ม. เพราะ prj เป็น UTM) → สรุปพื้นที่ทางการ |

> ⚠️ ไฟล์ `.zip`/`.shp` เป็น binary ก้อนใหญ่ (~5–17MB) — ไม่ควร commit เข้า git ตรงๆ
> อัปโหลดขึ้น GEE แล้วเก็บต้นฉบับไว้นอก repo (หรือใช้ Git LFS)

---

## ขั้นตอนอัปโหลด (ทำครั้งเดียว)

ต้องมี GEE project เดียวกับที่ backend ใช้ (`GEE_PROJECT`) และ login แล้ว

### วิธี A — Code Editor (ง่ายสุด, ผ่านเบราว์เซอร์)
1. เปิด https://code.earthengine.google.com → แท็บ **Assets** (ซ้ายบน) → **NEW → Shape files (.shp, .dbf, ...)**
2. เลือกไฟล์ **ทั้งชุด** ในโฟลเดอร์เดียวกัน: `.shp .dbf .shx .prj .cpg`
   (ต้องมี `.cpg = UTF-8` ไปด้วย ไม่งั้นชื่อไทยใน `LU_DES_TH` จะเพี้ยน — ในโค้ดใช้แค่
   `LUL1_CODE/LU_CODE/Shape_Area` ที่เป็น ASCII จึงไม่พังถึงชื่อเพี้ยน แต่แนบไปด้วยดีกว่า)
3. ตั้ง Asset ID เช่น `LU_BKK_2566` → **Upload** → รอ task (แท็บ Tasks) เสร็จ
4. ได้ asset id เต็ม เช่น `projects/<your-project>/assets/LU_BKK_2566`

### วิธี B — CLI `earthengine`
```bash
pip install earthengine-api            # มีอยู่แล้วใน requirements.txt
earthengine authenticate               # ครั้งแรก
# อัปโหลด (โยนไฟล์ .shp ทั้งชุดในโฟลเดอร์เดียวกัน ระบบดึง .dbf/.shx/.prj ให้เอง)
earthengine upload table \
  --asset_id=projects/<your-project>/assets/LU_BKK_2566 \
  path/to/Landuse_Bangkok_2566/LU_BKK_2566.shp
earthengine task list                  # รอ COMPLETED
```

GEE จะ reproject จาก UTM47N → EPSG:4326 ให้ตอน ingest เอง (`filterBounds` กับ geometry
WGS84 ของแอปจึงตรง) ส่วน `Shape_Area` เป็นตัวเลขเดิม (ตร.ม.) → คณิต km²/ไร่ ยังถูก

---

## ตั้งค่าให้ backend เห็น

1. ใน `.env` (ดู `.env.example`):
   ```
   LDD_LANDUSE_ASSET=projects/<your-project>/assets/LU_BKK_2566
   ```
2. restart backend → log ควรขึ้นตามปกติ (provider เปิดเมื่อ env มีค่า)
3. ทดสอบ:
   ```bash
   # สัดส่วน 5 ประเภท + detail 96 ประเภท (พื้นที่ทางการจาก polygon)
   curl "http://localhost:8000/analysis/landuse/Bangkok%20Metropolis?source=ldd"
   # tiles สำหรับวางทับแผนที่
   curl "http://localhost:8000/maps/Bangkok%20Metropolis/landuse-tiles?source=ldd"
   ```
   ผลควรมี `"source":"ldd"`, `"classes"` 5 แถว, และ (เฉพาะ summary) `"detail"` เรียงพื้นที่มากสุด

---

## เพิ่มจังหวัดอื่นในอนาคต

edition นี้เป็น **กทม.เท่านั้น** — UI โชว์ตัวเลือก LDD เฉพาะจังหวัดใน allow-list:

1. อัปโหลด asset ที่รวม polygon จังหวัดใหม่ (คอลัมน์ `LUL1_CODE/LU_CODE/Shape_Area` เหมือนเดิม)
2. `ldd.py` → เพิ่มชื่อจังหวัด (ชื่อ EN ตรงกับ `get_province_geom`) ใน `LDD_COVERAGE_PROVINCES`
3. `green-area-frontend/src/constants.js` → เพิ่มชื่อเดียวกันใน `LDD_PROVINCES`
4. ถ้ารหัส LU_CODE มีประเภทใหม่เกิน 96 → regenerate `ldd_codes.py` จาก DBF ชุดใหม่

> `ldd_codes.py` ถูก generate จาก DBF (LU_CODE → ประเภทหลัก + ชื่อ TH/EN) — อย่าแก้มือ
> ถ้าชุดข้อมูลเปลี่ยน ให้ generate ใหม่จาก shapefile ต้นทาง
