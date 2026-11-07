# PokeAgent: status care and EXP eligibility - cure poison before it faints a mon, buy the Antidote, and never train with a fainted trainee

**Read first (all in the worktree; if one is missing, stop and write that in the Status row):** `src/pokeagent/ramstructs.py` (`PartyMon.status` = party struct byte +4, `BattleMon.status`, `read_party`), `src/pokeagent/explorer/economy/prices.py` (`ANTIDOTE = 0x0B`, `PARLYZ_HEAL = 0x0F`, `FALLBACK_PRICE`, `HEAL_HP`, `price`, `stocked`), `economy/heal_items.py` (`HEAL_ITEMS`, `heal_count`, `bag_hp`, `pick_for_missing`), `economy/shopping.py` (`shopping_list`, `BALL_MIN`, the `add()` budget rule, `ball_need`), `economy/floor.py` (`potion_floor`, `FLOOR_MIN`), `economy/budget.py` (`reserve`, `spendable`), `economy/outside_use.py` (`walk_to_center`, `potion_beats_walk`, `field_wants`, `YEN_PER_FRAME`), `explorer/behaviours/use_items.py` and `behaviours/item_use.py` (`item_step`, `party_prompt_open`: how an item is used on a party slot), `explorer/behaviours/heal.py` and `ctx.center_intent`, `explorer/behaviours/switch_out.py` (the switch-trainee machinery: `trainee_out`), `src/pokeagent/magikarp.py` (`trainee_slot`, `trainee_slot_for`, `switch_candidate`, `SWITCH_MIN_HP`), `explorer/grind.py`, `explorer/behaviours/grind_drill.py`, `explorer/behaviours/plan_goal.py` (`team_for`, `ctx.train_member`, the gyarados/`team_ready` stage), `explorer/party_log.py`, `src/pokeagent/knowledge/encounters.py` (`species_on`, `where_to_catch`), `src/pokeagent/training_progress.py`, `docs/KNOWLEDGE.md`. **Do not list the tree recursively**; use `git ls-files`.
**Forbidden to edit:** `explorer/planner*.py`, `ship_gate.py`, `planner_checkpoint.py` (the Pokecenter heal path: read only), and any battle MOVE choice (`battle_moves.py` move scoring, flee/potion thresholds).

## 1. Why this exists

Robert (2026-11-07): "How do we teach the agent to use an antidote on a poisoned pokemon to avoid blacking out, as well as step counting to total HP and HP Tracking on a poison pokemon in possession?" and "The agent also needs to recognize that if a Pokemon is defeated, or blacked out, while the main does combat, it does not gain exp, so it needs to be healed to be eligible to receive exp."

What the code does today (read 2026-11-07): the heal item set is only Potion and Super Potion (`heal_items.HEAL_ITEMS`); `ANTIDOTE = 0x0B` exists in `prices.py` with a 100-yen fallback but nothing buys, carries or uses it. Status is decoded (`PartyMon.status`) but no behaviour reads it outside battle. Poison ticks while walking, so a poisoned party member can faint on the way to the nurse; one fainted member can no longer fight or gain EXP, and an all-poisoned party can black out (a blackout halves the money: `budget.blackout_cost`).
Switch training (Magikarp, or any `ctx.train_member` from `team_for`) only pays if the trainee is alive when the wild Pokemon faints. A fainted trainee earns nothing, yet the stage keeps counting grind steps and battles.

## 2. Facts (pasted; you cannot read `kb/` or `runs/` in the worktree)

- `uv run python --version` prints `Python 3.12.12`. Always `uv run`; never bare `python`. Full suite: `uv run pytest -q` (about 100-210 s; 1557 passed, 1 skipped on the live checkout today, plus one environment-dependent failure `tests/test_resources.py::test_lock_takeover_is_exclusive`, unrelated: ignore it and say so if it fails for you). `roms/`, `baselines/`, `runs/`, `kb/rom_tables.json` are gitignored: no ROM or `kb/` in your worktree; tests use `FakeEmulator`, `tmp_path` and fixture tables.
- **Item ids and prices (read from `kb/rom_tables.json` `items`, verified today):** 0x0B ANTIDOTE 100 yen, 0x0C BURN HEAL 250, 0x0D ICE HEAL 250, 0x0E AWAKENING 200, 0x0F PARLYZ HEAL 200, 0x10 FULL RESTORE 3000, 0x14 POTION 300, 0x13 SUPER POTION 700, **0x34 FULL HEAL 600, 0x35 REVIVE 1500, 0x36 MAX REVIVE 4000.** (Decimal keys 52/53/54 in the JSON.) `prices.ANTIDOTE = 0x0B`, `PARLYZ_HEAL = 0x0F` already exist; add `FULL_HEAL = 0x34`, `REVIVE = 0x35` constants beside them, with `FALLBACK_PRICE` entries 600 and 1500. Whether the Vermilion, Viridian, Pewter, Cerulean Marts stock the Antidote: `prices.stocked(item_id, map_id)` answers from the catalog when present and returns True ("try") when unknown; do not assume.
- **Gen 1 status byte (`PartyMon.status`, +4 in the party struct) - FROM MEMORY OF pokered, UNVERIFIED in this repo (nothing in `ram_map.json` or `docs/KNOWLEDGE.md` confirms it):** sleep = low 3 bits (a counter 1..7), poison = bit 3 (0x08), burn = bit 4 (0x10), freeze = bit 5 (0x20), paralysis = bit 6 (0x40). Put the decode in ONE helper `status_kinds(byte) -> frozenset[str]` with a `# unverified` comment, so the controller can correct it in one place. (The Catch Methods directive uses the same decode in `catch_math.status_kind`: if that module has merged, import it instead of duplicating.)
- **Gen 1 overworld poison - FROM MEMORY, UNVERIFIED:** a poisoned Pokemon loses 1 HP every 4 steps walked (pokered `ApplyOutOfBattlePoisonDamage`, on the step counter) and CAN faint from it; if the whole party is fainted by poison it is a blackout. Burn and paralysis do not tick in the overworld. In battle poison/burn damage is 1/16 of max HP per turn (not used here). Constants `POISON_STEPS_PER_HP = 4` (steps are tiles walked, i.e. a `moved` press in `transitions.jsonl`, not every press; blocked presses do not count), `POISON_BATTLE_FRACTION = 1/16`. The exact phase of the 4-step counter is unknown, so the policy uses the worst case: `steps_to_faint(hp) = (hp - 1) * POISON_STEPS_PER_HP + 1`.
- **Gen 1 EXP rule - FROM MEMORY, UNVERIFIED (pokered `GainExperience`, `wPartyGainExpFlags`):** experience goes to each Pokemon that PARTICIPATED in the fight (was sent out at some point) and is still alive when the enemy faints; a participant that faints before the kill has its flag cleared and receives nothing; the total is split among the alive participants. So: a fainted member earns no EXP, and a member that fainted and was revived mid-fight does not recover the share. The directive's eligibility gate only relies on "alive at the end".
- Walk cost to a heal: `outside_use.walk_to_center(ctx) -> (frames, grass_tiles, center_map) | None`; steps = `frames / legs.grid.FRAME_WALK` (16 frames a tile). `outside_use.potion_beats_walk(...)` exists for the HP-low case.
- Poison-typed wild species on the maps of the early campaign (grass, from `kb/rom_tables.json` `wild_by_map` and `species_by_dex` types; chance = share of encounters; type-based PROXY, the species that can actually inflict poison also depends on their moves): Route 2 (0x0D) WEEDLE BUG/POISON 0.152; Route 4 (0x0F) EKANS POISON 0.25; Route 5/6 (0x10/0x11) ODDISH GRASS/POISON 0.348; Route 7 (0x12) ODDISH 0.297; Route 11 (0x16) EKANS 0.402; Route 22 (0x21) NIDORAN(M) 0.395, NIDORAN(F) 0.055; Route 24 (0x23) WEEDLE 0.199, KAKUNA 0.199, ODDISH 0.246; Route 25 (0x24) WEEDLE 0.199, KAKUNA 0.199, ODDISH 0.246; Viridian Forest (0x33) WEEDLE 0.449, KAKUNA 0.395; Mt Moon 1F/B1F/B2F (0x3B/0x3C/0x3D) ZUBAT POISON/FLYING 0.789 / 0.598 / 0.492. Route 1 and Route 3 have none. Poison-inflicting moves in the ROM move table (effect poison): POISON STING, TWINEEDLE, POISONPOWDER, TOXIC, SMOG, SLUDGE, POISON GAS (so `poisoners_on` below computes from learnsets + `knowledge.moves.effect_of`, not just type).
- Existing seams: `ctx.center_intent` (go heal), `ctx.log`, `goals.bag_contents(emu)`, `perceive.party_hp(emu) -> (hp, max_hp)`, `ramstructs.read_party(emu)`, `ctx.train_member`, `team_for`, `magikarp.trainee_slot_for(emu, named)`, `switch_out.trainee_out(ctx)`, `training_progress.training_progress(rows)` (progress needs an XP or level gain), `ctx.decision_log`.

## 3. Scope (one PR, in order)

1. `explorer/status_care.py` (pure): `status_kinds`, `steps_to_faint`, the care decision table, `poisoners_on`.
2. Item use: a `StatusCare` behaviour that carries the decision out with the existing item-use machinery (Antidote on the poisoned slot, a Potion, or `ctx.center_intent`).
3. Shopping: Antidote joins the heal-item source of truth with a floor of 1 when the route ahead has poison.
4. EXP eligibility: a gate before training; heal first; log "trainee fainted: no exp"; no-progress accounting.
5. Tests.

## 4. The work

Every threshold is a NAMED constant with a comment that it is an untuned first value. Each new module under 300 lines.

### 4.1 `explorer/status_care.py` (pure)

```python
POISON_STEPS_PER_HP = 4        # UNVERIFIED (from memory of pokered): 1 HP per 4 walked tiles
CARE_MARGIN_STEPS = 8          # extra steps of slack before the nearest known heal
ANTIDOTE_FLOOR = 1
@dataclass(frozen=True)
class MonStatus: slot: int; hp: int; max_hp: int; kinds: frozenset[str]
@dataclass(frozen=True)
class CareDecision: action: str; slot: int | None; item: int | None; why: str   # "none" | "antidote" | "potion" | "walk_to_center" | "nothing_available"
def status_kinds(byte: int) -> frozenset[str]            # UNVERIFIED decode (section 2): {"sleep","poison","burn","freeze","paralysis"}
def steps_to_faint(hp: int, per_hp: int = POISON_STEPS_PER_HP) -> int     # (hp - 1) * per_hp + 1; 0 for hp <= 0
def poisoners_on(map_id, wild_by_map, learnsets, moves, kb=None) -> list[str]   # species on the map that are poison-typed OR whose moves at the map's level range include a poison-effect move
def decide(party: list[MonStatus], bag: dict, steps_to_heal: float | None, kb=None) -> CareDecision
```
Decision table (first match wins; worst-case poisoned member is the one with the smallest `steps_to_faint`):
1. No poisoned member -> `none`.
2. `need = steps_to_heal + CARE_MARGIN_STEPS` where `steps_to_heal` is the walk to the nearest known heal (None = no heal known = infinite). If every poisoned member has `steps_to_faint(hp) > need` -> `none` (it will reach the nurse; log "poison ok: N steps to heal, X to faint").
3. Otherwise some member would faint first. If an ANTIDOTE (or FULL HEAL 0x34) is carried -> `antidote` for that slot (Antidote first, Full Heal only if no Antidote; the log says which and the item cost).
4. Else if a POTION/SUPER POTION is carried and `steps_to_faint(hp + potion_hp) > need` (the extra HP buys enough steps) -> `potion` for that slot.
5. Else if a heal is known (`steps_to_heal` finite) -> `walk_to_center` now (sets `ctx.center_intent` exactly as `Heal` expects; read `heal.py` first).
6. Else `nothing_available` (log it once; exploration continues, the other guards own it).
Urgency tag in `why`: `blackout risk` when every living member is poisoned, `member loss` otherwise. Burn / paralysis / sleep / freeze are NOT cured outside battle by this table in v1 (they do not tick in the overworld); the table has a row for each kind with `action none` and a comment explaining that, so a later change is one edit. Pure functions; no emulator.
`poisoners_on` uses `knowledge.encounters.species_on` ranges, `party.moves_at(name, level, kb)` for the max level on the map and `knowledge.moves.effect_of(move)`'s `.status == "poison"`.

### 4.2 Carrying it out (`explorer/behaviours/status_care.py`)

Registered after `Heal()` and `Restock()` and before `UseItems()` in `default_behaviours()` (read the order first; do not reorder anything else). `applies`: not battling, no text box, `ctx.proc is None`, `ctx.center_intent is None`, at least one party member has `poison` in `status_kinds(PartyMon.status)`, re-evaluated every `RECHECK_EVERY = 10` steps and immediately when a poison appears (the status changed). It builds `MonStatus` rows from `read_party`, `steps_to_heal` from `outside_use.walk_to_center(ctx)`, calls `decide`, logs ONE line per change (`[status_care] slot 1 poisoned HP 12/40: 45 steps to faint, 80 to the nurse -> Antidote]`) and then:
- `antidote` / `potion`: use the item on that party slot through the SAME machinery the field Potion uses (`item_step` / `UseItems` target selection; read `use_items.py` to see how the party slot is chosen). If the existing machinery cannot target a specific slot, do NOT write new menu code: fall back to `walk_to_center` (when a heal is known) and say so in the Status row. Rows written to `status_care.jsonl` carry `provenance` (see the standing rule in section 7), and every constant marked `# unverified` (status bits, poison rate, EXP rule) stays a hypothesis until an ORGANIC run or save confirms it: the controller validation uses an organic save, not a synthetic one. A used Antidote must verify its effect: the status byte no longer has `poison` within `VERIFY_STEPS = 20` presses; a failed use is logged and not retried more than `MAX_TRIES = 2`.
- `walk_to_center`: sets `ctx.center_intent` (the same field `Heal` honours). Nothing else.
- Never inside a battle (battle poison is handled by the existing battle behaviours, untouched) and never while a boss segment is in its fight step.

### 4.3 Shopping: Antidote joins the heal-item source of truth

- `prices.py`: add `FULL_HEAL`, `REVIVE` constants and fallback prices (section 2). `heal_items.py`: add `CURE_ITEMS = (ANTIDOTE, FULL_HEAL)` and `cure_count(bag)` beside `heal_count` (do NOT put the Antidote into `HEAL_ITEMS`/`HEAL_HP`: it restores no HP and `bag_hp`/`potion_floor` maths must stay as they are).
- `shopping.shopping_list(...)`: after the potion step and before the Escape Rope, add `ANTIDOTE_FLOOR` Antidotes when `cure_count(bag) < ANTIDOTE_FLOOR` and `poison_ahead` is true; same budget rule as every other item (`budget.spendable`, `add()`), and only at a Mart whose `stocked(ANTIDOTE, mart)` holds (the `stock` callable already passed in). `poison_ahead(goals, here_map, wild_by_map, kb)` (pure, in `status_care.py`): true when any map in {the current map, the training map of the stage (`encounters.TRAIN_MAP`), the maps of the next `POISON_LOOKAHEAD = 3` unmet goals that carry a `{"map": [...]}` detector in `campaign.json`} has a non-empty `poisoners_on`. New keyword `poison_ahead: bool | None = None` (None = compute, like `needs_balls`/`cave`), so existing callers and tests keep working unedited.
- `MIN_TRIP_YEN` still applies (a 100-yen Antidote alone never justifies a trip); the Antidote rides along with a trip the potion floor already makes. Document that.

### 4.4 EXP eligibility: never train with a fainted trainee

```python
@dataclass(frozen=True) class Eligibility: ok: bool; why: str; fix: str    # fix: "" | "center" | "revive" | "antidote"
def trainee_eligible(party: list[MonStatus], slot: int | None, revive_carried: bool, steps_to_heal) -> Eligibility
```
- Eligible when the slot exists, `hp > 0`, and (if poisoned) `steps_to_faint(hp) > TRAINEE_MIN_SAFE_STEPS = 30` (it must survive the grass walk). Not eligible: `hp == 0` -> fix `revive` if a Revive is carried and a heal is not close (`steps_to_heal` None or above `REVIVE_BEATS_WALK_STEPS = 150`), else `center`; poisoned and short -> `antidote` (if carried) else `center`.
- Where it applies (read these call sites): `PlanGoal.step` computes `ctx.train_member` / the gyarados (`team_ready` after Team_Builder_V2) stage; `SwitchOut` (trainee out), `GrindDrill` and the drill/legs runs train a member. Add ONE helper `explorer/trainee_gate.py::trainee_ok(ctx) -> Eligibility` that reads the party and the trainee slot (`magikarp.trainee_slot_for(ctx.emu, ctx.train_member)`), and call it: (a) in `PlanGoal` before it keeps the training gate open (if the trainee is not eligible the gate for the trainee stage is held CLOSED for the heal, i.e. `need` unchanged but `ctx.center_intent` set to heal first; do not edit the planners); (b) in `GrindDrill.applies` (a drill must not start with a fainted trainee).
- A fainted trainee triggers heal FIRST: `fix == "center"` -> `ctx.center_intent` (the existing Pokecenter walk); `fix == "revive"` -> use the Revive on that slot through the existing item machinery when it can target a slot (same fallback rule as 4.2).
- **Logging and accounting:** when the gate finds the trainee fainted (and at most once per `FAINT_LOG_EVERY = 100` steps), log `[trainee fainted: no exp (slot 1 MAGIKARP L14) - healing first]` and append `{"step", "event": "trainee_fainted", "slot", "species", "level", "map"}` to the run's `status_care.jsonl` (flushed; best effort) so review tools can count it; count `ctx.trainee_fainted_steps`. `AfterVictory` (Goal Procedures, if merged) may read `trainee_ok`; do not edit it. A blackout or faint in the lead's fights that leaves a member fainted is the same case.
- **No-progress accounting:** `training_progress.training_progress(rows)` already needs an XP or level gain, so a fainted trainee produces no progress by construction; add a pure test that a `levels.jsonl`-shaped sequence with the trainee fainted yields `False`, and expose `ctx.trainee_fainted_steps` so a stall detector or review tool can subtract those steps from "training steps" (the Loop Memory directive's progress tracker will use it; do not edit `ProgressWatch` thresholds).

### 4.5 Tests (all fixtures; no ROM, no emulator run)

`tests/test_status_care.py`: `status_kinds` for each bit and combinations (incl. sleep counter bits), `steps_to_faint` (hp 1 -> 1, hp 10 -> 37, 0 -> 0), the full decision table (poison fine, Antidote preferred, Full Heal fallback, Potion that buys enough, Potion that does not, walk, nothing available, `blackout risk` vs `member loss` wording), burn/paralysis rows are `none`, `poisoners_on` on fixture `wild_by_map` + learnsets (a Weedle map, a poison-move species, a clean map), `poison_ahead` on fixture goals/maps.
`tests/test_status_care_shopping.py`: `shopping_list` adds one Antidote when `poison_ahead` and none carried; not when carried, not when the Mart does not stock it, not when `budget.spendable` is short; the potion maths (`potion_floor`, `bag_hp`) is unchanged; existing shopping tests unedited and green; `heal_items.cure_count`; `MIN_TRIP_YEN` still gates a trip.
`tests/test_status_care_behaviour.py` (FakeEmulator party with a poisoned member; pattern of `tests/test_explorer_behaviours.py`): the behaviour applies only for a poisoned member out of battle; it sets `ctx.center_intent` for the walk row; it logs once per change; it never applies in battle or with a box open; a failed Antidote use is retried at most `MAX_TRIES`; verify-after-use clears on the status byte.
`tests/test_trainee_gate.py`: `trainee_eligible` rows (alive, fainted + Revive, fainted + close center, fainted + far center, poisoned short, poisoned fine); `trainee_ok(ctx)` with a FakeEmulator Magikarp trainee at HP 0 sets the heal intent and logs "trainee fainted: no exp"; `GrindDrill.applies` is False with a fainted trainee; `PlanGoal` keeps the training behaviour otherwise unchanged (the existing plan_goal/team_readiness tests unedited and green); a `levels.jsonl`-shaped fixture with a fainted trainee gives `training_progress(...) == False`.

## 5. What NOT to do

- No battle move-choice changes (`battle_moves.py`), no flee/potion threshold changes, no planner edits (`planner*.py`, `ship_gate.py`, `planner_checkpoint.py`: the Pokecenter path is only REQUESTED through `ctx.center_intent`). No new item-menu or party-prompt code: reuse `item_step`/`UseItems`; if slot targeting is not possible, fall back to the walk and say so.
- Do not put the Antidote into `HEAL_ITEMS` or change `potion_floor`/`bag_hp`. Do not change `MIN_TRIP_YEN`, `reserve`, `FLOOR_MIN`. Do not claim the status bits, the 1-HP-per-4-steps rule or the EXP rule are verified: they are from memory and flagged `# unverified`. No RL. No emulator runs; no `uv run pokeagent ...`. No new dependencies; modules under 300 lines.

## 6. Verification

- `uv run pytest -q tests/test_status_care.py tests/test_status_care_shopping.py tests/test_status_care_behaviour.py tests/test_trainee_gate.py` - new tests pass (paste the tail).
- `uv run pytest -q` green; paste the before/after tails and `git diff --stat main`; confirm no forbidden file changed.
- **Controller validation (not Devin; the ROM is on the laptop):** (1) verify the status byte bits and the overworld poison rate on the ROM: take a save with a poisoned member (a Weedle/Zubat fight, Viridian Forest or Mt Moon), read party byte +4 before and after, count HP loss per walked tile, check burn/paralysis do not tick, and edit the constants and the decode in the one place each; (2) check which Marts stock the Antidote (`items_catalog` stock lists); (3) headless run in Viridian Forest or Mt Moon showing a poison episode handled (Antidote used, or the walk requested) and a fainted-trainee case logging "trainee fainted: no exp" and healing first; (4) confirm in the ROM disassembly or by experiment that a fainted participant gets no EXP.

## 7. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation is rejected and ends the run. No installs, downloads or fetches.
  Never read outside the worktree.
- **Do not run the `pokeagent` entry point (the sandbox refuses it). Do not list the directory tree recursively; use `git ls-files`.
  Do not read outside the worktree. Create no scratch files; deleting is denied. If something expected is missing, stop and write that in the Status row.**
- Do not search, glob or hunt for a missing file or fact: stop and say so in the Status row.
- Test commands are exactly `uv run pytest -q` and `uv run pytest -q tests/<file>`. Never bare `python`.
- Work only on branch `directive/pokeagent-status-care-and-exp-eligibility-directive`. Never commit to `main`; never push; never deploy; no `git stash`. Commit on the branch as you go.
- Create no scratch or debug files (deleting is denied and ends the run). If one is truly needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row; do not try another way around it.
- SOLID/SRP/KISS is a hard rule here: small new modules (under 300 lines), no new dependencies.
- **Standing rule (Robert, 2026-11-07, verbatim): "We can use synthetic data and states and saves throughout, with a standing rule that a synthetic result must be verified by organic data and states and saves, as a proof system."** Every learned record this work writes carries `"provenance": "organic" | "synthetic" | "unknown"`, taken from the start state's lineage (`statefp` lineage, PR #147: if it is not merged or a state has no lineage record the value is `"unknown"`, never guessed, and `unknown` is treated like organic for display and like synthetic for promotion: it can never be promoted by itself). Synthetic-born records are HYPOTHESES: usable for drills, A/B and planning, NEVER a chain best, a confirmed segment, a shared-memory veto or a KNOWLEDGE fact until an organic run reproduces them, at which point they are promoted (same semantics as state promotion). Tests use fixture lineage values only.

## 8. Completion criteria

- [ ] `status_care.py` (decode, `steps_to_faint`, decision table, `poisoners_on`, `poison_ahead`) and the `StatusCare` behaviour (Antidote / Potion / walk, verified, bounded retries)
- [ ] Antidote in the item source of truth (`cure_count`, constants, fallback prices) and the shopping floor of 1 when poison is ahead, existing shopping tests unedited and green
- [ ] `trainee_gate.py` + the `PlanGoal` and `GrindDrill` hooks: heal (Pokecenter or Revive) before training with a fainted trainee, the "trainee fainted: no exp" log and `status_care.jsonl` rows, no-progress accounting tested
- [ ] The four new test files pass; `uv run pytest -q` green (tail pasted); `git diff --stat main` pasted; no forbidden file changed
- [ ] Status row moved to Review with the branch name

## 9. Report

Findings first: test tails (before/after), `git diff --stat`, the final signatures and every named constant, where the behaviour sits in the order, whether the existing item machinery could target a party slot (and what you did if not), the hooks added in `PlanGoal` and `GrindDrill`, the list of items marked `# unverified` (status bits, poison rate, EXP rule), and anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-07 16:20 · robert-claude-laptop · none → Draft — Claude 2026-11-07: poison care/Antidote, shopping floor, EXP eligibility gate
- 2026-11-07 16:20 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; lint_override: dispatch-path-missing greenfield/gitignored
- 2026-11-07 16:24 · robert-claude-laptop · Queued → Draft — Claude: add provenance standing rule
- 2026-11-07 16:25 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; provenance rule; lint_override: dispatch-path-missing greenfield/gitignored
<!-- queue:end -->
