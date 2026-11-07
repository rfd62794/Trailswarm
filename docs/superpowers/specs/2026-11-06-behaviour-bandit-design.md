# Behaviour bandit, v1 (2026-11-06)

A contextual bandit that overrides the rule-based Explorer at three decision points. It never picks buttons. Off by
default. Items marked **(builder)** were settled while building; everything else is the controller's decision.

## Decisions

1. **Arms are choices at three decision points.**
   - `wild_battle`: `fight` or `flee` (catching stays rule-driven).
   - `heal`: `heal_now` or `push_on`, below 50% HP outside battle with a Pokecenter map known.
   - `train`: `grind` or `skip`, when `train_need` is above the lead's level.
   The bandit sets the answer the existing behaviours read; the Explorer's own rule is each point's *default arm*.
2. **Context key:** `point|goal_stage|map_id|hp_bucket|level_gap_bucket`. HP buckets 0-25/25-50/50-75/75-100.
   Gap buckets `<=-3`, `-2..0`, `1..3`, `>3`.
3. **Algorithm:** Thompson sampling, Gaussian posterior on the mean reward per (context, arm). The prior is the
   Explorer's default arm; a context behaves like the Explorer until the default has `MIN_N = 5` episodes.
4. **Reward per decision episode** (decision to next goal or 300 presses): -presses/100, +1 goal, -2 stall,
   -3 blackout, -5 `item_tossed`. Sparse, no per-step shaping.
5. **Storage:** shared `runs/bandit.json`. Each agent loads it at start and writes per-run deltas
   (`n`, `sum`, `sumsq` per context and arm). A merge adds deltas into the shared table under a lock.
6. **Off by default:** `ExplorerOptions.bandit`, `--bandit` on `tools/explore_demo.py` and
   `tools/explore_headless.py`. `swarm.py --continuous --bandit [--bandit-share F]` (default 0.5) runs that share of
   slots with it on; the rest are the control. Decision lines of a bandit run carry `driver: explorer|bandit` and `arm`.
7. **Layout:** `src/pokeagent/bandit/` (`table.py`, `points.py`, `reward.py`, plus `driver.py`, `hook.py`, `store.py`);
   it imports from `explorer`, never from `tools/`.

## Builder's calls

- **Where the arms act.** `hook.wild_flee` replaces the flee test in `behaviours/battle.py`; `hook.heal_push_on` adds
  `_push_on` to the planner's goals dict and `planner.plan_step` skips its Pokecenter branch when set;
  `hook.train_need` returns 0 for `skip` (the gate is lifted, as `area_grind` does) in `plan_goal.py`.
- **Thompson details.** Posterior mean = (2 x prior + sum) / (2 + n); sd = sample std (floor 0.25, 1.0 until two
  samples) / sqrt(2 + n). Default arm prior 0.0 (optimistic: real episodes are negative); once the default has 5
  samples, every arm's prior mean is the default's empirical mean, alternatives minus 0.1, so an untried arm is
  explored but must earn the switch.
- **Sticky choice.** One arm per situation: per battle for `wild_battle`, per low-HP spell for `heal`, per
  below-target spell for `train`. A new decision (and a new episode) starts when the situation ends or the episode
  closes. Episodes may overlap across points. Episodes cut off by the end of a run are dropped, not scored.
- **Level gap per point.** `wild_battle`: lead level minus enemy level. `heal` and `train`: lead level minus the
  training target (so `train` only ever lands in the two negative buckets).
- **Stall.** The swarm's stall-kill happens outside the process, so the in-process stand-in is the StallGuard's
  `stall_escalate` decision: -2 once per episode.
- **Blackout.** Detected as an increase of `ctx.blackouts_row`; the driver writes an `event: blackout` line.
- **Decision lines.** `driver`/`arm` are added only when the bandit is attached, so existing log consumers and
  the flag-off output are unchanged; a missing `driver` means the Explorer. `driver` is `bandit` only on a step where an
  arm *deviated* from the Explorer's default.
- **Idempotent merge.** A delta carries a run id; `runs/bandit.json` remembers the last 5000 merged ids, so a retry
  or a concurrent merge never double-counts. The lock is `runs/bandit.lock` (Windows-safe acquire and release).
- **Swarm wiring.** The Launcher passes `--bandit-delta <agentN-seq>.bandit.json` beside the agent's memory file;
  `Supervisor._finish` merges it into `runs/bandit.json` right after the memory merge (also when the agent's memory was
  untouched or unmergeable). A standalone run writes `<run dir>/bandit_delta.json`. Only `--continuous` is wired.
- **Saves.** The delta is rewritten every 10 closed episodes and at exit, so a killed agent keeps what it learned.

## Shields (controller, round 2)

- `wild_battle` does not apply when the rules would try a catch (`battle_run.catch_target`: a POKe BALL in the bag and
  an unowned species); the Explorer's answer stands and no episode opens.
- `hook.FIGHT_FLOOR = 0.25`: below 25% lead HP the bandit never chooses `fight` (flee, no episode).

## Known limits

- Few episodes close per short run; swarm runs use 3000-8000 steps, which helps.
