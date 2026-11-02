# Phase 1 — T1 GIS Database Schema & Authorization: Handoff

วันที่: 27 ตุลาคม 2026
Repository: Felsau/Green-Area-Analysis-Thailand
Branch: `feature/gis-data-management`
HEAD: `048273f7b69ec6b60ac02f18ddbd1007619bd574`

## Executive Summary

พัฒนาและทดสอบฐาน GIS เฉพาะ Local Sandbox แล้ว: ใช้ SQL Migration เดิมต่อด้วย
027–029 ไม่เพิ่ม Prisma หรือ Dependency ไม่สร้าง API, Python Worker, UI หรือ Cloud
ไฟล์ T0 ที่รับช่วง 12 ไฟล์ยังตรง SHA256 เดิม ไม่แก้ Business Logic หรือ Migration 000–026

ผลทดสอบที่ยืนยันจริง:

| ชุดตรวจ | ผล |
|---|---|
| Pure Guard/Contracts/Runtime policy tests รวม T0+T1 | 40 Pass |
| SQL suite บนฐานหลักที่คง vendor Auth เดิม | 83 Pass / 0 Fail |
| SQL suite บนฐาน Upgrade ที่มี Sentinel เดิม | 83 Pass / 0 Fail |
| Supplemental Atomicity / Lease-wait บนฐานหลัก | 6 Pass / 0 Fail ในรอบแก้ Assertion แล้ว |
| Fresh 000–026 แล้ว 027–029 | Pass |
| Upgrade 026 + Sentinel →029 โดยไม่ replay legacy | Pass |
| ข้อมูล 16 ตาราง + โครงสร้าง Legacy ที่ตรวจ ก่อน/หลัง GIS Migration | ตรงกันทั้งสองฐาน |
| Independent SQL/Security review ก่อนใช้ Migration ใหม่ | ไม่มี High/Critical ค้าง |

83 เคสบนสองฐานเป็นชุดเดียวกันที่รันซ้ำเพื่อยืนยันเส้นทาง Upgrade ไม่ใช่ 166 เคสคนละแบบ
จำนวนเก่า L1–L4=78 และ L5–L6=65 เป็นบริบทก่อนหน้านี้ ไม่ได้นับเป็นผลของ T1 รอบนี้

## 1. เป้าหมายและขอบเขตที่ได้รับ

เตรียม Application Schema เดิมในฐาน Local ที่ยืนยันตัวตนแล้ว พัฒนา GIS Foundation,
Authorization/RLS, Transaction Functions, Idempotency และ SQL Queue Foundation
ตรวจอิสระก่อนนำ Migration ใหม่ไปรัน และหยุดหลัง T1 เพื่อรออนุมัติงานถัดไป

รับช่วงไฟล์ T0 ที่ยังไม่ Commit โดยไม่ Reset/Stash/เขียนทับ ไม่เปลี่ยน Branch
ไม่เชื่อมต่อ Production/Staging, Supabase Cloud, GEE หรือเปิด Billing/IAM

## 2. สิ่งที่พบจากโค้ดและ Environment จริง

- Legacy SQL มี 000–026 รวม 27 ไฟล์; Backend เดิม FastAPI/Supabase Auth/PostgreSQL
- 007 ล้าง District Cache; 017 ลบ Cache ที่ซ้ำ; 019 ลบ Saved Areas ที่ไม่มี user_id
  จึงห้ามใช้ชุดเก่านี้ replay บนฐานที่มีข้อมูล
- 018 เปิด RLS แต่ไม่ล้าง permissive policy ที่อาจ drift; ตรวจ constraint บางรายการ
  จากชื่อรวม; 022 เพิ่ม FK แบบ rerun ไม่ได้ และมีช่องว่าง NULL district ใน composite FK
  ประเด็นเหล่านี้เป็นข้อจำกัดเดิม ไม่ได้ซ่อมใน T1
- T0 verification เดิมคาดว่าไม่มี application schema จึงต้องใช้ stage-aware proof ใหม่
- Docker Engine 29.8.0, Linux amd64, PostgreSQL 17.6 จาก image pin เดิม
- Migrator local postgres ไม่ใช่ superuser แต่มี CREATEDB/CREATEROLE
- Host harness ใช้ Python 3.12/stdlib; ไม่มีการติดตั้งแพ็กเกจหรือแก้ Runtime image
- ก่อน baseline ฐานหลักไม่มี public application tables, ไม่มี GIS schema และ Auth users=0

## 3. สิ่งที่ดำเนินการแล้ว

### Local baseline และการรักษาข้อมูล

Runner ใช้ Docker Desktop daemon ในเครื่องแบบระบุชัด และ docker exec ผ่าน Container ID
ที่ตรวจ T0 ownership/image/network/limits/mounts/volumes แล้ว ไม่รับ DSN/Host ภายนอก
ก่อน Mutation ตรวจ cluster `green-area-gis-t0`, DB allowlist, instance และ checkpoint
เมื่อมี GIS ตรวจ marker ของ DB/cluster/mode/baseline fingerprint เพิ่ม

ฐานหลัก `postgres` คง vendor Auth เดิม ส่วน `gis_t1_upgrade` สร้างจาก template0
และคัดลอกเฉพาะ Auth schema ว่างในหน่วยความจำ ไม่คัดลอก rows/owner/ACL
จากนั้นให้สิทธิ์ Auth functions ขั้นต่ำสำหรับทดสอบ Application Schema
ฐานที่สองจึงไม่ใช่การทดสอบ Supabase Auth Service ทั้งชุด

รัน 000–026 แบบ atomic บนฐานว่างทั้งสองชุดเท่านั้น และเก็บ SHA256/checkpoint
ใส่ Sentinel จำลอง NDVI/LST/District NDVI 3 แถวในฐาน Upgrade หลังถึง026
ก่อนและหลัง027–029เปรียบเทียบ Hash ข้อมูลทั้ง16ตาราง, columns, constraints,
indexes, profile functions, Auth trigger และ RLS flags: ตรงกัน
สิ่งที่ตั้งใจเพิ่มใน Legacy คือ column grants และ SELECT policies เฉพาะ gis_owner

### Migration / Schema ใหม่

| ไฟล์ | สิ่งที่เพิ่ม |
|---|---|
| 027_gis_foundation.sql | Owner/worker group roles, private GIS schema, local marker/ledger, datasets/editions/officers/audit/receipts/SQL synthetic fixtures, authorization/manifest helpers, FORCE RLS |
| 028_gis_queue.sql | jobs/attempts/results, FK/indexes, atomic claim/heartbeat/complete/fail/recover, lease/token fencing และ bounded retry |
| 029_gis_transactions.sql | immutable/deferred integrity triggers, service-only command/read wrappers, worker-only wrapper, activation/withdraw/rollback/idempotency/audit transactions |

ตารางภายในใช้ชื่อสั้น `gis.datasets`, `editions`, `officers`, `jobs`, `attempts`,
`results`, `audit`, `receipts`, `synthetic_fixtures`, `environment`, `schema_migrations`
ตรงแนวคิด Dataset/Edition/Officer Grant/Processing Job/Job Attempt/Result ตาม Contracts

- Dataset identity: จังหวัด/ปี CE/เดือน/kind/purpose; LDD เป็นรายปี month=0
- Edition: draft/validating/validated/withdrawn; active มาจาก pointer เท่านั้น
- Pointer มี composite FK, ตรวจผลสำเร็จที่ตรง revision/hash/validator และ synthetic fixture
- Inputs ที่ validate แล้วแก้ไม่ได้ ต้อง clone; ไม่เขียน GEE Assets หรือ Cache เดิม
- gis_owner เป็น NOLOGIN/non-super/NOBYPASSRLS; GIS ทุกตาราง FORCE RLS
- `profiles.role` คง user/admin; Officer แยกตารางและตรวจสิทธิ์สดทุก mutation/replay
- Audit/Result/Receipt แก้ประวัติไม่ได้ ยกเว้น actor/subject ถูก FK SET NULL เมื่อลบบัญชี
- Receipt key แยกตาม actor/request UUID; replay คืน status/body เดิมก่อนตรวจ stale revision
- ไม่เก็บสำเนา actor UUID ใน immutable JSON; ไม่มีระบบล้าง PII ที่ผู้ใช้พิมพ์ใน free text เอง

### Queue / Transaction Contracts

Public `gis_command(...)` และ `gis_read(...)` เรียกได้เฉพาะ service_role;
`gis_worker(...)` เรียกได้เฉพาะ gis_worker ส่วนฟังก์ชัน/ตารางใน private schema
ไม่เปิดตรงให้ anon/authenticated/service_role/worker

Actor parameter เป็นค่าที่ Backend ต้องยืนยันจาก user JWT; service-role ACL เป็น
trust boundary ของ SQL ไม่ใช่การยืนยัน JWT ของผู้ใช้ใน T1 และไม่ใช่ request-body actor

Claim ใช้ SKIP LOCKED และจำกัด1 running job; Lease60s,3 attempts/run,
backoff5/20s+jitter0–2s, explicit retryได้หนึ่ง child รวมไม่เกิน6 attempts
Heartbeat/complete/recover ตรวจเวลา wall clock หลังได้ Row Lock และตรวจ owner/token
การจบงานบันทึก result/job/edition/attempt/audit พร้อมกัน ไม่ auto-activate

## 4. ผลทดสอบ Authorization และ Transaction

| กรณี | ผล / ขอบเขตหลักฐาน |
|---|---|
| anon/authenticated อ่าน/เขียน private tables หรือเรียก service RPC | ปฏิเสธ SQLSTATE42501 |
| service_role เข้าตาราง GIS ตรง หรือเรียก worker RPC | ปฏิเสธ |
| gis_worker แก้ Cache/ตาราง GIS/เรียก command RPC | ปฏิเสธ |
| RLS หลังให้ temporary ACL ใน rollback fixture | authenticated อ่านไม่พบแถว และ insert ถูกปฏิเสธ |
| User ทั่วไปเรียก me | ได้สิทธิ์ว่าง; อ่าน/แก้ Catalog ไม่ได้ |
| Officer สร้าง Dataset/Draft/Queue/Retry | ผ่าน; grant officer/activate ไม่ได้ |
| Admin grant/revoke/activation/withdraw/rollback | ผ่านเมื่อ Sandbox gates และ revision/pointer ถูกต้อง |
| ถอน Officer แล้ว replay request เดิม | ถูกปฏิเสธจากสิทธิ์ปัจจุบัน |
| Same actor/key/payload / ต่าง payload | ผลไม่ซ้ำ / conflict |
| Mutation ล้มเหลวตอน INSERT Audit | ผลและ Receipt ถูก rollback พร้อมกัน |
| Claim งานเดียวพร้อมกันสอง SQL Clients | ได้งานเพียง1 Client; ผู้ส่งปิด connection แล้วงานยังอยู่ |
| Lease ผิด owner/token/หมดเวลา/attemptเก่า | heartbeat/complete ถูกปฏิเสธ |
| Lease หมดระหว่างรอ Row Lock จริงประมาณ3วินาที | ปฏิเสธด้วย GIS_STALE_LEASE หลังได้ lock |
| Recovery/Retry/Max attempts/ไม่ให้ retry-chain | ผ่าน รวม terminal failure คืน Edition เป็น draft |
| State/hash/identity/active result ผิด / แก้ Audit/Result | ถูก trigger/constraint ปฏิเสธ |
| ลบบัญชีจำลองภายใน rollback fixture | Catalog/Jobs/Results คงอยู่, actor FK NULL, grant subject cascade |

ชุด SQL บังคับ deferred constraints ก่อน rollback จึงตรวจ final invariants จริง
Concurrency/Lease-wait fixtures ที่ commit ถูกเก็บไว้ และจบงานผ่าน Queue protocol
ไม่ได้ลบข้อมูลที่มีอยู่ก่อนงานนี้ ไม่มี Python Worker จริงใน T1

## 5. Independent Review และปัญหาที่พบระหว่างทำ

มี independent static review แยกจากผู้เขียน/ผู้รัน ก่อนใช้027–029
แบบร่างมี High เรื่องสำเนา actor UUID ใน JSON; แก้และตรวจซ้ำแล้ว
เพิ่ม deferred invariants, result↔attempt FK, account-deletion exceptions,
แก้ lock order/NO KEY UPDATE และ capture reviewed bytes ใน runner
รายงานพร้อม hash: `t1-security-review.md`, `dev/gis_local/t1-review.json`

ปัญหาในขั้นทดลองที่แก้แล้ว โดยไม่แก้ Business Logic/Migration ที่ใช้แล้ว:

- COPY DATABASE จาก postgres ถูก55006เพราะ pg_cron/pg_net จับ Connection;
  ใช้ template0+Auth structure แทน ไม่ terminate งานภายใน
- Restore ครั้งแรกชน public schema (42P06) และ default ACL permission (42501);
  transaction rollback ทั้งชุด แล้ว restore เฉพาะ Auth โดยไม่คัดลอก owner/ACL
- Sentinel ใช้ชื่อ Bangkok ไม่ตรง key `Bangkok Metropolis`; FK ปฏิเสธและ transaction
  rollback ก่อนแก้ข้อมูลจำลองให้ตรง reference
- Pure tests3เคสติด Windows temp permission; ย้าย temp ไปพื้นที่เขียนได้แล้ว40ผ่าน
- Supplemental ครั้งแรกมี1Failจาก Assertion นับ Receipt ของเคสก่อนหน้า; แก้ให้กรอง
  actor ของเคสนั้นแล้ว6ผ่าน ไม่มีข้อบกพร่อง Migration ที่ต้องแก้หลังนำไปใช้

## 6. ยังไม่ได้ทำ / Not Tested / ข้อจำกัด

| รายการ | สถานะ |
|---|---|
| JWT/Auth HTTP→Backend→RPC E2E | Not Tested; ยังไม่สร้าง API ตามขอบเขต T1 |
| Worker LOGIN/Network identity/Process kill-restart จริง | Not Tested; SET ROLE/SQL client เป็นหลักฐานเฉพาะฐานข้อมูล |
| Python/GIS Runtime และไฟล์จริง NDVI/LST ใน T1 | Not Tested; SQL fixture เป็น protocol metadata เท่านั้น |
| Production/Staging/Supabase Cloud/GEE/Cache integration | ไม่ดำเนินการ |
| Dirty production schema หรือ upgradeทุกช่วงประวัติ016→026 | Not Tested; ทดสอบ baseline000–026 และ026→029ที่ระบุไว้ |
| Property-based/soak/load/ทุก lock interleaving | Not Tested; มี concurrency และ lock-wait cases ตามรายงาน |
| ระบบป้องกัน Cloud ที่ HTTP/Worker write boundary จริง | ยังไม่มีให้ทดสอบ; T1 guard ป้องกันเฉพาะ local harness และ SQL marker |

ต้องทดสอบเฉพาะ Queue จำลองที่แยกและไม่มี Worker อื่นร่วมทำงาน ผล Local ไม่ใช่
การรับรอง Production Security หรือการยืนยันความถูกต้องทางวิทยาศาสตร์ของ GIS
Gateway ของ T0 ยังมี ingress bridge ที่อาจออกเครือข่ายได้; ไม่ได้อ้างว่าจับ traffic แล้วเป็น zero-egress

## 7. ไฟล์และสถานะ Git

สร้างเฉพาะ T1: SQL3ไฟล์ข้างต้น; `dev/gis_local/t1_database.py`,
`t1_preservation.py`, `t1-review.json`, `T1-README.md`,
`tests/test_t1_guard.py`, `tests/t1_cases.py`; รายงานนี้, security review และ test evidence
รายละเอียดจำนวนบรรทัด/Hashอยู่ใน `t1-test-evidence.json`

ไฟล์ T0 ทั้ง12ยังไม่ Commit และคง bytes เดิม; tracked diff/staged diff ว่าง
ไฟล์ T1 ใหม่ยังไม่ Commit; Branch/HEADคงเดิม ไม่มี Push/Merge/Rebase/PR/Deploy
Container/ฐานทดลอง/Volumes ถูกเก็บไว้ ไม่ลบ ใช้คำสั่ง T1 resume/stop ตาม Runbook
หลังหยุดรอบสุดท้าย DB/Auth/Gateway แสดง Exit0 ส่วน REST แสดง Exit255
ทุกตัวหยุดแล้ว; การ Resume และชุดทดสอบก่อนหยุดผ่าน สาเหตุ Exit255 ยังไม่ยืนยัน
ไม่ได้เปิด Container logs หรือแก้ PostgREST configuration นอกขอบเขต

## 8. หลักฐานและการส่งต่อ

สรุปที่พกไปตรวจได้: `docs/gis/t1-test-evidence.json`
รายงานจริงแบบรายเคสและ before/after snapshot อยู่ในพื้นที่ทดลองเดิม:
`C:\Users\chaya\.codex\visualizations\2026\10\04\01a107d9-ff44-7731-8bc3-91814ffd8d51\t0-local-supabase-20261027-v2\t1`
ไม่มี Secrets/Tokens/Credentials ในรายงานเหล่านี้ ไม่ต้องเปิด runtime.env หรือ kong.yml

## 9. การตัดสินใจและงานถัดไป — ยังไม่ดำเนินการ

รอผู้ใช้ตรวจรับ T1 ก่อนเริ่ม T2/T3 ไม่มีการเริ่มอัตโนมัติ
ก่อน T2 ให้ยืนยัน backend-attested actor contract, `{status,body}` mapping/error DTO
และเส้นทางอ่านรายงานผล/แบ่งหน้า Officers ที่ยังต้องเติม; SQL ที่ใช้แล้วผูก checksum
จึงต้องใช้ forward migration ใหม่หากแก้ SQL ที่นำไปใช้แล้ว ห้ามแก้ ledger ย้อนหลัง
ก่อน T3 ให้อนุมัติตัวตน Worker แบบสิทธิ์จำกัดและการทดสอบ process จริง
T4 UI, Cloud/GEE/ไฟล์จริง และ Deployment ยังอยู่นอกการอนุมัติรอบนี้
