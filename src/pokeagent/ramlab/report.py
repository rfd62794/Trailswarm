"""Text report for `ram_discover.py report`: newly confirmed, new findings, failed hypotheses, coverage, story flags."""
from __future__ import annotations

from collections import Counter

from pokeagent.ramlab.flags import FlagBit, by_place, describe, map_name
from pokeagent.ramlab.kinds import describe as kind_text


def coverage(entries: list[dict]) -> list[str]:
    tot, ver, vbytes, tbytes = Counter(), Counter(), Counter(), Counter()
    for e in entries:
        tot[e["region"]] += 1; tbytes[e["region"]] += e["size"]
        if e.get("verified"):
            ver[e["region"]] += 1; vbytes[e["region"]] += e["size"]
    rows = [f"  {r:12s} {ver[r]:4d} / {tot[r]:4d} labels  {vbytes[r]:5d} / {tbytes[r]:5d} bytes" for r in sorted(tot)]
    rows.append(f"  {'TOTAL':12s} {sum(ver.values()):4d} / {sum(tot.values()):4d} labels  "
                f"{sum(vbytes.values()):5d} / {sum(tbytes.values()):5d} bytes")
    return rows


def finding_line(f: dict) -> str:
    st = f["stats"]
    return (f"  {f['addr']} {f['name']:28s} {f['event']:13s} {kind_text(f['kind']):26s} "
            f"n={st['support']} runs={st['runs']} spec={st['specificity']} cons={st['consistency']}")


def flag_rows(bits: list[FlagBit], names: dict | None = None, limit: int = 40) -> list[str]:
    rows = [f"  {b.key:7s} {b.direction:5s} x{b.count:<3d} {describe(b, names)}" for b in sorted(bits, key=lambda b: -b.count)[:limit]]
    return rows or ["  (no flag flips recorded)"]


def place_rows(bits: list[FlagBit], names: dict | None = None, limit: int = 25) -> list[str]:
    placed = sorted(by_place(bits).items(), key=lambda kv: -len(kv[1]))[:limit]
    return [f"  {map_name(m, names)} ({x},{y}): {', '.join(keys[:6])}" for (m, x, y), keys in placed] or ["  (none)"]


def build(entries: list[dict], data: dict, bits: list[FlagBit], n_records: int, n_runs: int, flipped: int = 0,
          names: dict | None = None) -> str:
    fs = data["findings"]
    confirmed = [f for f in fs if f["verified"] and f["status"] == "confirms"]
    new = sorted((f for f in fs if f["status"] == "new"), key=lambda f: -f["stats"]["score"])
    failed = data["failed"]
    out = [f"RAM discovery: {n_records} event records from {n_runs} run(s); {flipped} label(s) newly verified this pass", "",
           f"NEWLY CONFIRMED labels ({len(confirmed)} replay-verified findings that confirm a label):"]
    out += [finding_line(f) for f in confirmed] or ["  (none)"]
    out += ["", f"NEW FINDINGS ({len(new)}; verified = replay-confirmed, ? = mined but not yet confirmed):"]
    out += [("  [verified] " if f["verified"] else "  [?]        ") + finding_line(f).lstrip() for f in new[:25]] or ["  (none)"]
    out += ["", f"FAILED HYPOTHESES ({len(failed)}):"]
    out += [f"  {f['addr']} {f['name']:24s} {f['event']:13s} {f['kind']:18s} {f['evidence'][:110]}" for f in failed[:25]] or ["  (none)"]
    out += ["", "COVERAGE (verified labels / total):"] + coverage(entries)
    out += ["", "STORY FLAGS (bit, direction, count, where/what):"] + flag_rows(bits, names)
    out += ["", "STORY FLAGS BY MAP/TILE (Atlas input):"] + place_rows(bits, names)
    return "\n".join(out)
