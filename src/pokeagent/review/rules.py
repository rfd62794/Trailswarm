"""Press-share per decision rule (with its dominant behaviour)."""
from __future__ import annotations

from collections import Counter


def top_rules(decisions: list[dict], n: int = 10) -> list[dict]:
    """Top ``n`` rules by press count: [{rule, behaviour, presses, share}], ties broken by name."""
    total = len(decisions)
    by_rule: Counter = Counter()
    behav: dict[str, Counter] = {}
    for d in decisions:
        rule = str(d.get("rule"))
        by_rule[rule] += 1
        behav.setdefault(rule, Counter())[str(d.get("behaviour"))] += 1
    out = []
    for rule, presses in sorted(by_rule.items(), key=lambda kv: (-kv[1], kv[0]))[:n]:
        out.append({"rule": rule, "behaviour": behav[rule].most_common(1)[0][0],
                    "presses": presses, "share": presses / total if total else 0.0})
    return out
