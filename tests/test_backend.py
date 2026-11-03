import shutil
import subprocess

import pytest

from pokeagent.backend import BackendError, ClaudeCliBackend, StubBackend


class FakeRunner:
    """Stands in for subprocess.run; records calls, returns a canned result."""

    def __init__(self, result=None, exc=None):
        self.calls = []
        self._result = (
            result
            if result is not None
            else subprocess.CompletedProcess(
                args=[], returncode=0, stdout='{"button": "A"}', stderr=""
            )
        )
        self._exc = exc

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if self._exc is not None:
            raise self._exc
        return self._result


def _patch_which(monkeypatch, path="/fake/claude"):
    monkeypatch.setattr(shutil, "which", lambda name: path)


def test_stub_returns_replies_in_order():
    b = StubBackend(replies=["one", "two"])
    assert b.choose("p1") == "one"
    assert b.choose("p2") == "two"


def test_stub_default_forever_after_replies():
    b = StubBackend(replies=["one"], default="D")
    assert b.choose("p") == "one"
    assert b.choose("p") == "D"
    assert b.choose("p") == "D"


def test_stub_records_prompts_and_name():
    b = StubBackend()
    b.choose("hello")
    b.choose("world")
    assert b.prompts == ["hello", "world"]
    assert b.name == "stub"


def test_stub_default_reply():
    b = StubBackend()
    assert b.choose("p") == '{"thinking": "stub", "button": "A"}'


def test_claude_cli_command_line_and_kwargs(monkeypatch):
    _patch_which(monkeypatch)
    runner = FakeRunner()
    b = ClaudeCliBackend(model="haiku", runner=runner)
    out = b.choose("press a button")
    assert out == '{"button": "A"}'
    cmd, kwargs = runner.calls[0]
    assert cmd == [
        "/fake/claude",
        "-p",
        "--tools",
        "",
        "--no-session-persistence",
        "--model",
        "haiku",
        "--output-format",
        "text",
    ]
    assert kwargs["input"] == "press a button"
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["timeout"] == 120
    assert kwargs["encoding"] == "utf-8"


def test_claude_cli_name_and_model(monkeypatch):
    _patch_which(monkeypatch)
    b = ClaudeCliBackend(model="sonnet", runner=FakeRunner())
    assert b.name == "claude:sonnet"


def test_claude_cli_timeout(monkeypatch):
    _patch_which(monkeypatch)
    runner = FakeRunner(exc=subprocess.TimeoutExpired(cmd="claude", timeout=7))
    b = ClaudeCliBackend(timeout_s=7, runner=runner)
    with pytest.raises(BackendError, match="timeout after 7s"):
        b.choose("p")


def test_claude_cli_nonzero_exit_includes_stderr(monkeypatch):
    _patch_which(monkeypatch)
    proc = subprocess.CompletedProcess(
        args=[], returncode=3, stdout="", stderr="boom error"
    )
    b = ClaudeCliBackend(runner=FakeRunner(result=proc))
    with pytest.raises(BackendError, match="exit 3: boom error"):
        b.choose("p")


def test_claude_cli_missing_executable(monkeypatch):
    _patch_which(monkeypatch, path=None)
    with pytest.raises(BackendError, match="not on PATH"):
        ClaudeCliBackend()
