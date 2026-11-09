"""Negative startup controls: no Docker, Auth, credentials or database calls."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import threading
from unittest.mock import Mock
import pytest

spec=importlib.util.spec_from_file_location('phase5_demo_unit',Path(__file__).parents[1]/'phase5_demo.py')
demo=importlib.util.module_from_spec(spec);sys.modules[spec.name]=demo;spec.loader.exec_module(demo)


def test_wrong_branch_stops_before_local_operator(monkeypatch,tmp_path):
    monkeypatch.setattr(demo.m,'fingerprint',lambda:{'branch':'main'})
    operator=Mock(side_effect=AssertionError('must not access target'))
    monkeypatch.setattr(demo.p,'Phase4Local',operator)
    with pytest.raises(RuntimeError,match='WRONG_BRANCH'):demo.local_target(tmp_path)
    operator.assert_not_called()


def test_noninteractive_start_never_falls_back_to_echoed_password(monkeypatch,tmp_path):
    monkeypatch.setattr(sys,'argv',['demo','start','--runtime-dir',str(tmp_path)])
    monkeypatch.setattr(sys,'stdin',SimpleNamespace(isatty=lambda:False))
    password=Mock(side_effect=AssertionError('must not prompt'))
    operator=Mock(side_effect=AssertionError('must not connect'))
    monkeypatch.setattr(demo.getpass,'getpass',password);monkeypatch.setattr(demo,'Demo',operator)
    with pytest.raises(RuntimeError,match='INTERACTIVE_TERMINAL_REQUIRED'):demo.main()
    password.assert_not_called();operator.assert_not_called()


@pytest.mark.parametrize('password',['short','x'*73])
def test_invalid_demo_password_does_not_read_keys_or_create_accounts(password):
    session=demo.Demo.__new__(demo.Demo);session.local=Mock()
    with pytest.raises(RuntimeError,match='DEMO_PASSWORD_LENGTH'):session.accounts(password)
    session.local.local_keys.assert_not_called();session.local.sql.assert_not_called()


def closing_session(tmp_path,baseline):
    session=demo.Demo.__new__(demo.Demo)
    session.vite=session.server=None;session.workers=[];session.before={};session.initial_source={}
    session.run='test';session.smoke_exit=None;session.output=tmp_path
    session.local=SimpleNamespace(baseline=baseline,approved=[])
    return session


def test_close_retries_a_baseline_check_interrupted_by_ctrl_c(monkeypatch,tmp_path):
    monkeypatch.setattr(demo,'source',lambda:{});monkeypatch.setattr(demo.time,'sleep',lambda _:None)
    baseline=Mock(side_effect=[RuntimeError('LOCAL_DOCKER_COMMAND_FAILED'),{}])
    assert closing_session(tmp_path,baseline).close() is True
    assert baseline.call_count==2


def test_close_reports_failure_when_the_baseline_stays_unavailable(monkeypatch,tmp_path):
    monkeypatch.setattr(demo,'source',lambda:{});monkeypatch.setattr(demo.time,'sleep',lambda _:None)
    baseline=Mock(side_effect=RuntimeError('FOREIGN_NETWORK_MEMBER_REJECTED'))
    assert closing_session(tmp_path,baseline).close() is False
    report=json.loads((tmp_path/'local-results.json').read_text(encoding='utf-8'))
    assert report['cleanup_errors']==['BASELINE_CHECK_FAILED'] and report['checks']['baseline_checked'] is False


def running(dead=False):
    return SimpleNamespace(vite=SimpleNamespace(poll=lambda:1 if dead else None),workers=[])


def test_ctrl_c_arriving_after_a_child_exit_is_a_normal_stop():
    stopped=threading.Event();threading.Timer(.7,stopped.set).start()
    demo.wait_until_stopped(running(dead=True),stopped,grace=5)
    assert stopped.is_set()


def test_a_component_dying_without_ctrl_c_still_fails():
    with pytest.raises(RuntimeError,match='DEMO_COMPONENT_STOPPED'):
        demo.wait_until_stopped(running(dead=True),threading.Event(),grace=0)
