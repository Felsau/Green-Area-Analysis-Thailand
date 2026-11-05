"""Runtime isolation attestation: kernel-measured process state in a signed envelope.

Kept out of gee_genuine_runtime.py so that reviewed file (and its evidence hash) stays
byte-identical. Nothing here opens, relaxes or is consulted by the closed Live Gate.
"""
import os
import re
import time
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from gis_worker.gee_contracts import Contract, Hash
from gis_worker.gee_genuine_identity import GenuineBoundaryError
from gis_worker.gee_genuine_runtime import GenuineBinding
from gis_worker.gee_live_contracts import canonical

# H3 (trusted runtime isolation) is NOT VERIFIED. Only kernel-reported process state is
# measured below. The image id is supervisor-declared, and the nft ruleset is neither
# installed nor measured here. No Live Gate depends on or is opened by this module.
H3_STATUS = 'NOT_VERIFIED'
NET_NS = r'^net:\[[0-9]{1,20}\]$'


class ProcessMeasurement(Contract):
    """Kernel-reported state of one process, read by the supervisor from /proc."""
    pid: Annotated[int, Field(strict=True, ge=1)]
    uid: Annotated[int, Field(strict=True, ge=1)]  # real == effective == saved == fs
    no_new_privs: bool
    seccomp_mode: Annotated[int, Field(strict=True, ge=0, le=2)]
    net_ns: Annotated[str, Field(pattern=NET_NS)]


def measure_process(pid, *, proc='/proc') -> ProcessMeasurement:
    try:
        if type(pid) is not int or pid <= 0:
            raise ValueError()
        base = Path(proc, str(pid))
        fields = {k: v.strip() for k, _, v in (line.partition(':')
            for line in (base / 'status').read_text(encoding='ascii').splitlines())}
        uids = {int(x) for x in fields['Uid'].split()}
        if len(uids) != 1 or len(fields['Uid'].split()) != 4 or min(uids) < 1:
            raise ValueError()
        return ProcessMeasurement(pid=pid, uid=uids.pop(), no_new_privs=fields['NoNewPrivs'] == '1',
            seccomp_mode=int(fields['Seccomp']), net_ns=os.readlink(base / 'ns' / 'net'))
    except Exception:
        raise GenuineBoundaryError('GEE_RUNTIME_MEASUREMENT_REJECTED') from None


def supervisor_net_ns(*, proc='/proc') -> str:
    try:
        value = os.readlink(Path(proc, 'self', 'ns', 'net'))
        if not re.fullmatch(NET_NS, value):
            raise ValueError()
        return value
    except Exception:
        raise GenuineBoundaryError('GEE_RUNTIME_MEASUREMENT_REJECTED') from None


def _isolation_policy(worker, recorder, supervisor_ns):
    if (worker.uid == recorder.uid or worker.pid == recorder.pid
        or not worker.no_new_privs or worker.seccomp_mode != 2
        or recorder.net_ns in (worker.net_ns, supervisor_ns)):
        raise GenuineBoundaryError('GEE_RUNTIME_ISOLATION_REJECTED')


class RuntimeAttestation(Contract):
    """Supervisor-signed envelope around measured process state.

    ``image_identity='supervisor_declared'`` and ``network_enforcement='not_measured'``
    are signed on purpose: this is NOT proof of image identity or nft enforcement.
    Cannot be supplied by API request payloads; the verifier key is pinned by the
    supervisor's trusted configuration.
    """
    runtime_id: UUID
    image_id: Annotated[str, Field(pattern=r'^sha256:[0-9a-f]{64}$')]
    network_policy_sha256: Hash
    worker: ProcessMeasurement
    recorder: ProcessMeasurement
    supervisor_net_ns: Annotated[str, Field(pattern=NET_NS)]
    image_identity: Literal['supervisor_declared']
    network_enforcement: Literal['not_measured']
    attested_at: Annotated[int, Field(strict=True, ge=1)]
    supervisor_signature: Annotated[str, Field(pattern=r'^[0-9a-f]{128}$')]

    def message(self) -> bytes:
        d = self.model_dump(mode='json', exclude={'supervisor_signature'})
        return canonical(d).encode()


def create_runtime_attestation(*, runtime_id: UUID, image_id: str, network_policy_sha256: str,
    worker_pid: int, recorder_pid: int, supervisor_signer, measure=measure_process,
    supervisor_ns=supervisor_net_ns, wall=time.time) -> RuntimeAttestation:
    """The supervisor measures both processes itself; callers cannot declare isolation."""
    worker, recorder, ns = measure(worker_pid), measure(recorder_pid), supervisor_ns()
    _isolation_policy(worker, recorder, ns)
    d = {
        'runtime_id': str(runtime_id),
        'image_id': image_id,
        'network_policy_sha256': network_policy_sha256,
        'worker': worker.model_dump(mode='json'),
        'recorder': recorder.model_dump(mode='json'),
        'supervisor_net_ns': ns,
        'image_identity': 'supervisor_declared',
        'network_enforcement': 'not_measured',
        'attested_at': int(wall()),
    }
    try:
        unsigned = RuntimeAttestation.model_validate(d | {'supervisor_signature': '0' * 128})
    except ValueError:
        raise GenuineBoundaryError('GEE_RUNTIME_ATTESTATION_CONFIGURATION_REJECTED') from None
    sig = supervisor_signer(unsigned.message()).hex()
    return RuntimeAttestation.model_validate(d | {'supervisor_signature': sig})


def verify_runtime_attestation(attestation, *, supervisor_key: bytes, expected_image: str,
    expected_policy_sha256: str, binding: GenuineBinding, worker_peer: tuple,
    recorder_peer: tuple, measure=measure_process, supervisor_ns=supervisor_net_ns,
    wall=time.time):
    """True only when signature, expectations and a FRESH re-measurement all agree.

    worker_peer/recorder_peer are the (pid, uid) pinned for the IPC channels, so the
    attested processes are the ones actually spoken to. H3 stays NOT VERIFIED: image
    identity is declared and nft enforcement is not measured.
    """
    if type(attestation) is not RuntimeAttestation:
        raise GenuineBoundaryError('GEE_RUNTIME_ATTESTATION_REJECTED')
    if (type(supervisor_key) is not bytes or len(supervisor_key) != 32
        or not expected_image or not expected_policy_sha256
        or type(worker_peer) is not tuple or type(recorder_peer) is not tuple):
        raise GenuineBoundaryError('GEE_RUNTIME_ATTESTATION_REJECTED')
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        Ed25519PublicKey.from_public_bytes(supervisor_key).verify(
            bytes.fromhex(attestation.supervisor_signature),
            attestation.message()
        )
    except Exception:
        raise GenuineBoundaryError('GEE_RUNTIME_ATTESTATION_SIGNATURE_REJECTED') from None
    w, r = attestation.worker, attestation.recorder
    if (attestation.runtime_id != binding.runtime_id
        or attestation.image_id != expected_image
        or attestation.network_policy_sha256 != expected_policy_sha256
        or (w.pid, w.uid) != worker_peer or (r.pid, r.uid) != recorder_peer
        or not 0 <= wall() - attestation.attested_at <= 300):
        raise GenuineBoundaryError('GEE_RUNTIME_ATTESTATION_REJECTED')
    _isolation_policy(w, r, attestation.supervisor_net_ns)
    if (measure(w.pid) != w or measure(r.pid) != r
        or supervisor_ns() != attestation.supervisor_net_ns):
        raise GenuineBoundaryError('GEE_RUNTIME_ATTESTATION_REJECTED')
    return True
