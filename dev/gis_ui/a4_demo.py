"""Interactive A4.1 Local Preview using the existing attested demo lifecycle."""
import argparse
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runtime-dir',type=Path,required=True);args=p.parse_args()
    a4=load('a4_demo_operator',HERE.parent/'gis_local/geotiff_prepare_local.py');demo=load('a4_demo_existing',HERE/'phase5_demo.py');demo.local_target=lambda root:a4.GeoTiffPrepareLocal(root);original=demo.Demo
    class A4Demo(original):
        def start(self):super().start(launchers=(lambda:demo.p.GeoTiffContainer(self.local),lambda:a4.prepare_container(self.local)))
    demo.Demo=A4Demo;sys.argv=[sys.argv[0],'start','--runtime-dir',str(args.runtime_dir)];raise SystemExit(demo.main())
