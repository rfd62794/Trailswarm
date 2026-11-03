"""Model backends: a protocol, a scripted stub, and the ``claude -p`` CLI backend.

A backend returns the model's raw reply text; parsing it into a Decision is
the caller's job (see ``decision.py``). Every backend call is isolated - no
tools, no session persistence - and bounded by a timeout.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Callable, Protocol


class BackendError(Exception):
    """The backend failed to produce a reply (missing CLI, timeout, non-zero exit)."""


class Backend(Protocol):
    """One button choice per call. ``name`` identifies the backend in logs."""

    name: str

    def choose(self, prompt: str) -> str:
        """Return the model's raw reply text for ``prompt``."""
        ...


class StubBackend:
    """Scripted backend for dry runs and tests.

    Returns ``replies`` in order, then ``default`` forever. Records every
    prompt it was asked in ``prompts``.
    """

    def __init__(
        self,
        replies: list[str] | None = None,
        default: str = '{"thinking": "stub", "button": "A"}',
    ):
        self._replies = list(replies or [])
        self._default = default
        self.prompts: list[str] = []
        self.name = "stub"

    def choose(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self._replies:
            return self._replies.pop(0)
        return self._default


class ClaudeCliBackend:
    """Calls ``claude -p`` once per step, prompt on stdin, text on stdout.

    ``runner`` defaults to ``subprocess.run``; tests inject a fake that
    records the call so the real CLI (and the network) is never needed.
    """

    def __init__(
        self,
        model: str = "haiku",
        timeout_s: int = 120,
        runner: Callable | None = None,
        cwd: Path | None = None,
    ):
        exe = shutil.which("claude")
        if exe is None:
            raise BackendError("claude CLI not on PATH")
        self._exe = exe
        self.model = model
        self.timeout_s = timeout_s
        self._runner = runner if runner is not None else subprocess.run
        self._cwd = cwd
        self.name = f"claude:{model}"

    def choose(self, prompt: str) -> str:
        cmd = [
            self._exe,
            "-p",
            "--tools",
            "",
            "--no-session-persistence",
            "--model",
            self.model,
            "--output-format",
            "text",
        ]
        try:
            proc = self._runner(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                cwd=self._cwd,
                encoding="utf-8",
            )
        except subprocess.TimeoutExpired:
            raise BackendError(f"timeout after {self.timeout_s}s") from None
        if proc.returncode != 0:
            raise BackendError(f"exit {proc.returncode}: {(proc.stderr or '')[:200]}")
        return proc.stdout
