# PokeAgent: team readiness - judge the whole party, make "train Magikarp until it is Gyarados" a curriculum segment

**Read first (all in the worktree; if one is missing, stop and write that in the Status row):**
`docs/KNOWLEDGE.md` section "Magikarp: buy, reorder, switch-train (ROM-verified headless 2026-11-05)",
`src/pokeagent/magikarp.py`, `src/pokeagent/explorer/behaviours/switch_out.py`, `src/pokeagent/explorer/grind.py`,
`src/pokeagent/knowledge/readiness.py`, `src/pokeagent/knowledge/party.py`, `src/pokeagent/explorer/training.py`,
`src/pokeagent/explorer/behaviours/plan_goal.py`, `src/pokeagent/explorer/perceive.py` (`lead_level`), `src/pokeagent/goals.py`,
`src/pokeagent/campaign.py`, `src/pokeagent/data/campaign.json`, `tests/test_magikarp.py`, `tests/test_goal_order.py`,
`tests/test_readiness_all_bosses.py`, `tests/test_knowledge.py` (the synthetic cartridge `SYN`). **Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-07): "Should we explore a run that focuses on leveling Magikarp until it's useful? We may need to explore Team Improvement earlier
in the run to keep a stocked team, as an optimal team can get further than one outpowered main."

Evidence (live `runs/checkpoints/ss_anne_captain.state.fp.json`, rows are `[species, level, hp, max_hp]`; the other ship-stage fingerprints of 2026-11-07 show the same L12-13 / L29-30 spread):

```json
{"badges": 2, "bag_slots": 11, "frames": 14069, "heal_items": 0, "map": 101, "money": 14858, "party": [[133, 13, 29, 29], [179, 30, 82, 82]], "respawn": 5, "source_run": "explore-20261107-125805-24428", "v": 1, "x": 0, "y": 7}
```

Species 133 = MAGIKARP at L13, 179 = WARTORTLE at L30: the second member is 17 levels behind and does nothing in a fight (SPLASH, then TACKLE from L15).
The lead alone carried the S.S. Anne and lost the rival and sailor fights once it was hurt (spec `docs/superpowers/specs/2026-11-07-save-state-ledger.md`,
"Rival / captain note": every loss started with the lead at 6/79 HP and no potions). Gen 1 evolves Magikarp into Gyarados at L20; Gyarados is internal
species id 22 (ROM-verified, `kb/rom_tables.json` `name_of_internal`: `"22": "GYARADOS"`, `"133": "MAGIKARP"`; `src/pokeagent/magikarp.py` has `MAGIKARP, GYARADOS = 133, 22`).

What exists today (verified by reading the code, 2026-11-07):
- `readiness.assess` is lead-centric: it asks "what lead level wins the boss fight", with the rest of the party as switch-ins at their CURRENT levels.
  `plan_goal.py` even strips the Magikarp before judging (`party = [c for c in party if c.name != "MAGIKARP"]`, "the trainee never fights a boss").
- `buy_magikarp` is a ladder goal (before `to_mt_moon`), `reorder_party` and `switch_out_lead` (turn-one swap, `switch_out.py`) are merged and ROM-verified.
- `gyarados` exists only as a SIDE goal: `goals.SIDE_GOALS = ["gyarados"]`, detector `magikarp.gyarados_goal` (sticky "GYARADOS in the party"), reported but never planned.
  Nothing makes the agent actually raise the Magikarp: it reaches only L12-13 by incidental sharing.

## Repo facts (verified 2026-11-07 on the live checkout; they are pasted because you cannot look outside the worktree)

- `uv run python --version` prints `Python 3.12.12`. Always `uv run`; never bare `python`.
- Full suite: `uv run pytest -q` (about 80-120 s; 1419 passed, 18 skipped on a clean tree per the controller). Per item:
  `uv run pytest -q tests/<file>`.
- `roms/`, `baselines/` and `runs/` are gitignored. **Your worktree has NO ROM, no `.state` baselines and no `runs/` data.**
  Every test uses `FakeEmulator` (`from pokeagent.emulator import FakeEmulator`, defined in `src/pokeagent/emulator.py`):
  `FakeEmulator({addr: byte, ...})` with `.memory` (dict), `.read(addr)`, `.read_range(start, n)`, `.set(addr, v)`,
  `.frames`, and `save_state(path)` / `load_state(path)` which write/read the memory dict as JSON. Use `tmp_path` for files.
- The existing test helper to copy from is `tests/test_state_fingerprint.py::world()`, which builds a FakeEmulator on map 0x61:

```python
LEAD = 0xD16B
def world(respawn=5, hp=79, mx=79, level=29, potions=2):
    emu = FakeEmulator({0xD35E: 0x61, 0xD362: 13, 0xD361: 6, 0xD719: respawn, 0xD356: 0b11,
                        0xD347: 0x00, 0xD348: 0x12, 0xD349: 0x34, 0xD057: 0, 0xD163: 1, 0xD164: 179})
    for off, v in ((0, 179), (1, hp >> 8), (2, hp & 255), (33, level), (34, mx >> 8), (35, mx & 255)):
        emu.memory[LEAD + off] = v
    emu.memory.update({0xD31D: 1, 0xD31E: 0x14, 0xD31F: potions, 0xD320: 0xFF})
    return emu
```

  That file also shows how tests import the `tools/` scripts: `sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))`
  then `import seg_store as ss`.
- **Files you must NOT modify** (another agent is working on the walk-off there): `src/pokeagent/explorer/ship_gate.py`,
  `planner.py`, `planner_east.py`, `planner_checkpoint.py`. Read them if you must; do not edit them.

## 2. What this folds from the two old drafts (and what is superseded)

- `docs/directives/Magikarp_Switch_Training_Directive.md` (draft, never queued): its scope items 1-3 and 5 (buy goal, `reorder_party`, turn-one switch, log lines) are
  ALREADY IMPLEMENTED and merged (`buy_magikarp`, `behaviours/party_order.py`, `switch_out.py`, `tests/test_magikarp.py`). Its item 4 (`gyarados` is a side goal that must never
  block the route) is SUPERSEDED by this directive: `gyarados` becomes a ladder goal, with a settle rule so it still can never block (section 3.2).
- `docs/directives/Team_Builder_Directive.md` (draft, never queued): its team-plan, shopping, targeted catching, PC party management and metrics are DEFERRED, not in
  this PR (no catching of new species here). Folded in: only its "training allocation" idea (switch-train whoever is far below the others), as section 3.3.
  Everything else in it stays a draft for a later directive.

## 3. Scope (one PR, in order)

1. Team-centric readiness in `src/pokeagent/knowledge/readiness.py` (pure).
2. Campaign goal `gyarados` in the ladder (`campaign.json`, `campaign.py`, `goals.py`, `magikarp.py`, the settle rule).
3. The gate reads the team result (`perceive.lead_level` seam + `plan_goal.py`/`training.py`), and switch-training targets the member `team_readiness` names.
4. Tests: `tests/test_team_readiness.py`; update existing tests that assert `gyarados` is a side goal.

## 4. The work

### 4.1 `team_readiness` (pure, no emulator, no ROM)

In `knowledge/readiness.py` (it is 124 lines; if it would pass 300, put this in a new `knowledge/team_readiness.py` and re-export). Names and constants:

```python
TEAM_GAP = 6               # a useful second member is within this many levels of the lead
LEAD_HURT = 0.5            # the sim starts the lead at this fraction of its HP: the fight after the lead is hurt or faints
TEAM_MIN = 2               # members that must be useful before a boss (lead + one)
EVOLVE_LEVEL = 20          # import from pokeagent.magikarp, do not redefine

@dataclass(frozen=True)
class MemberNeed:
    slot: int; name: str; level: int; target: int; useful: bool

@dataclass(frozen=True)
class TeamReadiness:
    ready: bool
    lead: Readiness | None        # the existing lead verdict from assess()
    members: tuple[MemberNeed, ...]
    weakest: MemberNeed | None    # the useful-member shortfall to fix first (lowest level among those below target); None when ready
    text: str                     # the logged decision

def team_readiness(party: list[Combatant], boss: list[tuple[int, str]], label: str, kb: dict | None = None) -> TeamReadiness | None
```

Semantics (write them in the docstring):
- `party` is the whole party in slot order, Magikarp INCLUDED. `None` when `assess` would return `None` (missing data), like `assess`.
- A MAGIKARP member below `EVOLVE_LEVEL` is judged as the mon it will become: replace it by `trainer_mon("GYARADOS", max(level, EVOLVE_LEVEL), kb)` for the "after training"
  simulation, and its `target` is at least `EVOLVE_LEVEL`. (Magikarp is a switch-train trainee: it is not asked to fight the boss as a Magikarp.)
- Lead verdict: `lead = assess(party_without_trainee, boss, label, kb)` exactly as today (so the existing lead target is unchanged).
- Team verdict: simulate the boss fight with the lead hurt: `fight([replace(lead, hp=int(lead.hp * LEAD_HURT)), *others], theirs, chart, moves) >= MARGIN`, where `others` = the other members at
  their current level (Magikarp as its Gyarados projection only once its level >= `EVOLVE_LEVEL`; below that it contributes as itself).
- `target` per non-lead member = `max(lead.level - TEAM_GAP, sim_needed)` capped at `lead.level`, where `sim_needed` is the lowest level `L` (current+1 .. `MAX_LEVEL`) at which that member
  (`at_level`, or the Gyarados projection for a Magikarp) makes the hurt-lead simulation pass with the other members unchanged; if no level passes, `sim_needed = lead.level`. `useful` = `level >= target`.
- `ready` = lead verdict ready AND the hurt-lead simulation passes AND at least `TEAM_MIN` members are `useful` (a one-mon party is `TEAM_MIN`-short; a party with no second member is not ready, `weakest` = None, text says "no second member").
- `weakest` = the not-useful non-lead member with the lowest level (ties: lowest slot). `text`: `team ready vs BOSS: lead L29, 2/2 useful` or `team not ready vs BOSS: MAGIKARP L13 -> L23 (lead L30)`.
- It never raises on an empty party or an empty boss (returns `None`).

### 4.2 The `gyarados` ladder goal

Place: **right after `nugget_bridge` and before `to_bill`** in `src/pokeagent/data/campaign.json` (`to_bill`'s `after` becomes `gyarados`; `gyarados`'s `after` is `nugget_bridge`;
detector `{"special": "gyarados"}`, `"special": true`, note "hand-coded in goals.py", `needs: []`). Why there (reasoning from `campaign.json` and `docs/KNOWLEDGE.md`, not measured; say in the Status
row if you find a better spot):
- Before it the agent has the Boulder and Cascade badges, is in Cerulean (Pokemon Center `heal_cerulean` is a goal, so the heal loop is a few steps away), and has just entered Route 24 (map 35, the
  Nugget Bridge: trainers plus grass, with Route 25 north of it). That is the first area past Cerulean with both repeatable wild grass and a trainer line, and it comes BEFORE the ship stage
  (`to_vermilion`..`rival_ss_anne`), which is where the team gap lost the fights.
- Earlier (Route 3/4, Mt Moon) wild levels are too low to be worth the shared XP for a Magikarp that is already L12-13; later (after `to_bill`) the agent has left the Cerulean area.
- Estimate to sanity-check (not a measurement): Magikarp is a slow-growth mon, L13 -> L20 is about 7,000 experience points; a switched-out Magikarp earns half of each fight's experience, so on Route 24
  grass it is on the order of 100-250 shared fights. `src/pokeagent/grind/xpmath.py` has the repo's experience maths if you need to cite a number.

`goals.py`: remove `g["gyarados"] = gyarados_goal(emu, st)` (the side line), add `"gyarados": gyarados_goal_settled(emu, st, seen)` to the hand-coded dict next to `"buy_magikarp"`, and set
`SIDE_GOALS = []` (keep the name exported; consumers `adapters/explorer_snapshot.py`, `explorer/trainee.py`, `intervene/digest.py`, `tools/status.py` iterate it and must still work with an empty list).
`magikarp.py`: add

```python
GYARADOS_STEP_CAP = 6000      # steps on the stage without evolving before the goal is settled for this run (named; tune from runs)

def gyarados_goal_settled(emu, st: dict, seen: set) -> bool:
    """Ladder goal: a GYARADOS in the party (sticky), OR no Magikarp was ever owned, OR the stage ran out of steps (st["gyarados_skipped"])."""
```

It must NEVER block: it is true when `had_gyarados`, or when no Magikarp has ever been in the party (`not st.get("had_magikarp") and MAGIKARP not in party_species(emu)` — `magikarp_goal_settled`
already sets `had_magikarp`), or when `st.get("gyarados_skipped")`. `plan_goal.py` counts steps while the goal is the next unmet goal and a Magikarp is in the party
(mirror the `buy_steps` / `buy_skipped` block at the top of `PlanGoal.step`; new context fields `gyarados_steps: int`, `gyarados_skipped: bool` in `context.py`) and sets
`ctx.gyarados_skipped = True` with a log line once `GYARADOS_STEP_CAP` is exceeded. The grind-budget lift in `grind.py` (`GRIND_BLACKOUTS` = 2 blackouts in a row lifts the training gate) is
UNCHANGED; when it lifts the gate for the stage, the stage must still terminate through the step cap.
`campaign.py`: no new detector kind is needed because `special` goals are skipped by `campaign_goals`; the first-25 / goal-count assertions in tests change accordingly.
Check `campaign.selectable("gyarados")` is True so `tools/seg_store.layout` makes it a segment automatically (`nugget_bridge -> gyarados`) and `gyarados.state` becomes a checkpoint; do not edit
`tools/segments.py` or the seg_* tools.

### 4.3 The gate reads the team; switch-training follows `team_readiness`

The ONE seam every training-gate reader goes through is `explorer/perceive.py::lead_level(emu)` (read by `plan_goal`, `frontier.py`, `par_follow.py`, `party_log._count_steps`, the bandit points, `grind/drill.py`
and compared with `ctx.train_need`). Change it so that while a Magikarp trainee is in the party, the level the gate sees is
`min(fighter level, trainee level + TEAM_GAP)` (today it returns just the fighter's level). Effect: the gate stays open (grass-seeking continues) until the Magikarp is within `TEAM_GAP` of the level
the stage needs, instead of only the lead. Once it has evolved (no MAGIKARP in the party) the function behaves exactly as before. Import `TEAM_GAP` from `knowledge.readiness`; keep the function pure.

`explorer/behaviours/plan_goal.py` (NOT a forbidden file; this is the consumer where the new result is read): keep the Magikarp-stripped `readiness_for` for the lead target as is, and add next to it
a call to a new `training.team_for(goals, party_all)` (a thin wrapper over `team_readiness` with the same boss lookup, cache and `BOSS_LABEL` as `readiness_for`; returns `None` without data) using
`our_party(ctx.emu)` WITHOUT the strip. Log the verdict text once per change (like `ctx.readiness_note`) and store `ctx.train_member = weakest.slot` (new context field, `None` when ready).
Before `to_vermilion` / `to_ss_anne` (i.e. when `stage_goal(goals)` is `rival_ss_anne` or any later boss) a team that is not ready keeps the gate open through the `lead_level` seam above; do NOT touch
`ship_gate.py`, `planner.py`, `planner_east.py`, `planner_checkpoint.py` (the walk-off lives there; it keeps reading `under_level`, now fed by the same gate level).

Switch-training: `magikarp.trainee_slot(emu)` stays (Magikarp first). Add `trainee_slot_for(emu, named: int | None)` that returns the Magikarp slot if a Magikarp is in the party, else `named`
(the slot `ctx.train_member` names) when it is not the lead and its level is at least `TEAM_GAP` below the lead's; `switch_out.py` applies to the active mon at that slot (use
`read_battle_mon(...).party_pos` to match the slot; today it matches `species == MAGIKARP`) and `magikarp.switch_candidate` excludes the trainee slot instead of every MAGIKARP. Behaviour for a
party that has a Magikarp is unchanged. All existing `tests/test_magikarp.py` cases must pass unedited.

## 5. What NOT to do

- Do not edit `src/pokeagent/explorer/ship_gate.py`, `planner.py`, `planner_east.py`, `planner_checkpoint.py` (another agent is working on the walk-off there).
- No new RL/bandit code; `GRIND_BLACKOUTS`, `GrindBudget`, `battle_outcome`, `record_battle_result` stay as they are. No catching, shopping, PC or party-composition code (the Team Builder plan is deferred).
- Do not change `MARGIN`, `CAP_ABOVE_TABLE`, `TRAIN_LEVEL_BY_GOAL`, or the flee/potion thresholds. Do not change `tools/seg_*`, `tools/segments.py`.
- Do not run any emulator, `uv run pokeagent ...`, or the explorer; there is no ROM or `kb/` in the worktree (`kb/rom_tables.json` is gitignored): every test builds its own synthetic cartridge.
- No new dependencies; each module under 300 lines.

## 6. Verification

- `uv run pytest -q tests/test_team_readiness.py` - new tests. Build a synthetic cartridge by copying `tests/test_knowledge.py::SYN` into the new test file's own dict (do NOT edit `test_knowledge.py`) and
  adding two species rows (`MAGIKARP`, type WATER, tiny stats, move TACKLE; `GYARADOS`, WATER/FLYING or WATER, decent stats, move TACKLE plus a damaging WATER move learned at 20) via the same
  `_species`/`_mv` helper shapes; the `Combatant`s are built like `_starter` in that file:
  1. Weak second member (lead L30 AQUA, second a MAGIKARP L13) vs a synthetic two-mon boss: `ready is False`, `weakest.name == "MAGIKARP"`, its `target >= 20` and `>= 30 - TEAM_GAP`, `useful False`.
  2. Strong second member (both L28-30, same boss): `ready is True`, `weakest is None`, every member `useful`.
  3. Single-mon party: not ready, text mentions "no second member"; empty party or boss returns `None`.
  4. The hurt-lead simulation matters: a party whose lead alone passes the existing `assess` but fails with `LEAD_HURT` and a useless second member gives `lead.ready True` and `ready False`.
  5. A MAGIKARP at L20+ is judged as the GYARADOS projection (its row in `members` is `useful` when the sim passes).
  6. `gyarados` detector: `check_goals` on a `FakeEmulator` party (`tests/test_magikarp.py::party_mem` helper) with species 22 -> `g["gyarados"]` True and sticky; with no Magikarp ever owned -> True (settled);
     with a Magikarp and `st["gyarados_skipped"]` -> True; with a Magikarp only -> False. `GOALS.index("gyarados") == GOALS.index("nugget_bridge") + 1` and `to_bill` follows it; `"gyarados" not in SIDE_GOALS`.
  7. `lead_level` seam: a Magikarp L13 + Wartortle L30 party reads `min(30, 13 + TEAM_GAP) = 19`; after the species becomes 22 it reads slot 0's level as before; no Magikarp: unchanged.
  8. Training target selection: `trainee_slot_for` returns the Magikarp slot when one is present; with no Magikarp and `named=1` returns 1 only when slot 1 is >= `TEAM_GAP` below the lead, else `None`.
- Update, do not delete, the existing assertions that `gyarados` is a side goal (`tests/test_goal_order.py` lines ~49-54, `tests/test_magikarp.py::test_buy_magikarp_sits_before_mt_moon_and_gyarados_is_a_side_goal`,
  `tests/test_campaign.py::test_snapshot_goals_come_in_ladder_order`, the `EXPECTED` ladder list if it covers it, and any other test the full run shows) so they assert the new placement.
- `uv run pytest -q` green; paste the before/after tails.
- **Controller validation (not Devin; the ROM is on the laptop):** a headless segment `nugget_bridge -> gyarados` from `runs/checkpoints/nugget_bridge.state`, then `ship_gate` behaviour with the new gate level.

## 7. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation is rejected and ends the run. No installs, downloads or fetches.
  Never read outside the worktree.
- **Do not run the `pokeagent` entry point (the sandbox refuses it). Do not list the directory tree recursively; use `git ls-files`.
  Do not read outside the worktree. Create no scratch files; deleting is denied. If something expected is missing, stop and write that in the Status row.**
- Do not search, glob or hunt for a missing file or fact: stop and say so in the Status row.
- Test commands are exactly `uv run pytest -q` and `uv run pytest -q tests/<file>`. Never bare `python`.
- Work only on branch `directive/pokeagent-team-readiness-directive`. Never commit to `main`; never push; never deploy. Commit on the branch as you go.
- Create no scratch or debug files (deleting is denied and ends the run). If one is truly needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row; do not try another way around it.
- SOLID/SRP/KISS is a hard rule here: small new modules (under 300 lines), no new dependencies.

## 8. Completion criteria

- [ ] `team_readiness` + `TeamReadiness` / `MemberNeed` with `TEAM_GAP`, `LEAD_HURT`, `TEAM_MIN`; pure, tested
- [ ] `gyarados` in `campaign.json` after `nugget_bridge`, hand-coded settled detector (never blocks), `SIDE_GOALS = []`, step cap in `plan_goal.py`
- [ ] `perceive.lead_level` team seam; `plan_goal` logs `team_for` and sets `ctx.train_member`; `trainee_slot_for` + `switch_out` use it; Magikarp behaviour unchanged
- [ ] `tests/test_team_readiness.py` (the eight cases) passes; updated side-goal assertions; `uv run pytest -q` green (paste the tail); `git diff --stat main` pasted; no forbidden file changed
- [ ] Status row moved to Review with the branch name

## 9. Report

Findings first: test tails (before/after), `git diff --stat`, the final signatures, why `gyarados` sits where it does (or where you moved it and why), every existing test you had to update, the one call site
where the gate reads the team (`perceive.lead_level` + `plan_goal.py`), and anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Done |
| Assigned to | devin |
| Branch | directive/pokeagent-team-readiness-directive |
| Base branch | - |
| Base commit | 34ccc1b92eb31f1679df2cc61c49461ef2b8d770 |
| Head commit | b78b7c93132bf333e453f2e46895df372a671fa7 |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-07 13:01 · robert-claude-laptop · none → Draft — Claude 2026-11-07: team-centric readiness + gyarados ladder goal
- 2026-11-07 13:02 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; lint_override candidate: dispatch-path-missing on gitignored runs/ and kb/ evidence paths only
- 2026-11-07 13:20 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing on gitignored evidence paths (runs/checkpoints/ss_anne_captain.state.fp.json, kb/rom_tables.json); known false positive
- 2026-11-07 13:20 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-team-readiness-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6VKV8R3J302ZFK0E1M04JXV
- 2026-11-07 13:28 · dispatcher · launched pid=3612; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-team-readiness-directive; provisioned: uv sync --frozen
- 2026-11-07 13:56 · devin · In progress → Review — [origin] spent: devin 27 min est. n/a
- 2026-11-07 14:20 · robert-claude-laptop · Review → Done — note: PR #142 merged 362187d (merge commit); Sonnet review CHANGES-NEEDED -> fixes 2dbc360/449496d (team need 26 at gyarados stage, GRIND_BATTLES_GYARADOS 120 keyed on gyarados, idle settle 300, true_lead_level for bandit/drill) -> Haiku APPROVE; verify at 449496d 1452 passed 36 skipped
<!-- queue:end -->
