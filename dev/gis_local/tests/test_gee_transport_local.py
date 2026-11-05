"""Forward-only migration operator fails before ANY database transport."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

path=Path(__file__).resolve().parents[1]/'gee_transport_local.py'
spec=importlib.util.spec_from_file_location('test_a6_transport_operator',path)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)


def local_stub(tmp_path,approval='local_apply_after_rollback_review'):
    obj=object.__new__(m.TransportLocal)
    obj.output=tmp_path
    obj.proof=lambda:None
    obj.reviewed=lambda p:'a'*64
    obj.db=SimpleNamespace(instance='b'*32,transport=lambda *a,**k:pytest.fail('database transport called'))
    review=tmp_path/'review.json';review.write_text(json.dumps({'approval':approval}))
    (tmp_path/'probe.json').write_text(json.dumps({'sha256':'a'*64,'runtime_instance':obj.db.instance,
        'databases':{d:'rolled_back_lifecycle' for d in m.DATABASES}}))
    return obj,review


@pytest.mark.parametrize('db',m.DATABASES)
def test_applied_checksum_mismatch_never_reapplies_or_updates_ledger(tmp_path,db):
    obj,review=local_stub(tmp_path)
    obj.sql=lambda sql,database,**k:'c'*64 if database==db else None
    with pytest.raises(RuntimeError,match='APPLIED_CHECKSUM_DRIFT'):
        obj.migrate(review)


def test_probe_approval_cannot_authorize_persistent_apply(tmp_path):
    obj,review=local_stub(tmp_path,'local_rollback_probe_only')
    obj.sql=lambda *a,**k:pytest.fail('pre-approval SQL called')
    with pytest.raises(RuntimeError,match='APPLY_REVIEW_REQUIRED'):obj.migrate(review)


def test_wrong_target_proof_stops_before_review_or_transport(tmp_path):
    obj,review=local_stub(tmp_path)
    def denied():raise RuntimeError('WRONG_TARGET')
    obj.proof=denied
    obj.reviewed=lambda *a:pytest.fail('review reached before proof')
    with pytest.raises(RuntimeError,match='WRONG_TARGET'):obj.migrate(review)


def test_missing_or_other_runtime_rollback_proof_stops_apply(tmp_path):
    obj,review=local_stub(tmp_path)
    v=json.loads((tmp_path/'probe.json').read_text());v['runtime_instance']='c'*32
    (tmp_path/'probe.json').write_text(json.dumps(v))
    obj.sql=lambda *a,**k:pytest.fail('SQL called with stale proof')
    with pytest.raises(RuntimeError,match='ROLLBACK_PROOF_REQUIRED'):obj.migrate(review)
