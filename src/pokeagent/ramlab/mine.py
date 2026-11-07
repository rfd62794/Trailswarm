"""Rank (event type, address) candidates from event RAM diffs.

For each pair: support (records of the event where the byte changed), specificity (change rate on this event
minus the rate on other events), consistency (fraction of the changes that share one kind: increments, a
set bit, a copy of an id seen in the event context ...). Records whose diff was truncated cannot prove an
absence, so they only count toward a rate where they list the address.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from pokeagent.ramlab.kinds import kinds_of

KIND_ORDER = ("set_bit", "clear_bit", "inc1", "dec1", "copy", "zero", "const", "inc", "dec")


@dataclass
class Candidate:
    event: str
    addr: int
    support: int
    rate: float
    rate_other: float
    specificity: float
    kind: str
    consistency: float
    runs: int
    score: float
    examples: list = field(default_factory=list)     # (before, after)
    places: list = field(default_factory=list)       # (map, x, y)
    witnesses: list = field(default_factory=list)    # (run, step) of records that show it

    def key(self) -> str:
        return f"{self.event}@{self.addr:04X}"


def _best_kind(counter: Counter, total: int) -> tuple[str, float]:
    def rank(k: str) -> int:
        return KIND_ORDER.index(k.split(":")[0])
    best = min(counter, key=lambda k: (-counter[k], rank(k), k))
    return best, counter[best] / total


def mine(records: list[dict], min_support: int = 3, min_specificity: float = 0.3) -> list[Candidate]:
    full: Counter = Counter()                 # event -> records with an untruncated diff
    present: dict = defaultdict(Counter)      # event -> addr -> records listing the addr
    present_trunc: dict = defaultdict(Counter)
    kinds: dict = defaultdict(lambda: defaultdict(Counter))
    run_sets: dict = defaultdict(lambda: defaultdict(set))
    ex: dict = defaultdict(lambda: defaultdict(list))
    addr_total: Counter = Counter()           # event-agnostic presence, for the 'other events' rate
    addr_trunc: Counter = Counter()
    total_full = 0
    for r in records:
        trunc = bool(r.get("n"))
        total_full += not trunc
        for e in r["ev"]:
            full[e] += not trunc
        for addr, b, a in r["d"]:
            addr_total[addr] += 1
            addr_trunc[addr] += trunc
            ks = kinds_of(b, a, r.get("vals"))
            for e in r["ev"]:
                present[e][addr] += 1
                present_trunc[e][addr] += trunc
                for k in ks:
                    kinds[e][addr][k] += 1
                run_sets[e][addr].add(r["run"])
                if len(ex[e][addr]) < 9 and sum(1 for x in ex[e][addr] if x[1] == r["run"]) < 3:
                    ex[e][addr].append((r["step"], r["run"], b, a, (r["map"], r["x"], r["y"])))
    out: list[Candidate] = []
    for e, per in present.items():
        for addr, c in per.items():
            if c < min_support:
                continue
            den_e = full[e] + present_trunc[e][addr]
            rate = c / den_e if den_e else 0.0
            den_o = (total_full - full[e]) + (addr_trunc[addr] - present_trunc[e][addr])
            rate_o = (addr_total[addr] - c) / den_o if den_o else 0.0
            spec = rate - rate_o
            if spec < min_specificity:
                continue
            kind, cons = _best_kind(kinds[e][addr], c)
            runs = len(run_sets[e][addr])
            score = spec * cons * math.log2(1 + c) * (0.5 + 0.5 * min(runs, 3) / 3)
            samples = ex[e][addr]
            out.append(Candidate(e, addr, c, round(rate, 3), round(rate_o, 3), round(spec, 3), kind, round(cons, 3), runs,
                                 round(score, 3), [(b, a) for _, _, b, a, _ in samples], [p for *_, p in samples],
                                 [(run, step) for step, run, *_ in samples]))
    out.sort(key=lambda c: (-c.score, c.addr))
    return out
