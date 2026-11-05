# A6.4d-1 — Offline Live Safety Foundation Handoff

สถานะ: PASS — Offline Foundation / Local Rehearsal; Independent Final Review PASS,
ไม่มี High/Critical ค้าง Actual Live GEE ยัง NO-GO

## ขอบเขตและ Git

- พัฒนาเฉพาะ safety/budget/trusted-result foundation ที่ทดลอง Offline ได้
- Branch `feature/gis-data-management`; parent HEAD `55d88364b187a5de93bd8a053b4925bf4fe73262`
- Commit ที่อนุมัติ: หนึ่ง Local Commit `feat(gis): add offline live execution safety and budget controls`
- ไม่ Push, Merge, PR, Deploy, เปลี่ยน Branch หรือเริ่ม A6.4d-2
- ใช้ SQL Migration เดิม ไม่เพิ่ม Prisma, dependencies, services หรือ images
- `.gitattributes` เพิ่ม exact-byte rules สำหรับ Migration 043–045 และไฟล์
  ที่ผูกกับ evidence ของ A6.4d-1 เพื่อป้องกัน Git แปลง LF/CRLF แล้ว Hash เปลี่ยน
  ไม่แก้ bytes ของ Migration หรือ runtime/test source ที่ผ่านการตรวจแล้ว

## สิ่งที่พัฒนาและข้อเท็จจริง

- `gee_execution_safety.py`: policy ที่ unapproved/disabled และ future diagnostic
  envelope ผูก worker/job/attempt/result/fencing/input/method/output provenance
  โดยยังปฏิเสธ authority เสมอ ไม่มี approved Google Project หรือ principal
- `AccountedTransport`: one-use reservation ก่อน injected evaluation;
  reserved/attempted/completed/uncertain; ไม่คืน budget เมื่อ timeout/ขาด acknowledgement
- `gee_safety_worker.py`: reuse queue/lifecycle เดิมและ Local JWT role แยก;
  preserve shutdown/memory/output errors และแยก request/job/lease failures
- `gee_safety_child.py`: fixed Linux child, clean environment, resource/output
  limits, stop/lease events; ไม่มี credentials/lease token ใน child input
- Candidate เป็น injected, immutable, non-publishable และ Edition ยัง draft;
  ไม่มี activation, publication, cache mutation หรือ real Live startup
- ดูรายละเอียด protocol/authority/limits ที่ `a6-4d1-contracts.md`

## Migration / Review / Local Apply

Migration `045_gis_execution_safety.sql` SHA256:
`fed94e4efaf6ed2d339e0bb36f44c0dcb8bc4ef34a8d6738087fe0e888f17be8`

เพิ่ม forced-RLS tables `gee_safety_sessions`, `gee_safety_jobs`,
`gee_safety_requests`; เพิ่ม worker/readiness RPC สำหรับ role
`gis_gee_safety_worker` เท่านั้น Reuse inputs/requests/attempts/results/candidates,
receipts/audit และ queue เดิม ผ่าน forward-only function wrappers/constraints
พร้อม deferred integrity และ Edition -> Job -> Session -> Reservation lock order

- Independent exact SQL/auth/scientific/native-boundary source review: PASS;
  High/Critical ที่พบระหว่าง draft แก้และ review ซ้ำก่อน probe/apply
- Full lifecycle rollback probe ผ่าน `postgres` และ `gis_t1_upgrade` ก่อน apply
- Apply 045 ครั้งเดียวใน Local ทั้งสองฐาน; SHA ตรง Ledger; ไม่ reapply/UPDATE Ledger
- Review metadata: `dev/gis_local/gee-safety-review.json` เก็บ pre-apply และ
  latest reviewed worker hash; worker ปรับ safe error classification หลัง apply
  โดย SQL ไม่เปลี่ยน และทดสอบ latest source ใหม่แล้ว
- Local operator ตรวจ runtime/container/database identity, gate และ applied
  checksums; การจำลอง checksum mismatch ทำในหน่วยความจำเท่านั้นและ fail closed

## ขีดจำกัดที่พิสูจน์ Offline

4 logical jobs/session; 32 reservations รวมทุก state และทุก request kind;
one global running job และหนึ่ง JWT subject ที่ผูกกับ session;
สอง application attempts รวม recovery; 120 วินาที/request;
180 วินาทีจาก first attempt รวม retry/backoff/restart; immutable 20-minute window

Worker ไม่สามารถสร้าง/รีเซ็ต session หรือใช้ new idempotency key คืน budget ได้
การเพิ่ม reference/SDK retry ต้องจอง request แยก ไม่ใช่เพิ่ม retry ฟรี
ข้อจำกัดดังกล่าวยังไม่ใช่การรับรอง actual SDK HTTP interception หรือ hard EECU/cost cap
การหยุด local process ไม่ใช่หลักฐานว่า remote GEE computation ถูกยกเลิก

## ผลทดสอบจริงล่าสุด

| ชุด | ผล |
| --- | --- |
| Windows Python 3.12 focused unit/regression | 288 PASS, 12 Linux-only SKIP |
| Linux x86_64 Python 3.11.17 / Pydantic 2.13.4, network none | 280 PASS |
| Real Local Auth/SQL safety suite | 61 PASS, source 9/9 ตรง |
| Active stop/session expiry/exact-error/latest worker boundaries | 20 PASS, source 38/38 ตรง |
| Existing Mock/Offline SQL/Auth queue regression | 57 PASS |
| Existing Injected V2 SQL/Auth queue regression | 55 PASS |
| Read-only preservation | 25 PASS |
| Actual role/ACL/definer/ownership checks | ทั้งสองฐาน PASS |
| Fail-closed checksum/review mismatch | ปฏิเสธและ Ledger ทั้งสองฐานไม่เปลี่ยน |

มี actual concurrent reservations/claim/complete, real 60s lease expiry/recovery,
stale-token rejection, actual 120s request timeout และ 180s logical deadline
ข้าม retry รวม heartbeat และ exact `GIS_SAFETY_JOB_TIMEOUT`
Linux tests ใช้ fixed native subprocess จริง รวม timeout kill และ automatic
stop/lease-event binding การทดสอบ queue ใช้ actual Local Auth/SQL แต่ injected compute
ไม่ใช่ actual Google execution หรือ live Linux daemon

Session test ใช้ **session ใหม่ที่เกิดพร้อม timestamp จำลองอายุ 19m30s**
แล้วรอข้าม window edge จริง ไม่ได้รอครบ 20 นาที และไม่แก้ timestamp ของข้อมูลเดิม
exact-error test เพิ่ม attempt ใหม่ที่เกิดเก่าตาม fixture แยกจาก actual elapsed run

ผลรอบเก่าที่ Fail จาก test query นับ Index เป็น Table และ source เปลี่ยนกลางรัน
ยังถูกเก็บไว้ ไม่แก้ evidence ย้อนหลัง รอบล่าสุด rerun หลังตรึง source ผ่านแล้ว
ผลบน Windows/Linux มี test overlap จึงไม่รวมเป็นจำนวน test ที่ไม่ซ้ำกัน

## Data Preservation / Isolation

Migration 000–044 และ protected source/evidence เดิม 338 ไฟล์ไม่เปลี่ยน
Ledger rows/timestamps เดิม, profiles เดิม, GIS rows/artifacts/history/active
pointers และทุก public legacy table ยกเว้น profiles ที่เพิ่มเฉพาะ test users คงเดิม
Cache ที่ไม่ว่างถูกเทียบ row hashes จริง: primary NDVI annual 3, LST annual 3,
Saved Areas 3; upgrade NDVI annual 1, district NDVI annual 1, LST annual 1
ไม่มี broad cache clear; broad activation gate false และ queue idle หลังทดสอบ

ใช้ existing Local Supabase Core 4 containers/volumes เดิมและ existing Linux
test image; temporary test containers ใช้ --rm ไม่มี cloud resources/credentials
หรือ production/staging connection ไฟล์ evidence เดิม 5 ไฟล์ยัง untracked
Raw runtime evidence อยู่นอก Repository และไม่รวมใน Commit

## ตำแหน่งหลักฐานนอก Git

ใต้ `C:\Users\chaya\.codex\visualizations\2026\10\04\01a107d9-ff44-7731-8bc3-91814ffd8d51\`:

- `a6-4d1-safety/`: focused-0c37bbae XML/result/source, Linux result/log,
  old-protocol-regression, injected-v2-regression, regression-source-verification,
  preservation-final, security-schema-final, fail-closed-checks, runtime-versions
- `t0-local-supabase-20261027-v2/a6-4d1-safety/`: probe, migration-045,
  checks-0f43a3fdace3 JSON/source, boundaries-097641f86a40 JSON

## Not Tested / Remaining Live Blockers / Next Task

ยังไม่ทดสอบ real satellite parity, Cloud/GEE/IAM/Billing/Quota, actual SDK retries
หรือ physical EE HTTP accounting, authenticated transport attestation,
remote cancellation, live daemon restart หรือ actual Live compute
ไม่ทดสอบ full 20-minute elapsed session, new native OOM injection หรือ UI/browser
suite ซ้ำ เพราะ UI/source เดิมไม่เปลี่ยน ฐาน upgrade ผ่าน SQL probe/schema/ACL/
preservation แต่ real PostgREST/Auth E2E ใช้ primary เท่านั้น

ก่อน A6.4d-2 ต้องอนุมัติแยก: verified Sandbox identity/account readiness,
least-privilege Google identity/credential channel, approved image และ restricted
egress, transport attestation และทุก physical request/retry accounting รวม
external EECU/cost monitoring **Actual Live ยัง NO-GO** ห้ามเปิด gate/รันทดลองอัตโนมัติ
