# A6 Credential / Recorder / Restricted Egress boundary

Scope: closed/offline foundation only. No genuine Live readiness or Smoke Test
authorization. Starting HEAD `8f4a2ba066658064708a8b454cb8fb2bc44eeeca` includes
the prior foundation `c463250`; branch remains `feature/gis-data-management`.
An existing frontend test edit and the original five untracked evidence files
are preserved and excluded from this delivery.

Result: PASS for the offline implementation; Genuine Live remains NOT VERIFIED
and disabled. Independent Security Review found no unresolved High/Critical.

## Implemented and reused

- `gee_operator_delivery.py`: one-shot challenge/binding-signed mint observation
  contract; exact Sandbox/SA immutable identity, supported Earth Engine OAuth
  scope, freshness and RFC3339 expiry (fractional expiry rounded down). Produces
  the existing memory-only signed CredentialDelivery. No ADC, token paste,
  environment/CLI tokens, credential files, issuance, refresh or implicit auth.
  The real mint observer explicitly rejects; an observer signature is NOT a
  Google signature or proof from an opaque token. Trusted issuer keys are not
  provisioned by this implementation.
- `gee_recorder_channel.py`: per-job/per-lease Linux Unix packet IPC; kernel
  SCM_CREDENTIALS verifies the actual sender PID/UID on every message. Recorder
  signs nonce/binding/sequence-bound responses; canonical JSON, duplicate keys,
  truncation, deadlines and one-shot replay checks fail closed. The only worker
  operation is compute of a prebound request. No generic HTTP, URL, command,
  arbitrary path, reserve/response/seal RPC proxy or SQL input exists.
- `gee_restricted_network.py`: Linux amd64 seccomp denies non-Unix socket
  creation, namespace/ptrace/FD-theft/io_uring paths. Clean-exec child bootstrap
  checks UID/GID/groups and exact inherited Unix FDs plus supervisor pipes;
  refuses filter installation after threads exist. This is deny-all-Internet,
  not proof of selective Live egress. Unsupported platforms reject.
- Pinned TLS dialer connects literal approved public IPv4 addresses without DNS
  lookup; TLS still verifies the original exact hostname with existing Certifi
  roots. Direct-IP hostnames, private/metadata addresses, auth endpoints, proxy
  tunnels and unapproved hosts are rejected. Existing redirect, HTTP accounting,
  response-size/expiry/deadline checks remain. Auth refresh stays disabled.
- Default-drop nftables rules are generated for a NEW isolated Recorder network
  namespace. Only pinned IPv4 TCP443 is permitted; DNS/UDP/IPv6/other destinations
  remain denied. Rules are NOT installed or attested here. The supervisor must
  install/inspect the exact policy, enforce pin lifetime and session teardown,
  and prove allowed traffic/denial before Live can be approved. Endpoint/TLS
  checks alone cannot isolate Projects sharing a Google endpoint.
- `gee_boundary.Dockerfile`, `gee_boundary_entry.py`, `gee_boundary_local.py`:
  packaged Linux image from exact existing base, existing installed dependencies
  and previously approved Linux native packages. No pip, pull, downloads or
  dependency upgrades. External source/dependency manifests pin the resulting
  image by immutable ID. Offline-only entrypoint; no Live command branch.
  Probe validates its exact new container before start: network=none, no mounts,
  no logs/ports, read-only root,1GiB,1CPU,64PIDs and no new privileges. Root is
  used ONLY by the offline probe supervisor to exec/drop children to UID10001
  and UID10002 with only SETUID/SETGID capabilities. Neither child can access
  Recorder memory or create Internet sockets. Probe containers are removed;
  images/contexts/manifests remain outside Git for inspection.
- Existing Genuine Queue worker accepts the separately gated Recorder IPC
  runtime. SQL047 is reused unchanged for recorder authority, scientific seals,
  budget, attempts, fencing, immutable Candidates and completion. No migrations
  or database writes were performed. No publication/cache/pointer path changed.

## Evidence boundary

Raw evidence and generated artifacts remain outside Repository in the existing
Sandbox `a6-boundary/`; review metadata belongs in
`dev/gis_local/gee-boundary-review.json`. Windows audit hook denies all network
and credential discovery; Linux tests run packaged code without bind mounts
under network=none. All observations/signatures/tokens/TLS peers are synthetic.
The test process creates synthetic Recorder secrets only after clean exec in
the Recorder child, not in Worker configuration or environment.

Focused tests cover mint identity/scope/expiry/signature/replay; wrong peer,
duplicate/oversized packets from a correct kernel-verified UID/PID; signed nonce
forgery; forged signatures; attempted Recorder RPC bypass; extra inherited FD;
threaded seccomp installation rejection; actual prohibited socket syscalls;
private/metadata/IP-host rejection; pinned no-DNS/SNI; process timeout/crash and
fresh replacement. FakeHTTP SDK and scientific cases run in the same focused
suite. IPC replacement is not a new SQL lease-recovery test: unchanged SQL047
and prior queue evidence remain the authority for that behavior.

## Remaining prerequisites and approval

Final checks on the recorded current source: Windows Python3.12,102 passed and
15 Linux-only skipped; packaged Linux Python3.11.17,117 passed (zero failures,
exit0, no OOM). Counts overlap and are not added. Actual Linux tests prove UID,
IPC parsing/authentication, FD/thread guards and denied socket syscalls. One
vendor Python3.11 support FutureWarning was observed; no dependencies changed.
Tested image:
`sha256:3a83338c1263d85d4eb155ce3d0ad4cd5b4cfca245db5bf7704a1bc3b61ea159`.
Image/Windows evidence manifests match current source. Reviewer read source and
evidence only and did not execute tests independently.

Identity-verified, READ ONLY Local preservation checks passed12/12 across
`postgres` and `gis_t1_upgrade`: legacy/cache/Saved Areas, profiles, history,
pointers and ledger prefix unchanged; gate closed and runtime approval empty.
Applied047 SHA remains
`b04c63ca3f30a4605d8514bbbfc3195cdbe9a44dac3544b6ca19bf9a8c70962c`;
Migration000–047 were not edited, replayed or applied. Existing SQL lifecycle/
fencing evidence is reused because SQL/queue/accounting core did not change;
there was no new database-writing E2E run. Prior raw evidence remains intact.

1. Separately approve a trusted operator observer/issuer implementation and key
   provisioning. Verify actual authenticated SA metadata and mint response, token
   expiry, delivery/renewal and revocation without personal ADC/key fallback.
   No token has been issued or used in this task.
2. Approve the production Linux supervisor/Recorder packaging and network setup:
   install/attest fresh-namespace nft policy before any Internet socket, prove
   direct Worker bypass denied, pin/DNS/TLS/redirect/expiry handling, private
   credential IPC and exact image/resource identity. Current image is a tested
   offline probe, not an approved Live image.
3. Only after those proofs, independently review a startup gate change and
   provision bounded SQL047 runtime authority (currently empty). Obtain separate
   final authorization for one-worker Smoke Test with existing job/HTTP/retry/
   timeout/session limits. These counters are not hard EECU/billing caps.

No Google/GEE HTTP, Cloud/IAM/Billing changes, Production/Legacy access or real
credential use occurred. Live constants/gates remain closed. No Push/Merge/PR/
Deploy is authorized. The scoped local commit message is
`feat(gis): isolate credential recorder and offline egress boundary`.
