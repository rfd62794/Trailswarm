"""mine -> select -> replay-verify -> findings: shared by tools/ram_discover.py and tools/ram_checks.py."""
from __future__ import annotations

import tempfile
from collections import Counter
from pathlib import Path

from pokeagent.ramlab import findings as F
from pokeagent.ramlab.labels import LabelIndex, load_entries
from pokeagent.ramlab.mine import Candidate, mine
from pokeagent.ramlab.records import load_all
from pokeagent.ramlab.replay import Replayer
from pokeagent.ramlab.verify import run_checks

RECHECK = (0xD059,)           # wCurOpponent: the hand-written check failed on a wild battle; always re-test from the data
SKIP_EVENTS = {"goal"}           # fires with whatever else happened that step: no specific meaning to test


def select(cands: list[Candidate], labels: LabelIndex, top: int, per_label: int = 3) -> list[Candidate]:
    """Best ``top`` candidates, at most ``per_label`` per (event, label) so one big struct cannot crowd the rest."""
    seen: Counter = Counter()
    out: list[Candidate] = []
    for c in cands:
        if c.event in SKIP_EVENTS:
            continue
        if labels.join(c.event, c.addr)[0] == "stack":
            continue
        lb = labels.at(c.addr)
        key = (c.event, lb.name if lb else c.addr >> 4)
        if seen[key] >= per_label:
            continue
        seen[key] += 1
        out.append(c)
        if len(out) >= top:
            break
    return out


def mine_runs(roots: list[Path], min_support: int = 3, entries: list[dict] | None = None):
    records, metas = load_all(roots)
    labels = LabelIndex(entries if entries is not None else load_entries())
    return records, metas, labels, mine(records, min_support)


def verify_top(roots: list[Path], rom: Path, states: Path, top: int = 40, min_support: int = 3,
               entries: list[dict] | None = None, include: tuple[int, ...] = RECHECK) -> tuple[list[dict], list[dict], list[Candidate]]:
    """Mine, take the top candidates, replay-verify them. Returns (findings, notes, candidates)."""
    records, metas, labels, cands = mine_runs(roots, min_support, entries)
    chosen = select(cands, labels, top)
    have = {c.key() for c in chosen}
    for addr in include:                     # always test these addresses, whatever their rank
        extra = [c for c in cands if c.addr == addr and c.event not in SKIP_EVENTS and c.key() not in have][:3]
        chosen += extra
        have |= {c.key() for c in extra}
    runs_dir = {r: Path(m["dir"]) for r, m in metas.items() if (Path(m["dir"]) / "ram_trace.jsonl").is_file()}
    with tempfile.TemporaryDirectory(prefix="ramlab_") as tmp:
        rep = Replayer(rom, states, Path(tmp))
        try:
            findings, notes = run_checks(chosen, records, runs_dir, rep, labels)
        finally:
            rep.close()
    return findings, notes, chosen


def record_findings(findings: list[dict], path: Path = F.FINDINGS_PATH) -> dict:
    """Merge into ram_findings.json by (event, addr): replay-refuted hypotheses go under 'failed', the rest
    (verified, or not yet replayable) under 'findings'. A verified finding is never displaced."""
    data = F.load(path)
    for f in findings:
        refuted = not f["verified"] and f["replay"]["witnesses"] > 0 and f["replay"]["passed"] * 3 < f["replay"]["witnesses"] * 2
        F.upsert(data, f, "failed" if refuted else "findings")
    won = {(f["event"], f["addr"]) for f in data["findings"] if f.get("verified")}
    data["failed"] = [x for x in data["failed"] if (x["event"], x["addr"]) not in won]
    F.save(data, path)
    return data
