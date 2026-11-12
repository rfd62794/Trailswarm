# PokeAgent: survival floor - retreat and grind gates ask "can the PARTY survive the next wild fight", not "is HP above a fraction"

## Why this exists

Robert (2026-11-12, watching a live run): "We can lower the floor for level grinding to survive most battles, not a
health level, we base it on survival of the Player." In Gen 1 the player blacks out only when EVERY party member has
fainted, so one fighter below 50% HP is not a reason to walk to the nurse while the party can still win the next fight.

Measured on the live marathon `runs/explore-20261112-164916-2064/console.log` (41,153 lines, 6,909 steps):

- `retreat_heal` started **13 heal walks** (`heal_walk: start (retreat_heal: ...)` lines) and logged 707 "would keep" verdict lines.
- Verdicts where the fighter would comfortably survive, yet it walked to the nurse:
  - `[heal_walk: start (retreat_heal: CHARMANDER would keep 26% vs the worst wild fight here (floor 50%, nurse 1152 frames))]`
  - `[heal_walk: start (retreat_heal: CHARMANDER would keep 47% vs the worst wild fight here (floor 55%, nurse 640 frames))]`
  - `[heal_walk: start (retreat_heal: PIDGEY would keep 33% vs the worst wild fight here (floor 46%, nurse 1504 frames))]`
- Verdicts driven by a weak bench member while the rest of the party was fine (284 lines say "keep 0%"):
  - `[heal_walk: start (retreat_heal: PIDGEY would keep 0% vs the worst wild fight here (floor 55%, nurse 416 frames))]`
  - `[heal_walk: start (retreat_heal: RATTATA would keep 6% vs the worst wild fight here (floor 50%, nurse 1120 frames))]`
- Only 1 of the 13 walks was the whole-party catch (`party at 24%, nurse 848 frames away`).

The values below (SURVIVE_NEAR 0.15, SURVIVE_FAR 0.05, PARTY_FLOOR 0.20) are **untuned first values**. The controller
(Claude) will do a real-ROM hands-off check from the bedroom and from `runs/checkpoints/to_pewter.state` after this lands.
You have no ROM; do not look for one.

## Scope

In order:
1. `src/pokeagent/explorer/retreat_risk.py`: party-survival retreat test.
2. One small pure helper for the grind gates (same file if it stays under 250 lines, else new `src/pokeagent/explorer/survival.py`).
3. Wire the grind continuation gates through the helper (list below).
4. Tests.

## The work

### 1. retreat_risk.py (86 lines today). Current code, pasted

```python
FLOOR_NEAR, FLOOR_FAR = 0.55, 0.30      # HP fraction the fighter must keep after the worst likely wild duel (untuned)
NEAR_FRAMES, FAR_FRAMES = 700, 3000     # walk to the nurse: at or below NEAR the floor is FLOOR_NEAR, at FAR it is FLOOR_FAR
MAX_WALK_FRAMES = 4000                  # a nurse farther than this is never worth a retreat (same cap as after_victory)
PARTY_FLOOR = 0.35                      # whole-party HP fraction below which a known nurse is always walked to (untuned)
MIN_CHANCE = 0.05                       # a wild species rarer than this per encounter does not set the risk

def floor_for(walk_frames: float) -> float:
    if walk_frames <= NEAR_FRAMES:
        return FLOOR_NEAR
    if walk_frames >= FAR_FRAMES:
        return FLOOR_FAR
    t = (walk_frames - NEAR_FRAMES) / (FAR_FRAMES - NEAR_FRAMES)
    return FLOOR_NEAR + t * (FLOOR_FAR - FLOOR_NEAR)

def _max_hp(c: Combatant, kb) -> int:
    row = species_row(c.name, kb)
    return _stats(row, c.level, c.dv, c.sexp)[0] if row else max(c.hp, 1)

def _worst_wild(wild: dict, kb) -> list[Combatant]:
    return [f for n, (_, hi, ch) in wild.items() if ch >= MIN_CHANCE and (f := trainer_mon(n, hi, kb))]

def assess(party, wild, walk_frames, kb=None, fighter_idx: int = 0) -> Verdict:
    if not party or walk_frames is None or walk_frames > MAX_WALK_FRAMES:
        return Verdict(False, "no party or no reachable Pokecenter")
    total_hp = sum(c.hp for c in party)
    total_max = sum(_max_hp(c, kb) for c in party) or 1
    if total_hp / total_max < PARTY_FLOOR:
        return Verdict(True, f"party at {total_hp / total_max:.0%}, nurse {walk_frames:.0f} frames away")
    fighter = party[fighter_idx] if fighter_idx < len(party) and party[fighter_idx].hp > 0 else next((c for c in party if c.hp > 0), None)
    if fighter is None:
        return Verdict(True, "everyone has fainted")
    floor = floor_for(walk_frames)
    mx = _max_hp(fighter, kb)
    left = fighter.hp / mx
    foes = _worst_wild(wild, kb)
    if foes and table(kb, "moves"):
        chart, moves = _chart(kb), table(kb, "moves")
        left = min(duel(fighter, float(fighter.hp), f, float(f.hp), chart, moves)[0] / mx for f in foes)
    if left < floor:
        return Verdict(True, f"{fighter.name} would keep {left:.0%} vs the worst wild fight here (floor {floor:.0%}, "
                             f"nurse {walk_frames:.0f} frames)")
    return Verdict(False, f"{fighter.name} keeps {left:.0%} (floor {floor:.0%})")
```

Callers (only these): `behaviours/retreat_heal.py:71` `assess(party, encounters.species_on(ctx.view.m), self._walk_frames(ctx), None, fighter_slot(ctx.emu))`
and `party_now` is imported by `behaviours/after_victory.py:21`. `floor_for` / FLOOR_NEAR / FLOOR_FAR are used only inside retreat_risk.py and `tests/test_retreat_heal.py`.

Change to **party survival**:
- Replace `FLOOR_NEAR 0.55` / `FLOOR_FAR 0.30` with `SURVIVE_NEAR = 0.15` (walk <= NEAR_FRAMES) and `SURVIVE_FAR = 0.05` (walk >= FAR_FRAMES),
  linear between, via `survive_margin(walk_frames)` (rename of `floor_for`; keep NEAR_FRAMES / FAR_FRAMES values). The margin is a cushion for damage variance and crits.
- `PARTY_FLOOR` 0.35 -> **0.20** (last catch for missing duel data).
- Retreat only when NO living party member keeps at least the margin (`readiness.duel(...)[0] / its max HP`, minimum over `_worst_wild` foes, computed exactly as today). `_worst_wild`, MIN_CHANCE, MAX_WALK_FRAMES, `Verdict`, and the `assess` signature stay.
- Order: the designated fighter (`fighter_idx`, falling back to first living member as today) is checked first. If it fails but another living member passes, return `Verdict(False, ...)` whose `why` names the carrier, e.g. `f"{fighter.name} would keep {x:.0%} but {other.name} would carry the fight ({y:.0%}, margin {m:.0%})"`. When all fail: `Verdict(True, f"no party member keeps {m:.0%} vs the worst wild fight here (best {name} {best:.0%}, nurse N frames)")`. Fainted members (hp 0) are never candidates. "everyone has fainted" stays.
- No wild table for the map (`foes` empty or no moves table): keep today's fallback, each living member's own HP fraction stands in for its duel result, compared against the new margin.
- Existing switching brings the carrier in; do NOT add switching. Confirm only that these exist and say so in your report (use the Grep tool): `trainee_out` and `active_pos` in `src/pokeagent/explorer/behaviours/switch_out.py` (lines 32, 44), `team_plan.of(ctx)["breakers"]` in `src/pokeagent/knowledge/team_plan.py`, `fighter_slot` in `src/pokeagent/explorer/behaviours/cave_topup.py:28`.

### 2. Grind continuation gates (pasted; line numbers on main acf275e)

- `src/pokeagent/explorer/train_route.py:15` `MIN_HP_FRACTION = 0.5`, used at line 58 in `step(maps, pos, blocked, hp, mx, target=ROUTE24, patch=None)`: `if not mx or hp / mx < MIN_HP_FRACTION: return None`.
- `src/pokeagent/explorer/grind_episode.py:232`: `if (mx and hp / mx < train_route.MIN_HP_FRACTION or read_party_view(ctx.emu).any_fainted) and not heal_items.heal_count(bag_contents(ctx.emu)): return "hurt with no potion"` (hp, mx from `party_hp(ctx.emu)`).
- `src/pokeagent/explorer/planner.py:142`: `if (0 < level < goals.get("_train_level", 8) and mx and hp / mx >= 0.5 and goals.get("to_route2") and pos[0] in GRIND_IN_PLACE): return None` (hp, mx from `goals.get("_hp", (0, 0))`).
- `src/pokeagent/explorer/planner_east.py:114`: `if stage in TRAIN_OUTSIDE_STAGES and pos[0] not in CAVE and 0 < level < need and mx and hp / mx >= 0.5:` (same `goals["_hp"]`).
- Callers feeding train_route.step: `behaviours/plan_goal.py:131,153,155,157` (`*heal_gate_hp(ctx.emu)` into `_grind_step`, defined ~line 231, which calls `train_route.step(..., hp, mx, **kw)` at ~240), and `behaviours/grind_drill.py:68-70` (`heal_gate_hp` then `train_route.step`). `plan_goal.py:124` builds the `_hp` goals entry (`"_hp": heal_gate_hp(ctx.emu)`).
- `perceive.py:30-40`: `party_needs_heal(emu, below)` = `read_party_view(emu).any_fainted or (mx > 0 and hp / mx < below)`; `heal_gate_hp(emu)` = `(0, mx) if any_fainted else (hp, mx)`. Do NOT change `party_needs_heal`; its any-fainted rule stays. Its users (`frontier.py:119,140`, `menu.py:68`, `restock.py:31`) are heal/menu decisions, not grind gates: leave them.
- Use the Grep tool (never `git grep`) for `hp / mx`, `MIN_HP_FRACTION`, `heal_gate_hp`, `"_hp"` across `src/` and list in your report any OTHER grind_episode / grind_drill / plan_goal HP gate you find, with file:line. Wire it only if it decides whether to keep grinding or train; otherwise leave it and say why.

Add ONE small pure helper:

```python
def survives_next_wild(party: list[Combatant], wild: dict, kb=None, fighter_idx: int = 0, margin: float = SURVIVE_NEAR) -> bool:
    """True when some living member keeps >= margin after the worst wild duel (the same test as assess; no wild table -> own HP fraction)."""

def party_survives(emu, map_id: int, kb=None) -> bool:
    """Emu adapter: party_now(emu), encounters.species_on(map_id), cave_topup.fighter_slot(emu). Any fainted member -> False (routes to heal exactly as now)."""
```

`assess` and the helper must share one private function so they cannot drift. Wiring:
- `train_route.step`: add keyword `survives: bool | None = None`; when not None it replaces the `hp / mx < MIN_HP_FRACTION` test (`mx == 0` still returns None); when None keep the old fraction test (legacy callers and tests). `_grind_step` and `grind_drill._episode_step` pass `survives=party_survives(ctx.emu, ctx.view.m)`.
- `grind_episode.py:232`: replace the `hp / mx < MIN_HP_FRACTION` term with `not party_survives(ctx.emu, ctx.view.m)`; keep the any_fainted term and the no-potion condition.
- `planner.py:142` and `planner_east.py:114`: planner is pure over `goals`; have `plan_goal.py:124` add `"_survives": party_survives(ctx.emu, ctx.view.m)` next to `_hp`, and the two gates read `goals["_survives"]` when the key is present, else fall back to `hp / mx >= 0.5` (legacy tests and callers that do not set it).

## What NOT to do

- Do not change trainer or gym fight readiness, `heal_walk.RETREAT_DONE` (0.95), `retreat_heal` `LEAD_GATE` / `PARTY_GATE` pre-filter, `interaction_policy` `HEAL_BELOW`, `cave_escape`, catch policy, or `ship_gate`.
- Do not touch `party_needs_heal` or `heal_gate_hp`.
- Do not add any new switching behaviour. Do not touch `src/pokeagent/knowledge/readiness.py`.
- Do not change `Verdict`, the `assess` signature, or MAX_WALK_FRAMES.
- Do not edit tests that do not assert the old floor values themselves.
- No ROM work, no tuning beyond the three stated values, no refactors outside the files named.

## Verification

Python is `uv run` (3.12.12, confirmed with `uv run python --version`). Baseline on main before any change, run from the worktree:

```
uv run pytest -q -p no:cacheprovider tests/test_retreat_heal.py tests/test_train_route.py tests/test_grind.py tests/test_grind_episode.py tests/test_grind_pressure_plan_goal.py tests/test_area_grind.py tests/test_early_training_gate.py tests/test_east_followups.py tests/test_cave_training.py tests/test_party_view.py
...
119 passed, 1 warning in 1.43s
```

After your change the same command must pass (more tests, 0 failed). Then run the whole suite once: `uv run pytest -q -p no:cacheprovider tests` (tests/rom skips; there is no ROM), and report any failure outside the files above with its cause.

Tests to update ONLY where the floor value itself is under test (in `tests/test_retreat_heal.py`): `test_floor_rises_as_the_nurse_gets_closer` (FLOOR_NEAR/FLOOR_FAR -> SURVIVE_NEAR/SURVIVE_FAR), `test_hurt_lead_retreats_near_but_the_same_state_pushes_on_far` (its band `FLOOR_FAR < left < FLOOR_NEAR` must be rebuilt for the new margins: pick a lead HP so `left` lands between 0.05 and 0.15, or retarget the test), and `test_low_party_total_always_retreats_when_a_nurse_is_known` only if 0.2/0.2 no longer sits under PARTY_FLOOR 0.20 (use 0.1). Name each one you changed in the report. Fixtures: `from test_after_victory import SYN, _mon`; `WILD = {"PEBBLEMON": (10, 14, 1.0)}`; `_mon(name, level, frac)`.

New tests (survival tests in `tests/test_retreat_heal.py`, gate-wiring tests beside the existing train_route / grind_episode / planner tests):
1. A fighter that keeps ~26% vs WILD does not retreat (near nurse, 300 frames).
2. A fighter that keeps 0% after the duel, with a healthy bench member, does not retreat, and `why` names the bench member.
3. An all-weak party (every member keeps under the margin) retreats.
4. No wild table (`{}`): falls back to HP fractions compared with the new margin (a 10% fighter near retreats; a 20% fighter does not).
5. Each gate consults the helper: `train_route.step(..., survives=True)` proceeds with low `hp`; `survives=False` returns None at full `hp`; the `grind_episode` stop reason uses `party_survives` (monkeypatch it); `planner` and `planner_east` honor `goals["_survives"]` True/False regardless of `_hp`, and fall back to the 0.5 fraction when absent.
6. A fainted member: `party_survives` is False and the gate still routes to heal.

## Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and ends the run. Install, download, fetch nothing. Read nothing outside the working directory (the worktree).
- Use your Grep tool, not `git grep`. Do not search, glob, or hunt for the ROM, memory tools, runs/, or anything absent; if something expected is missing, stop and write that in the Status row.
- Test command is `uv run pytest -q -p no:cacheprovider <files>`; never bare `python` or `python -m pytest`.
- Work on the `directive/survival-floor` branch. Never commit to main/master, never push, never deploy; only Robert or Claude merge.
- Create no scratch or debug files (deletes are denied in the sandbox). If one is needed, put it under `.devin-scratch/` and leave it.
- New modules stay small (SOLID/SRP/KISS): retreat_risk.py must stay under 250 lines or the helper goes to `survival.py`.
- If a tool call is genuinely blocked, stop and write why in the Status row.
- Status row: Done only when every completion criterion below is met; otherwise Blocked with the reason.

## Completion criteria

- `assess` uses the survival rule with SURVIVE_NEAR 0.15 / SURVIVE_FAR 0.05 / PARTY_FLOOR 0.20; FLOOR_NEAR/FLOOR_FAR no longer exist.
- The helper exists, `assess` shares its core, and all four gates (train_route, grind_episode, planner, planner_east) plus every other grind gate you found go through it.
- The "do not change" list is untouched (`git diff --stat` shows none of those files).
- The named test command and the full suite pass; new tests 1-6 exist.
- Everything committed on the branch.

## Report

Findings first: the exact gate list with file:line after your change (and any extra gates found or deliberately left, with reasons); the tests you modified by name and why; confirmation the switch_out / team_plan / trainee_out / fighter_slot pieces exist (file:line); the baseline and final pytest tails (real output); the final commit sha. Note anything about the margins you could not check without a ROM.
