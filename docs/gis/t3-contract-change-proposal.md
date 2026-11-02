# T3 Contract Blocker — ข้อเสนอแยกสำหรับอนุมัติ

สถานะ: Proposal เท่านั้น ยังไม่สร้าง/รัน031 ไม่ provision Worker identity และยังไม่มี Worker
วันที่: 27 ตุลาคม 2026
Branch: feature/gis-data-management / HEAD048273f7b69ec6b60ac02f18ddbd1007619bd574

## เหตุที่ต้องขอทบทวนก่อนเปลี่ยนฐาน/สิทธิ์

กฎ T3 ของผู้ใช้ระบุว่า “หากพบ Contract Blocker ให้รายงานก่อน และเสนอ Forward
Migration แยกพร้อม Independent Review” การเปลี่ยนต่อไปนี้กระทบ Schema,
Authorization และ Guard/Models จาก T0–T2 จึงเสนอขอบเขตให้อนุมัติก่อนลงมือ
ไม่ใช้ผลทดสอบ SQL protocol ของ T1/T2 แทนหลักฐาน Native GIS validation

## Blockers ที่ยืนยันจากโค้ด

| หลักฐาน | สิ่งที่พบ | ผลกระทบ |
|---|---|---|
| migrations/027_gis_foundation.sql:119–122 | sha256(id), byte_size=octet_length(id), EPSG4326 และ placeholder fields | ไม่ใช่ Checksum/ขนาด/Metadata ของไฟล์ GIS จริง ห้ามอ้างว่าไฟล์ตรงกับ Manifest นี้ |
| PoC manifest.json | EPSG32647, LUL1_CODE/LU_CODE/Shape_Area, B8/B4, ST_B10, DN calibration | ต้องมี Catalog ที่อ้างไฟล์และชนิดข้อมูลจริง |
| migrations/028_gis_queue.sql:131–139 | complete รับเพียง valid/fixture_id/checks และ Check4คำ | เก็บผลเชิงวิทยาศาสตร์/Unknown codes/Warnings/รายละเอียด Failure ผ่าน Worker ไม่ได้ |
| 028:37 และ029:113–121 | results.valid=true และ succeededสัมพันธ์กับresult | ห้ามแก้ปัญหาด้วยการใส่ failed rows ใน gis.results |
| 027:28,39 และ030:234–235 | worker NOLOGIN, grantเฉพาะpostgres; readinessเฉพาะservice_role | ยังไม่มีตัวตนใช้งานจริงพร้อมตรวจ Target ด้วยสิทธิ์จำกัด |
| gis_schemas.py:43–46 | unitsไม่มี DN/K และไม่รับ scale/offset | APIยังอธิบายRaw S2/ST_B10/Kelvinอย่างถูกต้องไม่ได้ |
| dev/gis_local/manage.py:239–240,289–291 | ปฏิเสธ Network/Container member ที่เพิ่ม | Worker Containerแบบปกติจะทำให้ API Target Guardปฏิเสธ Local Stack |

กลไก Claim/Heartbeat/Lease/Retry/Recovery/Fencing และ Edition States เดิมยังใช้ได้
ไม่จำเป็นต้องสร้าง Queue หรือ State Model ใหม่

## ขอบเขตที่แนะนำให้อนุมัติ

### A. Forward031: Native validation contract แบบเพิ่มต่อ

1. เพิ่ม Catalog Synthetic V2 แยก ID จาก V1 โดยเก็บ SHA256/bytes ของไฟล์จริง,
   CRS/bands/units/resolution/NoData และ calibration/profile ที่ Server allowlist
   ไม่แก้ Manifest, Dataset, Edition หรือ Result เก่า
   การลงทะเบียนต้อง append-only และปฏิเสธ ID/hash collision ไม่ใช้ ON CONFLICT
   DO UPDATE แก้รายการ V1 หรือ Catalog ที่ลงทะเบียนแล้ว
2. เพิ่ม metadata schema_version2 สำหรับ Synthetic เท่านั้น รองรับ LDD,
   S2 B8/B4+mask, ST_B10+QA, NDVI/LSTสำเร็จรูป และ Kelvinตามชนิดจริง
   ห้ามเปลี่ยนชื่อ DN เป็น Celsius เพื่อให้ผ่าน Schema เดิม
3. แนะนำเพิ่ม nullable `gis.attempts.validation_report` ที่มี schema/size bound
   เพื่อเก็บผล Native ทั้งผ่าน/ไม่ผ่าน/Transient โดยไม่สร้าง failed gis.results
   แถวเก่ายังคงNULL; safe read projectionsเพิ่มข้อมูลเป็นoptional field
4. เพิ่ม Worker V2 RPC ซึ่งใช้ Queue Functions เดิม ตรวจ lease/revision/hash
   ภายใต้ lock order edition→job แล้วบันทึกรายงานกับการ complete/fail ใน TXเดียว
   ต้องตรวจ fencingก่อนเขียน report และไม่แก้ terminal historyย้อนหลัง
5. เพิ่ม deferred invariant: งาน Native V2ที่succeededต้องมี Native reportที่ผ่าน
   และตรง input/fixture SHA/provider build; old worker wrapperต้องใช้ทำสำเร็จ
   ให้ Native V2โดยข้ามรายงานไม่ได้ ข้อมูลV1เก่าไม่ถูกบังคับย้อนหลัง
6. เก็บ `validator_version=synthetic-v1` เป็นชื่อ Queue Protocolเดิมได้ และเพิ่ม
   Native provider build/versionที่ตรวจได้แยก ลดการเปลี่ยน command/eligibility
   ที่ hardcodeค่าเดิม หากตรวจSQLละเอียดแล้วจำเป็นต้องเปลี่ยนจะเสนอก่อนเพิ่มขอบเขต
7. ขยาย `gis.manifest_hash` และ API modelให้รองรับV2แบบมี discriminantชัดเจน
   V1 input/response/statusยังใช้ได้; Structured Native reportเป็นoptional addition
8. DDL+ledger031/checksumอยู่ในTransactionเดียว รันเฉพาะ Localที่ยืนยันแล้ว
   ต้อง Independent Review exact SQL bytes และแก้ High/Criticalก่อนนำไปรัน

### B. ตัวตน Worker แบบไม่ใช้ Service Role

แนะนำตัวตน Supabase Auth Localเฉพาะ Worker ใช้ signed user JWTที่ออกโดย Authจริง
ไม่อ่าน Signing Secretและไม่สร้าง Service Role keyให้ Worker

- เพิ่ม NOLOGIN permission roleเฉพาะ Native Worker เช่น gis_native_worker
  ให้เฉพาะ execute WorkerV2/readiness ไม่มี private table/admin/backend RPC
- ไม่ให้ membership gis_owner/service_role/legacy gis_worker โดยไม่จำเป็น
  แยกจาก roleที่ใช้ manual fixtures ใน T1/T2 เพื่อรักษา Regression testsเดิม
- ให้ authenticator SETROLEบทบาทใหม่เฉพาะที่จำเป็น พร้อมตรวจ inherited grants
- เพิ่ม Worker-only readiness RPC คืนเฉพาะ Local identity/contract version
- ผูก Worker IDกับ Auth Context ที่เชื่อถือได้ ไม่รับ IDเพื่อยกระดับสิทธิ์จาก Payload
- Bootstrapperที่ตรวจ Localแล้วอาจ provisionบัญชีจำลอง; Workerได้รับเฉพาะ
  credential/tokenของตัวเองและpublic anon keyผ่านช่องทางprocess-private
  Native childไม่ได้รับ Credential, Token, DB connection หรือ file descriptorเหล่านี้

ตัวเลือกนี้ต้องตรวจ Role/JWT capability ของ GoTrue/PostgRESTจริงอีกครั้งก่อนเลือกใช้
หากทำไม่ได้จะรายงาน ไม่ fallbackเป็น service_role/postgres/Docker execให้ Worker

### C. Runtime/Guard ที่เสนอ

แนะนำ Linux Worker Containerใช้ Python3.11 และ Image GISที่พิสูจน์แล้วเป็นฐาน
Parentใช้ Queue protocol; Native childเป็นprocessแยก ก่อนโหลดGDAL/Fiona
กำหนด memory/CPU/wall-time/output bounds, clean env/closed FDs, local immutable
fixture allowlist และไม่รับPath/URL/Command/SQLจากAPI
ต้องสร้าง Native childด้วย exec/spawn ไม่ใช้ fork ที่คงสำเนาหน่วยความจำซึ่งมี
CredentialของParent; clean env/closed FDsอย่างเดียวไม่เพียงพอสำหรับfork

ต้องอนุมัติขยาย Guardแบบเจาะจงเพื่อให้ยอมรับเฉพาะ Worker Containerที่ตรวจครบ
ID/labels/image/network/mounts/limits ภายใต้ scopeใหม่ โดยคงdefaultT0/T2 strict
และไม่อนุญาต Container/Networkทั่วไป ไม่แชร์ namespaceหรือซ่อน memberเพื่อเลี่ยงGuard
ไม่ mount Docker socket/Home/.env/Service credentialsให้ Worker

ไฟล์เดิมที่คาดว่าอาจต้องปรับแบบมี Diffเฉพาะจุด: T0 runtime guard interface,
T2 local attestor/factory และ gis_schemas.py; ไม่เขียนทับไฟล์ทั้งก้อนหรือแก้Migrationเก่า
ต้อง Regressionทั้ง originalstrict-modeและT3approved-topology รวมUnknown members

หากไม่ต้องการแตะ Guardเดิม ทางเลือกคือ Host Windows Worker+native childภายใต้
Windows Job Object ใช้GISvenvเดิม ไม่ใช้DockerในWorker แต่ต้องพิสูจน์limits/killจริง
และไม่อ้างว่าเป็น Linux Worker หรือ OS network/filesystem sandbox ตัวเลือกนี้ยังไม่ทำ

## แผนทดสอบหลังอนุมัติ

| กลุ่ม | Acceptance |
|---|---|
| Scientific/provider | FixtureSHA/size/metadata/known answersตรงServerCatalog; composite/unknownไม่สูญหาย; NoData/scaleซ้ำถูกตรวจ |
| Credentials/permissions | WorkerจริงเรียกเฉพาะWorker RPC; Admin/readinessservice/private tables/Legacy writesถูกปฏิเสธ |
| Queue E2E | Enqueueผ่านAPI→Workerclaimจริง→Nativechild→Result/Attempt/Reportจริง; ไม่activateอัตโนมัติ |
| Recovery | Kill Parent/Container, รอleaseจริง, replacementrecover; stale tokenไม่เขียนผลซ้ำ |
| Resource/shutdown | Timeout/OOM/SIGTERM/KILLมีsafe outcome; childถูกเก็บกวาด; terminalfailureคืนdraft |
| Regression | T0–T2API/SQLprotocolเดิมผ่าน; Legacy hashesเดิมคงอยู่; Ledger000–030ไม่เปลี่ยน |
| Safety | ไม่มีCloud/GEE/Production; idleSyntheticQueue; alltestjobsจบหรือบันทึกค้างชัดเจน; Gatefalse |

## สิ่งที่ยังไม่อนุมัติ/ยังไม่ดำเนินการ

ไม่มี031 SQL fileหรือSchema mutationในรอบGateนี้ ไม่มีบัญชี/role/grant/Workerใหม่
ไม่มีAPI/model/guardเดิมถูกแก้ ไม่มีWorker Queue E2E/OOM/Recoveryที่อ้างว่าผ่าน
ไม่มีT4–T5/Phase2/Cloud/Deploy/Commit/Push/PR

ขออนุมัติเป็นชุดเดียว: จัดทำ031และส่วนขยาย V2/Worker identityตาม A+B และ
Runtime/GuardแบบLinuxที่แนะนำใน C (ไม่รวมทางเลือกWindowsโดยอัตโนมัติ),
ตรวจอิสระก่อนMutation แล้วดำเนิน T3 Local E2Eให้ครบ โดยคง000–030และข้อมูลเดิม
