# คำตอบแบบฟอร์ม C1 · ชุดทดสอบบนเครื่องที่ 2 (สัปดาห์ที่ 3, 16–22 พ.ย. 2569)

จัดทำโดยชยากร · รันแล้วรายงานผลเท่านั้น ไม่ได้แก้โค้ด ชุดทดสอบ หรือ migration · ข้อมูลบน T0 เป็นข้อมูลสังเคราะห์ในเครื่อง (local) ไม่ได้แตะระบบ deployed

| ช่อง | คำตอบ |
|---|---|
| 1. รุ่น Windows, Python, Docker Desktop และ `git config core.autocrlf` | Windows 11 Home Single Language 26H2 (10.0.26300 build 26300) · Python 3.11.9 · Docker Desktop 4.91.0 (Engine 29.8.0, Compose v5.5.1) · `core.autocrlf = true` (ค่าจาก gitconfig ระดับระบบ ไม่ได้แก้) |
| 2. `git rev-parse HEAD` และ `git branch --show-current` | `540280594b1e01dcaa263a250e94c0f772156fa8` · `gis-unlock` (`ภาพที่1-C1-commit.png`) |
| 3. วันและเวลาที่ T0 ผ่านขั้นที่ 13 | **16/11/2569 23:42:38** (เริ่มขั้น 1 เวลา 23:28:27) · ทุกขั้นตรงกับ "ผลที่ควรเห็น" ใน `dev/gis_local/t0-rebuild/README.md` · probe 047 ผ่านรอบแรก (`c-step01.log` … `c-step13.log`, `ภาพที่2-C1-readiness.png`) |
| 4. ชุด 1 backend (passed / failed / skipped) | **2134 passed / 47 failed / 81 skipped** · เครื่องหัวหน้า 2180 passed / 0 failed / 82 skipped · รวมเท่ากัน 2262 ข้อ (`c1-backend.xml`) |
| 5. ชุด 2 dev (passed / failed / skipped) | **338 passed / 0 failed / 0 skipped** (37 subtests passed) · ตรงกับเครื่องหัวหน้า (`c1-dev.xml`) |
| 6. ชุด 3 native (ผ่าน / ไม่ผ่าน) | **ผ่านทุกข้อ (217 passed, 0 failed)** (`05-native.log`) |
| 7. ชุด 4 T1 ฐาน postgres / gis_t1_upgrade และ T2 (Pass / Fail) | T1 `postgres` **85 Pass / 0 Fail** · T1 `gis_t1_upgrade` **85 Pass / 0 Fail** · T2 **129 Pass / 0 Fail** · ตรงกับเครื่องหัวหน้า (`08-t1-postgres.log`, `09-t1-upgrade.log`, `10-t2.log`) |
| 8. ข้อที่ไม่ตรงกับเครื่องหัวหน้า พร้อมชื่อเทสต์และสาเหตุ | ชุด 1 ล้ม 47 ข้อ ทุกข้อเพราะ fixture เป็น CRLF · skip ต่าง 1 ข้อ (symlink) · รายละเอียดด้านล่างและใน `c1-backend-failures.md` |
| 9. ชื่อไฟล์ผลในโฟลเดอร์ evidence และรหัส commit ของ tag C1 | รายการด้านล่าง · commit: ดู tag C1 |

## ช่อง 8: ข้อที่ไม่ตรงกับเครื่องหัวหน้า (สรุปจาก `c1-backend-failures.md`)

### ก. ชุด 1 ล้ม 47 ข้อ สาเหตุเดียวกันทุกข้อ: fixture เป็น CRLF
| ไฟล์เทสต์ | จำนวน | error |
|---|---|---|
| `tests/test_processing_provider.py` | 32 | 31 ข้อ `ProcessingError: PROCESSING_FIXTURE_INVALID` · 1 ข้อ (`test_source_hash_drift_fails_before_ast_or_numeric_result`) `AssertionError` คาด `PROCESSING_LEGACY_SOURCE_CHANGED` ได้ `PROCESSING_FIXTURE_INVALID` |
| `tests/test_gee_mock_daemon.py` | 12 | `PROCESSING_FIXTURE_INVALID` |
| `tests/test_source_integrity.py` | 3 | `PROCESSING_FIXTURE_INVALID` |

ล้มเพราะขนาดหรือ sha256 ของ fixture ไม่ตรง 47 ข้อ · สาเหตุอื่น 0 ข้อ · ไฟล์ `green-area-backend/gis_worker/processing_fixtures/processing_*.json` ทั้ง 6 ไฟล์ไม่มีกฎ `-text` ใน `.gitattributes` เมื่อ `core.autocrlf=true` จึง checkout เป็น CRLF (`git ls-files --eol`: `i/lf w/crlf attr/`) ไฟล์ใหญ่ขึ้นไฟล์ละ 1 ไบต์ และ `processing_provider.py:219` ตรวจขนาดและ sha256 แบบ LF ที่ปักไว้ จึงไม่ตรง · ทางแก้น่าจะเป็นการตั้ง `-text` ให้ fixture ชุดนี้ (หัวหน้าตัดสิน ไม่ได้แก้)

### ข. ชุด 1 skip ต่าง 1 ข้อ
`tests/test_gis_native_provider.py::test_symlink_artifact_is_rejected` (บรรทัด 135) · เครื่องหัวหน้า skip ("Host does not permit symlink creation; Linux run required") · เครื่องนี้สร้าง symlink ได้ จึงรันและผ่าน

### ค. ขั้นตอนบนเครื่องใหม่ที่ต่างจากเอกสาร
1. `git clone` แบบไม่ระบุบรานช์จะ checkout `main` ก่อน (ไม่มีกฎ `-text` ของ migration 000–026) แล้ว `git switch` ไป 5402805 ไม่เขียนไฟล์ที่ blob เท่าเดิมใหม่ ไฟล์ 27 ไฟล์จึงค้างเป็น CRLF · ลบ clone แล้ว clone ใหม่ด้วย `git clone -b gis-unlock` ผ่าน · เสนอให้ README ขั้น 0 ระบุ `-b gis-unlock`
2. เครื่องไม่มี Python 3.11 ต้องติดตั้งเพิ่มก่อนสร้าง venv
3. T0 เดิมหยุดแบบ `Exited (255)` · pg_dump ต้องให้ db ทำงาน จึง tar volume ในสภาพที่เจอก่อน แล้ว start เฉพาะ db เพื่อ dump แล้ว stop และ tar อีกรอบ (`06-old-t0-backup.log`)
4. ไม่ได้รัน `git fetch` / `git switch` / `git pull` ของ README ขั้น 0 ตามกฎงานนี้ (clone อยู่ที่ `origin/gis-unlock` = 5402805 แล้ว) และใช้ image ที่มีในเครื่องตามที่หัวหน้าอนุญาต

## ช่อง 9: ไฟล์ในโฟลเดอร์ `docs/gis/evidence/16_20-chayakorn/c1/`
- ผลชุดทดสอบ: `c1-backend.xml` (ชุด 1), `c1-dev.xml` (ชุด 2), `05-native.log` (ชุด 3), `08-t1-postgres.log`, `09-t1-upgrade.log`, `10-t2.log` (ชุด 4)
- T0 เดิมและขั้น 0: `06-old-t0-backup.log` (รายการ container/volume/network เดิม และรายชื่อไฟล์สำรองพร้อมขนาดและ SHA256 · ไฟล์สำรองเก็บนอก repo), `07-step0.log` (ลบ T0 เดิม · `docker ps -a` และ `docker volume ls` ว่าง · `docker image inspect` ของ image ที่ปักไว้)
- สร้าง T0 ใหม่: `c-step01.log` … `c-step13.log`
- สรุปข้อล้ม: `c1-backend-failures.md`
- ภาพ: `ภาพที่1-C1-commit.png`, `ภาพที่2-C1-readiness.png`, `ภาพที่3-C1-backend-dev.png`, `ภาพที่4-C1-native-t1t2.png` (ภาพ 3 และ 4 อ่านค่าจาก log ที่บันทึกไว้ ไม่ได้รันซ้ำ)
- commit: ดู tag C1
- หมายเหตุ: ใน log ที่อยู่ในโฟลเดอร์นี้ path ของโฟลเดอร์ runtime และโฟลเดอร์สำรองบนเครื่องถูกแทนด้วย `<runtime-c1>` (runtime ของ T0 ใหม่), `<runtime-old>` (runtime ของ T0 เดิม) และ `<backup-20261117>` (โฟลเดอร์ไฟล์สำรอง) · ส่วนอื่นของ log ไม่ได้แก้

## ยังไม่ได้ทำหรือยังไม่ยืนยัน
- ยังไม่ได้รันชุด 1 ซ้ำแบบที่ fixture เป็น LF เพื่อยืนยันว่า 47 ข้อจะผ่าน (ต้องแก้ไฟล์ใน clone ซึ่งขัดกฎงานนี้)
- ยังไม่ได้ลอง restore ไฟล์สำรอง T0 เดิม (ตรวจแค่ `pg_restore --list` และจำนวน entry ใน tar)
