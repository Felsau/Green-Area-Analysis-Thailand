# LDD field mapping, code, area and geometry policy (`ldd-policy-v2`)

Updated 6 November 2026. Scope: findings 3 and 4 of the 3 November 2026 external review. Code: `gis_worker/ldd_policy.py`, `ldd_provider.assess()` and `ldd_prepare_provider.py`.

## Outcomes

| Category | Report | Meaning |
| --- | --- | --- |
| Accepted | `valid=true`, no minor warning | — |
| Accepted with Warnings | `valid=true` plus minor warnings | repaired geometry, slightly outside the boundary, declared area slightly different, numeric main code normalised, declared-area units not verifiable |
| Review Required | `valid=false`; every error is in the REVIEW set | unknown or unmapped codes, a small part outside the tolerance, outside share too high, declared area differs by more than 1 %, too many repairs |
| Rejected | `valid=false` with any other error | archive, CRS or encoding errors, missing or ambiguous fields, null/empty/non-polygon geometry, unrepairable geometry, a repair that changes the type or the area beyond the limit, clearly outside the province |

Exceptions from GDAL/OGR/GEOS/PROJ are reported as `SHAPEFILE_READ_ERROR`; any other unexpected exception is `NATIVE_PROCESS_FAILED`, so a code fault is never shown as a file defect. Every parcel is counted. The local inventory also counts parcels per category (`feature_outcomes`). Nothing is dropped, clipped or reduced to its largest part.

## Fields: `ldd-lu-text-v1`

The profile maps roles to field names: `LUL1_CODE` → main_code, `LU_CODE` → lu_code, `Shape_Area` → declared_area (m² only in EPSG:32647/32648).

- Names are matched case-insensitively.
- Names that are duplicates after case-folding are rejected (`FIELD_NAME_AMBIGUOUS`). So are files that match two profiles (`FIELD_MAPPING_AMBIGUOUS`). Files that match no profile fail with `ATTRIBUTES_MISSING`; a field such as `AREA` is never taken to mean `Shape_Area`.
- The profile ID and the actual field names are recorded in two places: in the validation report as the warning `FIELD_PROFILE_LDD_LU_TEXT_V1`, and in full in the preparation v2 metadata and the inventory output.
- More profiles (for example for the six 2025 provinces) can be added only from a real file's recorded schema. Run `ldd_inventory.py` on the file, add a new profile with that provenance, and have it reviewed. None is added yet, because those files are not in the repository.

## Codes: `ldd-code-legend-v1`

- Text LU codes, including composites, are looked up in the hash-pinned legend (Bangkok 2566, 96 codes).
- The main code may be a letter, an integer, an integral float or a numeric string. The letter↔number pairing is derived from the legend and must agree with the old fixed pairing. Values other than plain integers add the warning `NUMERIC_MAIN_CODE_NORMALISED`.
- Numeric LU codes need an approved crosswalk with recorded provenance. `CROSSWALKS` is empty, so these codes are counted as unknown (reason `NUMERIC_CODE_NO_APPROVED_CROSSWALK`) and need review. They are never mapped to U/A/F/W/M by assumption.
- For unknown codes the count, the area and up to 10 samples (value, main code, reason) are kept.

## Area: `geometry-area-utm-v1`

- Area is computed from the geometry in metres. UTM sources are used as they are; EPSG:4326 sources are projected to UTM 47N or 48N by longitude (102°E).
- Declared area is always compared as m². Within 0.1 % or 1 m² (the old tolerance) it matches; for a CRS whose units the profile does not state (EPSG:4326), a match is what shows the value is in m². Up to 1 % gives a minor warning. Above 1 % needs review, and when the profile states no units it also adds `DECLARED_AREA_UNITS_UNVERIFIED`. A wrong value is never ignored.
- Validation, preparation v2 and the summary all use this one area, together with any repaired geometry.

## Geometry and boundary

Boundary tolerance (`boundary-tolerance-m-v1`), measured in metres in the parcel's UTM zone against the approximate GADM boundary:

- Inside the boundary: no issue.
- Within boundary + 225 m: minor warning. The old 0.002° buffer is about 216–221 m in Bangkok, so 225 m keeps everything the old buffer accepted, and is not widened beyond it.
- Not within 225 m, but within boundary + 1000 m and with at most 5 % of the parcel beyond 225 m: review.
- Anything else: rejected.
- Across the whole dataset, if the area outside the raw boundary is more than 1 % of the total and more than 1 ha, the dataset needs review. The 1 ha floor stops one small edge parcel from turning a small dataset into Review Required.

Repair (`ldd-geometry-repair-v1`):

- Repair happens only for invalid polygons, using `shapely.make_valid(method='structure')` (shapely 2.2.0 in the pinned image). If that method is unavailable the parcel fails with `GEOMETRY_ENGINE_UNSUPPORTED`; there is no fallback to another method.
- The result must be a valid, non-empty Polygon or MultiPolygon, and its area may change by at most max(1 m², 0.1 %). Otherwise the parcel is rejected.
- Each repair is logged: feature index, method, reason, area before and after, type before and after.
- The dataset needs review if more than max(10, 1 %) of its parcels were repaired, or if the total area change is above max(1 m², 0.01 %).
- The original geometry stays in the immutable source ZIP. Preparation v2 also stores it per repaired parcel.

These thresholds were set before any real file was available, and no sample was used to tune them.

## Preparation

| Method | Status |
| --- | --- |
| `ldd-source-area-v1` | Pinned by migrations 038/039. Byte-identical for existing fixtures (tested). Gated by the frozen pre-v2 validator (`validate_legacy_v1`), so editions prepared before this change still re-verify. A dataset that only the v2 policy accepts (repairs, normalised codes) stops with `PREPARE_METHOD_V2_REQUIRED`. |
| `ldd-geometry-area-v2` | Implemented and tested (derived geometry, geometry area, source geometry for repaired parcels, mapping and policy metadata, same totals as validation). The queue cannot request it until migration 049 is approved and applied. |

## Real data

Status: NOT VERIFIED. The repository contains no real LDD file (Bangkok 2566/2023, or the six provinces for 2568/2025). The figures "158 out-of-bound parcels" and "6 geometry/area issues" have not been confirmed. Check them with:

```powershell
.\dev\gis_local\run_ldd_inventory.ps1 -Zip 'D:\ldd\bkk_2566.zip' -Province 'Bangkok Metropolis' -Year 2023
```

The inventory is read-only. It reports the filename, SHA256, CRS, schema and field types, feature count, profile, the four outcome counts, reasons, samples and repairs.

## Proposed forward migration 049 (not written, not applied, needs approval)

1. Extend the 034 report validator, accepting `schema_version` 2 alongside 1. Add optional `policy`, `field_mapping`, `feature_outcomes`, `unknown_samples` (≤10) and `repairs` (≤50) objects with closed key sets, so that these details live in the result and not only in warning codes.
2. Allow `ldd-geometry-area-v2` alongside `ldd-source-area-v1` in 038/039 (CHECK constraints, prepare and publication commands, and reads). v1 rows stay v1.
3. Add an optional officer-selected `field_profile` to the upload manifest (`gis.ldd_manifest`, `LddUploadQuery`), validated against the profiles in code. When it is absent, today's auto-match applies.
4. Add a review workflow so that an officer can approve or reject a Review Required edition with a reason. Until then, Review Required means not usable.

Each step needs an independent SQL review, then a rollback probe and an approval file before it is applied. Migrations 000–048 are not modified.
