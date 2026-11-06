# PokeAgent: Gen 1 battle simulator - train and plan in simulation, judge on the real game

**Read first:** `docs/directives/Game_Knowledge_Directive.md`, `src/pokeagent/explorer/battle.py`,
`src/pokeagent/explorer/stats.py`, `src/pokeagent/ramstructs.py`.
**Depends on:** Game Knowledge merged (species base stats, learnsets, move effects, trainer parties). If missing, stop.
**Builder:** a Claude builder on the laptop with the ROM, `kb/` and checkpoint copies (gitignored).
**Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-05, approved): train and plan in a high-speed simulation, then test on the real game. The emulator
already is the real game (deterministic from any save state), so we do not re-create the whole game - only the
part where massive repetition pays: **battles**. A battle sim built from the cartridge's own data lets the agent
evaluate thousands of fights per second for party readiness, counter planning, move/switch policy learning (the
place where RL is cheap), and "are we ready for Misty?" - and every prediction is checked on the emulator from the
same save state (sim-to-real).

## 2. Scope (in order)

1. `src/pokeagent/sim/battle.py`: a pure, seeded Gen 1 battle engine: stats from base/DV/stat-exp/level (reuse
   `explorer/stats.py`), the Gen 1 damage formula, type chart, STAB, random factor 217-255, critical hits from
   base Speed (Focus Energy quirk), the 1/256 miss on 100%-accuracy moves, accuracy/evasion stages, stat stages,
   status (sleep, poison, burn, paralysis, freeze, confusion), multi-hit, two-turn, recharge, fixed damage, drain,
   recoil, trapping, flinch, PP. Effects driven by the Game Knowledge effect table, not by move names.
2. Opponent AI: wild = random among known moves; trainers = the Gen 1 trainer AI rules (document which subset is
   modelled; unknown rules fall back to random).
3. `sim/policy.py`: our side's decision interface (same choices as the real battle menu: move, switch, item, run)
   so the real battle behaviour and the sim share one policy object; `sim/rollout.py`: run N seeded battles,
   return win rate, turns, HP left, faint counts.
4. **Sim-to-real harness** `tools/sim_vs_real.py`: from real pre-battle save states (make them by walking into
   grass / trainers from checkpoints), read both parties from RAM, simulate N times, then play the real battle in
   the emulator with the same policy; report predicted vs real: winner, turns, damage per hit range, and list
   mechanics where the real battle fell outside the sim's distribution (each one is a sim bug to fix).
5. Consumers (after the sim passes the harness): party readiness and the counter planner may call
   `rollout` instead of their closed-form scores (behind a named flag, default off until measured).

## 3. The work

Pure, deterministic under a seed, no emulator calls inside `sim/`. Keep modules <= 300 lines (split mechanics by
area). Named constants for every quirk with a docstring citing the mechanic.

## 4. What NOT to do

- Do not change live battle behaviour in this directive except the flagged consumer hook (default off).
- No new dependencies; never commit ROM bytes or kb/.

## 5. Verification

- `uv run pytest -q` green; unit tests per mechanic against hand-computed values (damage formula examples, crit
  rate from Speed, 1/256 miss, stat stages, status).
- Harness on >= 20 real battles (wild + at least one trainer): the real damage of every hit falls inside the sim's
  predicted range, and the predicted win probability is calibrated (report the table). Every miss of the range is
  listed with the move and situation.

## 6. Rules for this run

- Branch `directive/pokeagent-battle-simulator-directive` in a scratchpad worktree off main. Never commit to
  `main`. Test command `uv run pytest -q`. Never bare `python`. Headless only.

## 7. Completion criteria

- [ ] `sim/` engine + AI + shared policy interface + rollout
- [ ] `tools/sim_vs_real.py` harness results pasted (>= 20 battles)
- [ ] flagged consumer hook for readiness / counters

## 8. Report

Mechanics covered, harness table, test tail, gaps found.
