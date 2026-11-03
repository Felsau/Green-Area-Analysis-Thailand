# A4.1 Handoff — PASS (Local Synthetic Scope)

วันที่ตรวจ: 3 พฤศจิกายน 2026

## ขอบเขตและสถานะ Git

พัฒนาเฉพาะ GeoTIFF Prepare → Trusted Verify → Local Preview สำหรับ
`ndvi_ready`, `lst_celsius_ready`, `lst_kelvin_ready` ต่อจาก A1–A3
ไม่เปิด GeoTIFF Activation/Withdrawal/Rollback หรือ Dashboard Reader
ไม่เรียก GEE/Cloud/Production ไม่เพิ่ม Dependency หรือ Service

Branch `feature/gis-data-management` / HEAD
`4c136b4d550b535e0c1b2032a27bc08187b797d3` ไม่เปลี่ยน
งาน A4.1 ยังไม่ Commit; เก็บ Untracked Evidence เดิม 5 ไฟล์ครบและ Hash ไม่เปลี่ยน
ไม่มี Commit/Push/Merge/PR/Deploy หรือการเปลี่ยน Branch

## สิ่งที่พัฒนา

- Worker แยกจาก FastAPI ใช้ JWT Subject ของ `gis_native_worker`, Queue/Lease/
  Heartbeat/Retry/Recovery/Fencing เดิม; Native Child ไม่มี Credentials
- สร้าง Raster TIFF และ Summary JSON จริงแบบ deterministic; แยก NDVI/LST roles
  ผูก Edition/Input/Validation lineage/Method/SHA/Size/Grid/Units/NoData
- Kelvin แปลง Celsius ครั้งเดียว; กรณี Source NoData=0 ยังรักษา valid 0°C ได้
  โดยเปลี่ยน Output NoData เป็น -9999 พร้อมบันทึก Metadata
- Trusted Verifier แยก Container, Network None, Source/Staging RO ตรวจไฟล์จริง
  และคำนวณจากต้นฉบับใหม่ ก่อน Promote เข้า Immutable Content-addressed Objects
- API Officer/Admin 4 Routes และ UI เตรียม/ตรวจ/Preview PNG สูงสุด 64×64
  ไม่มี Full Raster Array ใน Browser ไม่มี Worker/HTTP Self-certification
- อ่าน Preview ตรวจ Source/Artifact Hash และ Current Lineage อีกครั้ง;
  เมื่อไฟล์หาย/เสียหายซ่อน Summary และ Revoke Certificate แบบคงประวัติ
- รายละเอียด API/Artifact/Spatial/Runtime Contract อยู่ใน `a4-1-contracts.md`

## SQL และ Independent Review

เพิ่ม Forward Migration `041_gis_geotiff_prepare.sql` ใช้กับ Local `postgres`
และ `gis_t1_upgrade` เท่านั้น ทั้งสอง Ledger ตรงกับ Reviewed SHA256:

`882bacfd1af803be3cd08307bfca8c150b10e0c28e8b4a893e57a1dc924db6d1`

เพิ่ม Immutable Requests/Certificates/Revocations แบบ Owner-only FORCE RLS,
Deferred Certificate/Queue Invariants และ RPC ที่แยก Service/Native Worker
เปลี่ยน Legacy Functions เพียง 4 จุดเพื่อแยกชนิด Prepare Job ใหม่
ไม่เปลี่ยน `eligible()`, `publication_ready()` หรือ LDD Publication Transactions
Migration 000–040 และ Ledger แถวเดิมรวม Applied Time ไม่เปลี่ยน
Migration041 ถูก Apply แล้ว ห้ามแก้ย้อนหลัง; หากต้องแก้ให้ใช้ Forward Migration

ผู้ตรวจอิสระ `local_integration_security_review` ตรวจ Exact SQL ก่อน Apply
และตรวจ Source/หลักฐานจริงรอบสุดท้าย: PASS, High/Critical คงค้าง 0
ตรวจ Authority, Filesystem/Byte Verification, Guard, RLS/ACL และ LDD Preservation
Review ไม่ได้ถือว่าการอ่านโค้ดเท่ากับการทดสอบ Runtime

## ผลทดสอบจริง

| ชุดทดสอบ | ผล | หลักฐานและขอบเขต |
|---|---:|---|
| Backend/Local Guard Regression | 623 Pass + 37 Subtests | แยก Environment, Suppress dotenv, ปิด Nonlocal Network; รวม Guard ใหม่ 20 เคส |
| Linux Scientific | 149 Pass | Python 3.11.17, Fiona 1.10.1, GDAL 3.10.3, Shapely 2.2.0; Source/Tests RO, Network None |
| Frontend Focused + Legacy | 89 Pass | 82 + 7 ใน 8 ไฟล์; Config ไม่โหลด Application env |
| Core API/Auth/Queue/Native/Verify | 34/34 Pass | NDVI/Celsius/Kelvin จริง, CAS, Idempotency, Corrupt/Missing Bytes, Authorization, No Publication |
| Browser | 8/8 Pass | Officer → Confirm Prepare → Worker → Verify → PNG Decode; ไม่มี API Mock, Desktop/Mobile Screenshots |
| Queue/Lifecycle/LDD Regression | 37/37 Pass | SIGKILL → Lease หมดจริง → Replacement Attempt 2, Fencing, One Result, Concurrent JWT Claims, Retry, LDD Pipeline |
| Final SQL/Security/Preservation | 24/24 Pass | Both DB Ledgers/RLS/ACL/Old Data/Pointers; Certificate Negative Probes Rollback |
| Frontend Build | Pass | Explicit Local Config, Build Output แยกจาก Repository |

Scientific Tests ตรวจ Metadata/Grid/CRS, ค่า NDVI/Celsius/Kelvin ที่รู้คำตอบ,
NoData/NaN/Inf, Wrong CRS/Transform/Bands/Dtype/Period/Province, Footprint,
Source/Staging Substitution, Missing/Corrupt Bytes และ Pixel Limit

Lifecycle แยกหลักฐานอย่างตรงไปตรงมา:
- ฆ่า Linux Worker จริงด้วย SIGKILL, รอ Lease 60 วินาทีจริง ไม่ Backdate SQL;
  Replacement ประมวลผล Raster 1,000,000 pixels สำเร็จและ Verify จากไฟล์จริง
- JWT สองตัวตน Claim งานเดียวได้หนึ่งตัว; ปฏิเสธ Spoofed Subject/Old Token/
  Legacy Validator Protocol และสิทธิ์ Certify/Admin RPC/Legacy Write
- Heartbeat RPC ขยาย Lease จริง; Retry Backoff/สาม Attempts/Explicit Retry Child
  ถูกทดสอบผ่าน JWT RPC โดย Inject `NATIVE_TIMEOUT` เป็น Fault จำลอง
- Native Period Mismatch ล้มเหลวจริงเป็น Invalid Data ไม่ใช่ Transient
- SIGINT/SIGTERM ขณะ Daemon Idle ออกอย่างเรียบร้อยจริง
- LDD เดิม Upload → Native Validate → Prepare → RO Trusted Verify ผ่านจริง:
  3 Features/6,400 m², Publication Readiness เดิมยังทำงาน, ไม่ Auto-activate

Not Tested รอบ A4.1: Physical Native Timeout/OOM/CPU Burn, Automatic Heartbeat
และ SIGTERM ระหว่างงาน GeoTIFF ยาว; ไม่ถือว่าการ Inject RPC เท่ากับทดสอบกรณีเหล่านี้
ไม่ได้ Rerun A3 Activation/Withdrawal/Rollback Browser ทั้งชุด; Functions เหล่านั้น
ไม่เปลี่ยน และมี Focused LDD Pipeline/Frontend/Preservation Regression รองรับ

Warnings ไม่ขวางผลทดสอบ: Rasterio PendingDeprecation 65 รายการ,
React act warnings ใน GIS Tests เดิม, Build Chunk Size Warning

## Source Binding และ Evidence

Final Code Manifest: 452 ไฟล์, SHA256
`2cfcee04a785c93e05e417acf7b836fe778d709fb6b80ec57baa5662b35fb94e`

Core Manifest 451/451 และ Lifecycle 452/452 ตรงกับ Source ปัจจุบันทุกไฟล์;
รายการเพิ่มเพียง Lifecycle Test Harness ไม่ใช่การเปลี่ยน Application หลังทดสอบ
Manifest ครอบคลุม Backend/Worker/SQL/Local Tools/Frontend/CSS/Fixtures/Tests
แยกจาก Docs และ `.gitattributes`; ไฟล์เหล่านั้นมี Hash ใน Final Evidence Index

Raw Evidence อยู่นอก Repository ใน A4 Local Runtime: `final-evidence-index.json`,
`final-checks.json`, `unit-tests.json`, `linux-science.json/log`, Frontend JSON 2 ชุด,
`integration-cf9b4de95a/results.json`, `browser-results.json`,
`lifecycle-308029678e/results.json` และ `independent-final-review.json`
ไม่มี Credentials หรือ Raw Runtime Logs/Evidence เพิ่มใน Repository

## Files Added/Changed

- SQL/Review: `migrations/041_gis_geotiff_prepare.sql`, `.gitattributes`,
  `dev/gis_local/geotiff-prepare-review.json`
- Backend ใหม่: `gis_geotiff_prepared.py`, `routers/geotiff_prepare.py`,
  `gis_worker/geotiff_prepare_{provider,child,worker}.py`, Tests Native/API 2 ไฟล์
- Backend เดิม: `gis_app.py`, `gis_runtime.py`, `routers/gis.py` ต่อ Capability/
  Closed RPC/Router เท่านั้น ไม่มี Legacy Analysis/Cache Reader เปลี่ยน
- Local Tools: `geotiff_prepare_local.py`, `geotiff_prepare_checks.py`,
  `geotiff_prepare_lifecycle.py`, Guard Tests; ปรับ `manage.py` ด้วย Exact Policy,
  `ldd_prepare_local.py` เพิ่ม Optional Factory โดย Default เดิมไม่เปลี่ยน
- Local UI Demo: `a4_demo.py`, `a4_smoke.cjs`; `legacy_demo.py` ผูก Private Store
- Frontend: `GeoTiffPreparedPreview.js` และ Tests, `GisManagement.js`,
  `gisClient.js` และ Tests; ใช้ Layout/Styles เดิม ไม่มี Dashboard Reader ใหม่
- Docs: `a4-1-contracts.md`, Handoff นี้

## Preservation / Cleanup

ทั้งสองฐาน: Legacy Table Row Counts/Hashes เดิม, Profiles เดิม, Ledger แถวเดิม,
Active Pointers เดิมทั้งหมดไม่เปลี่ยน มี Cache ที่ไม่ว่างก่อนเริ่มตรวจจริง
(`ndvi_annual`/`province_lst_annual` อย่างละ 3 แถวในฐานหลัก และ 1 แถวใน Upgrade)
Saved Areas เดิม 3 แถวในฐานหลักไม่เปลี่ยน ไม่ล้าง Cache
GeoTIFF Upload Editions ยัง Draft/Ineligible/No Active, Broad Gate ยังปิด
API/UI/Worker/Verifier ของการทดลองหยุดครบ; เก็บ Core/Images/Volumes/Test Rows/
Original Files/Artifacts/History เดิมทั้งหมด ไม่แตะ Production/Cloud

## ข้อจำกัดและงานถัดไป

- Synthetic เท่านั้น; พิสูจน์ Actual Prepare/Verify ได้ถึง 1,000,000 pixels
  ไม่ใช่การรับรองขนาดจังหวัดหรือ Throughput; เกิน Cap ถูกปฏิเสธ
- ขอบจังหวัดเป็นข้อมูลประมาณและตรวจ Intersection เท่านั้น ไม่รับรองทั้งจังหวัด
  สถิติคือ Valid Source Pixels ไม่มี Area Weighting/Clip; Footprint รวม NoData Holes
- ปี/เดือนตรวจความสอดคล้องของ Tags แต่ยัง `period_verified=false` เสมอ
- ไม่รองรับ Raw Satellite Bands, Arbitrary Masks, Reprojection หรือ Live GEE
- Soft Disk Accounting ไม่ใช่ Hard Quota; ขนาดใหญ่/Real Data ต้องทดสอบแยก

พร้อมเสนอ A4.2 เพื่ออนุมัติแยก: GeoTIFF Publication/Activation/Rollback และ
Dashboard Reader พร้อม Source Identity/Cache Preservation โดยยังไม่เริ่มในรอบนี้
