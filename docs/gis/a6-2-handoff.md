# A6.2 — Internal mock queue and candidate foundation

Status: **PASS, Local Mock-only**. Date: 2026-11-04.
Branch: `feature/gis-data-management`.
A6.1 base commit: `4c24a2fb6d73062d2a7d90a741485481d859f7db`.
One A6.2 local commit is authorized after acceptance; final message supplies SHA.
No push, merge, PR, deployment or A6.3–A6.6 execution.

## Implementation and actual scope

- Migration043 adds protocol `gee_contract_mock` to the **existing** GIS Queue,
  Job/Attempt/Result/Audit/Receipt system. It extends the current041 queue body;
  old protocol arms, edition→job lock ordering, global one-running-job guard,
  60-second lease, heartbeat, retry/backoff and recovery remain intact.
- Three owner-only forced-RLS append-only tables: `gee_mock_cases` (approved
  synthetic oracle), `gee_mock_requests` (catalog/job linkage), `gee_candidates`
  (immutable result/attempt/provenance linkage). No second queue, active pointer
  or publication system is created.
- A6.1 future `live_gee` requests are used only inside this explicitly mock protocol.
  Outputs remain `execution=mock`, `synthetic=true`, `publishable=false`,
  `endpoint_parity=summary_only`. Actual Google/Live execution stays disabled.
- External FastAPI processing model/routes and existing `LiveGeeAdapter` stub are
  unchanged. No public HTTP job creation path is opened for live processing.
- `MockQueueHooks` supplies injected readiness/claim/heartbeat/complete/recovery
  RPC hooks only. No daemon, native child, worker container, Google client,
  credentials or external network configuration is added.

Files added:

1. `green-area-backend/migrations/043_gis_gee_mock_candidates.sql`
2. `green-area-backend/gis_worker/gee_mock_queue.py`
3. `green-area-backend/tests/test_gee_mock_queue.py`
4. `dev/gis_local/gee_mock_local.py`
5. `dev/gis_local/gee_mock_checks.py`
6. `dev/gis_local/gee-mock-review.json`
7. This handoff.

## Authority, identity and integrity

- Dedicated `gis_gee_mock_worker`: NOLOGIN, NOINHERIT, no superuser/bypass-RLS/DDL
  capabilities or inherited application roles. Only PostgREST authenticator can
  select the worker role for actual Auth-issued JWTs.
- Worker may execute only two non-trigger public RPCs: mock readiness/worker.
  It cannot call service/Admin/old-native/offline RPCs or access private tables or
  write Legacy cache. Original Native Worker permissions are not expanded.
- SQL derives worker subject from the trusted session role/JWT context and fixed
  Local issuer. Payload actor/worker identity is rejected. Backend create/read RPCs
  are service-only; trusted actor forwarding reuses existing GIS authorization.
- Only the attested fixture operator can register private cases, after A6.1
  `LiveRequest`, `ComputeOutput`, geometry and canonical hash validation.
  There is no client/service/worker registration RPC. SQL checks parsed canonical
  documents and hashes; worker report must match the frozen expected output exactly.
- The registry is a synthetic test oracle, **not** a generic validator/certificate
  for arbitrary real satellite output. Hashes establish identity, not authenticity.
- Three separate hashes: scientific semantic request; Edition manifest input;
  A6.1 JSON candidate output. The latter is not a Raster/GeoTIFF checksum.
- Candidate binds request/job/dataset/edition/result/attempt, revision/hash,
  scientific method/source hashes, province/geometry, period, scenes, processing
  parameters/units/completeness, JWT worker and fenced completion token.
- Deferred invariants enforce candidate/result/attempt agreement. Candidates never
  set validated_result_id or become eligible/publishable; Edition returns draft.
  Missing/partial/no-data outcomes retain attempt reports and fail without candidate.
- Same completed worker/token/report may replay its acknowledgement idempotently;
  no new result/candidate/audit is committed. Previous-attempt tokens are rejected.
  A new create idempotency key cannot reset a case's three-attempt retry budget.

## Migration and review

043 SHA256:
`cc8d9fe7bd7163dd307a2f944614116bccd6460a50314d108cecc242320563b1`

Independent reviewer `a62_sql_security_review`: PASS before any DDL probe/apply,
and PASS again against final source and actual test evidence. No High/Critical or
must-fix findings remain. Exact reviewed SQL and two security-sensitive Python
hashes are in `dev/gis_local/gee-mock-review.json`.

The review found the operator initially accepted an empty Python review mapping;
fixed before applying. The first rollback probe found a CASE-parenthesis syntax
error; corrected and independently re-reviewed, then rollback probes passed in
both databases. Only then was043 applied once to `postgres` and `gis_t1_upgrade`.
No applied migration was edited/replayed and no old ledger row was updated.

Target proof verifies original Docker ownership/full container identity, healthy
Local core, cluster/database/runtime marker, baseline fingerprint, closed broad
gate and all applied file/ledger checksums. Mismatch fails closed before DDL.
No Cloud URL, production configuration, Google credential or ambient `.env` is used.

## Actual verification

| Evidence | Result / boundary |
|---|---|
| New mock protocol tests | 20 passed |
| A6.1 contract/adapter regression | 129 passed |
| Existing offline provider/API regression | 84 passed |
| Publication unit + LDD/GeoTIFF API regression | 79 passed |
| Total focused unit/mock API suites | **312 passed**, no failures/errors/skips |
| Local Auth/PostgREST/SQL/RPC integration | **57/57 passed** |
| Read-only preservation checks | **21/21 passed** |

Integration uses actual GoTrue-issued worker JWTs and SQL transactions. Covered:
role separation/negative ACL, forced RLS, payload spoofing, wrong input/semantic
hash/revision/protocol, forged live/scientific result, concurrent claim/completion,
heartbeat, real60-second lease expiry and replacement recovery, stale completion,
three-attempt retry exhaustion, immutable candidates and activation rejection.
The old offline worker RPC still commits the unchanged synthetic NDVI result0.1614.

No SQL shortened a lease or skipped backoff. Recovery simulates a client ceasing
heartbeats; no OS worker daemon/process kill is claimed. Queue lifecycle tests run
on `postgres`; the upgrade database covers DDL/ACL/RLS and preservation.

First integration run stopped at a test that incorrectly counted legacy trigger
functions as callable RPCs. Inspection showed only the two approved non-trigger
RPCs; actual HTTP calls to the two trigger names are rejected. Fixed test only,
without changing ACL. A regression runner first blocked Windows asyncio's Local
socketpair (51 setup errors), then an unprivileged run hung. Those owned processes
were stopped; final run permits Windows loopback and blocks external destinations,
credential-file reads and repository test writes. Source/SQL were not weakened.

Raw evidence stays outside Git under the existing visualization/runtime roots:

- `a6-2-queue/focused-b7249e6f.{log,xml}` and corresponding source/result JSON.
- `t0-local-supabase-20261027-v2/a6-2-gee-mock/checks-5f887c34ff55.json`,
  its source JSON and per-check JSONL.
- `a6-2-queue/before.json`, `source-before.json`, `preservation-final.json`.
- Local runtime `a6-2-gee-mock/migration-043.json` and rollback probe record.

Final regression12-file and integration4-file source fingerprints match current
files. Reviewer inspected evidence, not reran tests or connected to databases.

## Preservation and remaining work

- All257 pre-existing Python/SQL/evidence files retain baseline SHA256, including
  migrations000–042, A6.1 implementation and five original untracked evidence files.
- Both databases retain every pre-existing GIS row/history/artifact/pointer and
  old ledger values/timestamps; original profiles and Legacy cache/Saved Areas
  hashes are unchanged. Only new synthetic Auth/catalog/job/audit records remain.
- Worker database already contained3 NDVI annual cache rows,3 LST annual rows and
  3 Saved Areas before testing. Their hashes remain unchanged after success,
  failure, retry and recovery. Upgrade cache rows also remain unchanged.
- Representative original prepare/publication function bodies match their SQL
  source in both databases. Broad activation gate remains false and queue is idle.
- No containers/volumes/artifacts were removed or external services enabled.
  No new dependencies, Google calls, billing/IAM, Cloud or deployment operations.

Not Tested: Linux/Python3.11 execution of new hooks, worker daemon/native process
E2E, browser/UI flow, SIGKILL/OOM/timeout fault injection of a new worker, live GEE
scientific parity, IAM/Quota/Billing or production. Existing A6.1 limitations apply.

Ready to propose **A6.3 Mocked End-to-End** only after separate approval. Future
real outputs require a new trusted bridge/verification protocol and separately
approved Sandbox identity/network/budget. Do not relax this mock oracle or edit043.
