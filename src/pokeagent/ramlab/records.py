"""Load ram_events.jsonl records from run directories (this repo's runs/ and the swarm's)."""
from __future__ import annotations

import json
from pathlib import Path


def find_event_files(roots: list[Path], depth: int = 3) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        root = Path(root)
        if root.is_file():
            out.append(root)
            continue
        for d in range(depth + 1):
            out += sorted(root.glob("/".join(["*"] * d + ["ram_events.jsonl"])))
    return sorted(set(out))


def load_file(path: Path) -> tuple[dict, list[dict]]:
    """(meta, records). meta carries the start checkpoint/state hash from ram_trace.jsonl when present."""
    meta: dict = {"run": Path(path).parent.name, "dir": str(Path(path).parent)}
    recs: list[dict] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if "ev" in r:
            r["run"] = meta["run"]
            recs.append(r)
    trace = Path(path).parent / "ram_trace.jsonl"
    if trace.is_file():
        first = trace.read_text(encoding="utf-8").split("\n", 1)[0]
        try:
            meta.update({k: v for k, v in json.loads(first).items() if k != "t0"})
        except ValueError:
            pass
    return meta, recs


def load_all(roots: list[Path]) -> tuple[list[dict], dict[str, dict]]:
    """All records across runs plus per-run meta (keyed by run dir name)."""
    records: list[dict] = []
    metas: dict[str, dict] = {}
    for f in find_event_files(roots):
        meta, recs = load_file(f)
        metas[meta["run"]] = meta
        records += recs
    return records, metas
