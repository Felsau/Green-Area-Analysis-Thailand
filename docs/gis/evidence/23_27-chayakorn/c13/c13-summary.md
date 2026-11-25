# C13 · หน่วยความจำและเวลาของตัวตรวจ LDD จริง (สัปดาห์ที่ 4, 23–27 พ.ย. 2569)

จัดทำ 24/11/2569 โดยชยากร · **ข้อมูลจริง (ZIP จาก `<ldd-77>`) · รันในเครื่อง Windows (local) · ไม่ได้แก้โค้ด ไม่ commit**

## วิธี
- เรียก `gis_worker.ldd_provider.assess(request, storage_root=<c13-work>\store, collect=True)` ของ `<clone-c6>` (โค้ดเท่ากับ 7501cc8)
  ด้วย venv ของ C6 (Python 3.11.9 · fiona 1.10.1 · rasterio 1.4.4 · shapely 2.2.0)
  - **venv ไม่มี psutil จึงติดตั้ง psutil 7.2.2 อย่างเดียว** (`pip install psutil` ใน `<clone-c6>\green-area-backend\.venv` ซึ่ง git ไม่ติดตาม)
- request ตรงรูปแบบ `check_request`:
  - manifest: crs จาก .prj ตามบรรทัด 436–448 · encoding `auto` (ทั้ง 4 จังหวัดมี .cpg UTF-8) · data_year เป็น ค.ศ. ตามปีข้อมูล
  - ZIP ใช้ hardlink ชื่อ `<sha256>.zip` ตามที่ `_source_bytes` เปิด
- ยกเพดาน 5 ตัวเฉพาะในโปรเซสของสคริปต์ (ตั้งค่า attribute ของโมดูล ไม่ได้แก้ไฟล์):
  - MAX_EXPANDED_BYTES, MAX_MEMBER_BYTES, MAX_FEATURES, MAX_COORDINATES = 4 GiB
  - **MAX_ZIP_BYTES = ขนาด ZIP ของจังหวัดนั้นพอดี** เพราะ `_source_bytes` เรียก `stream.read(MAX_ZIP_BYTES + 1)` ซึ่ง Python จองบัฟเฟอร์เท่าค่านี้ไว้ก่อน (ดูหัวข้อรอบแรก)
  - ไม่มีจังหวัดใดติดเพดานอื่น ทั้งจำนวนไฟล์ใน ZIP ≤ 64 และอัตราบีบอัด ≤ 100 ผ่านหมด
- `ldd_provider._coordinates` ถูกห่อเพื่อนับผลรวมที่ตัวตรวจนับเองเท่านั้น (เรียกฟังก์ชันเดิมด้วยอาร์กิวเมนต์เดิม)
- ขั้น prepare: `ldd_prepare_provider.build(... method_version='ldd-geometry-area-v2')` เรียกได้โดยไม่ต้องเปิดระบบ วัดแยกอีกโปรเซส
  - build เรียก `assess` ซ้ำในตัว แล้วสร้างไฟล์ต่อเมื่อผลตรวจ valid เท่านั้น (บรรทัด 80–82)
- หนึ่งขั้นต่อหนึ่งโปรเซส · ค่าที่จดเป็นของโปรเซสที่ทำงานจริง วัดด้วย psutil ตอนจบ: peak_wset, peak_pagefile, cpu user+system และเวลาจริงของงาน
  - ตัวแม่สุ่มดู working set ของทั้งโปรเซสและโปรเซสลูกทุก 0.1 วินาที และจะหยุดถ้าเกินครึ่งหนึ่งของ RAM (15.43 GB จาก 30.86 GB) · ไม่มีโปรเซสใดถูกหยุด

## ผล (c13-memory.csv)
| จังหวัด | ZIP (MiB) | แปลง | จุด | ขั้น | ผล | peak wset (MiB) | peak pagefile (MiB) | CPU (s) | เวลาจริง (s) |
|---|---|---|---|---|---|---|---|---|---|
| กรุงเทพฯ | 5.26 | 11,073 | 315,943 | assess | **valid** | 172.4 | 497.4 | 3.31 | 3.33 |
| | | | | prepare | **สร้างได้** · geometry 9,738,680 B · summary 6,056 B | 203.0 | 527.4 | 11.47 | 11.41 |
| หนองบัวลำภู | 27.97 | 50,121 | 2,553,311 | assess | ไม่ valid: OUTSIDE_PROVINCE 459 · BOUNDARY_OUTSIDE_REVIEW_REQUIRED 94 · UNKNOWN_CODE_REVIEW_REQUIRED 39 · BOUNDARY_OUTSIDE_AREA_REVIEW_REQUIRED 1 | 622.3 | 949.1 | 15.53 | 15.55 |
| | | | | prepare | หยุดที่ OUTSIDE_PROVINCE (ประตู valid) | 623.0 | 949.9 | 15.41 | 15.47 |
| นครราชสีมา | 122.18 | 153,319 | 11,404,194 | assess | ไม่ valid: OUTSIDE_PROVINCE 738 · UNKNOWN_CODE_REVIEW_REQUIRED 246 · BOUNDARY_OUTSIDE_REVIEW_REQUIRED 237 | 2,226.7 | 2,556.5 | 55.83 | 56.18 |
| | | | | prepare | หยุดที่ OUTSIDE_PROVINCE | 2,226.2 | 2,556.1 | 56.62 | 56.71 |
| เชียงใหม่ | 117.66 | 162,832 | 11,097,284 | assess | ไม่ valid: OUTSIDE_PROVINCE 2,498 · UNKNOWN_CODE_REVIEW_REQUIRED 179 · BOUNDARY_OUTSIDE_REVIEW_REQUIRED 154 · BOUNDARY_OUTSIDE_AREA_REVIEW_REQUIRED 1 | 2,359.1 | 2,695.2 | 68.88 | 69.57 |
| | | | | prepare | หยุดที่ OUTSIDE_PROVINCE | 2,356.8 | 2,693.1 | 67.56 | 67.76 |

- **prepare วัดได้จริงแค่กรุงเทพฯ:** อีก 3 จังหวัดหยุดที่ประตู valid ก่อนเริ่มสร้างไฟล์ ตัวเลขจึงเท่ากับ assess อีกรอบ ไม่ใช่ภาระของการสร้างไฟล์
- กรุงเทพฯใช้เส้น `ldd-package` ส่วนอีก 3 จังหวัดใช้ `gadm-approx` ของไฟล์เส้นเขตในระบบ (sha `1b6cf62b…`) ไม่ใช่ไฟล์ของ C7
- จำนวนจุดของกรุงเทพฯ หนองบัวลำภู และนครราชสีมาตรงกับที่ C8 นับไว้

## เทียบกับเพดานของ child บนเซิร์ฟเวอร์ (`ldd_child.py` บรรทัด 15–16 · `ldd_prepare_child.py` บรรทัด 13–14)
| จังหวัด · ขั้น | wset ÷ 512 MiB | pagefile ÷ 512 MiB | CPU ÷ 20 วินาที |
|---|---|---|---|
| กรุงเทพฯ assess | 0.34 | 0.97 | 0.17 |
| กรุงเทพฯ prepare | 0.40 | **1.03** | 0.57 |
| หนองบัวลำภู assess | **1.22** | **1.85** | 0.78 |
| นครราชสีมา assess | **4.35** | **4.99** | **2.79** |
| เชียงใหม่ assess | **4.61** | **5.26** | **3.44** |

- **RLIMIT_AS 512 MiB:**
  - ค่าบน Windows เป็นหน่วยความจำที่ใช้จริง (working set) และหน่วยความจำที่จองแล้ว (pagefile/commit) ไม่ใช่ address space แบบที่ RLIMIT_AS บน Linux นับ
  - address space บน Linux รวมพื้นที่ที่จองไว้แต่ยังไม่ได้ใช้ และไลบรารีที่โหลด จึงมักสูงกว่า ตัวเลขนี้จึงต่ำกว่าที่เซิร์ฟเวอร์จะนับ
  - แม้ใช้ค่าที่ต่ำกว่านี้ หนองบัวลำภูก็เกินแล้ว และนครราชสีมากับเชียงใหม่เกินมากกว่า 4 เท่า
  - กรุงเทพฯ prepare มี pagefile 527.4 MiB เกิน 512 MiB เล็กน้อย แต่ยังไม่ได้ลองบน Linux จึงยังไม่รู้ว่าจะผ่านจริงหรือไม่
- **RLIMIT_CPU 20 วินาที:**
  - กรุงเทพฯ (3.3 / 11.5 วินาที) และหนองบัวลำภู (15.5 วินาที) ต่ำกว่า 20 วินาที ส่วนนครราชสีมา (55.8) และเชียงใหม่ (68.9) เกิน
  - เครื่องนี้ (Ryzen 5 5600H) กับเซิร์ฟเวอร์ความเร็วไม่เท่ากัน ตัวเลขนี้จึงใช้เทียบกันเองได้ ไม่ใช่เวลาบนเซิร์ฟเวอร์
  - เวลา CPU รวมเวลาเริ่ม Python และ import ราว 1 วินาที

## รอบแรก (ไม่ใช้ตัวเลข · เก็บไว้ใน `<c13-work>\run_c13_first.out`)
- ตั้ง MAX_ZIP_BYTES = 4 GiB ทำให้ทุกโปรเซสมี pagefile ราว 4,116 MiB และ wset ≥ 2,074 MiB แม้แต่กรุงเทพฯ
  - สาเหตุคือบัฟเฟอร์ของ `read(MAX_ZIP_BYTES + 1)` ไม่ใช่ภาระของข้อมูล
- ตัวแม่เฝ้าแค่ `python.exe` ของ venv ซึ่งบน Windows เป็นตัวเปิดที่สร้างโปรเซสลูกอีกตัว (เห็นแค่ 4.2 MiB) จึงไม่ได้เฝ้าโปรเซสที่ทำงานจริง
- แก้แล้วทั้งสองข้อและรันใหม่ทั้งหมด ผลตรวจ (ผ่าน/ไม่ผ่าน และรหัสข้อผิดพลาด) ของสองรอบเหมือนกัน

## ยังไม่ได้ตรวจ
- ไม่ได้รันใน container Linux ที่มี RLIMIT จริง จึงยังไม่รู้ว่าแต่ละจังหวัดจะหยุดด้วย NATIVE_MEMORY_LIMIT หรือหมดเวลา CPU ที่จุดไหน
- ภาระของการสร้างไฟล์ (`_build_v2`) วัดได้แค่กรุงเทพฯ อีก 3 จังหวัดไม่ผ่านขั้นตรวจ
- วัดแค่ครั้งเดียวต่อขั้น ไม่ได้วัดซ้ำหาค่าแปรปรวน

## ไฟล์ใน `docs/gis/evidence/23_27-chayakorn/c13/`
`c13_memory.py` · `c13-results.json` · `c13-memory.csv` · `c13-run.log` · `c13-summary.md`
