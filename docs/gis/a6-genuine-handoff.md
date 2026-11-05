# A6 Genuine HTTPS foundation

Status: PASS for the closed/offline Genuine HTTPS foundation. No Live execution
approval. Independent review found no unresolved High/Critical issues in this scope.

## Scope and implementation

- Branch `feature/gis-data-management`; starting commit
  `54100050bb4ac6bade27bee9a2d9774d0189e28a`.
- Explicit memory-only, broker-signed short-lived credential delivery binds the
  Sandbox ID/number, SA email/immutable ID, worker/recorder, session, job, attempt,
  input, ROI, method and lease. No ADC, key discovery, credential file/env/CLI,
  implicit Google refresh or credential logging. The broker's signature is not
  a Google signature: real mint-time identity verification remains required.
- Genuine HTTPS reuses the physical reserve/attempt/uncertain/retry/seal boundary
  from the pinned SDK Fake-HTTP implementation. Explicit Certifi CA roots,
  hostname verification, TLS1.2+, fixed endpoints, no redirects/proxy discovery,
  bounded response sizes and timeout shutdown. Discovery/catalog calls count;
  auth refresh is explicitly rejected, not silently sent outside accounting.
- Pure graph/scientific parsing is shared with the old injected path. Existing
  formulas, masks, datasets, scale/reducers and zero/NoData handling are retained.
- Separate Genuine Queue Worker specialization reuses polling/heartbeat/fencing.
  Its trusted recorder/runtime dependency is not taken from an API/job payload.
  No operational Live launcher, broker process or approved Live image is supplied.
- Migration047 reuses existing sessions, budgets, jobs, attempts, results and
  immutable Candidates. Adds private forced-RLS runtime approvals, bound authority,
  observed HTTPS receipts and per-attempt seals; dedicated NOLOGIN Worker and
  Recorder JWT roles. Fake/Rehearsal and Genuine budget/stop/recovery paths are
  isolated. The database owner/operator remains a trusted administrative boundary.

## Trust and deployment gate

`APPROVED_LIVE_IMAGE` and `APPROVED_EGRESS_POLICY` remain `None`;
`require_selective_egress()` always rejects. Caller booleans, env flags, hashes,
injected outputs or project registration do not open this gate. Mock/Native
allowlists are unchanged. No runtime approval is installed outside rolled-back
synthetic SQL tests; no genuine Candidate is retained from those tests.

The recorder is the trusted HTTPS observer. A receipt hash/certificate fingerprint
alone does not establish Google origin. An untrusted Worker has no recorder RPC,
private table access or runtime-approval authority. The real recorder must run
separately with an approved credential-delivery and network policy before that
authority may be provisioned.

Minimum network design still to prove: Worker has only local RPC/approved private
IPC, no direct Internet; recorder uses a pinned restricted-egress path with
default-deny network rules, approved DNS resolution/Google TLS destinations and
no redirect bypass. Application endpoint/graph checks bind Sandbox and public
collections, never arbitrary Legacy asset expressions. Hostname filtering alone
cannot isolate projects sharing a Google endpoint; IAM/resource isolation and
the trusted graph/recorder boundary are also required. `network=none` unit tests
are not evidence that selective egress works.

## Validation and preservation

Focused evidence is recorded outside Git under `a6-genuine/` and
`t0-local-supabase-20261027-v2/a6-genuine/` in the existing external Sandbox.
Independent exact-source review metadata is `dev/gis_local/gee-genuine-review.json`.
That file records the historical pre-Apply approval; final reviewed hashes and
test counts are in `dev/gis_local/gee-genuine-final-review.json`.
No real credentials, Google HTTP, Live computations, Cloud changes or EECU/cost
cap claims are part of these tests. Signed delivery, TLS exchanges and SQL
positive observations in tests are synthetic. SQL fixture lifecycles roll back.

Migration000–046 are immutable. Before persistent047 Apply, both database target
proofs, exact review hashes and rollback lifecycle evidence must pass. A checksum
mismatch fails closed; no ledger UPDATE/replay fallback. Preservation compares
old public tables/caches/Saved Areas, original profiles, GIS history/pointers and
ledger prefix. The original five untracked evidence files must stay uncommitted.

### Executed checks

| Check | Actual result |
| --- | --- |
| Windows Python3.12.10 focused tests |162 passed;12 Linux-only skipped |
| Linux Python3.11.17, existing pinned image, network=none |164 passed |
| Both Local DB rollback lifecycle probes |Passed before persistent Apply |
| Local GoTrue/JWT/RLS/SQL integration |27 passed,0 failed |
| Existing FakeHTTP SDK/Auth/SQL regression |40 passed |
| Existing concurrent/fencing/unbound regression |16 passed |
| Actual SDK-generated URI versus SQL allowlist |20 passed |
| Final preservation |12 passed,0 failed |

Counts overlap across platforms/suites and must not be summed as unique cases.
SDK TLS sockets, signed credential deliveries and positive SQL observations were
synthetic; these are not genuine Google observations. The reviewer inspected
source/hashes/evidence and did not rerun tests independently.

Migration047 was applied once to identity-verified Local `postgres` and
`gis_t1_upgrade`, after exact independent review and both rollback probes.
Reviewed/source/ledger SHA256:
`b04c63ca3f30a4605d8514bbbfc3195cdbe9a44dac3544b6ca19bf9a8c70962c`.
Migration000–046 bytes and previous ledger entries remain unchanged. Preservation
includes nonempty Local annual NDVI/LST caches and Saved Areas, old GIS history,
profiles and pointers. No runtime approval, Genuine Candidate, publication or
active pointer change was retained. Synthetic Auth/old Fake regression records
remain in Local Sandbox; no data or volumes were deleted.

During verification, a table-RLS assertion was corrected to exclude indexes;
preservation was corrected to compare000–046 separately from newly applied047.
Only the test helper changed after Apply; SQL047 did not change. Integration27
was rerun against the final helper hash
`1bf1269046dff8e0db9f40c037a49cc179e9ec4a7dd01cd3dbde4c6b519d69e2`.
Earlier evidence and the pre-Apply review were retained as historical records.

### Delivery files and repository state

Shared changes: `gee_live_bridge.py` and `gee_live_contracts.py`.
New worker modules: `gee_genuine_identity.py`, `gee_genuine_runtime.py`,
`gee_genuine_transport.py`, `gee_genuine_worker.py`.
New SQL/operator/tests: Migration047, `gee_genuine_local.py`,
`gee_genuine_checks.py`, `test_gee_genuine_local.py`,
`test_gee_genuine_foundation.py`.
Documentation/review metadata: this handoff and the two review JSON files.
No new dependencies, Cloud resources or real credentials are included.
The authorized scoped Local Commit uses
`feat(gis): add gated genuine GEE execution foundation` on the existing branch;
obtain its final SHA with `git log -1`. No Push is authorized.
Git's existing `core.autocrlf=true` normalizes the tested CRLF bridge file to LF
in the commit; byte comparison confirms only CRLF/LF differs. Its tested
working-tree SHA is recorded above in final review; canonical Git blob SHA is
`5720c887e51893fffc03ccece6ef0da9e926d924ed70281611505cfd950aedce`.
Staged whitespace check reports only a blank line at EOF in the new identity and
runtime modules; reviewed/tested bytes are retained without a cosmetic rewrite.

## Next task and approval

Prove the actual credential broker's mint-time identity/expiry and pin its public
verification key; prove a packaged image/process boundary and selective egress
(DNS/TLS/redirect/Legacy restrictions). Only then review the startup gate change,
provision time-bounded runtime authority and request final Smoke Test approval.
Smoke limits remain one worker, four logical jobs,32 counted attempts, two
application attempts/job,120s request,180s logical deadline,20min session. These
counters do not establish a hard EECU or billing cap. No publish/activation/cache
mutation is authorized. No Push/Merge/PR/Deploy is part of this delivery.
