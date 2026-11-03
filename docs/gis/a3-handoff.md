# A3 Handoff — PASS (Local Synthetic only)

วันที่3พฤศจิกายน2026 · Branch `feature/gis-data-management` · HEAD
`58957c283c87f8ddf176ac2ca95b08952489daaa` คงเดิม ไม่มี Commit/Push/Deploy

## เป้าหมายและสิ่งที่พัฒนา

เชื่อม LDD ที่ Upload/Validate/Prepare/Trusted Verify แล้วเข้ากับ Dashboard ผ่าน
Published Provider แยกจาก Legacy โดย Admin เปิดใช้/เปลี่ยนฉบับ/ย้อนกลับ/ถอนใช้เอง
ครอบคลุมจังหวัดและปี (month0) ใน Local เท่านั้น ไม่เปลี่ยน NDVI/LST/GEE เดิม

ข้อเท็จจริงจาก Source: A2 เก็บ ZIP และ Geometry/Summary แบบ Immutable พร้อม
Certificate แต่เดิมยังไม่มี Dashboard reader ที่อ่าน Active Pointer เส้นทางA3
เพิ่มการตรวจไฟล์ใหม่ก่อนเปลี่ยน Pointer และ reader ที่ตรวจไฟล์/Source Snapshot
ทุกคำขอ โดยใช้ Catalog/Queue/Prepare/Artifact Registry และ Auth เดิม

- คง Broad SQL/Backend Activation Gates เป็น false เพิ่ม private Local LDD flag
  และ service-only RPC สามรายการ ผู้ใช้ทั่วไปอ่าน Published ได้โดยไม่ให้สิทธิ์ Catalog
- Admin mutations ตรวจ JWT Actor, Revision CAS, pointer/lineage/hash/year/method/
  coverage, certificate และ fresh native original/object bytes ภายใต้ store lock
- Pointer/Audit/Receipt อยู่ใน transaction เดียว Idempotent replay คืนประวัติ
  โดยไม่เปลี่ยน Pointer กลับไปตาม Receipt เก่า
- A→B ไม่ถอนA จึง Rollback ได้ ส่วน Withdrawal เป็น terminal และเก็บไฟล์/ประวัติ
- Dashboard เลือก Published อย่างชัดเจน ใช้ Geometry/Legend/Summary bundle เดียว
  Legacy Dynamic World ยังคง default ไม่มี silent fallback เมื่อ Published เสีย
- Cache Published แยก SourceIdentity, snapshot, input revision และ artifact hashes
  อ่านไฟล์ใหม่แม้ summary cache hit ไม่ cache pointer/geometry และไม่ล้าง Legacy cache

รายละเอียด Contract/วิธีเปิด Local demo: [a3-contracts.md](a3-contracts.md)

## Migration และ Independent Review

039 เพิ่ม Functions/trigger เฉพาะ Dataset และ private RPC ไม่มีตารางใหม่/ไม่มี
การแก้ Migration000–038 หรือ Ledger เดิม ก่อนรันผ่าน exact independent review

Runtime พบ SQL42725 จาก operator precedence ของ JSONB ขณะ Activation ครั้งแรก
Pointer ยังเป็น null แก้ด้วย040แบบ forward-only โดยไม่แก้039 จากนั้นทดสอบต่อด้วย
ไฟล์A/B/Cชุดเดิมที่เคยผ่าน native pipeline แล้ว และตรวจbytesใหม่ก่อนเปิดใช้

| Migration | SHA256 |
|---|---|
|039|`ec1966a73fc8b463aa154b33a3dca5d9ab7d22ff679086da46b8ba41434dd118`|
|040|`dc397a2aaa0020768b71364f2116823134a745a0c66863569b250ca7417e1185`|

040เปลี่ยนเฉพาะวงเล็บเป็น `((p_proof->'report')-'verifier_version')` ใน Function
เดิม ไม่เปลี่ยน Contract/ACL ทั้งสอง Migration ใช้แล้วเฉพาะ `postgres` และ
`gis_t1_upgrade` ของ Local cluster ที่พิสูจน์ Identity ก่อนรัน

ผู้ตรวจ `local_integration_security_review` ตรวจ Exact SQL/Privileges ก่อนรัน
ทั้ง039/040 และตรวจ Source/Evidence/ภาพรอบสุดท้าย ผล PASS, High/Criticalคงค้าง0
ผู้ตรวจไม่ได้รันทดสอบใหม่เอง ตรวจหลักฐานที่มีจริงและยืนยัน Hash ตรงกับไฟล์ปัจจุบัน

## ผลทดสอบจริง

| ชุด | ผล |
|---|---|
|Backend/Local guard regression|587passed +37subtests|
|Linux Native scientific/prepare/publication verifier|56passed|
|Frontend focused+Dashboard/routing/selection regressions|115passed (71+44)|
|Frontend Local-only build|PASS; มีคำเตือน bundleขนาดใหญ่เดิม|
|Latest Local HTTP/Auth/SQL/native integration|40/40|
|Real Browser (ไม่ mock API)|8/8|
|Final read-only preservation/security ทั้งสองฐาน|28/28|

ยืนยัน ActivateA→B→RollbackA, historical replay ไม่ republish, concurrent CAS
สำเร็จหนึ่งคำสั่ง, revision/pointer/hash/lineage/province/year conflicts ถูกปฏิเสธ,
Officer/normal mutation403, normal read200, anonymous401 และการถอนแบบ terminal
ทั้ง inactiveB, activeCแทนด้วยA, activeA→null

บังคับ failure หลัง Function เขียน Pointer/Audit/Receipt และตรวจ Deferred
Constraints แล้วด้วย SQL subtransaction: ย้อนกลับครบ ไม่มี Receipt/Pointerค้าง
ตรวจ Audit ที่ commitจริง9รายการ กรณีไฟล์ targetหาย/เสียหายก่อนเปิดใช้ถูกปฏิเสธ
กรณี activeไฟล์หาย HTTPไม่ส่ง Geometry และเพิกถอนCertificate จากนั้นยังถอนฉบับ
ที่เสียหายและแทนด้วยAที่ตรวจbytesใหม่ได้

Browser ยืนยัน normal login, Legacy default, Published currentEdition3features/
6400m², geometry+summary+legend snapshotเดียว, source switchล้างPublished และ
district navigationเดิมยังอยู่พร้อมปิดตัวเลือกPublishedในขอบเขตอำเภอ ตรวจภาพจริงแล้ว

ก่อนหน้ามี test-harness setup failures เรื่อง roleสำหรับ seed/readตารางLegacy
และ information_schema visibility แก้เฉพาะ harness ไม่เพิ่มสิทธิ์ Application/
Worker และเก็บผลรอบล้มเหลวไว้ ไม่ถือว่าเป็นผลผ่าน

## Preservation และ Evidence

เติม Synthetic NDVI/LST cache และ Saved Area ของผู้ใช้ทดสอบก่อนทดลอง แล้วเทียบ
hashของทุก Legacy public tableก่อน/หลัง รวมถึง in-process Legacy landuse sentinel
ผลตรงกัน ไม่ล้างcache ส่วนบัญชี/fixtureใหม่เก็บไว้ แยกจากข้อมูลเดิม

Final read-only เทียบทุก GIS row เดิม, profileเดิม, Function bodyเดิม, Ledgerเดิม,
SQL000–038, raw evidenceเดิม5ไฟล์: ตรงทั้งหมดทั้งสองฐาน SHA039/040ตรงLedger
ตรวจRLS/owner/search_path/service-onlyACL และ workerไม่มีGIS DMLผ่านทั้งสองฐาน

Evidenceอยู่นอกRepositoryใต้ owned runtime `a3-ldd-publication/`:

- `evidence-index.json`, `before.json`, `final-preservation.json`
- `integration-6e7f2f0d07/results.json`, `browser-results.json`, ภาพ map/summary
- `integration-c89acb90d5/results.json`: Upload/Native Validation/Prepare A/B/C
  ผ่านก่อนพบ039parser error ใช้ซ้ำโดยตรวจbytesใหม่ ไม่อ้างว่ารันใหม่ทุกเคส
- `unit-tests.json`, `linux-science.json/log`, `migration-039.json`, `migration-040.json`

Final code-source fingerprint:
`a5911fe8698ebc7042f8f092358ed14d236d7d927dd29d2e5a80df504f24267a`
Manifestของintegrationมีขอบเขตต่างจากfinal-preservationจึงมีaggregateHashต่างกัน
ผู้ตรวจยืนยันHashทุกไฟล์ในทั้งสองManifestตรงกับSourceปัจจุบัน

## ไฟล์ที่เพิ่ม/แก้

- SQL039/040 + `.gitattributes` และ exact review JSON2ไฟล์
- Backendใหม่ `gis_ldd_publication.py`, `routers/ldd_publication.py`, native
  `gis_worker/ldd_publication_child.py`; ปรับ app/runtime/service และ `/gis/me`
- Local operator/checks/guard tests ใหม่; ปรับ `manage.py` เฉพาะ approvalของ
  network-none read-only verifier; เพิ่ม `a3_demo.py`, `a3_smoke.cjs`;
  `legacy_demo.py`ผูกprivate providerโดยไม่เปลี่ยนLegacy readers
- Frontendเพิ่ม `LddPublicationActions`, `PublishedLddSummary`, Published maplayer;
  เชื่อมในGIS/Dashboard/LandusePanel/StatsTab/MapLegend/hooks/gisClient พร้อมtests
- เอกสารA3 contracts/handoff ไม่มีRuntime evidenceหรือCredentialsในRepository

## ข้อจำกัด / Not Tested / งานถัดไป

- ผ่านเฉพาะSynthetic3features6400m² ไม่ยืนยัน LDDจริง/ความครบทั้งจังหวัด/Production
  ขอบเขตจังหวัดประมาณ, legend96codes, ปีจากmetadataตามข้อจำกัดA2
- Local Published DTOสูงสุด2MiB ไม่ตัดGeometryเงียบ ๆ ยังไม่พิสูจน์งานจังหวัดขนาดใหญ่
- Active-missing HTTPทดสอบจริง ส่วน corrupt-after-active cached readพิสูจน์ด้วย
  Native/Provider unit testsและcorrupt-before-activation HTTP ไม่ได้แยกทดสอบ
  physical corrupt-after-active HTTPอีกรอบ ไม่มีการอ้างว่าผ่านกรณีที่ไม่ได้รัน
- Clientตรวจใหม่ทุก10วินาทีเมื่อมองเห็นและเมื่อfocus/notification ไม่ใช่pushทันที
- Live Legacy GEE, GeoTIFF publication, Cloud/Productionไม่ได้ทดสอบหรือดำเนินการ
- API/UI/Workerของรอบทดสอบหยุดครบ ไม่มีcleanup errors เหลือCore4ตัวhealthy
  เก็บimages/volumes/ข้อมูลเดิมและfixtureใหม่ A/B/Cสุดท้ายwithdrawnตามกรณีทดสอบ
- Working TreeยังdirtyตามงานA3 และเก็บuntracked evidenceเดิม5ไฟล์ไว้ครบ

พร้อมเสนอ A4 เพื่อขออนุมัติเท่านั้น ยังไม่เริ่มA4–A6 ไม่มีCommit/Push/Merge/Deploy
การตัดสินใจถัดไป: ตรวจรับA3และอนุมัติขอบเขตA4แยกต่างหาก
