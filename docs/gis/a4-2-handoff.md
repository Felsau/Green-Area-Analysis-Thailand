# A4.2 Handoff — PASS / Local Synthetic Scope

งาน 3–4 พฤศจิกายน 2026; Local Synthetic เท่านั้น

## เป้าหมายและสถานะ

A4.2 CLOSED เฉพาะ Local Synthetic Scope หลัง Implementation, Runtime Tests
และ Independent Final Acceptance; ยังไม่เริ่ม A5/A6 หรือ Production

เพิ่ม Admin-only GeoTIFF activation/replacement/withdrawal/rollback และ Published
NDVI/LST Raster บน Dashboard โดยใช้ Catalog/Active Pointer/Storage/Native Runtime
เดิม แยกจาก Legacy GEE ไม่เปิด Broad Gate ไม่เปลี่ยนสูตรวิเคราะห์/Cache เดิม
รายละเอียด Contracts/API/Policy อยู่ใน `a4-2-contracts.md`

Branch `feature/gis-data-management`, HEAD ก่อนและระหว่างงาน
`07c4fc84b3f736154430afc2cc71339c0ed15d26`
งาน A4.2 ยังไม่ Commit ไม่มี Push/Merge/PR/Deploy/เปลี่ยน Branch
เก็บ Untracked Evidence เดิม 5 ไฟล์และ Runtime เดิมทั้งหมด

## Implementation ที่ตรวจจาก Source

- Forward042 เพิ่ม Immutable Policy Acceptance แบบ Owner-only FORCE RLS,
  Certificate/Lineage/Artifact/Product/Period Identity และ Service-only RPC4ตัว
- Local policy `local-declared-period-footprint-v1` ต้องให้ Admin ยืนยันข้อจำกัด
  สองข้อทุกคำสั่ง ไม่เปลี่ยน `period_verified=false` หรือ Complete Coverage
- Native Verifier แยก RO/Network None/Credential-free Recompute ต้นฉบับและเทียบ
  Immutable TIFF/JSON จริงก่อน Mutation/Read พร้อม SHA/Size/Metadata/Snapshot
- Reuse Dataset pointer, CAS, Lock Order, Audit และ Idempotency; Replacement
  ไม่ถอนฉบับเดิม, Rollback ต้องมีประวัติ, Withdrawal เป็น Terminal และไม่ลบไฟล์
- Published reader แยก Namespace ต้องระบุ Product/Province/Year/Month และ
  Source Footprint ชัดเจน; ไม่ใช้ Annual แทน Monthly ไม่รองรับ District/AOI
- Dashboard ต้องเลือก Published เอง ภาพ/Legend/Summary มาจาก Bundle เดียว
  Legacy Sidebar/Layers ซ่อนเฉพาะโหมดนี้ โดยไม่เปลี่ยนข้อมูล/State เดิม
- Image สูงสุด64×64 จาก Actual Prepared TIFF, NoData โปร่งใส, DTO256KiB;
  EPSG:4326 north-up เท่านั้น Display-only nearest EPSG3857 grid และ Bitmap Cartesian
  โดย Scientific TIFF/JSON ไม่เปลี่ยน; Catalog Snapshot แยกจาก Render Snapshot
  ที่ผูก PNG SHA/Bounds/Grid/Method
- Cache ใหม่แยกเฉพาะ Summary Projection32 entries/60s; แม้ Cache Hit ก็ตรวจ
  Source/Artifact จริงและ SQL Snapshot ใหม่ ไม่ล้างหรือเขียน Legacy Cache
- เฝ้าตรวจทุก10s เมื่อหน้า Visible และเมื่อกลับแท็บ/มี Publication Event;
  Source/Scope/Refresh/Error ล้างภาพเดิม ไม่มี Silent Legacy Fallback

## Migration และ Independent Review

042 SHA256:
`dfb9adf5b36b290f715165a57905373df1226ab52c539cd93ff79da6a0c86946`

ใช้กับ Local `postgres` และ `gis_t1_upgrade` หลัง Exact Independent Review แล้ว
Migration000–041 ไม่ได้แก้หรือ Reapply;042 ถูกใช้แล้ว ห้ามแก้ย้อนหลัง
ผู้ตรวจ `local_integration_security_review` ตรวจ SQL/Auth/Verifier/Guard/UI
รวมถึง Runtime Evidence รอบสุดท้าย และยืนยัน PASS Local Synthetic,
High/Critical คงค้าง0; Reviewer ไม่ได้แก้ Source/SQL หรือรันทดสอบเอง
Broad database/backend activation gates ยังปิด; Private GeoTIFF Capability
ถูก Inject เฉพาะ Local Operator ไม่มี Native Worker Certification/Admin Rights

## ผลทดสอบจริงและขอบเขตหลักฐาน

| ชุด | ผล | ขอบเขต |
|---|---:|---|
| Backend/Local Guard | 651 Pass +37 Subtests | Suppress dotenv, ปิด Nonlocal Network |
| Linux Scientific | 162 Pass | รวม13 Publication Byte/Image/NoData/Period Tests และ149 Regression เดิม |
| Frontend Focused/Legacy | 99 Pass | รวม Source/Scope/Error Clearing, Admin Acks, Snapshot/Map และ Accessible Labels |
| Local Build | Pass | Final Local Build หลัง Render/Mobile correction |
| Core remaining API/Transactions | 27/27 Pass | integration-ee492cda2c; Includes busy+CAS retry, withdrawal, corruption, exact scope, LDD regression |
| Focused SQL/API/Worker/Browser integration | 25/25 Pass | browser-final-9adc8a0e2d; actual SQL race, extra CAS/rollback, fresh upload→prepare→Browser, temporary503/revocation |
| Actual Chrome Browser | 13/13 Pass | No API mocks, no Page Errors; NDVI/Celsius map, snapshot, mobile, corruption clearing |
| Final SQL/Cache/Data Preservation | Pass | 28 checks เดิมผ่าน +16 Function Bodies×2DB ตรงหลัง CRLF-only normalization + Application/SQL/Fixtures ไม่เปลี่ยน; Runner-only delta ระบุด้านล่าง |

## Source/Evidence ที่ตรวจได้จริง

External evidence: `<owned T0 root>/a4-2-geotiff-publication/`

- `execution-source.json`:473 executable/config paths; Core manifests472paths
  เป็นคนละ Scope มี22และ21pathsเฉพาะแต่ละชุด ไม่ใช่ไฟล์ Hash ไม่ตรง
- `combined-source.json`: Union494paths ไม่มี Hash Conflict และตรง Source ที่ใช้ทดสอบ
  รวม Backend Provider ที่ helper manifest เดิมไม่ได้ครอบคลุม
- `integration-f687311473`:34Passก่อนหยุดที่ concurrent status expectation
  เก็บ2Fail rows (assertion + execution stop) ตามจริง ไม่อ้างว่าทั้งรอบผ่าน
- `integration-ee492cda2c`:27Pass0Fail ต่อรายการค้างด้วย External Harness ที่เก็บ SHA
- `browser-final-9adc8a0e2d`:25Pass0Fail; `browser-results.json`13Pass0Fail
  ใช้ Native/API/DB จริง, No Page Errors; Generic Demo `smoke_exit=null`
  ไม่ใช่ผล Browser ให้ใช้ subprocess assertion และ Browser report ที่ระบุข้างต้น
- `visual-review.json`: เปิดดู Desktop NDVI/LST และ Mobile Screenshot จริง
  ภาพ3ช่องที่มีข้อมูลตรง Preview และ NoData ล่างขวาโปร่งใส; External Basemap
  ถูกปิด HTTPS ระหว่างทดสอบ ไม่อ้างว่า Live Basemap/GEE ผ่าน
- Unit/Science/Frontend Current:651+37 /162 /99 ผ่าน; Build รอบสุดท้ายผ่าน
- Failed CAS ตรวจ Dataset/Audit/Receipt ไม่เปลี่ยน; Owner เขียน Pointer ตรงๆ
  โดยไม่มี Transaction Audit ถูกปฏิเสธและ Rollback
- HTTP concurrent test ได้200+429 Storage Busy แล้วลอง CAS เดิมได้409
  มี Pointer/Revision Commit เดียว ไม่อ้างว่าคำสั่ง HTTP ทั้งคู่ถึง SQL
- แยก SQL Race จริง: JWT Admin ที่พิสูจน์แล้ว + Fresh Native Proof,
  สอง RPC/CAS เดียวพร้อมกัน:หนึ่ง Commit อีกหนึ่ง Revision Conflict;
  Revision/Audit/Receipt เพิ่มเพียงครั้งเดียว โดยถือ Immutable File Lock ภายนอก
- Temporary Runtime503 ทดสอบด้วย Controlled Verifier Failure Injection
  ผ่าน Real Normal JWT/API และตรวจ DB ไม่เพิกถอน ไม่ใช่การ Kill Docker จริง
- Actual TIFF Corruption ทดสอบแยก:409, Browser ล้างภาพ/Legend/Summary,
  Certificate ถูกเพิกถอนจริง คืน Original Bytes แล้วถอน Pointer เป็นNull

## ผลก่อนหน้าที่ไม่ผ่าน / หลักฐานต้องเก็บ

- Unit รอบแรก4เคสล้มเหลวจาก Mock `_lock` ชน Attribute ภายใน Mock แก้เฉพาะ
  Test Fixture เป็น `nullcontext`; รอบถัดไป647+37 ผ่าน เก็บ Failure JSON ไว้
- Frontend รอบแรก Dashboard Compile ไม่ผ่านจาก JSX brace แก้แล้วและ99ผ่าน
- Integration `d51ddc36ea` รายปี6ฉบับผ่าน แต่ Monthly ถูกปฏิเสธถูกต้องด้วย
  PREPARE_MONTH_METADATA_REQUIRED: Generator แทนคำ YEAR ทั้ง String ทำให้
  GIS_YEAR กลายเป็น GIS_2026 ยืนยันจาก Original TIFF Bytes; แก้ Sentinel,
  สร้าง Monthly Input ใหม่ โดยไม่แก้ Source/History เดิมหรือ Validator
- Integration `a0ff3d6c1c` Monthly ผ่าน, Roles/CAS ผ่าน, Celsius/Kelvin เปิดใช้
  และอ่านค่าจริงผ่าน, Browser Admin Activation ผ่าน แต่ Exact Source Locator
  ไม่เจอเพราะ Wrapped Select Label รวม Option Text; Probe ยืนยัน Dashboard
  แสดงจริง ไม่มี Page Error แก้ Explicit ARIA Labels และเพิ่ม Unit Test
- Concurrent assertion รอบ f687311473 และ55b932de25 คาด200+409 แต่ระบบเดิม
  ใช้ Nonblocking Storage Lock จึงตอบ200+429 Busy; ไม่แก้ Application Contract
  รอบ ee492cda2c บันทึกผลจริงและลอง CAS เดิมซ้ำได้409 พร้อม Commit เดียว
- Browser cba7d20485 ผ่าน11ข้อก่อนหยุดที่ Layout มือถือซึ่งกว้างเพียง26px;
  แก้ Grid เฉพาะ Published Mode และเปลี่ยนภาพแสดงผลเป็น Web Mercator nearest
  โดยไม่แก้ Scientific TIFF/JSON/Certificate หรือ Migration042
- Independent Review พบ High: Verifier Busy/Timeout เคยถูกตีความเป็นไฟล์เสีย
  แก้503ชั่วคราวไม่เพิกถอน; การตรวจพบ Source/Artifact เสียจริงยัง409+Revoke
  เพิ่ม4 Unit Tests และ651+37ผ่าน; Exact Source Review ปิด High แล้ว
- Unit rerun ใน Process restricted รอ Local socketpair จนหมดเวลา; ใช้สิทธิ์
  Loopback สำหรับ TestClient โดยคง dotenv/nonlocal block แล้ว651+37ผ่าน
- Render Test รอบแรก161ผ่าน1ไม่ผ่านจาก MemoryFile cursor อ่านท้ายไฟล์;
  แก้ Test seek(0) โดยไม่แก้ Expected Pixel Positions แล้ว162ผ่าน
- Resume ใช้ผลและไบต์หกฉบับเดิมที่ตรวจผ่าน ไม่แก้ Expected Scientific Values
  ไม่ใช้ Receipt History เป็นหลักฐานว่าพอยน์เตอร์ปัจจุบันเปลี่ยนตามประวัติ
- Raw JSON/Logs/Screenshots และ Source Manifests ทั้งรอบผ่าน/ไม่ผ่านอยู่นอก Git

## Files Changed

- SQL/Review: `042_gis_geotiff_publication.sql`, `.gitattributes`,
  `dev/gis_local/geotiff-publication-review.json`
- Backend: ใหม่ `gis_geotiff_publication.py`, `routers/geotiff_publication.py`,
  `gis_worker/geotiff_publication_child.py` และ API/Scientific Tests;
  ต่อ Router/RPC/Capability/Error Mapping ใน app/runtime/service/routers/gis
- Local: `geotiff_publication_local.py`, `geotiff_publication_checks.py`,
  Publication Guard Tests, `a42_smoke.cjs`, `a42_demo.py`; เพิ่ม Exact RO Verifier Policy ใน
  `manage.py`, ผูก Private Provider ใน `legacy_demo.py`
- Frontend: `GeoTiffPublicationActions`, `PublishedGeoTiffPanel`,
  `usePublishedGeoTiff`, `publishedGeoTiffLayer`, Scoped CSS/Tests;
  ต่อ Dashboard/GIS Management/Closed Client Routes
- Docs: Contracts และ Handoff นี้ ไม่มี Raw Runtime Evidence/Credentials

## ข้อจำกัดและ Not Tested

- Synthetic เท่านั้น ไม่ใช่ข้อมูล GIS จริงหรือ Production/GEE Acceptance
- Publication รองรับเฉพาะ EPSG4326; A4.1 UTM Preview ยังอยู่ แต่ Publish ไม่ได้
- ปี/เดือนเป็น Declaration ที่ยอมรับใช้ Local ไม่ใช่การรับรองช่วงเวลาจริง
- Footprint Intersection ไม่รับรองทั้งจังหวัด; Summary ไม่ใช่สถิติจังหวัด/
  District หรือ Area-weighted GEE Analysis; Boundary เป็นข้อมูลประมาณ
- Raster64×64 เป็น Nearest Visual Sample; Source Prepare cap1million pixels
  ไม่ใช่หลักฐาน Publication Capacity ระดับจังหวัดหรือ Throughput
- Native Limits เดิมยังบังคับ แต่ไม่ได้ Rerun Physical OOM/Timeout/CPU Burn
  หรือ Worker Lifecycle ทั้งชุดของ A4.1 เนื่องจาก Queue/Worker ไม่ได้เปลี่ยน
- Polling10s และ Fresh Native Verifier ต่อ Read เป็น Local Design ไม่ใช่
  Instant Push หรือคำรับรอง Production Performance

## Final Preservation / Migration Verification

- `final-checks.json` เก็บผลดิบ28Pass2Failตามจริง:สองข้อที่ Fail เป็นการเทียบ
  Raw Function Body ซึ่งฐานเก็บCRLF แต่ SourceLF ไม่ใช่ Schema Drift
- `function-body-diagnostic.json` จาก Read-only pg_proc ทั้งสองฐาน ตรวจ16Functions:
  2Bodiesตรงไบต์ และ14Bodiesต่างเฉพาะ CRLF/LF; หลังแทน CRLF→LF เท่านั้น
  เนื้อหาตรงครบ16 ไม่มี Trim/Whitespace Rewrite หรือ SQL/Checksum Repair
- `final-verification.json` รวมหลักฐานจริงเป็น31Verification Checks ผ่าน
  (28Checks+2Normalized Function Checks+1Union Source Check) ไม่ใช่การอ้างว่า
  Rerun DB Tests ทั้งหมดใหม่; เก็บ Raw Failure/Diagnostic/Harness SHA ครบ
- Ledger042 ตรง Reviewed SHA ทั้ง `postgres`/`gis_t1_upgrade`;000–041ไม่เปลี่ยน
- New Table Owner-only FORCE RLS,12Functions ACL/Owner/Search Path ถูกต้อง;
  Actual Worker JWT ถูกปฏิเสธ4Publication RPCs และไม่มี Direct Table Grants
- Legacy Public Tables ทุกตารางที่ Baseline ตรวจ, Old Profiles, Old Ledger Rows,
  Old Active Pointers และ Pre-existing GIS Rows ทุกแถวที่เก็บ Hash ไม่เปลี่ยน
- ทดสอบ Cache ที่มีข้อมูลจริงในLocal: postgres NDVI annual3/LST annual3/Saved3,
  upgrade NDVI annual1/LST annual1/District NDVI annual1; ทุก Hash/Count เท่าเดิม
  ตาราง Month/Recommendation บางตารางว่าง จึงไม่อ้างว่าได้ทดสอบทุก Cache Type
  แบบมีข้อมูล แม้ Source ของ Legacy Readers/Calculations ไม่ได้แก้ไข
- Original Evidence5ไฟล์ตรง SHA เดิม; Native/Worker Containers ที่ชุดทดสอบสร้าง
  ถูกปิด/นำออกเฉพาะของตน ไม่มีการลบ Volumes/Original Artifacts/Raw Evidence
- Original Execution Union494paths SHA256:
  `6a11042aa37c6347d2640df8fa8b12cf02f5d10713a077556a8697c1d7b3e863`
- Git HEAD คงเดิม, Indexว่าง; A4.2มี32Files (10Modified+22New) ยังไม่Commit
  และรักษา Untracked Evidence เดิม5ไฟล์ ไม่ได้Push/Merge/Deployหรือเปลี่ยนBranch

## Test Runner Cleanup หลังเก็บผล Runtime

ตัวรันทดสอบใน Repository ยังมี Assertion เดิมที่คาด200+409 จึงนำบล็อก
200+429/Commitเดียว/CASเดิมลองซ้ำ409 ที่ผ่านจริงจาก External Harness กลับมาใช้
แก้เพียง `dev/gis_local/geotiff_publication_checks.py` หนึ่งไฟล์ ไม่แก้
Application/SQL/Native/Frontend/Fixtures หรือ Expected Scientific Values

- ตรวจ Syntax ผ่าน และบล็อกใหม่ตรง External Harness ที่รันผ่านทุกไบต์
- `test-runner-source-delta.json` เก็บ Before/After SHA, Block SHA,
  External Harness SHA และ Current Manifest494paths
- Runner ฉบับแก้ไม่ได้รัน E2E ทั้งชุดใหม่; หลักฐาน Runtime ใช้กับบล็อกเดียวกัน
  จาก External Harness ไม่อ้างว่าได้รัน Source Hash ของ Runner ใหม่แล้ว
- Original Execution Manifest/Reports/Failures ไม่ได้แก้ทับ; เป็น Source Delta
  ที่ Reviewer อนุมัติเป็น Test-only Reproducibility Cleanup
- Current Source494paths SHA256:
  `45637f1af01b3d02c71d42c1cd775b5d5499f1c0bbee38365a3dff44fcfe3bea`
- Application/SQL/Native/Frontend/Fixture Hashes ตรงชุดทดสอบทั้งหมด493pathsที่เหลือ

## การตัดสินใจและงานถัดไป

A4.2 PASS และปิดได้เฉพาะ Local Synthetic Scope ไม่มี Blocker/High/Critical ค้าง
พร้อมเสนอแผน/ขอบเขต A5 เพื่ออนุมัติแยก ไม่ใช่ Live GEE/Production Readiness
ห้ามเริ่ม A5/A6, Commit, Push หรือ Deploy จนกว่าจะได้รับอนุมัติใหม่
Physical Mobile Devices, Real GIS Data/Period/Coverage, Live Basemap/GEE/Cloud,
Production Throughput และการ Kill/OOM/Timeout Worker ทั้งชุดยังไม่ได้ทดสอบใหม่


## รายชื่อไฟล์ A4.2 ทั้งหมด

- `dev/gis_local/geotiff-publication-review.json`
- `dev/gis_local/geotiff_publication_checks.py`
- `dev/gis_local/geotiff_publication_local.py`
- `dev/gis_local/tests/test_geotiff_publication_guard.py`
- `dev/gis_ui/a42_demo.py`
- `dev/gis_ui/a42_smoke.cjs`
- `docs/gis/a4-2-contracts.md`
- `docs/gis/a4-2-handoff.md`
- `green-area-backend/gis_geotiff_publication.py`
- `green-area-backend/gis_worker/geotiff_publication_child.py`
- `green-area-backend/migrations/042_gis_geotiff_publication.sql`
- `green-area-backend/routers/geotiff_publication.py`
- `green-area-backend/tests/test_geotiff_publication_api.py`
- `green-area-backend/tests/test_geotiff_publication_native.py`
- `green-area-frontend/src/components/GeoTiffPublicationActions.js`
- `green-area-frontend/src/components/GeoTiffPublicationActions.test.js`
- `green-area-frontend/src/components/PublishedGeoTiffPanel.js`
- `green-area-frontend/src/components/PublishedGeoTiffPanel.test.js`
- `green-area-frontend/src/hooks/usePublishedGeoTiff.js`
- `green-area-frontend/src/hooks/usePublishedGeoTiff.test.js`
- `green-area-frontend/src/styles/published-geotiff.css`
- `green-area-frontend/src/utils/mapLayers/publishedGeoTiffLayer.js`
- `.gitattributes`
- `dev/gis_local/manage.py`
- `dev/gis_ui/legacy_demo.py`
- `green-area-backend/gis_app.py`
- `green-area-backend/gis_runtime.py`
- `green-area-backend/gis_service.py`
- `green-area-backend/routers/gis.py`
- `green-area-frontend/src/Dashboard.js`
- `green-area-frontend/src/components/GisManagement.js`
- `green-area-frontend/src/utils/gisClient.js`

รายการนี้ไม่รวม Evidence เดิม5ไฟล์ ซึ่งต้องเก็บไว้นอก Commit เช่นเดิม
