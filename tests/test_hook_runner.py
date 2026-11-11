import importlib.util
import io
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[1] / "scripts" / "hook_runner.py"
    spec = importlib.util.spec_from_file_location("hook_runner_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke(runner, monkeypatch, capsys, response=None, failure=None, event="Stop"):
    def run(*args, **kwargs):
        assert kwargs.get("input") == b'{"cwd":"test"}'
        if failure:
            raise failure
        return response
    monkeypatch.setattr(runner.subprocess, "run", run)
    monkeypatch.setattr(runner.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b'{"cwd":"test"}')))
    result = runner.main([event])
    output = capsys.readouterr()
    assert result == 0
    return json.loads(output.out)


@pytest.mark.parametrize("code", [1, 2, 127])
def test_bootstrap_failure_cannot_accidentally_block_stop(runner, monkeypatch, capsys, code):
    response = SimpleNamespace(returncode=code, stdout=b'{"decision":"block","reason":"must not escape"}', stderr=b"startup failed")
    assert invoke(runner, monkeypatch, capsys, response=response) == {}


@pytest.mark.parametrize("data", [b"not json", b"[]", b'{"schema_version":1,"status":"error"}', b'{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"wrong event"}}'])
def test_malformed_or_wrong_protocol_is_noop(runner, monkeypatch, capsys, data):
    assert invoke(runner, monkeypatch, capsys, response=SimpleNamespace(returncode=0, stdout=data, stderr=b"")) == {}


def test_valid_stop_decision_survives_wrapper(runner, monkeypatch, capsys):
    result = {"decision": "block", "reason": "Complete this run's staged memory"}
    assert invoke(runner, monkeypatch, capsys, response=SimpleNamespace(returncode=0, stdout=json.dumps(result).encode(), stderr=b"")) == result


def test_timeout_does_not_escape(runner, monkeypatch, capsys):
    assert invoke(runner, monkeypatch, capsys, failure=subprocess.TimeoutExpired("hook", 2)) == {}
