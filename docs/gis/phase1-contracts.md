# Phase 1 shared contracts — T0 baseline

Contract version: `1.0.0-t0`. Machine-readable counterpart:
`dev/gis_local/contracts.json`. This document freezes the defaults selected from
the reviewed Phase 1 plan; it is **not an API, SQL migration or worker implementation**.
Any semantic change in T1–T4 must update this document, JSON and relevant tests.

## Boundary and identity

- Default `GIS_ENABLED=false`, sandbox activation disabled. T0 starts only vendor
  local infrastructure. No GIS schema/application migrations, uploads or GEE calls.
- Dataset key: `(province, data_year, month, kind, purpose)`. Province references
  existing `public.provinces.name_en`; year is source year in CE (1980 through
  current calendar year + 1), with explicit BE conversion in UI.
- Month `0` means annual, `1..12` monthly. LDD must be annual.
- Allowed pairs: `ldd_shapefile/landuse`, `geotiff/ndvi`, `geotiff/lst`.
  Key fields are immutable after creation. A new edition is not a new dataset.
- Phase 1 uses allowlisted synthetic source manifests. Real metadata may remain
  draft only; it cannot be labelled validated/active from metadata alone.
- Source manifests have schema version, hash/size/provenance, CRS and attributes
  or bands/units/NoData/resolution/data kind. Reject arbitrary remote URLs, paths,
  executable payloads and client-supplied expected scientific results.

## Roles and database boundary

- Preserve `profiles.role=user/admin`. GIS Officer is a separate DB grant, not a
  JWT user-metadata claim or a self-editable profile property.
- Officers/admins read the shared internal catalog, create datasets/drafts,
  clone/edit drafts, enqueue validation and request eligible retries.
- Only admin grants/revokes officer access or activates/withdraws/rolls back the
  **sandbox catalog**, with explicit server/database gates and audit reason.
- Verified JWT determines actor. All SQL mutations recheck effective permission;
  no browser admin token or request-body actor ID.
- Proposed private `gis` schema is not exposed to PostgREST. Backend uses explicit
  service-role-only public RPC wrappers through existing supabase-py.
- Owner is NOLOGIN/non-superuser/NOBYPASSRLS. T1 must review precise column grants,
  owner-only SELECT policies on existing profiles/provinces and inherited grants.
  Worker has a separate execute-only DB role, no service key/direct DML/enqueue/
  activation/grant permissions. Revoke PUBLIC/anon/authenticated execute explicitly.
- New GIS tables/history stay separate from legacy cache. No account deletion
  cascades into shared datasets/jobs/results/audit. Actor FKs SET NULL; grant
  subject can CASCADE. Do not copy actor PII into JSON snapshots.
- Accepted jobs continue safely after requester revoke/delete, without automatic
  activation. Newly revoked users cannot submit/read new GIS operations.

## Edition states and commands

Stored review states: `draft → validating → validated`, or `validating → draft`
on invalid data/terminal failure. `withdrawn` is terminal; reuse via a new clone.
Effective `active` is derived solely from `dataset.active_edition_id`.

- Editing draft increments input revision. Queueing freezes its revision/hash.
- Validation cannot mutate already validated/active inputs; clone first.
- Successful fenced completion reaches validated, never auto-active.
- Composite FK protects pointer from cross-dataset editions. Activation checks
  eligible current validation result/input hash, expected dataset revision/current
  pointer, and sandbox gate in one transaction with audit/receipt.
- Superseded edition remains validated. Rollback selects a previously active,
  still eligible edition through the same guarded transaction. Active withdrawal
  must choose replacement or explicitly clear the pointer. No hard-delete API.
- Phase 1 active does not change the analysis read path or cache version/constants.

## Jobs and worker protocol

States: `queued`, `running`, `succeeded`, `failed`. Only P1 kind:
`validate_synthetic_edition`. One queued/running job per edition.

- Claim via atomic `FOR UPDATE SKIP LOCKED` + update/attempt record; no long SQL
  transaction while native GIS is executing.
- Initial defaults: one concurrent job, 60s lease, heartbeat 15s, 3 attempts/run,
  retry delays 5/20/60s with bounded jitter.
  Attempts include the initial claim: three attempts permit at most two automatic
  retries; the last delay is a configured backoff ceiling, not a fourth execution.
- Functions touching both edition/job lock edition before job. Heartbeat/claim
  only touch job. Recheck wall clock **after lock**, owner/token/status and lease.
- Complete result + terminal job + edition + history/audit atomically. Failed final
  recovery also returns edition from validating to draft atomically.
- Recovery runs independently of browser clients. Old/expired token cannot revive
  a lease or overwrite a replacement attempt. Progress is monotonic per attempt.
- Invalid GIS data is terminal without technical retry. Transient failure may use
  explicit retry if revision/hash are still current and state eligible.
- Fingerprint `(edition,input_revision,input_hash,validator_version)` dedups normal
  submissions. It is not a permanently unique index preventing an approved retry.
  One explicit retry run per original run; no retry chain on the retry child.
  Cap = 2 runs × 3 attempts = 6 attempts for that fingerprint under these defaults.
- Child validation gets allowlisted fixtures and bounded input/output/time, no DB
  secret. Parent controls heartbeat. SIGTERM stops new claims; unfinished work is
  recovered through leases, not falsely marked successful.

## HTTP contract to implement in T2

All routes below are **planned only**, under authenticated `/gis`, with GIS/admin
checks except `/gis/me`, which lets any authenticated user see their own effective
capabilities (possibly empty). No actual endpoints are added by T0.

| Endpoint | Contract |
|---|---|
| `GET /gis/me`, `/gis/provinces` | Effective capabilities/gates; province references |
| `GET/POST /gis/datasets` | Filtered cursor list/create identity+title |
| `GET/PATCH /gis/datasets/{id}` | Detail/edit title with expected revision |
| `GET/POST /gis/datasets/{id}/editions` | List/create draft or clone |
| `GET/PATCH /gis/editions/{id}` | Detail/allowlisted draft input edit |
| `POST /gis/editions/{id}/validation-jobs` | Freeze expected revision; enqueue allowlisted synthetic job |
| `GET /gis/jobs`, `/gis/jobs/{id}`, `/gis/jobs/{id}/attempts` | Safe job status/progress/report/history |
| `POST /gis/jobs/{id}/retry` | Eligible technical retry + expected revision/hash check + reason |
| `GET /gis/editions/{id}/history` | Validation/state/audit cursor history |
| `POST /gis/datasets/{id}/activation`, `/rollback` | Admin + sandbox gate + expected pointer/revision + reason |
| `POST /gis/editions/{id}/withdrawal` | Admin + sandbox gate + reason, expected revision and pointer/replacement |
| `GET/POST /gis/officers`, `POST /gis/officers/{id}/revocation` | Admin-only grants by user UUID, not a public user directory |

- UUID identifiers; UTC ISO timestamps. Pagination default20/max100, stable
  `(created_at,id)` cursor; response `{data,next_cursor,has_more}`.
- Every POST/PATCH carries `Idempotency-Key` UUID. Same actor/operation/payload
  returns stored status/sanitized response; different use of key gives409.
  Replay receipt before repeating stale-revision checks, but still recheck access.
- New/active dedup job →202; semantic dedup terminal job →200; create →201.
  Receipt replay returns the original HTTP status/body; then GET current job state.
- 401 authentication,403 authorization,404 missing,409 state/revision/idempotency,
  422 validation,429 rate limit,503 target/schema/provider unavailable.
- Errors: `detail:{code,message,fields}`; client also handles FastAPI422 arrays.
  Body forbids unknown/actor/worker result/state fields and nonfinite JSON numbers.
- Expected revision is in body; no ETag/If-Match requirement. T2 must add the
  `Idempotency-Key` CORS header without widening origins or legacy contracts.
- No upload/ingestion/cache-clear/hard-delete endpoints in P1. Worker SQL functions
  are not public browser endpoints.

## Atomicity, UI and next-stage checks

DDL + new migration ledger/checksum commit together. Never replay legacy 007/018/
019/022 to upgrade an existing database. Proposed027–029 are not created in T0.
Before T1 add a versioned database identity/schema proof to the T0 runtime marker
checks, rather than weakening the T0 check for the GIS schema and known application tables.

GIS UI is a lazy App sibling of Dashboard under existing auth/recovery gates.
`VITE_GIS_SANDBOX_ONLY` defaults false; approved sandbox mode chooses GIS **before**
mounting Dashboard and does not fall back to analysis when permission/target fails.
No new router library/deep links/analysis sidebar tab. Reuse tokens/components.
App-level draft memory is keyed by identity; clear on intentional signout/account
change, never restore another user's draft. Poll3–5s/backoff/unmount/terminal stop;
show synthetic/sandbox and attempt numbers accurately.

Local core readiness in T0 is not proof of actual user Auth/RPC/RLS/GIS behavior.
T1–T5 must test the real implementation and complete independent SQL/security
review. No new cloud resources, GCS/Redis/Celery/paid worker are prerequisites for
local development. No production or GEE integration is authorized by this contract.
