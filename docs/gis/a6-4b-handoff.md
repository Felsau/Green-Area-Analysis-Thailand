# A6.4b — Live GEE Foundation, offline-first

Foundation: **PASS — injected observations only**, 2026-11-04.
Actual Google execution / Live runtime: **BLOCKED, not approved or tested**.
Branch: `feature/gis-data-management`.
Base A6.3: `368127d684cbb95a161ffd55526c64a46d140857`.
One Local Commit after acceptance; final response records its SHA.
No push, merge, PR, deployment, Live Smoke Test or A6.5/A6.6.

## Delivered boundary

- Version2 `gee_live_v2` contracts are separate from old `gee_contract_mock`.
  Requests discriminate injected/live and province/sandbox_roi; ROI output never
  claims whole-province coverage. Project/principal/number are non-secret metadata
  with readiness explicitly `not_verified`, not proof of a real Cloud account.
- Semantic request, geometry, input manifest, observation and candidate hashes
  have separate purposes. V2 canonical JSON has sorted UTF8 keys and normalized
  plain decimal numbers; SQL independently reconstructs it. A6.1 is unchanged.
- `gee_live_bridge.py` builds explicit SDK-shaped expressions from injected SDK,
  transport and authorization dependencies. No ee import/initialization, ambient
  ADC, dotenv, legacy startup/endpoint, cache/database or credential access.
  Only injected SDK/transport can run; execution=live is rejected before auth or
  evaluation. One transport evaluation per call, no automatic bridge retry.
- Graph reuses the existing summary methods: Sentinel2 Harmonized + CloudScore+,
  clear0.6, division10000, annual scene20/fallback80, median Bands before NDVI,
  annual negative mask; monthly80/mean-only. Landsat8/9 C2L2 scene40, QA3/4,
  ST_B10 *0.00341802 +149 -273.15 once, median composite. Nominal reduction500m,
  bestEffort and annual NDVI tileScale4 remain. No legacy formulas were edited.
- This is summary-method scope: no population, canopy, area, raster/export,
  ranking, timeseries or full legacy endpoint parity. Monthly graph selects the
  requested closed period, rather than invoking the twelve-month endpoint helper.
  Additional valid-pixel count is evidence, not a changed NDVI/LST formula.
- Raw null, missing means/extrema, incomplete/open periods, all-masked data and
  genuine zero remain distinct. At most32 scenes; mismatched counts, duplicates,
  overflow or oversized16KiB reports reject rather than truncate. Effective scale
  and reduction CRS stay unknown/null;500m is not a native-resolution claim.

## SQL and queue

New migration: `044_gis_live_foundation.sql`.
SHA256: `874919e286d7870e61f0374502a513a53ca06d6085fd9ba0b2e17df329a08a9a`.

Three append-only forced-RLS owner-only tables: `gee_live_inputs` (trusted input,
no expected output/oracle), `gee_live_requests` (job/catalog linkage),
`gee_live_candidates` (result/attempt/worker/fencing linkage).
Only the attested operator registers inputs and invokes the private command.
No new public Live HTTP route or service-role create/read RPC was added.

The existing queue/attempt/result/audit/receipt model is extended additively.
Protocol-specific claim/recovery uses the same global concurrency1,60s lease,
heartbeat, three-attempt budget and5/20s+jitter retry backoff. Duplicate success
acknowledgements replay; stale/other-worker completion cannot commit.
Dedicated Auth-issued `gis_gee_live_worker` has only worker/readiness RPCs,
NOLOGIN/NOINHERIT and no direct table, Admin, legacy write or other-worker RPC
rights. SQL derives subject from trusted JWT/session context, never payload ID.

Every registration/completion is **injected-only** in044. It validates required
fields, method/context, canonical hashes, scoped geometry, scenes/dates/counts,
raw/rounded statistics, completeness, revision and current fenced lease.
SQL rejects overflow/underflow and numbers that fail float8 JSON round-trip;
Python also enforces finite values/exact legacy rounding. SQL checks reporting
precision and nearest-value bounds, not identical Python binary-float tie rules.
No hash alone certifies satellite authenticity; trusted worker authority is still
required. Scientifically plausible fabricated evidence is not made authentic by
schema validation. No synthetic expected-output certificate is used for V2.

Deferred invariants bind candidate to the exact result/attempt/report/worker.
Editions remain draft/unvalidated; candidates are immutable, ineligible and
nonpublishable. No active pointer or publication/cache operation is added.

## Review, migration execution and actual tests

Independent `a63_security_review` approved exact SQL and sensitive Python before
any probe/apply, then reviewed final saved evidence/source. No unresolved
High/Critical or must-fix finding. Review is source/evidence-only, not a reviewer
test rerun. Reviewed hashes are in `dev/gis_local/gee-live-review.json`.

Before applying: verified both Local identities, ownership/cluster/runtime marker,
closed broad gates and all previous ledger/file checksums. A complete synthetic
register/create/claim/complete plus deferred-invariant check ran inside ROLLBACK
on both `postgres` and `gis_t1_upgrade`. Both passed. Only then044 was applied
once with insert-only ledger entries. No old migration or ledger was replayed.

| Actual verification | Result |
|---|---:|
| Focused contract/bridge + affected A6.1/mock/offline unit regression | 268 passed |
| Python3.11.17/Linux, existing approved image, network=none | 248 passed |
| Actual Local GoTrue/PostgREST/JWT/SQL, injected observations | 55/55 |
| Catalog bypass/canonical/protocol/numeric boundary checks | 15/15 |
| Existing Mock/Offline SQL/Auth regression after044 | 57/57 |
| Read-only preservation, both databases | 25/25 |

Live-protocol SQL tests cover forged project/method/hash/revision/report,
JWT/ACL/RLS, concurrent claim/acknowledgement, heartbeat, real lease expiry,
replacement RPC recovery, fencing, retry/backoff/exhaustion and immutability.
Boundary checks actually attempt Mock/Offline claims while a V2 job is queued.
The similarly named row in the55-check suite only inspects readiness; it is not
counted as independent isolation proof. Rehashed LST-monthly overflow, underflow
and non-roundtrippable decimal tests isolate numeric checks from NDVI bounds.

Source hashes match all final reports. Earlier focused run had a test-only
misplaced block/NameError; corrected and rerun on Windows and Linux. Review
closed registration/null/canonical/numeric issues before applying044.

Raw evidence remains outside Git in the existing visualization root:
`a6-4b-foundation/` (focused-9bf3891a log/XML/source/result, Linux log/result,
old-protocol-regression.json, preservation-final.json, baseline and final audit).
Local runtime `a6-4b-live-foundation/` holds reviewed probe/apply records,
`checks-cbee558ca4d3` JSON/JSONL/source and `boundary-checks.json`.

## Files, preservation and readiness

All implementation files are new: four `gis_worker/gee_live_*.py` modules,
`tests/test_gee_live_foundation.py`, migration044; three local operator/check
scripts, `gee-live-review.json`, and this handoff. No existing application,
frontend, dependency or migration file changed.

All328 pre-existing protected files and original five untracked evidence files
retain SHA256. Both databases preserve every pre-existing GIS row/history/
artifact/pointer, old ledger values/timestamps and original profiles. Public
Legacy table hashes match, including nonempty worker DB3 NDVI annual rows,
3 LST annual rows and3 Saved Areas. Existing publication function bodies match.
Both queues are idle and broad activation gates remain closed. New synthetic
test users/inputs/jobs/history are retained. No old data or volume was deleted.
Linux unit containers auto-removed; core containers, volumes and images retained.

`LiveWorker` inherits the existing loop/lifecycle but executable startup and
compute fail closed: no approved Live image, credential channel or enforceable
egress exists. Caller/env flags cannot enable it. Mock/Native policy is unchanged.
No new dependency, service, image build or Google account access in this task.

Not Tested: actual Earth Engine SDK evaluation/server expression behavior,
empty-collection/server error handling, genuine satellite/scientific spatial
parity, Google identity/registration/IAM/Quota/Billing, real-network retry/cancel,
Live daemon/container/SIGKILL/OOM/timeout or browser/UI (no frontend changes).
The old A6.3 process evidence is not a new V2 daemon test. Current results prove
injected contract/graph-operation behavior and actual Local SQL authority only.

Next approval must establish the Sandbox Project and explicit allowlist, Google
identity lifecycle, registration/tier/budget, enforceable restricted egress,
approved exact image/command and bounded ROI/period. Real transport/auth remains
unimplemented/disabled. Accepting real observations also needs separately
reviewed forward-only authority changes;044 cannot certify or accept live output.
Do not silently relax044, feed Google credentials to Mock, publish candidates or
start a Live Smoke Test/A6.5/A6.6.
