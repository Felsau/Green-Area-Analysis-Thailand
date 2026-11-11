# สร้าง sandbox T0 ใหม่ตั้งแต่ศูนย์จนถึง migration 052

ลำดับคำสั่งนี้คัดจากการสร้าง T0 จริงเมื่อ 10–11 พ.ย. 2569 (งาน W4) บนเครื่อง Windows
ผลที่ควรเห็นทุกขั้นคัดจาก log ของรอบนั้น ค่า `runtime_instance`, id ของ container และ id ของรายงานจะต่างกันทุกเครื่อง
ส่วนค่า sha ของ migration ต้องตรงตามนี้ ถ้าไม่ตรงแปลว่าไฟล์ในเครื่องไม่ตรงกับบรานช์

ไฟล์ในโฟลเดอร์นี้:

| ไฟล์ | ใช้ที่ขั้น |
|---|---|
| `seed_runtime.py` | 3 เขียน frozen state และคัดลอกไฟล์ด้านล่างเข้า runtime |
| `phase2-evidence-index.json`, `phase3-evidence-index.json`, `review-036.json`, `a4-geotiff-prepare-before.json`, `a4-2-geotiff-publication-before.json` | 3 (seed คัดลอกให้) |
| `t3-identity-independent-review.json` | 5 |
| `migration-032-independent-review.json`, `migration-033-independent-review.json`, `run_032_033.py` | 6 |
| `review-034.json`, `review-035.json` | 7 |
| `gee-dashboard-048-approval.json`, `upload-049-approval.json` … `upload-052-approval.json` | 12 |

## คำเตือน
- **runtime dir มีค่าลับของเครื่อง** (`manage.py prepare` สร้างเอง) ต้องอยู่นอก repo ห้าม commit ห้ามแนบ และห้ามถ่ายภาพเนื้อหา
- README นี้**ไม่ครอบคลุมการสำรองหรือลบ T0 เดิม** ถ้ามี T0 เดิมอยู่ ต้องจัดการเองก่อน
- ไฟล์อนุมัติ 048–052 ผูกกับ sha ของ migration ถ้า migration เปลี่ยน **ห้ามแก้ sha ในไฟล์เอง** ต้อง probe ใหม่และออกไฟล์อนุมัติใหม่
- ทุกคำสั่งรันจาก root ของ repo ใน PowerShell

## 0. สิ่งที่ต้องมีก่อนเริ่ม
- Docker Desktop ทำงานอยู่ และ**ยังไม่มี** container หรือ volume ชื่อ `green-area-gis-t0-*`
  ```powershell
  docker ps -a --filter name=green-area-gis-t0      # ต้องว่าง
  docker volume ls --filter name=green-area-gis-t0  # ต้องว่าง
  ```
- อยู่บนบรานช์ชื่อ **`gis-unlock`** ตรงตัว ตัวรันเทียบชื่อบรานช์กับ `GIS_BRANCH` ใน `dev/gis_worker/remediation_local.py` ถ้าเป็น detached HEAD หรือบรานช์ชื่ออื่นจะหยุดด้วย `WRONG_BRANCH`
  ```powershell
  git fetch origin
  git switch gis-unlock          # ถ้ายังไม่มีบรานช์ในเครื่อง git จะสร้างจาก origin/gis-unlock ให้
  git pull --ff-only
  git branch --show-current      # ต้องได้ gis-unlock
  ```
- migration 000–052 บนดิสก์ต้องเป็น LF ทุกไฟล์ `.gitattributes` ตั้ง `-text` ให้ครบแล้ว clone ใหม่จึงได้ LF เองทุกระบบ แต่ clone เดิมบน Windows ที่ `core.autocrlf=true` อาจยังมีไฟล์ CRLF ค้างอยู่ ให้ตรวจและ checkout ใหม่
  ```powershell
  git ls-files --eol green-area-backend/migrations | Select-String 'w/crlf'   # ต้องไม่มีผลลัพธ์
  # ถ้ามี: ลบไฟล์ที่ขึ้นมาแล้ว checkout ใหม่
  Remove-Item green-area-backend\migrations\*.sql
  git checkout -- green-area-backend/migrations
  ```
- image ฐาน `gis-linux-poc:20261026` ที่ id ตรงกับค่าที่ปักไว้ใน `dev/gis_local/manage.py` (`WORKER_IMAGE`) ขั้น 8 (038–042) รัน container จาก id นี้ และ `manage.py` ไม่ดึง image นี้ให้ image นี้ไม่ได้อยู่ใน git และสร้างซ้ำจาก `dev/gis_local/gis_linux_poc.Dockerfile` ไม่ได้ เพราะจะได้ digest คนละค่า ให้ขอไฟล์ `gis-linux-poc_20261026.tar` (137,613,312 ไบต์) จากหัวหน้ากลุ่ม แล้วตรวจและโหลด
  ```powershell
  (Get-FileHash <path>\gis-linux-poc_20261026.tar -Algorithm SHA256).Hash
  # ต้องได้ BD0C4B65472A06835142A2B0521BFD89DDD01CF91E3E0F41324192BC09496C40
  docker load -i <path>\gis-linux-poc_20261026.tar
  docker image inspect sha256:fca4560d8a0d0198c0eb75fbf6598314cd8ed4a5e8bafa00e1d7298126aa04c9 --format '{{.Id}}'
  ```
- Python 3.11 และ `green-area-backend\.venv` ที่ติดตั้ง dependency ของ backend แล้ว ถ้ายังไม่มี
  ```powershell
  py -3.11 -m venv green-area-backend\.venv
  green-area-backend\.venv\Scripts\python.exe -m pip install -r green-area-backend\requirements.txt
  ```
- port 55421 ของเครื่องว่าง (`manage.py` ผูก port นี้ไว้) และมี `git` กับ `docker compose` อยู่ใน PATH
- เครื่องต่ออินเทอร์เน็ตได้ตอน `prepare` (ดาวน์โหลดสคริปต์ bootstrap ที่ hash ล็อกไว้)
- ตั้งตัวแปร (เลือก path ของ runtime dir เอง ต้องเป็นโฟลเดอร์ที่ยังไม่มี และอยู่นอก repo):
  ```powershell
  $rt = '<โฟลเดอร์ runtime ใหม่ นอก repo>'
  $py = 'green-area-backend\.venv\Scripts\python.exe'   # ทุกคำสั่งเรียกเป็น & $py -I -B ...
  ```

## 1. สร้าง T0
```powershell
& $py -I -B dev\gis_local\manage.py prepare --runtime-dir $rt
& $py -I -B dev\gis_local\manage.py start --runtime-dir $rt
docker ps -a --filter name=green-area-gis-t0 --format '{{.Names}} | {{.Status}}'
```
ผลที่ควรเห็น:
- `prepare`: `"prepared": true`, `"credentials_printed": false`
- `start`: `"ready": true`, `"GIS_ENABLED": false`, บริการ `db` `auth` `rest` `gateway` เป็น `"health": "healthy"`, `"postgres": {"cluster": "green-area-gis-t0", "gis_schema": false, "auth_users": 0}`
- container 4 ตัว `green-area-gis-t0-db`, `-gateway`, `-auth`, `-rest` เป็น `(healthy)`

## 2. baseline 000–026 ทั้งสองฐาน
ลำดับตาม log: `clone-empty` ก่อน แล้ว `baseline` ของ `postgres` และ `gis_t1_upgrade`
```powershell
& $py -I -B dev\gis_local\t1_database.py clone-empty --runtime-dir $rt
& $py -I -B dev\gis_local\t1_database.py baseline --runtime-dir $rt --database postgres
& $py -I -B dev\gis_local\t1_database.py baseline --runtime-dir $rt --database gis_t1_upgrade
```
ผลที่ควรเห็น: JSON ที่มี `"cluster": "green-area-gis-t0"`, `"gis": false`, `"auth_users": 0` และ `"database"` ตรงกับขั้น · `clone-empty` คืน `"database": "gis_t1_upgrade"` · `baseline` คืน `"legacy_functions": true`, `"application_tables": 16`

## 3. seed runtime
```powershell
& $py -I -B dev\gis_local\t0-rebuild\seed_runtime.py --runtime-dir $rt
```
ผลที่ควรเห็น: JSON 6 รายการ (path ใต้ runtime: sha) คือ `t3-remediation/initial-source-state.json`, `phase2/evidence-index.json`, `phase3/evidence-index.json`, `phase4/review-036.json`, `a4-geotiff-prepare/before.json`, `a4-2-geotiff-publication/before.json`
- ค่า sha ของ `initial-source-state.json` ต่างกันทุกเครื่อง (บันทึก HEAD ปัจจุบัน) ค่าอื่นเท่ากับ sha ของไฟล์ในโฟลเดอร์นี้
- seed ไม่ยอมเขียนทับไฟล์ที่มีอยู่ (`REFUSING_TO_OVERWRITE`) และไม่ทำงานถ้าบรานช์ไม่ใช่ `GIS_BRANCH` (`WRONG_BRANCH`)

## 4. 027–030
```powershell
& $py -I -B dev\gis_local\t1_database.py migrate --runtime-dir $rt --database postgres --review dev\gis_local\t1-review.json
& $py -I -B dev\gis_local\t1_database.py migrate --runtime-dir $rt --database gis_t1_upgrade --review dev\gis_local\t1-review.json
& $py -I -B dev\gis_local\t2_local.py migrate --runtime-dir $rt --review dev\gis_local\t2-review.json
```
ผลที่ควรเห็น:
- 027–029 (แต่ละฐาน): JSON ขึ้นต้นด้วย `{"proof": {"gis": true, ... "cluster": "green-area-gis-t0", ...`
- 030: `{"version": 30, "sha256": "6e7cc972d648fe717539c63131f752440c79446a5ffcbe8608b232cd63a4914f", "databases": ["postgres", "gis_t1_upgrade"], "local_only": true}`

## 5. T3 identity แล้ว 031
031 grant ให้ role `gis_native_worker` ซึ่งสร้างโดย `dev/gis_worker/identity_probe.sql` ผ่าน `t3_identity.py` **ต้องรันก่อน 031** ไม่อย่างนั้น 031 จะล้มด้วย `role "gis_native_worker" does not exist` (เกิดจริงในรอบ W4)
```powershell
& $py -I -B dev\gis_worker\t3_identity.py --runtime-dir $rt --review dev\gis_local\t0-rebuild\t3-identity-independent-review.json
& $py -I -B dev\gis_local\t3_local.py migrate --runtime-dir $rt --review dev\gis_local\t3-review.json
```
ผลที่ควรเห็น:
- `t3_identity`: 12 บรรทัด `"status": "Pass"` แล้ว `{"counts": {"Pass": 12, "Fail": 0}, "report": "identity-proof.json"}`
- 031: `{"version": 31, "sha256": "7ff49cf8cd2658c8c1ba0c5d015faf26306e310f30a129dd962994bb6d243b86", "databases": ["postgres", "gis_t1_upgrade"], "local_only": true}`

## 6. 032 และ 033
ตัวรันของ 032/033 ไม่มีคำสั่ง CLI จึงเรียกเมธอด `migrate` ผ่าน `run_032_033.py` (ไม่แก้ตรรกะของตัวรัน)
```powershell
& $py -I -B dev\gis_local\t0-rebuild\run_032_033.py $PWD $rt 32
& $py -I -B dev\gis_local\t0-rebuild\run_032_033.py $PWD $rt 33
```
ผลที่ควรเห็น:
- 032: `{"version": 32, "record": {"sha256": "ef58eb7d864c0433f4393b0f52dbb6db00a91e8d3dd397742594d1d909660b7f", "databases": ["postgres", "gis_t1_upgrade"], ... "forward_only": true}}`
- 033: `{"version": 33, "record": {"sha256": "034d6be5c329ec4d2259bb57482f06582fc2dc3c4aa8ea3e14be84fbb8996e5d", ... "forward_only": true}}`

## 7. 034–036
```powershell
& $py -I -B dev\gis_ui\phase2_local.py migrate --runtime-dir $rt --review dev\gis_local\t0-rebuild\review-034.json
& $py -I -B dev\gis_ui\phase3_local.py migrate --runtime-dir $rt --review dev\gis_local\t0-rebuild\review-035.json
& $py -I -B dev\gis_ui\phase4_local.py migrate --runtime-dir $rt --review dev\gis_local\t0-rebuild\review-036.json
```
ผลที่ควรเห็น: `{"migration": 34, "local_only": true}`, `{"migration": 35, ...}`, `{"migration": 36, ...}`

## 8. 037–042
```powershell
& $py -I -B dev\gis_local\publication_local.py migrate --runtime-dir $rt --review dev\gis_local\publication-review.json
& $py -I -B dev\gis_local\ldd_prepare_local.py migrate --runtime-dir $rt --review dev\gis_local\ldd-prepare-review.json
& $py -I -B dev\gis_local\ldd_publication_local.py migrate --runtime-dir $rt --version 39 --review dev\gis_local\ldd-publication-review.json
& $py -I -B dev\gis_local\ldd_publication_local.py migrate --runtime-dir $rt --version 40 --review dev\gis_local\ldd-publication-fix-review.json
& $py -I -B dev\gis_local\geotiff_prepare_local.py migrate --runtime-dir $rt --review dev\gis_local\geotiff-prepare-review.json
& $py -I -B dev\gis_local\geotiff_publication_local.py migrate --runtime-dir $rt --review dev\gis_local\geotiff-publication-review.json
```
ผลที่ควรเห็น (`"databases": {"postgres": "apply", "gis_t1_upgrade": "apply"}` ทุกขั้น):

| migration | sha256 |
|---|---|
| 037 | `bacd6937efb07d54fb37bef3d2be83a07c2ebff43ff97879d5220096532fcde6` |
| 038 | `95709b43f9a51001987dc687f98db868ac6f702aac375696d2d51fc8aa2c421d` |
| 039 | `287c1259ac685645a8a43275ee0a9fbdb6ca5cf5483aeeb8eaf8f650adeeff59` (`"broad_gate_closed": true`) |
| 040 | `b93d65306e112763cd24019a0abf225a1e02698ba9a3f9ae2da13f33392b083e` (`"broad_gate_closed": true`) |
| 041 | `57dc2baee7cf205f76167aacfffd0c9f9db55c63588c2fde280e4482975bfd95` |
| 042 | `a03b3271eb24624b8b033e205d5ce2a30ccd050a66ea4a638fa917822bb1b378` |

041 และ 042 อ่าน `before.json` ที่ขั้น 3 คัดลอกไว้

## 9. 043 (probe แล้ว migrate)
```powershell
& $py -I -B dev\gis_local\gee_mock_local.py probe --runtime-dir $rt --review dev\gis_local\gee-mock-review.json
& $py -I -B dev\gis_local\gee_mock_local.py migrate --runtime-dir $rt --review dev\gis_local\gee-mock-review.json
```
ผลที่ควรเห็น: sha `08c516b3098f202d3a9f673771a452113914f65ed455c03a57e24c2c89550f2a` · probe `"rolled_back_probe"` ทั้งสองฐาน · migrate `"applied"` ทั้งสองฐาน

## 10. สร้าง officer สังเคราะห์ก่อน 044
probe ของ 044 ต้องมีแถวใน `gis.officers` ทุกฐาน (`gee_live_local.py` ล้มด้วย `LOCAL_SYNTHETIC_OFFICER_REQUIRED` ถ้าไม่มี) ชุดทดสอบ `t1_cases.py` สร้าง officer สังเคราะห์ที่ commit ค้างไว้ฐานละ 1 คน
```powershell
& $py -I -B dev\gis_local\tests\t1_cases.py --runtime-dir $rt --database postgres
& $py -I -B dev\gis_local\tests\t1_cases.py --runtime-dir $rt --database gis_t1_upgrade
```
ผลที่ควรเห็น (log รอบ W4): ทั้งสองฐาน `{"counts": {"Pass": 78, "Fail": 5}, ...}` และ exit code 1
- 5 ข้อที่ล้มเป็นเทสต์ activation ที่ได้ `GIS_PUBLICATION_NOT_READY` (เทสต์ชุดนี้เขียนก่อน 037) **ไม่ต้องหยุด** สิ่งที่ต้องการจากขั้นนี้คือ officer
- ข้อ `committed_concurrent_job_completion` ต้องเป็น `Pass` (ข้อนี้สร้าง officer ที่ค้างไว้)
- ถ้าหัวหน้าแก้ `t1_cases.py` แล้ว ตัวเลขอาจเปลี่ยน ให้ยึดตามฉบับที่อยู่บนบรานช์

## 11. 044–047 (probe แล้ว migrate ทีละตัว)
```powershell
& $py -I -B dev\gis_local\gee_live_local.py probe --runtime-dir $rt --review dev\gis_local\gee-live-review.json
& $py -I -B dev\gis_local\gee_live_local.py migrate --runtime-dir $rt --review dev\gis_local\gee-live-review.json
& $py -I -B dev\gis_local\gee_safety_local.py probe --runtime-dir $rt --review dev\gis_local\gee-safety-review.json
& $py -I -B dev\gis_local\gee_safety_local.py migrate --runtime-dir $rt --review dev\gis_local\gee-safety-review.json
& $py -I -B dev\gis_local\gee_transport_local.py probe --runtime-dir $rt --review dev\gis_local\gee-transport-review.json
& $py -I -B dev\gis_local\gee_transport_local.py migrate --runtime-dir $rt --review dev\gis_local\gee-transport-review.json
& $py -I -B dev\gis_local\gee_genuine_local.py probe --runtime-dir $rt --review dev\gis_local\gee-genuine-review.json
& $py -I -B dev\gis_local\gee_genuine_local.py migrate --runtime-dir $rt --review dev\gis_local\gee-genuine-review.json
```
ผลที่ควรเห็น:

| migration | sha256 | probe | migrate |
|---|---|---|---|
| 044 | `53e3fc5359ea99a84f22d05714f9972a2e15d62b96bcf4b339d39ea9533b3f17` | `rolled_back_full_lifecycle` | `applied` |
| 045 | `a7ae1f4cfd99f4bd0d728b3ca290fb4a2734d05f585c3a192c9611a0b317b395` | `rolled_back_full_lifecycle` | `applied` |
| 046 | `1efa5e50247afbaf4fbf7d51a1ba3e4ee98921f8aa600de8d337c17b3bfbb4b0` | `rolled_back_lifecycle` | `applied` |
| 047 | `4d8af35d59bc90f81de4bd835a74ec6e957e7803ab6c6cdee268d67a63ff15f8` | `rolled_back_lifecycle` | `applied` |

**047 probe ล้มแบบสุ่มได้:** `ERROR: 23514: new row for relation "gee_https_runtimes" violates check constraint "gee_https_runtimes_check"`
- สาเหตุคือข้อมูลทดสอบใน `gee_genuine_checks.py` แข่งกับนาฬิการะดับ µs ไม่ใช่ schema เสีย probe ทำงานใน transaction ที่ rollback จึงไม่มีอะไรค้าง
- ให้**รัน probe ซ้ำ 1 ครั้ง** (รอบ W4 ผ่านในรอบที่ 2) แล้วจึง migrate ถ้ายังล้มให้หยุดและรายงาน

## 12. 048–052 (probe แล้ว migrate ด้วยไฟล์อนุมัติ)
```powershell
& $py -I -B dev\gis_local\gee_dashboard_local.py probe --runtime-dir $rt
& $py -I -B dev\gis_local\gee_dashboard_local.py migrate --runtime-dir $rt --approval dev\gis_local\t0-rebuild\gee-dashboard-048-approval.json
& $py -I -B dev\gis_local\upload_049_local.py probe --runtime-dir $rt
& $py -I -B dev\gis_local\upload_049_local.py migrate --runtime-dir $rt --approval dev\gis_local\t0-rebuild\upload-049-approval.json
& $py -I -B dev\gis_local\upload_050_local.py probe --runtime-dir $rt
& $py -I -B dev\gis_local\upload_050_local.py migrate --runtime-dir $rt --approval dev\gis_local\t0-rebuild\upload-050-approval.json
& $py -I -B dev\gis_local\upload_051_local.py probe --runtime-dir $rt
& $py -I -B dev\gis_local\upload_051_local.py migrate --runtime-dir $rt --approval dev\gis_local\t0-rebuild\upload-051-approval.json
& $py -I -B dev\gis_local\upload_052_local.py probe --runtime-dir $rt
& $py -I -B dev\gis_local\upload_052_local.py migrate --runtime-dir $rt --approval dev\gis_local\t0-rebuild\upload-052-approval.json
```
- probe ต้องมีผู้ใช้สังเคราะห์ (officer, profile ที่ไม่ใช่ officer, admin) และจังหวัดในทั้งสองฐาน ผู้ใช้สังเคราะห์มาจากขั้น 10 ส่วนจังหวัดมาจาก seed ของ migration 006 ตอน baseline ในขั้น 2
- ไฟล์อนุมัติมีแค่ `{"approval": "local_apply_0xx_after_rollback_probe", "migration_sha256": "<sha ของไฟล์ migration>"}` ตัวรันเทียบแบบตรงตัว

ผลที่ควรเห็น (probe `rolled_back_lifecycle` ทั้งสองฐาน · migrate `applied` ทั้งสองฐาน):

| migration | sha256 |
|---|---|
| 048 | `44d44e3e60fb307e1ccf95b9eee8239fb1b1547ff121c180107f78bc96c844d5` |
| 049 | `f3cb090958ce86be8d0f05628b4a58f5aa5cf236d900d89ed409eb2dbebc31bb` |
| 050 | `87a09b59ddeae481a0f927ebde641fa915260837bc82729fd8effcb026bac893` |
| 051 | `875cd02e5f5bb40f1fd7828c84335b856f097f65e3e496fde087f60c7c32cccc` |
| 052 | `329ce1a52a47db9735a8fca99488e00f0881c0403a4878268f07c77f6f229875` |

## 13. ตรวจ readiness แบบ READ ONLY ทั้งสองฐาน
```powershell
$sql = "BEGIN READ ONLY; SET LOCAL ROLE service_role; SELECT r->>'database_name' AS db, r->>'cluster_name' AS cluster_name, r->>'mode' AS mode, r->>'activation_enabled' AS activation_enabled, jsonb_array_length(r->'migration_versions') AS n_migrations FROM public.gis_readiness() r; ROLLBACK;"
$ver = "BEGIN READ ONLY; SELECT 'installed migrations (' || count(*) || '): ' || string_agg(version::text, ',' ORDER BY version) FROM gis.schema_migrations; ROLLBACK;"
foreach ($db in 'postgres', 'gis_t1_upgrade') {
    docker exec green-area-gis-t0-db psql -X -q -P pager=off -U postgres -d $db -c $sql
    docker exec green-area-gis-t0-db psql -X -qAt -U postgres -d $db -c $ver
}
```
ผลที่ควรเห็น (ทั้งสองฐาน):
- `cluster_name = green-area-gis-t0` · `mode = local_synthetic` · `activation_enabled = false` · `n_migrations = 26`
- `installed migrations (26): 27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52`

## ข้อจำกัดที่ทราบ
- **แก้แล้ว (11 พ.ย. 2569): migration 000–026 ต้องเป็น LF** เดิมค่า sha ของ migration 000–026 ทั้ง 27 ค่าที่ปักไว้เป็นค่าของไฟล์แบบ CRLF ทำให้เครื่องที่ checkout เป็น LF หยุดที่ 035 (`check_frozen` ใน `dev/gis_ui/phase3_local.py` เทียบกับ `phase2-evidence-index.json`) และจะหยุดซ้ำที่ 041 และ 042 (`geotiff_prepare_local.py` และ `geotiff_publication_local.py` เทียบกับ `before.json`) ตอนนี้ `.gitattributes` ตั้ง `-text` ให้ 000–026 แล้ว และค่า 27 ค่าในไฟล์ทั้งสี่ (`phase2-evidence-index.json`, `phase3-evidence-index.json`, `a4-geotiff-prepare-before.json`, `a4-2-geotiff-publication-before.json`) เปลี่ยนเป็นค่า LF แล้ว clone ที่ยังมีไฟล์ CRLF ค้างอยู่ให้ทำตามขั้น 0
- `gee_mock_checks.py` รับเฉพาะ ledger ถึง 042 หรือ 043 จึงใช้ตรวจ T0 ที่ 052 ไม่ได้
