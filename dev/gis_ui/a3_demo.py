"""Local A3 only; keeps broad gate closed and reuses existing demo lifecycle."""
import argparse
import importlib.util
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--runtime-dir',type=Path,required=True)
    args=parser.parse_args();operator=load('a3_demo_operator',HERE.parent/'gis_local/ldd_publication_local.py')
    demo=load('a3_demo_existing',HERE/'phase5_demo.py');demo.local_target=lambda root:operator.LddPublicationLocal(root)
    original=demo.Demo
    class A3Demo(original):
        def start(self):
            super().start(launchers=(lambda:demo.p.p.m.LddContainer(self.local),lambda:operator.a2.PrepareContainer(self.local)))
    demo.Demo=A3Demo;sys.argv=[sys.argv[0],'start','--runtime-dir',str(args.runtime_dir)];raise SystemExit(demo.main())
