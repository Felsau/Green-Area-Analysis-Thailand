# Phase 1 — T2 GIS Backend APIs & Authorization Integration

วันที่: 27 ตุลาคม 2026
Repository: Felsau/Green-Area-Analysis-Thailand
Branch: `feature/gis-data-management`
HEAD: `048273f7b69ec6b60ac02f18ddbd1007619bd574`

## 1. Executive Summary / ขอบเขตที่ได้รับ

พัฒนา Backend GIS24 HTTP endpoints บน FastAPI เชื่อม Supabase Auth และ T1 SQL
transaction functions อย่างปลอดภัย ทดสอบเฉพาะ Local Sandbox ใช้ SQL Migration
เดิมต่อด้วย Forward030 ไม่ใช้ Prisma ไม่เพิ่ม Dependency หรือบริการเสียเงิน

| ชุดทดสอบที่รันจริงใน T2 | ผล | ขอบเขตหลักฐาน |
|---|---|---|
| GIS API/JWT/Target Guard unit | 75 Pass / 0 Fail | Mock clients/runtime แยกจาก E2E |
| Existing Auth/API + GIS mount regression | 81 Pass / 0 Fail | Mock Supabase, ปิด dotenv และปฏิเสธ Network ภายนอก |
| Local Supabase integration | 126 Pass / 0 Fail | TestClient→FastAPI→SDK→Auth/PostgREST→PostgreSQL จริง |
| Forward030 บนสองฐาน Local | Pass | DDL+ledger atomic, ไม่แก้027–029ย้อนหลัง |
| Legacy preservation หลัง API tests | Pass | 15ตารางที่ไม่ใช่ profiles คงเดิม, profile เดิม12แถวคงเดิม, เพิ่มจำลอง3แถว |
| Independent Security/SQL review | ไม่มี High/Critical ค้างในขอบเขตตรวจ | Static review แยกจากผู้รันทดสอบ |

ผล126เคสใช้เวลาประมาณ328วินาที ไม่ใช่การทดสอบ Browser หรือ Hosted Backend
มีบางกรณี JWT ที่ระบุ Not Tested ด้านล่าง ไม่เหมารวมว่าครบทุก Negative Fixture
ยังไม่มี Python Worker, GIS UI, การอ่านไฟล์ GIS จริง, GEE/Cloud หรือ Deployment

## 2. สิ่งที่พบจากระบบเดิมและแนวทางที่เลือก

- T0/T1 ใช้ private gis schema และ service-role-only `gis_command`/`gis_read`
  โดย Actor ต้องมาจาก Backend ที่ตรวจ user JWT แล้ว
- T1 ยังขาด Result/report DTO, Officer pagination, typed filters และ service-only
  readiness RPC จึงเพิ่มเฉพาะสิ่งเหล่านี้ด้วย030
- Ledger ของT1จำกัด version27–29 จึงต้องขยาย CHECK แบบ forward ใน030
  ไม่แก้ source/checksum/rows ของ027–029
- `dependencies.py` โหลด dotenv เมื่อ Import และ `main.py` อาจเริ่ม GEE ตอน Import
  จึงสร้าง GIS-only local factory แยก ไม่ใช้ main เป็นทางรัน Integration
- Legacy require_user มี network fallback ไป Supabase Auth แต่การตรวจ JWT local
  ไม่บังคับ issuer; GIS ใช้ Auth get_user แนวทางเดียวกัน พร้อม strict claims แยก
  ไม่ refactor Authentication หรือ Analysis APIs เดิมนอกขอบเขต
- ใช้ backend .venv เดิม Python3.12.10, FastAPI0.136.3, Supabase2.31.0,
  PyJWT2.13.0, Pydantic2.13.4, httpx0.28.1; ไม่มีการติดตั้งแพ็กเกจ/แก้ lockfile
- Runtime ฐานเป็น Docker Linux/PostgreSQL17.6 ที่ T0 สร้างไว้เดิม

## 3. API ที่พัฒนาจริง

ทุก path อยู่ใต้ `/gis`; JWT required ทุก endpoint; POST/PATCH ต้องมี
Idempotency-Key UUID เดียว ไม่มี endpoint อัปโหลด/ลบถาวร/Worker/Cache/GEE

| Method | Path | หน้าที่ |
|---|---|---|
| GET | /me | Capabilities และ Backend/Database gates ที่ใช้จริง |
| GET | /provinces | Province references เดิม |
| GET/POST | /datasets | Filtered page / create |
| GET/PATCH | /datasets/{id} | Detail / title พร้อม expected_revision |
| GET/POST | /datasets/{id}/editions | Edition page / metadata draft |
| GET/PATCH | /editions/{id} | Detail / edit draft พร้อม revision |
| POST | /editions/{id}/clone | Clone เป็น draft ใหม่ |
| POST | /editions/{id}/validation-jobs | สร้าง SQL job จริง ตอบ202ทันที |
| GET | /editions/{id}/history | Audit cursor page |
| POST | /datasets/{id}/activation, /rollback | Admin + two gates + reason/revision/pointer |
| POST | /editions/{id}/withdrawal | Admin + explicit replacement/null pointer |
| GET | /jobs | Filtered page |
| GET | /jobs/{id} | สถานะจริงและ stored result/null |
| GET | /jobs/{id}/attempts, /result | Attempt history / safe protocol report |
| POST | /jobs/{id}/retry | Revision/hash และ retry budget |
| GET/POST | /officers | Admin page / grant โดย subject UUID |
| POST | /officers/{id}/revocation | Admin revoke พร้อมเหตุผล |

Pagination default20/max100, opaque base64 cursor จาก `(created_at,id)`;
Dataset/Job filters และ parent checks อยู่ทั้ง Pydantic/SQL
ผล Mutation คืน SQL receipt body/status200/201/202 เดิม ไม่คำนวณผลสำเร็จเอง

## 4. Authentication / Authorization / Target Safety

GIS ไม่เชื่อ Actor ID, Role หรือ Permission จาก Body/user_metadata/Admin Header
ตรวจ issuer ตายตัวของ Local Auth, audience, role=authenticated, exp/iat/nbf,
canonical UUID sub และต้องผ่าน Auth get_user จริงซึ่งคืน UUID ตรงกัน
Unsigned claims เป็นเพียงการตรวจเพิ่มเติม ไม่ใช่หลักฐานยืนยันลายเซ็น

| ตัวตน | พฤติกรรมที่ยืนยันจาก Tests |
|---|---|
| ไม่มี/ผิด/Unsigned JWT | 401 |
| User ที่ใส่ role=admin ใน user_metadata | meยังไม่มี GIS rights; read/write/grantถูก403 |
| User/Officer ส่ง Admin Header | ไม่เพิ่มสิทธิ์ |
| Officer | Read/Create/Edit/Clone/Enqueue/Eligible retry ผ่าน; Grant/Revoke/Activate/Withdraw403 |
| Admin | Grant/RevokeและSandbox actionsผ่านเมื่อ Gate/revision/pointerถูกต้อง |
| Officer ถูกถอนสิทธิ์ | meเปลี่ยนทันที; CatalogและReceipt replayถูก403 |
| Authenticated เรียก PostgREST service RPC ตรง | 42501; private gis schema ไม่เปิดให้เข้าตรง |

SDK Auth/service clients แยกกัน ไม่ให้ Login เปลี่ยน service Authorization
อ่านเฉพาะ T0-generated development API keys ใน Local Gateway ที่ยืนยันแล้วเข้า
หน่วยความจำ ไม่อ่าน Production.env/GEE หรือ Signing Secret และไม่ส่ง service key
ไป Browser/Response/Report

Runtime เริ่ม disabled ใน main และ factory เปล่า ไม่มี ambient Environment ใด
เลือก Production หรือเปิด GIS ได้เอง ต้องสร้าง Runtime แบบระบุ Local proof
ตรวจ fixed loopback URL, instance, DB/cluster/mode/baseline fingerprint,
Container ownership/health และ service-only SQL readiness/version30
ก่อน Auth และก่อน SQL operation รวมก่อน retry; ปิด proxy/redirect และมี timeout
Unknown/Production Target tests ปฏิเสธก่อนสร้าง Client/ส่ง Mutation โดยไม่ลองต่อ
Production จริงตามข้อจำกัดของงาน

## 5. SQL Integration / Transaction / Error Safety

030เพิ่ม projection/read functions, result DTO, Officer pagination, filters,
parent404, six GIS-only cursor indexes, readiness และ PostgREST reload-on-commit
ไม่เปลี่ยน command/worker/state functions หรือเขียน legacy Cache/GEE

SHA256030 ที่ตรวจอิสระและนำไปรัน:
`0c6cd4b6fb3fe964dfcba848bf392a9b93cea87be7c15fd214cfe5e435b6f113`
Runner ใช้ bytes เดียวกับที่ตรวจและ INSERT ledger ใน transaction เดียว
ผลตรวจสดหลังงาน: ledger27–29ยัง checksumเดิม, เพิ่ม30; activationfalseทั้งสองฐาน

- Concurrent API requests same actor/key สร้าง Dataset/Receipt/Auditอย่างละ1
- Replay คืน receiptก่อนตรวจ stale revision แต่หลังตรวจ permission ปัจจุบัน
- Enqueueจริงได้ queued/resultnull และไม่มี attempt จนกว่าจะมีผู้ประมวลผล
- Semantic dedup active202/terminal200, explicit retryมีได้หนึ่ง child;
  stale revision/hash, retry-chainและงบ retryผิดถูก409
- Activation/Rollback/Withdrawalต้องสอง GateและSynthetic validated result;
  แทนฉบับ/ย้อนฉบับเก็บผลเก่าไว้ และ explicit withdrawalล้างpointerได้
- HTTP401/403/404/409/422/429/503แยกตามกรณี; ไม่คืน SQL/SDK exception/inputลับ
- Strict Pydantic, body64KiB, ไม่รับ NaN/Infinity/unknown fields/authority fields
- CORSไม่เพิ่ม Origin/wildcard; mainเพิ่มเฉพาะ Idempotency-Key header
  GIS429มีรูปแบบเฉพาะ ส่วน Legacy delegateกลับhandlerเดิม

## 6. สิ่งที่ทำจริงใน Integration และข้อจำกัดผลทดสอบ

สร้าง3บัญชีผ่าน Auth Admin APIและSign-inผ่าน Authจริง โดย password/JWTอยู่ในmemory
เพิ่มเฉพาะ2Dataset/4Edition/4Job และ profile ของผู้ใช้ใหม่3แถว ไม่ลบข้อมูลเดิม
ใช้บริการ Auth/PostgRESTบนฐานหลัก `postgres`; ฐาน `gis_t1_upgrade`ทดสอบ030DDL
เท่านั้น ไม่อ้างว่าเป็น Supabase Auth deployment เต็มชุดที่สอง

การทดสอบ Result/Activation/Retry บางกรณีเรียก T1 SQL Worker Functions ด้วยตนเอง
เป็น Fixture Setup ให้เกิดสถานะ succeeded/failed จริงใน DB ไม่มี Python Worker
ไม่มีการประมวลผลไฟล์ GIS หรือ API รายงานสำเร็จปลอมจากการ Enqueue
งานที่failed2งานเป็นข้อมูลจำลองเพื่อทดสอบ Retry ไม่ใช่ Test Fail

| รายการที่ยังไม่ยืนยัน | สถานะ |
|---|---|
| Expired/wrong-issuer/wrong-audience JWT ที่ยังมีลายเซ็นจริงและถูกต้อง | Not Tested E2E; มี strict-claim Unit และ tampered-token integrationแยก |
| Python Worker process / actual worker LOGIN / kill-restart | Not Tested; T3 |
| Shapefile/GeoTIFFจริง, Native GIS, NDVI/LST scientific correctness ในT2 | Not Tested |
| Browser GIS UI / Hosted HTTP serverจริง | Not Tested; API E2Eใช้ TestClient ASGI |
| Cloud/GEE/Production/Staging/Deploy | ไม่ดำเนินการ |
| Load/soak/ทุก concurrency interleaving / distributed rate limiter | Not Tested |

Harnessต้องรันเดี่ยวบน Queue สังเคราะห์ที่ว่าง ไม่มี Producer/Workerอื่นร่วม
ในรอบนี้คืนGatefalse และงานค้างqueued/runningเป็น0; เก็บข้อมูลจำลองทุกแถวไว้
Rate limitเป็นprocess memoryตามแนวทางเดิม ไม่ใช่ distributed quota

## 7. Independent Review / ปัญหาที่พบ

ตรวจอิสระทั้ง SQLก่อนรัน และ API/runtime/harnessหลังแก้ข้อเสนอ ไม่มี High/Critical
ค้างในขอบเขตนี้ รายละเอียดใน `t2-security-review.md` ไม่ใช่ Production approval
ผู้ตรวจไม่ได้รัน SQL/Testsเอง ผล75/81/126มาจากการรันของผู้ดำเนินงาน

แก้ข้อเสนอเรื่อง safe result projection, Job filters, JWT recursion/overflow,
ซ่อน lease time, CORS body-guard order, GIS429, combined gates, duplicate Auth
และ Cleanup queue order ก่อนสรุปผล

Windows TestClientติดสิทธิ์ socketpair ใน restricted processครั้งแรก จึงรันผ่าน
สิทธิ์ Local loopbackที่อนุมัติ ไม่ใช่ปัญหา API ไม่มีการเปิด NetworkภายนอกในUnit
มีdeprecation warningของTestClient/httpxที่pinเดิม แต่Testsผ่าน ไม่เพิ่มDependency

Auto-approvalปฏิเสธแนวทางอ่าน Signing Secretเพื่อสร้าง Negative JWT จึงไม่ทำ
เปลี่ยนเป็น Auth-issued/tampered tokensและระบุ valid-signature altered claimsเป็น
Not Tested ไม่มีการอ่านSigning Secretหรือเลี่ยงการตรวจ
มีช่วงที่ระบบตรวจอนุมัติทำงานต่อไม่ได้เพราะลิมิต จึงหยุดก่อน Action และทำต่อหลัง
ผู้ใช้สั่ง ไม่มีการเปลี่ยนเครื่องมือเพื่อข้ามการตรวจนั้น

## 8. Files Changed / Git / สิ่งที่ยังไม่ได้ทำ

แก้ไฟล์เดิมเพียง `green-area-backend/main.py`: GIS mount disabled, header CORS
และ scoped rate-handler dispatch (7บรรทัดเพิ่ม/3บรรทัดลบ)

ไฟล์ใหม่: `gis_runtime.py`, `gis_app.py`, `gis_schemas.py`, `gis_service.py`,
`routers/gis.py`, `migrations/030_gis_api_reads.sql`, tests GIS3ไฟล์;
`dev/gis_local/t2_local.py`, `t2_checks.py`, `t2_integration.py`, `t2_preservation.py`,
`t2-review.json`, `T2-README.md`; SQL contract/review/handoff/evidenceในdocs/gis
รายละเอียดHash/line countและรายเคสอยู่ใน `t2-test-evidence.json`

T0/T1และMigration000–029คงเดิม ไม่Reset/Stash/เปลี่ยนBranch
Branch/HEADตามหัวรายงาน; ทุกไฟล์ใหม่ยังไม่Commit ไม่มีPush/Merge/Rebase/PR/Deploy
ไม่เพิ่มบริการเสียเงินหรือDependencies ไม่แก้Landing/Frontend/Analysis logic

## 9. Handoff ก่อน T3 / การตัดสินใจถัดไป

พร้อมให้ตรวจรับ T2 ในขอบเขตที่ทดสอบได้ แต่ยังไม่เริ่ม T3–T5 หรือ Cloud
ก่อน T3 ต้องอนุมัติตัวตน Workerสิทธิ์จำกัด, native validatorและresource bounds,
การทดสอบprocessจริง/lease recoveryและสิทธิ์อ่านแหล่งข้อมูล โดยไม่ใช้service keyให้Worker
ต้องคงข้อแยก scientific validationออกจากSQLprotocol fixturesและAPIqueue semantics

Runbook: `dev/gis_local/T2-README.md`; หลักฐานเต็มแบบไม่ใส่Secretsอยู่ที่
`C:\Users\chaya\.codex\visualizations\2026\10\04\01a107d9-ff44-7731-8bc3-91814ffd8d51\t0-local-supabase-20261027-v2\t2`
สรุปที่พกไปตรวจได้คือ `docs/gis/t2-test-evidence.json`
หยุดเฉพาะ ContainerของT0เมื่อจบ เก็บVolumes/ฐาน/Fixturesไว้ ไม่ลบข้อมูล
หลังหยุด DB/Auth/Gateway แสดงExit0 ส่วนRESTแสดงExit255เหมือนข้อจำกัดที่บันทึกในT1
ทุกตัวหยุดแล้ว สาเหตุREST Exit255ยังไม่ยืนยัน ไม่ได้เปิดLogsหรือแก้configuration
นอกขอบเขต; ก่อนหยุดบริการและIntegration126เคสผ่าน
