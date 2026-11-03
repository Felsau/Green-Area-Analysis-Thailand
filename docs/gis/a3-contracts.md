# A3 Local LDD publication

Scope: annual province-level uploaded LDD only, Local Sandbox. Migrations039/040
are forward-only (040 corrects JSONB operator grouping without changing the
contract/ACL;039 remains byte-identical after application). SQL `gis.environment.activation_enabled` and backend
`sandbox_activation_enabled` remain false. Only `LddPublicationLocal` enables the
separate private `ldd_publication_enabled` capability; normal app factories do not.

## Trust and mutation

- HTTP Admin is resolved from the verified Auth token, then SQL reauthorizes the
  trusted Actor. Officer/normal users cannot publish. The three new public RPCs
  are service-role-only. Neither browser nor worker gets those privileges.
- `POST /gis/datasets/{id}/ldd-publication/activation`, `/rollback`, `/withdrawal`
  require Idempotency-Key and dataset revision/current pointer, edition input
  revision/hash, validation result, source SHA256, province/year, method
  `ldd-source-area-v1`, coverage `validated_source_footprint`, and reason.
- Withdrawal additionally requires explicit replacement_edition_id, including
  null. Withdrawn remains terminal. Replacing A with B keeps A validated;
  rollback requires prior publication history and a fresh eligible A.
- Fresh proof recomputes original ZIP through an isolated Linux native child,
  compares immutable artifact bytes/SHA/size, and reopens objects before SQL CAS.
  The owned storage lock covers proof through the SQL mutation. The verifier has
  no credentials/network, nonroot/read-only mounts and CPU/memory/PID/time limits.
- A full Dashboard bundle exceeding2MiB is rejected before pointer mutation;
  geometry is never silently truncated. This is a Local display limit, not a
  benchmark for provincial inventory capacity.
- Dataset lock precedes sorted Edition locks. Pointer, audit and receipt commit
  together. The old Dataset invariants remain and only a matching immutable
  audit bound to the current full transaction ID authorizes the narrow transition.
- Idempotent replay returns historical receipt data and never republishes its
  old pointer. The UI refreshes catalog/current Published state separately.
- Missing/corrupt/revoked targets cannot activate. An active unavailable upload
  can be withdrawn to null without its broken files; a replacement still needs
  fresh verification. No automatic activation or physical deletion occurs.

## Dashboard read and cache

`GET /gis/published-ldd?province=...&data_year=...` allows signed-in normal users
with existing profiles without granting GIS catalog access. District/extra query
fields are rejected. It returns one geometry/summary/legend/SourceIdentity bundle,
dataset revision and snapshot hash. Objects are reread on every request and SQL
rechecks the current pointer/certificate/snapshot after assembling the response.
Missing/corrupt files revoke the certificate via a private backend path and return
an explicit error without geometry or silent Legacy fallback.

Only summary projections are cached, bounded32 entries/60seconds and keyed by the
full source identity, input revision, snapshot and artifact hashes. Pointer and
geometry are not cached; even cache hits verify bytes and current snapshot.
Responses use Cache-Control:no-store. Legacy caches are neither cleared nor reused.

Legacy Dynamic World remains the default. Published is explicit and annual/province
only. Map, legend and summary use the same render-time scope/year-matched bundle.
Changing source/year/scope or a failed refresh clears Published state. Visible
pages recheck every10seconds and on focus/visibility/publication notifications.
This is an as-of snapshot with polling, not instantaneous multi-client push.

## Scientific and deployment boundaries

Original accepted features, Shape_Area and raw composite LU_CODE buckets are
preserved by A2. EPSG4326 geometry is for display. Coverage is validated source
footprint, not complete/official province inventory. The96-code legend, approximate
boundary check and declared year retain A2 limitations. Published LDD does not
change NDVI/LST, ranking, recommendations or the old GEE LDD provider.

No GeoTIFF publication, live GEE, cloud, deployment or A4 work is included.

## Local operator

Use `dev/gis_ui/a3_demo.py --runtime-dir <owned-T0-root>` in an interactive
terminal after the independently reviewed039/040 are applied to both attested Local
DBs. Passwords are entered privately and not written to evidence. This starts only
the existing LDD validation/prepare workers plus API/Vite; the one-shot verifier
has a separate strict approval. Ctrl+C uses the existing lifecycle shutdown.
Runtime evidence stays outside Git under the owned runtime's `a3-ldd-publication`.
