# PokeAgent: direction

PokeAgent = reference agent + exploration lane.

## Queue gate (Devin builds)

Phase 1 done = all of:

1. One unbroken run from `baselines/bedroom.state` to the Boulder Badge, <=10 Claude consults, logged.
2. >=50% of 24 consecutive `beat_brock` segment runs succeed.
3. README + short writeup.

Starter: Charmander, fixed for measurement — it holds the best observed `beat_brock` record
(17 of 22 milestones; Squirtle has none). `tools/swarm.py --starter charmander` pins it;
changing it requires a directive that names the metric it moves.

Measure: `uv run python tools/status.py` (read-only; reports the numbers above).

Review checkpoint: 2026-11-15 — a checkpoint for Robert to ask whether this still pulls
him, not a deadline.

Out of scope for the queue: viewer GUI, hybrid mode, Phase 4, anything past Brock,
new MCP tools.

Gate: every directive names the finish-line metric it moves, or it isn't queued.

## Exploration lane (Robert; weekly-hour cap, no due date)

Portability, RAM discovery, language schema, model training — one experiment at a time,
negative results count. Log one-line findings in `EXPLORATION.md`.
