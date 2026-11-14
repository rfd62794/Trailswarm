# PokeAgent: Battle status conditions - model sleep, paralysis, burn, poison, freeze and confusion (the foe's and our own) in move scores and in the switch decision

**Depends on `Battle_Stat_Stage_And_Enemy_Moves_Directive.md` merged AND `Lead_And_Wild_Switch_Directive.md` merged.** The first defines the `SideState` record (`src/pokeagent/knowledge/battle_state.py` <!-- new: src/pokeagent/knowledge/battle_state.py -->, with unread `status` and `confused` fields) and the `own=` / `foe_state=` keywords of `team_plan.switch_choice`, and rewrites `_score_ctx` / `move_scores` in `src/pokeagent/explorer/battle.py` and `_foe` / `_matchup_pick` in `src/pokeagent/explorer/behaviours/switch_out.py`; this directive fills those fields and edits the same functions, so it must start from a main that contains it. The second adds the wild mode and trainee safety of `switch_choice`. If `git grep -n "class SideState" -- src/pokeagent/knowledge/battle_state.py` or `git grep -n "TRAINEE_SAFE_HP" -- src/pokeagent` finds nothing at the start of the run, stop and write that in the Status row; do not recreate those definitions. Base: a main that contains both. **Coordinate with** `Battle_Simulator_Directive.md` (queued, not started; it models the same six conditions inside a turn engine; its engine should later reuse `status_model.decode` rather than re-derive the byte layout).

## Why this exists

Robert's perception inventory (2026-11-14): enemy status is read only as a coarse flag. `_score_ctx` (`src/pokeagent/explorer/battle.py:121-132`) passes `enemy_status=foe.status` (the raw byte, `BattleMon.status` = struct byte 4, `src/pokeagent/ramstructs.py:91`; the player's own copy sits in the same struct) into `ScoreCtx` (`src/pokeagent/knowledge/scoring.py:28-35`), and the only uses are in `scoring.py`: `_status_value` (L37-43) returns 0 for ANY status move when the byte is non-zero (or `fast_ko`), and the DREAM EATER line (L64) tests the sleep bits. Nothing models what a condition DOES. Concretely:

- **Setup moves are worth nothing.** `adjust` (L45-) returns `(0.0, "")` for every effect kind `setup` (our own stat up: SWORDS DANCE, AGILITY, HARDEN ...), so the Agent never boosts, even against a foe that is asleep and cannot punish the turn.
- **Our own status is invisible.** A paralysed, confused, burned, asleep or poisoned active member scores its moves and its switch exactly as a healthy one. `team_plan.switch_choice` (`src/pokeagent/knowledge/team_plan.py:219`) compares best-move damage and HP only. A sleeping lead is not even recognised as unable to act.
- **Confusion is not modelled anywhere.** `git grep -n "0xD062\|0xD067\|BATTLE_STATUS" -- src tools` finds nothing: the volatile flags are never read. In the cartridge's layout (pokered, UNVERIFIED here) confusion is a bit of `wPlayerBattleStatus1` (0xD062) / `wEnemyBattleStatus1` (0xD067), not of the status byte; `ram_map.json` lists both symbols (and the confusion counters `wPlayerConfusedCounter` 0xD06B, `wEnemyConfusedCounter` 0xD070) with `verified: false`.
- **A confuse move on a confused foe** is scored as if it could land, because `enemy_status` cannot see confusion.

The status byte layout the repo already uses (do not redefine it; import it): `src/pokeagent/knowledge/catch_math.py:23`, `SLP_MASK, PSN_BIT, BRN_BIT, FRZ_BIT, PAR_BIT = 0x07, 0x08, 0x10, 0x20, 0x40` (sleep is a counter in the low three bits, the rest are single bits; the comment there marks it "unverified: from memory of pokered"), and `src/pokeagent/explorer/status_care.py:61-71` `status_kinds(byte)` decodes all of them but lives in the explorer layer, so the knowledge layer cannot import it. The same byte is the party struct's status (`PartyMon.status`, `ramstructs.py:34`) and the battle struct's.

Gen 1 effects this directive models (pokered; UNVERIFIED until Claude's organic check, so every number below is ONE named constant in `status_model.py`): a sleeping or frozen mon cannot act (a freeze has no natural thaw); a paralysed mon is fully paralysed about 25 percent of its turns (63 in 256) and its Speed is quartered (this directive does not model Speed); a confused mon hurts itself instead of acting about 50 percent of its turns, and confusion ends when the mon is switched out (the incoming mon is not confused; the status byte of the outgoing mon stays); a burn halves the burned mon's physical damage (the cartridge applies it to the live battle stat, not to the unmodified copy; see the stat-stage directive's trap note) and burn or poison removes about 1/16 of max HP each turn in battle.

## Scope (in this order)

1. `src/pokeagent/knowledge/status_model.py` <!-- new: src/pokeagent/knowledge/status_model.py --> - the pure model. Under 130 lines.
2. `src/pokeagent/knowledge/switch_status.py` <!-- new: src/pokeagent/knowledge/switch_status.py --> - the switch-side adjustments `switch_choice` calls. Under 100 lines.
3. `src/pokeagent/ram_symbols.py` and `src/pokeagent/ramstructs.py` - the two battle-status addresses as named constants and `read_battle_status1(emu, side)`.
4. `src/pokeagent/knowledge/battle_state.py` <!-- new: src/pokeagent/knowledge/battle_state.py --> - `side_state` fills `status` and `confused`.
5. `src/pokeagent/knowledge/scoring.py` - `ScoreCtx` and `adjust` (setup value, confusion, own attack factor).
6. `src/pokeagent/explorer/battle.py` - `_score_ctx` and `move_scores` pass the two `SideState` values and apply the factors.
7. `src/pokeagent/knowledge/team_plan.py` - `switch_choice` calls `switch_status` (net growth under 15 lines).
8. `src/pokeagent/explorer/behaviours/switch_out.py` - `_matchup_pick` builds the `SideState` values with status and confusion (net growth under 10 lines).
9. Tests: `tests/test_status_model.py`, `tests/test_status_scores.py`, `tests/test_status_switch.py` <!-- new: tests/test_status_model.py --> <!-- new: tests/test_status_scores.py --> <!-- new: tests/test_status_switch.py -->.

## The work

Existing signatures, pasted (the worktree cannot be searched; `uv run python --version` prints `Python 3.12.12`):

```
# src/pokeagent/knowledge/catch_math.py
SLP_MASK, PSN_BIT, BRN_BIT, FRZ_BIT, PAR_BIT = 0x07, 0x08, 0x10, 0x20, 0x40
def status_kind(byte) -> str | None      # one of sleep, freeze, burn, poison, paralyse (first match), or None
# src/pokeagent/knowledge/scoring.py
@dataclass(frozen=True) class ScoreCtx: level=0, hp_frac=1.0, enemy_hp=0, enemy_status=0 (raw byte), catching=False, fast_ko=False
def adjust(move: dict, base: float, eff: float, acc: float, c: ScoreCtx) -> tuple[float, str]     # (score, note)
FIGHT_STATUS = sleep 8.0, paralyse 6.0 (the value of an inflicting move in a normal fight); CATCH_STATUS = sleep 70, paralyse 55, poison 25, confuse 15 (while catching)
# src/pokeagent/knowledge/moves.py
@dataclass(frozen=True) class Effect: kind (damage | status | stat | setup | special), target (self | foe), stat, stages (+ own, - foe), status (poison burn paralyse sleep freeze confuse flinch leech-seed), ...
def effect_of(move: dict) -> Effect | None
# src/pokeagent/knowledge/battle_state.py (added by the stat-stage directive)
@dataclass(frozen=True) class SideState: stages: tuple = (0,)*6; status: int = 0; confused: bool = False
def side_state(bm: BattleMon | None) -> SideState
# src/pokeagent/knowledge/team_plan.py (with the stat-stage and wild-switch directives merged)
def switch_choice(team, active_slot, opponent, kb, *, hp_now=None, switches=0, trainee=None, wild=False, own=None, foe_state=None) -> int | None
SWITCH_HP_TURNS = 2; WEAK_RATIO = 0.5; SWITCH_MIN_HP = 0.25; SWITCH_GAIN = 1.5; MAX_SWITCHES_PER_BATTLE = 2
```
Synthetic style: `tests/test_party_view.py` `mem(...)` (a FakeEmulator memory dict with the party and battle blocks at real addresses; `from pokeagent.emulator import FakeEmulator`) and `tests/test_switch_matchup.py` (`SYN` tables, `_mon`). Status bytes in tests: 0x04 (asleep, counter 4), 0x08 poison, 0x10 burn, 0x20 freeze, 0x40 paralysis, and 0x80 in the battle-status1 byte for confusion.

### 1. status_model.py (pure)

```
@dataclass(frozen=True)
class Condition:
    sleep: int = 0            # the counter, 0 = awake
    poison: bool = False; burn: bool = False; freeze: bool = False; paralysis: bool = False
    confused: bool = False
def decode(status_byte: int, confused: bool = False) -> Condition      # imports the masks from knowledge.catch_math; never redefines them
def can_act_share(c: Condition) -> float
    # the expected share of its turns the mon actually acts: 0.0 asleep or frozen; else (1 - PARA_SKIP) if paralysed, times (1 - CONFUSE_SELF_HIT) if confused
def attack_factor(c: Condition, move_type: str) -> float
    # can_act_share, times BURN_ATTACK (0.5) when burned and the move type is in knowledge.damage.PHYSICAL
def residual(c: Condition, max_hp: int) -> int          # poison or burn: max(1, max_hp // RESIDUAL_DIV) per turn, else 0
def foe_blocked(c: Condition) -> bool                    # asleep or frozen: the foe cannot hit back this turn
PARA_SKIP = 0.25; CONFUSE_SELF_HIT = 0.5; BURN_ATTACK = 0.5; RESIDUAL_DIV = 16      # named, untuned, UNVERIFIED
SETUP_SAFE_VALUE = 10.0          # score of an own-stat-up move while the foe is blocked and we are not about to win or lose (a damaging move still wins)
SETUP_PARA_SHARE = 0.5           # the same value times this when the foe is only paralysed
```

### 2. Move scores (scoring.py and src/pokeagent/explorer/battle.py)

- `ScoreCtx` gains `foe_blocked: bool = False`, `foe_para: bool = False`, `foe_confused: bool = False` and `own_factor: float = 1.0` (all defaulted, so every existing construction is unchanged).
- `_score_ctx` fills them from `decode(foe.status, foe_confused)` and `decode(me.status, own_confused)` (the confusion flag from `read_battle_status1`; the raw `enemy_status` field stays as it is). `fast_ko` uses `best * own_factor`.
- `adjust`: (a) an effect of kind `setup` whose `stages` is above 0 returns `SETUP_SAFE_VALUE` (times `SETUP_PARA_SHARE` when only `foe_para`), note "foe cannot act", ONLY when `foe_blocked` or `foe_para`, `hp_frac >= 0.5` and not `fast_ko`; otherwise the old `(0.0, "")`. (b) an inflicting move whose effect `status` is "confuse" returns `(0.0, "foe already confused")` when `foe_confused`. (c) the existing "foe already has a status" zero stays exactly as it is for the other conditions. (d) the DREAM EATER line is unchanged.
- `move_scores`: multiply each damaging move's `base` by `attack_factor(own condition, move type)` (so a burned member's physical moves read at half, a confused or paralysed member's at their expected share, a sleeping member's at 0.0 with the note "own asleep"), append a note when the factor is not 1.0. Status and zero-power moves are not scaled by it.

### 3. Switch scoring (switch_status.py and team_plan.switch_choice)

`switch_status` exposes pure helpers that `switch_choice` calls with `own` and `foe_state` (the `SideState` values; None keeps today's behaviour exactly):
- `own_damage_factor(own_state, move_type) -> float`: `attack_factor(decode(own.status, own.confused), move_type)`. In `switch_choice`, the active member's `our_dmg` is multiplied by it BEFORE the thin tests and the `SWITCH_GAIN` comparison, so a sleeping or frozen active member reads as `our_dmg == 0` (which the wild mode of `switch_choice` already treats as thin), and a paralysed, confused or burned one needs a smaller gain from a candidate to be replaced. Candidates are scored with a factor of 1.0 (the incoming mon is fresh: its own status byte is read from `team` only if the caller supplied it; this directive does not read the party's status bytes for candidates beyond skipping a candidate that is asleep or frozen, see next).
- `candidate_ok(status_byte) -> bool`: False for a candidate that is asleep or frozen (it would waste the turn; it still counts as healthy for `SWITCH_MIN_HP`). The caller passes the party members' status bytes (`hp_now`'s sibling `status_now`, a new optional keyword defaulting to None = no filtering).
- `residual_hp(own_state, max_hp) -> int`: `residual(decode(...), max_hp)`; `switch_choice` adds it to the foe's expected hit in the HP-danger test (`foe best hit + residual` over `SWITCH_HP_TURNS` turns against current HP).
- `foe_hit_factor(foe_state) -> float`: 0.0 when `foe_blocked` (a sleeping or frozen foe cannot hit this turn, so staying in is right: the HP-danger test does not fire), else the foe's `can_act_share` (a paralysed foe's expected hit shrinks).
Do not let a sleeping foe suppress the safety rules of the wild-switch directive that do not depend on the foe's hit (an active member that cannot damage at all, the trainee-safety HP rule).

### 4. Reading confusion

`read_battle_status1(emu, side) -> int` in `ramstructs.py` ("player" 0xD062, "enemy" 0xD067), constants named in `ram_symbols.py`, with a comment that the confusion flag is bit 7 and the layout is from pret and unverified. `side_state(bm, battle_status1=0)` sets `status=bm.status` and `confused=bool(battle_status1 & 0x80)`; `_matchup_pick` and `_score_ctx` pass the byte. A stale read (`bm` None) gives `SideState()` as before.

### Tests

- `tests/test_status_model.py`: `decode` of each byte above; sleep counter 4 reads `sleep == 4`; a poisoned and burned byte combination is decoded without exception (the cartridge never sets two majors, but the decoder must not assume); `can_act_share` is 0.0 asleep and frozen, 0.75 paralysed, 0.5 confused, 0.375 paralysed and confused; `attack_factor` is 0.5 for a burned physical move and 1.0 for a burned special move; `residual` is `max_hp // 16` with a floor of 1; `foe_blocked`.
- `tests/test_status_scores.py`: `adjust` on a SWORDS DANCE-style setup effect returns the safe value against a sleeping foe, half of it against a paralysed foe, and 0.0 against an awake foe, at low HP, and when `fast_ko`; a damaging move of power 40 still outscores the setup value; a confuse move scores 0.0 against a confused foe and normally otherwise; `move_scores` over a FakeEmulator battle: a burned attacker's physical move scores half of an unburned one, a special move is unchanged, an asleep attacker's damaging moves score 0.0; with all status bytes 0 and no confusion bit the scores equal today's numbers (pin them).
- `tests/test_status_switch.py`: a sleeping active member in a trainer fight switches to a healthy damaging member (and does not switch into a sleeping candidate); a paralysed, confused or burned-physical active member switches where the same healthy member would not (choose numbers so the healthy member stays in); a poisoned active member's residual tips the HP-danger test; a sleeping or frozen foe suppresses the HP-danger switch but not the cannot-damage or trainee-safety switch; `own` and `foe_state` None give the old answers; the 2-per-battle cap and never-the-trainee-IN still hold.

## What NOT to do

- Do not redefine the status byte masks (import from `knowledge.catch_math`), do not import from `explorer.status_care` in the knowledge layer, and do not change `status_care.py`, the overworld poison care, item use (Antidote, Parlyz Heal, Awakening) or the catch logic and its `CATCH_STATUS` values.
- Do not change the stat-stage code, `SWITCH_GAIN`, `SWITCH_HP_TURNS`, `WEAK_RATIO`, `SWITCH_MIN_HP`, `MAX_SWITCHES_PER_BATTLE` or `TRAINEE_SAFE_HP`; do not model Speed ordering, toxic escalation, or sleep-counter turns remaining (a sleeping mon is simply "does not act").
- Do not build a turn engine or anything under `src/pokeagent/sim/` (`Battle_Simulator_Directive.md`), and do not add a new decision or a heal-with-item rule.
- Do not trust the unverified bytes silently: every constant here is named and one edit from correct; Claude's organic check confirms them before any tuning.
- No emulator run, no ROM, no window; do not touch `runs/`, `baselines/`, `roms/` or any save state.

## Verification (exact commands)

```
uv run --frozen pytest -q tests/test_status_model.py tests/test_status_scores.py tests/test_status_switch.py
```
Expected: all pass.

```
uv run --frozen pytest -q tests/test_status_care.py tests/test_status_interactions.py tests/test_battle_mon_gating.py tests/test_knowledge.py tests/test_switch_matchup.py tests/test_explorer_behaviours.py tests/test_layers.py
```
Expected: no new failures. Claude ran this exact command on origin/main 01b7fd6 while writing the directive: `71 passed, 2 skipped, 1 warning in 1.71s`.

```
git diff --stat origin/main -- src/pokeagent
```
Expected: the two new knowledge modules, `ram_symbols.py`, `ramstructs.py`, `battle_state.py`, `scoring.py`, `src/pokeagent/explorer/battle.py`, `team_plan.py`, `switch_out.py`.

## Completion criteria

- [ ] `decode`, `can_act_share`, `attack_factor`, `residual` and `foe_blocked` return the values above for each status byte and the confusion flag. <!-- test: tests/test_status_model.py -->
- [ ] Setup moves score the safe value only against a blocked (or half against a paralysed) foe at healthy HP when no damaging move ends the fight; a confuse move on a confused foe scores 0.0; a damaging move still outscores a setup move. <!-- test: tests/test_status_scores.py -->
- [ ] A burned physical attacker, a paralysed or confused attacker and a sleeping attacker score their damaging moves at the model's factor, and scores are unchanged when no condition is set. <!-- test: tests/test_status_scores.py -->
- [ ] `switch_choice` switches a sleeping or frozen active member out, lowers the bar for a paralysed, confused or burned one, counts poison and burn residual in the HP-danger test, never switches into a sleeping candidate, and does not fire the HP-danger switch against a sleeping or frozen foe. <!-- test: tests/test_status_switch.py -->
- [ ] The existing test files in the second verification command pass unchanged, and both size and layering tests stay green.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails, and the constants with their values (`PARA_SKIP`, `CONFUSE_SELF_HIT`, `BURN_ATTACK`, `RESIDUAL_DIV`, `SETUP_SAFE_VALUE`, `SETUP_PARA_SHARE`). Then the organic check Claude runs afterwards with the ROM (Devin cannot): in real fights where a mon is put to sleep, paralysed, burned, poisoned and confused (a seeded state from a swarm slot, not this worktree), read the status byte at wBattleMonStatus 0xD018 and wEnemyMonStatus 0xCFE9 and the flags at 0xD062 and 0xD067 against the battle text to confirm every bit position in `catch_math.py` and bit 7 for confusion, then read `runs/<run>/decisions.jsonl` for the status notes in the rule strings and the switch reasons. If any bit is wrong the fix is the one constant.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command (`uv run python --version` prints `Python 3.12.12`); never bare `python`.
- Branch only (`directive/pokeagent-battle-status-conditions-directive`); commit as you go; never commit to or push main; never merge.
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
