# A6.4d-2 — Offline Runtime, Identity and Transport Boundary

This prepares an **offline test image**, not an approved Live GEE worker.
Real credentials, Google transport, live startup and selective egress remain
blocked. No schema, queue, legacy method, API or dashboard behavior changes.

## Image and command authority

`gee-runtime-image.lock.json` pins the derived image ID, approved base ID,
source hashes, dependency pins and command. `gee-runtime-review.json` separately
approves the exact one-shot probe image after source/build-record review.
Image labels alone cannot authorize an existing image. Build rejects every
pre-existing derived tag instead of replacing it or trusting its labels.

The build uses the existing approved local Mock image, classic builder,
`--pull=false --network=none`, COPY-only context, no RUN/install/download.
Context contains only worker Python sources, Dockerfile and source manifest.
Base layers, inherited environment/labels and reviewed source are verified.

The approved command is:

`/usr/local/bin/python3 -I -B /app/gis_worker/gee_runtime_probe.py --offline-probe`

Default or unknown commands exit disabled before reading stdin or importing
project/Google credential code. The operator allows only its newly created
container ID with exact image, command, labels, non-root user, environment,
no mounts, readonly root, CPU1, memory/swap1GiB, PIDs64, FD64, core0,
file-size16384, bounded stdout16384 and wall time30s. Log driver is none;
capabilities are dropped and no-new-privileges is required. Temporary /tmp is
64MiB noexec/nosuid. Only the verified temporary probe is removed afterwards.

## Identity and credential boundary

`RuntimeBinding.from_claim` compares the claimed worker with the trusted GIS
JWT subject supplied by the parent client. It binds schema8 rehearsal session,
policy, job, attempt, input revision/hash, V2 geometry/semantic request/method,
project/principal and a digest of the current fencing token. It uses V2 numeric
canonicalization and never treats a hash as proof of satellite authenticity.

Real project allowlist is empty and real Google principal is unset.
`DisabledGoogleCredentials` always rejects issue/renew/revoke/authorize,
without environment discovery, ADC, OAuth, files or Google auth initialization.

`InjectedCredentials` is a trusted test dependency, not a sandbox against
hostile Python callbacks. It permits exactly its registered synthetic
project/principal and binding. Fake leases have issuer/object identity,
30s maximum TTL, revocation and renewal checks, and are never serialized into
jobs, argv, reports or candidates. Renewal revokes the old fake lease; a new
provider cannot accept a token from a previous provider/attempt. Fake expiry
does not replace SQL session/lease authorization. The real delivery/renewal
mechanism still requires separate design and approval.

## Network authority

Policy identity: `gee-live-deny-external-v1`. Google endpoint allowlist: empty.
Network-layer enforcement for the offline probe is Docker `network=none`.
Before installing Python audit guards, the Linux probe verifies only loopback
exists and tests kernel denial to reserved documentation IPv4/IPv6 addresses
and an external DNS datagram destination. It makes no Google/DNS provider call.
A local-only HTTP302 fixture is read, then its external redirect is rejected
without following it. Afterwards existing network/import/credential guards
cover injected computation; Pydantic plugin discovery is disabled beforehand.

This proves **deny-all**, not selective Google endpoint access, safe DNS for a
future allowlist, authenticated TLS routing or Queue/Auth access from this image.
Those are BLOCKED. No proxy/firewall/service or route was added. The original
Mock/Native/Offline worker allowlists and internal Queue/Auth network remain
unchanged. Host-side guarded Local SQL tests are separate from the no-network
image. Never attach this probe to an external or legacy data network.

## Request accounting

`PreparedInjectedTransport` reuses `AccountedTransport` and SQL045. A trusted
server-side plan contains compute/sdk_retry/reference entries, never URLs,
commands or paths from an API payload. Fake credentials are checked before
reservation and before/after each injected evaluation. Every entry consumes a
separate durable reservation; no reset/refund on provider restart or recovery.
Existing 4 jobs,32 requests,2 attempts,120s request,180s logical job and20min
session limits remain authoritative in SQL. No migration is added or replayed.

Each successful plan entry is a **full injected observation** with the same
evidence. A failed or uncertain entry aborts, stays spent, and cannot be hidden
by a later success in the same attempt. A replacement SQL attempt can preserve
the uncertain prior charge and commit only its complete current evidence.

This does NOT prove a physical failed HTTP response followed by an automatic
SDK retry, auxiliary-reference response accounting, real SDK interception,
Google attestation, remote cancellation or satellite parity. The SDK is absent
from the prepared image and no download/install is authorized or performed.
Candidates remain injected/draft/non-publishable. Live result acceptance under
migrations044/045 remains closed even if this offline preparation passes.
