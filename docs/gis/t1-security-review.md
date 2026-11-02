# T1 Independent Database / Security Review

วันที่ตรวจ: 27 ตุลาคม 2026 — ขอบเขตเฉพาะ Local Synthetic Sandbox

ผู้ตรวจอิสระ: `t1_schema_security_design` แยกจากผู้เขียน Migration และผู้รันทดสอบ
เป็นการอ่านโค้ดแบบ Static ไม่ได้รัน SQL หรือทดสอบแทนผู้ดำเนินงาน

ผลสุดท้ายก่อนรัน Migration ใหม่: **ไม่มี High/Critical ที่ยังไม่ได้แก้ไข**
การอนุมัติผูกกับ SHA256 ใน `dev/gis_local/t1-review.json` เท่านั้น

| ไฟล์ | SHA256 ที่อนุมัติและนำไปรัน |
|---|---|
| 027_gis_foundation.sql | bc879ca55e26a506e4b36c887dede928b07c619c42c94ddf69282362abd351e5 |
| 028_gis_queue.sql | fcf5d9530b516d93dda0fc2ea5b01158809aad237c1e90863d09bd324c9000d1 |
| 029_gis_transactions.sql | 7faf7bf6abbd4e52ab8389423c3c1876c94af459fe9d7c5d2a7710ffc0f236a5 |

## สิ่งที่ตรวจและปรับก่อนอนุมัติ

| ประเด็น | หลักฐาน/ผลการแก้ |
|---|---|
| Local target | Container/instance/image/network/mount/limits เดิมของ T0 + cluster/database + marker; ไม่มี URL ของฐานภายนอก |
| Owner | gis_owner NOLOGIN, NOSUPERUSER, NOBYPASSRLS; ตารางใหม่ FORCE RLS; owner policy เฉพาะบทบาทนี้ |
| Legacy privilege | SELECT/REFERENCES เฉพาะคอลัมน์ profiles/provinces และ owner-only SELECT policies; ไม่เปลี่ยน profile roles หรือเขียน Cache |
| Function security | SECURITY DEFINER เป็นเจ้าของโดย gis_owner, search_path คงที่ pg_catalog,gis; revoke PUBLIC/anon/authenticated แล้ว grant wrapper แบบระบุ signature |
| Worker boundary | gis_worker NOLOGIN, ไม่มีสิทธิ์ตาราง GIS/Cache และไม่มี service-role RPC; execute เฉพาะ worker wrapper |
| Actor | service_role-only wrapper คือขอบเขตการรับ actor ที่ Backend ต้องยืนยันจาก JWT; ตรวจ profile/grant สดก่อน mutation/replay |
| Account deletion | พบปัญหา High ในแบบร่างที่เก็บ UUID ซ้ำใน JSON; แก้โดยตัดสำเนา actor ออกจาก receipt และย้าย subject ของ audit เป็น nullable FK |
| State integrity | เพิ่ม immutable row guards + deferred constraints: edition/job/attempt/result/active pointer ต้องตรงกันเมื่อจบ transaction |
| Queue | Claim atomic, SKIP LOCKED + single-concurrency gate; edition ก่อน job; lease/token/owner/time ตรวจหลังได้ lock; retry มีขอบเขต |
| Lock order | เปลี่ยน dataset mutation lock เป็น NO KEY UPDATE ให้เข้ากับ FK KEY SHARE; clone จัด dataset ก่อน edition; actor/subject lock เรียงลำดับ |
| Migration atomicity | อ่านและใช้ bytes ชุดเดียวกับที่ตรวจ hash; DDL และ ledger อยู่ใน transaction เดียว |
| Existing GIS schema | Runner ต้องตรวจ marker+ledger ก่อนต่อจาก schema ที่มีอยู่; schema ที่ระบุตัวตนไม่ได้ไม่ผ่าน |

ผู้ตรวจอ่านซ้ำหลังแก้ High และหลังเพิ่ม integrity triggers ก่อนอนุมัติ bytes สุดท้าย
Migration ทั้งสามจึงถูกนำไปรันทดสอบ Local หลังผ่าน Gate นี้แล้ว

ตรวจรอบท้ายเพิ่ม: resume/stop ใช้ ID ของ Container ที่ตรวจ ownership แล้วและคง Volumes;
Audit-failure fixture อยู่ใน rollback transaction; Lease-wait fixture เปลี่ยนเฉพาะงาน
สังเคราะห์ของตัวเอง, ไม่เก็บ token ลงรายงาน และจบงานผ่าน queue protocol
ไม่มี High/Critical ใหม่จากการตรวจส่วนดังกล่าว

## ขอบเขตของข้อสรุป

การตรวจ Static ไม่ยืนยันว่าระบบปลอดภัยทุกกรณี ผลทดสอบจริงแยกอยู่ใน
`t1-handoff.md` และ `t1-test-evidence.json` โดยผู้ดำเนินงานเป็นผู้รัน

- SET ROLE ตรวจ ACL/RLS ภายใน PostgreSQL แต่ไม่ใช่การ Login ด้วยตัวตน Worker จริง
- ยังไม่มี Backend JWT-to-RPC E2E; actor parameter ต้องไม่มาจาก HTTP body ใน T2
- Secondary DB มีเพียง Auth structure ที่คัดลอก ไม่ใช่ Supabase Auth service ที่เทียบเท่าทั้งชุด
- การรันทดสอบต้องใช้ Queue สังเคราะห์ที่ว่างและไม่มี Worker อื่นทำงานร่วม
- Result/report read DTO และการแบ่งหน้ารายชื่อ Officer เป็นงานต่อเนื่องใน T2
- SQL protocol fixture ไม่ใช่หลักฐานการตรวจไฟล์ GIS จริงหรือคำนวณ NDVI/LST
- ไม่ได้อนุมัติ Cloud/Production, IAM, Billing, GEE หรือ Task ถัดไป
