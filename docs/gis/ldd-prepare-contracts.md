# A2 — Local LDD Prepare and Preview

Scope: Local Sandbox only. A2 does not publish, activate, withdraw, roll back,
change Dashboard readers, mutate legacy caches, or call GEE/Cloud.

## States and authority

Uploaded is an immutable ZIP association. Validated is an accepted native upload
validation Result for the Edition's current input revision/hash. Prepared is a
successful `prepare_ldd_edition` job with two physical staged files; it is **not
ready**. Verified means the private Backend verifier independently reopened the
original and recomputed/compared every output byte before certification.

Migration 038 adds request/certificate/revocation rows beside the existing 037
artifact registry. Registry declarations stay unverified; readiness requires the
separate current certificate, both artifact references, current accepted input
lineage, and no revocation. Native V1/V2 validation and other queues remain
separate. Preparing does not change the Edition validation state or pointer.

Only the trusted Local application factory injects a verifier callable. HTTP
input cannot select a path, URL, command, SQL, actor, proof or `ready` flag.
Browser Admin/Officer JWTs cannot call service-only certification RPC directly.
The subject-bound least-privilege Worker cannot certify or activate.

## Artifact method

`ldd-source-area-v1` creates canonical UTF-8 JSON:

- `ldd_geometry`: GeoJSON FeatureCollection, EPSG:4326, all accepted source
  features; original LU_CODE, LUL1_CODE, Shape_Area retained. No clipping or
  simplification. Reprojection is for display.
- `ldd_summary`: feature count, total Shape_Area, area by original raw LU_CODE
  and existing main-class classifier; square metres. Composite codes remain
  whole buckets rather than fabricated sub-code area shares.

Both embed Dataset/Edition/Validation Result IDs, input revision/hash, original
SHA256, province/year/month=0, method, boundary/legend hashes and warnings.
The native validator already checks declared area against projected geometry;
this method deliberately sums the validated declared Shape_Area once per feature.
It does not change the legacy LDD calculation method.

Coverage means `validated_source_footprint`: all source features pass the existing
approximate buffered province boundary. It does **not** certify an authoritative
provincial inventory, official source year, clipping accuracy or complete national
LDD legend. `complete_province_inventory=false` is mandatory. Unknown codes fail
review; the supported legend currently has 96 codes. Official licensed files
require separate acceptance.

## Files and runtime boundaries

Existing immutable ZIPs remain in the owned Local LDD store. Worker writes only
`ldd-prepared/staging/<job UUID>-<attempt>/geometry.json` and `summary.json`.
The host verifier promotes content-addressed `objects/<SHA256>.json` exclusively,
with fsync, existing-byte comparison and no overwrite. DB failure can leave
unreferenced immutable bytes counted against quota; no automatic deletion occurs.

Prepare daemon reuses polling, signals, heartbeat, 60-second lease, three-attempt
budget, natural-expiry recovery, trusted JWT subject and stale-token fencing.
Queue concurrency remains one. Existing validation workers cannot claim/recover
Prepare jobs. Explicit retry is allowed once after eligible transient failure;
invalid-data failure is terminal. No automatic activation.

Worker container is the existing pinned Linux image, nonroot, root RO, capabilities
dropped, 1 GiB memory/swap, 1 CPU, 64 PIDs, internal network only. Native child has
no DB/Auth credentials, 512 MiB address-space, CPU 20s, wall 25s, 64 FDs and no core
dump. Output files max20 MiB each; parent report max16 KiB. Certification checks
objects plus staging against a256 MiB/4096-entry threshold; the producer checks
staging separately before writing. This is a **soft pre-write accounting limit**,
not an atomic combined filesystem quota: concurrent/stale producers can race those
scans. New certification fails507 above the threshold, with no false readiness.
There is no proven absolute disk bound from these bind mounts. Strict disk quota
or reservations remain future capacity work. Existing input guards are unchanged.

Independent verifier is a one-shot container with the same restrictions but
`network=none`, all binds RO and **no credential bootstrap**. It recomputes every
expected byte from the original source, then the host rereads staged bytes and
checks SHA256/size before promotion. No Worker writes immutable objects.

## HTTP and UI

All four endpoints require verified existing Auth and GIS capability:

| Route suffix under `/gis/editions/{id}` | Request |
| --- | --- |
| POST `/prepare-jobs` | expected_dataset_revision, expected_input_revision, input_hash, province, data_year |
| POST `/prepare-retry` | same scope + job_id, reason |
| POST `/prepare-verification` | job_id only; Idempotency-Key required |
| GET `/prepared` | no client proof; actual current source/output SHA/size check |

Prepare commands use existing receipts, audit and row locks. The API hides private
native packets and paths. The preview panel is inside the existing Edition card,
with existing confirmation/idempotency flow. It shows job/attempts and explicit
Local Preview warnings, geometry and source-area summary. Failed rechecks clear
old ready geometry. No activation controls are added.

Browser geometry is bounded to200 features/20000 coordinate pairs, preserving
whole selected features, polygon holes and aspect ratio. Stored/verified geometry
remains complete; truncation is labelled. SVG preview uses no external map service.

## Readiness, revocation and the A3 boundary

Every HTTP readiness/Preview read reopens the original and output files, verifying
actual SHA256 and size. Missing or corrupt bytes suppress geometry/summary and
append a durable certificate revocation. No stale ready data is returned.

SQL `publication_ready` proves a current DB certificate, **not live filesystem
availability**. A3 must perform fresh trusted byte verification immediately before
publication and retain the 037 pointer/revision/transaction guard; it must not
activate based on that SQL Boolean alone. Activation Gate remains false in A2.

Revocation is deliberately permanent. Current successful-job dedup and certificate
uniqueness do not provide rebuild/re-certification of a revoked Edition; an
explicit future repair contract is needed. Physical/source bytes are retained.
Do not claim that restoring a corrupt file automatically makes it ready again.

## Repeatable Local verification

Use the existing project's isolated Python environment and Docker Desktop.
`ldd_prepare_local.py proof --runtime-dir <owned T0 directory>` verifies Local
identity, frozen migrations and closed gates. Migration action requires the exact
independent review checksum and never overwrites a mismatched ledger.

`ldd_prepare_checks.py --runtime-dir <owned T0 directory> --node-modules <existing
Playwright modules> --large-fixture <explicit synthetic ZIP>` runs real local
Auth/HTTP/queue/native files/browser checks, no migrations. It starts only LDD
validation and Prepare workers, within the unchanged maximum of four approved
containers including the verifier. Test users/rows/files are retained; only exact
owned processes/containers are stopped. Credentials remain in memory/private
stdin. External evidence belongs outside Git.

The optional recovery fixture must be independently identified as synthetic:
1500 copies of a known 1600m² test polygon, expected total2400000m². Overlaps are
intentional test data, not a meaningful land-use estimate or a capacity guarantee.
Use the manifest SHA256 and retain the original small3-feature/6400m² fixture.

Use `dev/gis_ui/vite.config.mjs` for Local tests/build so repository `.env` files
are not loaded. The original seven-day T0 development keys can expire; renewal is
an explicitly reviewed Local maintenance operation, never a reason to weaken JWT
checks, give a Worker service privileges or change production credentials.

For an interactive A2-only demo, use the existing Python environment:
`python -I -B dev/gis_ui/a2_demo.py --runtime-dir <owned T0 directory>`.
It reuses the existing hidden-password prompt and fresh Local demo accounts.
The user must run it in an interactive terminal. Visit
`http://127.0.0.1:3000/?view=gis`; Ctrl+C stops only owned API/UI/workers and retains
data/core volumes. This focused launcher runs LDD validation and Prepare only;
GeoTIFF/offline-synthetic queue workers are not launched. Their existing APIs and
the original full demo launcher are unchanged. No old user/password is overwritten.
