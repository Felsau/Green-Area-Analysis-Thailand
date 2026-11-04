# A6.1 — Live GEE contracts and safe compute adapter

Status: **PASS, local mock-only scope**. Date: 2026-11-04.
Branch: `feature/gis-data-management`.
Base: `1e292ca9a22bd54e2166264471ef69d84f55a38d`.
One local commit is authorized after acceptance; the completion message records
its SHA. No push, merge, PR, deployment or A6.2 execution is authorized here.

## Implemented boundary

- `gis_worker/gee_contracts.py`: version1 discriminated future `live_gee` request
  and `offline_synthetic` reference, canonical province/period/geometry/method
  identities, semantic request hash, raw observation evidence and content-addressed
  summary candidate. The offline reference delegates to the unchanged Phase3
  `check_request`; it is not a replacement API or SQL contract.
- `gis_worker/gee_adapter.py`: explicit injected bridges for four existing helper
  families: NDVI annual/monthly and LST annual/monthly. No SDK, application startup,
  dotenv, credential, filesystem, cache/database or network client imports.
- Adapter execution accepts **mock only**. The existing `LiveGeeAdapter` stub,
  HTTP schemas, worker runtime, SQL protocols and live gates are unchanged.
- All outputs state `execution=mock`, `synthetic=true`, `publishable=false` and
  `endpoint_parity=summary_only`. A request naming future live mode is not live
  authorization or evidence of satellite execution.

## Compute port and evidence

Construct `SafeComputeAdapter(LegacyBindings(...), as_of=<explicit date>)`.
Each trusted injected callable receives `(geometry_geojson, year, scale)` and
returns `LegacyReturn(payload, Observation(...))` from the same computation.
Monthly helpers retain their existing twelve-month result; the adapter selects
the requested month without inventing monthly min/max values.

The observation binds the exact request hash, geometry hash, product, method,
period, collections and unique dated scene IDs. Raw nulls must be captured before
the old helpers' `or 0` conversions. Missing/open/incomplete periods, no scenes and
all-masked pixels cannot become a zero-valued valid candidate. Genuine observed
zero remains valid. Unknown valid-pixel counts remain null rather than fabricated.

The adapter refuses a bare legacy summary without raw evidence and checks the
rounded summary against that evidence. Geometry is copied and checked again
after the callback. Output parsing rechecks the semantic request hash, canonical
method, lineage, status and summary even if a caller recomputes the output hash.

`output_sha256` hashes the normalized JSON content; it is **not** a satellite
file/raster checksum. A candidate identity is separate from the request hash.
Hashes prove identity/consistency, not authenticity or authorization.

The callbacks are trusted dependencies, not an execution sandbox. Arbitrary code
inside a callback cannot be made harmless by this wrapper. The real SDK bridge,
credential boundary and network enforcement remain separately gated work.

## Scientific reuse and limits

- Methods bind the current SHA256 of `gee_utils.py`, `routers/ndvi/compute.py` and
  `routers/lst.py`. They retain Sentinel2 SR Harmonized/Cloud Score+, threshold0.6,
  reflectance division10000, annual scene20 fallback80 and monthly scene80.
- Annual NDVI's negative mask remains distinct from monthly behavior. The method
  is median Bands then normalizedDifference(B8,B4), not median per-scene NDVI.
- LST retains Landsat8/9 C2L2, scene40, QA bits3/4, ST_B10 multiplier0.00341802,
  offset149 Kelvin and subtraction273.15 once, then median aggregation.
- Province nominal reduction scale500m, bestEffort and existing annual NDVI
  tileScale4 are retained. bestEffort can coarsen effective resolution; these are
  not claims of native10m/30m or verified full-province coverage.
- No new scientific calculation or broad legacy refactor. Existing helpers cannot
  safely be imported as an unattended live bridge without isolating environment
  imports and preserving raw evidence. That actual bridge is **not implemented**.
- Current tests establish method specification parity, mock routing, existing
  synthetic numerical expectations and the actual legacy LST arithmetic on an
  inert injected image. They do not establish real GEE/server/spatial parity.
- Population, Canopy, endpoint Validation, Raster publication, Ranking, Timeseries,
  Priority and Cooling compatibility are not inferred from summary candidates.
- Geometry hash validates bounded WGS84 payload identity, not topology, official
  province membership, boundary authority or complete spatial support.

## Tests and independent review

Final run: **192 passed, 0 failed** on Windows/Python3.12.10,
Pydantic2.13.4 and pytest9.0.3; no new dependencies installed.

| Suite | Passed |
|---|---:|
| New contracts | 62 |
| New adapter/import/scientific checks | 67 |
| Existing offline processing provider regression | 63 |

The external runner clears application environment, blocks socket connection/DNS,
credential-file access and repository test writes, and disables bytecode/pytest
cache. A fresh interpreter test rejects SDK/startup imports, application file
opens and sockets. Pydantic's plugin switch receives a fixed disable value rather
than reading ambient configuration. Only Windows SYSTEMROOT is passed to that
child for Python/Winsock startup.

Historical failures retained outside Git: first runner lacked a terminal method;
test package imports were corrected; fresh Windows child needed SYSTEMROOT;
Pydantic's internal plugin switch needed the fixed no-plugin setting. Final
source and fixtures passed after these test-harness corrections.

Independent read-only reviewer `a61_contract_review`: **PASS**, no remaining
must-fix/High/Critical findings within A6.1. Earlier output-deserialization and
contradictory no-data concerns were corrected with shared observation/status
validation and rehashed forged-output regressions. Reviewer inspected exact
source/tests and did not claim to execute tests or verify GEE accounts.

Evidence outside Git under the existing visualization root, `a6-1-contracts/`:
`focused-4a29c933.log`, `.xml`, `-source.json`, `-result.json`,
`preservation-review.json` and `before.json`. Raw logs/evidence are not committed.
Source hashes in the successful run match the implementation being committed.

For the focused suites using the existing backend environment:

```text
python -B -m pytest -q -p no:cacheprovider tests/test_gee_contracts.py tests/test_gee_adapter.py tests/test_processing_provider.py
```

Run from `green-area-backend`; use a separate temporary test directory when
reproducing the external evidence runner's strict repository-write boundary.

## Preservation and remaining approvals

All174 pre-existing protected backend Python/migration/evidence files retain their
baseline SHA256, including all43 SQL files000–042 and the original five untracked
evidence files. No existing application/API/worker/formula/migration file changed.
No database connection, queue execution, migration, container operation, cache
write, pointer change, credential inspection or cloud operation was performed.
Database rows were not queried; this is a no-access/source-preservation result,
not a fresh before/after database snapshot comparison.

Python3.11 syntax parsing passed; Python3.11/Linux runtime, HTTP/Queue E2E, real
GEE parity, Quota/IAM/Billing, actual satellite data and production are Not Tested.

A6.2 requires separate approval for forward-only SQL/protocol integration and
independent security review. Live additionally requires a verified isolated
project/identity, raw-observation bridge, restricted network/runtime policy,
credential lifecycle and approved job/quota/time budget. No A6.2–A6.6 started.
