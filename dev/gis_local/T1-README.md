# T1 Local Database Foundation

This harness targets only the exact T0-owned Docker Desktop Linux container.
It never takes a database URL, reads `.env`, or imports the application. No paid
service, Cloud account, Prisma, Python database package or new image is required.
Use Python 3.11+; this execution used host Python 3.12. Container PostgreSQL is 17.6.

## Existing runtime after T1

All commands run from the repository root, on `feature/gis-data-management`.
Set `$gisRuntime` to the T0 runtime folder containing its **nonsecret** `owner.json`.
Do not open `runtime.env` or `kong.yml`, and do not copy credentials into commands.

```powershell
python -I -B dev/gis_local/t1_database.py resume --runtime-dir $gisRuntime
python -I -B dev/gis_local/t1_database.py proof --runtime-dir $gisRuntime
python -I -B dev/gis_local/t1_database.py migrate --runtime-dir $gisRuntime --review dev/gis_local/t1-review.json
python -I -B dev/gis_local/tests/t1_cases.py --runtime-dir $gisRuntime
python -I -B dev/gis_local/tests/t1_cases.py --runtime-dir $gisRuntime --supplemental-only
python -I -B dev/gis_local/t1_database.py stop --runtime-dir $gisRuntime
```

`migrate` checks the independent review and applied checksums, then skips already
applied versions. It does not replay old migrations. Each new migration's exact
reviewed bytes and its ledger insertion commit in the same transaction.

T0 `manage.py verify/start` deliberately expects no application schema and is no
longer the T1 readiness command. `resume` starts only retained, verified containers
and uses a stage-aware marker check; it does not rebuild/reconfigure/read env files.
Stopping retains both volumes, both databases, and synthetic evidence. No automatic
drop/reset/cleanup is provided.

## Fresh preparation boundary

`baseline` is **one-time only**: checks zero public application tables, zero Auth
users, no legacy profile functions/trigger and no GIS schema. It wraps original
000–026 in one transaction without modifying source bytes. Historical standalone
outer BEGIN/COMMIT lines are adapted in memory; PL/pgSQL BEGIN blocks are retained.
Existing baselines, partial/unknown checkpoints and source checksum drift fail
closed. Do not remove a checkpoint to force a replay.

`clone-empty` creates `gis_t1_upgrade` with `template0`, then copies only the empty
local vendor `auth` schema, without rows/owners/ACLs. It grants only the app-required
Auth schema usage and uid/role/jwt function execution. This secondary database is
not an equivalent full Supabase Auth deployment. An existing target is refused.
`restore-empty` is explicit recovery for an instance-marked, still completely
uninitialised target only; it cannot overwrite a restored schema or populated DB.

The primary `postgres` database retains the original vendor Auth schema. Both
targets live inside the same T0 container; DB names are hard allowlisted and a
host/database URL cannot be supplied. Before writes, checks bind the Docker daemon,
container ID/images/labels/limits/mounts/networks, instance, cluster, database,
baseline fingerprint and GIS marker. GIS is not wired into legacy runtime APIs.

## SQL contracts implemented

Private schema `gis` tables: `environment`, `schema_migrations`, `synthetic_fixtures`,
`datasets`, `editions`, `officers`, `jobs`, `attempts`, `results`, `audit`, `receipts`.
These short internal names implement the T0 dataset/edition/job/attempt/result/
officer-grant concepts; legacy tables and `profiles.role=user/admin` stay intact.

Public wrappers (JSON return values, **not HTTP endpoints**):

| Function | Caller | Contract |
|---|---|---|
| `gis_command(actor,request_id,operation,payload,backend_sandbox=false)` | service_role | `{status,body}`; create/edit dataset or draft, clone, enqueue/retry, grant/revoke, activate/rollback/withdraw |
| `gis_read(actor,kind,payload={})` | service_role | me, provinces, fixtures, datasets/editions/jobs/detail, attempts/history/officers |
| `gis_worker(action,payload={})` | gis_worker | claim, heartbeat, complete, fail, recover |

Explicit `actor` is **backend-attested**, not browser supplied. T2 must verify the
user JWT and obtain actor from that context. Service-role identity itself is not
the user's `auth.uid()`. SQL checks the live profile/officer grant on every call,
including receipt replay. No ordinary client can execute service wrappers. T1
does not implement HTTP authentication/JWT verification.

Receipt uniqueness is `(actor_id,request_id)`, matching the same-actor replay
contract; it is not a globally unique cross-user idempotency key. Actor deletion
sets relational IDs NULL; deleted actors cannot authorize or replay. Snapshot
responses exclude actor UUID copies. Reasons/titles remain user text: callers must
not submit PII/secrets there. No claim of automatic free-text anonymisation is made.

Dataset identity: `(province,data_year,month,kind,purpose)` referencing existing
province English keys (e.g. `Bangkok Metropolis`). Edition review states are draft,
validating, validated, withdrawn. Active is derived from a composite FK pointer.
Draft edits increment input revision; validated inputs are immutable. Deferred
constraint triggers validate final queue/result/attempt/pointer consistency across
the whole transaction. Historical result/audit/receipt rows cannot be rewritten.
Only FK-driven actor/subject nulling is allowed for account deletion.

Source manifests are bounded, strict-key metadata. The allowlisted synthetic
fixtures are **SQL protocol fixtures**: their declared hash/size describe fixture
identifiers, not actual Shapefile/GeoTIFF bytes or the L1–L4 scientific datasets.
Real metadata may stay draft only. No file validation or scientific computation
is claimed by a SQL successful job.

Queue defaults: one concurrent running job, 60s lease, up to three attempts, 5/20s
retry backoff plus bounded 0–2s jitter, one explicit retry child (six total attempts
per unchanged fingerprint). Claim uses SKIP LOCKED and a single-claim advisory
gate. Completion/recovery lock edition before job; heartbeat locks job only and
checks `clock_timestamp()` after the lock. Random unique lease tokens fence stale
attempts. Workers cannot submit, grant or activate. Sandbox activation needs both
the backend flag and database gate, and never changes GEE assets/analysis/cache.

`gis_worker` is a NOLOGIN group role. Tests use SET ROLE, not a real worker login.
T3 must provision a narrowly scoped local execution identity separately, without
a service-role key. A native worker/process/GIS validator is outside T1.

## Tests and evidence

Pure checks: `python -I -B -m unittest discover -s dev/gis_local/tests -p 'test_*.py'`.
On restricted Windows environments choose a writable temporary directory first.
SQL suites store secret-free JSON in `$gisRuntime/t1/`. Tests use synthetic users,
roll back individual fixtures, and explicitly force deferred constraints before
rollback. Concurrency/lease-wait fixtures commit and are **retained**, with their
jobs finished through the queue protocol. They do not delete preexisting data.

`t1_preservation.py` records legacy table hashes, columns, constraints, indexes,
profile functions, Auth trigger and RLS flags before/after migration. The intended
new SELECT policies/column privileges for `gis_owner` on profiles/provinces are
documented additions. No legacy function/cache update is introduced.

Still required in T2/T3: authenticated HTTP E2E; stable result/report read DTO;
bounded officer-list pagination; error-to-HTTP mapping; concrete worker login and
actual process termination/restart; native file/GIS validation and resource bounds.
No Cloud/production approval is implied by these local tests.
