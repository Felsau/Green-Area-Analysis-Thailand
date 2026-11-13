# W4: LDD southern land-use layers, field survey (Narathiwat, Phang Nga, Yala 2564)

Recorded 10 November 2026. Documentation only: no code, profile or migration changed. Read with this: `ldd-field-policy.md` (`ldd-policy-v2`), which describes the field profiles, the `.cpg` aliases and the package rule referred to below.

## Scope and method

- Packages (kept outside the repository, already extracted; nothing was unzipped or copied for this survey):

  | Province | Package | SHA256 |
  |---|---|---|
  | นราธิวาส (Narathiwat) 2564 | `Landuse_นราธิวาส_2564 (ปีล่าสุด).zip` | `a2851b6a5bc1f52f587bba4ae7d7c68ab8c1b5789a19fff6403f8de83d48f487` |
  | พังงา (Phang Nga) 2564 | `Landuse_พังงา_2564 (ปีล่าสุด).zip` | `1b547a090e6043b6f81746967436d1c2814d8c666cbf685105a743fd1adc575d` |
  | ยะลา (Yala) 2564 | `Landuse_ยะลา_2564 (ปีล่าสุด).zip` | `a36cd8ba3506ed54e8c4eb8d639a227abf8e492697f01b5b51360e811509953d` |

- Each package holds one land-use layer (`LU_<abbr>_2564`: `.shp .shx .dbf .prj .cpg .sbn .sbx .shp.xml`), `LUCODE.xls` and `ReadMe_ปี62-64_Zone-47.pdf`. No other shapefile, so the package rule picks the `LU_*` layer without ambiguity.
- Read with the Python 3 standard library only (DBF header and every record, `.cpg` and `.prj` as text). GDAL was not used and the geometry was not read, so geometry area, validity and boundary were not checked.
- Codes were compared with `green-area-backend/gis_worker/ldd_codes_v2.json` (`ldd-code-legend-v2`, 256 entries).

## Per-province comparison

| | Narathiwat 2564 | Phang Nga 2564 | Yala 2564 |
|---|---|---|---|
| Layer | `LU_NWT_2564` | `LU_PNA_2564` | `LU_YLA_2564` |
| Records (deleted) | 30,693 (0) | 35,253 (0) | 18,497 (0) |
| `.dbf` / `.shp` size | 46.3 MB / 36.6 MB | 53.1 MB / 39.0 MB | 28.4 MB / 27.3 MB |
| DBF version, date | 0x03, 2022-01-02 | 0x03, 2021-12-22 | 0x03, 2023-11-22 |
| `.cpg` | `UTF-8` | `UTF-8` | `UTF-8` |
| DBF language ID (byte 29) | 0x00 (none) | 0x00 | 0x00 |
| Thai text | strict UTF-8 on every row; not valid cp874 | same | same |
| `.prj` | `WGS_1984_UTM_Zone_47N` (ESRI WKT, no `VERTCS`), identical in all three | same | same |
| Matching profile | `ldd-lu-text-v1` | `ldd-lu-text-v1` | `ldd-lu-text-v1` |

### Fields

DBF type / length.decimals. "—" means the field is absent.

| Field | Narathiwat | Phang Nga | Yala | Values |
|---|---|---|---|---|
| `OBJECTID` | — | — | N 10.0 | 1 … 18,497 |
| `LU_ID_L1` | F 19.11 | F 19.11 | F 19.11 | `2.00000000000e+000`; 1-5, plus `112` on 39 rows in Narathiwat |
| `LU_ID_L2` | F 19.11 | F 19.11 | F 19.11 | `23`, `24`, `12` …; composites as concatenations, e.g. `12124` |
| `LU_ID_L3` | F 19.11 | F 19.11 | F 19.11 | `2401`, `2302` …; composites e.g. `231512418` |
| `LU_CODE` | C 254 | C 254 | C 254 | `A401`, `A302`, `U201`; composites `U201/A401` |
| `LU_DES_TH` | C 254 | C 254 | C 254 | `ไม้ผลผสม`, `ยางพารา`, `หมู่บ้านบนพื้นราบ` |
| `LU_DES_EN` | C 254 | C 254 | C 254 | `Mixed orchard`, `Para rubber`, `Village` |
| `LUL1_CODE` | C 254 | C 254 | C 254 | `A U M F W` (always one letter, never blank) |
| `LUL2_CODE` | C 254 | C 254 | C 254 | `A3`, `A4`, `U2` |
| `LU_DES` | C 150 | C 150 | C 150 | free text, mostly blank (90 %, 46 %, 48 %); `R1`, `P2`, Thai crop lists |
| `Shape_Leng` | — | — | F 19.11 | 10.6 … 852,278 (m) |
| `Shape_Area` | F 19.11 | F 19.11 | F 19.11 | m²; 34 … 4.35×10⁸ / 0.013 … 1.15×10⁹ / 4.1 … 9.03×10⁸ |
| `RAI` | N 10.0 | N 10.0 | N 10.0 | whole rai, 0 … 720,698 |

Field order differs (Phang Nga has `Shape_Area` before `LU_DES`); the validator matches by name, so order is irrelevant.

### Value checks

| Check | Narathiwat | Phang Nga | Yala |
|---|---|---|---|
| Distinct `LU_CODE` | 68 | 167 | 53 |
| Composites with `/` | 1,348 | 881 | 59 |
| Composites with `+` | 0 | 0 | 0 |
| Codes (or composite parts) not in legend v2 | 0 | 0 | 0 |
| `LUL1_CODE` ≠ first letter of `LU_CODE` | 0 | 0 | 0 |
| `LU_ID_L1` ≠ `LUL1_CODE` (U A F W M = 1-5) | 1,334: `U201/A401` → 2 (1,295), `U201/A405` → 112 (39) | 0 | 53: `U201/A401` → 2 |
| `RAI` = round(`Shape_Area` / 1600) | every row | every row | every row |
| `Shape_Area` < 1 m² | 0 | 10 | 0 |

## Findings

1. All three layers carry `LUL1_CODE`, `LU_CODE` and `Shape_Area`, so they already satisfy `REQUIRED_FIELDS` (`green-area-backend/gis_worker/ldd_provider.py:49`) and match exactly one policy-v2 profile, `ldd-lu-text-v1`. This covers field names only: geometry, CRS-to-area agreement and the composite-code class rule were not checked (see "Not checked" below), so it does not yet show that the layers would be accepted. None has `AREA_SQM`, `Area_Rai` or `Area_RAI`. The layouts that motivated W4 were not found in these three provinces.
2. `RAI` sits alongside `Shape_Area` and is a rounded derivative of it (1 rai = 1,600 m²). It is not used and does not affect profile matching.
3. Encoding is UTF-8, declared by `.cpg` and confirmed on every row. This differs from the central-region 2568 files (`.cpg` "ANSI 874" or none, cp874). No alias is needed.
4. `LU_ID_L1` encodes the class of the first part of a composite inconsistently (`U201/A401` → 2, i.e. A) and holds the stray value `112`. This confirms the existing rule that `LU_ID_L1` is used only when `LUL1_CODE` is missing.
5. Not a field issue, but it decides the outcome: every `.dbf` exceeds the 20 MiB per-member limit (27.1, 50.7 and 44.1 MiB for Yala, Phang Nga and Narathiwat). The packages expand to 83,634,463 bytes (Narathiwat), 92,997,614 bytes (Phang Nga) and 56,256,806 bytes (Yala), 11 members each, so Phang Nga also exceeds the 80 MiB (83,886,080-byte) expanded limit, and Narathiwat is just under it. As distributed, all three packages would be refused on size before their fields are read.
   Which check refuses them, in order (code as of `9_13`):
   - If the `.zip` itself is over 20 MiB, the upload is refused with **`GIS_LDD_SIZE_LIMIT` (HTTP 413)** before it is stored (`routers/gis.py:227-228`, `gis_ldd_storage.py:363-364` and `:386-387`). The compressed `.zip` sizes were not recorded in this survey, so it is not yet known whether this check or the next one fires.
   - Otherwise the upload preflight refuses the oversized member with **`GIS_LDD_ZIP_UNSAFE` (HTTP 422)** (`gis_ldd_storage.py:284-286`). The officer sees the generic "ZIP ไม่ปลอดภัย" message, not a size message.
   - The worker's own codes (`ZIP_MEMBER_SIZE_LIMIT`, `ZIP_EXPANDED_SIZE_LIMIT`, `gis_worker/ldd_provider.py:185-187`) are never reached for these packages.
   - Still to do: record each package's compressed `.zip` size next to its SHA256.

## Proposal: field acceptance for every province

1. **Keep explicit profiles; do not loosen `REQUIRED_FIELDS`.** The `ldd_policy.FIELD_PROFILES` mechanism (roles `main_code`, `lu_code`, `declared_area`; case-insensitive names; `absent` lists so a file matches at most one profile; `FIELD_MAPPING_AMBIGUOUS` / `ATTRIBUTES_MISSING` otherwise) already covers these three provinces and the central/northern layouts. `REQUIRED_FIELDS` stays the frozen pre-v2 contract.
2. **No new profile for the southern 2564 layout.** It is `ldd-lu-text-v1`. Its provenance (the three SHA256s above) can be added to that profile's recorded real layouts when the profile list is next reviewed.
3. **`Area_Sqm` spelling** is already covered by `ldd-lu-area-sqm-v1` (`AREA_SQM`, case-insensitive).
4. **Missing `LUL1_CODE`** is already covered by `ldd-lu-id-l1-area-sqm-v1`. Keep `LUL1_CODE` first; the stray `LU_ID_L1` values here are further evidence.
5. **`Area_Rai` / `Area_RAI`** (none found in this survey): add a profile only from a real file's recorded schema and package SHA256, as `ldd-field-policy.md` requires. That profile would need:
   - `declared_area_units` of rai, converted to m² with 1 rai = 1,600 m²;
   - a tolerance that allows for whole-rai rounding (up to ±800 m² per parcel), not the 0.1 % / 1 m² used for m² fields, and a check that the value is actually rounded to whole rai;
   - an `absent` list keeping it apart from the m² profiles (`Shape_Area`, `AREA_SQM`), so a layer that has both an m² field and a rai field (like the `RAI` here) continues to use the m² field.
   A bare `RAI` or `AREA` field on its own stays refused (Phetchabun 2564 rule).
6. **Encoding**: keep reading the `.cpg`; UTF-8 needs no alias. A layer with neither a `.cpg` nor a DBF language ID still needs the officer's choice.
7. **Outside field policy, flagged only**: the per-member and expanded size limits block these packages. Changing them is a separate decision with its own review.

## Not checked

Added during review (11 November 2026). These limit what Finding 1 can claim:

- **Geometry**: not read, so validity, repairability and boundary fit (`OUTSIDE_PROVINCE`) are unknown.
- **CRS against area**: `Shape_Area` was not compared with the geometry area in `WGS_1984_UTM_Zone_47N`.
- **Composite class rule**: the legend check above only shows that every part of a composite exists in legend v2. It does not apply the policy rule that a composite must be listed whole or have every part in the parcel's own class. Mixed-class values such as `U201/A401` and `U201/A405` (at least 1,334 rows in Narathiwat and 53 in Yala, from the `LU_ID_L1` row above, where `LUL1_CODE` is `U` but the second part is `A`) still need to be checked against that rule.
- **Compressed `.zip` sizes**: not recorded (see Finding 5).
