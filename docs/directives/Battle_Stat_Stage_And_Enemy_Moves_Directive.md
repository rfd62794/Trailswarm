# PokeAgent: Battle stat stages and the foe's real moves - scale move scores and switch decisions by stat stages, and score a foe by the moves RAM says it knows

**Depends on `Lead_And_Wild_Switch_Directive.md` merged** (its fix round is running: it adds `can_damage`, `lead_order`, `TRAINEE_SAFE_HP` and the `wild` keyword of `switch_choice` in `src/pokeagent/knowledge/team_plan.py`, and moves its new helpers out of `team_plan.py` and `src/pokeagent/explorer/behaviours/battle.py` into small modules). If `git grep -n "TRAINEE_SAFE_HP" -- src/pokeagent` finds nothing at the start of the run, stop and write that in the Status row; do not recreate those functions. Base: a main that contains that directive. **Coordinate with** `Battle_Status_Conditions_Directive.md` (it depends on this one: it fills the `status` and `confused` fields of the `SideState` record this directive defines) and with `Battle_Simulator_Directive.md` and `Opponent_Modeling_Directive.md` (queued, not started): see "What NOT to do".

## Why this exists

Robert wants the Agent to read more of the battle than it does. Claude ran a read-only perception inventory on 2026-11-14: about 60 RAM addresses are read at runtime (`src/pokeagent/ram_symbols.py` 34, `ramworld.py` 9, `ramstructs.py` about 6, `ram.py` 7) out of 2,792 pret symbols in `src/pokeagent/data/ram_map.json`. Two decoded families are never used in a decision:

- **Stat stages.** `PLAYER_STAT_MODS = 0xCD1A` and `ENEMY_STAT_MODS = 0xCD2E` (`src/pokeagent/ramstructs.py:15-16`) are decoded into `BattleMon.stat_mods` (raw bytes 1..13, 7 = no change; `ramstructs.py:80`; `mod_stages()` at L82-84 gives -6..+6) by `read_battle_mon` (L150) and `read_enemy_mon` (L154). `git grep -n "stat_mods\|mod_stages\|STAT_MODS" -- src tools` finds them only in `ramstructs.py`. So a foe that used SWORDS DANCE (+2 attack), or a lead hit by GROWL three times, changes nothing: `move_scores` (`src/pokeagent/explorer/battle.py:135`) scores a move as power x type effectiveness x STAB x accuracy and ignores stages; `_score_ctx` (L121-132) estimates `fast_ko` from `me.stats` and `foe.stats` with no stages; and `team_plan.switch_choice` (`src/pokeagent/knowledge/team_plan.py:219`) never asks whether the active member is crippled or the foe is boosted.
- **The foe's known moves and PP.** `read_battle_view(emu).enemy_mon` (`src/pokeagent/party_view.py:92-101`, `EnemyMonView.moves` and `.pp`, from wEnemyMonMoves 0xCFED and wEnemyMonPP 0xCFFE, both marked verified in `ram_map.json`) is used by nobody when choosing a switch. The matchup switch builds its foe in `src/pokeagent/explorer/behaviours/switch_out.py:53-58` (`_foe`): `trainer_mon(name, level)` from `src/pokeagent/knowledge/party.py`, whose moves are the LEARNSET-legal moves at that level (`moves_at`), not the moves the foe actually has. The brief called the alternative "the observed-threat ledger"; Claude checked: that ledger (`threat_by_species`; `src/pokeagent/explorer/battle.py` `record_threat` L220, `threat_score` L206) feeds only the flee and potion logic in `src/pokeagent/explorer/behaviours/battle.py`, never `switch_choice`. So the real gap is that switch scoring assumes the foe has its best learnset move whether or not it has it, and ignores its PP.

Gen 1 facts this directive relies on (pokered; UNVERIFIED until Claude's organic check, so keep each in ONE named constant or helper and a correction is one edit): a stage multiplies the stat by 25/100, 28/100, 33/100, 40/100, 50/100, 66/100 at stages -6..-1, by 1 at 0, and by 150/100, 200/100, 250/100, 300/100, 350/100, 400/100 at +1..+6, floored, minimum 1, maximum 999; physical moves use Attack against Defense and special moves use Special against Special (the physical type list is `PHYSICAL` in `src/pokeagent/knowledge/damage.py`); a stage resets when a mon is switched out (the incoming mon starts at 0); critical hits ignore stages (the repo's damage average folds crits in as a small bonus, `damage.CRIT_RATE`; leave that alone).

A trap to design around: the live battle struct's stat words (`wBattleMonAttack` 0xD025, `wEnemyMonAttack` 0xCFF6) may ALREADY include the stage multiplier, because the cartridge keeps unmodified copies in `wPlayerMonUnmodifiedAttack` 0xCD12 (then Defense 0xCD14, Speed 0xCD16, Special 0xCD18, two bytes each, big-endian) and `wEnemyMonUnmodifiedAttack` 0xCD26 (Defense 0xCD28, Speed 0xCD2A, Special 0xCD2C); `ram_map.json` lists the unmodified symbols with `verified: false`. Applying a stage on top of an already-staged stat would count it twice. So this directive never multiplies `BattleMon.stats`: it multiplies the UNMODIFIED block, and falls back to the battle struct's stats with NO stage applied when the unmodified block reads all zero (and says so in the decision note). Claude settles which struct holds what in the organic check.

## Scope (in this order)

1. `src/pokeagent/knowledge/stat_stages.py` <!-- new: src/pokeagent/knowledge/stat_stages.py --> - pure stage maths. Under 100 lines.
2. `src/pokeagent/knowledge/battle_state.py` <!-- new: src/pokeagent/knowledge/battle_state.py --> - the `SideState` record and its decoder from a `BattleMon`. Under 60 lines.
3. `src/pokeagent/knowledge/foe_moves.py` <!-- new: src/pokeagent/knowledge/foe_moves.py --> - a foe `Combatant` built from RAM moves and PP. Under 100 lines.
4. `src/pokeagent/knowledge/switch_pressure.py` <!-- new: src/pokeagent/knowledge/switch_pressure.py --> - the stage-based switch reasons and staged damage for `switch_choice`. Under 120 lines.
5. `src/pokeagent/ram_symbols.py` and `src/pokeagent/ramstructs.py` - the two unmodified-stat base addresses as named constants, and `read_unmodified_stats(emu, side)`.
6. `src/pokeagent/knowledge/team_plan.py` - `switch_choice` takes the new keywords and delegates to scope item 4 (net growth under 15 lines).
7. `src/pokeagent/explorer/battle.py` - `move_scores` and `_score_ctx` use the stage ratio.
8. `src/pokeagent/explorer/behaviours/switch_out.py` - `_foe` uses scope item 3 and `_matchup_pick` passes the two `SideState` values (net growth under 20 lines).
9. Tests: `tests/test_stat_stages.py`, `tests/test_foe_moves.py`, `tests/test_stage_switch.py`, `tests/test_move_scores_stages.py` <!-- new: tests/test_stat_stages.py --> <!-- new: tests/test_foe_moves.py --> <!-- new: tests/test_stage_switch.py --> <!-- new: tests/test_move_scores_stages.py -->.

## The work

Existing signatures, pasted because the worktree cannot be searched (Claude read them on origin/main 01b7fd6):

```
# src/pokeagent/ramstructs.py
PLAYER_STAT_MODS = 0xCD1A; ENEMY_STAT_MODS = 0xCD2E       # 6 bytes each: atk, def, spd, spc, acc, eva (raw 7 = unmodified)
class BattleMon: species, hp, party_pos, status, type1, type2, moves (4 ids), dv_word, level, max_hp,
                 stats (atk, def, spd, spc), pp (4 raw bytes; low 6 bits = PP), stat_mods (6 raw bytes); mod_stages() -> raw - 7 per entry
def decode_battle_mon(raw: bytes, stat_mods: bytes = b"") -> BattleMon   # pure on bytes
def read_battle_mon(emu) -> BattleMon; def read_enemy_mon(emu) -> BattleMon
# src/pokeagent/party_view.py
@dataclass(frozen=True) class EnemyMonView: species, hp, max_hp, level, status, moves (4 ids), pp (4 bytes)
read_battle_view(emu).enemy_mon -> EnemyMonView | None
# src/pokeagent/knowledge/party.py
Combatant(name, level, types, hp, stats, moves, dv, sexp)   # hp is MAX hp; moves are NAMES
trainer_mon(name, level, kb=None) -> Combatant | None
# src/pokeagent/knowledge/kb.py: table(kb, key) -> dict ({} when absent); keys used: "moves" (id string -> row with name, type, power, accuracy, effect, pp), "name_of_internal" (id string -> species name)
# src/pokeagent/knowledge/readiness.py
def best_move(att, dfn, chart, moves) -> tuple[float, str]     # (expected damage per turn, move name); (0.0, "") when nothing damages
# src/pokeagent/knowledge/damage.py
def expected_damage(level, power, atk, dfn, *, stab, eff) -> float
# src/pokeagent/knowledge/team_plan.py (before the in-flight directive; its fix round adds wild= and trainee safety)
def switch_choice(team, active_slot, opponent, kb, *, hp_now=None, switches=0, trainee=None) -> int | None
# src/pokeagent/explorer/battle.py
def _score_ctx(emu, rows, chart, defs, mine, catching) -> ScoreCtx
def move_scores(emu, catching=False) -> dict[str, tuple[float, str]]    # MOVE NAME -> (score, rule string)
```
Synthetic style to copy: `tests/test_party_view.py` `mem(...)` builds a FakeEmulator memory dict (`from pokeagent.emulator import FakeEmulator`) with the party and battle blocks at their real addresses; `tests/test_switch_matchup.py` has the `SYN` knowledge-base tables and the `_mon` Combatant helper. Add the stat-mod bytes at 0xCD1A..0xCD1F and 0xCD2E..0xCD33, the unmodified blocks at 0xCD12 and 0xCD26, the foe's moves at 0xCFED and its PP at 0xCFFE.

### 1. stat_stages.py (pure)

```
RATIO = ((25, 100), (28, 100), (33, 100), (40, 100), (50, 100), (66, 100), (1, 1), (150, 100), (200, 100), (250, 100), (300, 100), (350, 100), (400, 100))   # index = stage + 6
STAT_MAX = 999
SWITCH_OWN_STAGE = -2        # switch pressure when our attacking stat is at or below this stage (untuned)
SWITCH_FOE_STAGE = 2         # ... or the foe's attacking stat is at or above this stage (untuned)
RATIO_CLAMP = (0.25, 4.0)    # bound on a move-score ratio
def stage_of(raw: int) -> int                 # raw 1..13 -> -6..+6; 0 or out of range (a stale read) -> 0, never an exception
def stage_mult(stage: int) -> float           # RATIO as a float; stage clamped to -6..+6
def staged(stat: int, stage: int) -> int      # floor(stat * ratio), min 1, max STAT_MAX
def attack_index(move_type: str) -> int       # 0 (Attack) for a PHYSICAL type, 3 (Special) otherwise
def defence_index(move_type: str) -> int      # 1 (Defense) for PHYSICAL, 3 (Special) otherwise
def move_ratio(move_type: str, own: tuple, foe: tuple) -> float
    # stage_mult(own[attack_index]) / stage_mult(foe[defence_index]), clamped to RATIO_CLAMP; own and foe are 6-tuples of stages, an empty tuple reads as all zero
```

### 2. battle_state.py

```
@dataclass(frozen=True)
class SideState:
    stages: tuple[int, ...] = (0, 0, 0, 0, 0, 0)   # atk, def, spd, spc, acc, eva as -6..+6
    status: int = 0          # the raw status byte; read by Battle_Status_Conditions, unused here
    confused: bool = False   # filled by Battle_Status_Conditions, unused here
def side_state(bm: BattleMon | None) -> SideState     # None (a stale block) -> SideState(); stage_of per raw byte
```

### 3. foe_moves.py

`foe_combatant(view: EnemyMonView | None, kb=None) -> tuple[Combatant | None, str]`: the foe at its CURRENT hp for the matchup maths (as `_foe` does today: `replace(foe, hp=max(1, view.hp))`), but with `moves` = the names of the RAM move ids whose PP (low 6 bits of the byte) is above 0, resolved through `table(kb, "moves")`; the second return value is the source tag `"ram"`. When no move resolves (all ids zero or unknown, a stale read) fall back to `trainer_mon`'s learnset moves and return `"learnset"`. A species name that does not resolve returns `(None, "none")`, exactly the case where `_foe` returns None today. Never read RAM here (the caller passes the view); never guess a move id.

### 4. switch_pressure.py

```
def stage_pressure(active, foe, own_state, foe_state, chart, moves) -> str | None
```
Returns a reason string when the stage state alone makes the active member "thin", else None: "own attack -2" when the stage of the active member's attacking stat for its best move (best_move name, then its type via `moves`) is at or below `SWITCH_OWN_STAGE`; "foe attack +2" when the foe's attacking-stat stage for ITS best move against the active member is at or above `SWITCH_FOE_STAGE`. A member with no damaging move (`best_move` returns 0.0) has no attacking stat to lower: only the foe test applies.
`staged_hit(att, dfn, att_stages, dfn_stages, chart, moves) -> float` is `best_move`'s expected damage multiplied by `move_ratio(type of the chosen move, att_stages, dfn_stages)`; a candidate is scored with its own stages at zero (the incoming mon is fresh) and the foe's real stages kept.

### 5. team_plan.switch_choice

New keywords `own: SideState | None = None` and `foe_state: SideState | None = None` (both None leaves every existing call and test unchanged). After the existing thin tests add `or stage_pressure(...)` as one more thin reason, so the in-flight directive's wild mode, the 2-per-battle cap, the incoming-survives check and trainee safety all still apply to the switch it then picks. Damage comparisons use `staged_hit`: the active member with `own.stages`, the foe with `foe_state.stages`, each candidate with ZERO own stages. The return type and the never-switch-the-trainee-IN rule are unchanged.

### 6. move_scores and _score_ctx (src/pokeagent/explorer/battle.py)

Read both `SideState` values once per call (`side_state(read_battle_mon(emu))`, `side_state(read_enemy_mon(emu))`). In `move_scores`, multiply each damaging move's `base` by `move_ratio(mv["type"], own.stages, foe.stages)` before `adjust`, and append a note such as "[stages x1.50]" (two decimals, only when the ratio differs from 1.0). Status and zero-power moves are untouched. In `_score_ctx`, the `fast_ko` estimate uses `staged(unmodified stat, stage)` from `read_unmodified_stats` for both sides; when the unmodified block is all zero it uses `me.stats` and `foe.stats` as today with no stage. Return the same `ScoreCtx`.

`read_unmodified_stats(emu, side) -> tuple[int, int, int, int]` (attack, defense, speed, special; `side` is "player" or "enemy"; big-endian words) goes in `ramstructs.py` with the two base addresses named in `ram_symbols.py`; comment that the layout is from pret and unverified.

### 7. switch_out wiring

`_foe` returns the Combatant from `foe_combatant(read_battle_view(ctx.emu).enemy_mon)`; `_matchup_pick` passes `own=side_state(read_battle_mon(ctx.emu))` and `foe_state=side_state(read_enemy_mon(ctx.emu))` to `switch_choice`, and the pick's `why` string gains the stage reason and the foe-move source ("foe moves: ram" or "foe moves: learnset") so the decision log shows which it used. Keep the Combatant-at-current-HP behaviour exactly.

### Tests

- `test_stat_stages.py`: `stage_mult` at -6, -2, 0, +1, +2, +6 gives 0.25, 0.5, 1.0, 1.5, 2.0, 4.0; `staged(100, -1)` is 66, `staged(100, 6)` is 400, `staged(300, 6)` is 999 (cap), `staged(1, -6)` is 1 (floor); `stage_of(0)` and `stage_of(14)` are 0; `move_ratio` for a special type with our Special at +2 and the foe's at -2 clamps at 4.0; a physical type reads Attack and Defense, a special type Special and Special.
- `test_foe_moves.py`: RAM moves [FIRE BLAST id, 0, 0, 0] with PP 5 give a foe whose best move is FIRE BLAST and source "ram"; the same move at PP 0 is dropped; all-zero move bytes fall back to the learnset with source "learnset"; the foe's HP is its current HP. Build the view with `read_battle_view` over a FakeEmulator memory dict (synthetic bytes).
- `test_stage_switch.py`: an active member at attack -2 with a physical best move switches to a healthy damaging member while the same position at -1 does not; a foe at +2 in its attacking stat switches, +1 does not; the chosen candidate is scored at zero own stages; both keywords None gives the old answer; the 2-per-battle cap and never-the-trainee-IN still hold; a foe whose RAM moves are all status moves is not a switch reason.
- `test_move_scores_stages.py`: a FakeEmulator battle with stage bytes: our attack +2 doubles a physical move's score and leaves a status move's score alone; the foe's defence at +2 halves it; all stage bytes at 7 changes nothing from today's scores (pin the numbers the existing code gives); an all-zero unmodified block makes `_score_ctx` fall back to the battle-struct stats with no stage.

## What NOT to do

- Do not change `ascending_order`, `lead_order`, `trainee_slot`, catch logic, `battle_moves.py` or the PP guard (the in-flight `PP_Zero_Move_Guard_Directive.md` owns it), `SWITCH_GAIN`, `SWITCH_HP_TURNS`, `WEAK_RATIO`, `SWITCH_MIN_HP`, `MAX_SWITCHES_PER_BATTLE` or `TRAINEE_SAFE_HP`.
- Do not build a species book, a per-species learned-move table or a counter planner (`Opponent_Modeling_Directive.md` owns observation and counters; its counter planner should later call `foe_combatant`, so keep that signature stable). Do not create anything under `src/pokeagent/sim/` or a turn engine (`Battle_Simulator_Directive.md` owns that; it may reuse `stat_stages.RATIO`, so do not duplicate the table anywhere else).
- Do not multiply `BattleMon.stats` by a stage anywhere (see the trap above). Do not model status conditions or confusion (`Battle_Status_Conditions_Directive.md`); leave `SideState.status` and `.confused` unread.
- Do not retune any constant; the two stage thresholds are named and untuned, and Claude tunes them from organic evidence.
- No emulator run, no ROM, no window. Tests build bytes in FakeEmulator memory or plain tables.

## Verification (exact commands)

```
uv run --frozen pytest -q tests/test_stat_stages.py tests/test_foe_moves.py tests/test_stage_switch.py tests/test_move_scores_stages.py
```
Expected: all pass.

```
uv run --frozen pytest -q tests/test_switch_matchup.py tests/test_party_view.py tests/test_battle_mon_gating.py tests/test_battle_types.py tests/test_knowledge.py tests/test_explorer_behaviours.py tests/test_layers.py
```
Expected: no new failures. Claude ran this exact command on origin/main 01b7fd6 while writing the directive: `104 passed, 2 skipped, 1 warning in 2.18s`.

```
git diff --stat origin/main -- src/pokeagent
```
Expected: the four new modules, `ram_symbols.py`, `ramstructs.py`, `team_plan.py`, `src/pokeagent/explorer/battle.py`, `switch_out.py`.

## Completion criteria

- [ ] `stage_mult`, `staged`, `stage_of` and `move_ratio` match the table above, including the 999 cap, the minimum 1 and a stale raw byte reading as stage 0. <!-- test: tests/test_stat_stages.py -->
- [ ] `foe_combatant` uses the RAM moves with PP above 0 and reports "ram"; with no usable RAM move it falls back to the learnset and reports "learnset". <!-- test: tests/test_foe_moves.py -->
- [ ] `switch_choice` treats our attacking stat at or below -2, or the foe's at or above +2, as a thin reason, scores candidates at zero own stages, and is unchanged when both new keywords are None. <!-- test: tests/test_stage_switch.py -->
- [ ] `move_scores` multiplies damaging moves by the stage ratio, leaves status moves alone, and at all-7 stage bytes returns today's numbers; `_score_ctx` never applies a stage to the battle struct's own stats. <!-- test: tests/test_move_scores_stages.py -->
- [ ] The existing test files in the second verification command pass unchanged, and both size and layering tests stay green.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails, the new constants and values (`SWITCH_OWN_STAGE`, `SWITCH_FOE_STAGE`, `RATIO_CLAMP`). Then the organic check Claude runs afterwards with the ROM (Devin cannot): in a real wild or trainer fight where a stat-changing move lands (a GROWL or LEER on us, a boost on the foe), read `runs/<run>/decisions.jsonl` for the stage note and the foe-move source in the rule strings, confirm `BattleMon.mod_stages()` matches what the battle text said, and compare 0xD025 and 0xCFF6 against the 0xCD12 and 0xCD26 blocks to settle whether the battle struct is already staged. If it is, the fallback path is the one the Agent has been on and the fix is one line in `_score_ctx`.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command (`uv run python --version` prints `Python 3.12.12`); never bare `python`.
- Branch only (`directive/pokeagent-battle-stat-stage-and-enemy-moves-directive`); commit as you go; never commit to or push main; never merge.
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
