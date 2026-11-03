# A2 Handoff — Local LDD Prepare & Preview

Date: 2026-11-03. **PASS — Local Synthetic scope only.**
Branch `feature/gis-data-management`; HEAD
`4c06fbd8a8f93af4dccf1a9389e277be98502185`.
A1 and A2 remain uncommitted. No branch change, Commit, Push, Merge or Deploy.

## Goal and completed behavior

Prepare accepted uploaded LDD ZIPs as actual immutable Geometry and Summary files,
with trusted byte verification and an embedded Officer Preview. Reused existing
Auth, catalog, queue/attempts/results, worker lifecycle, source storage and037 registry.
No Dashboard readers, legacy formulas/cache, active pointers or gates were changed.

`ldd-source-area-v1` retains every accepted source feature, reprojects display
geometry toEPSG:4326 and sums validated original Shape_Area in m² once per feature.
Raw composite LU_CODE buckets remain whole. Dataset/Edition/validation/input
revision/hash/sourceSHA/province/year/method and asset hashes are embedded.
Coverage is the validated source footprint, **not a complete province inventory**.
See [the detailed contract](ldd-prepare-contracts.md).

Prepare Worker writes staging only. A credential-free, network-disabled verifier
recomputes all bytes from the original. The host reopens/promotes content-addressed
files before service-only SQL certification. Browser/Worker cannot send a trusted
proof or self-certify. Every Preview/readiness HTTP read checks original/output
hashes and sizes; missing/corrupt bytes revoke the certificate and suppress data.
UI clears old ready geometry when a recheck fails.

## Changes and migration

| Area | A2 files |
| --- | --- |
| SQL | migrations/038_gis_ldd_prepare.sql; .gitattributes entry |
| Native | gis_worker/ldd_prepare_provider.py, ldd_prepare_child.py, ldd_prepare_worker.py |
| Backend | gis_ldd_prepared.py, routers/ldd_prepare.py; GIS factory/runtime/service/me wiring |
| UI | LddPreparedPreview.js/.test.js; GisManagement.js, gisClient.js |
| Local | ldd_prepare_local.py, ldd_prepare_checks.py, ldd-prepare-review.json; manage.py exact guard variants |
| Demo | a2_demo.py, a2_smoke.cjs; legacy_demo.py factory wiring; phase5_demo.py optional launchers with default retained |
| Tests/docs | test_ldd_prepare_native.py, test_ldd_prepare_api.py, test_ldd_prepare_guard.py; this handoff and contract |

Migration038 adds three immutable FORCE-RLS request/certificate/revocation tables,
deferred invariants and six public RPC wrappers (four service-only, two Worker).
It narrowly updates four old GIS functions for Prepare isolation and replaces
publication readiness with certificate-aware logic. No new queue or active pointer.

Applied once to Local `postgres` and `gis_t1_upgrade`, after independent exact-SQL
review. Frozen SHA256:
`e55344ef585e9c23c9269dae414ed73ba05fa508625fe6c6e7acf2e148795825`.
All000–037 file hashes and original ledger rows remain unchanged. Final read-only
checks match20 SQL function bodies to038 (CRLF/LF normalization only), fixed owner/
search_path, three FORCE-RLS tables with no direct non-owner privileges and six
exact RPC ACLs. Never edit/reapply038 or update its ledger to resolve a mismatch.

## Actual tests and evidence

Evidence lives outside Git under the existing T0 runtime directory,
`a2-ldd-prepare/`; use `evidence-index.json` for hashes and source comparison.

| Suite | Actual result |
| --- | --- |
| Linux scientific + existing native LDD | 50 Pass, Python3.11.17/Fiona1.10.1/Shapely2.2.0, pinned image/network none |
| Backend/Local guard regression | 555 Pass +37 subtests |
| Focused A2 API including two added quota cases | 20 Pass; overlaps the regression suite, not20 additional distinct tests |
| Frontend focused seven files | 83 Pass; Local no-env configuration |
| Frontend Local build | Pass; existing chunk-size warning remains |
| Core real Auth/API/Linux/files | 34 Pass; one pre-kill timing test failed because job had already finished |
| Focused lifecycle continuation | 30/30 Pass, resolves that Kill/Recovery case |
| Actual Browser enqueue → prepare → verify → preview | 6/6 Pass, API not mocked; external HTTPS blocked |
| Additional Preview screenshot/read flow | 6/6 Pass; Desktop/mobile images inspected by main agent |
| Final read-only SQL/preservation, both DBs | Pass |

Core evidence: `integration-8f45337913/integration-results.json`.
Continuation: `integration-f25a29325d/integration-results.json` and browser report.
Visual evidence: `visual-59cd26a63c/`. Scientific/current source: `linux-science.json`.
Preservation/security: `final-preservation.json`. Logs from aborted earlier runs
are retained: max-four-worker guard refusal, expired Local test keys, an upload-
response assumption in the test harness and the pre-kill timing race. They are
not represented as passing runs. Final application/SQL source did not drift;
indexed differences are test-harness changes and added API quota tests.

Verified: real two-daemon claim produces one attempt; idempotency/semantic dedup;
small3-feature6400m² known result; forged scope/hash/revision/authority rejection;
actual object corruption and source removal revoke readiness; source restored
without overwrite; originals retained. Actual SIGKILL of claimed pending work,
natural60s lease expiry, replacement recovery, expired→succeeded attempts, one
result and old-token fencing passed. For deterministic timing, the test briefly
paused its exact owned container before SIGKILL; no DB clock/state was shortened.
Three controlled transient RPC failures exhausted the budget; explicit retry ran
the real native provider successfully and retained failed-parent history. This
injection is **not** a new OS timeout/OOM test.

Independent reviews: `a1_security_review` approved exact038 before application;
`local_integration_security_review` reviewed current boundaries and actual final
reports. **No High/Critical finding remains in A2 Local scope.** Screenshot visual
QA was performed by the main agent, not independently by that reviewer.

## Preservation, maintenance and cleanup

Original public-table hashes, original profiles, the eight captured old GIS tables'
rows, original ledgers and active pointers are preserved in both Local DBs.
New synthetic users/jobs/attempts/certificates/audit rows remain intentionally.
Existing NDVI/LST/recommendation cache tables and Saved Areas were empty: unchanged
empty hashes do **not** prove populated numerical-cache preservation behavior.

The original generated seven-day Local anon/service keys expired during testing.
An independently reviewed one-time external maintenance renewed only those keys,
same issuer/roles/signing secret/TTL, retained a private Windows-ACL-protected
backup, and restarted only the verified Local Gateway. No Auth settings, SQL
roles, schema, production credentials or repository env files were changed by
that maintenance. No credentials entered reports/Git. Worker bootstrap contains
only the Local anon key and Auth-issued Worker session, never a service key or
JWT signing secret.

All owned test API/UI/workers/verifier/science containers were stopped/removed;
existing core containers retain their initial running state. Original volumes,
fixtures, retained failed-test bytes and data remain. No images pulled/built, no
dependencies/services added, no Cloud/GEE calls or production/staging operations.

## Limits and next approval

- Only synthetic files tested. No official licensed LDD, official source-year
  authenticity or complete-province acceptance. Existing approximate buffered
  boundaries and96-code legend remain limitations; unknown codes fail review.
-1500 overlapping synthetic polygons exercised Prepare/recovery successfully.
  This is not a verified full-province artifact benchmark or a higher capacity
  promise. Complete trusted-byte verification is demonstrated on the small known
  fixture; large/official data needs separate capacity acceptance.
-256 MiB is a certification/pre-write accounting threshold, **not a hard atomic
  combined filesystem quota**. Stage accounting is separate and can race; strict
  disk quota/reservation remains future work. Quota507 denial is unit-tested;
  physical disk exhaustion is Not Tested.
- Certificate revocation is permanent; current dedup/uniqueness does not offer
  same-Edition rebuild/re-certification. Original bytes/history are retained.
- SQL readiness proves a certificate, not current filesystem availability. A3
  must freshly verify actual bytes before publication and preserve revision/
  pointer/transaction guards. The Activation Gate remains false in A2.
- No new A2 kernel OOM/CPU-timeout or interactive hidden-password manual session
  is claimed. Resource settings and inherited lifecycle were checked; actual
  process kill/recovery and Browser flow were executed.
- A2 manual launcher starts LDD validation+Prepare only; other provider workers
do not drain jobs in this focused mode. Original full demo default behavior is preserved.

**A3 readiness: READY to propose Local implementation, pending separate approval.**
No A3–A6 implementation, activation, withdrawal, rollback, Dashboard publication,
Cloud/GEE integration or production deployment is authorized by this closure.
