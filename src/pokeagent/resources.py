"""Smart resource detection: how many agent processes this machine can run right now.

max_agents = min(configured cap, (free RAM - reserve) // per-agent RSS, logical CPUs - 2), at least 1.
Agents are counted by the agent registry (live pids), never by process count: on Windows a venv python.exe
is a launcher that starts the real interpreter, so every agent shows as two processes.
No third-party dependencies: Windows memory comes from ctypes, elsewhere from /proc.
"""
from __future__ import annotations

import ctypes
import json
import os
import statistics
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from pokeagent.agent_registry import list_agents
from pokeagent.registry import process_alive

DEFAULT_CAP = 6
RESERVE_MB = 2048
DEFAULT_RSS_MB = 350.0
CPU_RESERVE = 2
LOCK_STALE_S = 6 * 3600


class LockBusy(RuntimeError):
    pass


def _runs(root: Path) -> Path:
    return Path(root) / "runs"


def free_ram_mb() -> float:
    """Available physical memory in MB (0.0 when unreadable: callers then stay at one agent)."""
    if os.name == "nt":
        class _Mem(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("ptotal", ctypes.c_ulonglong),
                        ("pavail", ctypes.c_ulonglong), ("vtotal", ctypes.c_ulonglong),
                        ("vavail", ctypes.c_ulonglong), ("xavail", ctypes.c_ulonglong)]
        m = _Mem()
        m.length = ctypes.sizeof(m)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return 0.0
        return m.avail / (1024 * 1024)
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def process_rss_mb(pid: int) -> float | None:
    """Working set of ``pid`` in MB (None when unreadable)."""
    if os.name != "nt":
        try:
            pages = int(Path(f"/proc/{pid}/statm").read_text().split()[1])
            return pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
        except (OSError, ValueError, IndexError):
            return None

    class _Pmc(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong), ("peak", ctypes.c_size_t),
                    ("ws", ctypes.c_size_t), ("a", ctypes.c_size_t), ("b", ctypes.c_size_t),
                    ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("e", ctypes.c_size_t),
                    ("f", ctypes.c_size_t)]
    k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Pmc), ctypes.c_ulong]
    h = k32.OpenProcess(0x1000 | 0x0010, False, pid)  # QUERY_LIMITED_INFORMATION | VM_READ
    if not h:
        h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    try:
        pmc = _Pmc()
        pmc.cb = ctypes.sizeof(pmc)
        return pmc.ws / (1024 * 1024) if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb) else None
    finally:
        k32.CloseHandle(h)


def cpu_count() -> int:
    return os.cpu_count() or 1


def load_rss(root: Path | None) -> float:
    """Measured per-agent RSS in MB from runs/resources.json, else the 350 MB default."""
    if root is not None:
        try:
            v = float(json.loads((_runs(root) / "resources.json").read_text(encoding="utf-8"))["per_agent_rss_mb"])
            if v > 0:
                return v
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return DEFAULT_RSS_MB


def save_rss(root: Path, mb: float, samples: int = 0) -> None:
    _runs(root).mkdir(parents=True, exist_ok=True)
    data = {"per_agent_rss_mb": round(float(mb), 1), "samples": samples, "measured": time.time()}
    tmp = _runs(root) / "resources.tmp"
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, _runs(root) / "resources.json")


def measure_agent_rss(root: Path, reader: Callable[[int], float | None] = process_rss_mb) -> float | None:
    """Median RSS of the live registered agents, recorded in runs/resources.json. None if none readable."""
    sizes = [s for e in list_agents(root) if (s := reader(e["pid"])) is not None]
    if not sizes:
        return None
    mb = float(statistics.median(sizes))
    save_rss(root, mb, len(sizes))
    return mb


def live_agent_count(root: Path) -> int:
    return len(list_agents(root))


def configured_cap(cap: int | None = None) -> int:
    if cap:
        return max(1, int(cap))
    try:
        return max(1, int(os.environ.get("POKEAGENT_MAX_AGENTS", DEFAULT_CAP)))
    except ValueError:
        return DEFAULT_CAP


def max_agents(cap: int | None = None, root: Path | None = None, free_mb: float | None = None,
               cpus: int | None = None, rss_mb: float | None = None) -> int:
    """How many agents may run at once on this machine (always at least 1)."""
    free = free_ram_mb() if free_mb is None else free_mb
    rss = load_rss(root) if rss_mb is None else rss_mb
    by_ram = int((free - RESERVE_MB) // rss)
    by_cpu = (cpu_count() if cpus is None else cpus) - CPU_RESERVE
    return max(1, min(configured_cap(cap), by_ram, by_cpu))


def room_for(want: int, root: Path, **kw) -> tuple[int, str]:
    """(agents that may start now, one-line reason). ``kw`` are max_agents overrides (cap, free_mb, ...)."""
    mx, live = max_agents(root=root, **kw), live_agent_count(root)
    n = max(0, min(want, mx - live))
    why = (f"agent limit: max {mx} (RAM/CPU/cap), {live} live ({2 * live} processes: venv launcher + "
           f"interpreter each); starting {n} of {want} requested")
    return n, why


def _try_acquire(path: Path) -> bool:
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True


def _stale(path: Path) -> bool:
    try:
        if time.time() - path.stat().st_mtime > LOCK_STALE_S:
            return True
        return not process_alive(int(path.read_text().strip() or 0))
    except (OSError, ValueError):
        return True


@contextmanager
def spawn_lock(root: Path, wait_s: float = 0.0):
    """Global lock (runs/spawn.lock) so two swarms cannot race past the cap. Dead/old holders are stolen."""
    _runs(root).mkdir(parents=True, exist_ok=True)
    path = _runs(root) / "spawn.lock"
    end = time.monotonic() + wait_s
    while not _try_acquire(path):
        if _stale(path):
            path.unlink(missing_ok=True)
            continue
        if time.monotonic() >= end:
            raise LockBusy(f"another swarm holds {path}")
        time.sleep(0.1)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)
