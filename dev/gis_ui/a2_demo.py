"""Interactive Local A2 Preview, reusing the existing demo auth/lifecycle.

Starts only LDD validation + Prepare (two approved workers, room for verifier).
Other legacy/synthetic queue providers are not started by this focused launcher.
No migration, dotenv, GEE, Cloud, activation, publish or credential output.
"""
import argparse
import importlib.util
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir',type=Path,required=True)
    args=parser.parse_args()
    operator=load('a2_demo_operator',HERE.parent/'gis_local/ldd_prepare_local.py')
    demo=load('a2_demo_existing',HERE/'phase5_demo.py')
    demo.local_target=lambda root:operator.LddPrepareLocal(root)
    original=demo.Demo
    class A2Demo(original):
        def start(self):
            super().start(launchers=(lambda:demo.p.p.m.LddContainer(self.local),lambda:operator.PrepareContainer(self.local)))
    demo.Demo=A2Demo
    sys.argv=[sys.argv[0],'start','--runtime-dir',str(args.runtime_dir)]
    return demo.main()


if __name__=='__main__':
    raise SystemExit(main())
