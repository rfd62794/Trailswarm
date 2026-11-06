"""Auto-verification: replay the recorded witnesses of a candidate and assert the predicted change.

Per witness (run, step): the replayed pre-state must match the recorded 'before' byte (the replay is in sync)
and the press must produce the predicted kind of change. A control replay of the same stretch WITHOUT the press
says whether the change is press-driven or time-driven (a menu/text box keeps opening on its own after an
earlier press); that is reported in the evidence, not required. A finding is verified only when >= MIN_WITNESSES
witnesses are all in sync and at least two thirds reproduce the change.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from pokeagent.ramlab.findings import finding_name
from pokeagent.ramlab.kinds import describe, matches
from pokeagent.ramlab.labels import LabelIndex
from pokeagent.ramlab.mine import Candidate
from pokeagent.ramlab.replay import Unreplayable, load_trace

MIN_WITNESSES = 2


def judge(kind: str, vals: dict, recorded_before: int, ev: list[int], ct: list[int]) -> dict:
    """One witness: ev/ct are [pre, samples...] with and without the press."""
    pre = ev[0]
    changed = lambda s: s != pre and matches(kind, pre, s, vals)
    return {"in_sync": pre == recorded_before, "event_ok": any(changed(s) for s in ev[1:]),
            "control_clean": not any(s != ct[0] and matches(kind, ct[0], s, vals) for s in ct[1:])}


def passed(results: list[dict]) -> bool:
    ok = [r for r in results if r["in_sync"] and r["event_ok"]]
    return len(results) >= MIN_WITNESSES and all(r["in_sync"] for r in results) and len(ok) * 3 >= len(results) * 2


def evidence_text(c: Candidate, results: list[dict]) -> str:
    ok = sum(r["event_ok"] for r in results)
    drive = "press-driven" if all(r["control_clean"] for r in results) else "time-driven (also changes without the press)"
    return (f"{c.event}: byte {describe(c.kind)} ({c.support} occurrences in {c.runs} run(s), specificity {c.specificity}, "
            f"consistency {c.consistency}); replay: {ok}/{len(results)} witnesses reproduce it, {drive}")


def gather(cands: list[Candidate], by_key: dict, runs_dir: dict[str, Path], per: int = 3) -> dict[str, dict[int, list]]:
    """run -> step -> [(candidate, record, before)] for the replayable witnesses of each candidate."""
    plan: dict = defaultdict(lambda: defaultdict(list))
    for c in cands:
        n, seen = 0, defaultdict(int)
        ordered = []
        for run, step in c.witnesses:
            seen[run] += 1
            ordered.append((seen[run], run, step))
        for _, run, step in sorted(ordered, key=lambda t: t[0]):
            rec = by_key.get((run, step))
            if rec is None or run not in runs_dir or n >= per:
                continue
            before = next((b for a, b, _ in rec["d"] if a == c.addr), None)
            if before is None:
                continue
            plan[run][step].append((c, rec, before))
            n += 1
    return plan


def run_checks(cands: list[Candidate], records: list[dict], runs_dir: dict[str, Path], replayer: Any,
               labels: LabelIndex) -> tuple[list[dict], list[dict]]:
    """(verified-or-not findings, per-candidate notes). ``runs_dir`` maps run name -> run directory."""
    by_key = {(r["run"], r["step"]): r for r in records}
    plan = gather(cands, by_key, runs_dir)
    results: dict[str, list[dict]] = defaultdict(list)
    notes: dict[str, str] = {}
    for run, steps in plan.items():
        try:
            _, presses = load_trace(runs_dir[run])
            pres = replayer.pre_states(runs_dir[run], sorted(steps))
        except Unreplayable as e:
            for items in steps.values():
                for c, *_ in items:
                    notes[c.key()] = str(e)
            continue
        for step, items in steps.items():
            if step not in pres or step > len(presses):
                continue
            press = presses[step - 1]
            gap = presses[step][0] - press[0] if step < len(presses) else 120
            addrs = sorted({c.addr for c, *_ in items})
            ev, ct = replayer.branches(pres[step], press, gap, addrs)
            for c, rec, before in items:
                results[c.key()].append(judge(c.kind, rec.get("vals", {}), before, ev[c.addr], ct[c.addr]))
    findings = []
    for c in cands:
        res = results.get(c.key(), [])
        status, lb = labels.join(c.event, c.addr)
        ok = passed(res)
        findings.append({
            "addr": f"0x{c.addr:04X}", "event": c.event, "kind": c.kind, "status": status,
            "label": lb.name if lb else "", "label_size": lb.size if lb else 0, "name": finding_name(c.event, c.addr, lb), "verified": ok,
            "evidence": evidence_text(c, res) if res else notes.get(c.key(), "no replayable witness"),
            "stats": {"support": c.support, "runs": c.runs, "specificity": c.specificity, "consistency": c.consistency,
                      "score": c.score},
            "replay": {"witnesses": len(res), "passed": sum(r["event_ok"] for r in res),
                       "in_sync": sum(r["in_sync"] for r in res)}})
    return findings, [{"key": k, "note": n} for k, n in notes.items()]
