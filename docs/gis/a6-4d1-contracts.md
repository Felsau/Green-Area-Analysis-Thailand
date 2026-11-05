# A6.4d-1 — Offline live-safety contracts

This foundation does not authorize Google Cloud access, credentials, network,
real Earth Engine execution, publication or deployment. Account readiness is
NOT VERIFIED. No approved Project ID, Project Number or Google principal exists
in the policy. Fixture identities are synthetic and never approval evidence.

## Authority and protocols

| Protocol | Meaning | Authority |
| --- | --- | --- |
| Existing offline/mock/injected protocols | Unchanged contracts | Existing Local scope |
| `gee_safety_rehearsal` / manifest 8 / report 3 | Accounted injected observations | Dedicated Local JWT subject only; never publishable |
| `gee_trusted_live_v3` | Future diagnostic envelope | Always rejected; no SQL result acceptance or executable startup |

`LiveResultBinding` describes worker/job/attempt/result/fencing/input identity and
a complete claimed output. Existing V2 provenance carries exact project,
province/ROI geometry, period, method, collections/scenes/acquisition dates,
raw values, pixels, completeness, units, scale/CRS and semantic/observation/output
hashes. `transport_evidence_sha256` identifies a future transport-attestation
document, not a verified observation. Parsing or matching hashes never certifies
that Google executed a request. The policy and transport verification remain
false even when a diagnostic envelope is fully populated.

## Durable rehearsal policy

| Boundary | Ceiling |
| --- | --- |
| Active queue work | One global running job, existing atomic queue claim |
| Worker | One trusted JWT subject bound to each session |
| Logical jobs | Four per session, independent of idempotency keys |
| Request reservations | 32 total per session, all states count |
| Application attempts | Two total, including recovery; no child-job reset |
| Request | 120 seconds from attempted, bounded native parent deadline |
| Logical job | 180 seconds from first attempt, including retry/backoff/restart |
| Session | Immutable 20-minute window |

Only the Local owner/operator can create a rehearsal session or register an
input. The worker cannot create or reset sessions. Its role has no direct GIS
table privileges, service/admin RPCs, legacy writes or real-live actions.

Every compute, reference, discovery or SDK retry must reserve a unique request
before marking it attempted. Reservation replay does not authorize another
evaluation. Allowed transitions are `reserved -> attempted -> completed` and
`reserved/attempted -> uncertain`. There is no refund, delete or reset path.
Completion requires all current-attempt reservations, their exact subject,
lease and observation hash. Concurrent reservation is serialized by session.

Lost accounting acknowledgement, expired lease, stop, timeout or replacement
preserves spent/uncertain history. Killing a local child does not prove remote
cancellation. Actual SDK retry interception, cancellation, HTTP counting and
transport attestation remain unimplemented and disabled pending separate live
runtime approval. EECU/cost objectives are external monitoring objectives, not
hard cost guarantees from these request counters.

## Isolation and storage

The fixed Linux child receives request/geometry/scenario only, with no JWT,
lease token or credentials. It reuses the existing clean environment, bounded
output, process-group termination and stop/lease events. Native CPU, memory,
file-size and FD limits apply. The approved test container has network `none`.
Server-side injected factories are trusted test dependencies, not a mechanism
for accepting arbitrary Python from a job or user payload.

Migration 045 adds forced-RLS session/job/reservation tables and two public
least-privilege RPCs. It reuses existing input/request/attempt/result/candidate,
audit, receipt and queue structures. Edition -> Job -> Session -> Reservation
is the work lock order. Batch finalization uses SKIP LOCKED for sessions.
Old protocol retry ceilings remain three; only rehearsal work uses two.

Successful results remain immutable injected Candidates. Editions stay draft;
neither eligibility nor publication readiness is granted. Legacy cache,
publication pointers and application readers are untouched.

## Local migration operations

Use `dev/gis_local/gee_safety_local.py` with the approved runtime directory.
`proof` verifies exact Local container/database identity, closed broad gate and
all applied migration checksums. `probe --review ...` requires the exact reviewed
SQL and sensitive Python hashes and rolls back a full candidate lifecycle on
both databases. `migrate --review ...` additionally requires that matching
two-database probe record. An applied checksum mismatch fails closed; no ledger
UPDATE, reapplication or old migration editing is allowed.

Focused reproducible tests are `tests/test_gee_execution_safety.py` (unit/Linux)
and `dev/gis_local/gee_safety_checks.py` (mutating approved Local synthetic DBs
only). Raw runtime evidence belongs outside Git. Run Local checks only under
their target guards, never against Supabase Cloud or production.
