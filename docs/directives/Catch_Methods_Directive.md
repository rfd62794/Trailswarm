# PokeAgent: catch methods - the Gen 1 capture formula, a catch policy (status, minimum damage, best ball) and the overpower gate (a damaging catcher slot)

**Depends on (merged to main; if missing from your worktree, stop and write that in the Status row):** `Team_Builder_V2_Directive.md` (its PR: `knowledge/team_value.py` with `catcher_value` and `CATCHER_BAND`, `knowledge/catch_plan.py` with the provisional `p_catch` / `expected_balls`,
`catch_list.catch_wanted(..., wants=...)`, `ctx.team_wants`, `behaviours/team_hunt.py`). **Do not list the tree recursively**; use `git ls-files`.

**Read first (all in the worktree):** `src/pokeagent/explorer/behaviours/catch.py` (weaken to <=35% then throw; sets `ctx.catch_mode`), `explorer/behaviours/battle_moves.py` (around lines 95-120: the move chooser already uses `move_scores(..., catching=ctx.catch_mode)`
and, in catch mode, "a sleep / paralyse move first, else the weakest damaging hit"), `knowledge/scoring.py` (`move_scores`), `knowledge/damage.py` (`expected_damage`, `AVG_ROLL`, `CRIT_RATE`, `type_mult`), `knowledge/moves.py` (`Effect`, `effect_of`, `EFFECTS`: `kind == "status"`,
`status` is one of poison burn paralyse sleep freeze confuse flinch), `knowledge/party.py` (`Combatant`, `our_party`, `trainer_mon`), `knowledge/catch_plan.py` and `knowledge/team_value.py` (from V2), `explorer/behaviours/switch_out.py` (the party-menu switch you may reuse),
`ramstructs.py` (`BattleMon.status`, `PartyMon.status`, `catch_rate`), `explorer/restock.py` (`ball_price`, `BALL_ID`), `explorer/item_use`/`behaviours/item_use.py` (`item_step`), `tests/test_team_hunt.py`, `tests/test_catch_plan.py` (V2).

## 1. Why this exists

Robert (2026-11-07): "The ability to complete the pokedex gates certain items later, we should train this as a goal along the way to complete where possible, while being cost efficient, and find the best catch methods for each opportunity, including exploring and exploiting
special moves and status, like paralyze and burn. It also needs to recognize the overpower gate, where the high level lead pokemon will always wipe a wild pokemon, and explore ways to avoid this, like having a level band across the party, or a lower level last option for wild exploit."
And (correction, same day): "a cheap low-level member only has value as the catcher if they can cause damage. Magikarp does not apply without an attack to cause damage."

Today (read from the code): `catch.py` weakens a wanted wild species to <= 35% HP then throws a Poke Ball (the only ball it knows, `POKE_BALL = 0x04`); `battle_moves.py` in catch mode prefers a sleep/paralyse move, else the weakest damaging move; V2's `catch_plan.p_catch` is a placeholder
`min(0.95, (catch_rate + 1) / 256 * CATCH_HP_FACTOR)`. There is no capture formula, no choice of ball, no status-aware stopping rule, and nothing handles the overpower gate: when the active mon (the high-level lead) KOs any wild mon with every move, the wild mon cannot be weakened
and the catch fails or never starts.

**HARD RULE (Robert, 2026-11-07): "We can teach the agent a hard rule, you CANNOT Capture an Owned Pokemon, ONLY Wild Pokemon can be caught, Stealing is wrong."**
A ball is thrown ONLY in a WILD battle, never in a trainer battle. The battle kind the behaviours already use: `catch.py` reads `bv.kind` (`ctx.bv.kind`, 1 = wild, 2 = trainer) and `battle.py` derives `trainer = bool(ctx.battle_log and ctx.battle_log.get("kind") == 2) or ctx.trainer_npc is not None`. Implement ONE pure predicate
`may_throw(kind: int | None, trainer_npc: object | None = None, battle_log_kind: int | None = None) -> bool` in `knowledge/catch_policy.py` (True iff the kind is 1 and neither `trainer_npc` is set nor the battle log says 2; unknown/None kind -> False) plus a thin `may_throw_ctx(ctx)` that reads exactly those fields. Everything below obeys it:
`catch_policy.decide` returns `skip` (why "trainer battle: cannot catch") whenever `may_throw` is false, and NEVER returns `throw`, `status_move`-for-catching, `damage_move`-for-catching or `switch`-to-catcher in a trainer battle (the overpower/catcher switch must not trigger there either: in a trainer battle the normal win path decides everything, untouched); `catch.py` sets `ctx.catch_hint` / `ctx.catch_mode` only when `may_throw_ctx(ctx)` holds, and keeps its existing `kind == 1` guard.
Test: `may_throw`/`may_throw_ctx` -> False for a trainer battle (kind 2, or `trainer_npc` set, or log kind 2) and True for a wild one (kind 1, no trainer); `decide(...)` with a trainer battle returns `skip` for every fixture (including a lone overpowering lead and a qualifying catcher in the party).

## 2. Facts (pasted; you cannot look outside the worktree)

- `uv run python --version` prints `Python 3.12.12`. Always `uv run`. Full suite: `uv run pytest -q` (about 100-210 s; 1557 passed, 1 skipped on the live checkout today before V2, plus one environment-dependent failure
  `tests/test_resources.py::test_lock_takeover_is_exclusive` that is unrelated: ignore it and say so if it fails for you).
- `roms/`, `baselines/`, `runs/`, `kb/rom_tables.json` are gitignored. **No ROM, no `kb/`, no `.state` in your worktree.** Tests use `FakeEmulator` and fixture tables passed in as dicts (`tests/test_cut_learner.py`, `tests/test_team_readiness.py`, V2's tests show the patterns).
- **Capture formula (Gen 1, pokered `ItemUseBall`) - NONE of these constants is verified in this repo; they are from memory of the pokered disassembly. Put each one in a named constant with a comment `# unverified: from memory of pokered ItemUseBall` and list them in your report. The controller verifies them (against the disassembly and empirically on the ROM).**
  1. Master Ball: always caught.
  2. `R1` = a uniform random integer in `0..BALL_RMAX`: Poke Ball 255, Great Ball 200, Ultra Ball 150.
  3. Status bonus `s`: asleep or frozen 25, poisoned / burned / paralysed 12, otherwise 0. If `R1 < s` the mon is caught outright; otherwise `R1 -= s`.
  4. If `R1 > catch_rate` (the species' `catch_rate` from `species_by_dex`) the throw fails.
  5. Otherwise `f = min(255, HPmax * 255 // BALL_DIV // max(1, HPcur // 4))` with `BALL_DIV` = 8 for a Great Ball, 12 for Poke Ball and Ultra Ball; a second uniform `R2` in `0..255` catches iff `R2 <= f`.
  6. Ball item ids (pokered): MASTER 1, ULTRA 2, GREAT 3, POKE 4 (only POKE = 0x04 is already confirmed in this repo). Prices come from the ROM items table at runtime (`(ROM_KB or {}).get("items", {}).get(str(id), {}).get("price")`, as `restock.ball_price` does for the Poke Ball); the fallback
     constant when absent is Poke Ball 200, Great Ball 600, Ultra Ball 1200 (unverified).
  7. Battle status byte (pokered): sleep is bits 0-2 (a counter), poison bit 3, burn bit 4, freeze bit 5, paralysis bit 6 (unverified; the decode lives in one helper `status_kind(byte) -> str | None`, so the controller can fix it in one place).
  Probability to implement: `P = (P(R1 < s) + P(s <= R1 and R1 - s <= C) * (f + 1) / 256)` with `R1` uniform on `0..rmax`, i.e. counts over the integers (see the examples).
- **Three worked examples (computed with exactly the formula above; your tests must reproduce them to 1e-3):**
  - A: Poke Ball, no status, catch_rate 255, HPmax 20, HPcur 20: `f = 20*255//12//5 = 85`; `P = 256*(86/256)/256 = 0.3359`.
  - B: Great Ball, asleep (s = 25), catch_rate 45, HPmax 100, HPcur 25: `f = min(255, 100*255//8//6) = 255`; `P = (25 + 46*1.0) / 201 = 0.3532`.
  - C: Ultra Ball, no status, catch_rate 45, HPmax 100, HPcur 35: `f = min(255, 100*255//12//8) = 255`; `P = 46 / 151 = 0.3046`.
  (Also: HPmax 20, HPcur 5, Poke Ball, catch_rate 255 gives `f = 255`, `P = 1.0`.)
- Damage: `damage.expected_damage(level, power, atk, dfn, *, stab, eff)` returns the AVERAGE roll (x0.925) with a small crit bonus (x1.06). The Gen 1 random factor is 217..255 / 255, so the MINIMUM roll is `217/255 = 0.851`, and a crit is ignored for "can it KO" safety only as a margin you name
  (`CRIT_SAFETY = 2.0`: treat the worst case as min-roll damage x 1 for "will it KO" in the catcher check, and max-roll x crit for "could it KO" in the overpower check; both named, untuned).
- Existing seams: `ctx.catch_mode` (bool, read by `battle_moves.py`), `ctx.bv` (the battle view: `kind`, `species`, `e_lvl`, `run_line`), the enemy HP read in `catch.py` (`0xCFE6/0xCFE7` current, `0xCFF4/0xCFF5` max), `item_step(ctx, lines, cursor, POKE_BALL, "POKe BALL", reason)` for throwing, `BattleMon.status`.
- Controller state (gitignored, NOT in your worktree): `baselines/battle_matrix_pidgey_5.state` is a battle baseline against a Pidgey; the controller validates there. You cannot run the emulator.
- **Files you must NOT modify:** `src/pokeagent/explorer/ship_gate.py`, `planner.py`, `planner_east.py`, `planner_checkpoint.py`, `tools/seg_*.py`, `tools/segments.py`.

## 3. Scope (one PR, in order)

1. `src/pokeagent/knowledge/catch_math.py` (pure): the capture formula.
2. `src/pokeagent/knowledge/catcher.py` (pure): the catcher qualification (hard rule) and the level band.
3. `src/pokeagent/knowledge/catch_policy.py` (pure): the decision in a wild battle for a wanted species.
4. Seams: V2's `catch_plan.p_catch` / `expected_balls` and `team_value.catcher_value` use the new modules; `catch.py` / `battle_moves.py` read the policy's decision through ONE new context field (`ctx.catch_hint`).
5. Tests: `tests/test_catch_math.py`, `tests/test_catcher.py`, `tests/test_catch_policy.py`.

## 4. The work

Every constant is named, with `# unverified` where section 2 says so.

### 4.1 `knowledge/catch_math.py` (pure, under 300 lines)

```python
BALLS = {"MASTER": 1, "ULTRA": 2, "GREAT": 3, "POKE": 4}     # item ids (unverified except POKE)
BALL_RMAX = {"POKE": 255, "GREAT": 200, "ULTRA": 150}        # unverified
BALL_DIV = {"POKE": 12, "GREAT": 8, "ULTRA": 12}             # unverified
STATUS_BONUS = {"sleep": 25, "freeze": 25, "poison": 12, "burn": 12, "paralyse": 12}   # unverified
FALLBACK_PRICE = {"POKE": 200, "GREAT": 600, "ULTRA": 1200}  # unverified

def status_kind(byte: int) -> str | None            # the status byte -> "sleep"|"poison"|"burn"|"freeze"|"paralyse"|None
def p_catch(catch_rate: int, hp: int, hp_max: int, ball: str = "POKE", status: str | None = None) -> float   # the formula in section 2; MASTER -> 1.0
def expected_throws(p: float) -> float              # 1 / p, inf when p <= 0
def best_ball(catch_rate, hp, hp_max, status, bag: dict[str, int], price: dict[str, int]) -> tuple[str, float] | None
    # the ball in the bag with the highest P(catch) / price (never MASTER unless it is the only one); None when the bag has none
```

`p_catch` is exact integer counting over `R1` (no floating-point shortcuts), clamped to [0, 1]. V2's `catch_plan.p_catch(catch_rate)` becomes a thin wrapper `catch_math.p_catch(catch_rate, hp=HP_FRACTION_ASSUMED...)` with `PLAN_HP_FRACTION = 0.35`
(the weaken target), a Poke Ball and no status; its signature stays so the V2 tests pass unedited, and only its body changes. Update `expected_balls` to use `expected_throws`.

### 4.2 `knowledge/catcher.py` (pure): the catcher HARD RULE and the level band

**HARD RULE (Robert, 2026-11-07): a low-level member only has value as the catcher if it can cause damage. Magikarp does not apply without an attack to cause damage.**

```python
MIN_ROLL = 217 / 255 / damage.AVG_ROLL      # scale an expected_damage (average roll) down to the minimum roll; named, see section 2
def min_damage(att: Combatant, move: dict, dfn: Combatant, chart: dict) -> float   # expected_damage scaled by MIN_ROLL and without the crit bonus (damage.CRIT_RATE); 0 for a non-damaging move
def safe_moves(att: Combatant, dfn: Combatant, chart: dict, moves: dict) -> list[str]   # moves with 0 < min_damage < dfn.hp  (a hit that cannot KO even at the minimum roll, and hurts)
def qualifies(member: Combatant, wild: list[Combatant], chart, moves) -> bool           # True iff member has at least one safe move against EVERY wild mon in `wild` (the route's species at their lowest level)
def catcher_slot(party: list[Combatant], wild: list[Combatant], chart, moves, lead: int = 0) -> int | None   # lowest-level qualifying member that is not the lead, else None
def level_band_ok(party, wild, chart, moves, band: int = CATCHER_BAND) -> bool          # a qualifying member within `band` levels BELOW the lead exists
```

- A Splash-only Magikarp (below L15, where it learns Tackle) does NOT qualify: it has no damaging move. A status-only move set does NOT qualify (a status move is a bonus handled by the policy, never the qualification). A mon whose every damaging move can KO the wild mon at the minimum roll does NOT qualify.
- V2's `team_value.catcher_value` must call `catcher.qualifies` (it had its own copy of this rule): keep its signature and tests green.
- The level band is the "level band across the party" idea: `level_band_ok` is True when there is a qualifying member within `CATCHER_BAND` of the lead; `catch_plan` adds `catcher_value` for a candidate only when the party does not already satisfy the band (V2 behaviour, unchanged apart from calling these helpers).

### 4.3 `knowledge/catch_policy.py` (pure, under 300 lines)

```python
ACCEPTABLE_P = 0.15            # throw an unweakened target only if one ball has at least this chance; untuned
STATUS_MIN_GAIN = 0.05         # a status move is worth a turn only if it raises P(catch) by at least this (after its own hit chance); untuned
WEAKEN_TARGET = 0.35           # stop reducing HP at or below this fraction (the existing catch.py threshold); untuned
MAX_TURNS = 8                  # give up the attempt after this many policy turns on one wild mon

@dataclass(frozen=True)
class CatchStep:
    kind: str          # "throw" | "status_move" | "damage_move" | "switch" | "skip"
    move: str = ""     # for the two move kinds
    ball: str = ""     # for "throw"
    slot: int | None = None   # for "switch": the party slot of the catcher
    p: float = 0.0     # P(catch) with the chosen ball now (throw) or the expected P after the step
    why: str = ""      # the logged reason

def decide(active: Combatant, party: list[Combatant], wild: Combatant, wild_hp: int, wild_hp_max: int, wild_status: str | None,
           catch_rate: int, bag: dict[str, int], price: dict[str, int], chart: dict, moves: dict, turn: int = 0) -> CatchStep
```

Order of decision (first match wins):
1. `turn >= MAX_TURNS` or no ball in the bag -> `skip`.
2. **Overpower gate.** If EVERY damaging move of `active` can KO the wild mon even at the minimum roll (`safe_moves(active, wild) == []`) then: (a) if `catcher_slot(party, [wild], ...)` exists and is not the active mon -> `switch` to that slot (the catcher then acts through steps 3-5);
   (b) otherwise, if the wild mon is at full HP and `best_ball(...)` gives `p >= ACCEPTABLE_P` -> `throw` now at full HP (do not attack: any hit would KO it); (c) otherwise `skip` (log "overpowered, no catcher, P(catch) too low").
3. **Status first.** If the wild mon has no status and the active mon knows a status move (paralyse or sleep first, then burn/poison via `moves.effect_of(mv).status`; a damaging move with a status side effect counts only as a damaging move) whose
   `accuracy * (P(catch | status) - P(catch | none)) >= STATUS_MIN_GAIN`, use it -> `status_move`. Sleep/freeze beat paralyse/burn/poison by the bonus table (25 vs 12). Never use a status move on a mon that already has a status.
4. **Reduce HP with the minimum-damage move.** While `wild_hp / wild_hp_max > WEAKEN_TARGET`: pick, among `safe_moves(active, wild)`, the move with the LEAST expected damage that is still positive, but only if it will not KO this turn (its MAX-roll damage x `CRIT_SAFETY` `< wild_hp`; if only moves that could KO remain, `throw` instead) -> `damage_move`.
5. **Throw the best ball.** `best_ball(...)` by `P(catch) / price` -> `throw` with `p`.

`decide` is deterministic and never raises on missing data (an unknown species returns `skip`).

### 4.4 Seams (thin; no change to the battle win path)

- New context field `ctx.catch_hint: CatchStep | None`. `catch.py` (only when it already decides to catch a wanted species) builds the inputs (the active and party Combatants via `our_party`, the wild mon via `trainer_mon(sp_name, e_lvl)` with its current HP read from the existing `0xCFE6..` reads, the bag via `bag_contents`, ball prices via the items table) and
  stores `ctx.catch_hint = catch_policy.decide(...)`; `ctx.catch_mode` stays as the existing switch for the move chooser. `battle_moves.py` gets ONE added branch in its existing catch-mode block (read lines ~95-120 first): when `ctx.catch_hint` is `status_move` or `damage_move`, choose that exact move
  instead of its own heuristic; otherwise its present behaviour is unchanged. A `throw` hint makes `catch.py` use `item_step` with the hinted ball (Great/Ultra ball names `"GREAT BALL"` / `"ULTRA BALL"` as the item list shows; unknown names fall back to the Poke Ball). A `switch` hint
  reuses `switch_out.py`'s party-menu press helper to bring the catcher slot out (read it first; if it cannot be reused cleanly, DO NOT write new menu code - leave `switch` unhandled by the behaviour, make `decide` still return it, and say so in the Status row).
- The normal win path (`Battle`, `BattleMoves` when not catching, flee/potion thresholds) is untouched. If `catch_hint` is None the behaviour is exactly today's.

### 4.5 Tests (fixtures; no ROM)

`tests/test_catch_math.py`: the three worked examples A, B, C (1e-3) and the 255/255 case (`P = 1.0`); Master Ball is 1.0; a higher catch rate gives a higher P; lower HP gives a higher P (monotone); sleep beats paralyse beats none; Ultra vs Great at the same inputs matches your formula by hand;
`best_ball` picks the ball with the best P/price (a case where a Great Ball is not worth 3x the price, and one where it is), returns None for an empty bag; `status_kind` maps each documented bit; `expected_throws(0)` is infinite.

`tests/test_catcher.py` (synthetic cartridge pattern from `tests/test_team_readiness.py`): **MAGIKARP L10 (SPLASH only) is rejected as a catcher; MAGIKARP L15 (TACKLE) qualifies against a PIDGEY L3 fixture when the minimum-roll TACKLE does not KO it, and is rejected when it would;**
a status-only fixture mon (only a sleep/paralyse move) is rejected; a mon whose only moves can KO at the minimum roll is rejected; `catcher_slot` returns the lowest-level qualifying non-lead member; `level_band_ok` true/false cases around `CATCHER_BAND`; `team_value.catcher_value` and `catch_plan` still pass V2's tests.

`tests/test_catch_policy.py` (fixture battles): (1) status first: a wild mon with no status and an active mon knowing a paralysis/sleep move whose gain clears `STATUS_MIN_GAIN` -> `status_move` (sleep chosen over paralyse when both known); no status move once the mon is already paralysed;
(2) minimum damage: with two safe moves, the weaker one is chosen; a move that would KO this turn is never chosen; (3) overpower switch: an L25 lead whose every move KOs a PIDGEY L3 at min roll, with a qualifying L10 catcher in slot 2 -> `switch` to slot 2; with no catcher and the wild mon at full HP and P >= `ACCEPTABLE_P` -> `throw` at full HP;
with no catcher and P below it -> `skip`; (4) ball choice: with Poke and Great balls in the bag, the best P/price ball is returned; (5) HP at or below `WEAKEN_TARGET` goes straight to `throw`; `turn >= MAX_TURNS` -> `skip`; (6) unknown species / empty data -> `skip`, no exception.

## 5. What NOT to do

- No changes to the battle behaviour's win path (`Battle`, flee and potion thresholds, `BattleMoves` outside the one catch-mode branch). No PC automation (deposit / withdraw). No edits to `ship_gate.py`, `planner.py`, `planner_east.py`, `planner_checkpoint.py`, `tools/seg_*.py`, `tools/segments.py`.
- No shopping changes (balls are bought by the existing `Restock`; this PR only chooses among balls already in the bag). No new menu-pressing code beyond reusing the existing helpers. No Safari Zone logic, no Master Ball use unless it is the only ball.
- Do not change `damage.expected_damage`'s behaviour or constants (add helpers beside it, in `catcher.py`). No emulator runs by you, no `uv run pokeagent ...`; no reading `kb/` or `baselines/`. Each module under 300 lines, no new dependencies.

## 6. Verification

- `uv run pytest -q tests/test_catch_math.py tests/test_catcher.py tests/test_catch_policy.py` - new tests pass (paste the tail with the worked-example values).
- `uv run pytest -q tests/test_catch_plan.py tests/test_team_value.py tests/test_team_hunt.py tests/test_explorer_behaviours.py` - V2's tests stay green unedited.
- `uv run pytest -q` green; paste the before/after tails and `git diff --stat main`; confirm no forbidden file changed.
- **Controller validation (not Devin; the ROM is on the laptop):** from `baselines/battle_matrix_pidgey_5.state` (gitignored, the controller's state), a headless Pidgey catch showing the policy's steps in the log; the controller also verifies each `# unverified` constant (formula, ball ids, prices, status bits) against the pokered disassembly and the ROM.

## 7. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation is rejected and ends the run. No installs, downloads or fetches.
  Never read outside the worktree.
- **Do not run the `pokeagent` entry point (the sandbox refuses it). Do not list the directory tree recursively; use `git ls-files`.
  Do not read outside the worktree. Create no scratch files; deleting is denied. If something expected is missing, stop and write that in the Status row.**
- Do not search, glob or hunt for a missing file or fact: stop and say so in the Status row.
- Test commands are exactly `uv run pytest -q` and `uv run pytest -q tests/<file>`. Never bare `python`.
- Work only on branch `directive/pokeagent-catch-methods-directive`. Never commit to `main`; never push; never deploy; no `git stash`. Commit on the branch as you go.
- Create no scratch or debug files (deleting is denied and ends the run). If one is truly needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row; do not try another way around it.
- SOLID/SRP/KISS is a hard rule here: small new modules (under 300 lines), no new dependencies.

## 8. Completion criteria

- [ ] `knowledge/catch_math.py` (formula, `best_ball`, `status_kind`), the three worked examples reproduced; every unverified constant named and commented
- [ ] `knowledge/catcher.py` with the damaging-move HARD RULE (Splash-only Magikarp rejected, Tackle Magikarp qualifies only when it cannot KO at the minimum roll), `catcher_slot`, `level_band_ok`; V2's `catcher_value` uses it
- [ ] `knowledge/catch_policy.py` (`decide`: overpower gate, status first, minimum damage, best ball) gated by the pure `may_throw` predicate (wild only; trainer battle never throws, never switches to a catcher; tested); `ctx.catch_hint` seam in `catch.py` and the one added branch in `battle_moves.py`; the win path untouched
- [ ] Three new test files pass; V2's tests unedited and green; `uv run pytest -q` green (tail pasted); `git diff --stat main` pasted; no forbidden file changed
- [ ] Status row moved to Review with the branch name

## 9. Report

Findings first: test tails (before/after), `git diff --stat`, the final signatures, the list of `# unverified` constants and their values, the three worked-example outputs, whether the `switch` hint was wired through `switch_out.py` or left unhandled (and why), and anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Approved |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-07 15:19 · robert-claude-laptop · none → Draft — Claude 2026-11-07: Gen 1 capture formula, catch policy, damaging-catcher rule; depends on Team_Builder_V2
- 2026-11-07 15:20 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; depends on Team_Builder_V2 merging first; lint_override: dispatch-path-missing on greenfield modules/tests and gitignored kb/baselines paths
- 2026-11-07 15:52 · robert-claude-laptop · Queued → Draft — Claude: amend with Robert's hard rule (wild only, never catch an owned/trainer Pokemon)
- 2026-11-07 15:52 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; wild-only hard rule added; depends on Team_Builder_V2; lint_override: dispatch-path-missing greenfield/gitignored
- 2026-11-07 16:31 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing on greenfield modules (catch_math.py, catcher.py, catch_policy.py, tests) and gitignored kb/rom_tables.json; known false positives. Dependency Team_Builder_V2 merged as PR #151.
<!-- queue:end -->
