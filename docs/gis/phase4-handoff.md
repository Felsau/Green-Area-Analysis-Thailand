# Phase 4 — GeoTIFF Upload & Validation

วันที่ 30 ตุลาคม 2026 · Implementation COMPLETE เฉพาะ Local/Test MVP · รอ Final Acceptance

## เป้าหมายและสิ่งที่พัฒนา

GIS Officer/Admin อัปโหลด GeoTIFF ผ่านหน้า GIS เดิม จัดเก็บต้นฉบับแบบ Immutable พร้อม SHA256 แล้วสั่งตรวจผ่าน PostgreSQL Queue และ Linux Worker จริง ดูรายงานจาก API/UI ได้ โดยไม่เปิดใช้ผล ไม่ Publish ไม่เปลี่ยน Cache และไม่เชื่อม GEE/Cloud/Production

ใช้ SQL Migration เดิม ไม่เพิ่ม Prisma, Dependency, Storage Service หรือ Queue Infrastructure ใหม่ งานนี้เป็น **การตรวจไฟล์** ไม่ใช่การนำ GeoTIFF ไปคำนวณ NDVI/LST ผ่าน Pipeline GEE หรือการรับรองความถูกต้องของข้อมูลดาวเทียม

## Scientific Contract ที่รองรับ

| Profile | Band / Units ในไฟล์ | ค่าที่ยอมรับ | หน่วยรายงาน |
|---|---|---|---|
| `ndvi_ready` | `NDVI` / `unitless` | -1 ถึง 1 | unitless |
| `lst_celsius_ready` | `LST` / `celsius` | -100 ถึง 100 | Celsius |
| `lst_kelvin_ready` | `LST` / `kelvin` | 173.15 ถึง 373.15 | Celsius โดยลบ 273.15 หนึ่งครั้ง |

- Classic TIFF แบบ Single Band, Float32/Float64; ต้องมี Tag `GIS_PROFILE`, Band Description และ Band Units ตรงกับ Profile ที่ผู้ใช้เลือก
- ต้องเป็น Scale 1 / Offset 0 เท่านั้น ปฏิเสธ Raw DN, Integer Raster และการ Scale ซ้ำ ไม่เดา Calibration หรือหน่วยจากช่วงตัวเลข
- CRS: EPSG:32647 / 32648 / 4326; North-up, ไม่มี Rotation; Resolution 0.01–1000 m หรือ 0.000001–1 degree ตาม CRS
- Explicit finite NoData นอกช่วงค่าของ Profile และค่าสัมบูรณ์ไม่เกิน 1e30; ปฏิเสธ NaN/Infinity และ Raster ที่ไม่มี Valid Pixels
- ขนาดไฟล์ไม่เกิน 20 MiB; Disk Quota แยก GeoTIFF 256 MiB; Width/Height ไม่เกิน 16,384 และรวมไม่เกิน 16 ล้านพิกเซล
- อ่านเป็น Window ไม่เกิน 256×256; Parent Wall Limit 25 s, Child Address Space 512 MiB / CPU 20 s / Output 16 KiB; Container Non-root, Read-only, CPU 1 / Memory 1 GiB / PIDs 64
- ใช้ GTiff Driver และ MemoryFile หลังตรวจ Bytes/Hash; ปิด Sidecars/PROJ Network, ปฏิเสธ External References ใน Metadata และจำกัด Metadata/Namespaces
- ยังไม่รองรับ BigTIFF, Overviews, Internal Masks/Alpha นอกเหนือ NoData, Multiband, Raw-DN Calibration, Reprojection หรือการยืนยันขอบเขตจังหวัดและปีจากเนื้อหาไฟล์

## Storage / API / Database / Worker

- Reuse `LocalLddStore` ผ่าน Hooks เล็กสำหรับชื่อ Storage/Owner Scope/Migration/นามสกุล/Preflight โดยพฤติกรรม LDD เดิมคงเดิม
- `LocalGeoTiffStore` แยก Owner Marker และ Objects/Stages ภายนอก Repository, ชื่อไฟล์มาจาก SHA256 เท่านั้น; Lock/Quota/Timeout/Atomic No-overwrite เดิม ไม่มี Public Download Route
- API ใหม่ `POST /gis/datasets/{id}/geotiff-uploads` และ `GET /gis/geotiff-uploads/{id}`; Auth/Dataset/Profile/Revision ตรวจทั้งก่อนรับ Bytes และตอน Commit
- ใช้สิทธิ์ GIS Officer/Admin สำหรับ Catalogue ร่วมตาม Contracts เดิม ไม่เพิ่ม ACL ส่วนตัวต่อ Uploader หรือขอบเขตสิทธิ์รายจังหวัด
- ใช้ `/editions/{id}/validation-jobs`, `/jobs`, Attempts/Result/Retry/History เดิม ไม่มี API รับ Path/URL/Command/SQL
- Migration 036 เพิ่ม Immutable Forced-RLS `gis.geotiff_uploads`, Manifest V4, `geotiff` Queue Protocol และ RPC สี่ตัว โดย Reuse Jobs/Attempts/Results/Audit/Receipts และ Lock/Lease/Heartbeat/Retry/Recovery/Fencing เดิม
- Worker รับเฉพาะ Native Worker JWT ผูก Trusted Subject; ไม่รับ Worker ID จาก Payload เป็น Authority และไม่มี Direct Table/Legacy Write Permissions
- Report ผูก Upload ID, Artifact SHA/Size, Input Revision/Hash, CRS/Profile/Units/Scientific Invariants; Deferred Constraints ปิดทางสำเร็จผ่าน Legacy Protocol
- Validation สำเร็จเก็บ Result Provider `local_geotiff` แต่ Edition ยังคง Draft, `validated_result_id=NULL`, Eligible=false และไม่มี Active Pointer/Cache DML แม้ Gate อื่นเปิดในอนาคต
- UI เพิ่ม File/Profile/CRS, Confirmation/Double-submit Guard, สถานะส่งไฟล์แบบ Indeterminate และรายงาน Metadata/Valid Pixels/Min/Mean/Max พร้อม Local/Test และ Validation-only Labels

## Migration / Independent Review

`036_gis_geotiff_upload.sql` SHA256:

`acd1f28d50e6db4e861424049037785143b2f2e2cfacf4e7131949814ed75df7`

Independent Reviewer ตรวจ Exact SQL/ACL/RLS/Security Definer/Deferred Invariants ก่อน Apply ทั้งสองฐาน Local ที่ Attest แล้ว ไม่มี High/Critical ค้าง Native Review ตรวจ File/Driver/Child/Hash/Metadata/Resource Boundary และแก้ NoData ที่เกินขอบเขต SQL พร้อม Negative Test แล้ว

ครั้งแรก Syntax Error 42601 จาก `IS DISTINCT FROM CASE` สามจุด ทำให้ Transaction Rollback ทั้งหมด ตรวจจริงยืนยันทั้งสองฐานไม่มี Ledger/Table 036 ก่อนแก้เฉพาะวงเล็บสามคู่และ Review SHA ใหม่ จากนั้น Apply สำเร็จ ไม่แก้ Migration ที่ Apply สำเร็จแล้วหรือ Ledger ย้อนหลัง

Read-only Audit ตรวจ 26 ข้อ: Ledger รวม Timestamp เดิม, SHA 000–036, Forced RLS/FK/Dedup, Exact Grants สี่ RPC, Function Bodies 20 ตัวและ Trusted JWT Function จาก 032, Worker Table Permissions และข้อมูล Public/Profile เดิม

## ผลทดสอบและหลักฐาน

หลักฐานภายนอก Repository ใต้ `t0-local-supabase-20261027-v2/phase4/` และ `phase4-browser/` พร้อม `phase4/evidence-index.json` เมื่อปิดงาน

| ชุดทดสอบ | ผลล่าสุด |
|---|---|
| API/Storage/Target Guard/Worker/Processing Regression | 371 Passed |
| Linux GeoTIFF Science | 70 Passed; Python 3.11.17 / Rasterio 1.4.4 / GDAL 3.10.3 / NumPy 2.4.6 |
| Frontend GIS/Auth/Client/App/Dashboard | 74 Passed |
| Legacy/Auth/Health/Mount Regression | 81 Passed |
| Frontend Build | Exit 0; GIS Disabled และไม่โหลด .env |
| Local SQL Audit | 26 Passed หลัง Browser Cleanup; Ledger/Functions/RLS/Privileges/Legacy Preservation ทั้งสองฐาน |
| Actual Upload/Queue/Linux Worker Integration | รอบแรก 34 Pass / 1 Test Harness Fail; Focused รอบสุดท้าย `cde72f4ea477` 62 Pass / 0 Fail / 1 Not Tested |
| Actual Browser E2E | รอบสุดท้าย `46c6bd5498` 33 Pass / 0 Fail; UI/Auth/API/Storage/Queue/Linux Worker จริง ไม่มี HTTP Mock |

Fixtures เป็น **GeoTIFF จริงที่สร้างจากพิกเซลจำลอง** 13 กรณี แยกจากข้อมูล GIS จริงและ Original Native Fixtures เดิม: NDVI Mean 0, LST Celsius Mean 30, LST Kelvin Mean ประมาณ 30 (Tolerance 2e-5), Wrong CRS/Bands/Units/Scale, Raw DN, NaN, NoData, Missing Profile และ Corrupt TIFF

Unit รอบแรกมี Import Error ในตัวช่วย และ Expected Status ของ Empty File ผิด (ระบบปฏิเสธ 413 ตาม Size Guard); แก้เฉพาะ Test Harness/Expectation แล้ว 371 ผ่าน Frontend Unit แก้การส่งฟอร์ม File ของ jsdom โดยแยกจาก Browser E2E จริง ไม่แก้ Guard ให้ผ่าน Test

Integration รอบแรก `3e15370a577f` ผ่าน Security/Concurrent Claim/Heartbeat/Recovery/Fencing แล้ว แต่ตัวทดสอบอ่าน Result Envelope ผิดชั้น (`result.report`) จึงแก้เฉพาะ Helper และทดสอบ Science/Compatibility ส่วนที่เหลือใหม่ หลักฐานยืนยัน App/SQL/Native Sources อื่นไม่เปลี่ยนทั้งหมด จึงไม่รอ Lease 60 s ซ้ำโดยไม่มีเหตุผล จำนวนผลต่างรอบมีกรณีซ้ำ ห้ามบวกเป็นยอด Test ที่ไม่ซ้ำ

ช่วงส่งต่องานมี Focused Run ที่ไม่ได้บันทึก Final Report ครบ ตรวจจริงพบไม่มี Container/Process หรืองานค้าง ก่อน Root รัน Focused รอบสุดท้ายใหม่โดยเก็บข้อมูลเดิมไว้ ไม่อ้างผลของรอบที่ไม่มีหลักฐานครบ

Browser รอบ `02f2421bbf` และ `bc093eb61b` ติดข้อจำกัด Chromium Inspector ที่ไม่เก็บ POST Response Body หลัง Refresh (รอบหลังไม่มี Browser Results ครบ) แก้เฉพาะตัวทดสอบให้ตรวจ ID/SHA/Metadata จาก GET API จริงหลังคำสั่ง UI และจัดการ Promise/Cleanup ให้บันทึกผลครบ ไม่เปลี่ยน Source แอปหรือใช้ Mock Response รอบสุดท้ายผ่านทั้ง NDVI, LST Kelvin และ Invalid Range พร้อม Double Submit/No Activation/Desktop/Tablet

การทดลอง Recovery ใช้ Least-Privilege RPC Claim/Heartbeat แล้วรอ Lease หมดอายุตามเวลาจริง ก่อนให้ Replacement Linux Worker Recover/ตรวจจริง และทดสอบ Token เก่าถูกปฏิเสธ **ไม่ใช่การทดสอบ SIGKILL ของ Provider GeoTIFF ใหม่** ส่วน Lifecycle/Timeout/Memory ของ Common Worker ใช้หลักฐาน T3 เท่าที่ Source ตรงกัน

## ข้อจำกัดและสถานะข้อมูลเดิม

- ไม่ได้ทดสอบ GeoTIFF ข้อมูลดาวเทียมจริง/ไฟล์จังหวัดขนาดใหญ่ หรือรับรอง Capacity ถึงขีดจำกัดทุกค่าที่ตั้งไว้
- ไม่เปิด Activation Gate, Publish, Cache Swap, GEE Ingestion หรือ Cloud Resources
- ค่า Province/Year มาจาก Dataset ที่ผู้ใช้ระบุ ไม่ได้พิสูจน์จากพิกเซล/ขอบเขตจังหวัด; Report/UI ระบุข้อจำกัดนี้
- V1 Actual Worker E2E ต้องแยกจาก Compatibility จาก SQL/Unit เพราะ Python Native Worker เดิมไม่ได้รองรับ V1
- V2, LDD และ Offline Processing ผ่าน Actual Worker หลัง 036; GeoTIFF Claim ไม่รับงานเหล่านั้น และ Worker เก่าไม่รับ GeoTIFF
- Main Worker DB มี Legacy NDVI/LST Cache 0/0 แถว ส่วน Upgrade DB มี 1/1 แถว Hash คงเดิม จึงไม่อ้างว่าพิสูจน์ Failure Preservation ของ Cache ที่ไม่ว่างในฐานเดียวกับ Worker แล้ว ไม่มี Cache DML/Privileges จากเส้นทางใหม่
- ข้อมูลเดิม/Volumes ไม่ถูกลบ; เก็บ Test Users, Synthetic Rows และ Immutable Originals ใหม่ไว้ Container ชั่วคราวหยุด/นำออกเฉพาะที่ตรวจ Ownership ได้

## ไฟล์ / Git / ขั้นถัดไป

เพิ่ม `gis_geotiff_storage.py`, `gis_worker/geotiff_provider.py`, `geotiff_child.py`, `geotiff_worker.py`, Migration 036, API/Native/Target Guard Tests และ `dev/gis_ui/phase4_*` สำหรับ Local Operator/Fixtures/Integration/Browser/Audit พร้อมเอกสารฉบับนี้

แก้เฉพาะส่วนที่เกี่ยวข้องใน `gis_ldd_storage.py`, `gis_app.py`, `gis_runtime.py`, `gis_schemas.py`, `gis_service.py`, `routers/gis.py`, `dev/gis_local/manage.py`, `GisManagement.js`, `gisClient.js` และ Tests คู่กัน ไม่มี Dependency/Legacy Analysis/Cache Changes

Branch `feature/gis-data-management`; HEAD `048273f7b69ec6b60ac02f18ddbd1007619bd574`; งาน T0–Phase 4 ยังไม่ Commit และรักษางานเดิมทั้งหมด ไม่มี Checkout/Reset/Stash/Clean/Commit/Push/Merge/PR/Deploy

Integration/Browser/Preservation ผ่านตามขอบเขตข้างต้น ไม่มี High/Critical ค้างจาก Independent Review รอ **Final Acceptance Review** ก่อนประกาศปิด Phase 4; **ยังไม่อนุมัติเริ่ม Phase 5**
