# T3 Implementation Handoff — Python GIS Worker & Synthetic Validation

**สถานะ:** T3 เสร็จสมบูรณ์ (Completed) พร้อมหลักฐานการทดสอบครบทุกชั้น  
**วันที่:** 28 ตุลาคม 2026  
**Branch:** `feature/gis-data-management`  
**HEAD:** `048273f7b69ec6b60ac02f18ddbd1007619bd574`  

---

## 1. Executive Summary & Objective

การดำเนินงานใน Task T3 เพื่อพัฒนา **Python GIS Worker & Synthetic Validation** ต่อจาก ChatGPT Work ที่ติด Usage Limit ได้เสร็จสมบูรณ์ตามขอบเขตที่ได้รับอนุมัติ 100%:
1. **Worker Identity Gate:** พิสูจน์บทบาท `gis_native_worker` สิทธิ์จำกัดแบบ Least-Privilege ผ่าน GoTrue/PostgREST โดยไม่แตะต้อง Service Role Key หรือ Signing Secrets
2. **Forward Migration 031 (`031_gis_native_v2.sql`):** เพิ่ม Synthetic V2 Catalog, ฟิลด์ `validation_report` ใน `gis.attempts` และ RPC `gis_worker_v2` รองรับ V1 Compatibility สมบูรณ์
3. **API & Target Guard Extension:** รองรับ Schema V1/V2 Manifests และขยาย Target Guard อนุญาต Linux Worker Container สำหรับ Isolated Execution
4. **Python GIS Queue Worker Daemon:** พัฒนา `GisWorker` ทำงานร่วมกับ Database State Machine แบบ Atomic, Heartbeat Thread, Fencing และ Isolated Child Process
5. **End-to-End Integration & Regression Suite:** ผ่านการทดสอบครอบคลุม API $\rightarrow$ Queue $\rightarrow$ Worker $\rightarrow$ Linux Isolated Container $\rightarrow$ Database State Machine (24/24 Pass) และ Regression ทั้งหมด 231 ข้อทดสอบ (100% Pass)

---

## 2. Implementation Overview

### 2.1 Worker Identity & Role Gate
- **Role:** `gis_native_worker` ภายใต้ Supabase GoTrue Auth
- **RPC Whitelist:** เรียกได้เฉพาะ `gis_worker_v2` และ `gis_worker_ready`
- **Rejections:** ปฏิเสธการเรียก Admin RPC (`gis_command`, `gis_read`), Direct Table Writes บน `gis.*` และ Legacy Direct Cache Operations
- **Verification Script:** `dev/gis_worker/t3_identity.py` (12 Pass / 0 Fail)

### 2.2 Forward Migration 031 (`green-area-backend/migrations/031_gis_native_v2.sql`)
- **SHA256:** `85d345fa5b8dca615735618f7d9e689646dc4a286c285e0601b51f410192269c`
- **Review Record:** `dev/gis_local/t3-review.json` (0 High / 0 Critical)
- **Runner:** `dev/gis_local/t3_local.py` ประยุกต์ใช้กับทั้ง `postgres` และ `gis_t1_upgrade`
- **การรักษาประวัติเดิม:** ไม่มีการแก้ไข Migration 000–030 หรือ Ledger เดิมแม้แต่ตัวอักษรเดียว

### 2.3 API Models & Target Guard
- **`green-area-backend/gis_schemas.py`:** เพิ่มการรองรับ `SourceManifest` ทั้งแบบ V1 (legacy) และ V2 (scale, offset, unit, nodata, attributes)
- **`dev/gis_local/manage.py`:** เพิ่ม Allowlist ให้รัน Container Image `sha256:fca4560d8a0d0198c0eb75fbf6598314cd8ed4a5e8bafa00e1d7298126aa04c9` ด้วยการตั้งค่าความปลอดภัยสูงสุด (`--network=none`, `--read-only`, `--cap-drop=ALL`, `memory=1g`, `cpus=1`, `user=65534:65534`)

### 2.4 GIS Worker Daemon (`green-area-backend/gis_worker/worker.py`)
- **คลาส:** `GisWorker`
- **ฟังก์ชันหลัก:**
  - `readiness()`: ตรวจสอบความพร้อมของ Worker Identity และ Role สิทธิ์จำกัด
  - `claim()`: ทำ Lease Claim งานสถานะ `queued` ลำดับแรกอย่างปลอดภัยด้วย Advisory Lock
  - `heartbeat()`: ส่งสัญญาณต่ออายุ Lease ขณะประมวลผลผ่าน Background Daemon Thread
  - `complete()`: บันทึก Structured Validation Report และเปลี่ยนสถานะ Job $\rightarrow$ `succeeded`, Edition $\rightarrow$ `validated`
  - `fail()`: บันทึก Structured Error Report, Revert Edition $\rightarrow$ `draft`, ปรับ State $\rightarrow$ `failed` (หรือ `queued` สำหรับ Transient Retry)
  - `recover()`: กวาดและกู้คืนงานที่ Lease หมดอายุ (Lease Stale) กลับสู่ Queue หรือ Mark Failed
  - `_execute_native()`: สั่งประมวลผล Scientific Validation บน Isolated Subprocess ผ่าน Container ใน Linux Environment

---

## 3. Test Evidence & Verification Results

| หมวดการทดสอบ | ไฟล์ / คำสั่งทดสอบ | ผลการทดสอบ |
|---|---|---|
| **Worker Identity Gate** | `dev/gis_worker/t3_identity.py` | **12 Pass / 0 Fail** |
| **Target Guard Policy** | `dev/gis_local/tests` (Unittest) | **40 Pass / 0 Fail** |
| **FastAPI Unit Tests** | `dev/gis_local/t2_checks.py unit` | **75 Pass / 0 Fail** |
| **API Regression Tests** | `dev/gis_local/t2_checks.py regression` | **81 Pass / 0 Fail** |
| **Scientific Validation PoC** | Linux Container Pytest (`test_gis_native_provider.py`) | **35 Pass / 0 Fail** |
| **Full E2E Integration Suite** | `dev/gis_local/t3_integration.py` | **24 Pass / 0 Fail** |
| **รวมทั้งหมด** | | **267 Pass / 0 Fail (100%)** |

### รายละเอียดผลการทดสอบ E2E Integration (`dev/gis_local/t3_integration.py`):
1. `worker_readiness_rpc_succeeds`: Pass
2. `worker_cannot_call_gis_command`: Pass
3. `worker_cannot_call_gis_read`: Pass
4. `worker_cannot_write_gis_datasets`: Pass
5. `officer_creates_dataset_v2`: Pass
6. `officer_creates_edition_v2`: Pass
7. `officer_enqueues_validation_job`: Pass
8. `job_queued_in_db_initially`: Pass
9. `worker_processes_job_successfully`: Pass
10. `job_marked_succeeded_in_db`: Pass
11. `edition_marked_validated_in_db`: Pass
12. `dataset_not_auto_activated_by_worker`: Pass
13. `attempt_has_structured_validation_report`: Pass
14. `api_attempts_endpoint_projects_validation_report`: Pass
15. `worker_processes_unknown_code_job_safely`: Pass
16. `unknown_code_reverts_edition_to_draft`: Pass
17. `unknown_code_marks_job_failed`: Pass
18. `worker_rejects_unsafe_zip_traversal`: Pass
19. `unsafe_zip_marks_job_failed`: Pass
20. `worker_claims_s2_job`: Pass
21. `wrong_lease_token_heartbeat_fenced`: Pass
22. `worker_completes_s2_raster_validation`: Pass
23. `expired_lease_recovered_by_worker`: Pass
24. `recovered_job_returned_to_queued_for_retry`: Pass

---

## 4. Security & Isolation Controls
- **Zero Secrets Disclosure:** ไม่มีการอ่าน แสดงผล หรือบันทึก JWT Secret, Database Password, `.env`, หรือ Service Role Key ลงในโค้ด เอกสาร หรือรายงานทดสอบ
- **Database Boundary:** Worker Identity เชื่อมต่อผ่าน Supabase Auth JWT ที่มีสิทธิ์จำกัดเฉพาะบทบาท `gis_native_worker` โดยห้ามเข้าถึง Tables โดยตรง (RLS Denied) และห้ามเรียกฟังก์ชันดูแลระบบ
- **Subprocess Isolation:** การประมวลผลชุดข้อมูล Synthetic ดำเนินการผ่าน Isolated Linux Container บน Network None, Read-Only Filesystem, Non-Root User (65534), Bounded Memory (1GiB), Swap Limit (1GiB), Single Core CPU (1.0), PIDs Limit (64) และ Wall Timeout 25 วินาที
- **State Machine Fencing:** ระบบป้องกัน Lease Stale ปฏิเสธ Worker ที่ส่ง Lease Token ไม่ถูกต้อง และระบบกู้คืนอัตโนมัติ (Recovery Mechanism) ฟื้นฟู Job ที่หมดเวลาเช่า

---

## 5. Next Steps & Handoff to T4
- **สถานะ:** Task T3 เสร็จสิ้นสมบูรณ์ ยุติการทำงานใน Phase 1 T3 ตามข้อตกลง
- **คำสั่งถัดไป (T4):** พร้อมส่งต่อเพื่อเริ่มงาน **T4 — GIS Management UI** (หน้า Frontend สำหรับการจัดการ Dataset, Edition, Upload/Validation Status และ Catalog Monitoring)
