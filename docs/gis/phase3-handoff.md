# Phase 3 — NDVI/LST Offline Processing Handoff

วันที่ 29 ตุลาคม 2026 · รอ Final Acceptance · ไม่เริ่ม Phase 4

## ขอบเขตและสถานะ

พัฒนา Local UI → FastAPI → Supabase Auth/PostgreSQL → Linux Worker → Candidate/Failure Report จริง โดยใช้พิกเซลจำลอง ไม่ใช่ผลดาวเทียมหรือผลของพื้นที่ที่เลือก ไม่มี Live GEE, Publish, Cache Swap หรือ Auto-activation

สถานะโดยรวม **PARTIAL**: Offline MVP พัฒนาแล้ว แต่ Live GEE ไม่ได้รับอนุมัติ/ยังไม่ทดสอบ และยังไม่มีการทดสอบรักษา Cache ที่ไม่ว่างในฐานเดียวกับ Worker ดู Evidence Index สำหรับผล Browser ล่าสุด

## Implementation / Contracts

- UI เดิมเพิ่ม NDVI/LST, จังหวัด/อำเภอ, ปี/เดือน, Confirmation, Double-submit Guard, Queue/Attempts/History และรายงานที่ระบุ Offline Synthetic ชัดเจน ใช้ Auth/API Client เดิม
- API: `GET /gis/processing-options`; `GET/POST /gis/processing-jobs`; `GET /gis/processing-jobs/{id}` และ `/attempts`, `/result`, `/history`; `POST /gis/processing-jobs/{id}/retry`
- Request ใช้ `mode=offline_synthetic`, Metric, จังหวัด/อำเภอจากฐาน Local, ปี, Month 0=รายปี/1–12=รายเดือน และ Scenario ที่ Allowlist เท่านั้น ไม่รับ Path/URL/Command/SQL
- NDVI รองรับปี 2017–ปีปัจจุบัน; LST 2013–ปีปัจจุบัน; Scale Metadata จังหวัด 500 m/อำเภอ 100 m ไม่มีการวัดพื้นที่จริง
- Migration 035 เพิ่ม Forced-RLS `gis.processing_requests` และ Processing RPC/Protocol โดย Reuse Dataset/Edition/Job/Attempt/Result/Audit/Idempotency/Lease เดิม ไม่มี Cache DML
- Manifest V3 ผูก Scope, Dates, Processing Version, Legacy Source Hash, Fixture SHA256/Size และ Input Revision/Hash ผลสำเร็จเก็บ Candidate `offline_processing`, Edition กลับ Draft, Validated Pointer เป็น NULL และ SQL ไม่อนุญาต Activation ของ Schema 3
- Worker ใช้ Native Worker JWT Subject เดิมที่จำกัดสิทธิ์ ไม่ใช้ Service Role; Processing Claim แยกจาก LDD/V1/V2; Atomic Claim, Heartbeat, Retry Budget, Recovery และ Fencing เดิม
- Native Child แยก Credentials, จำกัดเวลา 25 s, Address Space 512 MiB, CPU 20 s และ Output 16 KiB; Container Non-root/Read-only/CPU 1/Memory 1 GiB/PIDs 64 บน Internal Network ที่ Attest แล้ว
- Target Guard เพิ่มเฉพาะ Exact Processing Container และสาม Read-only Legacy Source Mounts ไม่ลด Guard เดิมหรือ Mount `.env`/Home/Credentials/Docker Socket

## GIS Science และขอบเขต Reuse

Processing Fixtures ใหม่ 6 JSON อยู่ `gis_worker/processing_fixtures/` แยกจาก Native GIS Fixtures เดิม 13 ไฟล์ที่ตรวจแล้วว่า Bytes ไม่เปลี่ยน

Provider อ่าน Formula/Filter Specification จาก Legacy AST หลังตรวจ SHA256 ไม่ Import Legacy Startup, ไม่ Eval/Exec และไม่เรียก Earth Engine SDK จากนั้นคำนวณจากพิกเซลจำลองจริง ไม่คืนตัวเลขสำเร็จแบบ Hardcode ใน Worker

| กรณี | Expected Result ที่ทดสอบ |
|---|---|
| NDVI รายปี | 2 Valid Pixels; Mean 0.4921; Min 0.4286; Max 0.5556 |
| NDVI รายเดือน | 3 Valid Pixels; Mean 0.1614; Min -0.5; Max 0.5556 |
| LST | 2 Valid Pixels; Mean 29.66 °C; Min 22.82; Max 36.5 |
| No Data | Failed; ไม่มี Candidate; ค่าเฉลี่ย NULL ไม่ใช่ 0 |
| Transient Once | Attempt 1 รอจำลอง Cloud Boundary 12 s แล้ว Fail; Attempt ถัดไปคำนวณจริง |

Reuse สูตร NDVI B8/B4, Scale Reflectance, Cloud Score/Cloud Cover/Annual Negative Mask และ LST ST_B10 Scale/Offset/QA Bits ตาม Source เดิม แต่ **ไม่ใช่การรัน Full Legacy Annual Pipeline**: Geometry/Spatial Reduction, Canopy, Data Quality, WorldCover/WorldPop และ Cloud Collection Query จริงยังไม่พิสูจน์

## Migration / Independent Security Review

- ใช้ SQL Migration เดิม ไม่เพิ่ม Prisma หรือ Dependency/บริการใหม่
- `035_gis_processing_offline.sql` SHA256: `4617ff8686e640df5ab8596f9c9e4605e5900ef4e3b9e32c1a43c9bc4fa8dc96`
- Independent Reviewer ตรวจ Exact SQL, 22 Functions, ACL/SECURITY DEFINER/RLS/Deferred Invariants ก่อนรัน; ไม่มี High/Critical ค้าง และตรวจซ้ำหลังแยก Fixture Directory/Transient Wait
- Apply 035 เฉพาะ `postgres` และ `gis_t1_upgrade` ใน Local Instance ที่ Attest แล้ว; ไม่แก้ 000–034 หรือ Ledger ย้อนหลัง
- Read-only Audit 13 Checks ผ่าน: SHA/Ledger รวม Timestamp เดิม, Forced RLS, Exact RPC Grants และ Native Worker ไม่มี Direct Table Privileges
- Actual Negative Tests ครอบคลุม JWT Spoofing, Admin RPC/Legacy Write Denial, Forged Scientific Report, Hash/Revision Conflict และ Stale Lease Completion

## ผลทดสอบจริงและประวัติข้อผิดพลาด

หลักฐานอยู่ใต้ Local Runtime `t0-local-supabase-20261027-v2/phase3/` และ `phase3-browser/`; ดู `phase3/evidence-index.json` สำหรับ Absolute Paths, SHA256 และ Source Coverage

| หลักฐาน | ผล / ขอบเขต |
|---|---|
| Unit / API / Target Guard / Worker Regression | 338 Passed |
| Linux Python 3.11.17: Processing + Common Worker + Original Native Provider | 124 Passed; Network None |
| Frontend GIS/Auth/Client Tests | 71 Passed |
| Backend Legacy/Auth Regression | 81 Passed |
| Frontend Build | Exit 0; มี Warning ขนาด Chunk เดิม |
| Integration `26564ed3b5a2` | 8 Pass / 2 Fail; สมมติว่าฐานหลักมี Cache Sentinel ผิด ไม่สร้างงานสำเร็จในรอบนี้ |
| Integration `d2811f282f3c` | 40 Pass / 2 Fail / 1 Not Tested; พบ Fixture Directory Regression |
| Integration `0fb9e239072b` หลังแก้ | 30 Pass / 0 Fail / 1 Not Tested; LDD/V2 Compatibility และ Recovery จริง |
| Browser `4ea1445c2c` | 23 Pass / 0 Fail; UI/Auth/API/Queue/Linux Worker จริง ไม่มี HTTP Mock; NDVI รายปี, LST เดือน 2 ระดับอำเภอ, No Data, Double Submit, Live/Invalid Scope Denial และ Desktop/Tablet |

ไม่รวมผลต่างรอบเป็นจำนวน Test ที่ไม่ซ้ำ: รอบ 40 Pass เป็น Source ก่อนย้าย Fixture Directory โดย Evidence พิสูจน์ความเทียบเท่า 4 ข้อ (Bytes ใหม่เดิมตรงกัน, App/SQL อื่นไม่เปลี่ยน, Provider/Unit เปลี่ยนเฉพาะ Default Path) และรัน Linux/Native Compatibility ใหม่แล้ว

Regression ที่พบแก้โดยย้ายเฉพาะหก JSON ใหม่ออกจากโฟลเดอร์ Registry เดิม ไม่แก้/ผ่อนปรน Registry เดิม งาน LDD ทดสอบที่ค้างถูกประมวลผลด้วย Worker จริง ไม่มีการ Patch Job State ผ่าน SQL

Browser รอบ `c4bace9b47` มี 18 Pass / 1 Fail และ `3aea5a13a0` มี 12 Pass / 1 Fail: ตัวทดสอบรีเฟรชทุกวินาทีก่อน GET เดิมเสร็จจนยกเลิกคำขอ จึงแก้เฉพาะตัวทดสอบให้รอ Response ครบ ไม่ขยาย Timeout ของแอป ไม่ Mock หรือเปลี่ยนผลลัพธ์ รอบแรกยังมี Exit Code ผิดจาก Function ชื่อ `process` บัง Node Global; แก้ชื่อแล้วและตัดสินผลจาก Case Rows ด้วย ไม่อ้าง Exit 0 รอบนั้นว่าผ่าน

พิสูจน์จริงแล้ว: Concurrent Claim, Retry Budget/Explicit Retry, Heartbeat ระหว่างงาน → SIGKILL → Lease หมดอายุตามเวลาจริง → Replacement Recovery → Stale Completion ถูกปฏิเสธ → Candidate เดียว

Manual Retry Exhaustion ใช้ Authorized Worker RPC Fault Injection **ไม่ใช่ OS Timeout/OOM จริงของ Provider ใหม่**; หลักฐาน SIGTERM/SIGINT/Timeout/Memory Limits ของ Common Worker จาก T3 ใช้ได้เฉพาะ Source ที่ยังตรงกัน ไม่อ้างว่ารัน Fault Cases เหล่านั้นใหม่ทั้งหมดใน Phase 3

## Preservation / ข้อจำกัดที่ยังไม่ทดสอบ

- Public Legacy Tables, Profiles เดิม และ Ledger ทั้งสองฐานผ่าน Before/After Comparison; Test Users/Rows ใหม่เก็บไว้ ไม่ลบข้อมูล/Volumes
- ฐาน Worker `postgres`: NDVI Annual / LST Annual Cache = 0 / 0 แถว Hash ไม่เปลี่ยน
- `gis_t1_upgrade`: Cache = 1 / 1 แถว Hash ไม่เปลี่ยน แต่ไม่ได้รัน Worker กับฐานนี้
- ดังนั้น **Not Tested: การรักษา Cache ที่ไม่ว่างในฐานเดียวกับ Worker หลัง Processing Failure** ไม่เติมตัวเลขจำลองที่ดูเหมือนผลดาวเทียมลง Legacy Cache เพื่อให้ผ่าน
- Live GEE, Project Binding/API Registration, IAM/Service Account, Billing/Noncommercial Tier/Quota และสิทธิ์เข้าถึง Collections ของบัญชีปัจจุบัน **Not Verified**; Adapter ปฏิเสธก่อนโหลด Cloud Configuration
- ไม่แก้ `gee_utils.py`, `routers/ndvi/compute.py`, `routers/ndvi/endpoints.py`, `routers/lst.py` หรือ Legacy Cache Logic เดิม ซึ่งบางเส้นทางเดิมยังลบ Cache ก่อน Compute; งานใหม่ไม่เรียกเส้นทางนั้น
- ไม่อนุมัติเปิด Activation Gate, Publish/Cache Swap, Production Capacity หรือ Full Phase 2 Management จากผลนี้

## ไฟล์ที่เพิ่ม/แก้ใน Phase 3

- เพิ่ม `migrations/035_gis_processing_offline.sql`; `gis_worker/processing_provider.py`, `processing_child.py`, `processing_worker.py`, `processing_fixtures/*.json`; `tests/test_processing_api.py`, `test_processing_provider.py`
- แก้ `gis_schemas.py`, `gis_runtime.py`, `gis_service.py`, `routers/gis.py`
- แก้ `src/components/GisManagement.js`, `GisManagement.test.js`, `src/utils/gisClient.js`, `gisClient.test.js`
- แก้ `dev/gis_local/manage.py`; เพิ่ม `dev/gis_local/tests/test_processing_worker_guard.py`
- เพิ่ม `dev/gis_ui/phase3_local.py`, `phase3_checks.py`, `phase3_units.py`, `phase3_linux.py`, `phase3_audit.py`, `phase3_browser.py`, `phase3_browser.cjs` และเอกสารฉบับนี้
- งาน T0–Phase 2 ที่ยังไม่ Commit รักษาไว้ทั้งหมด ไม่ถือ Git Diff เทียบ HEAD ว่าเป็นเฉพาะ Phase 3 เพราะไฟล์ส่วนใหญ่เดิมก็ยัง Untracked

## Git / Cleanup / ขั้นถัดไป

Branch `feature/gis-data-management`; HEAD `048273f7b69ec6b60ac02f18ddbd1007619bd574`; Working Tree ยังไม่สะอาดตามเดิม ไม่มี Commit/Push/Merge/Deploy/เปลี่ยน Branch

Containers ของการทดสอบถูกหยุด/นำออกเฉพาะที่เป็นเจ้าของ; Local Core สี่ตัว, Image เดิม, Volumes และข้อมูลเก็บไว้ ไม่มี Cloud/GEE Access

รอ **Final Acceptance Review** ตรวจ Source/Evidence รวม Browser และ Cache Gap ก่อนปิด Phase 3; การทดลอง Live ต้องอนุมัติ Sandbox Project, ตัวตน Least Privilege, Registration/API/Quota/Budget และชุดทดสอบวิทยาศาสตร์แยกก่อน ห้ามเริ่ม Phase 4–5 อัตโนมัติ
