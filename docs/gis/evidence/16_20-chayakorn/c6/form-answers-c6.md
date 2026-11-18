# คำตอบแบบฟอร์ม C6 · ยืนยันการแก้ CRLF ของ fixture ที่ 7501cc8 (สัปดาห์ที่ 3 งานเพิ่มเติม)

จัดทำ 18/11/2569 โดยชยากร · รันแล้วรายงานผลเท่านั้น ไม่ได้แก้ไฟล์ใน clone · ไม่ได้แตะ T0 · ชุดทดสอบใช้ข้อมูลสังเคราะห์ในเครื่อง (local)

| ช่อง | คำตอบ |
|---|---|
| 1. รหัส commit ที่ทดสอบ และผล `git ls-files --eol` ของ fixture | `7501cc87782a1441dc5678fa5504cf37bc1495d2` ("fix(gis): keep processing fixtures LF on CRLF checkouts") บน `gis-unlock` · clone ใหม่ด้วย `git clone -b gis-unlock` บนเครื่องที่ `core.autocrlf = true` · `git status --short` ว่าง · fixture `green-area-backend/gis_worker/processing_fixtures/` ทั้ง 6 ไฟล์เป็น **`i/lf w/lf attr/-text`** (`c6-eol.txt`) |
| 2. ชุด backend (passed / failed / skipped) | **2181 passed / 0 failed / 81 skipped** (93 warnings, 207.92 วินาที) · **ตรงกับที่คาด** · เทียบ C1 ที่ 5402805 (2134 / 47 / 81): 47 ข้อที่เคยล้มด้วย `PROCESSING_FIXTURE_INVALID` ผ่านหมด · รายการ skip ตรงกับ C1 ทุกบรรทัด (81 = 81) · junit: tests 2262, failures 0, errors 0, skipped 81 (`c6-backend.xml`) |
| 3. ชื่อไฟล์ผลในโฟลเดอร์ evidence และรหัส commit ของ tag C6 | `c6-run.log` (คำสั่งและผลทั้งหมด ขั้น 1–6) · `c6-eol.txt` · `c6-backend.xml` · `ภาพที่3-C6-eol-pytest.png` · `form-answers-c6.md` · commit: ดู tag C6 |

## หมายเหตุ
- คำสั่งติดตั้งและรันเทสต์เหมือน C1: `py -3.11 -m venv green-area-backend\.venv` · `pip install -r green-area-backend\requirements.txt` · `pip install -r green-area-backend\requirements-native.txt` · (ใน `green-area-backend`) `python -m pytest tests/ -q -rs --junitxml=…` (Python 3.11.9)
- ใน `c6-run.log` path บนเครื่องถูกแทนด้วย `<clone-c6>`, `<clone-c1>`, `<evidence-c6>` · `c6-backend.xml` เป็นไฟล์จาก pytest ตามเดิม (ยังมี path ของ clone และโฟลเดอร์ temp แบบเดียวกับ `c1-backend.xml`)
- ภาพที่ 3: ผล `git ls-files --eol` รันสดตอนถ่ายภาพ ส่วนบรรทัดสรุปของ pytest อ่านจาก `c6-run.log` ไม่ได้รันเทสต์ซ้ำ
- clone `green-area-c6` และ venv เก็บไว้ ไม่ได้ลบ (ใช้ต่อใน C4 และ C5)
