"""Leg entry states: a save state on each map entry, so a drill can start right where a leg starts.

Files: ``<dir>/<map>_<x>_<y>.state`` is the newest for that (map, entry tile); older ones rotate to ``.1.state``, ``.2.state``
(KEEP per key). At most MAX_FILES in total (oldest evicted). Only calm entries are kept: not in battle, no text box, lead
HP above 50%. Only maps on the curriculum route (maps seen in runs/segments.json attempts); with no evidence, every map.
Cheap by design: one state file per key per run, and nothing here may raise into a run.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from pokeagent import statefp

STATES_DIR = Path("runs/legs/states")
KEEP, MAX_FILES = 3, 2000
BATTLE_FLAG, HP_FRACTION = 0xD057, 0.5


def name(m: int, x: int, y: int, n: int = 0) -> str:
    return f"{m}_{x}_{y}.state" if n == 0 else f"{m}_{x}_{y}.{n}.state"


def calm(emu, box: bool) -> bool:
    """Not in battle, no text box, lead HP above half (and a lead exists)."""
    if box or emu.read(BATTLE_FLAG):
        return False
    hp = (emu.read(0xD16C) << 8) | emu.read(0xD16D)
    mx = (emu.read(0xD18D) << 8) | emu.read(0xD18E)
    return mx > 0 and hp > mx * HP_FRACTION


def route_maps(runs_dir: str | Path = "runs") -> set[int]:
    """Maps the curriculum's recorded attempts passed through (any goal); empty when there is no evidence yet."""
    try:
        doc = json.loads((Path(runs_dir) / "segments.json").read_text(encoding="utf-8"))
        from pokeagent.invariants.segments import route_maps as one
        out: set[int] = set()
        for st in (doc.get("stats") or {}).values():
            out |= one(st, None)
        return out
    except (OSError, ValueError, AttributeError, TypeError):
        return set()


def newest(d: str | Path, m: int, x: int, y: int) -> Path | None:
    p = Path(d) / name(m, x, y)
    return p if p.is_file() else None


def keys(d: str | Path) -> set[tuple[int, int, int]]:
    """(map, x, y) of every key that has a state file."""
    out = set()
    try:
        for f in Path(d).glob("*_*_*.state"):
            a = f.name[:-len(".state")].split(".")[0].split("_")
            if len(a) == 3 and all(s.isdigit() for s in a):
                out.add(tuple(map(int, a)))
    except OSError:
        pass
    return out


def newest_on_map(d: str | Path, m: int) -> Path | None:
    """The most recently written entry state on map ``m`` (grind drills start from one)."""
    c = [f for f in Path(d).glob(f"{m}_*_*.state") if f.name.count(".") == 1]
    return max(c, key=lambda f: f.stat().st_mtime, default=None)


def save_entry(emu, d: str | Path, m: int, x: int, y: int, keep: int = KEEP) -> Path:
    """Write the state as the newest for the key, rotating older ones; returns the newest path."""
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{os.getpid()}.tmp"
    emu.save_state(tmp)
    for i in range(keep - 1, 0, -1):
        src = d / name(m, x, y, i - 1)
        if src.exists():
            os.replace(src, d / name(m, x, y, i))
            _move_fp(src, d / name(m, x, y, i))
    os.replace(tmp, d / name(m, x, y))
    statefp.sidecar(d / name(m, x, y)).unlink(missing_ok=True)   # a stale stamp must not describe the new state
    return d / name(m, x, y)


def _move_fp(src: Path, dst: Path) -> None:
    if statefp.sidecar(src).exists():
        os.replace(statefp.sidecar(src), statefp.sidecar(dst))
    else:
        statefp.sidecar(dst).unlink(missing_ok=True)


def evict(d: str | Path, max_files: int = MAX_FILES) -> int:
    """Delete the oldest state files until about 95% of ``max_files`` remain (slack, so it does not run every save)."""
    groups: dict[str, list[Path]] = {}
    for f in Path(d).glob("*.state"):
        groups.setdefault(f.name.split(".")[0], []).append(f)  # <map>_<x>_<y> -> .state, .1.state, .2.state
    total = sum(len(g) for g in groups.values())
    if total <= max_files:
        return 0
    stamp = {k: max(_mtime(f) for f in g) for k, g in groups.items()}
    dropped, target = 0, total - int(max_files * 0.95)
    for k in sorted(groups, key=stamp.get):  # oldest key first, all its rotated files together: no half-key is left
        if dropped >= target:
            break
        for f in groups[k]:
            f.unlink(missing_ok=True)
            statefp.sidecar(f).unlink(missing_ok=True)
        dropped += len(groups[k])
    return dropped


def _mtime(f: Path) -> float:
    try:
        return f.stat().st_mtime
    except OSError:
        return 0.0


class LegStateSaver:
    """Per-press hook: on a map entry that is calm and on the route, save the entry state (once per key per run)."""

    def __init__(self, d: str | Path = STATES_DIR, route: set[int] | None = None, keep: int = KEEP, max_files: int = MAX_FILES):
        self.dir, self.route, self.keep, self.max_files = Path(d), route or set(), keep, max_files
        self.done: set[tuple] = set()
        self.saved = 0
        self.count: int | None = None

    def observe(self, ctx, fr) -> Path | None:
        try:
            b, a = fr.before, fr.after
            if a[0] == b[0] or (self.route and a[0] not in self.route) or tuple(a) in self.done:
                return None
            if not calm(ctx.emu, bool(fr.box_after)):
                return None
            self.done.add(tuple(a))
            if self.count is None:
                self.count = len(list(self.dir.glob("*.state"))) if self.dir.is_dir() else 0
            fresh = not (self.dir / name(*a, self.keep - 1)).exists()
            p = save_entry(ctx.emu, self.dir, *a, keep=self.keep)
            try:
                statefp.stamp(ctx.emu, p, Path(ctx.run_dir).name)   # respawn, party, money, bag beside the state
            except Exception as e:  # noqa: BLE001  an unstamped state is still a state
                ctx.log(f"[leg state unstamped: {e!r}]", "res")
            self.saved += 1
            self.count += 1 if fresh else 0
            if self.count > self.max_files:
                self.count -= evict(self.dir, self.max_files)
            return p
        except Exception as e:  # noqa: BLE001  saving states must never end a run
            ctx.log(f"[leg state skipped: {e!r}]", "res")
            return None
