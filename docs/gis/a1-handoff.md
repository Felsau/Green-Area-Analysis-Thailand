# A1 — Local GIS Publication Foundation Handoff

2 พฤศจิกายน 2026 · **A1 PASS — Foundation เท่านั้น / พร้อมเสนอ A2 เพื่ออนุมัติ**

## เป้าหมายและขอบเขต

เพิ่ม Contracts และ Artifact Registry เพื่อเตรียมเชื่อมข้อมูลอัปโหลดกับ Dashboard
อย่างปลอดภัย โดยยังไม่ทำ Prepare Processing, Trusted Artifact Verification,
Publish, เปิด Gate, เปลี่ยน Dashboard Readers หรือเรียก GEE/Cloud

## สิ่งที่พบและการตัดสินใจ

- ใช้ Catalog, Validation Results, Audit/Receipts และ Active Pointer เดิม
- ไม่เปลี่ยน `gis.eligible()` เพราะ Deferred Catalog Invariants เดิมใช้ตรวจ Validation
- GeoTIFF ที่ตรวจผ่านยังคง Edition เป็น draft และไม่มี validated_result_id ตาม036;
  A1 ตรวจความสำเร็จจาก Native Job/Attempt/Result ที่ตรง Revision/Hash จริง
- Registry รับเฉพาะแหล่ง local_ldd/local_geotiff ที่มี Upload Association และรายงาน
  Native สำเร็จตรงกัน ไม่รับ Synthetic/Offline เป็นหลักฐานข้อมูลจริง
- Artifact ที่ลงทะเบียนเป็นเพียง Declaration: Hash/Size/Method/Coverage ไม่ใช่
  หลักฐานว่าไฟล์ผลลัพธ์ถูกสร้างหรือตรวจแล้ว แม้ลงทะเบียนครบก็ยังไม่ Ready

## สิ่งที่พัฒนา

Migration037 เพิ่ม `gis.publication_artifacts` แบบ Immutable พร้อม Composite FKs,
Hash/Size/Method Constraints, Province Coverage Declaration, Generated Content Key,
FORCE RLS และ owner-only policy ไม่ให้ Browser/Service/Worker เข้าตารางโดยตรง

มี Service-only SQL RPC สำหรับ Admin Registration และ GIS Officer/Admin Read:
ตรวจสิทธิ์ซ้ำ, Dataset/Input Revision, Current Validation Lineage, Idempotency,
และบันทึก Artifact+Audit+Receipt ใน Transaction เดียว ไม่เพิ่ม HTTP Endpoint

แยก Validation, Artifact Completeness และ Publication Readiness;
`publication_ready` เป็น false เสมอใน A1 จนกว่าจะมี Trusted Verifier ที่ตรวจเพิ่มใน
Forward Migration ของ A2/A4 ไม่มี payload หรือสิทธิ์ Worker ที่ทำให้ Ready ได้เอง

เพิ่ม Before-update Pointer Guard ป้องกันเปลี่ยน Active Pointer ไปฉบับที่ไม่ Ready
รวมเส้นทางอนาคตของ Rollback/Replacement โดยไม่แก้ Command/Queue/Gate เดิม
Registry เก็บต่อเมื่อบัญชีถูกลบ โดย null ได้เฉพาะ FK ผู้ลงทะเบียน

`SourceIdentity` แยก Legacy/Published และสร้าง Cache Namespace จาก Scope/Period/
Method/Lineage สำหรับ Reader ในอนาคต ไม่ให้ Namespace เป็น Authority และไม่ใช้กับ
Dashboard/Cache ปัจจุบัน เริ่ม Publication ระดับจังหวัดเท่านั้น

## Files Changed

แก้ไฟล์เดิม:

- `.gitattributes` — รักษาไบต์037 เพิ่มจาก Migration เดิม
- `dev/gis_local/contracts.json` — Publication Extension ที่ Verification/Readiness ปิด
- `docs/gis/phase1-contracts.md` — เชื่อม Contracts A1 และอธิบาย GeoTIFF Compatibility

ไฟล์ใหม่:

- `green-area-backend/migrations/037_gis_publication_foundation.sql`
- `green-area-backend/gis_publication.py`
- `green-area-backend/tests/test_gis_publication_unit.py`
- `dev/gis_local/publication_local.py`
- `dev/gis_local/publication_checks.py`
- `dev/gis_local/publication-review.json`
- `dev/gis_local/tests/test_publication_runner.py`
- `docs/gis/publication-contracts.md`
- `docs/gis/a1-handoff.md`

## Migration และ Independent Review

037 SHA256: `386538e46e2b5e220ad271bd6c34b047a4624aac7cec8f818d1b5d2af65389a8`

ผู้ตรวจอิสระ `a1_security_review` ตรวจ Exact SQL ก่อน Apply และตรวจ Source ซ้ำ
หลังแก้ข้อสังเกต ไม่เหลือ High/Critical ใน A1 ที่ตรวจ

แก้ก่อน Apply: BEFORE Trigger ต้องไม่นำ Stored Generated object_key ไปเทียบใน
FK actor-nulling เพราะ Generated Value อาจยังไม่ถูกคำนวณ; Actual Account-delete
Test ของบัญชีจำลองใหม่ผ่านแล้ว

แก้ Runner ก่อนส่งมอบ: ทุก Proof รวม Read-only Checks ต้องเทียบ Applied037 SHA
กับ Source เช่นเดียวกับ Migration Path หากไม่ตรงให้หยุด ไม่แก้ Ledger/Reapply

Apply037 ครั้งเดียวกับ `postgres` และ `gis_t1_upgrade` หลังตรวจ Container/Target/
Baseline Identity ผ่าน มี Gate=false ทั้งสองฐาน ไม่แก้000–036 หรือ Ledger ย้อนหลัง
037 ใช้แล้ว: การแก้ SQL ครั้งถัดไปต้องเป็น Forward Migration ใหม่

## Tests Passed / Failed / Not Tested

| ชุดทดสอบรอบสุดท้าย | ผลและขอบเขต |
|---|---|
| Unit/Guard/Backend/Local Demo Regression | 509 Passed +37 Subtests; 55 A1 ใหม่และ454 Regression เดิม; Python3.12.10 |
| Actual SQL Primary | 97 Passed: LDD/GeoTIFF Registration, ACL, Revision/Hash/Result Conflict, Idempotency, Completeness≠Ready, FK Actor Nulling, Deferred Compatibility |
| Actual SQL Upgrade | 41 Passed: Migration/RLS/ACL/Gate/Unsupported-source checks |
| SQL → Python Source Identity | Passed จาก SQL Status จริงหลัง Rollback Fixtures |
| Preservation ทั้งสองฐาน | Passed ตามตารางด้านล่าง |
| Diff/Syntax | Passed; SQL Hash ตรง Review และ Ledger |

SQL Tests สร้างเฉพาะบัญชีจำลองใหม่และ Declaration ใน Transaction แล้ว Rollback
ทั้งหมด ไม่ลบบัญชีเดิม ไม่สร้างไฟล์ผลลัพธ์หรือเปลี่ยน Active Pointer
สิทธิ์ทดสอบผ่าน SET ROLE จริง แต่ไม่ใช่การออก JWT/Auth Flow รอบใหม่

ข้อผิดพลาดระหว่างพัฒนาเก็บหลักฐานไว้: ตัวเก็บ Snapshot เดิมคืน Hash เป็น text
แทน JSON และ SQL Test Harness เริ่มใช้สิทธิ์ Operator ผิดสำหรับ Private Functions
แก้เฉพาะ Harness/Role Restoration แล้วรันผ่าน ไม่เพิ่ม Grants เพื่อทำให้ Test ผ่าน
SQL037 ไม่เปลี่ยนหรือถูก Reapply หลัง Review/Apply

Not Tested / ไม่ได้ทำ:

- Positive Registration ใน Upgrade DB เพราะไม่มี Real-file Validation Results;
  Positive Path ใช้รายงาน Native ของ Synthetic Uploads ที่มีอยู่ใน Primary
- Trusted File Verification, Prepare Jobs, Actual Publication/Withdrawal/Rollback
  รวม Gate-open และ Concurrent Publish ซึ่งยังไม่ได้พัฒนาและไม่ได้รับอนุมัติ
- Concurrent Committed Registration Race; ทดสอบ Idempotency/Revision Negative Cases
  แต่ไม่อ้างว่าได้ทำ Multi-session Commit Race
- Browser/Frontend Build/Linux Scientific/Worker E2E รอบใหม่ เพราะไม่แก้ส่วนเหล่านั้น
- Official GIS Data, Production/Staging/GEE/Cloud และการออก Worker JWT ใหม่

## Data Preservation

เปรียบเทียบ Hash ก่อน Migration และหลัง Rollback Tests:

- Public Tables, Old Profiles และ Existing GIS Dataset/Edition/Job/Attempt/Result/
  Audit/Receipt ไม่เปลี่ยน รวม Active Pointers
- Function Definitions เดิมไม่เปลี่ยน; Registry ว่างหลัง Rollback Tests
- Ledger027–036 ตรงเดิม เพิ่มเฉพาะ037; Source000–036 ตรงไบต์ก่อนเริ่ม
- Gate ยังปิดทั้งสองฐาน; ไม่มี Legacy Cache Writes
- Primary Cache ที่ตรวจเป็นศูนย์; Upgrade มี ndvi_annual, province_lst_annual และ
  district_ndvi_annual อย่างละ1แถวและ Hash คงเดิม ไม่อ้างเป็นการทดสอบ Cache Swap

ไม่มีการอ่าน `.env`/Credentials, Provision/Auth Keys, Worker/Container/Image ใหม่,
เปิด Billing/IAM, ลบ Volumes หรือเปลี่ยน Deployment

## หลักฐานและ Source Fingerprint

หลักฐานภายนอก Repository อยู่ `<runtime-dir>/a1-publication-20261102/`:
`before.json`, `frozen-sql.json`, `migration-037.json`, `unit-tests.json`,
`unit-tests.log`, `sql-tests.json`, `preservation.json`, `final-evidence.json`.
เก็บ Source/Artifact SHA256 โดยไม่ใส่ Secrets หรือ Raw User Data ในรายงาน

## Git / งานถัดไป

Branch `feature/gis-data-management`; HEAD
`4c06fbd8a8f93af4dccf1a9389e277be98502185` ไม่เปลี่ยน
งาน A1 ยัง Uncommitted และรักษา Runtime Evidence Untracked เดิม5ไฟล์
ไม่มี Stage/Commit/Push/Merge/Deploy

พร้อมเสนอ **A2 — LDD Prepare & Preview**: ใช้ Queue/Worker/Storage เดิม ตรวจไฟล์
Artifacts จริงและ Coverage/Method ก่อนพัฒนาความพร้อม Publish ไม่ใช้ Hash Declaration
แทน File Verification และยังไม่เปิด Gate หรือเปลี่ยน Dashboard Readers โดยอัตโนมัติ
หยุดรออนุมัติ A2 หรือการเปลี่ยนขอบเขตอื่น
