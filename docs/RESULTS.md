# Results

These are the measured results so far. Numbers come from the project's own run logs; nothing here is a benchmark against other agents.

## Overnight continuous swarm (2026-11-05 to 06)

The continuous swarm (`tools/swarm.py --continuous --plan curriculum`) ran 8 agents and finished 500 runs. Along the way it:

- reached Cerulean City,
- beat Misty,
- crossed Nugget Bridge (Route 24),
- mapped battles on the way.

It is currently stuck before Bill's house: the `to_bill` segment is at 0 of 288 attempts.

## Battle-text wait (pending change, not merged)

Fresh game, 3,000-step budget, 3 seeds, before versus after the pending battle-text-wait change. Values are steps to reach the goal, listed per seed.

| goal | before | after |
|---|---|---|
| `to_pewter` | not reached / 2953 / 2630 | 2006 / 1917 / 1847 |

With the change, `beat_brock` was reached on 2 of 3 seeds. This change is not merged; treat these numbers as preliminary until it is.

## Fewer wasted presses

An earlier fix cut no-op A presses per run from about 198 to 16-31.

## Mt Moon

Mt Moon was traversed on 3 of 3 seeds on an earlier harness, after the agent gained ROM-derived collision data and multi-floor planning.
