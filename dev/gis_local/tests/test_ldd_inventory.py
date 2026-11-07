"""The inventory tool must start where the Windows wrapper mounts it: /app/ldd_inventory.py."""
import importlib.util
from pathlib import Path, PurePosixPath
import sys

path = Path(__file__).resolve().parents[1] / 'ldd_inventory.py'
spec = importlib.util.spec_from_file_location('test_ldd_inventory_module', path)
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)


def test_a_file_mounted_directly_under_app_has_no_grandparent_to_look_in():
    assert m.source_roots(PurePosixPath('/app')) == [PurePosixPath('/app'), PurePosixPath('/')]


def test_the_repository_layout_still_finds_the_backend_folder():
    roots = m.source_roots(PurePosixPath('/repo/dev/gis_local'))
    assert roots[0] == PurePosixPath('/repo/dev/gis_local') and PurePosixPath('/repo/green-area-backend') in roots
