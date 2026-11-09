# T2 Independent Security / SQL Review

วันที่: 27 ตุลาคม 2026 — Local Synthetic Sandbox เท่านั้น
ผู้ตรวจอิสระ: `t2_review` แยกจากผู้เขียน API/SQL และผู้รันทดสอบ

## ขอบเขตและผลตรวจ

ผู้ตรวจอ่าน SQL030 ก่อนใช้จริง และอ่าน `gis_runtime.py`, `gis_app.py`,
`gis_schemas.py`, `gis_service.py`, `routers/gis.py`, diff ของ `main.py`,
`t2_local.py` และ `t2_integration.py` พร้อมการแก้ไขล่าสุด
**ไม่มี High/Critical ที่ยังไม่ได้แก้ในขอบเขตที่ตรวจ**
เป็น Static Review ผู้ตรวจไม่ได้รัน SQL หรือ Tests เอง ผลทดสอบต้องอ้างอิง
หลักฐานของผู้ดำเนินงานใน `t2-test-evidence.json` และ `t2-handoff.md`

อนุมัติ Migration ใหม่เฉพาะ bytes นี้ ผ่าน Local Runner ที่ตรวจแล้ว:

| ไฟล์ | SHA256 |
|---|---|
| 030_gis_api_reads.sql | 0c6cd4b6fb3fe964dfcba848bf392a9b93cea87be7c15fd214cfe5e435b6f113 |

## รายการที่ตรวจ

| เรื่อง | ข้อสรุปจากโค้ด |
|---|---|
| Target | URL/DB/cluster/mode allowlist ตายตัว ตรวจ Container ownership/health และ marker ก่อนสร้าง Client, ก่อน Auth และก่อน SQL RPC |
| Local credentials | อ่านเฉพาะ development API keys ที่ T0 สร้างใน Gateway ที่ยืนยันแล้ว เก็บใน memory ไม่โหลด Production.env/GEE หรือ Signing Secret |
| Network | แยก Auth/service SDK clients, ปิด environment proxy และ redirects, timeout/retry มีขอบเขต |
| JWT | ตรวจ issuer/audience/time/role/sub เพิ่มเติม แล้วต้องผ่าน Auth get_user จริงและคืน UUID เดียวกัน; unsigned claims ไม่ใช่หลักฐานยืนยันตัวตน |
| Actor/roles | Actor จาก Dependency ที่ยืนยันแล้ว; SQL ตรวจ profile/grant สด ไม่เชื่อ Body, user_metadata หรือ X-Admin-Token |
| SQL030 | Guard ตรวจ T1 checksums/instance, เปลี่ยน GIS ledger CHECK แบบ forward, DDL+ledger atomic และ reload PostgREST เมื่อ commit |
| RPC privileges | Definer owner/search_path ชัดเจน; readiness/service read ไม่เปิด PUBLIC/anon/authenticated; ไม่เปลี่ยน Worker/Command permissions เดิม |
| Read DTO | Filter/cursor แบบ typed parameters, bounded pagination, parent404, รายงานจริงหรือ null, ตัด lease/worker/actor metadata |
| HTTP input | Pydantic extra-forbid/finite/bounds, Header key UUID เดียว, explicit nullable pointers, JSON body64KiB, ไม่ echo input/errors ของ SDK/SQL |
| Rate/CORS | GIS429 แยกรูปแบบและ delegate Legacy กลับ Handler เดิม; CORS ครอบ body guard; ไม่เพิ่ม wildcard/origin |
| Local entrypoint | ไม่ import legacy dependencies/main/dotenv/GEE; main ปกติเปิด GIS แบบ disabled |
| State changes | ใช้ T1 transaction RPC เดิม; idempotency/revision/permission recheck; Activation ต้องสอง Gate และ Synthetic Sandbox |
| Test harness | จำกัด3ผู้ใช้/2Dataset/4Edition/4Job, บัญชีและ Token อยู่ใน memory, ไม่ลบข้อมูลเก่า, Gate คืน false |

## จุดที่แก้จากข้อเสนอ Review

- ปฏิเสธ JWT JSON recursion/overflow โดยไม่ปล่อยให้กลายเป็น500
- Job query รับ Dataset identity filters ตรงกับ SQL030
- ซ่อน lease_until นอกเหนือจาก token/worker/actor fields
- จัด Main body guard ก่อน CORS; oversized GIS errors จึงอ่านได้จาก Origin ที่อนุญาต
- GIS429 มี `detail:{code,message,fields}` โดยคง Legacy handler
- `/gis/me` แสดงทั้ง Backend/Database gates และค่าเปิดใช้งานที่รวมสอง Gate
- ปฏิเสธ Authorization Header ซ้ำ; ยังคง target proof ก่อน Auth และ SQL
  (ปรับ 8 พ.ย. 2569 ตาม `w5-ldd-publication-design.md` หัวข้อ 6.4 ที่ผู้ใช้อนุมัติ: คำขอ GET/HEAD `/gis` หนึ่งครั้งพิสูจน์เป้าหมายเต็มครั้งเดียวก่อน Auth แล้วใช้ผลนั้นกับ SQL/ไฟล์ของคำขอเดียวกัน ·
  คำขอเปลี่ยนข้อมูล, เส้นทางอื่น, worker และ CLI ยังพิสูจน์ก่อน Auth และ SQL ทุกครั้ง · ไม่เก็บผลข้ามคำขอ ไม่เก็บผลที่ล้ม และ transport error ก่อน retry ทำให้พิสูจน์ใหม่)
- Cleanup ทำตาม Queue order และปฏิเสธการแตะงานที่ไม่อยู่ในรอบทดสอบ

## ข้อจำกัดของการรับรอง

- ต้องรัน Integration Harness บน Queue สังเคราะห์ที่ว่างและไม่มี Producer/Worker อื่น
  การตรวจชุดงานก่อน Cleanup ไม่ใช่ระบบรองรับการรันทดสอบหลายรอบพร้อมกัน
- ไม่มี Worker HTTP endpoint/Python Worker/GIS computation หรือ Cloud approval
- Manual SQL worker calls ใน Harness มีไว้เตรียมสถานะสำหรับทดสอบ API เท่านั้น
- แยก tampered-token cases ออกจาก valid-signature altered-claim cases ที่ Not Tested
- ไม่อ่าน Signing Secret เพื่อสร้าง JWT ที่มีลายเซ็นจริงสำหรับกรณีลบเหล่านั้น
- Static Review และ Local E2E ไม่ยืนยัน Production/ทุก concurrency interleaving/load/soak
- เหตุผล/ชื่อข้อมูลเป็น free text ที่ผู้มีสิทธิ์เขียนเอง ไม่ได้อ้างว่าล้าง PII ทุกข้อความ

ระบบอนุมัติอัตโนมัติปฏิเสธแนวทางทดลองเริ่มต้นที่อ่าน Signing Secret เพื่อสร้าง JWT
จึงเปลี่ยนเป็น Auth-issued tokens + tampered tokens/ลายเซ็นผิด และระบุส่วนที่ไม่ทดสอบ
ไม่มีการใช้วิธีเลี่ยงการตรวจ ไม่มีการอ่าน Signing Secret หรือเปิดเผย Credentials
