# A6.4d-2 — Cloud Identity & Runtime Preparation Handoff

ผลตรวจ: **PASS — Local Offline Foundation เท่านั้น**
Independent Security/Evidence Review PASS; ไม่มี High/Critical ค้าง
Actual Live GEE, credentials, SDK transport และ selective egress ยัง **NO-GO/BLOCKED**

## ขอบเขต / Git

- Branch `feature/gis-data-management`
- ยืนยัน A6.4d-1 Commit `335bccbbfce1e78458f98c7136a7a239910889de` ก่อนเริ่ม
- งานนี้แยกเป็น Local Commit หนึ่งครั้ง:
  `feat(gis): prepare isolated live GEE worker runtime`
- ไม่เปลี่ยน Branch, ไม่ Push/Merge/PR/Deploy, ไม่เริ่ม Live Smoke/A6.5/A6.6
- ไม่มี SQL Migration ใหม่ ไม่มีการแก้/replay 000–045 หรือ Ledger

## Cloud Readiness

ไม่พบ Cloud Console tab ที่เข้าถึงได้ใน browser inventory ปัจจุบัน
ไม่ได้เริ่ม Login/OAuth หรือเปิด Console/เรียก Google API ใหม่

| รายการ | สถานะ |
| --- | --- |
| Sandbox Project ID/Number และการแยก Legacy | NOT VERIFIED |
| GEE Registration/Verification/API/Tier | NOT VERIFIED |
| Billing linkage, cost exposure, Quota/Usage | NOT VERIFIED |
| Google Worker Principal/effective IAM | NOT VERIFIED |
| Credential delivery/renewal และ Google endpoint policy | BLOCKED |

ไม่อนุมานจากชื่อ Project, Environment หรือบทสนทนาเก่า ไม่มี approved real
Project/Principal ในโค้ด และไม่ได้ตรวจ/ขอ/สร้าง Google credentials

## สิ่งที่พัฒนา

- `gee_runtime_identity.py`: Trusted GIS JWT subject แยกจาก Google identity;
  binding ครบ job/attempt/session/project/principal/input/method/V2 geometry/
  request/fencing digest; Fake lease ผูก issuer/object identity, expiry,
  revocation และ renewal; real channel และ real allowlist ปิดเสมอ
- `gee_runtime_transport.py`: server-side injected plan ตรวจ credential ก่อน
  reserve และก่อน/หลัง evaluation; reuse AccountedTransport/SQL045 ทุก entry
- `gee_runtime_probe.py`: default/unknown command ปิดก่อนอ่าน stdin;
  one-shot Linux probe เท่านั้น ไม่มี Live daemon, credentials หรือ SDK init
- `gee_runtime_policy.py` / `gee_runtime_local.py`: exact image/command/labels/
  environment/resource/no-mount policy แยกจาก Native/Mock guard เดิม
- Dockerfile, image lock และ review metadata; focused tests/Local SQL harness
- `.gitattributes` เพิ่มเฉพาะ exact-byte rules ของไฟล์ใหม่ ไม่แก้กติกาเดิม
- API/UI/legacy methods และ production configuration เดิมไม่เปลี่ยน

## Image / Isolation ที่พิสูจน์จริง

Approved **offline probe image only**:
`sha256:9e4cea21aa365fe4b648221d1617769a788d623910b134f83c7cd2436721df16`

Source tree:
`96d294abee7b0c559333c2f56a236c7647b5cdfc3dc294210f37d43ffaaad7ca`

ใช้ base เดิม `sha256:7557955c9e2c8611ea1396ddef6d8629c2ee1e7f193e85f0c65bcf5db9566674`
Build classic/COPY-only, `--pull=false --network=none`; ไม่ RUN/install/download
Source 38 ไฟล์/context/Dockerfile/manifest ตรงกับที่ review
ไม่เชื่อ labels ของ tag ที่มีอยู่ และไม่ overwrite tag เดิม

Probe ใช้ non-root65534, readonly root, network none, ไม่มี mounts,
CPU1, memory/swap1GiB, PIDs64, FD64, core0, file-size16384,
stdout16384, wall time30s, log none, cap-drop ALL, no-new-privileges,
tmpfs64MiB noexec/nosuid; ตรวจ policy ก่อนและหลังรัน แล้วลบเฉพาะ probe ของงานนี้

Kernel ปฏิเสธ reserved test IPv4/IPv6 และ external DNS datagram จริง
อ่าน local-only302 แล้วปฏิเสธ redirect โดยไม่ตามออกภายนอก จากนั้นเปิด Python
network/import guards สำหรับ injected compute; ปิด Pydantic plugin discovery
ก่อน project imports ไม่มี Google call และ SDK ใน image ไม่มี (`null`)

**Network none พิสูจน์ deny-all เท่านั้น** ยังไม่พิสูจน์ selective Google
egress, DNS/TLS/redirect allowlist หรือ Queue/Auth จาก image ใหม่
การเชื่อม Queue/Auth ใน tests ใช้ guarded Local parent แยกต่างหาก
Original Native/Mock/Offline image/network policies และ internal network ไม่เปลี่ยน

## Budget / Scientific Evidence

4 logical jobs,32 reservations,2 total attempts, concurrency1,
120s request/180s logical job/20min session ยังคงเป็น authority ของ SQL045
Fake credential reset/renew/provider restart ไม่คืน request budget
New attempts ต้องมี binding/lease ใหม่ และ stale SQL fencing ถูกปฏิเสธ

แต่ละ compute/sdk_retry/reference entry ที่สำเร็จเป็น **full injected
observation** แยก reservation ไม่ใช่ actual HTTP response หรือ auxiliary
reference-response accounting หาก entry ล้มเหลว/uncertain จะ abort และเก็บยอด
ไว้ ไม่ซ่อนด้วย success ถัดไปใน attempt เดิม Candidate ยัง injected/draft/
non-publishable และไม่มี cache/publication/activation mutation

## Tests / Independent Review

| ชุด | ผลจริงล่าสุด |
| --- | --- |
| Focused Windows units + original runtime guard regressions | 285 PASS + 24 subtests,12 Linux-only SKIP |
| Focused Linux Python3.11 | 139 PASS |
| Exact derived-image one-shot probe | PASS; container cleanup verified |
| Actual Local Auth/SQL with fake credentials/observations | 19 PASS |
| Read-only preservation | 26 PASS |
| Independent source/image/final evidence review | PASS; High/Critical0 |

มี actual60s lease expiry/replacement, uncertain durable charges,
separate compute/retry/reference reservations, fake issuer/context/revocation,
duplicate completion, stale fencing และ SQL stop tests
ไม่มี actual Live worker kill/restart หรือ authenticated Google transport
ผลทดสอบต่าง platform มี overlap จึงไม่รวมเป็นจำนวนเคสไม่ซ้ำกัน

Review พบและแก้ก่อน build: ใช้ V2 geometry canonicalization, ไม่เชื่อ existing
image tag จาก label อย่างเดียว และปิด Pydantic plugins ก่อน early imports
ไม่มีการแก้ SQL ตามหลัง ไม่มี High/Critical ค้าง

## Preservation / Artifacts

เทียบ original files640รายการ: unchanged ทุกไฟล์ยกเว้น `.gitattributes`
ที่ append rules ใหม่โดยคง rules เดิมครบ Migration000–045 byte-for-byte
และ Ledger rows/timestamps ทั้งสองฐานไม่เปลี่ยน ไม่มี DDL/reapply
Old GIS rows/history/artifacts/active pointers และ original profiles คงเดิม
Public legacy/cache/saved tables เทียบ hashes รวมฐานที่ cache ไม่ว่าง:
primary NDVI3/LST3/SavedAreas3, upgrade NDVI1/districtNDVI1/LST1
Broad activation gate false และ queue idle หลังทดสอบ

เก็บ core containers/volumes และ original Native/Mock images เดิม
เหลือ derived offline image สำหรับตรวจต่อ; probe container ถูกนำออกแล้ว
ห้า original untracked evidence files คงเดิมและไม่ Commit
Raw runtime evidence/context/build logs อยู่ภายนอก Repository

หลักฐานใต้ `C:\Users\chaya\.codex\visualizations\2026\10\04\01a107d9-ff44-7731-8bc3-91814ffd8d51\`:

- `a6-4d2-runtime/`: focused-8f3c0c0c XML/result/source/log, Linux result/log,
  before/source-before, preservation-final, resources-final
- `t0-local-supabase-20261027-v2/a6-4d2-runtime/`: build-result/log/context,
  probe-result, checks-a17e49fb0a09 JSON/source

## Remaining Blockers / Next Action

Actual Cloud identity/isolation/registration/IAM/billing/quotas ยัง NOT VERIFIED
Real credential delivery/renewal, SDK preparation/interception/physical retries,
selective egress และ trusted genuine-Live SQL acceptance ยัง BLOCKED
ไม่ได้ทดสอบ actual satellite parity, remote cancellation หรือ hard EECU cap
ไม่รัน full UI/browser หรือ unrelated historical suites เพราะ source เดิมไม่เปลี่ยน

ขั้นถัดไปเสนอให้ตรวจ Cloud Console metadata แบบ read-only เมื่อมี session
ที่เข้าถึงได้ แล้วอนุมัติแยกเรื่อง SDK/credential delivery/selective egress/
trusted transport protocol ก่อนพิจารณา Live Smoke Test ไม่ดำเนินการอัตโนมัติ
