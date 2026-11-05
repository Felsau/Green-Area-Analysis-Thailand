"""Packaged entry point: offline test only; no Live branch or credential input."""
import sys


def main():
    if sys.argv[1:] != ['--offline-probe']:
        raise SystemExit('GEE_BOUNDARY_LIVE_STARTUP_DISABLED')
    # No environment configuration, ADC or credential bootstrap.
    sys.path[:0]=['/app','/app/tests','/sdk']
    import os
    os.environ.clear()
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
    os.environ['PYDANTIC_DISABLE_PLUGINS']='__all__'
    import pytest
    raise SystemExit(pytest.main(['-q','--tb=short','-p','no:cacheprovider',
        '--basetemp','/tmp/boundary-tests','/app/tests/test_gee_credential_boundary.py',
        '/app/tests/test_gee_genuine_foundation.py','/app/tests/test_gee_sdk_transport.py']))


if __name__=='__main__':
    main()
