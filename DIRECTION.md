# PokeAgent: direction

PokeAgent = reference agent + exploration lane.

## Queue gate (Devin builds)

Phase 1 done = all of:

1. One unbroken run from `baselines/bedroom.state` to the Boulder Badge — rule-based
   agent, zero consults — logged.
2. >=50% of 24 consecutive `beat_brock` segment runs succeed.
3. README + short writeup.

Starter: segment runs inherit the party from the checkpoint, so `--starter` is cosmetic
there and the 24-run `beat_brock` condition is starter-agnostic. For the unbroken run the
starter is chosen for real at Oak's lab — decide it from evidence once merged-SHA runs
exist (`tools/swarm.py --starter` pins full runs).

Measure: `uv run python tools/status.py` (read-only; reports the numbers above).

Review checkpoint: 2026-11-15 — a checkpoint for Robert to ask whether this still pulls
him, not a deadline.

Out of scope for the queue: viewer GUI, hybrid mode, Phase 4, anything past Brock,
new MCP tools.

Gate: every directive names the finish-line metric it moves, or it isn't queued.

## Exploration lane (Robert; weekly-hour cap, no due date)

Portability, RAM discovery, language schema, model training — one experiment at a time,
negative results count. Log one-line findings in `EXPLORATION.md`.
