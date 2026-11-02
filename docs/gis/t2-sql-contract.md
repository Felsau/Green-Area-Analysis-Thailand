# T2 forward SQL API read contract

This is the interface for new forward migration `030_gis_api_reads.sql`. It does
not edit or replay027–029. It must pass independent review before local execution;
the guarded runner owns BEGIN, exact reviewed bytes, version30 ledger insert and
COMMIT. No cloud/production approval or SQL execution is supplied by this document.

## Migration scope

- The original GIS ledger capped versions at29. Forward030 replaces only that
  GIS check constraint with `version>=27`, leaving all applied rows/checksums intact.
- Guard requires the existing local environment marker/GUC identity and exact
  reviewed027–029 ledger checksums. Owner/RLS/worker/command functions are unchanged.
- Replace only private `gis.read`, add private projection helpers, six GIS-only
  cursor indexes and one service-role-only readiness RPC. No state/data/cache/GEE
  mutation, no new table/role, no worker or extension.

## RPCs

`public.gis_read(p_actor uuid,p_kind text,p_payload jsonb={})` retains its T1
service-role-only wrapper. The actor comes from Backend-verified JWT, never a
browser body, role claim or legacy admin header. SQL rechecks live permissions.

| Read kind | Payload | Response |
|---|---|---|
| me | {} | admin/officer/capabilities/synthetic_only/database activation gate |
| provinces, fixtures | {} | bounded reference `{data,next_cursor:null,has_more:false}` |
| dataset, edition | {id} | sanitized detail or GIS_NOT_FOUND |
| job | {id} | sanitized job detail plus `result:null|object` |
| result | {id:jobUUID} | `{job_id,state,result:null|object,error_code:null|safe_code}` |
| datasets | limit/cursor plus province/data_year/month/kind/purpose | cursor page |
| editions | required dataset_id, optional state, limit/cursor | cursor page; missing parent404 |
| jobs | limit/cursor plus state/dataset_id/edition_id and optional dataset-identity filters | cursor page |
| attempts | required job_id, limit/cursor | cursor page; missing parent404 |
| history | required edition_id, limit/cursor | cursor page; missing parent404 |
| officers | limit/cursor | admin-only cursor page |

Limit defaults20/max100. Cursor is `{created_at:timezone-aware ISO timestamp,id:UUID}`
and sorts ascending by timestamp then UUID. Attempts use `started_at` internally
but the cursor field remains `created_at`. Officer rows expose both `id` and
`user_id` as the grant subject UUID needed for Admin revocation, plus created_at;
no email, user directory, grantor identity, actor copies or extra profile fields.
Filters are typed/allowlisted SQL parameters; dynamic identifiers/fragments are
chosen solely from internal constants. Unknown keys or malformed cursors fail.

An existing queued/running/failed job without a successful result returns
`result:null` and its real state, never a fabricated successful report. Reports
are the bounded T1 synthetic protocol reports, not scientific GIS output. Job and
attempt error codes are allowlisted; unknown values become `internal_error`.
Lease tokens, worker IDs, lease times and actor columns are not read DTO fields.
Audit detail is projected to known non-actor keys; reason/title remain authorized
user-authored free text, without a promise of automated anonymisation.

`public.gis_readiness()` is service_role-only and returns nonsecret metadata:
runtime_instance, baseline_fingerprint, database_name, cluster_name, mode,
activation_enabled, contract_version=`1.1.0-t2`, migration_versions.
It returns no key, token, password, Auth user, storage credential or service config.
The Backend must compare these values against its exact attested local target
and require version30. It is not a public browser readiness endpoint and does not
replace JWT verification or pre-network local target allowlisting.
The readiness function itself refuses calls without ledger version30 using
`GIS_SCHEMA_NOT_READY`; the runner inserts that ledger row in the same transaction.
The migration queues a PostgREST schema-cache reload notification on commit.

SQL errors stay symbolic (`GIS_FORBIDDEN`, `GIS_NOT_FOUND`, `GIS_INVALID_*`);
T2 Backend maps them to safe HTTP responses without exposing raw SQL diagnostics.
