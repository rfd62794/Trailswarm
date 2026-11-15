# PokeAgent: Trainer party from RAM - read the true enemy party (species, levels, moves) at a trainer fight, remember it per boss, and plan against it instead of the static ROM table

**Independent of the stat-stage and status directives.** It does not touch `team_plan.switch_choice`. Base: current main (it works with or without `Lead_And_Wild_Switch_Directive.md` merged; it edits `team_plan._theirs`, `choose_lead` is only read). **Coordinate with** `Opponent_Modeling_Directive.md` (queued, not started; its counter planner and species book also want the enemy party: they should call `enemy_party.read_party` and `boss_source.boss_for` from this directive, so keep those signatures stable) and `Battle_Simulator_Directive.md` (it wants trainer parties too; do not build a second reader).

## Why this exists

Robert's perception inventory (2026-11-14): the enemy trainer's party is decoded and never used. `ENEMY_PARTY_COUNT` 0xD89C, `ENEMY_PARTY_SPECIES` 0xD89D and `ENEMY_MONS` 0xD8A4 (`src/pokeagent/ram_symbols.py:41-44`, 44-byte structs) are read only by `_enemy_party` in `src/pokeagent/party_view.py:139-148` (species, hp, max_hp and level; NOT moves, status or PP), which `read_battle_view` fills for trainer fights only (`kind == 2`, `party_view.py:174`; the symbols are stale outside trainer fights). Nothing in `src/` or `tools/` consumes `BattleView.enemy_party` except tests (`git grep -n "enemy_party" -- src tools`).

Every planning decision uses the static ROM table instead. Claude traced it (origin/main 01b7fd6):

- `team_plan.choose_lead(team, opponent_party, kb, hp_now)` (`src/pokeagent/knowledge/team_plan.py:88`) has exactly one caller, `team_plan.boss_need` (L118); `boss_need` is called by `src/pokeagent/explorer/training.py:92` (`boss_need_for`) and `tools/grind_report.py:60`. Its `boss` argument comes from `trainers.boss_party(goal, starter_names)` (`src/pokeagent/knowledge/trainers.py:46`): a list of (level, species) read from the ROM `trainers` table.
- Those moves are invented: `_theirs` (`team_plan.py:84-85`) turns each (level, species) into a `Combatant` via `trainer_mon(name, level)`, whose moves are the LEARNSET-legal moves at that level (`src/pokeagent/knowledge/party.py` `moves_at`), not the moves the trainer's mon actually carries. A gym leader or rival whose mon has a fixed or different moveset is mis-scored in both directions.
- The rival's party is guessed: with no starter name in our party `boss_party` takes "the strongest of the three" parties (`trainers.py:46-60`, docstring: "the cautious choice"), so readiness can be pessimistic for a fight whose real variant is known the moment it starts.
- The planners (`src/pokeagent/explorer/behaviours/plan_goal.py:63-76`, `readiness_for`, `team_for`, `boss_need_for`) run in the overworld (`party_all = ... if not ctx.view.battling else []`, L61), where the enemy RAM block is stale. So RAM can never feed them directly. What RAM CAN do is observe the true party the first time a boss is fought and let every LATER planning pass (after a blackout and retry, after a rematch attempt, in the next run that shares maps.json) use the observed party, its real levels and its real moves.

## Scope (in this order)

1. `src/pokeagent/party_view.py` - `EnemyPartyMon` gains `moves` and `status` (defaulted, so every existing constructor and test keeps working) and `_enemy_party` decodes them.
2. `src/pokeagent/knowledge/enemy_party.py` <!-- new: src/pokeagent/knowledge/enemy_party.py --> - the validated read and the "remaining party" view. Under 130 lines.
3. `src/pokeagent/knowledge/boss_source.py` <!-- new: src/pokeagent/knowledge/boss_source.py --> - `boss_for`: observed party when it matches a ROM option for the goal, else the ROM table, with the reason. Under 100 lines.
4. `src/pokeagent/knowledge/team_plan.py` - `_theirs` accepts (level, species, moves) entries (net growth under 6 lines).
5. `src/pokeagent/explorer/training.py` and `src/pokeagent/explorer/behaviours/plan_goal.py` - `readiness_for`, `team_for` and `boss_need_for` take an optional `observed` table and use `boss_for` (plan_goal.py is at 298 of 300 lines: change the existing three call sites in place without adding lines; if that cannot be done, first move an equal number of lines into a new module).
6. `src/pokeagent/explorer/behaviours/battle_party.py` <!-- new: src/pokeagent/explorer/behaviours/battle_party.py --> - an observer behaviour: at each trainer fight start and each time the enemy party position changes, read, validate, remember, log. Under 100 lines. Register it in `default_behaviours` in `src/pokeagent/explorer/behaviours/__init__.py` directly after `Battle()` (it always returns None; `src/pokeagent/explorer/behaviours/battle.py` is at 299 of 300 lines so it must not be edited).
7. Tests: `tests/test_enemy_party.py`, `tests/test_boss_source.py`, `tests/test_battle_party.py` <!-- new: tests/test_enemy_party.py --> <!-- new: tests/test_boss_source.py --> <!-- new: tests/test_battle_party.py -->.

## The work

Existing facts, pasted (the worktree cannot be searched; `uv run python --version` prints `Python 3.12.12`):

```
# src/pokeagent/ram_symbols.py
ENEMY_PARTY_COUNT = 0xD89C; ENEMY_PARTY_SPECIES = 0xD89D; ENEMY_MONS = 0xD8A4; ENEMY_MON_SIZE = 44; ENEMY_MON_PARTY_POS = 0xCFE8; MAX_PARTY = 6
# src/pokeagent/party_view.py (before this directive)
@dataclass(frozen=True) class EnemyPartyMon: species: int; hp: int; max_hp: int; level: int
BattleView: kind (0 none, 1 wild, 2 trainer), battle_mon, enemy_mon (EnemyMonView | None), enemy_party_pos (int | None, trainer only), participants, enemy_party (tuple; () in wild fights)
_enemy_party reads, per struct i: species[i] from ENEMY_PARTY_SPECIES, hp = u16 at struct+1, level = byte at struct+33, max_hp = u16 at struct+34
# party struct offsets (pret, the same 44-byte layout the player's party uses): +0 species, +1 hp (2), +4 status, +8..+11 moves (4 ids), +29..+32 PP (4), +33 level, +34 max hp (2)
# src/pokeagent/knowledge/trainers.py
GYM_BOSSES = beat_brock -> (BROCK, 1, 0x36), beat_misty -> (MISTY, 1, 0x41)    # (class, party number, gym map)
RIVAL_BOSSES: goal -> (class, first party number); the rival has THREE parties per slot (one per starter line)
def party_of(trainer_class, number=1, kb=None) -> list[tuple[int, str]]    # [(level, species)] ROM table; [] when unknown
def boss_party(goal, kb=None, starter_names=()) -> list[tuple[int, str]]
# src/pokeagent/knowledge/team_plan.py
def _theirs(boss, kb) -> list[Combatant]: return [m for lv, n in boss or () if (m := trainer_mon(n, lv, kb))]
def boss_need(team, boss, kb, label="BOSS") -> Need | None;  def choose_lead(team, opponent_party, kb, hp_now=None) -> int
# src/pokeagent/explorer/training.py: readiness_for(goals, party) L54, team_for(goals, party) L68, boss_need_for(goals, party) L82; module dict _cache keyed (kind, goal, tuple(party))
# src/pokeagent/knowledge/kb.py: table(kb, key); "name_of_internal" maps a species id string to its name; "moves" maps a move id string to a row with a name
```
`ram_map.json` marks `wEnemyMons` verified and `wEnemyMon1Moves` (0xD8AC, the first struct's +8) unverified: the move bytes are therefore best effort, validated below, and Claude's organic check confirms them.

### 1. party_view.py

`EnemyPartyMon` becomes: species, hp, max_hp, level, then `moves: tuple[int, int, int, int] = (0, 0, 0, 0)` and `status: int = 0` (defaults keep the four-argument constructor in `tests/test_party_view.py` valid). `_enemy_party` fills them from struct offsets +8..+11 and +4. No other behaviour change.

### 2. enemy_party.py (pure; takes a BattleView, never reads RAM)

```
@dataclass(frozen=True)
class FoeMon: level: int; species: str; hp: int; max_hp: int; moves: tuple[str, ...]; fainted: bool
@dataclass(frozen=True)
class EnemyParty: mons: tuple[FoeMon, ...]; pos: int       # pos = the party index of the mon currently out
def read_party(view, kb=None) -> tuple[EnemyParty | None, str]
    # (party, "ok") or (None, reason); reasons are exactly: "not a trainer fight", "count out of range", "species unknown", "level out of range",
    # "hp above max", "position out of range", "foe mismatch" (the mon out per view.enemy_mon does not match the species at pos)
def remaining(party: EnemyParty) -> list[tuple[int, str]]     # [(level, species)] of every mon not fainted, in party order, the one currently out included
def true_boss(party: EnemyParty) -> list[tuple[int, str, tuple[str, ...]]]   # the WHOLE party as (level, species, moves), for planning
```
Validity rules (each a separate reason, each tested): `view.kind == 2`; 1 <= count <= 6; every species id resolves through `table(kb, "name_of_internal")`; every level 1..100; every hp <= max_hp and max_hp > 0; `view.enemy_party_pos` is within count; the species at `pos` equals `view.enemy_mon.species`. Move ids resolve through `table(kb, "moves")`; an id of 0 or an unresolved id is dropped (so a stale move block yields an empty move tuple, and `boss_source` then keeps the learnset moves for that mon rather than treating it as "knows nothing").

### 3. boss_source.py (pure)

```
def boss_for(goal, starter_names, observed, kb=None) -> tuple[list, str, str]
    # (boss, source, reason). source is "ram" or "table".
```
`boss_party` today returns ONE party. `boss_for` first collects the ROM OPTIONS for the goal (for a gym or leader goal, the single `party_of`; for a rival goal, the three variants `party_of(cls, first + i)`; build this from `GYM_BOSSES`, `LEADER_BOSSES` and `RIVAL_BOSSES`, without changing those tables or `boss_party`). `observed` is the maps.json table `observed_parties` (goal -> a stored party, see item 6; None or missing means no observation). When the stored party's species multiset equals one option's species multiset, return the stored party as 3-tuples (level, species, moves) with `("ram", "observed party matches ROM option N")` (N = the variant index; a rival variant is thereby identified without our starter's name). When it matches no option, or there is no observation, return `boss_party(goal, kb, starter_names)` (2-tuples) with `("table", reason)` where reason is one of "no observation", "observation matches no ROM option". Levels in the stored party win over the ROM levels (same species, so a level difference is real); say so in the reason when they differ ("levels differ").

### 4. team_plan._theirs

Accept entries of length 2 or 3. For a 3-tuple whose move tuple is non-empty, build the `Combatant` as `trainer_mon(name, level, kb)` with `moves` replaced by the given names (`dataclasses.replace`); an empty move tuple keeps the learnset moves. 2-tuples behave exactly as today (pin with the existing tests).

### 5. training.py and plan_goal.py

`readiness_for`, `team_for` and `boss_need_for` each gain `observed: dict | None = None`; their boss lookup becomes `boss_for(goal, [c.name for c in party], observed)` (keeping the existing Mt Moon fallback `strongest_on_mt_moon()` for the goal `to_mt_moon`, which has no single boss). The `_cache` key must include the boss itself (`tuple(boss)`), so an observation that arrives mid-run replaces the cached verdict. `plan_goal.py` passes `ctx.mem.data.get("observed_parties")` at its three call sites (L63, L64, L76). Add no `global` statement.

### 6. battle_party.py (observer behaviour)

`BattleParty.applies`: `ctx.view.battling`, trainer fight (`ctx.bv` may be None on the first step: read the kind from `read_battle_view(ctx.emu)`), and the (battle id, enemy position) pair differs from the last one handled (keep that pair in `team_plan.of(ctx)`, which is a plain dict per run; do NOT add a field to `ExplorerContext`, `context.py` is at 300 lines). `step` always returns None. It: reads the view; calls `read_party`; on failure logs `[trainer party: RAM invalid (<reason>); planning keeps the ROM table]` once per battle; on success stores `team_plan.of(ctx)["foe_party"] = remaining(party)` and logs `[trainer party: RAM <n> mons <species L<level>, ...> (remaining <m>)]`. At the battle's first read only, when `ctx.stage_goal` has ROM options and the party's species multiset matches one, it stores `ctx.mem.data["observed_parties"][goal]` as a plain list of rows [level, species, [move names]] and logs `[trainer party: matches ROM option N for <goal>]` or, when levels differ, `... levels differ: ROM ... vs RAM ...`; when nothing matches it logs `[trainer party: matches no ROM option for <goal>]` and stores nothing. It also, report-only, calls `team_plan.choose_lead(our_party(emu), remaining as Combatants, None)` once at the battle's first read and logs `[trainer party: lead vs this party would be slot X (out: slot Y)]`; it never presses anything. `maps.json` gains a new top-level key; before writing it, confirm with `git grep -n "observed_parties"` that nothing else uses the name and write a test that `MapMemory` loads a file containing the key (see `tests/test_explorer_behaviours.py::test_map_memory_accepts_str_path`). Do not touch the swarm's merge code; report in the Report whether an unknown top-level key survives a merge (`git grep -n "def merge_file_into" -- tools`).

### Tests

- `tests/test_enemy_party.py`: a FakeEmulator memory dict (style of `tests/test_party_view.py` `mem(...)`; extend it with the struct's move bytes at struct+8..+11) with a 3-mon trainer party reads count, species, levels, move names and the current position; each of the seven reasons is produced by one corrupted input (count 0, an unknown species id, level 0 and 101, hp above max, position 3 of 3, a foe that does not match, a wild kind); `remaining` drops a fainted mon and keeps the one out; `true_boss` returns all three; a stale move block (all zero) gives empty move tuples.
- `tests/test_boss_source.py`: a gym goal with a matching observation returns source "ram" with the observed levels and moves; a rival goal with three ROM options and an observation matching variant 1 returns that variant (and without starter names, the table path returns the strongest, so the two differ); a mismatching observation returns "table" with the reason; a levels-differ observation says so; `_theirs` with a 3-tuple whose moves lack the species' best learnset move yields a lower `boss_need` than the 2-tuple (synthetic `SYN` tables from `tests/test_switch_matchup.py`); with an empty move tuple it equals the 2-tuple result; two calls to `boss_need_for` with different observations do not share a cache entry.
- `tests/test_battle_party.py`: the behaviour returns None on every step, logs the RAM-invalid reason once per battle, stores `observed_parties` only on a matching first read, logs the choose_lead line, and does nothing in a wild fight (kind 1) or outside battle.

## What NOT to do

- Do not change `trainers.boss_party`, `GYM_BOSSES`, `LEADER_BOSSES`, `RIVAL_BOSSES`, `choose_lead`'s signature or maths, `switch_choice`, `lead_order`, battle behaviour, catch logic or the PP guard. Do not edit `src/pokeagent/explorer/behaviours/battle.py` or `src/pokeagent/explorer/context.py` (both at the 300-line cap).
- Do not build a species book, learned-move tables, a counter planner or a battle simulator (`Opponent_Modeling_Directive.md` and `Battle_Simulator_Directive.md` own those).
- Do not trust RAM silently: any failed validity rule falls back to the ROM table and says why in the log; never raise out of the observer.
- Do not store an observation that matches no ROM option as a boss; a route trainer's party is not a boss party.
- Do not touch the swarm merge, `runs/`, `baselines/`, `roms/` or any save state. No emulator run, no window.

## Verification (exact commands)

```
uv run --frozen pytest -q tests/test_enemy_party.py tests/test_boss_source.py tests/test_battle_party.py
```
Expected: all pass.

```
uv run --frozen pytest -q tests/test_party_view.py tests/test_team_readiness.py tests/test_team_plan.py tests/test_switch_matchup.py tests/test_explorer_behaviours.py tests/test_layers.py
```
Expected: no new failures. Claude ran this exact command on origin/main 01b7fd6 while writing the directive: `91 passed, 1 warning in 1.83s`.

```
git diff --stat origin/main -- src/pokeagent
```
Expected: `party_view.py`, the two new knowledge modules, the new behaviour and its registration, `team_plan.py`, `training.py`, `plan_goal.py`.

## Completion criteria

- [ ] `read_party` returns the party, current position, levels and move names from synthetic bytes, and returns the exact reason string for each of the seven invalid cases. <!-- test: tests/test_enemy_party.py -->
- [ ] `boss_for` returns the observed party as "ram" when it matches a ROM option (identifying the rival variant), and the ROM table with a reason otherwise; observed levels win. <!-- test: tests/test_boss_source.py -->
- [ ] `_theirs` uses given moves for a 3-tuple and the learnset for a 2-tuple or an empty move tuple, and `boss_need_for` does not share a cache entry between different observations. <!-- test: tests/test_boss_source.py -->
- [ ] The observer behaviour never presses, logs RAM-invalid reasons once per battle, stores an observation only for a matching boss party, and ignores wild fights. <!-- test: tests/test_battle_party.py -->
- [ ] `MapMemory` loads a maps.json that contains `observed_parties`; `plan_goal.py` and `training.py` stay within 300 lines.
- [ ] The existing test files in the second verification command pass unchanged, and both size and layering tests stay green.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails, whether an unknown top-level maps.json key survives the swarm merge (the grep result), and the exact log line formats. Then the organic check Claude runs afterwards with the ROM (Devin cannot): fight Brock and one rival fight from real checkpoints (a swarm slot, not this worktree), read `runs/<run>/decisions.jsonl` for the `[trainer party: ...]` lines, confirm the species, levels and move bytes against the ROM trainers table and the battle text (wEnemyMon1Moves is unverified in `ram_map.json`), confirm `observed_parties` appears in that run's maps.json, and call `boss_for` for that goal against that run's maps.json (read-only) to confirm it returns source "ram". Only after that organic confirmation may the observed moves be trusted over the learnset.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command (`uv run python --version` prints `Python 3.12.12`); never bare `python`.
- Branch only (`directive/pokeagent-trainer-party-from-ram-directive`); commit as you go; never commit to or push main; never merge.
- Standing rule for synthetic data (Robert, 2026-11-07, verbatim): "We can use synthetic data and states and saves throughout, with a standing rule that a synthetic result must be verified by organic data and states and saves, as a proof system." Every test here is synthetic (FakeEmulator memory or plain tables); a green run is a claim. The Report names the organic confirmation Claude runs afterwards, and the code, comments and PR text never describe a synthetic pass as proof.
- No ROM data is committed (no ROM bytes, no extracted tables, no save states); tests never open a window or send input; no emulator runs.
- SOLID and KISS: every NEW module stays under 150 lines and does one job; an explorer file never passes 300 lines (`tests/test_explorer_behaviours.py::test_explorer_package_layering_and_size` enforces it, and its import allow-list: explorer code may import only the listed `pokeagent.*` layers, `knowledge`, `bandit`, `party_view`, `ramstructs`, `ram_symbols` among them); `tests/test_layers.py` forbids package code importing `tools`. No `global` statements in package code (cache with a dict or `functools.lru_cache`).
- Create no scratch or debug files; anything temporary goes under `.devin-scratch/`.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat and test tails in the Report.

## Forbidden Actions

- ROMs, extracted game art, save states and anything derived from them are local and gitignored. Never commit them or add one as a fixture.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor.
- Do not read or write anything under `runs/` (a swarm is running), `baselines/` or `roms/`; do not open a window or send input.
- Do not commit to or push main, merge, or deploy.

## Required from User

- The organic check named in the Report section, run by Claude with the ROM after the verify lane passes (a swarm is running; Claude schedules it). Nothing here blocks the run.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(git diff)
- Exec(git grep)
