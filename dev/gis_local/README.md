# GIS T0 — isolated local foundation

T0 prepares infrastructure, safety checks and contracts only. It does **not**
implement GIS routes, schema, users/roles, validation workers, UI, uploads or GEE.
The existing application, migrations and deployment configuration are unchanged.

## Choice of environment

Use a **local Supabase core**: PostgreSQL, Auth, PostgREST and its optional Kong
gateway, pinned to image digests from Supabase `self-hosted/v0.8.3`. Plain
PostgreSQL cannot exercise Auth-issued JWT → HTTP RPC → RLS end to end.

The Supabase CLI is another valid future option, but `start` applies local
migrations/seed and its documented settings do not provide the same per-container
limits before startup. This T0 uses a separate four-service Compose file, creates
containers stopped, verifies them, then starts exact owned IDs. It does not
install the CLI or run the repository's `docker-compose.yml`.

Upstream references:

- [Supabase Docker](https://supabase.com/docs/guides/self-hosting/docker)
- [Pinned upstream Compose](https://github.com/supabase/supabase/blob/self-hosted/v0.8.3/docker/docker-compose.yml)
- [Official Kong override](https://github.com/supabase/supabase/blob/self-hosted/v0.8.3/docker/docker-compose.kong.yml)
- [CLI workflow](https://supabase.com/docs/guides/local-development/cli-workflows)

The upstream default is Envoy. Kong here is the upstream optional local gateway;
this is not a recommendation to replace any production gateway. Studio, Storage,
Realtime, Functions, Analytics and a paid/cloud worker are not needed for T0.

## Isolation and resources

| Service | Maximum RAM / swap ceiling | CPU | PID limit |
|---|---:|---:|---:|
| db | 2 GiB / 2 GiB | 2 | 256 |
| auth | 256 MiB / 256 MiB | 0.5 | 128 |
| rest | 256 MiB / 256 MiB | 0.5 | 128 |
| gateway | 512 MiB / 512 MiB | 1 | 256 |

Total configured RAM ceiling: **3 GiB**, CPU: **4**. Disk is not a hard per-volume
quota: startup requires 10 GiB free and the new volumes must be monitored.

- Only `127.0.0.1:55421` (gateway) is published. The DB has no host port: migrations
  use identity-checked `docker exec`; future Docker workers use internal `db:5432`.
- DB/Auth/REST use `green-area-gis-t0-internal`. Gateway also uses exactly one
  project bridge, `green-area-gis-t0-ingress`, for host access. Other attached
  networks fail preflight; the gateway has potential egress and this is not a
  four-service zero-egress claim. Docker 29.8 deliberately skips port rules for
  internal-only networks, so that topology cannot expose host Auth/RPC endpoints.
  Kong anonymous reports are explicitly disabled and checked by a boolean-only
  Docker projection before startup; no environment array is returned.
  No Docker socket, repository, old `.env`, GEE files or home-directory
  mount. Only three pinned vendor bootstrap files and a generated gateway config
  are read-only binds from the explicit external runtime directory.
- Named volumes are `green-area-gis-t0-data` and `green-area-gis-t0-db-config`.
  Labels carry project/scope/instance ownership. Unknown existing resources are
  rejected, not reset, adopted, stopped or removed.
- Capability drops, no-new-privileges, bounded logs, readonly non-DB root filesystems
  and fixed images/ports/mount destinations are checked before starting.
- Kong writes to `/tmp/kong`; do not mask `/usr/local/kong`, which also contains
  packaged native libraries.

## Explicit configuration, no inherited production settings

`local.example.json` is the nonsecret allowlist and has `GIS_ENABLED=false`.
There is no `.env` discovery, no application import and no GEE initialization.
The guard accepts only the exact local project, literal loopback API URL and
Docker-internal database identity. Cloud URLs, alternate hosts, embedded credentials, query
strings, unknown fields and string-valued flags are rejected without echoing them.

`manage.py` passes a small OS-only environment to Docker and explicitly sets the
local Docker socket, a new empty registry credential store, Compose file/project,
working directory and runtime env file. It never copies the user's Docker config,
Supabase keys or GEE credentials. Shell variables cannot override Compose values.

Preparation generates **new local-only** random development values outside the
repository. They are consumed internally by the local services, not printed or
committed. Do not run resolved `compose config`, `docker inspect` without a field
projection, `env`, or raw diagnostic commands that print those values. Local
gateway role tokens expire after seven days; rotation/rebootstrap is an explicit
future operation, not a reason to use production keys.

## Runbook

Use Python 3.11+ and Docker Desktop's Linux engine. Commands below are examples;
choose an explicit **new directory outside this repository** as `<runtime-dir>`.
An existing directory with unrelated contents is refused. Do not enter the literal
angle-bracket placeholder in the commands.

```text
python -I -B dev/gis_local/target_guard.py --config dev/gis_local/local.example.json
python -I -B -m unittest discover -s dev/gis_local/tests -v
python -I -B dev/gis_local/manage.py prepare --runtime-dir <runtime-dir>
python -I -B dev/gis_local/manage.py start --runtime-dir <runtime-dir>
python -I -B dev/gis_local/manage.py verify --runtime-dir <runtime-dir>
python -I -B dev/gis_local/manage.py stop --runtime-dir <runtime-dir>
```

`prepare` downloads only hash-locked vendor bootstrap scripts and generates local
settings. `start` checks ownership, engine, free disk and loopback port availability;
pulls missing digest-locked images; checks Compose without printing resolved values;
creates stopped containers; inspects safety; starts DB → Auth → REST → gateway.

The base image/vendor bootstrap and Auth run **Supabase's own infrastructure
initialization/migrations**. No application migrations 000–026 or proposed GIS
027–029, seeds, cloud resources or user accounts are run/created by these tools.

`verify` makes only local read-only metadata queries, Auth health GET and a
keyless REST GET that must be rejected (401). It checks the cluster identity and
absence of GIS/known application tables. This is readiness, not a user login,
application RPC, RLS or GIS end-to-end test.

`stop` preserves volumes/data and only stops exact owned IDs. After an intentionally
reviewed config change, stop the old owned services, run explicit `reconfigure`,
then `start`; `reconfigure` refuses running resources and only acknowledges a
config fingerprint. It does not migrate or erase the database. No automatic
volume deletion/global prune is provided. A half-initialized failed bootstrap
must be investigated before an independently scoped cleanup.

On restricted Windows runners, set TEMP/TMP to a writable isolated test directory
outside the repository before tests. The tests create only fake `.env` sentinels,
synthetic config and fake Docker metadata. No real credential fixture is read.

## Limits and handoff to T1

`target_guard.py` is a development/test seam, not newly installed protection on
the existing application's endpoints. Its successful fake callback test does not
write SQL. T1 must add the approved database marker/schema version and database
authorization; T2 must wire the guard to the actual new API write boundary.
The T0 verifier intentionally rejects the GIS schema and five known application tables: update its stage-specific
proof contract during approved T1 work instead of disabling checks.

Contracts are in [contracts.json](contracts.json) and
[phase1-contracts.md](../../docs/gis/phase1-contracts.md). Auth/signup is disabled
for T0 and there are no users. Real Auth/RPC/RLS tests require explicit synthetic
user/bootstrap work in T1–T5. Local mode needs no cloud subscription; the machine
must be running and the worker in T3 will not become always-on through Free Web
hosting. Do not deploy or link this runtime to Supabase Cloud.
