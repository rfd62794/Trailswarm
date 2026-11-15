# PokeAgent: Battle synthetic scenarios - a seeded generator of legal battle situations and property tests that the lead, wild-switch and PP-zero rules hold across hundreds of them

**Size:** M. **Model:** swe-2-high. **Assignee:** devin.

**Depends on:** `Lead_And_Wild_Switch_Directive.md` (In progress) AND `PP_Zero_Move_Guard_Directive.md` (Approved), both merged first. From the first: `can_damage`, `lead_order`, the `TRAINEE_SAFE_HP` constant and the `wild` keyword of `switch_choice` in `src/pokeagent/knowledge/team_plan.py`. From the second: `src/pokeagent/explorer/behaviours/battle_pp.py` <!-- new: src/pokeagent/explorer/behaviours/battle_pp.py --> (`usable_moves`, `cursor_step`). Check with `git grep -n "def can_damage\|def lead_order\|TRAINEE_SAFE_HP" -- src/pokeagent/knowledge/team_plan.py` and `git ls-files src/pokeagent/explorer/behaviours/battle_pp.py`. If either check prints nothing, STOP and write "dependency not merged" in the Status row; do not recreate or stub those functions. Both are not merged yet, so this directive describes them from their own directives; the merged code wins wherever it differs, and you list each difference in the PR description. **Coordinate with** `Battle_Simulator_Directive.md` (Queued, assigned to Claude, not started): see "Overlap with the Battle Simulator" below. Base: current main containing both dependencies.

**Read first:** `docs/directives/Lead_And_Wild_Switch_Directive.md`, `docs/directives/PP_Zero_Move_Guard_Directive.md`, `docs/directives/Battle_Simulator_Directive.md`, `src/pokeagent/knowledge/team_plan.py`, `src/pokeagent/knowledge/readiness.py`, `src/pokeagent/knowledge/damage.py`, `src/pokeagent/knowledge/party.py`, `tests/test_switch_matchup.py` (the synthetic `SYN` knowledge-base style and the `_mon` helper).

## Standing rule for synthetic data (Robert, 2026-11-07, verbatim)

"We can use synthetic data and states and saves throughout, with a standing rule that a synthetic result must be verified by organic data and states and saves, as a proof system."

Here: generated scenarios test and drill the battle rules; they never decide truth. A property that holds on a thousand synthetic scenarios is a claim, not proof the live agent behaves; Claude confirms on real battles (the Report names how). A scenario never becomes a checkpoint, a KNOWLEDGE fact or a threshold change.

## 1. Why this exists

Robert, 2026-11-14: "The Agent keeps using low-levelled pokemon in battle until they faint, instead of relying on the swap tactic where more effective", and "Agent also gets stuck trying Ember even when out of PP". Two directives fix the rules, and each pins them with a handful of hand-written cases (`tests/test_lead_and_wild_switch.py`, `tests/test_battle_pp_guard.py`). Hand-written cases test the situations their author thought of. The real bugs came from combinations nobody listed: a Harden-only Kakuna that leads because it is the lowest level, a candidate at 3 HP that a foe one-shots on the switch turn, a stale PP read of all zeros, a Magikarp trainee at 30 percent HP. A seeded generator of LEGAL battle situations, plus property tests that assert the rules over hundreds of them, finds the combinations for free, repeatably, with no emulator and no ROM.

The properties to hold, in the words of the two directives:
1. The lead can damage: when any healthy member can hurt a foe, the member that leads is not one that cannot (`Lead_And_Wild_Switch` rule 1).
2. No press of a 0-PP move: the PP guard never selects or presses a move whose PP is 0, and an all-zero read yields no usable move (`PP_Zero_Move_Guard`).
3. The trainee is never left below the safety HP: a designated trainee under `TRAINEE_SAFE_HP` is switched out when an eligible candidate exists, and is never switched IN (`Lead_And_Wild_Switch` rule 4).
4. The incoming member survives the hit: any member a switch picks can take the foe's best expected hit on the switch turn (`Lead_And_Wild_Switch` rule 3).

## 2. Overlap with the Battle Simulator (read it; do not duplicate it)

`docs/directives/Battle_Simulator_Directive.md` (Queued, assigned to claude, base-less, 2026-11-09) specifies a full seeded Gen 1 battle ENGINE under `src/pokeagent/sim/` (damage with random roll, crits, status, stat stages, trainer AI, rollouts, a sim-versus-real harness). That is a different and much larger thing: it plays a battle forward turn by turn.

This directive is ONLY (a) a seeded generator of the situation at the START of a decision (parties, HP, PP, the foe and its moves, with the expected damage the existing closed-form maths gives), and (b) property tests that call the EXISTING pure rule functions on those situations. It has no turn engine, no random damage roll, no status effects, no trainer AI and no rollout. Scope decision, stated for the record: the overlap is "synthetic battle inputs"; this directive owns the scenario generator and the property tests; the simulator directive keeps the engine. Rules:
- Do NOT create or edit anything under `src/pokeagent/sim/`. If `git ls-files src/pokeagent/sim` lists files when you start, read its party and move types and keep the `Scenario` record below easy to convert to them, but do not import from `sim/`, and list any duplication you notice in the PR description.
- Keep the generator pure and importable so the simulator can later reuse it for its starting positions without a rewrite.

## 3. Facts to build on (pasted; the worktree cannot be searched; `uv run python --version` prints `Python 3.12.12`)

```
# src/pokeagent/knowledge/party.py
@dataclass(frozen=True)
class Combatant:  name: str; level: int; types: tuple[str, ...]; hp: int   # hp is MAX hp
                  stats: tuple[int, int, int, int]   # atk, def, spd, spc
                  moves: tuple[str, ...]; dv: tuple[int, ...] = (); sexp: tuple[int, ...] = ()
def species_row(name: str, kb: dict | None = None) -> dict | None            # row of kb["species_by_dex"] with the key name
def moves_at(name: str, level: int, kb: dict | None = None, after: int = 0) -> list[str]   # up to 4 moves legal at that level
def trainer_mon(name: str, level: int, kb: dict | None = None) -> Combatant | None   # base stats at DV 8, no stat exp, legal moves
# src/pokeagent/knowledge/readiness.py
def best_move(att: Combatant, dfn: Combatant, chart: dict, moves: dict) -> tuple[float, str]
    # (expected damage per turn, move name) of the best hit att knows against dfn; (0.0, "") when nothing damages
def _chart(kb) -> dict                      # {(attack type, defend type): multiplier}
# src/pokeagent/knowledge/damage.py
def type_mult(chart, move_type, def_types) -> float
def expected_damage(level, power, atk, dfn, *, stab: bool, eff: float) -> float
# src/pokeagent/knowledge/kb.py
def table(kb: dict | None, key: str) -> dict          # kb[key], or the loaded ROM tables, or {}
# src/pokeagent/explorer/stats.py
def stat_value(base: int, dv: int, stat_exp_value: int, level: int, *, hp: bool = False) -> int
# src/pokeagent/knowledge/team_plan.py (already on main)
def ascending_order(levels, fainted) -> list[int]
def trainee_slot(party, named=None, breakers=(), wild=None, kb=None) -> int | None
def switch_choice(team, active_slot: int, opponent, kb, *, hp_now=None, switches: int = 0, trainee: int | None = None) -> int | None
SWITCH_HP_TURNS = 2; WEAK_RATIO = 0.5; SWITCH_MIN_HP = 0.25; SWITCH_GAIN = 1.5; MAX_SWITCHES_PER_BATTLE = 2
def survives_hit(member: Combatant, foe: Combatant, chart: dict, moves: dict) -> bool   # best_move(foe, member)[0] < member.hp (MAX hp)
```
The knowledge-base shape (a plain dict, the synthetic style of `tests/test_switch_matchup.py`): key `moves` maps a move id string to a row with name, type, power, accuracy, effect, pp; key `type_chart` is a list of triples (attack type, defend type, multiplier); key `species_by_dex` maps a dex string to a row with name, type1, type2, hp, atk, def, spd, spc, moves1 (the level-1 move names); key `learnsets` maps a species name to a row whose `learnset` is a list of pairs (level, move name). A row for HARDEN has power 0; a row for POISON STING has power 15.

From the two dependency directives (confirm against the merged code):
```
# src/pokeagent/knowledge/team_plan.py (Lead_And_Wild_Switch)
def can_damage(c, kb=None) -> bool                       # any move with power above 0 in the kb moves table
def lead_order(levels, fainted, can_dmg) -> list[int]    # sorted by (fainted, not can_dmg, level); can_dmg None equals ascending_order
TRAINEE_SAFE_HP = 0.35
switch_choice(team, active_slot, opponent, kb, *, hp_now=None, switches=0, trainee=None, wild=False)
#   a candidate is eligible only when best_move(foe, c, chart, moves)[0] < its CURRENT HP, current HP / max HP >= SWITCH_MIN_HP, it is not the trainee;
#   a trainee active under TRAINEE_SAFE_HP switches out to an eligible candidate even when not "thin"
# src/pokeagent/explorer/behaviours/battle_pp.py (PP_Zero_Move_Guard)
def usable_moves(moves: list[str], pp_bytes: tuple[int, ...] | None, no_pp: set[str]) -> list[str]   # PP is the low 6 bits of each byte; pp_bytes None = stale read, all usable
def cursor_step(cursor_mv: str, target: str, usable: list[str], nav: int) -> tuple[str, str | None]    # ("press_a", move) never for a move outside usable
```

## 4. Scope (in this order)

1. `src/pokeagent/knowledge/battle_scenarios.py` <!-- new: src/pokeagent/knowledge/battle_scenarios.py --> - the pure seeded generator and the `Scenario` record. Under 200 lines.
2. `tests/scenario_kb.py` <!-- new: tests/scenario_kb.py --> - a richer synthetic knowledge base than `SYN` (about 12 species across at least 5 types with a few species that have NO damaging move at low level, about 16 moves including HARDEN with power 0, a type chart with super effective, resisted and immune pairs, and learnsets that give some species a damaging move only after a level) plus the helper that builds a `Combatant` at a level. Test support only; under 150 lines. No game data: invented names and numbers only, so no fixture is derived from a cartridge.
3. `tests/test_battle_scenarios.py` <!-- new: tests/test_battle_scenarios.py --> - tests of the generator itself (legality, determinism, coverage).
4. `tests/test_battle_rule_properties.py` <!-- new: tests/test_battle_rule_properties.py --> - the property tests over N scenarios for the four rules above.
5. `docs/KNOWLEDGE.md` - two sentences naming the generator, the seed and how to re-run a failing seed.

Nothing else changes. No file under `src/pokeagent/explorer/behaviours/`, `src/pokeagent/sim/`, `tools/` or any existing test is edited.

## 5. The work

### 5.1 The generator (`src/pokeagent/knowledge/battle_scenarios.py`, pure)

```
N_DEFAULT = 500                       # scenarios per property test
LEVEL_RANGE = (2, 60)

@dataclass(frozen=True)
class Scenario:
    seed: int
    index: int
    party: tuple[Combatant, ...]      # 1 to 6 members, legal species, levels and moves
    hp_now: tuple[int, ...]           # current HP per member, 0 (fainted) to max, at least one above 0
    pp: tuple[tuple[int, ...], ...]   # per member, one PP byte per move slot (see below)
    active: int                       # slot of the member in the battle, never fainted
    trainee: int | None               # a designated trainee slot, or None
    wild: bool                        # a wild fight (True) or a trainer fight (False)
    foe: Combatant                    # the opposing mon, built like a trainer mon at its level
    foe_hp_now: int                   # 1 to foe.hp
    incoming: tuple[tuple[float, str], ...]   # per member, best_move(foe, member): expected damage per turn and move name
    outgoing: tuple[tuple[float, str], ...]   # per member, best_move(member, foe)

def generate(seed: int, index: int, kb: dict) -> Scenario: ...
def scenarios(seed: int, n: int, kb: dict) -> Iterator[Scenario]: ...
```
Rules:
- Seeded: `random.Random(f"{seed}:{index}")` (a string seed, so scenarios are independent of each other and stable across Python versions). `generate(seed, i, kb)` is the same every call; `scenarios` yields `generate(seed, i, kb)` for i in range(n). No global state, no clock, no file access.
- Legal: every species is a species row in `table(kb, "species_by_dex")` (sorted names before sampling); every level is in `LEVEL_RANGE`; the moves of a member are a subset of `moves_at(name, level, kb)` (at most 4, never empty: if the learnset gives none, use the level-1 moves); max HP and stats come from `trainer_mon(name, level, kb)` so they follow the existing base-stat maths (use `dataclasses.replace` to set `moves` on that result). The foe is built the same way. HP: `hp_now[i]` is drawn from a mix that deliberately includes the edges (0, 1, exactly 25 percent of max, exactly 35 percent of max, exactly max) as well as uniform values; at least one member is above 0 and `active` is one of them.
- PP bytes: for each move slot, a PP value in 0 to the move's `pp` from the kb moves table (0 and 1 are drawn often) OR'd with a PP-Up flag in the top two bits drawn from 0, 0x40, 0x80, 0xC0, so a byte such as 0xC0 (PP 0 with PP Ups) occurs. With a small probability (about 2 percent) a member's PP is all zeros (the real all-zero read), and with about 1 percent the whole `pp` entry is None-equivalent: model "stale read" separately as the PP tuple for that member being the empty tuple, which the tests translate to the `pp_bytes=None` call.
- `trainee`: None in about half the scenarios; otherwise a slot that is not `active` in about half of the remainder and equal to `active` in the rest (the interesting case for the safety rule).
- `incoming` and `outgoing` come from the existing `readiness.best_move(att, dfn, chart, moves)` with `chart = readiness._chart(kb)` and `moves = table(kb, "moves")`. Do NOT reimplement damage, type effectiveness or STAB; that is the whole point of reusing the modules. A property test also asserts the stored values equal a fresh `best_move` call so the record cannot drift from the maths.
- Coverage by construction, not luck: a fixed fraction of scenarios (at least one in six) is built from a "stress template" instead of free sampling: a Harden-only member as the lowest level, a member at 1 to 3 HP the foe can one-shot, a trainee at exactly `TRAINEE_SAFE_HP` and just under it, a party of exactly one member, an all-fainted-but-the-active party, a foe immune to every move of the active member (outgoing damage 0). The templates still go through the same legality rules.
- Planning and tests only: the module imports nothing that touches an emulator, a RAM address, a file or a window, and nothing from `src/pokeagent/sim/`.

### 5.2 Tests of the generator (`tests/test_battle_scenarios.py`)

- Determinism: `generate(7, 3, KB)` equals itself on a second call; `scenarios(7, 50, KB)` twice gives equal lists; a different seed gives a different list.
- Legality over 500 scenarios: every species exists in the kb; every move of every member is in `moves_at(name, level, kb)`; levels in range; `hp` equals the `trainer_mon` max HP; at least one member above 0 HP; `active` is above 0 HP; `len(party)` from 1 to 6; PP bytes are ints in 0 to 255 whose low 6 bits do not exceed the move's `pp`.
- `incoming` and `outgoing` equal fresh `best_move` calls for every member of every scenario.
- Coverage: across 500 scenarios at least these each occur at least 5 times: a member that cannot damage (all its moves power 0); a member with PP byte low 6 bits equal to 0 while another slot has PP above 0; an all-zero PP member; a trainee equal to the active slot; a member at 1 to 3 HP; a wild fight and a trainer fight; a foe that the active member cannot damage at all. If a count is too low, fix the generator, not the threshold.

### 5.3 Property tests (`tests/test_battle_rule_properties.py`)

Each test loops `scenarios(SEED, N_DEFAULT, KB)` for two fixed seeds (so about 1000 scenarios per property), calls the EXISTING rule functions, and on a violation fails with the seed, the index and the scenario so it can be replayed with one call. Define a helper that converts a scenario to the arguments the functions take (`levels`, `fainted` flags from `hp_now`, `hp_now` list, the kb). The tests must be fast: the whole file under 10 seconds.

1. Lead can damage (rule 1). Build `levels`, `fainted = [hp == 0 ...]`, `can_dmg = [can_damage(c, KB) ...]`. Assert: `lead_order(levels, fainted, can_dmg)` is a permutation of the slots; fainted slots come after every non-fainted slot; when any non-fainted member can damage, the FIRST slot of the order is a member that can damage; among members that can damage and are not fainted, the first is the lowest level (ties keep slot order); `lead_order(levels, fainted, None)` equals `ascending_order(levels, fainted)`; `can_damage` is False exactly for members whose every move has power 0 in the kb.
2. No 0-PP press. For each member, call `usable_moves(list(member.moves), pp_bytes, no_pp)` with `pp_bytes` as the member's PP tuple (None for the stale-read marker) and with `no_pp` empty and then with a random subset of the member's moves (seeded). Assert: no returned move has `byte & 0x3F == 0`; every returned move is not in `no_pp`; with `pp_bytes` all zero the list is empty; with `pp_bytes` None the list is every move not in `no_pp`; a move with the PP-Up bits set and low bits above 0 IS usable. Then for every `cursor_step(cursor_mv, target, usable, nav)` over each move as the cursor move, each move as the target, and `nav` in 0, 5, 6, 50: it never returns `("press_a", m)` with `m` outside `usable`, and with an empty `usable` it never returns a press-A at all.
3. Trainee never left below the safety HP (rule 4). For scenarios whose `trainee` equals `active` and whose current HP fraction is below `TRAINEE_SAFE_HP`: compute the set of eligible candidates yourself (not the trainee, not fainted, current HP over max at least `SWITCH_MIN_HP`, and surviving the hit as in property 4); call `switch_choice(party, active, foe, KB, hp_now=list(hp_now), trainee=trainee, wild=scenario.wild)`; assert that when that set is non-empty the result is not None and is in the set. Also over ALL scenarios: the result is never the trainee slot (the trainee is never switched IN) and never the active slot. A scenario with no eligible candidate is allowed to return None; assert nothing else about it (the rule cannot save a trainee when nobody can come in, and the test must say so in a comment).
4. Incoming survives the hit (rule 3). Over all scenarios and both `wild` values: when `switch_choice` returns slot `s`, then `incoming[s][0] < hp_now[s]` (the foe's best expected hit is strictly below the member's CURRENT HP), the member is not fainted, `hp_now[s] / party[s].hp >= SWITCH_MIN_HP`, `s != active`, and `s != trainee`. When `switches >= MAX_SWITCHES_PER_BATTLE`, `switch_choice` returns None. Wild versus trainer: in a trainer fight the existing "thin" test applies; do not assert liveness there beyond the property above.
5. Wild liveness (rule 2 of the switch directive, one test): over scenarios with `wild` True, a no-damage active member (`outgoing[active][0] == 0`) and at least one eligible candidate that can damage the foe (`outgoing[c][0] > 0`) and survives the hit, `switch_choice(..., wild=True)` returns a slot (not None). This pins "a Harden-only lead is swapped out of a wild fight".

If a property FAILS on a generated scenario, that is a finding, not a test to loosen. Do not change `team_plan.py`, `battle_pp.py` or any behaviour file. Record the failing seed, index and a one-line reading of the scenario in the Report under "Findings", mark the test with `pytest.mark.xfail(strict=True, reason="<finding>")` ONLY after you have shown it fails for a genuine rule bug and not a generator illegality, and keep the passing assertions of the same test. Claude opens the fix as its own named change.

## 6. What NOT to do

- No emulator, no ROM, no window, no real RAM read, no `runs/`, no `baselines/`, no save states. Every fixture is invented; none is derived from game data.
- Do not edit `team_plan.py`, `readiness.py`, `damage.py`, `party.py`, `battle_pp.py`, `battle_moves.py`, `switch_out.py`, `party_order.py`, `battle.py`, or anything under `src/pokeagent/sim/`. The generator reads those modules; it does not change them.
- Do not build a turn engine, a random damage roll, status effects, a trainer AI or a rollout; that is `Battle_Simulator_Directive.md`.
- Do not retune any constant (`SWITCH_GAIN`, `SWITCH_HP_TURNS`, `WEAK_RATIO`, `SWITCH_MIN_HP`, `TRAINEE_SAFE_HP`). Do not reimplement damage or type maths in the generator.
- Do not add a dependency (no hypothesis library: the generator is hand-rolled and seeded). Do not state where any game copy came from.

## 7. Verification (exact commands)

```
uv run --frozen pytest -q tests/test_battle_scenarios.py tests/test_battle_rule_properties.py
```
Expected: all pass (or the one documented strict xfail per genuine finding).

```
uv run --frozen pytest -q tests/test_switch_matchup.py tests/test_team_plan.py tests/test_team_readiness.py tests/test_team_floor.py
```
Expected: no new failures. Claude ran this exact command on main while writing the directive; the tail was `48 passed, 1 warning`. After the dependencies merge, also run `tests/test_lead_and_wild_switch.py` and `tests/test_battle_pp_guard.py` and paste their tails.

```
git diff --stat origin/main -- src/pokeagent tests docs
```
Expected: the files in Scope only.

## 8. Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command. Never bare `python`.
- Branch only (`directive/pokeagent-battle-synthetic-scenarios-directive`); commit as you go; never commit to or push main; never merge.
- Create no scratch or debug files; anything temporary goes under `.devin-scratch/`.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat and test tails in the Report.
- Synthetic data may train, test and drill but never decides truth: never scored on (evaluation is always organic held-out data), never a checkpoint start, chain best, KNOWLEDGE fact or shared-memory veto without organic confirmation. Every synthetic record carries a provenance tag (here: the `seed` and `index` fields of every `Scenario`). Reports show organic versus synthetic side by side. The synthetic share of any training mix is capped by a config constant (not applicable: nothing here trains). ROM-derived data stays local and gitignored, never published; the fixtures here are invented, not derived. Never state where a game copy came from.
- Tests never open a window.

## 9. Completion criteria

- [ ] `generate` is deterministic and independent per index; `scenarios` yields exactly n scenarios; a different seed differs. <!-- test: tests/test_battle_scenarios.py -->
- [ ] Every generated party is legal (species in the kb, level in range, moves from `moves_at`, HP from `trainer_mon`, at least one live member, the active member alive, PP bytes bounded) over 500 scenarios. <!-- test: tests/test_battle_scenarios.py -->
- [ ] `incoming` and `outgoing` equal fresh `best_move` calls and the generator contains no copy of the damage maths. <!-- test: tests/test_battle_scenarios.py -->
- [ ] The coverage counts in section 5.2 are each reached at least 5 times in 500 scenarios. <!-- test: tests/test_battle_scenarios.py -->
- [ ] Property 1 (lead can damage) holds over about 1000 scenarios. <!-- test: tests/test_battle_rule_properties.py -->
- [ ] Property 2 (no 0-PP press, all-zero yields nothing, stale read yields all) holds, including the PP-Up bit case. <!-- test: tests/test_battle_rule_properties.py -->
- [ ] Property 3 (trainee never left below the safety HP when an eligible candidate exists, never switched in) holds. <!-- test: tests/test_battle_rule_properties.py -->
- [ ] Property 4 (the incoming member survives the foe's best hit at its CURRENT HP, honours the minimum HP, the cap, and excludes the trainee and the active slot) holds. <!-- test: tests/test_battle_rule_properties.py -->
- [ ] Property 5 (a no-damage wild lead is swapped out when a damaging survivor exists) holds. <!-- test: tests/test_battle_rule_properties.py -->
- [ ] The existing test files in section 7 pass unchanged, and no file outside Scope changed.
- [ ] Status row set to `Review` with the evidence above.

## 10. Report

Diff stat, test tails (including the two dependency test files once merged), the generator's constants, the coverage counts reached, every difference between the dependency descriptions here and the merged code, and "Findings": each property that failed on a generated scenario with its seed, index and a one-line reading (or "none"). Then the check Claude runs afterwards with the ROM (Devin cannot): replay three of the generated lead and PP situations as real save-state battles and confirm the live agent behaves as the properties say; the properties are claims until that organic check passes.

## Forbidden Actions

- ROMs, extracted game art, save states and anything derived from them are local and gitignored. Never commit them or add one as a fixture.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor.
- Do not open a window or send input.
- Do not commit to or push main, merge, or deploy.

## Required from User

- The organic replay in the Report, run by Claude after the dependencies merge. Nothing here blocks the run.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(git diff)
- Exec(git grep)
