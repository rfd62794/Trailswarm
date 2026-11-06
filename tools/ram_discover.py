"""RAM discovery: mine event RAM diffs, replay-verify the best candidates, report.

    uv run python tools/ram_discover.py mine   [--runs DIR ...] [--top 40] [--min-support 3]
    uv run python tools/ram_discover.py verify [--runs DIR ...] [--top 40] [--dry-run]
    uv run python tools/ram_discover.py report [--runs DIR ...]

Runs record events with `--ram-diff` (on for swarm agents; see tools/ram_seed.py for a windowless seeder).
`verify` replays each top candidate (press vs no-press control), writes src/pokeagent/data/ram_findings.json and,
only for candidates that pass, flips the matching precise label in ram_map.json to verified with the evidence.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_ram_map import DATA, write_map  # noqa: E402

from pokeagent.ramlab import findings as F  # noqa: E402
from pokeagent.ramlab import pipeline, report  # noqa: E402
from pokeagent.ramlab.flags import FLAG_HI, FLAG_LO, flag_bits, describe  # noqa: E402
from pokeagent.ramlab.kinds import describe as kind_text  # noqa: E402
from pokeagent.ramlab.labels import load_entries  # noqa: E402
from pokeagent.ramlab.records import load_all  # noqa: E402


def maps_events(roots: list[Path]) -> list[dict]:
    out: list[dict] = []
    for root in roots:
        for p in {root / "maps.json", root.parent / "maps.json"}:
            if p.is_file():
                out += json.loads(p.read_text(encoding="utf-8")).get("events", [])
    return out


def cmd_mine(a, roots) -> int:
    records, metas, labels, cands = pipeline.mine_runs(roots, a.min_support)
    print(f"{len(records)} records, {len(metas)} runs, {len(cands)} candidates\n")
    for c in pipeline.select(cands, labels, a.top):
        status, lb = labels.join(c.event, c.addr)
        print(f"0x{c.addr:04X} {c.event:13s} {kind_text(c.kind):26s} n={c.support:<4d} runs={c.runs} spec={c.specificity:.2f} "
              f"cons={c.consistency:.2f} score={c.score:.2f}  {status}: {lb.name if lb else '-'}")
    return 0


def flag_entries(roots: list[Path]) -> list[dict]:
    records, _ = load_all(roots)
    return [{"addr": f"0x{b.addr:04X}", "bit": b.bit, "direction": b.direction, "count": b.count, "runs": len(b.runs),
             "where": describe(b), "places": [list(p) for p, _ in b.places.most_common(3)]}
            for b in flag_bits(records, maps_events(roots))]


def cmd_verify(a, roots) -> int:
    entries = load_entries(Path(a.map))
    findings, notes, chosen = pipeline.verify_top(roots, Path(a.rom), Path(a.states), a.top, a.min_support, entries, tuple(a.include))
    for f in findings:
        print(f"{'VERIFIED' if f['verified'] else 'not    '} {f['addr']} {f['name']:26s} {f['event']:13s} {f['status']:9s} "
              f"replay {f['replay']['passed']}/{f['replay']['witnesses']}")
    for n in notes:
        print(f"note {n['key']}: {n['note']}")
    if a.dry_run:
        return 0
    data = pipeline.record_findings(findings)
    data["flags"] = flag_entries(roots)
    flipped = F.apply_to_map(entries, data)
    F.save(data)
    write_map(Path(a.map), entries)
    print(f"\n{sum(f['verified'] for f in findings)}/{len(findings)} verified; {flipped} ram_map labels newly verified")
    return 0


def cmd_report(a, roots) -> int:
    records, metas = load_all(roots)
    data = F.load()
    bits = flag_bits(records, maps_events(roots))
    print(report.build(load_entries(Path(a.map)), data, bits, len(records), len(metas)))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["mine", "verify", "report"])
    ap.add_argument("--runs", type=Path, nargs="*", default=[ROOT / "runs"])
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--min-support", type=int, default=3)
    ap.add_argument("--rom", default=str(ROOT / "roms" / "Pokemon Red.gb"))
    ap.add_argument("--states", default=str(ROOT / "runs" / "checkpoints"))
    ap.add_argument("--map", default=str(DATA / "ram_map.json"))
    ap.add_argument("--include", type=lambda v: int(v, 16), nargs="*", default=list(pipeline.RECHECK),
                    help="hex addresses to test whatever their rank (default: wCurOpponent 0xD059)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    return {"mine": cmd_mine, "verify": cmd_verify, "report": cmd_report}[a.cmd](a, a.runs)


if __name__ == "__main__":
    raise SystemExit(main())
