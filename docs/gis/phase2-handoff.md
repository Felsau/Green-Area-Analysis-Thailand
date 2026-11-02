# Phase 2 — LDD Upload & Management / Handoff

29 ตุลาคม 2026 · **PARTIAL — Local Upload/Validation พัฒนาแล้ว; รอ Final Acceptance Review**

## 1. เป้าหมายและขอบเขต

ต่อยอด Phase 1 ให้ Officer/Admin อัปโหลด Shapefile ZIP จริงผ่านเว็บไซต์ จัดเก็บต้นฉบับ
สร้าง Edition ส่ง Queue ไปตรวจด้วย Linux Worker และอ่านรายงานได้ใน Local Sandbox
ข้อมูลทดสอบทั้งหมดเป็น Synthetic; ยังไม่มีหลักฐานจากชุด LDD ทางการหรือ Production
ไม่เริ่ม Phase 3 ไม่เชื่อม GEE/Cloud ไม่ Deploy และไม่ Commit/Push

## 2. สิ่งที่พัฒนาและไฟล์ที่เกี่ยวข้อง

| ส่วน | ไฟล์ / การเปลี่ยนแปลง |
|---|---|
| Private Storage ใหม่ | `green-area-backend/gis_ldd_storage.py` — streaming, ZIP preflight, owner proof, quota, lock, immutable SHA256 objects |
| API เดิม | `gis_app.py`, `gis_runtime.py`, `gis_schemas.py`, `gis_service.py`, `routers/gis.py` — เพิ่ม raw ZIP upload/metadata; JSON limits และ Auth เดิมยังใช้ต่อ |
| Forward SQL | `green-area-backend/migrations/034_ldd_upload.sql` — `gis.ldd_uploads`, LDD protocol/RPC/report invariants; เก็บ V1/V2 compatibility delegates |
| Native Worker ใหม่ | `gis_worker/ldd_provider.py`, `ldd_child.py`, `ldd_worker.py`, `ldd_codes.json`, `province_boundaries.json` |
| Worker เดิม | `gis_worker/worker.py` — hook สำหรับ request/report/child/RPC; lifecycle เดิมเป็นค่าเริ่มต้น |
| Target Guard | `dev/gis_local/manage.py`, `tests/test_ldd_worker_guard.py` — ยอมรับเฉพาะ LDD container ที่ launcher อนุมัติและ mount อ่านอย่างเดียวที่ตรงกัน |
| UI เดิม | `src/components/GisManagement.js`, `src/utils/gisClient.js` และ Tests — upload/confirmation/status/metadata/native reports; รักษา synthetic workflow |
| Tests/เครื่องมือ Local | `tests/test_ldd_native.py`, `test_ldd_upload_api.py`; `dev/gis_ui/phase2_local.py`, `phase2_checks.py`, `phase2_units.py`, `phase2_linux.py`, `phase2_science_extra.py`, `phase2_audit.py`, `phase2_browser.py`, `phase2_browser.cjs` |

ทางเดิน API: `POST /gis/datasets/{id}/ldd-uploads` และ `GET /gis/ldd-uploads/{id}` ใหม่
ส่วน enqueue/job/attempt/result/history ใช้ endpoints เดิม ไม่เพิ่ม Queue อีกชุด
Upload รับ `application/zip` พร้อม Idempotency-Key และ query expected_revision/CRS/encoding
Actor มาจาก JWT ที่ Auth ตรวจแล้ว ไม่รับ actor/path/URL จากไฟล์หรือ payload

## 3. Storage และการรักษาฉบับเก่า

ต้นฉบับอยู่ใน runtime แยกจาก Repository: `ldd-storage/objects/{SHA256}.zip`
ไม่ได้อยู่ใน public web directory และไม่มี public download endpoint
Server คำนวณ hash/size และสร้าง ID เอง; ตารางผูก dataset/edition/upload actor/time
ใช้ OS lock ป้องกัน upload แข่งกัน, publish แบบ no-replace, read-only file/worker mount
ไฟล์เดิมไม่ถูกเขียนทับหรือลบอัตโนมัติ การอัปโหลดซ้ำคืน association เดิม
แก้ manifest/clone ของ uploaded edition ไม่ได้ ต้องอัปโหลดเป็นฉบับใหม่
ไฟล์ที่ publish แล้วแต่คำสั่ง DB ไม่สำเร็จอาจเป็น orphan ซึ่งยังนับ quota; ไม่มี automatic GC

เพดาน: ZIP 20 MiB, expanded รวม 80 MiB, สมาชิก 64 รายการ, ratio 100,
พื้นที่ Local รวม 256 MiB; idle upload 10 วินาทีและเวลารวม 60 วินาที
ตรวจ EOCD/central directory แบบ bounded ก่อนสร้าง ZipFile เพื่อจำกัด allocation

## 4. LDD Validation และ Runtime

อ่าน .shp/.shx/.dbf/.prj พร้อม .cpg หรือ encoding ที่ระบุ ตรวจ CRS/geometry/attributes/
Thai decoding/feature counts/area/code/province association และ hash ก่อนประมวลผล
Required fields: LUL1_CODE, LU_CODE, Shape_Area (ตารางเมตร); CRS: EPSG:32647/32648/4326
รองรับ UTF-8, CP874, TIS-620 ตาม metadata ที่ตรวจได้ ไม่ใช้ silent replacement
Unknown Codes ทำให้ไม่ผ่าน พร้อมเก็บจำนวนและพื้นที่ ไม่ทิ้งพื้นที่เงียบ ๆ
ใช้ legend 96 รหัสและขอบเขต 77 จังหวัดที่นำมาจาก Repository พร้อม hash คงที่

Linux ที่รันจริง: Python 3.11.17, Rasterio 1.4.4/GDAL 3.10.3,
Fiona 1.10.1/GDAL 3.9.2, Shapely 2.2.0, NumPy 2.4.6; ไม่มี dependency ใหม่
Worker แยกจาก FastAPI ใช้ custom JWT subject/role gis_native_worker
Native child ไม่ได้รับ credentials; container non-root/read-only/internal network,
1 CPU/1 GiB/PIDs 64; child AS 512 MiB/CPU 20 วินาที/wall 25 วินาที/report 16 KiB
Reuse atomic claim, lease/heartbeat/retry/recovery/fencing เดิม ผ่าน RPC เฉพาะ LDD

## 5. Migration และ Security

034 SHA256: `be6edafd9ea9abd8bddcf90c0ac57a3149e2a1aa3aaa0995cc2c7c060e787069`
ผ่าน Independent exact SQL review ก่อนรันกับ `postgres` และ `gis_t1_upgrade` ในเครื่อง
มี Forced RLS/owner-only ACL, trusted JWT subject, immutable association และ deferred report invariants
Worker ไม่มี direct table privileges หรือสิทธิ์ Admin/service upload RPC
Read-only audit ผ่าน 13 checks: ledger เก่ารวม applied_at ไม่เปลี่ยน, hashes ตรง source,
Migration 000–033 ไม่เปลี่ยน, RLS/ACL/ownership/search_path ใหม่ตรงทั้งสองฐาน
ไม่พบ High/Critical ค้างจาก independent static review และกรณี security ที่ทดสอบ

รอบแรก 034 มี syntax error ใน IF/CASE และ transaction rollback จึงยังไม่มี ledger entry
แก้เฉพาะ 034 ที่ยังไม่ถูกใช้ ให้ review exact SHA ใหม่ แล้วรันสำเร็จ ไม่มี reapply/แก้ ledger เก่า

## 6. ผลทดสอบจริง

| ชุด | ผล / ขอบเขต |
|---|---|
| Upload/Storage/Worker/Target Guard Units | 160 Passed; mock Auth/RPC + filesystem จริง |
| Linux Scientific/Worker Units | 59 Passed; รวม wrong CRS/province/encoding, missing attribute, nonpolygon/self-intersection |
| Frontend GIS/Route/App Regression | 67 Passed |
| Backend GIS API/Runtime Units | 75 Passed |
| Backend Legacy/Auth Regression | 81 Passed |
| Frontend Build | ผ่าน; warning chunk ขนาดใหญ่ของ Map/PDF เดิม |
| Actual Auth/API/Storage/SQL/Linux Integration | 60 checks Passed; valid/CP874/composite/unknown/missing DBF, idempotency, ACL, concurrent claim, V1/V2, no activation |
| Focused Worker Recovery 1,500 polygons | 13 Passed: SIGKILL จริง, lease หมดตามเวลา, replacement, fencing, result เดียว, preservation/cleanup |
| SQL Read-only Audit ทั้งสองฐาน | 13 checks Passed |
| Browser Upload/Report/closed lifecycle gates | 22 Passed; Upload→Queue→Worker→รายงานผ่าน/Unknown จริง, metadata, revision conflict, desktop/tablet |
| Browser Roles/Revocation แบบ focused | 8 Passed; Admin grant/Officer/User และถอนสิทธิ์แล้วเข้า GIS ไม่ได้ |

**Stress capacity ที่ไม่ผ่าน:** full integration run มี 60 Pass / 2 Fail
(assertion ที่คาดให้ 15,000 polygons สำเร็จ และ suite failure ที่ตามมา)
ผลจริงคือ NATIVE_MEMORY_LIMIT, retry จนครบแล้ว Failed โดยไม่มี successful result/activation
ไม่ได้เพิ่ม memory limit เพื่อให้ผ่าน และไม่เรียกผลนี้ว่า kernel/cgroup OOM
แก้ความคาดหวังของชุด Recovery ให้ใช้ 1,500 polygons แล้วผ่านครบ ไม่ซ่อน stress evidence เดิม
การเปลี่ยนระหว่าง full/focused run มีเฉพาะ test runner; Application/SQL/Worker SHA256 ตรงกัน

Browser full run เดิมมี 22 Pass / 1 Fail ในขั้นถอนสิทธิ์ เพราะสคริปต์ยังไม่รอรายการ
แบ่งหน้าของเจ้าหน้าที่โหลดครบ แก้เฉพาะสคริปต์แล้วรันเฉพาะ Auth/Grant/Revocation ผ่าน 8/8
เก็บผลเดิมไว้ ไม่อ้างว่า full suite เดิมผ่านทั้งหมด ไม่มีการแก้ Application เพื่อแก้เรื่องนี้
ตรวจภาพ Tablet ที่บันทึกจริงแล้ว รายงาน Unknown และพื้นที่ที่ไม่รู้จักแสดงได้

## 7. Edition Lifecycle และ Preservation

Upload → Draft → Validating → Validated/Failed มี attempt/report/audit จริง
เก็บฉบับเก่าและต้นฉบับครบ ไม่มี auto-activation และไม่เปลี่ยน legacy data source/cache
Activation Gate ยังคงปิด; Browser/API จริงยืนยันทั้ง activation/rollback/withdrawal:
Officer ถูกปฏิเสธ 403 และ Admin ถูกปฏิเสธ 503
**ยังไม่ทดสอบ successful activation/withdrawal/rollback** เพราะยังไม่มี per-dataset gate ที่อนุมัติ
ไม่เปิด gate แบบกว้างเพื่อทำให้การทดสอบผ่าน
การทดสอบทั้งสองฐานยืนยัน ledger/ข้อมูล public เดิมและ profiles เดิมยังอยู่; เพิ่มเฉพาะ fixtures ใหม่
containers ทดลองถูกหยุด/ลบหลังทดสอบ; core Local 4 containers, volumes, DB rows และไฟล์ต้นฉบับยังเก็บไว้

## 8. หลักฐานและวิธีตรวจต่อ

Evidence root (ไม่มี credentials):
`C:\Users\chaya\.codex\visualizations\2026\10\04\01a107d9-ff44-7731-8bc3-91814ffd8d51\t0-local-supabase-20261027-v2\phase2`

- `review-034.json`, `migration-034.json`, `sql-audit.json`
- `unit-tests.json`, `linux-science.json`, `frontend-tests.json`
- `integration-61046497bd9a.json` — full run/stress failure ที่เก็บไว้
- `integration-f3be04c2dd7c.json` — focused recovery/source fingerprint
- `evidence-index.json` — รายการ hashes/source และ browser results
- Browser core: `../phase2-browser/a11ddc8d65/`; focused roles: `../phase2-browser/93f77f3b7e/`

Local API ที่มี storage: ใช้ backend venv Python `-I -B dev/gis_ui/phase2_local.py serve --runtime-dir <owned T0 runtime>`
Browser workflow ที่สร้างเฉพาะ test users/data: `phase2_browser.py --runtime-dir <owned T0 runtime> --node-modules <bundled modules>`
อย่าใช้ production .env/credentials หรือเปิด Gate; ไม่ใช้ docker-compose เดิม

## 9. ข้อจำกัดและการตัดสินใจ

ต้องยอมรับ/ตัดสินใจก่อนขยายการใช้งาน: ขนาดข้อมูลที่ native budget รองรับจริง,
ชุด LDD ทางการพร้อมสิทธิ์และ schema/legend ที่ครบกว่า 96 รหัส,
boundary ที่แม่นยำกว่า (~200 m tolerance ปัจจุบัน) และปีที่เป็น metadata ผู้ใช้ประกาศ
ยังไม่ได้พิสูจน์ไฟล์ LDD ทางการระดับจังหวัด, native kernel OOM, Cloud/Production หรือ GEE
การทำ lifecycle สำเร็จต้องมีการอนุมัติ gate ที่จำกัดและปลอดภัยก่อน ไม่ bypass ใน Phase นี้
Phase 3 ยังไม่เริ่ม ให้ Final Acceptance Review ตรวจหลักฐานและยอมรับขอบเขตก่อน

## 10. Git / ส่งต่อ

Branch: `feature/gis-data-management`
HEAD: `048273f7b69ec6b60ac02f18ddbd1007619bd574`
Working Tree ยังคง dirty ตามงาน T0–Phase 2 ที่ยังไม่ commit; รักษางานเดิมทั้งหมด
ไม่มี branch change/reset/stash/clean/commit/push/merge/PR/deploy
รายงานนี้เป็น handoff เดียวของ Phase 2; ยังไม่ประกาศปิด Final Acceptance หรืออนุมัติ Phase ถัดไป
