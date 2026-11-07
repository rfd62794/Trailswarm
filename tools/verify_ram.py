"""Prove RAM addresses on the real ROM and write `verified: true` + evidence into ram_map.json.

    uv run python tools/verify_ram.py [--rom ROM] [--states DIR] [--dry-run]

Needs the ROM, kb/rom_tables.json and the checkpoint copies (*.state; all gitignored). Only addresses
a passing check names are flipped; nothing is ever downgraded. Prints verified counts by region and
every failed check.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))
from build_ram_map import DATA, write_map  # noqa: E402
from ram_checks import ALL, Rig  # noqa: E402


def region_table(entries: list[dict]) -> str:
    tot, ver, vbytes = Counter(), Counter(), Counter()
    for e in entries:
        tot[e["region"]] += 1
        if e.get("verified"):
            ver[e["region"]] += 1
            vbytes[e["region"]] += e["size"]
    rows = [f"{r:12s} {ver[r]:4d} / {tot[r]:4d} labels   {vbytes[r]:5d} bytes" for r in sorted(tot)]
    rows.append(f"{'TOTAL':12s} {sum(ver.values()):4d} / {sum(tot.values()):4d} labels   {sum(vbytes.values()):5d} bytes")
    return "\n".join(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", type=Path, default=ROOT / "roms" / "Pokemon Red.gb")
    ap.add_argument("--states", type=Path, default=ROOT / "runs" / "checkpoints")
    ap.add_argument("--map", type=Path, default=DATA / "ram_map.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    entries = json.loads(args.map.read_text(encoding="utf-8"))
    by_name = {e["name"]: e for e in entries}
    by_name.update({e["alias"]: e for e in entries if "alias" in e})
    kb = json.loads((ROOT / "kb" / "rom_tables.json").read_text(encoding="utf-8"))
    rig = Rig(args.rom, args.states, kb)
    failed: list[str] = []
    flipped = 0
    try:
        for check in ALL:
            try:
                res = check(rig)
            except Exception:
                failed.append(f"{check.__name__}: raised\n{traceback.format_exc(limit=3)}")
                continue
            failed += [f"{check.__name__}: {f}" for f in res.failed]
            for name, evidence in res.ok.items():
                e = by_name.get(name)
                if e is None:
                    failed.append(f"{check.__name__}: unknown name {name}")
                elif not e.get("verified"):
                    e["verified"], e["evidence"] = True, evidence
                    flipped += 1
                elif not e.get("evidence"):
                    e["evidence"] = evidence
            print(f"{check.__name__}: {len(res.ok)} names proven, {len(res.failed)} failed")
    finally:
        rig.emu.close()
    if not args.dry_run:
        write_map(args.map, entries)
        if getattr(rig, "findings", None):
            from pokeagent.ramlab import pipeline
            pipeline.record_findings(rig.findings)
    print(f"\nnewly verified this run: {flipped}\n\n{region_table(entries)}\n\nFAILED CHECKS ({len(failed)}):")
    print("\n".join(f"  - {f}" for f in failed) or "  (none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
