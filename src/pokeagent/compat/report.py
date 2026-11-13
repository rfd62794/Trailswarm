"""Assemble the compat report (JSON-able dict) and its plain summary."""
from __future__ import annotations

import datetime
import hashlib
from pathlib import Path

from pokeagent.compat.addresses import compare_addresses
from pokeagent.compat.maps import compare_memory
from pokeagent.compat.thresholds import evaluate


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_report(baseline: dict, candidate: dict, *, baseline_addresses: list | None = None,
                 candidate_addresses: list | None = None, overrides: dict | None = None,
                 baseline_name: str = "baseline", candidate_name: str = "candidate", inputs: dict | None = None) -> dict:
    memory = compare_memory(baseline, candidate)
    addrs = compare_addresses(baseline_addresses, candidate_addresses) \
        if baseline_addresses is not None and candidate_addresses is not None else None
    rules, verdict = evaluate(memory, addrs, overrides)
    return {"schema": 1, "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "baseline_name": baseline_name, "candidate_name": candidate_name, "inputs": inputs or {},
            "memory": memory, "addresses": addrs if addrs is not None else "skipped",
            "thresholds_status": "proposed", "thresholds_overridden": sorted(overrides or {}),
            "rules": rules, "verdict": verdict}


def summary(rep: dict) -> str:
    lines = [f"verdict: {rep['verdict']}  ({rep['baseline_name']} vs {rep['candidate_name']})"]
    for r in rep["rules"]:
        lines.append(f"  {r['status']:<12} {r['rule']}: {r['value']} (threshold {r['threshold']})")
    if rep["addresses"] == "skipped":
        lines.append("addresses: skipped")
    for w in rep["memory"]["worst"][:3]:
        lines.append(f"  worst map {w['map']}: unexplained walls {w['unexplained']}, candidate-only tiles {w['candidate_only']}")
    lines.append("thresholds are proposals")
    return "\n".join(lines[:15])
