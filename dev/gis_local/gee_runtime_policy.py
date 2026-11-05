"""Separate offline-probe policy; never extends the existing worker allowlist."""
import hashlib
import json
import re

BASE_IMAGE = 'sha256:7557955c9e2c8611ea1396ddef6d8629c2ee1e7f193e85f0c65bcf5db9566674'
POLICY = 'gee-live-deny-external-v1'
ENTRYPOINT = ['/usr/local/bin/python3', '-I', '-B', '/app/gis_worker/gee_runtime_probe.py']
COMMAND = ['--offline-probe']
TMPFS = {'/tmp': 'rw,nosuid,noexec,size=64m,mode=1777'}
ULIMITS = {'core': (0, 0), 'nofile': (64, 64), 'fsize': (16384, 16384)}


class RuntimePolicyError(ValueError):
    pass


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def verify_probe(info, lock, *, instance, run_id, container_id):
    """Inspect only the ID returned by our launcher, never caller job metadata."""
    if (not re.fullmatch('[a-f0-9]{32}', instance)
        or not re.fullmatch('[a-f0-9]{32}', run_id)
        or not re.fullmatch('[a-f0-9]{64}', container_id)
        or lock.get('schema_version') != 1
        or lock.get('mode') != 'offline-probe-only'
        or lock.get('base_image') != BASE_IMAGE
        or not re.fullmatch('sha256:[a-f0-9]{64}', lock.get('image_id', ''))
        or lock.get('network_policy') != POLICY
        or lock.get('live_enabled') is not False):
        raise RuntimePolicyError('GEE_RUNTIME_APPROVAL_REJECTED')
    image_labels = lock.get('image_labels', {})
    if (image_labels.get('gis.a6.4d2.scope') != 'offline-runtime-probe'
        or image_labels.get('gis.a6.4d2.egress') != POLICY
        or not re.fullmatch('[a-f0-9]{64}', lock.get('source_tree_sha256', ''))
        or image_labels.get('gis.a6.4d2.source') != lock['source_tree_sha256']):
        raise RuntimePolicyError('GEE_RUNTIME_SOURCE_POLICY_REJECTED')
    config, host = info.get('Config', {}), info.get('HostConfig', {})
    labels = dict(lock.get('image_labels', {})) | {
        'gis.a6.4d2.instance': instance, 'gis.a6.4d2.run': run_id}
    if (info.get('Id') != container_id
        or info.get('Name') != '/gis-a64d2-probe-' + run_id[:12]
        or info.get('Image') != lock['image_id'] or config.get('Image') != lock['image_id']
        or config.get('Entrypoint') != ENTRYPOINT or config.get('Cmd') != COMMAND
        or config.get('User') != '65534:65534' or config.get('WorkingDir') != '/app/gis_worker'
        or config.get('Labels') != labels
        or fingerprint(config.get('Env')) != lock.get('environment_sha256')
        or config.get('OpenStdin') is not False or config.get('Tty') is not False
        or config.get('Volumes') not in (None, {})
        or info.get('Mounts') not in ([],)
        or not isinstance(info.get('NetworkSettings', {}).get('Networks'), dict)
        or set(info.get('NetworkSettings', {}).get('Networks', {})) - {'none'}):
        raise RuntimePolicyError('GEE_RUNTIME_IDENTITY_REJECTED')
    exact = {'Memory': 1073741824, 'MemorySwap': 1073741824, 'NanoCpus': 1000000000,
        'PidsLimit': 64, 'ReadonlyRootfs': True, 'Privileged': False, 'Init': True,
        'NetworkMode': 'none', 'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true'],
        'Tmpfs': TMPFS, 'PidMode': '', 'IpcMode': 'private', 'PublishAllPorts': False}
    if any(type(host.get(k)) is not type(v) or host.get(k) != v for k, v in exact.items()):
        raise RuntimePolicyError('GEE_RUNTIME_ISOLATION_REJECTED')
    if host.get('LogConfig', {}).get('Type') != 'none':
        raise RuntimePolicyError('GEE_RUNTIME_LOGGING_REJECTED')
    for key in ('Binds', 'CapAdd', 'Devices', 'DeviceRequests', 'VolumesFrom',
                'Links', 'Dns', 'DnsSearch', 'ExtraHosts', 'PortBindings'):
        if host.get(key) not in (None, [], {}):
            raise RuntimePolicyError('GEE_RUNTIME_EXTRA_ACCESS_REJECTED')
    limits = host.get('Ulimits')
    if (not isinstance(limits, list) or len(limits) != len(ULIMITS)
        or any(type(v.get('Soft')) is not int or type(v.get('Hard')) is not int for v in limits)
        or {v.get('Name'): (v.get('Soft'), v.get('Hard')) for v in limits} != ULIMITS):
        raise RuntimePolicyError('GEE_RUNTIME_ULIMIT_REJECTED')
    return {'verified': True, 'mode': 'offline-probe-only', 'live_enabled': False,
        'image_id': lock['image_id'], 'network_policy': POLICY, 'mounts': 0}


def require_live_runtime(*args, **kwargs):
    raise RuntimePolicyError('GEE_LIVE_RUNTIME_NOT_APPROVED')
