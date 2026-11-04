# A6.3 — Local Mocked End-to-End Integration

Status: **PASS — Local Synthetic / Mock-only**, 2026-11-04.
Branch: `feature/gis-data-management`.
A6.2 base: `6eb58400f6b1b9e2e1a739fb1087b0dc63cb8fc9`.
One Local Commit after acceptance; final response supplies its SHA.
No push, merge, PR, deployment or A6.4–A6.6 execution.

## Implemented path and contracts

Authenticated loopback FastAPI → existing043 queue → existing Linux daemon loop
→ isolated mock child → A6.1 injected adapter → immutable A6.2 candidate →
authorized status/attempt/history reads.

- Four opt-in routes under `/gis/mock-gee`: options, create job, status and history.
  They are disabled without an explicitly injected server-side catalog. Both
  backend and database broad activation gates must remain false. The request
  accepts only `mode=gee_contract_mock`, a fixed case key and an idempotency key.
  No caller-supplied oracle, geometry, worker identity, path, command or live mode.
- The trusted operator registers ten fixed synthetic cases. The real worker
  computes their outputs again; API clients never register expected outputs.
- `MockWorker` subclasses `GisWorker` and inherits its polling, process execution,
  signal handling, bounded output, heartbeat and shutdown behavior. `MockClient`
  uses real Auth-issued `gis_gee_mock_worker` JWTs and only two existing RPCs.
  Native transport keeps its original role and Offline behavior is unchanged.
- Child input excludes JWTs and lease tokens. Child limits: 512MiB address space,
  20 CPU seconds, 64 file descriptors, 64KiB input and 16KiB output. Child guards
  deny sockets/DNS/UDP, subprocesses, credential filenames and Google/EE/startup
  imports. Trusted synthetic code is fixed, not a general untrusted-code executor.
- Existing043 SQL remains authoritative for JWT identity, protocol isolation,
  report/oracle agreement, revision/hash, fencing, immutable candidate invariants,
  retry/backoff and recovery. No SQL/schema/ledger changes or migrations run.
- All candidates remain `execution=mock`, `synthetic=true`, `publishable=false`.
  NDVI/LST use four artificial pixels and the existing Offline/legacy AST method
  checks. Fake scene IDs explicitly contain `A63_SYNTHETIC`. Monthly fixtures are
  synthetic templates; this does not prove real spatial/temporal satellite parity.

## Runtime preparation approved by user

Original Linux image lacked Pydantic. User approved the separate derived-image
option; Repository dependencies and original image were not changed.

- Base retained: `sha256:fca4560d8a0d0198c0eb75fbf6598314cd8ed4a5e8bafa00e1d7298126aa04c9`.
- Added image: `sha256:7557955c9e2c8611ea1396ddef6d8629c2ee1e7f193e85f0c65bcf5db9566674`.
- Python3.11.17/Linux amd64; Pydantic2.13.4 and pydantic-core2.46.4.
  Exactly five wheels match existing requirements versions/SHA256s; public PyPI
  download occurred on the host, outside Git. Image installation used local wheels,
  no index/dependency resolution and build network disabled.
- First BuildKit attempt interpreted `FROM sha256:<id>` as a registry name and
  attempted DockerHub metadata/anonymous-token resolution, then failed. Corrected
  to the verified existing local tag with classic builder, `--pull=false` and
  `--network=none`. No GEE/Google requests or worker external network were enabled.
- Worker image policy is a separate exact-image/command/label opt-in. Existing
  default/Native policies remain strict. Non-root65534, read-only root and exact
  source mounts, internal-only network, no published ports, CPU1/1GiB/PIDs64,
  capabilities dropped and no-new-privileges. No Home, `.env` or credential mounts.
- The lock identifies the exact tested local build, not a portable published image.
  Rebuilding on another machine needs separate image verification/policy review.

## Files

Modified four existing files: `dev/gis_local/manage.py`, backend `gis_app.py`,
`gis_runtime.py`, `gis_worker/worker.py`.

Added backend: `gis_gee_mock.py`, `routers/gee_mock.py`,
`gis_worker/gee_mock_worker.py`, `gee_mock_child.py`, `gee_mock_fixtures.py`,
`tests/test_gee_mock_api.py`, `tests/test_gee_mock_daemon.py`.

Added local tooling: `dev/gis_local/gee_mock_e2e.py`, `gee_mock.Dockerfile`,
`gee-mock-image.lock.json`, `tests/test_gee_mock_worker_guard.py`, and this handoff.
No frontend, dependency lockfile, legacy scientific formula or migration edits.

## Actual tests and independent review

| Evidence | Result and boundary |
|---|---|
| Focused Windows units/mock API/Native+Offline+Publication+Guard regression | **524 passed +24 subtests** |
| Linux/Python3.11 adapter/contract/fixture/scientific regression, network=none | **207 passed** |
| Real loopback HTTP/Auth/PostgREST + Linux daemon/child E2E | **40/40 passed** |
| Read-only preservation/ledger/RLS/ACL checks, both local databases | **25/25 passed** |

Actual process E2E proves annual/monthly NDVI and LST, two concurrent daemons with
one claim, duplicate requests/acknowledgements, NoData/all-masked/partial failures,
retry/backoff/exhaustion, long-child heartbeat, real container SIGKILL, real lease
expiry/replacement recovery, stale completion fencing and clean idle SIGTERM.
No test shortened leases or edited queue state. Every E2E source hash remained
unchanged throughout execution. Unit/Linux reports have source fingerprints too.

Existing A6.2 real JWT/negative ACL/RLS, immutability, publication-rejection and
SQL forgery evidence remains applicable: all four integration source fingerprints
and reviewed043 SHA match; it was not presented as a newly rerun suite.

Independent reviewer `a63_security_review` inspected exact source and evidence,
without running tests or accessing Docker/databases. Closed findings: database
gate check, child UDP/process escape and partial-start container cleanup. Final
review found no remaining must-fix/High/Critical issue in the A6.3 scope.

Earlier checks: strict test runner initially blocked synthetic `.env` creation and
lacked a synthetic home path; only the external test runner was corrected. The
first preservation checker used a mistyped evidence filename; corrected read-only
rerun passed. No application or SQL relaxation was used to make tests pass.

Raw evidence is outside Git under the existing visualization root:

- `a6-3-e2e/focused-50adcce5.{log,xml}` and source/result JSON.
- `a6-3-e2e/linux-units.log`, `linux-units-result.json`.
- `t0-local-supabase-20261027-v2/a6-3-gee-e2e/e2e-d1e27625a7ce.{json,jsonl}`
  and `e2e-d1e27625a7ce.source.json`.
- `a6-3-e2e/before.json`, `source-before.json`, `preservation-final.json`,
  final review/commit audit records. Wheels/build output are external too.

## Preservation, cleanup and remaining boundaries

- Both databases preserve every original GIS row/history/artifact/pointer, all
  previous ledger rows/timestamps and original profiles. Legacy table hashes match.
  Worker DB had3 NDVI annual rows,3 LST annual rows and3 Saved Areas before the
  actual E2E; their hashes are unchanged. Upgrade cache rows are unchanged too.
- Of262 pre-existing source/evidence files, only the four approved Python files
  changed. Migrations000–043 and the five original untracked evidence files retain
  baseline hashes. Representative publication function bodies still match SQL.
- Broad activation gates stay closed, both queues are idle. New synthetic test
  users/cases/jobs/results/history remain for inspection; no old data was deleted.
- All owned test worker/probe containers were removed and test API stopped. Core
  containers/volumes, old image and new image remain. No existing volume removed.
- Not newly tested: SIGINT, forced OOM/timeout injection for this mock child,
  browser/UI (no frontend changed), genuine satellite observations/liveGEE,
  Cloud IAM/Quota/Billing or production. Resource configuration/guards were tested;
  inherited older lifecycle evidence is not a fresh mock-specific fault injection.
- Ready to propose A6.4 after separate approval. Do not convert this mock oracle
  into a live-result trust boundary or enable Google credentials/network implicitly.
