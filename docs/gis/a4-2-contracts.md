# A4.2 Local uploaded GeoTIFF publication

Scope: explicit Local Admin publication of verified uploaded ready profiles.
No GEE/cloud/production/deployment work. Legacy GEE stays the Dashboard default;
the Published view is a separate opt-in source and never replaces legacy NDVI/LST,
ranking/recommendations, saved areas, comparison or timeseries data.

## Eligibility and provenance policy

- Policy `local-declared-period-footprint-v1` records informed Local use. It
  NEVER changes `period_verified=false`, claims an independently observed date,
  complete province inventory, official validation or equivalence to GEE.
- Publication supports EPSG:4326 north-up ready-profile inputs only. A4.1 still
  supports its original preview profiles/CRSs; its ready_for_publication stays
  false. Geographic image bounds must remain within longitude ±180/latitude ±85.
- NDVI is unitless; LST is Celsius. Kelvin conversion occurs only in A4.1.
- Scope is an exact province/product/year/month Dataset identity. Month 0 is
  declared annual scope, never a substitute for a requested month. Matching
  month tags are declarations, not independently verified dates.
- Summary describes all valid pixels of the uploaded source footprint, not
  full-province or district statistics. Approximate boundary intersection and
  valid-pixel fractions retain the A4.1 accuracy limitations. District, bbox,
  arbitrary AOI or whole-province coverage requests are rejected.
- Uploaded bytes are labeled `local_uploaded_ready_profile`, never automatically
  labeled synthetic or official. Acceptance tests separately use synthetic data.

## Mutation contract

Admin-only POST `/gis/datasets/{id}/geotiff-publication/{activation|rollback|withdrawal}`.
All require Idempotency-Key and explicit reason; Dataset revision/current pointer,
Edition input revision/hash, original SHA, native validation ID, certificate ID,
province/year/month/product/profile, method/coverage/policy versions. Both
`acknowledge_unverified_period` and `acknowledge_limited_coverage` must be true.
They acknowledge limitations and do not replace independent byte verification.

Backend verifies the JWT Actor, SQL reauthorizes Admin. Before a new activation
or replacement, an isolated credential-free RO/network-none verifier reopens the
original, recomputes A4.1 artifacts and compares actual immutable TIFF/JSON bytes.
It reopens the prepared TIFF for image pixels/mask/CRS/bounds. The host checks
candidate/metadata/identity and reads SHA/size again. The storage lock covers
proof through SQL commit. SQL locks Dataset → sorted Editions → relevant Jobs;
pointer, acceptance, audit and receipt commit atomically with revision CAS.

One existing Dataset active pointer is reused. Replacement keeps the previous
Edition draft and eligible for rollback. Rollback requires prior publication
history and fresh verification. Explicit withdrawal is terminal and preserves
files/history. It may replace an active Edition with a freshly verified Edition,
or explicitly set no-active. An inactive withdrawal preserves another active
Edition. Broken/revoked active data can be retired without its broken files;
replacement always needs fresh verification.

Historical receipt replay returns operation history without rewriting its old
pointer. The UI reloads current catalog/Published data after any successful call.
Upload, validation, prepare and verification never activate automatically.

## SQL/permissions boundary

Forward migration042 only. It adds immutable, owner-only FORCE RLS policy
acceptance bound to the exact certificate and full lineage/artifact identity.
Service-only RPCs expose command/status/published read/unavailable notification;
no worker/browser/direct table privileges are added. The trusted Backend supplies
native proof; HTTP input cannot supply Actor, paths or proof.

Four narrowly scoped replacements extend eligibility, publication readiness,
Dataset pointer guard and GeoTIFF catalog guard. LDD branches are preserved.
GeoTIFF remains draft with validated_result_id NULL; current native validation
lineage is separate. Withdrawal requires trusted GeoTIFF publication audit history.
Neither broad database activation_enabled nor backend sandbox gate is opened.
Only the attested Local operator injects a private GeoTIFF provider/capability.

Revocation immediately makes a source unservable; the active pointer stays as
history until Admin retires/replaces it. Ordinary catalog metadata updates can
fail closed while such an unavailable pointer remains. No automatic fallback,
pointer rewrite, cache clearing or physical deletion occurs.

## Published reader and browser

Signed-in readers GET `/gis/published-geotiff` with required province, data_year,
month, product and coverage_mode=`source_footprint_intersection`. Unknown extra
fields are rejected. One active Edition must match the exact Dataset identity.
No active source returns 404; stale/revoked/broken source returns an explicit error.
Temporary verifier startup/resource/timeout failures or undifferentiated native
failures return503 without durable certificate revocation. Established host
source/artifact hash, size or lineage corruption returns409 and revokes the
certificate. Both paths clear Published UI and never fall back to Legacy.

Every read recomputes original/output bytes and checks SQL snapshot again before
responding. Snapshot binds SourceIdentity, input revision/hash, certificate,
artifact hashes, method, product/period and Dataset revision. Even cache hits
perform fresh byte verification. The new cache holds at most32 summary projections
for60s and shares no legacy keyspace. HTTP uses no-store/no-cache.

One bounded response supplies raster image, bounds, legend, summary, identity and
warnings. PNG is a display-only Web Mercator nearest sample of at most64×64 actual prepared pixels,
NoData transparent; it is not a full-resolution tile service. The native child
warps values and masks on the same bounded EPSG:3857 display grid; immutable
scientific TIFF, source grid and full-pixel summary stay byte-identical.
`geotiff-mercator-nearest-v1` plus PNG SHA, bounds, transform and dimensions
are bound to the render snapshot; `catalog_snapshot_id` remains the independent
SQL expected-snapshot check. Bitmap uses Cartesian texture coordinates without
a second longitude/latitude GPU transformation. Image/DTO response
is limited to256KiB. No full scientific arrays enter the browser. The palette
matches the native image: red→olive→green, NDVI[-1,1] or LST[-100,100] Celsius.
Existing prepare cap is1,000,000 pixels; this is an admission limit, not a new
province-capacity or throughput claim.

Dashboard Published mode displays only that snapshot's raster/legend/summary.
Its province/product/period controls are independent of legacy sidebar selection;
legacy analytical controls/layers are hidden in this explicit mode, their data
and state are preserved when returning to Legacy. Source/scope changes, refresh,
errors and hidden tabs clear Published imagery. Visible pages recheck every10s,
on focus and publication events. Responses are as-of snapshots, not instantaneous
multi-client push. No unsupported district statistics are inferred.

## Local execution

Use the owned T0 core and independently reviewed042 applied to both approved DBs.
The operator requires the external pre-A4.2 baseline and exact identity/ledger
proof, never production dotenv. `geotiff_publication_checks.py` creates fresh
synthetic rows/files, runs actual Auth/API/Linux/browser, faults only run-owned
objects while retaining originals, and stops owned services on completion.
`a42_demo.py --runtime-dir <owned-local-root>` starts the manual Local demo;
password input is private. Runtime evidence belongs outside Git.
