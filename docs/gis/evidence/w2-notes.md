# W2 notes: open items and handoff corrections

Installer: `dev/gis_install/install_migrations.py`. Test: `dev/gis_install/test_pg17.sh`.
Evidence: `w2-gis-readiness.json` (postgres:17), `w2-gis-readiness-supabase-image.json`
(pinned Supabase image), `w2-install-runs.txt` (full log). All values come from throwaway
containers, and the project ref `pgtestlocalcontainer` is fake.

**Nothing has been run against the real project.** The Supabase results below come from the
image pinned in `dev/gis_local/images.lock.json` (PostgreSQL 17.6, tag 17.6.1.136).

## Open items before any real install

### 1. Independent reviews are out of date
Commit `f150e92` changed 027 and re-pinned the checksums from 027 to 052. It left the 16
`dev/gis_local/*-review.json` records on the old bytes and says they must be redone, not
rewritten. `t1_database.py` refused to run 027-029 without a matching review, but this
installer does not check reviews. W2's evidence shows the migrations install. It does not
replace those reviews.

### 2. Two account assumptions are unconfirmed on the real project
Both hold on the pinned image. The project owner can check them with this read-only query in
the SQL Editor, connected as `postgres`:

```sql
SELECT pg_has_role('postgres','pg_read_all_data','MEMBER') AS read_all_data,
       pg_has_role('postgres','service_role','SET')        AS set_service_role;
```

Both must be `true`, and the installer's preflight refuses to start otherwise.

- **`service_role`:** only this role can execute `gis_readiness()`, so the installer uses
  `SET ROLE service_role`.
- **`pg_read_all_data`:** see correction 1 below.

### 3. No-op GRANT and REVOKE statements on Supabase-like accounts
Each target produced 14 warnings of the form `no privileges could be revoked` or `no privileges
were granted`, on schemas `gis` and `public`, in 027, 029, 031 and 043-047. They are in
`w2-install-runs.txt`.

After install, the test checks these on both targets, and all pass:
- no client role can use schema `gis` or reach a `gis` table
- `PUBLIC`, `anon` and `authenticated` cannot execute any GIS function
- `gis_owner` keeps no `CREATE` on `public`

These statements do nothing, so they are not what enforces those results. For example,
`gis_native_worker` gets `USAGE` on `public` through `PUBLIC`, not through 031's `GRANT`. A
project that has revoked `USAGE` on `public` from `PUBLIC` would behave differently.

The owner should review them with item 1.

### 4. `postgres` can read every `gis` table
On the pinned image, `pg_read_all_data` gives `postgres` read access to the `gis` schema and
its tables (checked on `gis.environment`), and it also has `BYPASSRLS`. Client roles cannot do
this, but the review should know the migrator account can.

### 5. The role step commits separately
`gis_native_worker` is created in its own transaction before 027. If 027 then fails, the role
remains. A re-run accepts it, but it is a change on the target even though no migration applied.

## Handoff corrections (`handoff-2026-11-08-runtime.md`)

1. **Non-superuser requirement (missing from the handoff, found in testing).** 027 line 67
   revokes on schema `gis` before it assumes `gis_owner`. A plain non-superuser with
   `CREATEROLE` fails there with `permission denied for schema gis`. It passes only because
   Supabase's `postgres` is in `pg_read_all_data`, which turns the error into a no-op warning.
   So section 4's "ready in version and privileges" is not sufficient by itself.
2. **Item 5, roles.** Do not pre-create `gis_owner` or `gis_worker`. 027 creates them and raises
   `GIS_ROLE_COLLISION` if they exist without its marker comment. `.env.example` has the same
   wrong instruction.
3. **Item 5, prerequisites.** The list is incomplete. 027 and 010 also need `public.profiles`,
   `public.provinces`, `auth.users`, `auth.uid()` and the roles `anon`, `authenticated` and
   `service_role`. The test replays legacy 000-026 instead of 007 alone.
4. **`gis_native_worker`.** No migration creates it, only `dev/gis_worker/identity_probe.sql`.
   The real project needs it too, and 031 and 032 fail without it. The installer creates it.
5. **Item 1, "session-local".** `set_config(..., true)` is transaction-local, so the values are
   declared once per migration.
6. **Test command.** A bare `docker run postgres:17` makes `postgres` a superuser, which would
   hide correction 1. The test creates a non-superuser `postgres` instead.
7. **Section 4, file count.** It says 20 migration files, but 027-048 is 22. A re-grep of all 22
   for `CREATE EXTENSION`, `ALTER SYSTEM`, `CREATE EVENT TRIGGER`, `CREATE LANGUAGE` and
   `ALTER ROLE` found none.

## Limits of this evidence
- The postgres:17 `auth` schema and roles are stand-ins (`dev/gis_install/empty_db_baseline.sql`).
  The Supabase image has the real ones, but the auth, REST and gateway services were not running.
- The test proves installation, re-runs and privileges. It does not exercise the backend, the
  worker or any GIS function through PostgREST.
- `--allow-hosted` has never been used, and a TLS connection (`sslmode`) has not been tested.
