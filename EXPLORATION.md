# PokeAgent: exploration lane

Robert's lane: weekly-hour cap, no due date. One experiment at a time, negative
results count. Write one line before each session: what do I want to learn tonight.

## Findings

- 2026-11-04 `tools/env_rate.py` (lean env, bare PyBoy null window): ~3,500
  raw frames/s, ~1,018 steps/s at agent pacing (tick 4/step), ~261 at full
  human presses (24 frames), ~3,269 at RL-min presses. Emulation is NOT the
  bottleneck — the explorer's ~11 steps/s is planning overhead. RL on
  segments is CPU-feasible: 1M lean steps ≈ 5–15 min single env.
- 2026-11-04 `tools/rl_dataset.py` (corpus filter): 283k successful-segment
  rows in 504 runs, 182k unique after global dedupe. Shards in
  `runs/rl_dataset/`. Stall signature (8+ identical presses) is heavy:
  28,676/136,504 to_pewter rows (~21%), 9,713/25,421 beat_brock — confirms
  the visible clumsiness and the need to drop/filter stalls before cloning.
- 2026-11-04 dataset shape: rows carry (from, button, to, moved) but not the
  KB/goal state the planner uses — fits a world-model experiment (predict
  `to` from position+button) better than policy cloning. Battle detail
  (HP/party) lives in `runs/battles.jsonl`, a separate join.
- 2026-11-04 `--starter` is cosmetic on segment runs (party comes from the
  checkpoint); the milestone starter split is confounded by agent role
  (explorer vs exploiter), not starter type.
