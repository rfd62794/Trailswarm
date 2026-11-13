# Training v2: raise xp/1k steps on the team_ready stage

**Evidence (laptop, real ROM, 2026-11-12):** 12,000 steps from the Cerulean Pokecenter toward beat_misty (main with #232 XP
measurement). Never reached Misty: the whole run was `team_ready` (floor L19 x2 members). Final party: Magikarp-line L8/7/8/9/12
+ one fighter L26. Route 24 154 xp/1k steps (30 battles); Cerulean 305 xp/1k. Steps per map: Route 24 8747, Cerulean 2124,
Pokecenter 1108. `thinking:` lines: FIGHT 4445, walk to grass 1608, heal 973, leave Pokecenter 200, SHAKE ~1090, shake box 207,
close box B 356, text box 291, busy-A 181.
`tools/step_budget.py RUN_DIR` reproduces that table from console.log.

## What is already built (checked against main cdd3ed9)

| Directive | State |
|---|---|
| Magikarp_Switch_Training | **Built**: `behaviours/switch_out.py` (switch_out_lead), `bring_out.py`, `trainee_gate.py`, `trainee.py`. |
| Grind_Points | **Built**: `grind/` (points, atlas, centers, measure, xpmath), `grind_episode.py`, `area_grind.py`. |
| Trainer_Ledger_And_Battle_Avoidance | `trainer_ledger.py` / `grind/trainer_spots.py` exist; trainer XP is not chosen as a stage. |
| xp measurement (#232) | **Built**: `xp_meter.py`, `xp_spots.py` ledger. "Measurement only: nothing picks a spot." |
| Level_Banded_Grind | **Not built** (status Queued): weak trainee still trains by the switch trick, `choose()` never asks if it could win alone. |

Why switch-training did not lift this run: it gives the trainee only a *share* (XP is split among participants; trainee + fighter =
half) and the fighter (L26) is far over the wild L8-12 on Route 24, so each battle is cheap XP split two ways, and the stage
still needs 2 members at L19. It also does nothing about the ~10% shake loop, the walk-to-grass churn or heal trips.

## Levers, ranked by expected xp/1k gain over cost

| # | Lever | Evidence | Gain / cost | Acceptance metric |
|---|---|---|---|---|
| 1 | **(c) Stay in the grass: stop shake loops** that fire on a training pace | SHAKE ~1090 + shake-box 207 + B-close 356 = ~1650 lines, ~14% of steps | ~+12% xp/1k, tiny code, ROM-free tests. **Slice 1, done.** | SHAKE+shake-box lines < 3% of steps; Route 24 xp/1k > 175 from this alone |
| 2 | **(c) Cut walking-to-grass churn** (re-entering Route 24 after every heal; Cerulean 2124 steps) | 1608 walk lines, Cerulean 2124 steps, 200 leaving-Pokecenter | ~+10%; needs `train_route`/grind_episode changes | walk-to-grass lines < 5% of steps |
| 3 | **(d) Fewer heal trips**: heal only when the survival floor says so; buy/use Potions | 973 heal lines + 1108 Pokecenter steps (~17%) | ~+15%, medium (economy + survival floor) | heal+Pokecenter steps < 8%; trips per 1k steps halved |
| 4 | **(b) Pick the spot by xp_spots + wild bands** instead of nearest grass | Route 24 154 vs Cerulean 305 xp/1k: the ledger already knows it | up to 2x on the best cell; medium (`grind/points.choose` already scores xp/min; wire xp_spots into it) | trainee xp/1k on the chosen map > 400 |
| 5 | **Level-banded grind** (full XP, not half) | Queued directive; fighter L26 earns almost nothing on L8-12 wilds | high but large and RNG-prone; do after 1-4 | trainee xp/1k > 2x switch-trained rate |
| 6 | **(e) Trainer XP** (Nugget Bridge before wild) | trainer x1.5 XP and no encounter RNG; ledger exists, stage does not | high, large (routing + battle avoidance) | xp/1k on bridge > wild by 1.5x |
| 7 | **(f) Two members in parallel** (floor = 2 members) | floor met by only one at L26 | halves time to floor; interacts with switch logic, hard to test w/o ROM | both members >= floor within 12k steps |
| 8 | **(a) Switch-training** | built; see above | already banked | `magikarp_shared` per battle ~ 1 |

## Slice 1 (this PR)

* `behaviours/grind_loop.py` + `guards.py`: LoopGuard's "60 presses on <=6 tiles" shake is skipped when the team_ready stage is
  training and a battle began inside that 60-press window (pacing in grass IS the training). A window without a battle still
  shakes, so a real edge stall is still broken; the 150-press and A-streak guards are untouched.
* `tools/step_budget.py` + test: the before/after measurement.

## Next slices

Lever 3 (heal only on the survival floor), then lever 4 (feed `xp_spots` rates into `grind/points.choose`), then lever 2.
Re-run the laptop measurement after each.

## Slice 3 (2026-11-13 A/B follow-up)

* `grass_pace.py` (via `train_route.step`): ON the grass the step used to be None, so frontier paced the patch edge (no encounter
  roll off-grass; no battle in the window, so slice 2's exemption never applied). Now it paces INSIDE grass tiles (ROM grid, else
  encounters + patch).
* `center_visit.py`: the Pokecenter walk-in + nurse dialog + walk-out is 60+ presses on <=6 tiles; LoopGuard shook at the exit.
  Exempt inside a Pokecenter, capped 150 presses per visit.
* `grind_heal.py`: while grinding, retreat_heal's LEAD/PARTY gates and frontier's `weak` (0.4) use `party_survives`; a usable field
  Potion (`wants_topup`) replaces the Pokecenter trip. `after_heal.py`: the center exit is train_route's walk to the grass.
Expected laptop A/B (seed 12, 12k steps): SHAKE ~7.9% -> <2%, to-the-Pokecenter 8.7% -> ~5%, walking-to-grass 15.6% -> ~11%.
