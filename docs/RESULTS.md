# Results

These are the measured results so far. Numbers come from the project's own run logs; nothing here is a benchmark against other agents.

## Overnight continuous swarm (2026-11-05 to 06)

The continuous swarm (`tools/swarm.py --continuous --plan curriculum`) ran 8 agents and finished 500 runs. Along the way it:

- reached Cerulean City,
- beat Misty,
- crossed Nugget Bridge (Route 24),
- mapped battles on the way.

Update (2026-11-08): the `to_bill` segment has been solved. Best run `explore-20261107-082910-320` reached Bill's house (map `0x58`) in 2,177 steps on 2026-11-07, at about a 10% success rate over recent attempts. This confirms the segment, not the full curriculum chain.

## Battle-text wait (merged, PR #90)

Fresh game, 3,000-step budget, 3 seeds, before versus after the battle-text-wait change. Values are steps to reach the goal, listed per seed.

| goal | before | after |
|---|---|---|
| `to_pewter` | not reached / 2953 / 2630 | 2006 / 1917 / 1847 |

With the change, `beat_brock` was reached on 2 of 3 seeds.

## Fewer wasted presses

An earlier fix cut no-op A presses per run from about 198 to 16-31.

## Mt Moon

Mt Moon was traversed on 3 of 3 seeds on an earlier harness, after the agent gained ROM-derived collision data and multi-floor planning.
