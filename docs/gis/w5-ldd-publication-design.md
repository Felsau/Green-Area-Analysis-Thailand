# ออกแบบ W5: เผยแพร่ข้อมูล LDD จริงขึ้นแดชบอร์ด (ร่างเพื่อขออนุมัติ)

- **ผู้รับผิดชอบ:** ชยากร (สมาชิกคนที่ 2) · **กำหนดตามแผน:** W5 (30 พ.ย.-6 ธ.ค. 2569, ส่งหลักฐานศุกร์ 4 ธ.ค.)
- **สถานะ:** ร่างออกแบบ 8 พ.ย. 2569 · ยังไม่ได้เขียนโค้ด ไม่ได้เขียน migration ไม่ได้แตะฐานข้อมูล · ตัวเลขมาจากการวัดแบบอ่านอย่างเดียว
- **โค้ดที่อ้างอิง:** branch `feature/gis-data-management` HEAD `fa10e1f`

## 1. เป้าหมายตามแผน (PDF หน้า 6)
1. เจ้าหน้าที่ GIS เปิดใช้ ถอน และย้อนกลับฉบับข้อมูลได้เองตามสิทธิ์
2. ข้อมูลที่เปิดใช้แสดงบนแดชบอร์ดและรายงานได้จริง
3. ทดลองตั้งแต่อัปโหลดจนเห็นผลบนหน้าเว็บครบหนึ่งรอบ บนเครื่องผู้พัฒนา
4. หลักฐาน: วิดีโอ/ภาพลำดับการใช้งาน · รายงานว่าเปิดใช้/ถอน/ย้อนกลับไม่ทำลายข้อมูลเดิม · รายการสิ่งที่ต้องแก้เพื่อให้รันนอกเครื่องผู้พัฒนาพร้อมเวลาที่ประเมิน (ร่างแล้วใน `docs/gis/w2-integration-prep.md` ข้อ 2)

**ขอบเขตที่เสนอ:** จังหวัดขนาดเล็กที่ผ่านการตรวจแล้ว (กรุงเทพฯ 2566, สิงห์บุรี 2566, นนทบุรี 2567, สมุทรปราการ 2567 ไม่เกินราว 11,100 แปลง) เป็นเป้าหลัก · ปทุมธานี 2568 (21,832 แปลง) เป็นเป้าเสริม ถ้าวัดใต้ลิมิตแล้วผ่าน (ข้อ 6) · จังหวัดใหญ่ไม่อยู่ในขอบเขต W5 เพราะติดเพดานตั้งแต่ขั้นตรวจ

## 2. ตอนนี้ติดอะไร (ตรวจจากโค้ดจริง)

| ขั้น | สถานะ | หลักฐาน |
|---|---|---|
| ตรวจไฟล์ (validation v2) | ✔ ใช้ได้กับข้อมูลจริง | กรุงเทพฯ ผ่านหน้าเว็บกับ worker จริงแล้ว |
| เตรียมข้อมูล (prepare v2) ฝั่ง worker | ✔ โค้ดและเทสต์พร้อม | `gis_worker/ldd_prepare_provider.py` (`METHOD_V2 = 'ldd-geometry-area-v2'`) · กรุงเทพฯ: geometry 15.06 MB, CPU 9.1 วินาที, VM 377 MiB ใต้ลิมิต child |
| เตรียมข้อมูล ฝั่ง SQL/API/หน้าเว็บ | ✗ ผูกกับ v1 | SQL 038: CHECK `method_version='ldd-source-area-v1'` ของ `ldd_prepare_requests`, `ldd_prepare_report`, `ldd_verify_complete`, `publication_ready`, `gis_publication_read` · `routers/ldd_prepare.py:51` · ไฟล์ที่ผ่านเฉพาะกฎ v2 ได้ `PREPARE_METHOD_V2_REQUIRED` |
| Preview | ✗ ใช้สัญญาณ v1 | `LddPreparedPreview.js:44-46` ใช้ `ready_for_publication` เป็น "ตรวจแล้ว" (GeoTIFF แยกเป็น `ready_for_review`) |
| เผยแพร่ (activate/withdraw/rollback) | ✗ ผูกกับ v1 | SQL 039/040: `ldd_publication_command`, `ldd_published_packet` · `routers/ldd_publication.py:24` `Literal['ldd-source-area-v1']` |
| แสดงบนแดชบอร์ด | ✗ ติดเพดาน 2 MiB | `gis_ldd_publication.py:47-54` ใส่ geometry ทั้งชุดใน bundle เดียว แล้วปฏิเสธเมื่อเกิน 2 MiB (`GIS_LDD_DISPLAY_LIMIT`) · หน้าเว็บเรียก bundle ซ้ำทุก 10 วินาที (`useLanduseData.js:90`) |
| เดโมบนเครื่อง | ✗ ไม่มี prepare worker | เดโมหลักใช้ worker ครบ 4 ตัวตามเพดาน guard (`manage.py:424`, ห้ามผ่อน) · เดโม A2 รับ ledger 37/38 เท่านั้น |

**ข้อห้ามที่ต้องคงไว้:** ห้ามให้ข้อมูล v2 ถูกเผยแพร่ใต้ identity ของ v1 (reader จะเรียก `gis_ldd_published_unavailable` และเพิกถอน certificate ถาวร) · ห้ามแก้ migration ที่ apply แล้ว · ห้ามผ่อน guard

## 3. ขนาดชั้นแสดงผลจากไฟล์จริง (วัด 8 พ.ย. 2569)
วัดด้วย `assess(collect=True)` ของ repo ใน image ปักหมุด (`--network=none`) แล้วสร้าง GeoJSON EPSG:4326 แบบต่าง ๆ (ไม่รวม metadata) · สคริปต์ `display_size_probe.py` ใน scratchpad ของ session

| แบบ | กรุงเทพฯ 2566 (11,073 แปลง) ดิบ / gzip | ปทุมธานี 2568 (21,832 แปลง) ดิบ / gzip | พื้นที่เปลี่ยน |
|---|---|---|---|
| แปลงเดิม ความละเอียดเต็ม (แบบ artifact ปัจจุบัน) | 13.65 / 4.76 MB | 22.82 / 7.73 MB | 0 |
| **แปลงเดิม ปัดพิกัด 6 ตำแหน่ง (≈0.11 ม.)** | **8.32 / 2.02 MB** | **14.05 / 3.20 MB** | 0 (จุดยอดครบ) |
| แปลงเดิม ลดรูป 1 ม. + 6 ตำแหน่ง | 6.55 / 1.55 MB | 10.12 / 2.21 MB | −0.001% / 0% |
| แปลงเดิม ลดรูป 3 ม. + 6 ตำแหน่ง | 5.44 / 1.25 MB | 8.46 / 1.76 MB | −0.004% / −0.008% |
| รวมตามหมวดหลัก (5 รูป) | 4.91 / 1.34 MB | 8.81 / 2.29 MB | 0 |
| รวมตามหมวด + ลดรูป 2 ม. | 3.35 / 0.93 MB | 5.22 / 1.39 MB | −0.001% / −0.005% |

ข้อสังเกต: การรวมตามหมวดลดขนาดได้น้อย (รูปมีรูและขอบภายในมาก) และทำให้หน้าเว็บเลิกนับแปลงได้ (`publishedAnalysis.js` ตรวจว่าจำนวน feature เท่ากับ `summary.feature_count`) · **ไม่มีแบบไหนผ่านเพดาน 2 MiB แบบดิบ** จึงต้องเปลี่ยนวิธีส่ง ไม่ใช่แค่ลดรูป

## 4. แนวทางที่เสนอ

### 4.1 Geometry สำหรับแสดงผล (เลือก B)
- **A. artifact แสดงผลแยก (ลดรูป 1 ม.)**: ส่งเล็กสุด แต่ต้องเพิ่มชนิด artifact ใหม่ (`037` CHECK `artifact_kind` มีแค่ `ldd_geometry`, `ldd_summary`) และแปลงข้างกันอาจมีรอยเหลื่อมหลังลดรูป
- **B. (แนะนำ) ใช้ `ldd_geometry` ของ v2 เดิม แต่ปัดพิกัดเป็น 6 ตำแหน่งตอน prepare**: จุดยอดครบทุกจุด ความคลาดเคลื่อน ≤ 0.11 ม. ไม่ต้องมีชนิด artifact ใหม่ · พื้นที่ในรายงานยังมาจาก geometry ที่ไม่ปัด (ผลของ validation) · ขนาดน่าจะต่ำกว่าเพดาน artifact 20 MiB ได้ถึงราว 25,000 แปลง (ประมาณจากเรขาคณิตล้วน 0.64-0.75 KB/แปลง บวก properties และ metadata · ต้องวัดจริง) · verifier สร้างซ้ำได้ byte เดียวกันเพราะการปัดเป็น deterministic
- ไม่เลือกแบบรวมตามหมวด เพราะเสียการนับแปลงและได้ขนาดลดลงไม่มาก
- **ปรับหลังอนุมัติ (8 พ.ย., วัดจากไฟล์จริง):** การปัด 6 ตำแหน่งทำให้บางแปลงเสียรูป (self-intersection) กรุงเทพฯ 7, ปทุมธานี 14, สิงห์บุรี 32, นนทบุรี 19, สมุทรปราการ 10 แปลง (ที่ 7 ตำแหน่งยังมี 0-5 แปลง) ซึ่ง prepare v2 จะปฏิเสธทั้งชุด (`PREPARE_GEOMETRY_INVALID`)
  จึงใช้กฎเพิ่ม: **แปลงที่ปัดแล้วเสียรูปให้คงพิกัดเต็ม** (กฎตายตัว verifier สร้างซ้ำได้) และบันทึกจำนวนกับรายชื่อแปลง (สูงสุด 100) ใน `metadata.display_coordinates` · ทำแล้วใน `gis_worker/ldd_prepare_provider.py` (`DISPLAY_DECIMALS = 6`) พร้อมเทสต์ 2 ข้อ ยังไม่ commit
  · v2 ยังไม่เคยถูกบันทึกหรือเผยแพร่ในฐานข้อมูล (SQL ยังรับแค่ v1) จึงเปลี่ยนรูปแบบไฟล์ v2 ได้โดยไม่ต้องตั้ง method version ใหม่ · v1 ไม่เปลี่ยน (เทสต์ byte-identical ผ่าน)

### 4.2 การส่งข้อมูลให้แดชบอร์ด
- แยกเป็น 2 คำขอ: `/published-ldd` ส่งเฉพาะ snapshot, source identity, summary, legend และ descriptor ของ geometry (sha256, ขนาด) → เล็ก เรียกซ้ำทุก 10 วินาทีได้เหมือนเดิม
- `/published-ldd/geometry?snapshot=<id>` ส่ง geometry ครั้งเดียวต่อ snapshot (บีบอัด gzip, ใช้ sha256 เป็น ETag, ตรวจ lineage เหมือน bundle เดิม) · หน้าเว็บโหลดใหม่เฉพาะเมื่อ snapshot เปลี่ยน
- เพดานใหม่: ตรวจขนาด summary ส่วนเล็กเท่าเดิม (2 MiB) และจำกัด geometry ที่ส่งไม่เกินเพดาน artifact (20 MiB ดิบ) แทนการรวมทุกอย่างใน bundle เดียว · ยังไม่ตัด geometry เงียบ ๆ

### 4.3 SQL: Migration 052 (ไฟล์เดียว, ขออนุมัติตามขั้นตอนเดิม)
ใช้แบบแผนเดิม: เปลี่ยนชื่อฟังก์ชันเดิมเป็น `u052_previous_*` แล้วครอบ (เหมือน 049-051) ไม่แก้ 038-040
1. **prepare v2:** ขยาย CHECK `method_version` ของคำขอ prepare และงานให้รับ `ldd-geometry-area-v2` · ฟังก์ชัน prepare/report/verify/read รับ v2 โดยตรวจ metadata ของ v2 (`schema_version=2`, `area_method`, `boundary_sha256` ที่ 051 รับ, `legend_sha256`, `field_profile`)
2. **สัญญาณ preview:** v2 ใช้ `ready_for_review` แบบ GeoTIFF ก่อน แล้วจึง `ready_for_publication` เมื่อ verifier ผ่าน
3. **publication v2:** `publication_ready`, `ldd_publication_command`, `ldd_published_packet` รับ v2 โดย identity ต้องบอก method จริงเสมอ (v1 คงเดิมทุกประการ) · ย้อนกลับข้ามเวอร์ชัน (v2 → v1 ฉบับเก่า) ได้เพราะ reader อ่าน method จาก identity
4. **ไม่รวม:** ปุ่มอนุมัติ Review Required, ชนิด artifact ใหม่, เปลี่ยนเพดาน 20 MiB
5. probe แบบ rollback บน `postgres` และ `gis_t1_upgrade` → ไฟล์อนุมัติผูก SHA256 → apply บน Local T0 เท่านั้น · `gee_dashboard_local.py` ต้องเพิ่ม ledger 52 (ต้องขออนุมัติแก้ไฟล์นี้)

### 4.4 Backend และหน้าเว็บ
- `routers/ldd_prepare.py`, `routers/ldd_publication.py`: รับ `ldd-geometry-area-v2` (ตาม method ของ validation ไม่ให้ผู้ใช้เลือกเอง)
- `gis_ldd_publication.py`: แยก summary กับ geometry ตามข้อ 4.2
- `LddPreparedPreview.js`: ใช้ `ready_for_review` · `useLanduseData.js` + `publishedLddLayer.js`: โหลด geometry ตาม snapshot
- `PublishedLddSummary.js`: ข้อความสำหรับ v2 (ตอนนี้เขียนว่า "พื้นที่จาก Shape_Area เดิม" และ "Boundary เป็นแบบประมาณ" ซึ่งไม่ตรงกับ v2 ที่ใช้พื้นที่จากรูปแปลงและขอบเขตจากผู้ผลิตในหลายจังหวัด)

### 4.5 เดโมบนเครื่อง (ไม่ผ่อน guard)
- ตัวเปิดเดโมแบบ "LDD publication" แยกจากเดโมหลัก ใช้ worker ไม่เกิน 4 ตัว: ตรวจ LDD + prepare LDD (+ processing ถ้าจำเป็น) · รับ ledger ปัจจุบัน (51 → 52)
- ใช้ runner/verifier เดิมของ A2 (`dev/gis_local/ldd_prepare_local.py`) โดยปรับให้รู้จัก ledger ใหม่ (ต้องขออนุมัติเหมือนการแก้ `gee_dashboard_local.py`)

## 5. ลำดับงานและเวลาที่ประเมิน

| ช่วง | งาน | ประมาณ |
|---|---|---|
| W2 (9-13 พ.ย.) | ผู้ใช้/หัวหน้าอนุมัติแนวทางในเอกสารนี้ | — |
| W3 (16-20 พ.ย.) | worker: ปัดพิกัด geometry v2 + เทสต์ · ร่าง Migration 052 + lifecycle probe | 2-3 วัน (ทำคู่กับงานรวมระบบ W3) |
| W4 (23-27 พ.ย.) | อนุมัติและ apply 052 · router + หน้าเว็บ + ตัวเปิดเดโม | 2-3 วัน |
| W5 (30 พ.ย.-4 ธ.ค.) | ทดลองครบรอบบนเครื่อง: อัปโหลด → ตรวจ → prepare → verify → เปิดใช้ → แดชบอร์ด → ถอน → ย้อนกลับ · เก็บวิดีโอและรายงานว่าข้อมูลเดิมไม่ถูกทำลาย | 1-2 วัน |

**เกณฑ์ผ่านของ W5:** อย่างน้อยกรุงเทพฯ 2566 ผ่านครบรอบผ่านหน้าเว็บ · ถอนแล้วแดชบอร์ดไม่แสดงฉบับนั้นอีก (แจ้งว่าไม่มีฉบับเปิดใช้ หรือแสดงฉบับที่เลือกแทน) · ย้อนกลับแล้วได้ snapshot ของฉบับก่อนหน้า · ไฟล์ต้นฉบับ ผลตรวจ และ artifact ของฉบับก่อนยังอยู่ครบ · เทสต์ทุกชุดผ่าน

## 6. ความเสี่ยงและสิ่งที่ยังไม่ได้วัด
- **prepare v2 ใต้ลิมิต child (วัด 8 พ.ย. หลังปัดพิกัด, `RLIMIT_CPU` 20 วินาที, `RLIMIT_AS` 512 MiB):**

  | จังหวัด | แปลง | ldd_geometry | CPU | VM สูงสุด | แปลงคงพิกัดเต็ม |
  |---|---|---|---|---|---|
  | กรุงเทพฯ 2566 | 11,073 | 9.74 MB (เดิม 15.06) | 9.9 วินาที | 366 MiB | 7 |
  | สิงห์บุรี 2566 | 10,820 | 11.96 MB | 10.3 วินาที | 400 MiB | 32 |
  | นนทบุรี 2567 | 9,635 | 7.26 MB | 8.3 วินาที | 325 MiB | 19 |
  | สมุทรปราการ 2567 | 8,819 | 9.39 MB | 8.4 วินาที | 363 MiB | 10 |
  | ปทุมธานี 2568 | 21,832 | 16.62 MB | **18.3 วินาที** | **466 MiB** | 14 |

  จังหวัดเล็กทั้ง 4 มีที่ว่างราวครึ่งหนึ่ง · **ปทุมธานีผ่านแต่ใช้ CPU 92% และหน่วยความจำ 91% ของเพดาน** เครื่องที่ช้ากว่าอาจเกินได้ จึงคงเป็นเป้าเสริม · verifier สร้างไฟล์ซ้ำด้วยงานขนาดเท่ากัน
- **ความเร็วหน้าเว็บ:** ยังไม่ได้วัดการวาดราว 316,000 จุดยอด (กรุงเทพฯ) ใน deck.gl บนเครื่องผู้ทดสอบ · ถ้าช้า ใช้แบบ A (ลดรูป 1 ม.) เป็นทางสำรอง
- **ขนาดของ Migration 052:** ฟังก์ชันใน 038-040 ยาวและเชื่อมกันหลายจุด อาจใช้เวลามากกว่าที่ประเมิน · ถ้าไม่ทันใน W4 ให้แยก prepare/preview (ทำได้ก่อน) ออกจาก publication
- **ขอบเขตจังหวัด:** กรุงเทพฯ ใช้ขอบเขตจากผู้ผลิตข้อมูลเอง ต้องเขียนในหน้าแดชบอร์ดว่าไม่ใช่แหล่งอิสระ
- **ข้อจำกัดของเดโม:** ทั้งหมดยังเป็นงานบนเครื่องผู้พัฒนา (ล็อก 4 ชั้นตาม `w2-integration-prep.md` ข้อ 2) การขึ้นเซิร์ฟเวอร์เป็นงาน W6

## 6.1 แผนร่าง Migration 052 (สำรวจ SQL 8 พ.ย.)
ฟังก์ชันและ constraint ที่ผูกกับ v1 หรือสัญญาณ `ready_for_publication` (ห้ามแก้ไฟล์เดิม ใช้วิธีครอบ):

| ไฟล์ | สิ่งที่ผูกกับ v1 | สิ่งที่ 052 ต้องทำ |
|---|---|---|
| 038 บรรทัด 65 | `ldd_prepare_requests.method_version` DEFAULT และ CHECK = `ldd-source-area-v1` | ขยาย CHECK ให้รับ `ldd-geometry-area-v2` (คง DEFAULT v1) |
| 038 `check_catalog` (25-89), `check_ldd_prepare_catalog` (542-581) | ตรวจ catalog ของคำขอ prepare | รับ v2 และตรวจ metadata ของ v2 |
| 038 `ldd_prepare_command` (146-195), `ldd_prepare_packet` (99-114) | สร้างคำขอและ packet ให้ worker | เลือก method จาก validation (v2 เมื่อผลตรวจเป็น policy v2) ไม่ให้ผู้ใช้เลือกเอง |
| 038 `ldd_prepare_report` (115-145) | รับรายงาน worker ของ v1 | รับรายงาน v2 (`schema_version=2`, `display_coordinates`, `boundary_sha256` ที่ 051 รับ, `legend_sha256`) |
| 038 `ldd_verify_complete` (605-661), `ldd_prepare_read` (662-680), `gis_publication_read` (720-743) | ใช้ `ready_for_publication` และ method v1 | v2: ตั้ง `ready_for_review` เมื่อ verifier ผ่าน และอ่านได้ทั้งสองแบบ |
| 038 `publication_ready` (582-604) | v1 เท่านั้น | รับ v2 ที่ verify แล้ว (identity ต้องบอก v2) |
| 039/040 `ldd_publication_command` (040: 14-111), 039 `ldd_published_packet` (163-185) | v1 | รับ v2 · ย้อนกลับข้ามเวอร์ชันได้ |
| 045/048 `jobs_validator_version_check` | มี `ldd-prepare-v1` | คงชนิดงานเดิม (method อยู่ในคำขอ) ถ้าเป็นไปได้ เพื่อไม่ต้องแตะ CHECK นี้ |

ลำดับร่าง: (1) อ่านฟังก์ชันทั้งหมดและเขียนสเปกฟังก์ชันละย่อหน้า (2) เขียน 052 + lifecycle SQL ที่ rollback (แบบ `upload_051_lifecycle.sql`) (3) probe บนทั้งสองฐาน (4) ขออนุมัติ apply

## 6.2 สถานะ Migration 052 (8 พ.ย. 2569): **apply บน Local T0 ทั้งสองฐานแล้ว** (ผู้ใช้อนุมัติ "อนุมัติ 052")
- **apply:** ไฟล์อนุมัติ `green-area-backend/.venv/upload-052-approval.json` ผูก sha256 `1fbbf733...60cb` → `upload_052_local.py migrate` ได้ `applied` ทั้ง `postgres` และ `gis_t1_upgrade`
- **ตรวจหลัง apply (อ่านอย่างเดียว):** ledger = 52 และ hash ตรงทั้งสองฐาน · CHECK รับ v1/v2 · trigger `prepare_method` มีอยู่ · ฟังก์ชันใหม่มีสิทธิ์เฉพาะ `gis_owner` · `gis_publication_read` ยังให้ `service_role` เท่านั้น · สิทธิ์ CREATE บน public ของ `gis_owner` ถูกถอนแล้ว · คำขอ prepare เดิม 15 แถวยังเป็น v1 ไม่เปลี่ยน
- **lifecycle รันซ้ำกับฟังก์ชันจริง** ในทรานแซกชันที่ rollback ผ่านทั้งสองฐาน และไม่เหลือข้อมูลทดสอบ
- **ผลข้างเคียงที่แก้แล้ว:** `dev/gis_local/gee_dashboard_local.py` ให้ worker ของเดโม GEE รับ ledger 52 (ผู้ใช้อนุมัติ 8 พ.ย.; เทสต์ 5 ผ่าน, proof กับ ledger จริงผ่าน) · ยังไม่ได้ลองเปิดเดโมจริงหลัง 052
- **ไฟล์:** `green-area-backend/migrations/052_gis_ldd_prepare_publication_v2.sql` (sha256 `1fbbf733f007c148302c47455c366ddbdd468050f57a6c260daab5007c0e60cb`) · ตัวรัน `dev/gis_local/upload_052_local.py` · lifecycle `dev/gis_local/upload_052_lifecycle.sql` (sha256 `be537006...f767`) · `.gitattributes` เพิ่ม `-text` ให้ `052`
- **สิ่งที่ 052 ทำ (ไม่แก้ 038-040):**
  1. CHECK `method_version` ของคำขอ prepare รับ v1 และ v2
  2. trigger `prepare_method` ตั้ง method ของคำขอจากผลตรวจ: รายงานที่มี `LDD_POLICY_V2` → v2 นอกนั้น v1 (ผู้เรียกเลือกเองไม่ได้)
  3. `ldd_prepare_report` ครอบของเดิม (`u052_previous_ldd_prepare_report`): รายงานต้องบอก method เดียวกับคำขอ แล้วตรวจด้วยกฎเดิมทุกข้อ
  4. `publication_ready`, `ldd_verify_complete`, `gis_publication_read`, `ldd_publication_command`, `ldd_published_packet` เขียนทับในที่เดิม (แบบ 040) โดยเปลี่ยนเฉพาะจุดที่เคยเป็นค่าคงที่ v1 ให้ใช้ method ของคำขอ · v1 ได้ผลเหมือนเดิม และ identity ของ v1 (รวม snapshot id) ไม่เปลี่ยน
  5. เผยแพร่: payload ต้องบอก method ของใบรับรองของฉบับนั้น ไม่ตรงได้ `GIS_PUBLICATION_METHOD_MISMATCH` (รหัสใหม่ ตรวจหลังข้อเดิมทั้งหมด เพื่อไม่ให้รหัสผิดพลาดของ v1 เปลี่ยน) · audit บันทึก method จริง
- **ต่างจากแผนข้อ 4.3:** ไม่มีแฟล็ก `ready_for_review` แยก เพราะ 052 เปิดเผยแพร่ v2 พร้อมกันและ identity บอก method เสมอ จึงไม่มีทางที่ v2 จะถูกเผยแพร่ใต้ชื่อ v1 · เพิ่มการให้สิทธิ์ CREATE บน schema public ชั่วคราวในทรานแซกชันเดียวกับ 038 เพื่อแทนที่ `public.gis_publication_read`
- **probe แบบ rollback ผ่านทั้ง `postgres` และ `gis_t1_upgrade`:** 2 ชุดข้อมูล (ผลตรวจแบบ v2 และแบบเดิม) ผ่านครบ ตรวจ → prepare → verify → เปิดใช้ → อ่านแบบแดชบอร์ด และชุด v2 ถอนใช้แล้วอ่านไม่ได้ · กรณีที่ต้องถูกปฏิเสธ 7 แบบของรายงาน, proof ที่ method ผิด, payload ที่ method ผิด/ไม่รู้จัก/null, ถอนด้วย method ผิด · ฟังก์ชันใหม่ไม่เปิดให้ role ใดเรียก และ `gis_publication_read` ยังให้ `service_role` เท่านั้น ·
  ตรวจหลัง probe: ledger ยัง 51, ไม่เหลือฟังก์ชัน/trigger/ข้อมูลทดสอบ · **negative control:** แก้ความคาดหวังให้ผิดหนึ่งจุดแล้ว probe ล้มด้วย `T_REQUEST_METHOD` ตามคาด (lifecycle ตรวจจริง)
- **ยังไม่ครอบคลุม:** การย้อนกลับข้ามเวอร์ชัน (v2 → ฉบับ v1 เก่าในชุดข้อมูลเดียวกัน) · การเรียกผ่าน worker จริงด้วย JWT (probe เขียนแถวของ worker เองตามที่ `ldd_prepare_worker` เขียน) · ฝั่ง API และหน้าเว็บยังผูก v1 (`routers/ldd_prepare.py:51`, `routers/ldd_publication.py:24`) จะแก้หลัง apply
- **ขั้นถัดไปที่ต้องอนุมัติ:** (ก) apply 052 บน Local T0 ด้วยไฟล์อนุมัติที่ผูก sha256 ข้างบน (ข) แก้ `dev/gis_local/gee_dashboard_local.py` ให้รับ ledger 52 (ไม่งั้น worker ของเดโม GEE จะเปิดไม่ได้)

## 6.3 API และหน้าเว็บรับ v2 (8 พ.ย. 2569, ยังไม่ commit)
- **`routers/ldd_publication.py`:** รับ `method_version` ได้ทั้ง v1/v2 · method ที่ส่งให้ SQL มาจากคำขอ prepare ของฉบับนั้นเอง (`gis_ldd_prepare_read`) ใช้ค่าจากผู้ใช้เฉพาะเมื่อฉบับยังไม่เคยเตรียม แล้ว SQL ตรวจซ้ำ · ปุ่มเผยแพร่เดิม (`LddPublicationActions.js`) จึงไม่ต้องแก้
  · endpoint ใหม่ `GET /gis/published-ldd/geometry?province=&data_year=&snapshot_id=` ส่ง geometry ของ snapshot นั้นเท่านั้น (ไม่ตรงได้ 409 `GIS_SOURCE_CHANGED`) บีบอัด gzip เมื่อผู้เรียกรับได้ ไม่ cache ฝั่ง server
- **`gis_ldd_publication.py`:** bundle ที่เรียกทุก 10 วินาทีไม่มี geometry แล้ว มีแค่ `geometry_artifact` (sha256, ขนาด) · เพดาน 2 MiB ตรวจกับ bundle เล็กนี้ · ตอนเปิดใช้ตรวจว่า geometry เป็น FeatureCollection และจำนวนแปลงเท่ากับ summary · ตรวจ byte/lineage ของไฟล์ทุกครั้งเหมือนเดิม
- **`routers/ldd_prepare.py`:** Preview บอก method จริงของคำขอ prepare (ไม่ตายตัวเป็น v1)
- **หน้าเว็บ:** `useLanduseData.js` โหลด geometry ครั้งเดียวต่อ snapshot แล้วรวมเข้า bundle · `gisClient.js` เพิ่มเส้นทาง geometry · `publishedAnalysis.js` รับ v2 (ทุกส่วนต้องบอก method เดียวกัน) · `PublishedLddSummary.js` ข้อความของ v2 (พื้นที่จากรูปแปลง UTM, ขอบเขตจากผู้ผลิตข้อมูล "ไม่ใช่แหล่งอิสระ", ผลตรวจไฟล์) · `LddPreparedPreview.js` คำอธิบายตารางตาม method
- **เทสต์:** backend Windows 1779 ผ่าน/81 ข้าม · native 415 ผ่าน · หน้าเว็บ 395 ผ่าน 2 ล้ม (`SystemModal.test.js` ของงาน 2.2.4 ที่พักไว้ ไฟล์นี้ import แค่ `apiClient`, `constants`, `SystemModal`, `UserMenu` ซึ่งไม่ได้ถูกแก้ในงานนี้; ยังไม่ได้พิสูจน์ด้วยการรันบน HEAD) · eslint ของไฟล์ที่แก้ผ่าน
- **ยังไม่ได้:** ทดลองครบรอบจริงบนเครื่อง (ต้องมีตัวเปิดเดโมแบบ "LDD publication" ที่มี prepare worker ตามข้อ 4.5) · วัดความเร็วการวาดแผนที่

## 7. เรื่องที่ต้องตัดสินใจ
**ผู้ใช้อนุมัติ "ตามที่เสนอ" เมื่อ 8 พ.ย. 2569:** ข้อ 1-3 อนุมัติแล้ว · ข้อ 4 อนุมัติในหลักการ แต่จะขอยืนยันอีกครั้งก่อนแก้ไฟล์ runner จริง (ตามกฎเดิมของ `gee_dashboard_local.py`) · การ apply Migration 052 ยังต้องขออนุมัติแยกตามขั้นตอนเดิม
1. อนุมัติแนวทาง B (ปัดพิกัด 6 ตำแหน่ง ไม่ลดรูป) และการแยก geometry ออกจาก bundle
2. Migration 052 เป็นไฟล์เดียว (prepare + publication v2) หรือแยกสองไฟล์ → **ไฟล์เดียว**
3. ขอบเขต W5: จังหวัดเล็กเป็นเป้าหลัก และปทุมธานีเป็นเป้าเสริม
4. อนุญาตให้แก้ runner ของเดโม (`ldd_prepare_local.py`, `gee_dashboard_local.py`) เพื่อรับ ledger 52 เมื่อถึงขั้นนั้น
