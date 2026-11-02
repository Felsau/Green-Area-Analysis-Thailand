# T3 Remediation Handoff — 28 ตุลาคม 2026

สถานะ: แก้ T3 และทดสอบ Local เสร็จ พร้อมส่ง Final Acceptance Review รอบใหม่
ยังไม่อนุมัติหรือเริ่ม T4, T5, Phase 2–4 หรือ Deployment

เอกสารนี้ใช้แทนข้อสรุป Completed/100% ใน `t3-handoff.md` และ
`t3-test-evidence.json` รุ่นก่อนสำหรับการประเมินงานปัจจุบัน โดยเก็บหลักฐานเดิมไว้

## 1. เป้าหมายและขอบเขต

แก้ High Findings 5 เรื่องจาก Final Acceptance Review: Worker Identity,
Native Report Integrity, Target Guard, Migration Runner และ Queue V1/V2 Isolation
พร้อมทำ Linux Worker Lifecycle และทดสอบจริงด้วย Synthetic GIS Fixtures เท่านั้น
ระบบยังใช้ FastAPI, Supabase PostgreSQL/Auth และ Forward SQL Migrations ไม่ใช้ Prisma

ก่อนเริ่มตรวจพบ Branch ที่กำหนดและงาน T0–T3 ยังไม่ Commit ไม่มี Agent อื่นในทีม
ที่กำลังแก้ Workspace ก่อนแบ่งงาน Remediation และไม่พบ Antigravity Process
ระหว่างเริ่มตรวจ มีการเก็บ Source Hash ก่อนแก้และตรวจความคงเดิมระหว่างทดสอบ

## 2. Findings → Fixes → หลักฐาน

| Finding | สิ่งที่แก้ | หลักฐานจริง |
|---|---|---|
| Worker ID มาจาก Payload | SQL `gis.native_subject()` ตรวจ PostgREST session/role, Local JWT issuer และ subject; ถ้าส่ง worker_id ต้องตรง subject | JWT จริง: Spoof ID ถูกปฏิเสธ 42501; Job บันทึก Worker ตาม subject; Admin/Backend/Legacy RPC และ Direct Read ถูกปฏิเสธ |
| Native Report ข้ามการตรวจได้ | Report Schema/Types/Keys/ขนาด 16 KiB; SHA ของ Artifact, Input Hash/Revision, Build, Scientific Checks และ Expected Results; Deferred Triggers บังคับ Report กับ Result ให้ตรงกัน | Report ที่ปลอม Hash/Revision/Build/Checks/Area ถูกปฏิเสธ; Legacy Worker และ Owner Transaction ที่พยายามข้าม Report ถูกปฏิเสธและ Rollback |
| Guard เดิมอ่อนลง | Default ปฏิเสธทุก Extra Container; เพิ่มได้เฉพาะ Exact-ID Approval จาก Trusted Launcher ตรวจ Image ID, User, Command, Privileges, CPU/Memory/PIDs, Network และ Exact Mounts | Guard 92 ข้อผ่าน รวมใหม่ 52; Container จริงผ่าน Approved Policy แต่ถูกปฏิเสธเมื่อใช้ Strict Default |
| Runner เขียน Ledger ย้อนหลัง | ลบ Reapply/UPDATE path ของ 031; Checksum Mismatch ต้อง Fail Closed; DDL ใหม่ผ่าน Review และ INSERT version ใหม่ใน Transaction เท่านั้น | Runner Mock 12 ข้อผ่าน; SQL Audit เทียบ Ledger จริง; Preservation ยืนยัน Ledger เดิมรวม applied_at ไม่เปลี่ยน |
| Native Worker หยิบงาน V1 | Shared private Queue Protocol แยก V1/V2 ใน Claim/Recover/Heartbeat/Complete/Fail; รักษา State/Retry/Lease เดิม | Native ไม่ Claim/Recover งาน V1; Legacy ไม่ Complete Native; V1 Retry/Result ผ่าน และ T2 จริงผ่าน 126 ข้อ |

## 3. Forward Migrations และ Independent Review

Migration 000–031 ทั้ง 32 ไฟล์คง bytes เดิม ไม่มีการแก้ Ledger เก่าหรือ Reapply
032/033 ผ่าน Independent Review ของ Exact SQL ก่อนรันกับ `postgres` และ
`gis_t1_upgrade` ใน Local Instance ที่ตรวจ Container/Cluster/Environment Identity แล้ว

| Migration | การเปลี่ยนแปลง | SHA256 |
|---|---|---|
| 032_gis_worker_remediation.sql | Trusted JWT subject, Strict Native Report, Shared V1/V2 Protocol, Deferred Invariants, Readiness และ ACL | `659e898015310390e75061dc13ef93020b45b1744193875c2c2085d604f7d99b` |
| 033_gis_native_trigger_fields.sql | แก้การอ้าง NEW ของ Polymorphic Trigger ด้วย IF ตามชนิดตาราง | `7786a473e8a05364e54d77b81a1cc1917d24bd2a00e53493625110a5922fc0fd` |

032 ไม่เพิ่มตารางหรือเปลี่ยน Queue States ส่วน 033 เปลี่ยน Trigger Function เท่านั้น
Private Functions ยังคง SECURITY DEFINER ของ `gis_owner` พร้อม Fixed Search Path
Worker ไม่มี Table Grants, Privileged Membership, LOGIN หรือ BYPASSRLS
Public V2 RPC ให้เฉพาะ Native Worker Role; ไม่เพิ่มสิทธิ์ Backend/Admin ให้ Worker

ผู้ตรวจอิสระตรวจโค้ดและหลักฐานหลังรันแล้วอีกครั้ง บันทึก `final-review.json`
ยืนยันว่าไม่มี High/Critical ค้างในขอบเขต Local Synthetic T3 นี้ ผู้ตรวจไม่ได้รัน
Runtime Tests เอง จึงแยก Static Review ออกจากผลรันทดสอบของตัวหลักชัดเจน

ข้อผิดพลาดที่พบและแก้จริง:

1. หลังใช้ 032 พบ PostgreSQL 42703 ขณะ Enqueue เพราะ CASE อ้าง `NEW.job_id`
   บนแถว Jobs ที่ไม่มีฟิลด์นี้ Transaction ถูก Rollback จึงแก้ด้วย 033 โดยไม่แก้ 032
   ที่ใช้แล้ว และตรวจ Exact SQL อิสระใหม่ก่อนรัน
2. SQL Regression T1 เดิมผ่าน 82/83 เพราะสมมติว่า Officer List ต้องมีรวมหนึ่งคน
   แต่ฐานเก็บ Synthetic Grants เก่าตามกฎรักษาข้อมูล แก้เฉพาะ Test Assertion
   ให้ตรวจว่าพบ Officer UUID ของรอบนี้หนึ่งรายการ ผ่านการตรวจอิสระและรันใหม่ 83/83
3. เครื่องมือ Read-only SQL Audit ใช้ Regex ที่ไม่รับตัวเลขในชื่อ Function
   แก้ให้ตรวจ `worker_v2`/`readiness_v2` ครบ ไม่เปลี่ยน Runtime หรือ SQL

## 4. Worker และ Isolation

- Python Worker เป็น Linux Process แยกจาก FastAPI มี Poll Loop และ Automatic Recovery
- ใช้ Custom-role JWT ที่ GoTrue ออกจริง Worker ได้เฉพาะ Session ของตนและ Public Anon Key
  ผ่าน stdin ของ Process ไม่ผ่าน Env, File, Command Line หรือ Log
- Operator สำหรับ Local Fixtures แยกจาก Worker; Worker ไม่ได้รับ Service Role Key,
  PostgreSQL Login หรือ Docker Socket
- HTTP Target คงที่เฉพาะ Local Gateway ตรวจ Subject/Instance/Fingerprint/Schema Versions
  ก่อนทุก Mutation ไม่อ่าน `.env` หรือ GEE Credentials
- Parent เป็น Non-dumpable; Child เริ่ม Interpreter ใหม่ด้วย Clean Env/Closed FDs
  ไม่มี Credentials หรือ DB Connection
- Container: Non-root 65534:65534, Read-only, CapDrop ALL, No New Privileges,
  Internal Network เท่านั้น, Memory/Swap 1 GiB, CPU 1, PIDs 64, Exact Read-only Source Mount
- Child: Address Space 512 MiB, CPU Time 20 วินาที, Core Dump 0, Open Files 64,
  File Output 16 KiB; Parent ใช้ Temporary File อ่านไม่เกิน 16 KiB+1 และทิ้ง stderr
- Native Wall Timeout 25 วินาที, Heartbeat ทุก 5 วินาที, Lease 60 วินาที, Attempts ไม่เกิน 3
- SIGTERM คืนงานผ่าน Fenced Transient Failure; SIGKILL ใช้ Lease Expiry/Replacement Recovery
- OOM/Timeout/Shutdown เป็น Infrastructure Transient Error แยกจาก Invalid GIS Data
- ไม่มี Auto-activation หรือการเปลี่ยน Legacy Analysis/Cache

Runtime ที่ยืนยันจริง: Linux x86_64, Python 3.11.17, Rasterio 1.4.4 / GDAL 3.10.3,
Fiona 1.10.1 / GDAL 3.9.2, Shapely 2.2.0 / GEOS 3.14.1 และ NumPy 2.4.6
Backend Tests บนเครื่องใช้ Python 3.12.10 ไม่มี Dependency ใหม่หรือ Global Install

## 5. ผลทดสอบล่าสุด

ตัวเลขเป็นข้อทดสอบ/Assertion ตามชนิด ไม่ควรรวมเป็นจำนวน Scenario อิสระ

| ชุดทดสอบ | ผล | ขอบเขต |
|---|---:|---|
| T0/T1 Guard Regression | 92 Pass | Mock Policy Tests รวมใหม่ 52 ข้อ |
| T2 API/Runtime Unit | 75 Pass | Mock Tests, ปิด dotenv และห้าม Non-local Network |
| Legacy API Regression | 81 Pass | Mock Regression เดิม |
| Worker + Migration Runner Unit | 38 Pass | Worker 26 / Runner 12 ไม่มีฐานจริง |
| Linux Scientific Provider | 35 Pass | อ่านไฟล์ ZIP/GeoTIFF จริงจาก Synthetic Fixtures ใน Network-none Container |
| T1 SQL Regression บน Upgrade DB | 83 Pass | Local PostgreSQL จริง รวม ACL/RLS/Queue/History/Concurrency; ใช้ SQL Role Simulation |
| T2 Auth/API Integration | 126 Pass | Auth/PostgREST/PostgreSQL จริง ไม่ใช่ Python Worker Test |
| T3 Linux Worker E2E | 72 Pass | API → Queue → Linux Daemon → Native Child → Result/Attempt จริง |
| Two Linux Workers / Closed Client | 7 Pass | สอง Process พร้อมกัน ไม่สร้าง Result ซ้ำ และ Job อยู่ต่อหลังปิด Client |
| Read-only SQL Audit | 78 Pass | ทั้งสองฐาน: Ledger, Roles/ACL, FORCE RLS, Function Bodies และ Deferred Triggers |
| Preservation | 19 Pass | ข้อมูลเดิม, Ledger, Source และ Policies จริง |

E2E ก่อนปรับให้ Daemon เดียวรับงานต่อเนื่องเคยผ่าน 85 Assertions มีการเก็บรายงานตาม
Run ID ไว้ ผลล่าสุด 72 Assertions ตัดเพียง Startup Checks ที่ซ้ำ 13 ครั้งออก ไม่ตัด
Scientific Expected Results หรือกรณี Lifecycle ใดออก

### Lifecycle ที่พิสูจน์จริง

| กรณี | ผลและหลักฐาน |
|---|---|
| SIGKILL Worker | ฆ่า Linux Worker จริง งานยัง Running ในฐาน |
| Replacement Recovery | Worker อีกตัวรอ Lease หมดจริงแล้ว Recover/Claim โดยไม่ย้อนเวลาในฐาน |
| Stale Completion Fencing | Old Lease Token ถูกปฏิเสธก่อนตรวจ/บันทึก Report |
| Heartbeat | ส่งจริงระหว่าง Native Child ทำงานยาวและ Progress เพิ่มในฐาน |
| SIGTERM | หยุด Child, บันทึก WORKER_SHUTDOWN เป็น Transient, คืน Queued และออก Exit 0 |
| SIGINT | Worker ขณะ Idle ออกจาก Poll Loop อย่างเรียบร้อย |
| Timeout | Child ถูกจำกัด Wall Time จริง จบตาม Retry Budget และ Edition กลับ Draft |
| Memory Limit | Allocation จริงเกิน RLIMIT_AS ทำให้ MemoryError; รายงาน NATIVE_MEMORY_LIMIT เป็น Transient ครบ 3 Attempts |
| Concurrent Claim | JWT สองตัวตนแข่ง Claim จริง และทดสอบ Linux Worker สอง Process พร้อมกัน |
| Validation Failures | Unknown Code/ZIP Traversal/Symlink/Missing DBF/All NoData เก็บ Report และไม่สร้าง Success Result |

มีการทดสอบ LDD UTF-8/CP874/Composite/Unknown Codes และ GeoTIFF S2 NDVI,
Landsat ST_B10 LST, Ready NDVI/LST, Kelvin, NoData โดยไม่แก้ Expected Results

## 6. Source Fingerprints และหลักฐาน

Functional E2E / Dual Worker / Scientific / Unit Snapshot:
`4fb48aeb6b99db8b13a251526b1540884427073560e3d012f9b91c886383de62`

Final Working-tree Source Fingerprint:
`34a1d1e92888f57b93ac6e9588606fd48e00ba591e687010b13fac752fd23fc7`

ความต่างมีเฉพาะ `dev/gis_worker/remediation_sql_audit.py` ซึ่งแก้ Regex ของเครื่องมือ
Audit หลัง Functional Tests ไม่ใช่ Worker, API, Migration, Provider หรือ Fixtures
ตรวจ Hash รายไฟล์แล้ว Runtime และ Functional Test Sources ทั้งหมดตรงกับที่รัน
SQL Audit/Preservation รันบน Fingerprint สุดท้าย มีการบันทึก Delta นี้ตรงไปตรงมา
ไม่ได้อ้างว่าทุก Global Fingerprint เหมือนกัน

หลักฐานรายละเอียดอยู่ใน Local Runtime เดิม:

```text
C:/Users/chaya/.codex/visualizations/2026/10/04/01a107d9-ff44-7731-8bc3-91814ffd8d51/t0-local-supabase-20261027-v2/t3-remediation/
```

ไฟล์หลัก: `final-evidence-index.json`, `e2e-results.json`, `dual-workers-results.json`,
`science-tests-final.json`, `worker-migration-unit.json`, `guard-regression-tests.json`,
`sql-audit.json`, `preservation-final.json` และ Review Records ของ 032/033/Worker/Guard
รายงาน 032 ที่ล้มเหลวเก็บแยกเป็น `failed-032-e2e-results.json`
Raw T1/T2 Reports เก็บใน Runtime `t1/` และ `t2/` พร้อม Source Binding ใน Evidence Index

## 7. Files Changed / Diff Summary

ไฟล์เดิมที่แก้ในรอบ Remediation:

| ไฟล์ | สรุป |
|---|---|
| dev/gis_local/manage.py | Strict Default และ Exact Worker Approval |
| dev/gis_local/t3_local.py | Checksum Drift Fail Closed ไม่มี Reapply/UPDATE Ledger |
| dev/gis_local/tests/t1_cases.py | แก้ Assertion เฉพาะ Officer ของรอบทดสอบ |
| green-area-backend/gis_worker/worker.py | Linux Daemon, Local JWT Client, Heartbeat/Recovery/Fencing/Signals/Bounded Native Execution |
| green-area-backend/gis_worker/native_child.py | เพิ่ม RLIMIT_FSIZE ก่อน Native Imports |

ไฟล์ใหม่: Migrations 032/033; `dev/gis_worker/remediation_local.py`,
`remediation_e2e.py`, `remediation_sql_audit.py`; `test_t3_worker_guard.py`,
`test_gis_worker_unit.py`, `test_gis_migration_runner.py`; Handoff และ Evidence Summary นี้
ไม่มีการแก้ Dependencies, Docker Deployment, Legacy Business Logic, GIS Provider,
Registry, Synthetic Fixture Bytes หรือ Migration 000–031
`main.py` มี Uncommitted Changes จาก T2 เดิม ซึ่ง Hash ไม่เปลี่ยนในรอบนี้
ไฟล์ภายนอก Repository อยู่ในพื้นที่ทดลองที่อนุมัติ ได้แก่ Source/Baseline Snapshots,
Review Records, Test Artifacts และ `finalize_evidence.py` สำหรับอ่านตรวจ Preservation

## 8. Preservation, Cleanup และข้อจำกัด

- Hash ของ Legacy 15 ตารางที่ไม่ใช่ Profiles ทั้งสองฐานตรงก่อนทดลอง
- Profiles ทุกแถวที่มีอยู่ก่อน Remediation มี Hash เดิมครบ ไม่ลบหรือเขียนทับ
- เก็บ Synthetic Profiles ใหม่ 21 แถวใน `postgres` และ 6 แถวใน Upgrade DB ไว้ตามกฎ
- Legacy Columns/Constraints/Indexes/Functions/Auth Trigger/RLS คงเดิม
- Ledger เดิมถึง 031 รวม applied_at คงเดิม; 032/033 เพิ่มด้วย INSERT ใหม่
- หลังทดสอบ Queues ทั้งสองฐานไม่มีงาน Queued/Running และ Activation Gate เป็น false
- Worker Containers ที่สร้างถูกหยุด/ลบเฉพาะ Exact Owned IDs แล้ว ไม่มีการลบ Volumes
- Core Local Containers เดิมทั้งสี่ยัง Running/Healthy และใช้ Image เดิม ไม่มี Build/Pull ใหม่

Not Tested / ไม่อยู่ในหลักฐานที่รับรอง:

- Kernel/cgroup OOM-kill และ Parent OOM; ที่ทดสอบคือ Native Child RLIMIT_AS/MemoryError จริง
- การ Burn CPU จน RLIMIT_CPU ถูกบังคับ แม้กำหนด Limit แล้ว
- Auth Refresh-token Expiry/Rotation Lifecycle; Expired Token ใน Fencing Test คือ Lease Token
- ข้อมูล GIS จริง, Production/Staging, Supabase Cloud, GEE Compute/Ingestion และ GIS UI
- งาน Upload/Storage จริงและงาน T4–T5/Phase 2–4

## 9. Git และการส่งต่องาน

ตัวรันทดสอบปัจจุบันคือ `dev/gis_worker/remediation_e2e.py --runtime-dir <T0-local-runtime>`
และ `dev/gis_worker/remediation_sql_audit.py --runtime-dir <T0-local-runtime>`
ใช้ Python ของ Backend .venv พร้อม Docker Desktop และ Local Core เดิมเท่านั้น
E2E สร้างข้อมูลจำลองใหม่และเก็บประวัติไว้ ส่วน SQL Audit ใช้อ่านอย่างเดียว
`dev/gis_local/t3_integration.py` เป็น Harness รุ่นเก่าที่ใช้ Host Worker Constructor
และการย้อนเวลา Lease ซึ่งถูกแทนที่ด้วย Remediation Harness นี้ ไม่ใช้ยืนยันผลปัจจุบัน

Branch คงเดิม: `feature/gis-data-management`
HEAD คงเดิม: `048273f7b69ec6b60ac02f18ddbd1007619bd574`
T0–T3 และ Remediation ยังไม่ Commit มี Untracked Files ตามงานเดิมและไฟล์ใหม่
ไม่ได้ Reset/Stash/Clean/เปลี่ยน Branch/Commit/Push/Merge/PR/Deploy
`git diff --check` ของ Tracked Diff ไม่พบปัญหา; Untracked Sources ตรวจผ่าน Tests/Hash

สิ่งที่ต้องได้รับอนุมัติถัดไปคือ Final Acceptance Review ของ T3 Remediation รอบนี้
ให้ผู้ตรวจใช้โค้ดปัจจุบัน, Exact Migration/Review Records และ Evidence Index ร่วมกัน
ก่อนพิจารณาอนุมัติ Task ถัดไป งานรอบนี้หยุดที่ T3 ไม่เริ่ม T4 โดยอัตโนมัติ
