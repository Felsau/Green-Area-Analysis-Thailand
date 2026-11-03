"""Linux actual original/object bytes; no staged-file dependency."""
import importlib.util
from pathlib import Path
import pytest
from gis_worker import ldd_prepare_provider as prepare
from gis_worker.ldd_publication_child import verify,VERSION
spec=importlib.util.spec_from_file_location('a3_native_base',Path(__file__).with_name('test_ldd_prepare_native.py'))
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)

def objects(tmp_path):
    packet,source,stage=base.setup(tmp_path)
    candidate=prepare.prepare(packet,source_root=source,staging_root=stage)
    root=tmp_path/'objects';root.mkdir()
    outputs=prepare.build(packet,source_root=source)
    for kind,raw in outputs.items():(root/(candidate['artifacts'][kind]['sha256']+'.json')).write_bytes(raw)
    return {'prepare_request':packet,'candidate':candidate},source,root

def test_recomputes_original_and_immutable_objects(tmp_path):
    packet,source,root=objects(tmp_path)
    report=verify(packet,source_root=source,objects=root)
    assert report=={**packet['candidate'],'verifier_version':VERSION}

@pytest.mark.parametrize('mode',['missing','corrupt','source_missing','proof_changed'])
def test_publication_byte_failures(tmp_path,mode):
    packet,source,root=objects(tmp_path);path=next(root.iterdir())
    if mode=='missing':path.unlink()
    elif mode=='corrupt':path.write_bytes(b'{}')
    elif mode=='source_missing':next(source.iterdir()).unlink()
    else:packet['candidate']['valid']=False
    with pytest.raises((OSError,ValueError)):verify(packet,source_root=source,objects=root)

def test_no_arbitrary_native_input(tmp_path):
    packet,source,root=objects(tmp_path);packet['path']='/etc/passwd'
    with pytest.raises(ValueError):verify(packet,source_root=source,objects=root)
