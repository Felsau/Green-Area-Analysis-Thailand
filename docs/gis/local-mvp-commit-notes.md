# Local MVP source packaging

2 November 2026 — T0–Phase 5, Local Dashboard Integration and GIS UI/UX improvements.
Scope remains **Local/Synthetic**, with activation/publish and live GEE disabled.
This record does not approve deployment, production data or a new phase.

## Included source

The commits retain the integrated local environment tools, SQL migrations
027–036 and exact review manifests, API/storage/worker code, synthetic fixtures,
frontend, tests, contracts, runbooks and historical handoffs. The district overlay
labels are removed while geometry and existing picking behavior are retained.

`.gitattributes` disables line-ending conversion only for migrations 027–036.
Their original bytes are bound to the applied local ledger and review checksums;
neither their SQL nor migrations 000–026 were edited during packaging.

## External files retained locally

The following generated runtime evidence is intentionally not committed or deleted:

- `docs/gis/t1-test-evidence.json`
- `docs/gis/t2-test-evidence.json`
- `docs/gis/t3-readiness-evidence.json`
- `docs/gis/t3-remediation-evidence.json`
- `docs/gis/t3-test-evidence.json`

Other execution logs, screenshots, database snapshots, generated credentials,
uploads and runtime state remain outside Git. Static `dev/gis_local/t*-review.json`
records are checksum-bound inputs to the migration runners, not raw runtime logs.
Historical handoffs describe their original dates and pre-commit states.

## Evidence boundary

The packaging review rechecked current migration bytes against the saved ledgers
for both local databases. It did not query or mutate a database or rerun migrations.
Current frontend/application hashes match the latest successful local UI tests.
The Browser E2E driver subsequently added a necessary-cookie selection for visual
capture; the application did not change. The later focused visual run covers that
cookie selection. No claim is made that every historical test ran anew.

## Reproduction limits

Frontend and isolated backend unit-test source is included. Real integration/demo
commands require the separately attested local Supabase runtime and its generated
files. The current worker launcher pins a locally built image ID; that image and
its build workspace are external runtime prerequisites, not a portable image
release. A fresh clone alone cannot recreate the complete tested environment.

`dev/gis_ui/final_readiness.py` is a historical evidence verifier and also needs
the archived T3/T4 reports, including the uncommitted remediation evidence above.
It is not a standalone fresh-checkout unit test. Creating a portable bootstrap or
changing the worker image policy requires a separate task; no guard is relaxed.
