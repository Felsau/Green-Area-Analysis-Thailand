"""Packaged entry for the A6 egress proof image. No credential, token or Live branch.

argv is exactly one role. One JSON config line arrives on stdin from the operator
launcher (never environment, files or CLI values). The environment is cleared.
"""
import json
import os
import sys

ROLES = ('relay', 'probe-recorder', 'probe-worker')


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ROLES:
        raise SystemExit('GEE_EGRESS_ROLE_REJECTED')
    sys.path[:0] = ['/app']
    os.environ.clear()
    raw = sys.stdin.readline(65537)
    if not raw or len(raw) > 65536:
        raise SystemExit('GEE_EGRESS_CONFIG_REJECTED')
    config = json.loads(raw)
    if sys.argv[1] == 'relay':
        from gis_worker.gee_egress_relay import Relay
        Relay(config).serve()
    else:
        if not isinstance(config, dict) or config.get('role') != sys.argv[1]:
            raise SystemExit('GEE_EGRESS_ROLE_REJECTED')
        from gis_worker.gee_egress_probe import main as probe
        probe(config)


if __name__ == '__main__':
    main()
