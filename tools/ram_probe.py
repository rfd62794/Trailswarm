"""RAM probe: the unlabeled-gap report, a scripted-state diff run, and promoting confirmed gap
bytes to `discovered` map rows.

    uv run python tools/ram_probe.py gaps [--game pokemon-red] [--sym pokered.sym]
    uv run python tools/ram_probe.py run --rom ROM --state STATE --script SCRIPT [--game pokemon-red] [--out-root runs]
    uv run python tools/ram_probe.py promote --addr 0xD430 --size 1 --name wDisc_D430 \
        --evidence-run runs/ramprobe-... --evidence-run runs/ramprobe-... [--region other] [--apply]

Runs write under runs/ (gitignored); only `promote --apply` touches ram_map.json, and it never
touches an existing row. probe.json lists changed bytes only (addr, before, after): no dumps.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_ram_map import parse_sym, write_map  # noqa: E402

from pokeagent.ramlab import probe, trust  # noqa: E402
from pokeagent.ramlab.games import map_path_for  # noqa: E402
from pokeagent.ramlab.gaps import summary, wram_gaps  # noqa: E402
from pokeagent.ramlab.labels import load_entries  # noqa: E402


def _sym_dists(sym: Path) -> dict[int, int]:
    """WRAM addr -> distance to the next sym label, for spotting inferred map sizes."""
    addrs = sorted({a for a, _ in parse_sym(Path(sym)) if 0xC000 <= a <= 0xDFFF})
    return {a: (addrs[i + 1] if i + 1 < len(addrs) else 0xE000) - a for i, a in enumerate(addrs)}


def cmd_gaps(a) -> int:
    entries = load_entries(map_path_for(a.game))
    s = summary(entries)
    print(f"bytes covered by some entry: {s['covered']} of {s['total']}")
    print(f"unlabeled bytes: {s['unlabeled']} in {s['gaps']} gaps")
    print("largest: " + ", ".join(f"0x{ad:04X} ({n} bytes)" for ad, n in s["largest"]))
    print(f"entries at the 256 cap: {s['at_cap']}")
    print(f"unknown-ish names: {s['unknown_named'][0]} entries, {s['unknown_named'][1]} bytes")
    if a.sym:
        dist = _sym_dists(a.sym)
        inferred = [(int(e["addr"], 16), e["name"], e["size"]) for e in entries
                    if dist.get(int(e["addr"], 16), 0) > e["size"]]
        print(f"\n{len(inferred)} labels whose entry is smaller than the next sym label (inferred size):")
        for ad, name, size in sorted(inferred)[:40]:
            print(f"  0x{ad:04X} {name:42s} size {size} < {dist[ad]}")
    return 0


def cmd_run(a) -> int:
    if not Path(a.rom).is_file():
        print("skipped: no ROM")
        return 0
    entries = load_entries(map_path_for(a.game))
    script = json.loads(Path(a.script).read_text(encoding="utf-8"))
    from pokeagent.emulator import PyBoyEmulator
    emu = PyBoyEmulator(Path(a.rom), headless=True)
    try:
        run_dir = probe.probe_run(emu, Path(a.state), script, entries, Path(a.out_root), a.game)
    finally:
        emu.close()
    print(f"probe run -> {run_dir}")
    return 0


def _evidence(runs: list[Path], addr: int, size: int) -> dict[str, list]:
    """{event label: [(run dir, [(addr, before, after) sorted])]}: the runs where every byte of
    the range changed under that one label."""
    out: dict[str, list] = {}
    want = set(range(addr, addr + size))
    for r in runs:
        data = json.loads((r / "probe.json").read_text(encoding="utf-8"))
        for ev in data.get("events", []):
            got = {u["addr"]: (u["before"], u["after"]) for u in ev.get("unlabeled", [])}
            if want <= set(got):
                pairs = sorted((a2, *got[a2]) for a2 in want)
                out.setdefault(ev["label"], []).append((r, pairs))
    return out


def cmd_promote(a) -> int:
    map_path = map_path_for(a.game)
    entries = load_entries(map_path)
    addr, size = int(a.addr, 16), a.size
    if a.name in {e["name"] for e in entries}:
        print(f"refused: name {a.name} is already used")
        return 1
    if not any(g <= addr and addr + size <= g + n for g, n in wram_gaps(entries)):
        print(f"refused: 0x{addr:04X}+{size} is not wholly inside an unlabeled gap")
        return 1
    runs = [Path(r) for r in a.evidence_run]
    missing = [str(r) for r in runs if not (r / "probe.json").is_file()]
    if missing:
        print("refused: --evidence-run dirs without probe.json: " + ", ".join(missing))
        return 1
    good = {lb: dirs for lb, dirs in _evidence(runs, addr, size).items() if len(dirs) >= 2}
    if not good:
        print("refused: fewer than two run directories show the range changing under one event label")
        return 1
    label, dirs = max(good.items(), key=lambda kv: len(kv[1]))
    ev = "; ".join(f"{label} " + "+".join(f"0x{a2:04X} {b}->{v}" for a2, b, v in pairs)
                   + f" in {r.name}" for r, pairs in dirs)
    row = {"name": a.name, "addr": f"0x{addr:04X}", "size": size,
           "encoding": "u8" if size == 1 else "bytes", "region": a.region,
           "verified": False, "trust": "discovered",
           "source": "ram_probe " + " ".join(r.name for r, _ in dirs), "evidence": ev}
    problems = trust.validate(entries + [row])
    if problems:
        print("refused: the row would not validate:")
        print("\n".join(f"  - {p}" for p in problems))
        return 1
    if not a.apply:
        print(json.dumps(row, separators=(", ", ": ")))
        print("dry run; pass --apply to write it")
        return 0
    entries.append(row)
    entries.sort(key=lambda e: (int(e["addr"], 16), e["name"]))
    write_map(map_path, entries)
    print(f"discovered row written -> {map_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gaps")
    g.add_argument("--game", default="pokemon-red")
    g.add_argument("--sym", type=Path)
    r = sub.add_parser("run")
    r.add_argument("--rom", type=Path, required=True)
    r.add_argument("--state", type=Path, required=True)
    r.add_argument("--script", type=Path, required=True)
    r.add_argument("--game", default="pokemon-red")
    r.add_argument("--out-root", type=Path, default=ROOT / "runs")
    p = sub.add_parser("promote")
    p.add_argument("--addr", required=True)
    p.add_argument("--size", type=int, required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--evidence-run", action="append", required=True)
    p.add_argument("--region", default="other")
    p.add_argument("--game", default="pokemon-red")
    p.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    return {"gaps": cmd_gaps, "run": cmd_run, "promote": cmd_promote}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
