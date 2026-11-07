"""Estimate per-battle XP from the existing battle history. Read-only on runs/battles.jsonl; writes runs/xp_estimates.jsonl.

Gen 1 formula for one participant: exp = base_exp * enemy_level / 7, times 1.5 for a trainer battle. Base exp comes from
the ROM-extracted kb/rom_tables.json (gitignored); without it the tool says so and writes nothing. Every line is marked
``"estimated": true``; records that already carry a measured ``exp_gained`` also carry ``exp_measured``.
Only won battles earn exp (a fled or lost fight is 0). Shared fights (several participants) are over-estimated.

    uv run python tools/xp_backfill.py [--battles runs/battles.jsonl] [--kb kb/rom_tables.json] [--out runs/xp_estimates.jsonl]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def gen1_exp(base_exp: int, level: int, trainer: bool) -> int:
    return int(base_exp * level * (1.5 if trainer else 1) // 7)


def estimate(rec: dict, kb: dict) -> dict | None:
    internal, level = rec.get("enemy_species"), (rec.get("enemy") or [0, 0])[1]
    if not internal or not level:
        return None
    dex = kb["dex_of_internal"].get(str(internal))
    row = kb["species_by_dex"].get(str(dex)) if dex else None
    if not row or "base_exp" not in row:
        return None
    trainer = rec.get("kind") == 2
    won = bool(rec.get("won"))
    out = {"run": rec.get("run"), "start": rec.get("start"), "map": rec.get("map"), "enemy_species": internal,
           "enemy_name": row.get("name"), "enemy_level": level, "kind": rec.get("kind"), "won": won,
           "base_exp": row["base_exp"], "exp_estimate": gen1_exp(row["base_exp"], level, trainer) if won else 0,
           "estimated": True, "method": "gen1: base_exp*level/7, x1.5 trainer, one participant"}
    if rec.get("exp_gained") is not None:
        out["exp_measured"] = sum(g for g in rec["exp_gained"] if g > 0)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--battles", default="runs/battles.jsonl")
    ap.add_argument("--kb", default="kb/rom_tables.json")
    ap.add_argument("--out", default="runs/xp_estimates.jsonl")
    a = ap.parse_args(argv)
    if not Path(a.kb).exists():
        print(f"no {a.kb}: base exp yields come from the ROM extraction; run the kb extractor first (nothing written)")
        return 1
    kb = json.loads(Path(a.kb).read_text(encoding="utf-8"))
    total = skipped = bad = 0
    written = []
    for line in Path(a.battles).read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            bad += 1
            continue
        total += 1
        est = estimate(rec, kb)
        if est is None:
            skipped += 1
        else:
            written.append(est)
    Path(a.out).write_text("".join(json.dumps(w) + "\n" for w in written), encoding="utf-8")
    won = [w for w in written if w["won"]]
    print(f"{total} battle records ({bad} unparseable): {len(written)} estimated, {skipped} skipped (no enemy species/level/base exp); "
          f"{len(won)} won, {sum(w['exp_estimate'] for w in won)} estimated exp total -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
