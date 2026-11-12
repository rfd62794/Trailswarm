"""Perf baseline probe: cProfile one headless explore_demo run and print the cost buckets.

    uv run python tools/perf_probe.py --steps 2000
    uv run python tools/perf_probe.py --steps 2000 --state baselines/bedroom.state --maps runs/maps.json \
        --work-dir .devin-scratch/perf

The run happens IN THIS PROCESS under cProfile: ``os._exit`` (the headless loop's exit for swarm
parents) is trapped so the stats land before the interpreter dies. The map memory and the run dir go
under ``--work-dir`` so a probe never touches the real ``runs/``. Output: the directive's bucket
table, steps/s, presses, and per-step call counts of the named hot functions. Pure stdlib.

Note: this tool is for the main checkout (it needs the ROM and a state file); a worktree without
``roms/`` cannot run it - the bucketing is covered by tests/test_perf_probe.py instead.
"""
from __future__ import annotations

import argparse
import cProfile
import json
import os
import pstats
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


class _RunFinished(Exception):
    """os._exit trap: the headless loop calls it when ctx.done; under the probe it just ends profiling."""

    def __init__(self, code: int = 0) -> None:
        self.code = code


def _trap_exit(code: int = 0):
    raise _RunFinished(code)


# --- buckets: ordered rules, first match wins -----------------------------------------------------
# Each rule is (label, filename_needles, func_names): a stats row (file, line, func) lands in the
# first bucket where ANY needle is a substring of the filename AND (no func_names OR func in them).
# Needles are lowercase. These are the directive's rows, tightened to named modules/functions.

BUCKETS: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("PyBoy tick/emulation", ("pyboy", "emulator.py", "emu_thread.py"), ()),
    ("Tk GUI loop", ("tkinter", "imagetk", "tkapp"), ()),
    ("socket/select wait", ("socketserver", "selectors", "http\\server", "http/server", "socket"), ("select", "poll")),
    ("file I/O / json", ("\\json\\", "/json/", "encoder", "decoder", "scanner", "\\io.py", "/io.py"), ()),
    ("RAM/screen reads", ("ramstructs", "ramworld", "\\ram.py", "/ram.py", "perceive", "screentext", "hexmap"), ()),
    ("decision logic", ("pokeagent", "explore_demo", "explore_plan"), ()),
    ("logging", ("logging\\", "logging/"), ("log",)),
    ("other", (), ()),
]


def bucket_of(filename: str, func: str) -> str:
    f = filename.lower()
    for label, needles, names in BUCKETS[:-1]:
        if names and func not in names:
            continue
        if any(n in f for n in needles):
            return label
    return "other"


# --- named per-step call counts (the directive's bottom line) -------------------------------------
# (label, filename_needle, func_name): counts total calls and calls/step of the functions that
# matter for the perf items. "(wrapper)" rows count the public memoized entry points; "(real)" rows
# count the work the memo actually saves - a healthy memo shows wrapper calls high and real work ~1.

COUNTS: list[tuple[str, str, str]] = [
    ("read_party (wrapper)", "ramstructs", "read_party"),
    ("read_party_count (wrapper)", "ramstructs", "read_party_count"),
    ("_read_party (real)", "ramstructs", "_read_party"),
    ("read_snapshot", "features", "read_snapshot"),
    ("world.path", "world", "path"),
    ("world._bfs_node", "world", "_bfs_node"),
    ("world.neighbours", "world", "neighbours"),
    ("memory_nav.choose_local", "memory_nav", "choose_local"),
    ("check_goals", "goals", "check_goals"),
    ("json.dumps", "json", "dumps"),
    ("engine.step", "engine", "step"),
]


def _rows(stats: pstats.Stats) -> dict:
    """{func key: (bucket, ncalls, tottime, cumtime)} flattened from pstats."""
    out = {}
    for (filename, _line, func), (_cc, nc, tt, ct, _callers) in stats.stats.items():
        out[(filename, func)] = (bucket_of(filename, func), nc, tt, ct)
    return out


def report(stats: pstats.Stats, *, steps: int, secs: float, presses: int | None = None) -> str:
    """The bucket table + steps/s + per-step call counts, as text."""
    rows = _rows(stats)
    steps = max(1, steps)
    agg = {}  # label -> [total_tottime, (hot_name, hot_nc, hot_tt)]
    for (filename, func), (bucket, nc, tt, _ct) in rows.items():
        tot, hot = agg.get(bucket, (0.0, None))
        if hot is None or tt > hot[2]:
            hot = (f"{os.path.basename(filename)}:{func}", nc, tt)
        agg[bucket] = (tot + tt, hot)
    total = sum(v[0] for v in agg.values()) or 1.0
    lines = ["| bucket | tottime | share | hottest function |", "|---|---|---|---|"]
    for label, _needles, _names in BUCKETS:
        if label not in agg:
            lines.append(f"| {label} | 0.0 s | 0.0% | - |")
            continue
        tot, (hot_f, hot_nc, hot_tt) = agg[label]
        lines.append(f"| {label} | {tot:.1f} s | {tot / total * 100:.1f}% | `{hot_f}` {hot_tt:.1f}s {hot_nc:,} calls |")
    lines.append("")
    lines.append(f"steps={steps} presses={presses if presses is not None else '?'} "
                 f"wall={secs:.1f}s  steps/s={steps / max(secs, 1e-9):.2f}")
    per = []
    for label, needle, func in COUNTS:
        n = sum(nc for (filename, f), (_b, nc, _t, _c) in rows.items() if needle in filename and f == func)
        per.append(f"{label} {n / steps:.2f}/step")
    lines.append("per step: " + ", ".join(per))
    return "\n".join(lines)


def bucket_report_from_prof(prof_path: str | Path, *, steps: int, secs: float, presses: int | None = None) -> str:
    return report(pstats.Stats(str(prof_path)), steps=steps, secs=secs, presses=presses)


def _work_maps(a, work: Path) -> Path:
    """The maps.json the probe run uses: a byte copy of ``--maps`` (the source file is only read,
    never mutated - the run writes its learned memory into the work dir's copy) or empty memory."""
    maps = work / "maps.json"
    maps.write_text(Path(a.maps).read_text(encoding="utf-8") if a.maps else '{"maps": {}}')
    return maps


def run_probe(a) -> dict:
    """Profile ``explore_demo.main`` headless in-process; returns the pieces the report needs."""
    import explore_demo

    work = Path(a.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    run_root = work / "runs"
    maps = _work_maps(a, work)
    argv = ["--headless", "--steps", str(a.steps), "--rom", a.rom, "--state", a.state,
            "--maps", str(maps), "--control-port", "0", "--runs-dir", str(run_root)]
    if a.seed is not None:
        argv += ["--seed", str(a.seed)]
    real_exit, os._exit = os._exit, _trap_exit  # the run must not take the profile down with it
    prof, t0 = cProfile.Profile(), time.perf_counter()
    try:
        prof.enable()
        explore_demo.main(argv)
    except _RunFinished:
        pass
    finally:
        prof.disable()
        os._exit = real_exit
    secs = time.perf_counter() - t0
    prof_path = work / "perf.prof"
    prof.dump_stats(str(prof_path))
    return {"stats": pstats.Stats(str(prof_path)), "secs": secs, "prof": prof_path, "work": run_root}


def _presses(work: Path) -> int | None:
    """Presses in the newest probe run dir (transitions.jsonl line count)."""
    dirs = sorted(work.glob("explore-*"), key=lambda p: p.stat().st_mtime) if work.exists() else []
    if not dirs:
        return None
    trans = dirs[-1] / "transitions.jsonl"
    return sum(1 for _ in trans.open(encoding="utf-8")) if trans.exists() else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--steps", type=int, default=2000)
    ap.add_argument("--rom", default="roms/Pokemon Red.gb")
    ap.add_argument("--state", default="baselines/bedroom.state")
    ap.add_argument("--maps", default=None, help="seed map memory (default: fresh empty memory in the work dir)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--work-dir", default=".devin-scratch/perf",
                    help="scratch dir for the map memory, the profile and the run dir (default .devin-scratch/perf)")
    ap.add_argument("--report-only", default=None, metavar="PROF",
                    help="skip the run: reprint the table for an existing .prof file")
    a = ap.parse_args(argv)
    if a.report_only:
        print(report(pstats.Stats(a.report_only), steps=a.steps, secs=1.0))
        return 0
    if not Path(a.rom).exists():
        print(f"ROM missing: {a.rom} - the probe needs the main checkout (no roms/ in a worktree)", file=sys.stderr)
        return 2
    r = run_probe(a)
    presses = _presses(r["work"])
    print(report(r["stats"], steps=a.steps, secs=r["secs"], presses=presses))
    meta = {"steps": a.steps, "secs": round(r["secs"], 2), "presses": presses, "prof": str(r["prof"])}
    (Path(a.work_dir) / "perf_report.json").write_text(json.dumps(meta, indent=1))
    print(f"\nprofile: {r['prof']}   run dir: {r['work']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
