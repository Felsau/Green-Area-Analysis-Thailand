# T2 GIS Backend APIs — local runbook

Run from the repository root using the existing backend virtual environment.
No package installation, original `.env`, GEE credential or Cloud service is
required. The only enabled T2 target is the attested T0 local sandbox.

```powershell
$gisRuntime = 'C:\Users\chaya\.codex\visualizations\2026\10\04\01a107d9-ff44-7731-8bc3-91814ffd8d51\t0-local-supabase-20261027-v2'
& green-area-backend/.venv/Scripts/python.exe -I -B dev/gis_local/t2_local.py resume --runtime-dir $gisRuntime
& green-area-backend/.venv/Scripts/python.exe -I -B dev/gis_local/t2_local.py migrate --runtime-dir $gisRuntime --review dev/gis_local/t2-review.json
& green-area-backend/.venv/Scripts/python.exe -I -B dev/gis_local/t2_local.py serve --runtime-dir $gisRuntime
```

The server binds only `127.0.0.1:55422`. Stop its terminal process before stopping
the local stack. No worker starts; enqueue returns an actual queued SQL record.
Normal `main.py` mounts GIS disabled. Setting an ambient GIS environment variable
alone cannot enable this local-only runtime or select a different database.

The runner reads only T0-generated development API keys from the verified local
gateway's generated configuration into process memory after target proof. It does
not read original production `.env`, GEE files or JWT signing secrets. Keys, user
passwords and access/refresh tokens must never be printed or copied into reports.
Use separate Auth and service SDK clients; login clients must not replace the
backend service client's Authorization header.

Auth uses the same Supabase Auth service as the existing system: strict
issuer/audience/time/user-role/sub checks supplement an actual `auth.get_user(jwt)`
verification and UUID match. The SQL actor is bound from that verified user, not
body, role metadata, cookies or `X-Admin-Token`. SQL rechecks live Admin/Officer
permissions, including idempotency replay. Roles remain `profiles.role=user/admin`
plus separate GIS Officer grants. `gis_worker` has no HTTP endpoint.

Every RPC is preceded by a fixed-loopback target check and an independent
service-only database readiness comparison. Client initialization occurs after
proof. Proxy environment and redirects are disabled; timeouts/retries are bounded.
An enabled runtime requires migration30 and matching instance/baseline/DB/cluster.

## HTTP contracts

All paths are under `/gis`, requiring `Authorization: Bearer <user-access-token>`.
Every POST/PATCH also requires one UUID `Idempotency-Key` header. No hard-delete,
upload, cache-clear, GEE ingestion or worker-completion endpoint exists.

| Method | Path | Behavior |
|---|---|---|
| GET | /me | Live capabilities and both server/database activation gates |
| GET | /provinces | Existing province references |
| GET/POST | /datasets | Filtered page / create identity+title |
| GET/PATCH | /datasets/{id} | Detail / title with expected revision |
| GET/POST | /datasets/{id}/editions | Page / metadata draft |
| GET/PATCH | /editions/{id} | Detail / draft metadata with expected revision |
| POST | /editions/{id}/clone | New draft, source revision required |
| POST | /editions/{id}/validation-jobs | Actual queued record, immediate202 |
| GET | /editions/{id}/history | Bounded audit page |
| POST | /datasets/{id}/activation, /rollback | Admin + two sandbox gates + revision/pointer/reason |
| POST | /editions/{id}/withdrawal | Admin + two gates + explicit replacement/null pointer |
| GET | /jobs | Filtered job page |
| GET | /jobs/{id} | Actual state plus stored result or null |
| GET | /jobs/{id}/attempts, /result | Safe attempt page / stored protocol report |
| POST | /jobs/{id}/retry | Current revision/hash + technical retry eligibility/budget |
| GET/POST | /officers | Admin page / grant by subject user UUID |
| POST | /officers/{user_id}/revocation | Admin revoke with reason |

Dataset filters: province/data_year/month/kind/purpose. Jobs also support
dataset_id/edition_id/state. Edition lists support state. Pages default20/max100
and return `{data,next_cursor,has_more}`. The opaque URL-safe base64 cursor encodes
the SQL `(created_at,id)` tuple; it is validated, not an authorization token.

Mutation responses are the sanitized SQL receipt body with its original
200/201/202 status. Receipt replay precedes revision checks, after live permission
checks. Enqueue dedup can return202 while active or200 for an existing terminal
job. Pending jobs have `result:null`; SQL fixture reports are not GIS computation.

Errors are scoped to GIS: `detail:{code,message,fields}`, with401/403/404/409/422/
429/503 as applicable. SQL details, input values, tracebacks, service keys, actor
copies, lease tokens/times and worker identifiers are not returned. GIS429 adds
Retry-After; existing endpoints delegate to their original rate-limit handler.

Input models forbid unknown fields/nonfinite numbers, bound metadata/text and
require explicit nullable activation/withdrawal pointers. GIS body size is limited
to64KiB. CORS allows the two existing local UI origins in the local factory, with
Authorization/Content-Type/Idempotency-Key; no credential cookies or wildcard.
The legacy main retains its original origins and adds only Idempotency-Key.

## Tests

```powershell
& green-area-backend/.venv/Scripts/python.exe -I -B dev/gis_local/t2_checks.py unit --runtime-dir $gisRuntime
& green-area-backend/.venv/Scripts/python.exe -I -B dev/gis_local/t2_checks.py regression --runtime-dir $gisRuntime
& green-area-backend/.venv/Scripts/python.exe -I -B dev/gis_local/t2_integration.py --runtime-dir $gisRuntime
& green-area-backend/.venv/Scripts/python.exe -I -B dev/gis_local/t2_local.py stop --runtime-dir $gisRuntime
```

`t2_checks.py` clears ambient service environment, disables dotenv before legacy
imports and denies non-loopback network. Unit/regression tests are mocks and do
not prove actual Auth/RPC. Windows TestClient requires local socket permission.

Since migration 037 an Edition must be prepared for publication before activation
(`GIS_PUBLICATION_NOT_READY`, HTTP 409). `t2_integration.py` first proves the unprepared
activation is refused, then `prepare_publication()` swaps in a synthetic
`gis.publication_ready` (edition belongs to dataset) for the activation cases and
`restore_publication_ready()` puts the original definition back and checks it byte for
byte (also called from cleanup). Because T2 commits, a killed run can leave the
override (marker `T2_SYNTHETIC_PUBLICATION_READY_OVERRIDE`) installed; the next run
refuses to start, and the original definition is saved as
`$gisRuntime/t2/publication-ready-original-<run>.json`; re-apply it as `gis_owner`
without newline translation (the installed body contains CR/LF; the harness sends it as
hex through `convert_from(decode(...))`).

Integration uses the real local Auth and PostgREST services through the SDK and
FastAPI TestClient (ASGI), not a browser or hosted backend. It must run alone on an
idle synthetic queue with no other producer/worker. Per-run positive fixtures are
bounded to3 new synthetic Auth users,2 datasets,4 editions and4 jobs. Rows are
retained; owned queued jobs are settled through explicit manual SQL fixture calls.
These calls prepare success/failure states for API read/activation/retry tests and
are not a Python worker or API auto-processing. Gates are restored false.

Actual valid Auth-issued JWT and invalid-signature rejection are tested. Altered
issuer/expiry/audience tokens have tampered signatures; valid-signature altered-
claim integration fixtures are explicitly Not Tested because signing secrets are
not read. Claim validation additionally has isolated unit tests. No signing-secret
access or token issuance workaround is permitted.

Secret-free JSON evidence is under `$gisRuntime/t2/`. The repository handoff must
distinguish actual E2E results, mock results, static review and Not Tested items.
All T0/T1 sources and applied migrations stay unchanged. Migration030 is reviewed
and applied forward with its ledger record in one transaction; changed checksums
are refused. No T3–T5, Cloud, deployment or Git publishing is authorized here.
