# C1 ชุด 1 backend: รายการเทสต์ที่ล้มและที่ skip ต่าง

จัดทำจาก `c1-backend.xml` และบรรทัด SKIPPED จาก output `pytest -rs` ของรอบเดียวกัน (clone ใหม่บนเครื่องที่ 2, `gis-unlock` @ 5402805, Python 3.11.9) · อ่านอย่างเดียว ไม่ได้รันเทสต์ใหม่

junit: tests=2262 failures=47 errors=0 skipped=81 · baseline หัวหน้า: 2180 passed, 0 failed, 82 skipped

## 1. เทสต์ที่ล้มทั้งหมด: 47 ข้อ

### `green-area-backend/tests/test_gee_mock_daemon.py` (12 ข้อ)
| # | เทสต์ | รหัส error / ข้อความบรรทัดแรก |
|---|---|---|
| 1 | `test_all_trusted_mock_case_outputs_use_same_adapter_as_worker[ndvi-annual]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 2 | `test_all_trusted_mock_case_outputs_use_same_adapter_as_worker[ndvi-monthly]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 3 | `test_all_trusted_mock_case_outputs_use_same_adapter_as_worker[lst-annual]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 4 | `test_all_trusted_mock_case_outputs_use_same_adapter_as_worker[lst-monthly]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 5 | `test_all_trusted_mock_case_outputs_use_same_adapter_as_worker[no-data]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 6 | `test_all_trusted_mock_case_outputs_use_same_adapter_as_worker[all-masked]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 7 | `test_all_trusted_mock_case_outputs_use_same_adapter_as_worker[partial]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 8 | `test_all_trusted_mock_case_outputs_use_same_adapter_as_worker[retry-once]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 9 | `test_all_trusted_mock_case_outputs_use_same_adapter_as_worker[retry-exhausted]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 10 | `test_all_trusted_mock_case_outputs_use_same_adapter_as_worker[long-running]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 11 | `test_retry_behavior_is_fixed_by_fixture_not_api_delay_or_command` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 12 | `test_unapproved_scope_and_geometry_are_rejected` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |

### `green-area-backend/tests/test_processing_provider.py` (32 ข้อ)
| # | เทสต์ | รหัส error / ข้อความบรรทัดแรก |
|---|---|---|
| 1 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[0-ndvi]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 2 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[0-lst]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 3 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[1-ndvi]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 4 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[1-lst]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 5 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[2-ndvi]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 6 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[2-lst]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 7 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[3-ndvi]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 8 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[3-lst]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 9 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[4-ndvi]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 10 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[4-lst]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 11 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[5-ndvi]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 12 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[5-lst]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 13 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[6-ndvi]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 14 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[6-lst]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 15 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[7-ndvi]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 16 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[7-lst]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 17 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[8-ndvi]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 18 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[8-lst]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 19 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[9-ndvi]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 20 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[9-lst]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 21 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[10-ndvi]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 22 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[10-lst]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 23 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[11-ndvi]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 24 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[11-lst]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 25 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[12-ndvi]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 26 | `test_actual_numeric_scene_medians_and_legacy_scale_expected_results[12-lst]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 27 | `test_all_masked_no_data_is_failed_not_zero_success[ndvi]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 28 | `test_all_masked_no_data_is_failed_not_zero_success[lst]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 29 | `test_simulated_transient_boundary_then_real_numeric_computation[ndvi]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 30 | `test_simulated_transient_boundary_then_real_numeric_computation[lst]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 31 | `test_scope_is_only_routing_not_fabricated_spatial_measurement` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 32 | `test_source_hash_drift_fails_before_ast_or_numeric_result` | `AssertionError: Regex pattern did not match.` |

### `green-area-backend/tests/test_source_integrity.py` (3 ข้อ)
| # | เทสต์ | รหัส error / ข้อความบรรทัดแรก |
|---|---|---|
| 1 | `test_legacy_spec_and_numeric_results_identical_on_lf_and_crlf_checkouts[lf]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 2 | `test_legacy_spec_and_numeric_results_identical_on_lf_and_crlf_checkouts[crlf]` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |
| 3 | `test_new_definition_does_not_change_old_results_or_relabel_old_requests` | `gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID` |

## 2. แยกตามสาเหตุ
- ล้มเพราะ `PROCESSING_FIXTURE_INVALID` (ขนาดหรือ sha256 ของ fixture ไม่ตรง ที่ `gis_worker/processing_provider.py:219`): **47 ข้อ**
  - 46 ข้อได้ `ProcessingError: PROCESSING_FIXTURE_INVALID` ตรง ๆ
  - 1 ข้อเป็น `AssertionError` แต่ข้อความเต็มแสดงว่าสาเหตุคือ fixture: `tests.test_processing_provider::test_source_hash_drift_fails_before_ast_or_numeric_result` คาด `PROCESSING_LEGACY_SOURCE_CHANGED` แต่ได้ `PROCESSING_FIXTURE_INVALID` จากบรรทัด 219 ก่อนถึงจุดที่เทสต์ต้องการ
- ล้มเพราะสาเหตุอื่น: **0 ข้อ**

ข้อความเต็มของข้อที่เป็น AssertionError (อ้างอิง):
```
legacy = WindowsPath('<pytest-tmp>/test_source_hash_drift_fails_b0')

    def test_source_hash_drift_fails_before_ast_or_numeric_result(legacy):
        (legacy/'gee_utils.py').write_text('raise RuntimeError("MUST_NOT_EXECUTE")',encoding='utf-8')
        with pytest.raises(p.ProcessingError,match='PROCESSING_LEGACY_SOURCE_CHANGED'):
>           p.OfflineProcessingAdapter(legacy_root=legacy).compute(request())

tests\test_processing_provider.py:104: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
gis_worker\processing_provider.py:219: in compute
    require(len(raw) == m['byte_size'] and hashlib.sha256(raw).hexdigest() == m['sha256'], 'PROCESSING_FIXTURE_INVALID')
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

value = False, code = 'PROCESSING_FIXTURE_INVALID'

    def require(value, code='PROCESSING_INPUT_INVALID'):
        if not value:
>           raise ProcessingError(code)
E           gis_worker.processing_provider.ProcessingError: PROCESSING_FIXTURE_INVALID

gis_worker\processing_provider.py:53: ProcessingError

During handling of the above exception, another exception occurred:

legacy = WindowsPath('<pytest-tmp>/test_source_hash_drift_fails_b0')

    def test_source_hash_drift_fails_before_ast_or_numeric_result(legacy):
        (legacy/'gee_utils.py').write_text('raise RuntimeError("MUST_NOT_EXECUTE")',encoding='utf-8')
>       with pytest.raises(p.ProcessingError,match='PROCESSING_LEGACY_SOURCE_CHANGED'):
E       AssertionError: Regex pattern did not match.
E         Expected regex: 'PROCESSING_LEGACY_SOURCE_CHANGED'
E         Actual message: 'PROCESSING_FIXTURE_INVALID'

tests\test_processing_provider.py:103: AssertionError
```

## 3. เทสต์ที่ skip ต่างจาก `c1-baseline-backend-5402805.txt`
skip รวม: baseline 82 · เครื่องนี้ 81 · ต่าง 1 รายการ

| ไฟล์:บรรทัด | เหตุผลที่ skip | baseline | เครื่องนี้ |
|---|---|---|---|
| `tests/test_gis_native_provider.py:135` | Host does not permit symlink creation; Linux run required | 1 | 0 |

เทสต์คือ `test_symlink_artifact_is_rejected` ในเครื่องนี้สร้าง symlink ได้ จึงรันและ**ผ่าน** (ไม่อยู่ในรายการล้ม) ส่วนเครื่องหัวหน้า skip

## 4. `git ls-files --eol -- green-area-backend/gis_worker/processing_fixtures/`
```
i/lf    w/crlf  attr/                 	green-area-backend/gis_worker/processing_fixtures/processing_lst_no_data.json
i/lf    w/crlf  attr/                 	green-area-backend/gis_worker/processing_fixtures/processing_lst_standard.json
i/lf    w/crlf  attr/                 	green-area-backend/gis_worker/processing_fixtures/processing_lst_transient_once.json
i/lf    w/crlf  attr/                 	green-area-backend/gis_worker/processing_fixtures/processing_ndvi_no_data.json
i/lf    w/crlf  attr/                 	green-area-backend/gis_worker/processing_fixtures/processing_ndvi_standard.json
i/lf    w/crlf  attr/                 	green-area-backend/gis_worker/processing_fixtures/processing_ndvi_transient_once.json
```
ทั้ง 6 ไฟล์เป็น `i/lf w/crlf attr/` คือใน git เป็น LF แต่บนดิสก์เป็น CRLF และไม่มีกฎ `-text`
