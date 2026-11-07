"""Check 5: bandit, novelty, grind-atlas and economy tables parse, hold no NaN/inf or negative counts, and merged run ids are unique."""
from __future__ import annotations

import math
from pathlib import Path

from pokeagent.invariants.findings import ERROR, INFO, Finding, read_json

# file -> (section whose entries hold counts, key of the merged-run-id list or None)
TABLES = {
    "bandit.json": ("cells", "merged"),        # cells: {cell: {action: [n, reward_sum, ...]}}; n = element 0
    "novelty.json": ("counts", "merged"),      # counts: {key: int}
    "grind_atlas.json": ("stats", None),       # stats: {key: [fights, wins, ...]}; first two are counts
    "economy.json": (None, None),
}
COUNT_INDEXES = {"bandit.json": (0,), "grind_atlas.json": (0, 1)}


def _numbers(v, path=""):
    if isinstance(v, bool):
        return
    if isinstance(v, (int, float)):
        yield path, v
    elif isinstance(v, dict):
        for k, x in v.items():
            yield from _numbers(x, f"{path}/{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from _numbers(x, f"{path}[{i}]")


def _count_leaves(fname: str, section: dict):
    idx = COUNT_INDEXES.get(fname)
    for k, v in section.items():
        if idx is None:
            yield from _numbers(v, f"/{k}")
        else:
            yield from ((p, n) for p, n in _numbers(v, f"/{k}") if any(p.endswith(f"[{i}]") for i in idx))


def check_tables(runs_dir: Path) -> list[Finding]:
    out: list[Finding] = []
    for fname, (section, merged_key) in TABLES.items():
        data, err = read_json(runs_dir / fname)
        if err:
            out.append(Finding("tables", ERROR, "unparsable", f"{fname}: {err}", {"file": fname}))
            continue
        if data is None:
            out.append(Finding("tables", INFO, "missing", f"{fname}: not present", {"file": fname}))
            continue
        if not isinstance(data, dict):
            out.append(Finding("tables", ERROR, "not_object", f"{fname}: top level is {type(data).__name__}, expected object", {"file": fname}))
            continue
        nan = [p for p, n in _numbers(data) if isinstance(n, float) and not math.isfinite(n)]
        if nan:
            out.append(Finding("tables", ERROR, "nan", f"{fname}: {len(nan)} NaN/inf values, e.g. {nan[0]}", {"file": fname, "paths": nan[:10]}))
        if section and isinstance(data.get(section), dict):
            neg = [p for p, n in _count_leaves(fname, data[section]) if n < 0]
            if neg:
                out.append(Finding("tables", ERROR, "negative_count", f"{fname}: {len(neg)} negative counts, e.g. {section}{neg[0]}",
                                   {"file": fname, "paths": neg[:10]}))
        if merged_key and isinstance(data.get(merged_key), list):
            ids = data[merged_key]
            seen, dup = set(), []
            for i in ids:
                if i in seen and i not in dup:
                    dup.append(i)
                seen.add(i)
            if dup:
                out.append(Finding("tables", ERROR, "duplicate_merged", f"{fname}: {len(dup)} duplicated merged run ids, e.g. {dup[0]}",
                                   {"file": fname, "ids": dup[:10]}))
    return out
