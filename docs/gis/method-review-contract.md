# Source integrity and NDVI/LST method review contract

Updated 6 November 2026. Scope: findings 1 and 2 of the 3 November 2026 external review.

## 1. Hash schemes (`gis_worker/source_integrity.py`)

| Scheme | Used for | Normalisation |
| --- | --- | --- |
| `source-text-lf-sha256-v1` | reviewed text: legacy NDVI/LST sources, `registry.json`, `poc_validation.py` | CRLF → LF only |
| `raw-bytes-sha256` | artifacts: ZIP, Shapefile, GeoTIFF, processing fixtures, uploads, SQL migrations, ledger | none |
| `raw-crlf-sha256-v0` | historical identities reviewed on the Windows CRLF checkout | derived only, never read from disk |

Rules:

- The text scheme rejects instead of normalising: a lone CR, a NUL byte or invalid UTF-8 fails with `SOURCE_TEXT_INVALID`. Whitespace, comments, a BOM and the final newline all still count.
- Every check names its scheme. There is no fallback from one scheme to another.
- The historical v0 values are unchanged. They are pinned in migrations 035 and 044 and in old manifests and results. The approved definition stores both the LF-scheme hash and the v0 value for the same reviewed text, and every check verifies both (`legacy_crlf_sha256(text) == v0`). An old value is never relabelled as the new scheme.
- `.gitattributes`, migration checksums and the database ledger are not changed.
- `registry.json` (T3) carries `source_code_sha256` for `poc_validation.py` without naming a scheme. That value was computed over LF bytes. `poc_validation.py` has no CR in either checkout, so its raw hash and its text-scheme hash are the same value; `provider.py` now names the text scheme for that check explicitly. `registry.json` itself is verified under both the text scheme and its v0 value.

## 2. Approved method definitions (`gis_worker/method_registry.py`)

`APPROVED` contains only `legacy-v1`, which covers `ndvi-annual|ndvi-monthly|lst-annual|lst-monthly-legacy-v1`. Each definition records:

- the method versions it covers;
- the hash scheme and the approved source hashes;
- the v0 identity;
- collections, bands, masks, scale/offset, reducers and units;
- the scientific values that `legacy_spec()` must read from the sources (AST data only);
- a review reference.

Definitions are immutable and come only from reviewed code, never from an API payload.

Fail-closed behaviour:

- An unknown or unreviewed method version fails with `PROCESSING_METHOD_UNREVIEWED`.
- Sources that match no approved definition, or match more than one, fail with `PROCESSING_LEGACY_SOURCE_CHANGED`.
- A request whose pinned identity differs from the definition matched on disk fails with `PROCESSING_METHOD_UNREVIEWED`. This stops an old request from being computed under a newer method.
- `gee_contracts.method_for()` takes `legacy_sources` and `METHODS` from the definition and refuses (`GEE_METHOD_INVALID`) to build any version without an approved definition. The values are unchanged, so the method hash bound by 044 is unchanged.

### Changing a Dashboard formula later

When the Dashboard formula changes:

1. Add a new definition (for example `legacy-v2`) with a new review reference. Do not edit `legacy-v1`.
2. Add a forward migration that lets the queue accept the new method identity in manifests. Migrations 035 and 044 accept only the `legacy-v1` identity (`legacy_pipeline_sha256`, `gee_live_method`). The migration must also keep old candidates and caches bound to v1.
3. Get an independent scientific review of the new expected values.

Until all three steps are done, the worker stops with `PROCESSING_LEGACY_SOURCE_CHANGED`. This is intentional.

Status: `origin/main` at `048273f` (the merge base of this branch) does not change `gee_utils.py`, `routers/ndvi/compute.py` or `routers/lst.py`. If the reviewer's local main has formula changes that are not pushed yet, they need the steps above.

## 3. Proposed forward migration (not written, not applied, needs approval)

`049_gis_method_registry.sql`:

- Add a `gis.approved_methods` table: method_id, versions, scheme, approved hashes, v0 identity, review reference, approved_by/at. It is append-only and owned by `gis_owner`.
- Seed one row for `legacy-v1` with exactly the current values.
- Wrap `processing_manifest` and `gee_live_method` so that they read the identity from that table, keyed by method_id. Old rows keep resolving to `legacy-v1`.
- Add a `method_id` column to new manifests. When it is absent, the manifest means `legacy-v1`. It is never inferred as a newer method.
- Needs an independent SQL review, then the usual rollback probe and approval file before it is applied.

## 4. Handoff notes

- `dev/gis_local/gee-runtime-image.lock.json` (A6.4d-2, owned by the A6 track) pins the hashes of `gis_worker` files. The files changed here (`processing_provider.py`, `gee_contracts.py`, `provider.py`, `ldd_provider.py`, `ldd_prepare_provider.py`) differ from that lock, and the new modules `source_integrity.py`, `method_registry.py` and `ldd_policy.py` (now imported by `gee_contracts.py` and the LDD providers) are not in it. The lock was not edited. It must be re-reviewed before any A6 runtime image is rebuilt.
- Historical evidence JSON and review records are unchanged.
