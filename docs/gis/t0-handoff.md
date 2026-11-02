# Phase 1 — Task T0 Handoff Summary

วันที่: 27 ตุลาคม 2026 — **ทำเฉพาะ Safe Local Environment & Contracts**

## 1. เป้าหมายและขอบเขต

เตรียมสภาพ Local สำหรับ GIS Data Management ที่แยกจากระบบเดิม พร้อม Target
Guard และ Contracts ให้ T1–T4 ใช้ร่วมกัน อนุญาตสร้าง Branch และ Local Containers/
Volumes เท่านั้น ไม่พัฒนา GIS API/Schema/Worker/UI หรือเริ่ม T1 ในรอบนี้

## 2. สิ่งที่ดำเนินการแล้ว

- ตรวจ Working Tree สะอาดและ Branch เป้าหมายยังไม่มี ก่อนสร้าง
  `feature/gis-data-management` จาก Local `main`
- เพิ่มเครื่องมือ Dev/Test ที่ใช้ Python Standard Library ไม่ Import Backend,
  `dotenv` หรือ Earth Engine และไม่อ่าน `.env`/Credentials เดิม
- เพิ่ม Nonsecret Config พร้อม Positive Allowlist, `GIS_ENABLED=false` และ
  Target Proof สำหรับโครงสร้าง Docker ที่เป็นเจ้าของ
- เตรียม Local Supabase Core จาก Snapshot ทางการที่ Pin Image Digests:
  PostgreSQL, Auth, PostgREST, Kong ไม่มี Studio/Storage/Realtime/Cloud Worker
- ใช้ Local Values สร้างใหม่ในพื้นที่ทดลองนอก Repository ไม่คัดลอกหรือแสดงค่าลับ
- ตรวจ Resource Limits/Mounts/Capabilities/Labels/Networks ก่อน Start จริง
- เก็บ API/Database/Worker Contracts ทั้งเอกสารและ JSON พร้อม Tests
- ทบทวน Security แยกก่อนเริ่ม และแก้ Network/Mount/Capability/Telemetry ที่พบ

## 3. Environment และผลที่ยืนยันได้จริง

| องค์ประกอบ | ผลตรวจ |
|---|---|
| Docker Desktop / Engine | 4.91.0 / 29.8.0, Linux amd64/x86_64 |
| Compose | 5.5.1 |
| Host Docker Resources | 12 CPUs, RAM 16,164,007,936 bytes |
| Python ทดสอบ Host | Windows Python 3.12 |
| Python ทดสอบ Container | Linux Python 3.11.17 จาก Base Image ที่ Pin Digest |
| Local PostgreSQL | 17.6; Cluster `green-area-gis-t0`; Database `postgres` |
| Auth / PostgREST / Gateway Images | gotrue v2.197.0 / postgrest v14.18 / kong 3.9.3 |
| Core Readiness ก่อนหยุด | 4 บริการ Healthy |
| Auth Health จาก Host | `http://127.0.0.1:55421/auth/v1/health` → 200 |
| REST ไม่ส่ง Key | `http://127.0.0.1:55421/rest/v1/` → 401 |
| Database Metadata | มี Vendor Auth Schema; Auth Users=0; ไม่มี `gis` Schema และ Known App Tables ที่ตรวจ=0 |
| Schema แอปเดิม/GIS | ไม่รัน SQL Migration 000–026 หรือ 027–029 |

DB/Auth/REST อยู่เฉพาะ Internal Backplane Gateway เชื่อมเพิ่มกับ Bridge ของ
โปรเจกต์เพื่อให้ Host เข้าถึงผ่าน Loopback ได้ ไม่มี Published DB Port;
Worker ในอนาคตต้องอยู่ใน Docker Network ที่ตรวจ Identity แล้ว ใช้ `db:5432`
หรือ SQL Tool ผ่าน `docker exec` ที่ตรวจ Container ก่อน

Gateway มี Potential Egress จึง **ไม่รับรอง Zero Egress ทั้งระบบ** ปิด Kong
Anonymous Reports และตรวจแบบ Boolean จาก Container ก่อน Start ไม่มีการเรียก
Production/GEE หรือสร้าง Cloud Resources โดยงานนี้ ไม่ใช่การทำ Traffic Audit
ที่พิสูจน์ว่าเป็นไปไม่ได้ที่จะมี Packet ออกทุกกรณี

เพดาน RAM: DB 2 GiB, Auth 256 MiB, REST 256 MiB, Gateway 512 MiB รวม 3 GiB;
CPU รวม 4, MemorySwap เท่ากับ Memory, มี PID Limits และ Bounded Logs
Disk ไม่ได้มี Hard Quota ต่อ Volume; Startup ตรวจ Free Disk ขั้นต่ำ 10 GiB

RAM Snapshot ขณะวัด: DB ประมาณ85 MiB, Auth9 MiB, REST18 MiB, Gateway91 MiB
เป็นค่าขณะนั้น ไม่ใช่ Peak หรือ Benchmark GIS จริง

## 4. ไฟล์ใน Repository ที่สร้าง

ไฟล์ทั้งหมดเป็น T0 Dev Configuration/Documentation/Test Scaffolding ไม่แก้
ไฟล์เดิมของ Backend/Frontend/Deploy/Migrations

| ไฟล์ | หน้าที่ |
|---|---|
| `dev/gis_local/local.example.json` | Allowlist แบบไม่ลับ, Feature ปิด |
| `dev/gis_local/target_guard.py` | ตรวจ Config/Proof/Isolation และ Fake-mutation Test Seam |
| `dev/gis_local/manage.py` | เตรียม/เริ่ม/ตรวจ/หยุด Local Core แบบตรวจ Ownership |
| `dev/gis_local/compose.yaml` | Core4บริการ, Limits, Internal/Ingress Networks, Loopback |
| `dev/gis_local/images.lock.json` | Image Digests และ Hash Bootstrap ทางการ |
| `dev/gis_local/contracts.json` | Shared Contract Version `1.0.0-t0` |
| `dev/gis_local/README.md` | Runbook, Resource/Isolation Model และข้อจำกัด |
| `dev/gis_local/tests/test_target_guard.py` | Target/Flag/Environment/No-mutation Tests |
| `dev/gis_local/tests/test_runtime_policy.py` | Metadata/Network/Mount/Capability/Ownership Tests |
| `dev/gis_local/tests/test_contracts.py` | Contract/Pin Consistency Tests |
| `docs/gis/phase1-contracts.md` | API/DB/Worker/Role/State Contracts สำหรับงานถัดไป |
| `docs/gis/t0-handoff.md` | รายงานฉบับนี้ |

Diff Summary: เพิ่ม12ไฟล์ ไม่เปลี่ยน Tracked Files เดิม และไม่มีไฟล์ SQL Migration ใหม่

ไฟล์ภายนอก Repository: Runtime Ownership Marker, Empty Docker Registry Config,
Vendor Bootstrap SQL ที่ตรวจ Hash, Local-only Runtime Settings/Gateway Config,
Test Logs และ Readiness Evidence เก็บในพื้นที่ทดลองของงานนี้ ห้ามคัดลอก Runtime
Settings/Gateway Config ลง Git หรือรายงาน เนื่องจากมี Local Development Secrets

## 5. Contracts ที่ตกลงเป็นพื้นฐาน

เป็น **Contract เท่านั้น ไม่ใช่ Implementation ที่ทดสอบแล้ว**:

- Dataset Identity: จังหวัด+ปีแหล่งข้อมูล ค.ศ.+เดือน(0=รายปี)+Kind+Purpose;
  LDD เป็นรายปี และใช้ Province Reference เดิม
- คง `user/admin` เพิ่ม GIS Officer Grant แยก; Backend/SQL ตรวจ Actor จาก JWT
- Edition เก็บ Draft/Validating/Validated/Withdrawn; Active มาจาก Dataset Pointer
  และจำกัด Sandbox Catalog ไม่เชื่อม Analysis/Cache เดิม
- Job Queued/Running/Succeeded/Failed, Atomic Claim, Lease60s/Heartbeat15s,
  Max3 Attempts รวมครั้งแรก, Explicit Retry ได้1 Run รวมไม่เกิน6 Attempts
- Retry ต้องตรวจ Revision/Hash ปัจจุบัน; Terminal Failure คืน Edition กลับ Draft
  ใน Transaction เดียวกับ Job/History/Audit; Worker ไม่ Auto-activate
- HTTP `/gis`, Idempotency-Key, Expected Revision, Cursor Pagination และ
  Sanitized Errors; ไม่มี Upload/Ingestion/Hard-delete API ใน P1
- Proposed Private `gis` Schema และ Service-role-only RPC Wrappers; SQL Migration
  เดิม ไม่ Prisma; DDL+Ledger และ Mutation+Receipt ต้อง Atomic
- Local Worker ไม่ใช่ Always-on Cloud Worker และไม่มี Subscription ใหม่ที่จำเป็น

รายละเอียดครบใน `docs/gis/phase1-contracts.md` และ `dev/gis_local/contracts.json`

## 6. ผลการทดสอบจริง

| ชุดทดสอบ | ผล |
|---|---|
| T0 Standard-library Tests บน Windows/Python3.12 | **33 Pass / 0 Fail** |
| ชุดเดียวกันบน Linux/Python3.11 | **32 Pass / 0 Fail / 1 Skip**: Windows-only Path Translation ไม่เกี่ยวกับ Linux |
| Positive Local Proof / GIS disabled | ปฏิเสธ Fake Mutation เมื่อ Flag ปิด |
| Production/Unknown URL, DB Host/Port/Name, Untrusted Proof | Reject ก่อน Fake Callback; ไม่มีการยิง URL นั้นจริง |
| Ambient Service Config / Fake `.env` Sentinel | ไม่โหลดค่าเดิม; Child Env ไม่สืบทอด Supabase/GEE/Compose/Docker Overrides |
| Network/Foreign Member/External Bind/Capability/Mount/Telemetry | Negative Metadata Tests ผ่าน และ Config จริงผ่าน Pre-start Inspection |
| Foreign Resource Stop / Existing Runtime Overwrite / Running Reconfigure | Reject ก่อน Action ที่ไม่อนุญาต |
| Local Core Startup / Read-only Metadata / Health | ผ่านตามข้อ3 |
| Login/RPC/RLS ของแอป/Scientific GIS/Queue Worker | **Not Tested / Not Implemented ใน T0** |

อย่านับ Windows/Linux เป็น66เคสคนละฟีเจอร์ เป็น33 Test Methods ที่รันข้าม OS;
ผล PoC เก่า78/65ไม่ได้รันซ้ำใน T0

ปัญหาที่พบและแก้ระหว่างทดลอง:

1. Windows Restricted TEMP เขียน Fixture ไม่ได้ แก้โดยใช้พื้นที่ Temp ทดลองที่ระบุ
2. Docker Created State ไม่มี Health Field แก้ Metadata Projection ให้รองรับก่อน Start
3. Docker Desktop แสดง Windows Bind Path สองรูปแบบ เพิ่ม Canonicalization โดย
   คงการตรวจ Source+Destination+Read-only แบบ Exact
4. Bootstrap Roles ทางการอาศัย Webhooks Prerequisite จึงเพิ่มไฟล์ทางการที่ตรวจ Hash
   ลบเฉพาะ First-attempt Containers/Volumes ใหม่ที่ Auth ยังไม่เคย Start แล้วสร้างใหม่
5. tmpfs เดิมบัง Kong Native Library ย้าย Working Prefix ไป `/tmp/kong` โดยไม่เปลี่ยน Image
6. Internal-only Network ไม่เปิด Host Port ใน Docker29.8 เพิ่ม Gateway-only Ingress
   พร้อมระบุ Potential Egress/ปิด Telemetry ไม่ลด Isolation ของ DB/Auth/REST

มี Independent Source Review ของ Safety Scaffolding; Reviewer ไม่ได้รัน Tests
หรือรับรอง SQL/สิทธิ์/ฟีเจอร์ GIS ที่ยังไม่ได้พัฒนา

## 7. สถานะทรัพยากรและ Cleanup

หลังเก็บ Readiness Evidence ได้หยุด Core ทั้ง4บริการแล้ว และคง2 Named Volumes/
2 Networks/Images สำหรับตรวจสอบหรือใช้ต่อใน T1 โดยไม่ลบข้อมูลอัตโนมัติ
Temporary Test/Diagnostic Containers ใช้ `--rm`; ไม่มี Global Prune และไม่แตะ
Container/Volume ของงานอื่น

การล้าง First Attempt เป็นการลบเฉพาะ Bootstrap ใหม่ที่ล้มเหลว โดยตรวจ Labels/
IDs และยืนยัน Auth ยังไม่เริ่ม ไม่มีข้อมูลผู้ใช้/แอปที่ต้องรักษา Volume สุดท้าย
ของ Runtime รอบที่ผ่านไม่ถูกลบ ตรวจสถานะหยุดจริงแล้วใน Final Evidence
DB/Auth/Gateway ออกด้วย Exit0; PostgREST ออกด้วย Exit255 ตอน Stop จึงยืนยันเพียงว่า
หยุดแล้ว ไม่อ้างว่า Graceful Shutdown ของทุกบริการผ่าน ก่อนหยุดบริการทั้ง4 Healthy

## 8. ข้อจำกัดและงานที่ต้องทำใน T1

- Guard อยู่ใน Dev/Test Scaffolding **ยังไม่ได้ Wire เข้ากับ API เดิม** และไม่มี
  GIS API จริง T0 ไม่ได้รับรองว่า Legacy API มี Target Guard ใหม่แล้ว
- T0 Proof ตรวจ Docker Ownership/Topology/Cluster และ GIS Schema/5 Known App
  Tables ไม่ใช่ Schema Audit ทุกวัตถุ; T1 ต้องเพิ่ม DB Marker/Version ที่เหมาะสม
- Local Supabase Auth/REST พร้อม ไม่ได้แปลว่า JWT/RPC/RLS Business Flow ผ่านแล้ว
  ยังไม่มีบัญชี/Profiles/GIS Grants หรือ RPC ของแอป
- T1 ต้องทดสอบ Baseline/Upgrade เฉพาะฐานทดลอง แล้วสร้าง027–029ตาม Review;
  ห้าม Replay007/018/019/022กับฐานจริงหรือแก้ Legacy Defects แฝง
- Full Backend/Worker Dependencies และไฟล์ GIS จริงยังไม่ทดสอบใน T0
- Local Role Tokens มีอายุ7วันตาม Scaffolding การหมุนค่าใหม่ต้องทำเฉพาะ Local
  ไม่คัดลอก Production Credentials มาแทน
- Disk Growth/Host Availability/Custom Worker Role และ Production/GEE Project
  Relationship ยังเป็นเรื่องค้าง ไม่สร้าง Cloud/เปิด Billing เพื่อแก้โดยอัตโนมัติ

## 9. Git และการตัดสินใจที่ต้องอนุมัติ

- เริ่ม: `main` @ `048273f7b69ec6b60ac02f18ddbd1007619bd574`, Clean
- จบ: `feature/gis-data-management`, HEAD เดิม ไม่มี Commit ใหม่
- Working Tree มีเฉพาะ12ไฟล์ T0 ใหม่ที่ยังไม่ Commit ตามข้อห้าม ไม่มี Staging/
  Push/Merge/Rebase/PR/Deploy
- ก่อน T1 ต้องรับทราบ/อนุมัติการรับช่วงไฟล์ T0 ที่ยังไม่ Commit หรือวิธีเก็บงาน
  ห้าม Reset/ลบทิ้ง/Commit เองเพื่อทำให้ Working Tree สะอาด
- การอนุมัติ T0 ไม่ครอบคลุม T1 SQL/Role Bootstrap หรือ T2–T5/Cloud PoC

**ข้อเสนอขั้นถัดไป:** ผู้ใช้ตรวจ T0/Contracts แล้วอนุมัติ T1 เฉพาะ Local Schema,
Authorization และ Transaction Functions พร้อม Independent Security/DB Review
ก่อนรันจริงในฐานทดลองที่ยืนยันได้ว่าแยกจากระบบเดิม

**หยุดที่ T0 รอการตรวจสอบ ไม่เริ่ม T1 อัตโนมัติ**
