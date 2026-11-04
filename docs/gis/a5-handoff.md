# A5 — PASS / Local Synthetic source-aware Dashboard

Scope: Local Synthetic only. Base `9757cbe9e9a691deabfb81ebe1428032400afeb9`,
branch `feature/gis-data-management`. No A6, Live GEE, Cloud or deployment.

## Compatibility matrix / focused source findings

| Feature | Required inputs | Current Published inputs | Decision / minimal implementation |
|---|---|---|---|
| Map / legend / descriptive summary | One current verified source snapshot | A3 geometry + original Shape_Area/code groups; A4.2 raster + valid-pixel statistics | Supported for source footprint only; one snapshot, explicit units/provenance |
| Province / district analysis | Complete province or validated AOI clip and denominator | Intersection with approximate boundary, no whole-province guarantee or AOI statistics | Unsupported; never label uploaded footprint statistics as province/district statistics |
| Existing province Comparison | Comparable province NDVI/green-area measurements at same period | No full-province NDVI/green-area coverage; LDD is not NDVI; raster periods unverified | Unsupported; explain missing inputs instead of invoking Legacy compare |
| Timeseries / forecast | Multiple independent observations with verified periods and comparable spatial support | Uploaded ready-profile period declarations only; one active snapshot per scope | Unsupported; no invented timeline or forecast |
| Ranking | Comparable urban green area / urban population denominators | No urban subset, population or compatible province-wide inventory | Unsupported; Legacy ranking retained separately |
| Recommendation / Priority | Aligned NDVI/LST, population, access, ISA, land cover, slope/feasibility inputs | Independent footprint summaries, no complete aligned factor grids | Unsupported; preserve all existing formulas/weights |
| Cooling / NDVI–LST relationship | Aligned paired observations and established model assumptions | No verified spatial/temporal pairing | Unsupported; no correlation/causality claim |
| Saved-area analysis | AOI geometry + source identity, period and validated clipping | Existing saved records have their own geometry/year/Legacy analysis; no Published AOI contract | Unsupported in Published mode; keep records and normal Legacy loading unchanged |

Relevant source: Backend `main.py:160` Comparison (`ndvi_annual`), `main.py:329`
Ranking (`urban_ndvi_annual`, m²/person); `routers/recommend/scoring.py:223`
multifactor priority; `routers/saved.py:37` saved geometry/year/analysis contract.
Frontend `useCompareData`, `useTrendData`, `CompareTab`, `TrendTab`, `useAreaTools`.
Providers: `gis_ldd_publication.py`, `gis_geotiff_publication.py`; A1 `SourceIdentity`.

These decisions describe existing Dashboard feature meanings, not a claim that
every possible future descriptive comparison is impossible. A new footprint
comparison or verified temporal pipeline needs a separately approved contract.

## Implementation approach approved for this task

Reuse the existing providers, source identity, polling/revocation, map builders,
summary components and Sidebar navigation. Add a shared presentation-only
compatibility/availability view. Isolate Published LDD map/legend/summary even
while loading or unavailable, and show explicit unsupported explanations instead
of mounting Legacy derived views. GeoTIFF uses its existing explicit mode.
No new calculation, API, migration, authorization boundary, cache or dependency.

Independent scientific/data-integrity review: existing reviewer
`local_integration_security_review` agrees with this limited matrix and requires
selected-source guards, exact scope/snapshot, reachable source/year/back controls,
and no Legacy draw/recommend/saved-area overlays in Published mode.

## Implementation / acceptance

A5 PASS within the compatibility matrix above: source-aware map/descriptive views
and explicit unsupported derived states. This does not mean new Published
Comparison, Timeseries, Ranking or Priority algorithms are implemented.

- New shared `publishedAnalysis` DTO guard binds scope, lineage, method, units,
  NoData and required display payload. It calculates no scientific measurements.
- `PublishedAnalysisAvailability` presents supported/unavailable/unsupported
  reasons tied to the same source snapshot, for LDD and ready-profile GeoTIFF.
- Dashboard isolates Published LDD layers/legend/summary even during loading,
  failed/revoked/mismatched data; hides Legacy draw/recommendation/saved overlays.
- Sidebar retains existing navigation with specific unsupported reasons;
  Stats uses existing LDD source/year controls; Header clearly identifies source.
- Missing scope and country-back remain Published/unavailable with a visible
  Legacy escape; Legacy ranking/compute/export never appear under Published.
- Published scope/year/source changes and revocation clear old views; valid zero
  NDVI/Celsius values stay valid and NoData is never converted into zero.
- No new Backend/API/Auth/SQL/cache/dependency or scientific formula changes.

## Actual tests / evidence boundary

| Evidence | Result | Scope |
|---|---|---|
| `frontend-country-final.json` | 110/110, 14 suites | Affected views/hooks, lineage/units/NoData, loading/error/source changes, country isolation, Legacy default |
| `integration-ad8ee3ebc5/results.json` | 14/14 | Real Local Auth/API/Queue/Linux Worker, two synthetic LDD editions + one NDVI GeoTIFF, trusted verification, no auto-activation, cleanup |
| `integration-ad8ee3ebc5/browser-results.json` | 32/32 | Actual Chrome/no API mocks: replacement/rollback/revocation, snapshot, missing period, unsupported tabs, Legacy return, mobile viewport; no page errors or Legacy derived requests while Published |
| `country-b6a3d46042/browser-country-results.json` | 14/14 | Targeted final country-back fix, source/year-preserving province reselection and explicit Legacy return; no page errors or API mocks |
| `preservation-country-final.json` | 15/15 | Read-only final preservation against the pre-A5 baseline, both Local databases, current source |
| `local-build-country-final/` | PASS | Final source compiled with existing Local Vite profile, no deployment |

No tests ran against Production/Staging/GEE/Cloud. Native/Backend/SQL acceptance
from A4.2 is reused because those source files and dependencies are unchanged;
this task does not claim a new full Backend/Linux/SQL regression run.

The initial isolation unit test failed once because the UI DTO fixture omitted
its legend; fixed the fixture and added a missing-display-payload regression.
No scientific expected values were changed. Independent review then found P1:
Published LDD → country overview could mount Legacy ranking/compute/export.
Fixed only that Sidebar branch, added two unit cases and the targeted real
Browser regression. The original 32-check Browser run predates this final
branch fix; it is retained, not relabeled as rerun. The changed branch is covered
by the final 14-check targeted run, and all affected frontend tests/build passed.

Raw evidence is outside Git under `<owned-T0-root>/a5-published-analysis/`.
`tested-source.json` retains the initial 480-path manifest. Final
`tested-source-country-fix.json` records the five-path delta (one Sidebar source,
two tests and two harnesses), with all other app/Backend/Native/SQL unchanged.
Final executable/config source SHA256:
`34a66b05aee4ba3efe66736fba7e54a0a2c8ed29ee8e0df9fc0b54083c4f1fcc`.
Docs are finalized after tests; they are not claimed as executable test inputs.

## Preservation / independent review

Both `postgres` and `gis_t1_upgrade`: original public-table counts/hashes,
profiles, full migration ledger and original GIS rows (including active pointers,
artifacts and audit/history) preserved. Pre-existing populated NDVI/LST caches
and Saved Areas are unchanged; no global invalidation or cache write was added.
The broad activation gate remains closed; test-owned catalog pointers were
retired without deleting their source bytes, artifacts or history. Queue idle;
owned API/UI/Worker processes were closed and original volumes retained.
All migrations000–042 remain byte-identical; no migration ran in A5. The five
original untracked evidence JSON files are retained unchanged and excluded from
this commit.

Scientific/data-integrity review by `local_integration_security_review` approved
the matrix/core approach. The final recheck was transferred after that reviewer
became unavailable; `a5_final_integrity_review` found and verified the country P1
fix, exact final source/manifest, 110 tests, targeted Browser and final 15-check
preservation. Final independent decision: PASS Local Synthetic; High/Critical0.
Reviewers did not edit files or run DB/cloud operations themselves.

## Changed files / reproducibility

Frontend: Dashboard, AppHeader, UserMenu, Sidebar, StatsTab, LandusePanel,
Published LDD/GeoTIFF summaries, both publication hooks; new availability component
and `utils/publishedAnalysis`. Tests cover those boundaries and use clearly
labeled UI DTO fixtures in `src/testFixtures/publishedSnapshots.js`.

Local harnesses: `dev/gis_local/published_analysis_checks.py` and
`dev/gis_ui/a5_smoke.cjs`. They reuse the attested A4.2 operator and create only
fresh synthetic catalogs on an owned T0 sandbox with migrations000–042 already
reviewed/applied. Credentials stay in private memory/stdin pipes, not files.

Full focused Local flow: run `published_analysis_checks.py --runtime-dir
<owned-T0-root> --node-modules <existing-Playwright-node-modules>` with the
existing Backend virtual environment. The country-only regression uses
`--resume-country ad8ee3ebc5`, restricted to that A5-owned synthetic catalog.
After acceptance its A edition was terminally withdrawn; a fresh full run is
needed for later repeatability, not an attempt to reactivate withdrawn editions.

## Remaining limitations / next approval

- All measurements tested here are synthetic, not real GIS or production proof.
- GeoTIFF dates remain declarations, not verified observations; footprints are
  not province inventories. Existing Comparison/Trend/Ranking/Priority/Cooling
  meanings still need their missing inputs and separately approved contracts.
- No physical mobile-device, Live Basemap/GEE/Cloud, throughput or new physical
  Worker Kill/OOM/timeout test was run. Browser external HTTPS was blocked.
- Saved records keep their original geometry/year/Legacy results; Published AOI
  clipping and source-aware saved-result storage remain unsupported.
- A6 can be proposed separately; Cloud/GEE identity, sandbox isolation and live
  execution permissions still require verification/approval. Do not start A6.

Base/parent commit: `9757cbe9e9a691deabfb81ebe1428032400afeb9` on
`feature/gis-data-management`. A5 is authorized for one Local Commit after PASS;
final commit SHA/status is supplied in the completion message. No Push, Merge,
PR, Deploy, main change or branch switch is authorized or performed.
