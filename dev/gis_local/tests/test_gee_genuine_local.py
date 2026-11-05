"""No Docker/DB calls: prove 047 runner stops before any unsafe transport."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

path=Path(__file__).resolve().parents[1]/'gee_genuine_local.py'
spec=importlib.util.spec_from_file_location('test_https_operator',path)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)


def stub(tmp_path):
    obj=object.__new__(m.GenuineLocal);obj.output=tmp_path
    obj.proof=lambda:None;obj.reviewed=lambda p:'a'*64
    obj.db=SimpleNamespace(instance='b'*32,transport=lambda *a,**k:pytest.fail('DDL transport reached'))
    review=tmp_path/'review.json';review.write_text(json.dumps({'approval':'local_apply_after_rollback_review'}))
    (tmp_path/'probe.json').write_text(json.dumps({'sha256':'a'*64,'runtime_instance':obj.db.instance,
        'databases':{d:'rolled_back_lifecycle' for d in m.DATABASES}}))
    return obj,review


@pytest.mark.parametrize('db',m.DATABASES)
def test_mismatch_in_either_database_never_replays_or_updates_ledger(tmp_path,db):
    obj,review=stub(tmp_path)
    obj.sql=lambda sql,database,**kw:'c'*64 if database==db else None
    with pytest.raises(RuntimeError,match='CHECKSUM_DRIFT'):obj.migrate(review)


def test_unknown_target_fails_before_review_or_sql(tmp_path):
    obj,review=stub(tmp_path)
    def fail():raise RuntimeError('UNKNOWN_TARGET')
    obj.proof=fail;obj.sql=lambda *a,**k:pytest.fail('SQL reached')
    with pytest.raises(RuntimeError,match='UNKNOWN_TARGET'):obj.migrate(review)


def test_stale_rollback_evidence_fails_before_ddl(tmp_path):
    obj,review=stub(tmp_path);obj.sql=lambda *a,**k:None
    v=json.loads((tmp_path/'probe.json').read_text());v['sha256']='c'*64
    (tmp_path/'probe.json').write_text(json.dumps(v))
    with pytest.raises(RuntimeError,match='ROLLBACK_PROOF'):obj.migrate(review)


def test_probe_review_does_not_approve_persistent_apply(tmp_path):
    obj,review=stub(tmp_path);obj.sql=lambda *a,**k:None
    review.write_text(json.dumps({'approval':'local_rollback_probe_only'}))
    with pytest.raises(RuntimeError,match='APPLY_REVIEW'):obj.migrate(review)
