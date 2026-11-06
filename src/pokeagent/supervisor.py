"""Spawn/stop wiring for the viewer control bar: launches demo tools as subprocesses.

``build_argv`` is pure (unit-tested without spawning); ``spawn``/``stop`` manage Popen handles.
Agents self-register in the agent registry, so the viewer discovers them on its next poll.
"""
from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

from pokeagent import resources
from pokeagent.agent_registry import list_agents

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


class SpawnRefused(RuntimeError):
    """The agent limit is reached (or another swarm is mid-spawn); the message is shown in the viewer."""


class Supervisor:
    def __init__(self, root: Path = Path("."), limits: dict | None = None) -> None:
        self.root = Path(root)
        self._limits = limits or {}  # max_agents overrides (cap, free_mb, cpus, rss_mb); tests inject fakes
        self._procs: dict[int, subprocess.Popen] = {}

    def spawn(self, kind: str, *args: str) -> int:
        """Launch ``kind`` with ``args``; returns the agent process pid. Raises SpawnRefused at the agent limit."""
        port = free_port()
        argv = build_argv(kind, list(args), port, self.root)
        try:
            with resources.spawn_lock(self.root, wait_s=5.0):
                registered = {e["pid"] for e in list_agents(self.root)}
                # agents spawned here that have not registered yet still count against the limit
                pending = sum(1 for pid, p in self._procs.items() if p.poll() is None and pid not in registered)
                mx, live = resources.max_agents(root=self.root, **self._limits), len(registered)
                if live + pending >= mx:
                    raise SpawnRefused(f"agent limit reached: {live + pending} of max {mx} "
                                       f"(RAM/CPU/cap); not spawning another")
                proc = subprocess.Popen(argv, cwd=str(self.root))
        except resources.LockBusy as e:
            raise SpawnRefused(f"another spawn is in progress: {e}") from e
        self._procs[proc.pid] = proc
        return proc.pid

    def stop(self, pid: int) -> bool:
        """Terminate an agent this supervisor spawned. Any other pid (e.g. one read from the agent
        registry, which a stale or hostile entry could point at an unrelated process) is refused."""
        proc = self._procs.pop(pid, None)
        if proc is None:
            return False
        try:
            proc.terminate()
        except OSError:
            pass
        return True
