# T4 — GIS Management UI Handoff

วันที่ 28 ตุลาคม 2026 · **COMPLETE เฉพาะ Local Synthetic Scope**

## เป้าหมาย / ขอบเขต

เพิ่ม UI บน React/Vite เดิมให้ GIS Officer/Admin จัดการ Dataset, Edition,
Validation Jobs/Reports และ Officer Grants ผ่าน FastAPI T2–T3 จริง
ไม่พัฒนา T5, Upload/Storage, GEE, Migration หรือ Deployment

## สิ่งที่ยืนยันจากโค้ด / สิ่งที่ทำแล้ว

- ระบบเดิมไม่มี React Router จึงเพิ่ม `?view=gis` โดยรักษา Query ของแผนที่เดิมและ Browser Back
- เมนูผู้ใช้แสดง GIS เมื่อ `/gis/me` ให้ `read_catalog` เท่านั้น ไม่ใช้ `profiles.role` เป็นอำนาจตัดสิน
- Deep Link ที่ยังไม่ Login ใช้ AuthGate เดิม; ผู้ไม่มีสิทธิ์เห็น Access Denied
- ใช้ Supabase Session เดิม และอ่าน Session ใหม่ก่อนส่งแต่ละคำขอ ไม่เก็บ Token เพิ่ม
- GIS ปิดเป็นค่าเริ่มต้น ต้องเปิด Flag พร้อม Exact Local API/Auth/Browser Targets เท่านั้น
- API Client ปฏิเสธ Arbitrary Paths/Remote Targets, Redirects และ JWT issuer/subject/role ที่ไม่ตรง
  การตรวจ JWT ฝั่ง UI เป็นเพียง Routing Guard; Backend ยังคงตรวจ Signature และสิทธิ์จริง
- Dataset มี List/Filter/Pagination/Create/Edit; Edition มี Create/Edit Draft/Clone/Validation/History
- Admin มี Activation/Withdrawal/Rollback เมื่อ Backend รายงาน Gate เปิด; Backend ตรวจสิทธิ์และ Eligibility อีกครั้ง
- Jobs แสดงตามสถานะและ Dataset ที่เลือก มี Detail, Attempts, Safe Reports และ Retry ที่ตรวจ Revision/Hash ปัจจุบัน
- ทุก Mutation ต้อง Review + Confirm พร้อมข้อมูลเป้าหมายและ Revision; ป้องกัน Double Submit
- เมื่อผลคำสั่งไม่แน่นอน จะพักคำสั่งใหม่และเก็บ Body/Key เดิมไว้เหนือ Authorization Branch
  แม้ `/me` ตอบ 503 แล้วฟื้นกลับมา ยังลองคำสั่งเดิมด้วย Key เดิมได้
- จำนวนใน Overview ระบุชัดว่าเป็นข้อมูลเฉพาะหน้าที่โหลด ไม่อ้างเป็น Aggregate ทั้งฐาน
- ใช้ Manual Refresh ไม่มี Poll Loop ค้างเมื่อออกจากหน้า; Reads ยกเลิกเมื่อ Unmount
- Native Worker รองรับ V2; V1 ยังคงแสดง/แก้/Clone ได้แต่ไม่ส่งเข้า Native V2 Queue จาก UI

## ไฟล์ที่เปลี่ยน

ไฟล์เดิม 4 ไฟล์:

- `green-area-frontend/src/App.js` — Route/Auth/Navigation ไป GIS แบบ Lazy Load
- `green-area-frontend/src/Dashboard.js` — ส่ง Navigation Callback
- `green-area-frontend/src/components/AppHeader.js` — ส่ง Callback ให้เมนูเดิม
- `green-area-frontend/src/components/UserMenu.js` — เมนู GIS ตามสิทธิ์ Backend

ไฟล์ใหม่ 12 ไฟล์:

- `green-area-frontend/src/components/GisManagement.js` — หน้าจัดการและ Dialogs
- `green-area-frontend/src/styles/gis.css` — Styling ตาม Tokens เดิม พร้อม Desktop/Tablet
- `green-area-frontend/src/utils/gisClient.js` — Local-only API Client/Error/Idempotency/Abort
- `green-area-frontend/src/hooks/useGisAccess.js` — Backend Capabilities และ Session Change
- `green-area-frontend/src/components/GisManagement.test.js`
- `green-area-frontend/src/utils/gisClient.test.js`
- `green-area-frontend/src/hooks/useGisAccess.test.js`
- `green-area-frontend/src/GisRouting.test.js`
- `dev/gis_ui/vite.config.mjs` — Local/Test Profile ไม่โหลด `.env` เดิม; Flag ปิดโดย Default
- `dev/gis_ui/local_smoke.py` — Attested Local Auth/API/Worker/Preservation Test Harness
- `dev/gis_ui/browser_smoke.cjs` — Chrome Browser Acceptance ผ่าน API จริง จำกัดเฉพาะ Local Origins
- `docs/gis/t4-handoff.md` — รายงานนี้

ไม่เพิ่ม Dependency หรือเปลี่ยน SQL/Backend/Worker/Legacy Analysis/Cache
`green-area-backend/main.py` ที่ยัง Modified เป็นงาน T2 เดิม ไม่ใช่การแก้ใน T4

## API ที่เชื่อมจริงตาม Contract

Reads: `/gis/me`, `/provinces`, `/datasets`, `/datasets/{id}`, `/datasets/{id}/editions`,
`/editions/{id}`, `/editions/{id}/history`, `/jobs`, `/jobs/{id}`, `/jobs/{id}/attempts`, `/officers`

Commands: Create/Patch Dataset, Create/Patch/Clone Edition, Enqueue Validation,
Activation, Rollback, Withdrawal, Job Retry, Grant/Revoke Officer
ใช้ทั้งหมดภายใต้ `/gis`; Result อ่านจาก Job Detail/Attempt Report ไม่ต้องเรียก Result Endpoint แยก

## ผลทดสอบจริง

| ชุดตรวจ | ผล / ขอบเขต |
|---|---|
| Frontend Unit/Component/Route/Regression | **63 Passed / 0 Failed**, 7 Files; ใช้ Mock เฉพาะใน Tests |
| Browser → Local Auth/API → PostgreSQL → Linux Native Worker | **16 Passed / 0 Failed**, Chrome จริง ไม่มี Mock API |
| Build | ผ่าน 2,820 Modules; มี Warning Chunk ใหญ่ของชุด Map/PDF เดิม ไม่ได้ Refactor นอก Scope |
| ESLint ไฟล์ที่เกี่ยวข้อง | ผ่าน |
| Git Diff Check | ผ่าน |
| Preservation ทั้ง `postgres` และ `gis_t1_upgrade` | Ledger, Profiles เดิม และ Non-profile Legacy Tables ไม่เปลี่ยน |
| Backend/T0–T3 Source Preservation | Fingerprint ก่อน/หลัง Browser Test เท่ากัน |
| Cleanup | หยุด API/Vite และลบเฉพาะ Worker Container ที่ Harness สร้าง; Queue Idle |

Browser ยืนยัน Login เดิม, ปฏิเสธ User, Admin Grant, Officer Actions, Create Dataset/Edition V2,
Enqueue จน Native LDD ผ่านจริง, Report/No Auto-activate, Desktop 1366×900,
Tablet 768×1024 ไม่มี Document Overflow, Revision Conflict 409 จริง และ Revoke แล้วหมดสิทธิ์

หลักฐานรอบสุดท้าย:
`C:\Users\chaya\.codex\visualizations\2026\10\04\01a107d9-ff44-7731-8bc3-91814ffd8d51\t0-local-supabase-20261027-v2\t4-ui\a13e91f362\`

- `browser-results.json`, `frontend-tests.json`, `local-results.json`
- `gis-desktop.png`, `gis-tablet.png` — ภาพผล Job จริง ตรวจภาพแล้ว
- Source SHA256: `86f93d772206a064d82768f4e559af1072b504d92e310f76ed1cf237dd083f8b`
  ครอบคลุม Frontend JS/CSS และไฟล์ `dev/gis_ui`; ตรวจเทียบ Source ปัจจุบันแล้วไม่มี Drift
  ไม่รวมรายงานนี้ และไม่ใช่ Commit ใหม่

คำสั่ง Frontend ที่ใช้ ไม่โหลด `.env` เดิม:

```powershell
# จาก green-area-frontend
node node_modules/vite/bin/vite.js build --config ../dev/gis_ui/vite.config.mjs
node node_modules/vitest/vitest.mjs run --config ../dev/gis_ui/vite.config.mjs src/App.test.js src/Dashboard.test.js src/utils/apiClient.test.js src/GisRouting.test.js src/components/GisManagement.test.js src/hooks/useGisAccess.test.js src/utils/gisClient.test.js
```

Browser Harness ใช้ `local_smoke.py --runtime-dir <owned-T0-runtime> --node-modules <bundled-node-modules>`
ต้องมี Docker/Core Containers เดิมพร้อมและ Queue Idle; ใช้ Python Backend Venv และ Chrome ที่มีอยู่
ไม่ติดตั้งเพิ่ม ไม่อ่าน Host `.env`/GEE Credentials; Local Operator/Session ของ Synthetic Users อยู่ใน Memory เท่านั้น

## Independent Review / ข้อผิดพลาดที่พบและแก้

Read-only Reviewer `/root/t4_ui_review` ไม่พบ High/Critical ค้างในขอบเขต T4
ปิด Medium เรื่อง Attempt `expired`, Confirmation Details, Rollback History ที่ API แสดงไม่ครบ
และ Pending Key หายเมื่อ Authorization Refresh ขัดข้อง โดยเพิ่ม Test ของกรณีสุดท้าย
Reviewer ตรวจ Source; Runtime/Browser Tests ดำเนินการโดย Implementation Owner

Browser รอบต้นยังไม่ผ่าน: ตัวเปิด Chrome ขาด ProgramFiles ใน Environment ของ Harness
และ Label ของ Dropdown จังหวัดไม่ชัดเจนสำหรับ Browser Selector
แก้ Test Launcher Environment และผูก Label/Control ด้วย `htmlFor`/`id` จริงแล้ว
รอบสุดท้าย 16/16 ใช้ Source ปัจจุบัน ไม่อ้างผลรอบที่ล้มเหลวว่าผ่าน
รอบทดลองทั้งหมดสร้างบัญชี Local Synthetic ใหม่รวม 16 บัญชี เก็บ Rows ตามข้อห้ามลบ
การยกระดับ Admin ใช้เฉพาะ Profile ที่สร้างในรอบนั้น ไม่เปลี่ยนบัญชีเดิม

## ข้อจำกัด / สิ่งที่ยังไม่ได้ทดสอบ

- ไม่มี HTTP Fixture Catalog Endpoint จึงวาง Manifest ที่ลงทะเบียนไว้ในแบบฟอร์มแทนการเลือกอัตโนมัติ
- Activation/Withdrawal/Rollback ถูกปิดใน Local Gates เดิม: ตรวจ Rendering/Payload/Rejection ด้วย Component Tests
  **ยังไม่ได้ทดสอบ Live Success ใน T4** และไม่ได้เปิด Gate เพื่อทดสอบ
- Retry มี Positive/Negative UI/Contract Tests แต่ **ไม่ได้ทำ Live Browser Retry จนสำเร็จใน T4**
- Browser Native Success รอบนี้เป็น LDD V2; **ไม่ได้ทำ GeoTIFF Browser E2E ใหม่**
  ไม่อ้างผล Scientific Tests T3 ว่าเป็นการรันซ้ำใน T4
- Pending Command อยู่ใน Memory ของหน้าจัดการ ไม่เป็น Durable Recovery หลัง Reload/ปิดหน้า
  หลังเหตุการณ์นั้นต้องตรวจสถานะ Backend ก่อนสร้างคำสั่งใหม่; Jobs ที่ส่งแล้วอยู่ใน Server Queue
- ใช้ Standalone GIS Local API; ไม่ทดสอบ Map/GEE/Account API แบบ Live หรือ Production
- Core Containers เดิมยัง Running; API/Vite ของ Harness หยุดแล้ว จึงไม่มี Demo Server ค้าง
- ไม่ใช้ข้อมูล GIS จริง, Upload/Storage, Cloud หรือ Deployment; ไม่รับรอง Production Readiness

## Git / การอนุมัติถัดไป

Branch: `feature/gis-data-management`
HEAD: `048273f7b69ec6b60ac02f18ddbd1007619bd574`

T0–T4 ยัง Uncommitted ตามคำสั่ง รักษางานเดิมทั้งหมด ไม่มีการเปลี่ยน Branch/Commit/Push/Merge/Deploy
ไม่รัน Migration, Reapply หรือแก้ Ledger และไม่มีการเชื่อม Production/Staging/GEE/Cloud

**T4 COMPLETE ใน Local Synthetic Scope** พร้อมเสนอ T5 เพื่อขออนุมัติแยกเท่านั้น
ยังไม่ได้เริ่ม T5 หรือ Phase อื่น
