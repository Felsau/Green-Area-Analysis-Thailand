"""Local W5 demo: upload -> validate -> prepare -> verify -> publish -> Dashboard for real LDD data.

The A3 demo (a3_demo.py) on the current ledger (027-052): LDD validation and Prepare workers only (two approved
workers; the one-shot trusted verifiers fit within the existing four-worker guard). Reuses the existing demo
auth/lifecycle; the broad activation gate stays closed. No migration, dotenv, GEE or Cloud.
"""
import argparse
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module; spec.loader.exec_module(module); return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir', type=Path, required=True)
    args = parser.parse_args()
    operator = load('w5_demo_operator', HERE.parent / 'gis_local/ldd_publication_v2_local.py')
    demo = load('w5_demo_existing', HERE / 'phase5_demo.py')
    demo.local_target = lambda root: operator.LddPublicationV2Local(root)
    original = demo.Demo
    class W5Demo(original):
        def start(self):
            super().start(launchers=(lambda: demo.p.p.m.LddContainer(self.local), lambda: operator.a3.a2.PrepareContainer(self.local)))
    demo.Demo = W5Demo
    sys.argv = [sys.argv[0], 'start', '--runtime-dir', str(args.runtime_dir)]
    return demo.main()


if __name__ == '__main__':
    raise SystemExit(main())
