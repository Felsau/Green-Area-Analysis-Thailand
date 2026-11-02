# T5 Final Readiness / Phase 1 Closure

28 ตุลาคม 2026 · **T5 PASS — Phase 1 CLOSED เฉพาะ Local Synthetic Scope**

## ขอบเขตและสิ่งที่ดำเนินการ

ตรวจ Integration/Security/Data Integrity ของ T0–T4 โดยใช้หลักฐานเดิมเมื่อ SHA256
ตรงกับ Source ปัจจุบัน และรันเฉพาะ Final Regression กับช่องว่างเรื่อง Closed Gates
ไม่พบ Application Blocker จึงไม่แก้ UI, Backend, Worker, Contracts หรือ Migration

ไฟล์ใหม่ใน T5 มีสองไฟล์:

- `dev/gis_ui/final_readiness.py` — ตรวจ Source/Evidence, Local Auth/API, Gates,
  Idempotency และ Preservation; ไม่มี Schema/Worker/Container/Cloud Creation
- `docs/gis/t5-closure.md` — สรุปปิดงานฉบับนี้

## ผลทดสอบใหม่

| รายการ | ผล |
|---|---|
| Final Readiness | **42 Pass / 0 Fail** รวมการตรวจจริงผ่าน Auth/API/PostgreSQL และ Source/Evidence Checks |
| RLS Policies จริงทั้งสองฐาน | ผ่าน 8 Predicates: ฐานละ 11 Owner-only Policies / ALL / Owner Predicates |
| Frontend GIS/Route/Regression | **63 Passed / 0 Failed** — 7 Test Files |
| Backend GIS API/Runtime Unit | **75 Passed / 0 Failed** — Mock Tests |
| Backend Legacy/Auth Regression | **81 Passed / 0 Failed** — Mock Tests |
| Frontend Build | ผ่าน; มี Warning Chunk ของ Map/PDF เดิมใหญ่กว่า 500 kB |
| Source/Diff | Source T3/T4 เดิมตรง SHA256, Git Diff Check ผ่าน |

หลักฐานเดิมที่ตรวจ Source/Hashes แล้วนำกลับมาใช้ ไม่ได้รันซ้ำใน T5:
T4 Browser E2E **16/16** (UI → Auth/API → Queue → Linux Worker → Native LDD Result → UI),
T3 Worker E2E 72 Assertions, Dual Workers 7 Assertions และ Linux Scientific 35 Tests
รวมถึงหลักฐาน Recovery/Fencing/Heartbeat/Shutdown/Native Memory/Timeout ของ T3

Backend Runs รอบแรกใน Restricted Shell ค้าง จึงหยุดเฉพาะ Processes ของ T5 ที่ยืนยันแล้ว
และรันใหม่ด้วย Host Permissions จนผ่าน ทั้งสองชุดปิด dotenv และปฏิเสธ Nonlocal Sockets
ไม่ได้ถือรอบที่ค้างว่าทดสอบผ่าน และไม่ได้เปลี่ยน Dependency เพื่อแก้ข้อจำกัดนี้

## Security / Data Integrity ที่ยืนยันแล้ว

- JWT ที่แก้ลายเซ็นได้ 401; User อ่าน Catalog/ให้สิทธิ์ตัวเองไม่ได้ และเรียก Service RPC โดยตรงไม่ได้
- Admin Grant/Revoke ได้; Officer ไม่มี Admin Capabilities และถูกปฏิเสธหลัง Revoke
- Key/Body เดิม Replay ผลเดิม มี Receipt เดียว; Key เดิมต่าง Body ได้ 409
- Gate เดิมยังปิด: Admin Activate/Rollback/Withdraw ได้ 503 `GIS_ACTIVATION_DISABLED`;
  Officer ได้ 403 ไม่เปิด Gate เพียงเพื่อให้ Test ผ่าน
- Schema/Functions/Grants/RLS Flags/Worker Identity Boundary และ Ledger ของทั้งสองฐาน
  ตรง SQL Audit ที่ผ่าน Independent Review ใน T3; ไม่มี Direct Worker Table Privileges
- Policies ปัจจุบันตรวจเพิ่มเติมแบบ Read-only แล้วเป็น Owner-only ทั้ง 11 ตาราง
- Ledger รวม Checksum/Applied Time, Profiles เดิม และ Legacy Tables คงเดิมทั้งสองฐาน
  Catalog/Jobs/Attempts/Results ก่อนและหลัง T5 ไม่เปลี่ยน ไม่มี Auto-activation
- สร้างเพียง Auth/Profile จำลองใหม่สองบัญชีสำหรับทดสอบ Admin/User และ Grant/Revoke;
  ไม่เปลี่ยนบัญชีเดิม เก็บ Test Rows ตามข้อห้ามลบข้อมูล
- Local Target/Feature Flag Guards และ V1/V2 Isolation/Compatibility ใช้ Source เดิมที่ยืนยัน SHA แล้ว
  ไม่มีการแก้ Security Behavior ใน T5 จึงไม่จำเป็นต้องเปิด Independent Review ใหม่
  ไม่พบ High/Critical ค้างจากการตรวจรอบนี้หรือ Reviews ที่อ้างอิง

## Evidence / ขอบเขตที่ยังไม่ได้ทดสอบ

หลักฐานใหม่อยู่ที่
`C:\Users\chaya\.codex\visualizations\2026\10\04\01a107d9-ff44-7731-8bc3-91814ffd8d51\t0-local-supabase-20261027-v2\t5-final\`

`summary.json` บันทึก Artifact SHA256; รายละเอียดคือ `integration.json`, `rls-policies.json`,
`frontend-tests.json`, `backend-unit-tests.json`, `backend-regression-tests.json`
ตรวจ Source เทียบหลังทดสอบแล้วไม่เปลี่ยน รายงานไม่บันทึก Credentials/Tokens

ยังไม่ได้ทดสอบ Gate-enabled Activation/Rollback/Withdrawal Success,
Live Browser Retry Success, GeoTIFF Browser E2E, Auth Refresh Expiry/Rotation,
Kernel/cgroup OOM-kill หรือ CPU-burn Exhaustion
Native GIS/GeoTIFF Scientific Tests เดิมมีหลักฐาน แต่ไม่อ้างว่าเป็น Browser Test ใหม่
Pending UI Command ยังอยู่ใน Memory และไม่รอด Reload/ปิดหน้า
ไม่มี Fixture Picker Endpoint จึงยังวาง Allowlisted Synthetic Manifest เอง
ข้อจำกัดเหล่านี้ไม่ขวางการปิด Local Synthetic Scope แต่ไม่ใช่ Production Readiness

## Git / สถานะส่งต่อ

Branch `feature/gis-data-management`
HEAD `048273f7b69ec6b60ac02f18ddbd1007619bd574`

รักษา Uncommitted Changes ของ T0–T4 ทั้งหมด ไม่แก้ Migration 000–033 หรือ Ledger
ไม่เปลี่ยน Branch/Reset/Stash/Clean/Commit/Push/Merge/Deploy ไม่ลบข้อมูลหรือ Volumes
ไม่เชื่อม Production/Staging/GEE/Cloud และไม่สร้าง Container ใหม่ใน T5

**ไม่มี Remaining Blocker สำหรับ Phase 1 Local Synthetic — CLOSED**
งานถัดไปเสนอ Phase 2 — LDD Upload & Management โดยต้องได้รับอนุมัติแยกก่อนเริ่ม
ยังไม่ได้เริ่ม Phase 2 และไม่ได้สร้าง Upload/Storage หรือ Production Resources
