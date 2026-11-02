# GIS Data Management — Local Demo

อัปเดต 1 พฤศจิกายน 2026 · ใช้ Local Sandbox เดิมบนเครื่องนี้เท่านั้น · ไม่ใช่ Production

## เปิดระบบ

เปิด Docker Desktop แล้วเปิด PowerShell ที่ Repository:

```powershell
Set-Location 'C:\Users\chaya\Green-Area-Analysis-Thailand'
$gisRuntime = 'C:\Users\chaya\.codex\visualizations\2026\10\04\01a107d9-ff44-7731-8bc3-91814ffd8d51\t0-local-supabase-20261027-v2'
.\green-area-backend\.venv\Scripts\python.exe -I -B dev/gis_ui/phase5_demo.py core-start --runtime-dir $gisRuntime
.\green-area-backend\.venv\Scripts\python.exe -I -B dev/gis_ui/phase5_demo.py start --runtime-dir $gisRuntime
```

กรอกรหัสผ่านชั่วคราว 12–72 ตัวอักษรใน Terminal ระบบซ่อนการพิมพ์และไม่บันทึกหรือแสดงรหัสผ่าน Console จะแสดงเฉพาะชื่อบัญชี Local จำลองสำหรับ Admin/Officer/Normal ใช้รหัสที่เพิ่งกรอกเข้าสู่ระบบ ห้ามนำรหัส Production มาใช้

คำสั่งเดียวเริ่ม FastAPI `127.0.0.1:55422`, React/Vite `127.0.0.1:3000` และ Linux Workers เดิมสี่ชนิด: Native V2 / LDD / GeoTIFF / Offline Processing ทุกตัวใช้ Target Guard, Image/Resources/Mount Policy และ Worker JWT เดิม Queue ประมวลผลพร้อมกันหนึ่งงาน ไม่โหลด `.env`, ไม่รัน Migration และไม่เรียก Cloud

เปิด **http://127.0.0.1:3000/?view=gis** ถ้าเปลี่ยนเครื่องหรือไม่มี Local Sandbox/Fixtures เดิม ให้เตรียมตามงาน Local Environment ก่อน ไม่ใช้คำสั่ง Migration หรือ Supabase Cloud มาทดแทน

### Dashboard เดิมและ GIS ในเดโมเดียวกัน

ตัวเปิดเดโมเชื่อม Router เดิมแบบอ่านอย่างเดียวจาก Local Supabase: โปรไฟล์, Cache, Ranking, Compare, Timelapse, Context, District Summary, Cooling, Timeseries และพื้นที่ที่บันทึกของเจ้าของ ใช้ “กลับแผนที่” หรือเมนูผู้ใช้ “จัดการข้อมูล GIS” สลับหน้าได้ โดยรักษาลิงก์จังหวัด/อำเภอเดิม

หัว Dashboard แสดง **Local Demo · อ่าน Cache ในเครื่อง · Live GEE ยังปิดอยู่** ข้อมูล Cache ว่างจะยังว่าง ไม่มีการเติมตัวเลขจำลอง งาน NDVI/LST สด, จุดแนะนำ, Raster จาก GEE และการวิเคราะห์พื้นที่สดตอบ `503 LOCAL_GEE_BLOCKED` แทน 404; การแก้บัญชี/ลบ Cache/เขียนข้อมูล Legacy ตอบ `503 LOCAL_READ_ONLY` ไม่เปลี่ยน Auth หรือ API ของ Deployment ปกติ

แผนที่ฐาน/ภาพถ่ายภายนอกยังเป็นแหล่งเดิม จึงต้องมีเครือข่ายของบริการนั้น การทดสอบที่ปิดเครือข่ายภายนอกยืนยันได้เฉพาะขอบเขตและการเลือกพื้นที่จากไฟล์ Local ไม่ใช่การโหลด Basemap/GEE จริง

ผล Local Integration รอบนี้: Browser 85/85 (ล็อกอินจริงด้วยบัญชีจำลองใหม่, ไม่ดัก Request เพื่อข้าม CORS), Auth/Admin-write/Active-pointer checks 10/10, Unit/Startup 28, Legacy Auth/Mount Regression 14, Frontend 67 และ Build ผ่าน ผู้ตรวจอิสระไม่พบ High/Critical ในการเปลี่ยนแปลงนี้ ไม่ได้ใช้รหัสผ่านจริงของผู้ใช้

Legacy Data/Cache/โปรไฟล์เดิมและ Migration Ledger ทั้งสองฐานตรงก่อน–หลังทดสอบ ฉบับใหม่ไม่ถูก Activate; งาน NDVI/LST/จุดแนะนำสดยัง Blocked ตามขอบเขต ไม่ได้พิสูจน์กราฟ Legacy ที่มีค่าจริงเพราะ Cache หลักว่าง หลักฐานใหม่อยู่ `local-integration-20261101/` และ `phase5/1c45d5b4f5/` ภายใต้ `$gisRuntime` ส่วนหลักฐาน Phase 5 เดิมด้านล่างเก็บไว้ตามรอบทดสอบเดิม ไม่ได้เขียนทับ

## ลำดับสาธิตประมาณ 5–10 นาที

1. เข้าด้วย **Officer** เปิดหน้า GIS; **Admin** มีส่วนจัดการเจ้าหน้าที่เพิ่ม; **Normal** ต้องถูกปฏิเสธ ตัวเปิด Demo ให้สิทธิ์เฉพาะบัญชีใหม่ที่สร้างในรอบนี้ ไม่แก้บัญชีเดิม
2. สร้าง Dataset จังหวัด **Bangkok Metropolis**, ปี **ค.ศ.** ที่ยังไม่มี Key นั้น เลือก Shapefile LDD รายปี หากมี Dataset Key เดิมแล้วให้เลือกจากรายการหรือเปลี่ยนปี ไม่ใช่เปลี่ยนชื่ออย่างเดียว
3. อัปโหลด `green-area-backend\gis_worker\fixtures\ldd_valid.zip` เลือก EPSG:32647 และ Encoding `auto` ตรวจทานแล้วจึงยืนยัน ไฟล์นี้เป็นข้อมูลจำลองในรูปแบบ Shapefile จริง ไม่ใช่ข้อมูล LDD ทางการ
4. เปิด “ข้อมูลไฟล์ต้นฉบับ” ดู SHA256/ขนาด แล้วกด **ส่งตรวจสอบ** ดูสถานะ Job/Attempts/รายงาน โดยใช้ปุ่มรีเฟรชตามต้องการ การตรวจผ่านไม่เปิดใช้ฉบับอัตโนมัติ
5. สร้าง Dataset **GeoTIFF NDVI** แล้วอัปโหลด `$gisRuntime\phase4\fixtures\ndvi_valid.tif` เลือก `ndvi_ready` / EPSG:32647 ส่งตรวจและดู Bands/Resolution/NoData/Units/Scale/Mean
6. ถ้าสาธิต LST ให้สร้าง Dataset GeoTIFF LST แล้วเลือก `lst_celsius_valid.tif` / `lst_celsius_ready` หรือ `lst_kelvin_valid.tif` / `lst_kelvin_ready` ในโฟลเดอร์เดียวกัน รายงาน Kelvin แปลงเป็น Celsius เพียงครั้งเดียว ต้นฉบับไม่ถูกแก้
7. ใน **ประมวลผล NDVI/LST** เลือกดัชนี จังหวัด/อำเภอ ปี/เดือน และชุด `standard` ยืนยันแล้วดู Candidate/Attempts/History ต้องมีป้าย **Offline Synthetic** ชัดเจน ตัวเลขจากพิกเซลจำลอง ไม่ใช่ค่าดาวเทียมจริงของพื้นที่/ปีนั้น
8. ใช้ชุด `no_data` เพื่อแสดง Failed Report: ไม่มี Candidate และไม่มีการแทนค่าที่ไม่มีข้อมูลด้วย 0 งาน Invalid Data ไม่เปิด Retry; Transient Retry/Recovery ใช้ตามงบและสิทธิ์เดิม
9. ชี้ให้เห็นว่าไม่มี Auto-activation/Publish/Cache Swap และ Gate สำหรับเปิดใช้ยังปิดอยู่ ห้ามเปิด Gate เพื่อสาธิต

GeoTIFF ที่รับในรอบนี้: Classic TIFF, Single-band Float32/64, Tag `GIS_PROFILE` และ Band Name/Units ตรงกับ Profile, Scale 1 / Offset 0, Explicit finite NoData ไม่เกิน 20 MiB ไม่รองรับ Raw DN Calibration/Multiband/BigTIFF รายงานผ่านคือการตรวจไฟล์ ไม่ใช่การผูกเข้ากับ Legacy Analysis

## ปิดระบบโดยเก็บข้อมูล

กด **Ctrl+C** ใน Terminal ตัว Demo เพื่อหยุด API/UI/Workers ที่สร้างในรอบนั้น ไฟล์ต้นฉบับ บัญชีจำลอง งาน/รายงาน และ Volumes คงอยู่ Core Services ยังเปิดอยู่

หากต้องการหยุด Core เดิมด้วย:

```powershell
.\green-area-backend\.venv\Scripts\python.exe -I -B dev/gis_ui/phase5_demo.py core-stop --runtime-dir $gisRuntime
```

เปิดอีกครั้งด้วย `core-start` และ `start` ตามด้านบน จะสร้างบัญชีจำลองชุดใหม่ ไม่ Reset รหัสบัญชีเดิม งานที่ค้างใช้ Lease/Recovery เดิม ห้ามใช้ `down -v`, Volume Delete, Reset หรือ Reapply Migration

ถ้าเริ่มไม่ได้ ตรวจ Branch `feature/gis-data-management`, Docker Desktop, Core Health และ Port 3000/55422 ก่อน อย่าหยุด Process/Container ที่ไม่ทราบเจ้าของ อย่าส่ง `.env`, รหัสผ่าน หรือ Token ในรายงานปัญหา

## ผลตรวจและ Handoff ของ Phase 5

**Phase 5 PASS — GIS Data Management — Local MVP READY FOR DEMO**

ผลทดสอบใหม่จาก `phase5/9389ce9af6/`: Cross-feature Browser Smoke **49 Pass / 0 Fail** ไม่มี HTTP Mock และใช้ Workers เดิมสี่ชนิดพร้อมกัน; Startup Negative Controls **4 Pass**; Read-only SQL/Security/Preservation Audit หลัง Demo **26 Pass**

พิสูจน์จริงผ่าน UI: Login/Normal Denial, Admin Grant/Officer Boundaries, Dataset/Native Edition Creation, Native V2/LDD ZIP/GeoTIFF Validation, SHA256 Metadata, Attempts/Reports, Offline Candidate/History/NoData Failure, Double Submit, Revision Conflict, Invalid-data Retry Denial และ Closed Activation Gate ไม่มีการ Publish หรือเปลี่ยน Active Pointers

คำสั่ง `core-stop` และ `core-start` ใช้งานจริงกับ Container ID เดิมโดยไม่สร้างใหม่หรือแตะ Volumes; ตัว Demo เริ่ม API/UI/Workers จริงและ Cleanup ครบ ไม่มี Error และ Port 3000/55422 กลับมาว่าง Core สี่ตัวกลับมา Healthy และเปิดทิ้งไว้ตามสถานะก่อนเริ่มงาน

ส่วนรับรหัสผ่านของ `start` ใช้ `getpass` และปฏิเสธ Non-interactive Input ก่อนรับรหัส/เชื่อมเป้าหมาย มี Negative Unit Test; การเปิด/ปิด Components ทดสอบจริงผ่าน `smoke` ซึ่งเรียก `Demo.start`/`Demo.close` ชุดเดียวกัน ไม่ได้อ้างว่าใช้รหัสผ่านจริงของผู้ใช้ในการทดสอบ

ไม่มี Blocking Application Bug จึงไม่แก้ Application/Worker Logic, Dependencies, Auth Architecture หรือ SQL Migration เดิม เพิ่มเฉพาะ `dev/gis_ui/phase5_demo.py`, `phase5_smoke.cjs`, `tests/test_phase5_demo.py` และคู่มือฉบับนี้ ไม่สร้างบริการ/Queue ใหม่ ใช้ Local Operator/Worker Launchers และ Policies ที่ผ่านการตรวจเดิม

หลักฐานภายนอก Repository อยู่ `$gisRuntime\phase5\evidence-index.json` พร้อม Source/Artifact SHA256, Lifecycle, Audit และ Browser Results; Passwords/Tokens ไม่อยู่ใน Evidence ใช้ Synthetic Users ใหม่และเก็บข้อมูลเดิมทั้งหมดไว้

Reuse หลักฐาน Phase 4 เฉพาะ Source/Artifact SHA256 ที่ยังตรง: Unit 371, Linux Science 70, Frontend 74, Legacy/Auth 81, Build Exit 0, Browser 33 และ Focused Integration 62 ไม่ได้รันทั้งหมดซ้ำใน Phase 5 เพราะไม่แก้ Application Source/Build Config ไม่รวมตัวเลขเป็นยอด Test ที่ไม่ซ้ำ การ Recovery/Fencing/Retry/Unsafe-file Tests เดิมใช้ตามขอบเขตและข้อจำกัดที่ระบุในหลักฐานเดิม

Branch `feature/gis-data-management`; HEAD `048273f7b69ec6b60ac02f18ddbd1007619bd574`; งาน T0–Phase 5 ยัง Uncommitted ไม่มี Commit/Push/Merge/Deploy ไม่แก้ Application Logic/Migration 000–036 หรือเปิด Activation Gate

งาน Full Scope ที่ยังไม่เสร็จ: LDD Live Activation/Withdrawal/Rollback, Official LDD/Province-scale Capacity, Live GEE Processing, GeoTIFF Integration กับ Legacy Analysis และ Production/Cloud Readiness นอกจากนี้ยังมี Gap เรื่อง Cache ที่ไม่ว่างในฐานเดียวกับ Worker, V1 Python Worker E2E และ Fault Injection โดยตรงบางกรณีของ GeoTIFF Provider

การตัดสินใจถัดไปต้องได้รับอนุมัติแยก: ฟีเจอร์ Full Scope, Activation/Publish, ข้อมูลจริง/Capacity, Cloud/GEE และ Deployment งานรอบนี้หยุดที่ Local Demo โดยไม่ดำเนินการเหล่านั้นอัตโนมัติ
