"""ram_findings.json: committable record of what RAM discovery found (addresses, names, evidence text; no dumps)."""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.ramlab.labels import DATA, Label

FINDINGS_PATH = DATA / "ram_findings.json"
EMPTY = {"version": 1, "findings": [], "failed": [], "flags": []}


def load(path: Path = FINDINGS_PATH) -> dict:
    if Path(path).is_file():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return json.loads(json.dumps(EMPTY))


def save(data: dict, path: Path = FINDINGS_PATH) -> None:
    Path(path).write_text(json.dumps(data, indent=1, sort_keys=False) + "\n", encoding="utf-8")


def finding_name(event: str, addr: int, label: Label | None) -> str:
    return label.name if label else f"unk_{addr:04X}"


def upsert(data: dict, entry: dict, bucket: str = "findings") -> None:
    """One entry per (event, addr). A verified entry is never replaced by an unverified one."""
    rows = data[bucket]
    for i, row in enumerate(rows):
        if (row["event"], row["addr"]) == (entry["event"], entry["addr"]):
            if row.get("verified") and not entry.get("verified"):
                return
            rows[i] = entry
            return
    rows.append(entry)
    rows.sort(key=lambda r: (r["addr"], r["event"]))


def apply_to_map(entries: list[dict], data: dict) -> int:
    """Flip ram_map.json labels to verified for verified findings that confirm a precise (<= 8 byte) label.
    Never downgrades; returns how many labels flipped."""
    by_name = {e["name"]: e for e in entries}
    flipped = 0
    for f in data["findings"]:
        e = by_name.get(f.get("label", ""))
        if not (f.get("verified") and f["status"] == "confirms" and e and e["size"] <= 8):
            continue
        if not e.get("verified"):
            e["verified"], e["evidence"] = True, f["evidence"]
            flipped += 1
        elif not e.get("evidence"):
            e["evidence"] = f["evidence"]
    return flipped
