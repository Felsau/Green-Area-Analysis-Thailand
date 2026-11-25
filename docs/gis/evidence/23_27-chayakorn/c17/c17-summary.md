# C17 · นำไฟล์เส้นเขต 41 จังหวัดเข้าระบบ (migration 053) (สัปดาห์ที่ 4, 23–27 พ.ย. 2569)

จัดทำ 25/11/2569 โดยชยากร · **ทำครบ: แก้โค้ด, ผ่านเทสต์ทุกชุด, probe และ migrate 053 บน T0 ในเครื่อง** · push บรานช์ `23_27-chayakorn-c17` และ tag C17 แล้วเมื่อ 25 พ.ย. ตามที่อนุมัติในแชต · commit แก้ README `d67ce5a` ก็ push แล้ว (`git ls-remote` ได้บรานช์ = `d67ce5a` · commit ที่ยังไม่ push: 0) · ไม่ได้แตะ Supabase จริง
- **รันซ้ำหลัง migrate 053 (25 พ.ย. 21:53–22:04):** ledger 27 migration ถึง 53 ทั้งสองฐาน · T1 85/85 ทั้งสองฐาน · T2 129/0 · native 217 (image ใหม่ build จาก `d67ce5a`)
- เทสต์ใช้ข้อมูลสังเคราะห์ของเทสต์ ส่วนไฟล์เส้นเขตเป็นข้อมูลจริงจาก C7 · ทั้งหมดรันในเครื่อง (local) ไม่มีส่วนไหน deploy

## Commit และ tag (บรานช์ `23_27-chayakorn-c17` จาก 7501cc8)
| | hash | ข้อความ |
|---|---|---|
| commit 1 | `1932d1db7345bd5e4c4240d9c6ab28838b9f1211` | feat(gis): validate uploads against the 41-province LDD boundary asset (migration 053) |
| commit 2 | `515718f89a5ff65a3d70e86b25e7c9ea7940ac22` | chore(gis): record the local T0 approval for migration 053 |
| tag C17 (annotated) | object `357d988e5359b3d5042913bc1846e8509dc10668` → `515718f` | C17: 41-province LDD boundary asset, migration 053, tests and T0 probe/migrate |

- `git show HEAD:green-area-backend/gis_worker/province_boundaries_ldd.json`: SHA256 `49473e7e59aeecfe4b3dff1c9b6ebc21ffe859fa76de47c46c45e1d55dae93a3` · 8,413,889 ไบต์ · ไม่มีตัวขึ้นบรรทัด (ไม่ถูกแปลง)
- migration 053 ใน HEAD: `7db4320ec7b651a0c823d483469771e9af176829b5c5fbb87a713f707a0fe9a3`
- ก่อน push: `git ls-remote origin refs/heads/23_27-chayakorn-c17 refs/tags/C17` ว่าง · หลัง push: บรานช์ = `515718f` · tag C17 = `357d988e…` (→ `515718f`)
- commit 3 `d67ce5a` docs(gis): list upload-053-approval.json in the T0 rebuild README · แก้บรรทัด 16–17 ของ README ให้ครอบถึง `upload-053-approval.json` · tag C17 ไม่ย้าย · push แล้ว (origin/23_27-chayakorn-c17 = `d67ce5a`)
- `c17.diff` ทำใหม่จาก `git diff 7501cc8 d67ce5a` ไม่รวมไฟล์เส้นเขต (10 ไฟล์ · รวมส่วนที่แก้ README ของ commit 3)

## ไฟล์ที่แก้ (11 ไฟล์ · `c17.diff` ไม่รวมไฟล์เส้นเขต)
| ไฟล์ | สิ่งที่ทำ |
|---|---|
| `green-area-backend/gis_worker/province_boundaries_ldd.json` | คัดลอกจาก C7 (41 จังหวัดจากแพ็กเกจ LDD · 36 จังหวัด GADM) |
| `green-area-backend/gis_worker/ldd_provider.py` | `BOUNDARY_LDD_SHA256 = '49473e7e…'` และคอมเมนต์ 2 บรรทัด |
| `green-area-backend/migrations/053_gis_ldd_boundary_asset_v2.sql` (ใหม่) | ตามแบบ 051:<br>· guard version 52 sha `329ce1a5…` · ไม่มี version ≥ 53 · error `GIS_LOCAL_BASELINE_052_REQUIRED`<br>· rename ฟังก์ชันเดิมเป็น `u053_previous_validate_ldd_report`<br>· hash ใหม่ → `1b6cf62b…` แล้วเรียกฟังก์ชันเดิม<br>· REVOKE ชุดเดียวกับ 051 และ `NOTIFY pgrst`<br>· หัวไฟล์อธิบายชุด 41 จังหวัด |
| `dev/gis_local/upload_053_local.py` (ใหม่) | ตามแบบ 052:<br>· proof รับ ledger 52 ตอน probe และ 52/53 ตอน migrate<br>· `APPROVAL = local_apply_053_after_rollback_probe` · ผลลง `upload-053`<br>· ไม่มี `t.admin` เพราะ lifecycle ไม่ใช้ |
| `dev/gis_local/upload_053_lifecycle.sql` (ใหม่) | รายงานที่ใช้ hash ใหม่, hash ชุด 24 จังหวัด และ hash GADM ต้องผ่าน · hash ผิดต้องไม่ผ่าน · กฎอื่นยังทำงาน · queue เก็บ hash ใหม่ไว้ · ฟังก์ชันปิดจากบทบาท API และ worker |
| `dev/gis_local/t0-rebuild/README.md` | ชื่อเรื่องเป็น "ถึง migration 053" · เพิ่มไฟล์ใหม่ในตาราง · หัวข้อ 12 เป็น 048–053 พร้อมคำสั่งและ sha ของ 053 · หัวข้อ 13 เป็น 27 migration |
| `dev/gis_local/t0-rebuild/upload-053-approval.json` (ใหม่ · commit 2) | `{"approval": "local_apply_053_after_rollback_probe", "migration_sha256": "7db4320e…"}` 140 ไบต์ แบบเดียวกับ 052 |
| `green-area-backend/tests/test_ldd_native.py` | OFFICIAL_OUTLINES 41 จังหวัด และ `len == 41`<br>· `data_year_be` รับ 2563 และ 2564 เพิ่ม<br>· เทสต์ 051 ล็อก hash เป็นค่าคงที่<br>· เพิ่มเทสต์ 053 (ชุด hash = {ใหม่, `1b6cf62b…`, sha ของ 052})<br>· ไม่แตะบรรทัด `identical_in_packages == 24` |
| `green-area-backend/tests/test_ldd_policy_native.py` | `GADM_PROVINCE = 'Ranong'` และคอมเมนต์ท้ายบรรทัด แก้บรรทัดนี้บรรทัดเดียว |
| `docs/gis/ldd-field-policy.md` | 24 → 41 และ "other 53" → 36 (บรรทัด 80) |
| `.gitattributes` | เพิ่ม `/green-area-backend/migrations/053_*.sql -text` · คอมเมนต์ของกลุ่มเป็น 047-053 |

## ทำไมเพิ่มบรรทัดใน `.gitattributes`
- เดิม `-text` ครอบถึง `05[0-2]_*.sql` เท่านั้น
- ถ้า clone ใหม่บน Windows ที่ `core.autocrlf=true` จะได้ 053 เป็น CRLF ทำให้ sha ไม่ตรง `7db4320e…` ที่ ledger, README และไฟล์อนุมัติผูกไว้ แบบเดียวกับที่เคยทำให้ T0 หยุดที่ 035
- ตรวจแล้ว: `git check-attr text` ได้ `unset` · ไฟล์ 053 ไม่มี CR · sha ตรง

## ทำไมเปลี่ยน GADM_PROVINCE จากเชียงใหม่เป็นระนอง
- เชียงใหม่ได้เส้น LDD (`ldd-package`) ในไฟล์ C7 แล้ว จึงใช้เป็นจังหวัดที่ยังใช้เส้น GADM ไม่ได้
- **อ่างทองทำให้ล้ม 2 เทสต์:**
  - เทสต์ที่ล้มคือ `test_parcel_accepted_by_the_old_0002_degree_buffer_is_not_newly_rejected` และ `test_v1_rebuild_keeps_the_frozen_legacy_rules_for_existing_editions`
  - สาเหตุ: มุมของแปลง `legacy_edge` ห่างเส้น GADM 0.002007° ซึ่งเกินบัฟเฟอร์ 0.002° ของตัวตรวจเดิม
  - ระยะ 214 ม. ตั้งไว้ให้พอดีกับเชียงใหม่ แต่บัฟเฟอร์ 0.002° กว้างไม่เท่ากันทุกที่ ขึ้นกับละติจูดและทิศของจุดขอบ
- **ผลสำรวจ 18 จังหวัด gadm-approx ในโซน UTM 47:** ผ่านครบ 3 เทสต์ 16 จังหวัด ไม่ผ่าน 2 จังหวัด (อ่างทอง เลย) ดู `c17-gadm-province-survey.py` `.json` `.log`
- **หัวหน้าตรวจซ้ำบนเครื่องหัวหน้า ได้ผลตรงกัน และเลือกระนอง** เพราะเผื่อจากบัฟเฟอร์ราว 7.9 ม. ซึ่งมากที่สุดในกลุ่ม
  - ลพบุรีเผื่อแค่ราว 1.7 ม. และแพ็กเกจเป็น ZIP ซ้อน ถ้าวันหลังเครื่องมือเปิด ZIP ชั้นในได้ ลพบุรีอาจได้เส้น LDD
  - ภาคใต้ทั้ง 14 จังหวัดไม่มีชั้นจังหวัดในแพ็กเกจ

## ผลเทสต์ (เทียบ C6/C1)
| ชุด | C17 | เทียบ | log |
|---|---|---|---|
| backend ทั้งชุด (venv ของ C6 · requirements ตรงกันทุกไบต์) | **2182 passed / 0 failed / 81 skipped** | C6: 2181 / 0 / 81 (เพิ่มขึ้นเป็นเทสต์ 053) | `c17-backend.log` `.xml` |
| native (image `gis-native-runtime:c17` build จาก green-area-c17) | **217 passed** | C1: 217 | `c17-native.log` |
| T0 ใหม่: readiness หัวข้อ 13 (ก่อน 053) | **26 ทั้งสองฐาน** | 26 | `c17-t0-rebuild.log` |
| T1 postgres / gis_t1_upgrade (T0 ใหม่) | **85/85 · 85/85** | C1: 85/85 ทั้งสองฐาน | `c17-t1-*.log` |
| T2 (T0 ใหม่) | **129 Pass / 0 Fail** | C1: 129 | `c17-t2.log` |
| **หลัง migrate 053:** ledger หัวข้อ 13 (READ ONLY) | **27 ถึง 53 ทั้งสองฐาน** · `activation_enabled = false` | ก่อน 053: 26 | `c17-ledger-after-053.log` |
| **หลัง 053:** T1 postgres / gis_t1_upgrade (HEAD `d67ce5a`) | **85/85 · 85/85** | ก่อน 053: 85/85 · 85/85 | `c17-t1-postgres-after-053.log` `c17-t1-gis_t1_upgrade-after-053.log` |
| **หลัง 053:** T2 (HEAD `d67ce5a`) | **129 Pass / 0 Fail** | ก่อน 053: 129 / 0 | `c17-t2-after-053.log` |
| **native ใหม่:** image `gis-native-runtime:c17-d67ce5a` build จาก green-area-c17 ที่ `d67ce5a` (working tree สะอาด) | **217 passed** | `c17` (working tree ก่อน commit 1): 217 | `c17-native-d67ce5a.log` |

- **ขอบเขตของผล T1/T2 หลัง 053:** T1 และ T2 ไม่ได้เรียก `gis.validate_ldd_report`
  - ค้น `validate_ldd_report` ใน `dev/gis_local/tests/t1_cases.py` และ `dev/gis_local/t2_integration.py` ไม่เจอ · `ldd-valid-v1` มีแค่ในบรรทัด 70 ของ T1 (ไม่มีเคสไหนเรียกใช้) · ทุกเคสที่ complete ใช้รายงานของ fixture สังเคราะห์ ndvi/lst/invalid
  - ผลที่ผ่านจึงบอกได้แค่ว่า 053 ไม่ทำให้สิทธิ์และ API เดิมพัง
  - **ตรรกะของ 053** (hash ใหม่ hash ชุด 24 จังหวัด และ hash GADM ผ่าน · hash ผิดไม่ผ่าน · กฎอื่นยังทำงาน · สิทธิ์ของฟังก์ชัน) **ยืนยันได้จาก probe เท่านั้น** (`upload_053_lifecycle.sql` ใน `c17-053-probe-migrate.log`)
- log ชุดหลัง 053 ทุกไฟล์มีบรรทัดแรกเป็น HEAD เวลาที่รัน และ `gis-unlock=7501cc8` · เขียนเป็น UTF-8 ไม่มี BOM
- backend และ native รันที่ working tree ก่อน commit 1 ซึ่งต่างจาก commit 1 แค่ `.gitattributes` (ไม่มีผลกับโค้ดหรือเทสต์)
- **T2 รอบแรกล้ม (บน T0 เดิม 09:43):** `integration_dependency_failed` (AuthApiError)
  - log ของ auth ได้ 403 `bad_jwt` "token is expired" (ดู `c17-t2-auth-log.txt`)
  - สาเหตุคือคีย์ที่ `manage.py prepare` ออกให้มีอายุ 7 วัน (บรรทัด 171–172) และ T0 เดิมสร้างตั้งแต่งาน C1
  - ไม่ได้แก้ `manage.py`
- `c17-readiness.log` เป็นผลบน T0 เดิม (26) ก่อนสร้างใหม่

## สร้าง T0 ใหม่ (อนุมัติในแชต)
1. **สำรองและลบ T0 เดิม** (เลือก "สำรองแบบ C1 แล้วลบ"):
   - ปิด T0 แล้ว tar volume ทั้งสองตัว และ pg_dump ทั้งสองฐาน (pg_restore --list ได้ 1555 และ 1337 รายการ) ลง `<backup-20261125>` (อยู่นอก repo) พร้อม SHA256SUMS ตรวจแล้วตรงครบ
   - แล้วลบ container 4 ตัว volume 2 ตัว และ network 2 ตัว ทีละชื่อ (ไม่ลบ image, runtime dir เดิม หรือ container ของ worker)
   - ดู `c17-old-t0-backup.log`
2. **สร้างใหม่ตาม README ของ t0-rebuild ขั้น 0–13** จาก clone นี้บน `gis-unlock` ที่ 7501cc8 ด้วย runtime dir ใหม่ `<runtime-c17>`
   - ผ่านทุกขั้นในรอบเดียว ไม่ต้อง probe 047 ซ้ำ · ทุก sha ตรงตาม README · readiness ได้ 26 ทั้งสองฐาน
   - ดู `c17-t0-rebuild.log`

## probe และ migrate 053 (วิธีที่หัวหน้าตอบรับ · `c17-053-probe-migrate.log`)
- `git branch -f gis-unlock 1932d1d` แล้ว `git switch gis-unlock` · HEAD = 1932d1d · working tree สะอาด · **ไม่ push**
- ผลแต่ละขั้น:

| ขั้น | ผล |
|---|---|
| proof ก่อน probe | `both_databases_verified: true` · `ledger_source_match: true` · ledger 52 ทั้งสองฐาน |
| probe | sha `7db4320e…` · `{"postgres": "rolled_back_lifecycle", "gis_t1_upgrade": "rolled_back_lifecycle"}` |
| proof หลัง probe | ผ่าน · ledger ยังเป็น 52 ทั้งสองฐาน |
| migrate (ไฟล์อนุมัติ) | `{"postgres": "applied", "gis_t1_upgrade": "applied"}` |
| proof หลัง migrate | ผ่าน · ledger 53 ทั้งสองฐาน (27 migration ถึง 53) |
| readiness หัวข้อ 13 | `n_migrations = 27` ทั้งสองฐาน · `activation_enabled = false` |

- lifecycle sha ตอน probe และตอน migrate เป็นค่าเดียวกัน `c8efc214…` เพราะใช้ checkout เดียวกัน
- **คืนสภาพแล้ว:** `git switch 23_27-chayakorn-c17` (เอาไฟล์อนุมัติติดไปด้วย) แล้ว `git branch -f gis-unlock 7501cc8`
  - `git rev-parse gis-unlock` = `7501cc87…` = `origin/gis-unlock`

## หมายเหตุ
- **ข้ามการลองอัปโหลดบน T0** เพราะใน C4 ไม่มีจังหวัดภาคเหนือที่ผ่านเพดานอัปโหลด
- ไม่ได้แก้ 051 ตามที่หัวหน้ายืนยัน คำอธิบายชุด 41 จังหวัดอยู่ที่หัวไฟล์ 053
- **T0 ใหม่ยังเปิดอยู่ที่ 053** · ส่วน T0 เดิมถูกลบแล้ว แต่มีข้อมูลสำรองอยู่ที่ `<backup-20261125>`

## ยังไม่ได้ตรวจ
- ยังไม่ได้อัปโหลดแพ็กเกจจริงผ่านตัวตรวจบน T0 ที่ 053 จึงยังไม่มีเทสต์ใดเรียก `validate_ldd_report` ของ 053 นอกจาก probe
- ยังไม่ได้รัน backend ทั้งชุดซ้ำที่ `d67ce5a` (commit 3 แก้แค่ README)
- ยังไม่มีคนอื่นตรวจโค้ด

## ไฟล์ใน `docs/gis/evidence/23_27-chayakorn/c17/`
`c17-summary.md` · `c17.diff` · `c17-backend.log` · `c17-backend.xml` · `c17-native.log` · `c17-readiness.log` · `c17-t1-postgres.log` · `c17-t1-gis_t1_upgrade.log` · `c17-t2.log` · `c17-t2-auth-log.txt` · `c17-old-t0-backup.log` · `c17-t0-rebuild.log` · `c17-053-probe-migrate.log` · `c17-ledger-after-053.log` · `c17-t1-postgres-after-053.log` · `c17-t1-gis_t1_upgrade-after-053.log` · `c17-t2-after-053.log` · `c17-native-d67ce5a.log` · `c17-gadm-province-survey.py` · `c17-gadm-province-survey.json` · `c17-gadm-province-survey.log`
