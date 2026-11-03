# A4.1 Local GeoTIFF prepare and trusted review

Scope: Local synthetic ready profiles only. No GeoTIFF activation, withdrawal,
rollback, published Dashboard reader, GEE call, cloud storage or deployment.
The legacy Dashboard and the A1–A3 LDD publication contract remain unchanged.

## Supported input and output

- `ndvi_ready` → `ndvi_raster` + `ndvi_summary`, unitless.
- `lst_celsius_ready` → `lst_raster` + `lst_summary`, Celsius unchanged.
- `lst_kelvin_ready` → the same LST roles, Float64 Celsius. Subtract 273.15
  exactly once during preparation; summary/preview read that prepared array.
- Revalidate the original single-band Float32/Float64 TIFF, supported CRS,
  north-up affine, explicit finite NoData, scale=1/offset=0, units/profile/band.
  Reject NaN/Inf, all-NoData, external/internal dataset masks, unsupported raw
  bands/profiles. Preserve the numerical grid, CRS and resolution; no clipping,
  resampling or reprojection of raster values.
- Maximum preparation size: 1,000,000 pixels and original source 20 MiB;
  individual artifacts 20 MiB. Native AS 512 MiB, CPU 20s, parent wall 25s;
  container 1 GiB/1 CPU/PIDs64, no swap above its memory limit. Staging/storage
  accounting 256 MiB is a soft Local guard, not an OS disk quota. Concurrency=1.
- A finite input NoData sentinel is preserved unless it collides with the output
  scientific range (e.g. Kelvin NoData=0 vs valid Celsius=0); then output NoData
  becomes -9999. Metadata retains both sentinels and the normalization flag.

Versioned method: `geotiff-grid-celsius-v1`; verifier:
`geotiff-trusted-bytes-v1`; metadata/summary schema_version=1.
TIFF embeds `GIS_PREPARED_METADATA`. The JSON summary binds Dataset/Edition,
current successful native validation result, input revision/hash, original SHA,
province/year/month, original/output profile/units, method, CRS, transform,
resolution, dtype, NoData, footprint and coverage. Descriptor pairs contain
actual SHA256 and byte_size; summary also binds the prepared raster SHA256.
Registry artifacts additionally bind the actual completed job/edition.

Statistics are unweighted mean/min/max of valid pixels, with valid/NoData/total
counts. They are not province-wide or geodesically area-weighted statistics.
The bounded PNG samples at most 64×64 pixel positions for visualization only;
NoData is transparent. The browser never receives the full scientific array.

## Spatial and period limitations

Transform densified outer grid edges to EPSG:4326 solely for footprint checks.
Use the existing SHA-pinned approximate province boundaries. Require a valid
positive-area intersection. Record footprint and both intersection fractions as
approximate geographic-area ratios, not physical/geodesic area measurements.
Footprint includes NoData holes; valid-pixel fraction is reported separately.
`complete_province_inventory=false` always.

Any present GIS_PROVINCE/GIS_YEAR/GIS_MONTH source tags must match Dataset scope.
Monthly input requires all three tags; annual input may omit them. Tags remain
uploader declarations: `period_verified=false` always, even when consistent.
Neither a province name nor an intersection proves complete provincial coverage.
Ready-profile uploads are not equivalent to the legacy GEE annual/monthly pipeline.

## API and authority

All routes require a verified Auth actor and GIS officer/admin capability.
No normal-user/anonymous access to these private previews.

| Method/path under `/gis/editions/{id}` | Contract |
|---|---|
| POST `geotiff-prepare-jobs` | Idempotency-Key; dataset revision, input revision/hash, current validation_result_id, province/year/month |
| POST `geotiff-prepare-retry` | Same CAS fields plus failed root job_id and reason; one explicit retry child |
| POST `geotiff-prepare-verification` | Idempotency-Key + current job_id only; client cannot supply a proof |
| GET `geotiff-prepared` | no-store; current status/attempts, verified summary/PNG only when actual source and artifacts remain intact |

SQL reauthorizes the trusted actor. GeoTIFF editions remain draft, with
validated_result_id NULL under the existing upload contract. Successful native
validation lineage is resolved separately. A successful prepare is a candidate,
not a certificate. `ready_for_review` is distinct from publication readiness;
`ready_for_publication=false` and generic eligibility remain false.

## Worker, storage and verifier

Reuse existing jobs/attempts/results, atomic single claim, trusted Auth JWT subject,
60s lease, 5s heartbeat, 5s retry backoff, three attempts, fencing and recovery.
The new worker claims/recovers only prepare_geotiff_edition. Legacy queue protocols
cannot heartbeat/complete/fail these jobs. Worker has only its least-privilege
custom-role JWT, never a service-role key; the native child receives neither.

Worker original-source mount is RO; staging is RW. It has no immutable-object
mount or certification authority. Native child uses a fixed command and bounded
clean environment. A separate one-shot verifier has source/staging RO, network
none, no credentials and the same pinned runtime. It revalidates the original and
recomputes deterministic raster/summary bytes, then compares actual staged bytes.
The host binary adapter parses no GIS natively; it rechecks SHA/size, promotes
fixed allowlisted roles by immutable content-addressed filenames, then SQL
certifies current lineage/lease/result/registry consistency atomically.

Reads recheck current lineage and actual source/output hashes. Missing/corrupt
bytes hide the summary and revoke the certificate durably; restoring files alone
does not undo revocation. Failed verification cannot self-certify a candidate.
Old source objects, attempts, artifacts and certificates remain stored.

## SQL change boundary

Forward migration041 only. Three owner-only FORCE RLS tables store requests,
certificates and revocations, with immutable/deferred invariants. Four legacy
functions gain only the required GeoTIFF-prepare exclusions; LDD eligibility,
publication readiness, publication transactions and scientific formulas do not
change. Exact SQL/ACL must be independently reviewed before Local application.
Applied SQL000–041/ledger are immutable; any correction requires a new migration.

Test operators attest exact Local containers, runtime identity and both database
ledgers before mutations. A4 operator uses the existing external Local baseline
snapshot, not production configuration or dotenv. Ordinary application startup
does not enable this private store/provider or any new publication gate.
