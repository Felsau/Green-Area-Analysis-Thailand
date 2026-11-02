"""Negative startup controls: no Docker, Auth, credentials or database calls."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
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
