# A6 — Local Fake-HTTP SDK integration handoff

Overall status: **PARTIAL**. Fake-HTTP implementation/tests PASS. Genuine-Live
approval/result authority is NOT implemented; all real execution remains closed.
No commit: the user authorized a local commit only after overall PASS.

## Scope and baseline

- Branch: `feature/gis-data-management`.
- Unchanged HEAD: `23d08fd69ab321d4b1f068b4e8fa0922e1d0b770`.
- Preserve the original five untracked T1–T3 evidence JSON files.
- No Google/GEE HTTP, real credentials, IAM/Billing, publication, legacy reader,
  dependency lock, deployment, branch switch, commit or push changes.
- User separately approved two Linux binary wheels, cryptography49.0.0 and
  cffi2.0.0. Both match hashes already in requirements.txt. Downloaded/extracted
  outside Git; no global install. Linux tests used network=none and readonly
  mounts of installed SDK sources plus those approved wheels.

## Implemented

`gee_sdk_transport.py` exercises installed earthengine-api1.7.30 through actual
ee.Initialize, dynamic normal/raw discovery, algorithms, graph serialization,
computeValue, googleapiclient503 retry, AuthorizedHttp401 refresh/retry and the
SDK's otherwise separate urllib deprecation-catalog lookup. All HTTP goes to
an exact in-memory FakeHTTPWire; SDK and synthetic credentials are explicit.
Imports never initialize EE or discover credentials. SDK global state is reset
under a process-local concurrency lock; no legacy main.py/HTTP/cache calls.

PhysicalHTTP reserves and marks attempted in SQL BEFORE each send, validates
acknowledgements and remaining deadline, records response evidence and seals a
complete receipt set. No ambiguous timeout/ack refunds. Discovery/catalog/token
bootstrap calls count as discovery; retries after HTTP errors count as sdk_retry.
Authorization/token bytes are excluded from receipts. Token request/response
hashes are explicitly redacted placeholders, not hashes of genuine tokens.

The original scientific bridge/model is unchanged: NDVI annual/monthly masks,
cloud thresholds, scale/reducers and Landsat thermal conversion are reused.
Zero remains distinct from NoData; all outputs remain injected/synthetic.

## Migration046: applied locally, never edit/reapply

`046_gis_gee_live_authority.sql` SHA256:
`bd4d94a0b993aa7d037f14f6957451052707b4af1cb614d9d45ae42c03cbe23c`

- Applied only to identity-verified `postgres` and `gis_t1_upgrade` in the
  approved local Supabase cluster, after independent exact-SQL review and full
  transaction rollback probes on BOTH databases.
- Adds immutable forced-RLS authority, physical receipt and attempt seal tables.
- Dedicated NOLOGIN/NOBYPASSRLS recorder role, trusted JWT role/issuer/subject,
  distinct from the bound worker. One public RPC; private helpers/table access,
  admin/service/legacy writes are denied.
- Reuses045 sessions/jobs/reservations and Queue/Attempt/Result/Candidate tables.
- Authority binds session/job/worker/recorder/project/principal/input/method/ROI.
- Original045 completion paths ALSO require a recorder seal for bound jobs.
  Unbound old jobs delegate to the unchanged045 validator.
- Per-HTTP hashes/status/raw compute observation are distinct from045's final
  observation hash; sealing checks scientific output against recorded response.
- Deferred invariants reconstruct completed Attempt identity. Edition remains
  draft, result/candidate immutable, no publication/activation/cache writes.

IMPORTANT: mode is constrained to `fake_http`, principal is explicitly the
nonexistent offline test identity. No google_https approval can be inserted and
genuine completion is always rejected. This prevents fake→genuine laundering
but does NOT satisfy the requested positive genuine-result authority. A later,
separately reviewed forward migration is needed; never change applied046.

The guarded operator requires exact reviewed source/checksum, verified local
targets, matching two-database rollback evidence and explicit post-probe apply
approval. Mismatch fails closed without reapply or ledger UPDATE.

Early rollback probes exposed preflight ACL, session-authorization simulation
and an unused-variable ambiguity. All rolled back. Fixed and independently
reviewed BEFORE persistent Apply. Probe now uses operator-private lifecycle,
not a simulated proof of JWT; actual GoTrue tokens were tested after Apply.

## Actual evidence (not rerun claims)

| Suite | Result |
| --- | --- |
| Focused Windows SDK/safety/science/operator units | 130 PASS,12 Linux-only SKIP |
| Linux Python3.11.17 real SDK over FakeHTTP + safety units | 137 PASS |
| Actual local GoTrue/JWT/RPC/SDK/SQL integration | 40 PASS |
| Extra Auth/SQL concurrency/forgery/old-protocol integration | 16 PASS |
| Read-only preservation, both databases | 11 PASS |

Counts overlap across platforms; do not add them as unique cases. Integration
checks compare source hashes before/after. Concurrent reservations consumed32
slots exactly; concurrent claim/complete created one attempt/result; stale token,
wrong subject, spoof payload, forged output, response hash/replay and original
worker-completion bypass were rejected. Existing unbound045 path still works.

Scientific tests validate known synthetic outputs and serialized real-SDK graph,
NOT actual satellite results or EE server-side scientific parity.

Runtime evidence is outside Git under:
`C:\Users\chaya\.codex\visualizations\2026\10\04\01a107d9-ff44-7731-8bc3-91814ffd8d51\`

- `a6-sdk-http/`: units XML/result, Linux log/result, approved-wheel hashes,
  isolated launchers. No raw evidence or wheels should be committed.
- `t0-local-supabase-20261027-v2/a6-sdk-http/`: before snapshot, reviewed rollback
  probes, migration046 application, integration40, extra-integration16 and
  preservation reports.
- Historical pre-Apply review is `dev/gis_local/gee-transport-review.json`.
  Final independent-review record is separate; historical hashes are retained.

Preservation compares original profiles/rows, all legacy caches including
nonempty NDVI/LST caches, Saved Areas, datasets/editions/history/active pointers,
and old ledger rows/timestamps. Only046 is appended. Migration000–045 bytes are
unchanged. Synthetic users/jobs/history are retained; nothing is deleted.
Temporary unit containers cleaned up; existing core containers/volumes retained.

## Remaining blockers / Not Tested

- Positive genuine approval, recorder attestation and genuine Candidate SQL
  acceptance are absent. No amount of matching JSON hashes proves Google origin.
- No approved real Google principal, IAM, short-lived credential delivery/renewal,
  Live image or selective DNS/TLS/redirect/egress policy.
- No actual Google SDK HTTP, satellite parity, remote cancellation, live worker
  kill/restart or hard EECU/cost-cap proof. Physical accounting is proven only for
  the enumerated pinned SDK FakeHTTP paths; no generic EE API/network guarantee.
- Linux test source reuse is NOT a packaged/approved Live runtime image.
- Existing worker recovery evidence is reused for unchanged Queue/Lifecycle;
  genuine daemon integration is not proven by this controller-driven test.

## Next approval needed

Review this PARTIAL delivery first. Resolve the real Sandbox worker identity and
approved transport/recorder trust model before implementing positive genuine
authority in a new forward migration. No047, Cloud configuration, Live test or
commit is authorized automatically. Retain all work and applied046 as-is.
