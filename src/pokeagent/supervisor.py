"""Spawn/stop wiring for the viewer control bar: launches demo tools as subprocesses.

``build_argv`` is pure (unit-tested without spawning); ``spawn``/``stop`` manage Popen handles.
Agents self-register in the agent registry, so the viewer discovers them on its next poll.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

_TOOLS = {"explorer": "tools/explore_demo.py", "rl": "tools/rl_train.py"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def build_argv(kind: str, args: list[str], port: int, root: Path) -> list[str]:
    """argv for ``kind`` ("explorer"|"rl"). Explorer runs headless+frame-share so the viewer
    gets snapshots and frames without a Tk window; rl_train gets --frame-port (status+frames)."""
    tool = _TOOLS.get(kind)
    if tool is None:
        raise ValueError(f"unknown agent kind {kind!r}; expected one of {sorted(_TOOLS)}")
    argv = [sys.executable, str(Path(root) / tool)]
    if kind == "explorer":
        argv += ["--headless", "--frame-share", "--control-port", str(port)]
    else:
        argv += ["--frame-port", str(port)]
    return argv + list(args)


class Supervisor:
    def __init__(self, root: Path = Path(".")) -> None:
        self.root = Path(root)
        self._procs: dict[int, subprocess.Popen] = {}

    def spawn(self, kind: str, *args: str) -> int:
        """Launch ``kind`` with ``args``; returns the child pid."""
        port = free_port()
        argv = build_argv(kind, list(args), port, self.root)
        proc = subprocess.Popen(argv, cwd=str(self.root))
        self._procs[proc.pid] = proc
        return proc.pid

    def stop(self, pid: int) -> bool:
        """Terminate a spawned (or registry-listed) agent; False when nothing was signaled."""
        proc = self._procs.pop(pid, None)
        if proc is not None:
            try:
                proc.terminate()
            except OSError:
                pass
            return True
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except (OSError, ProcessLookupError):
            return False
