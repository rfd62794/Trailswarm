# PokeAgent: move chooser - a used move counts as tried, a status move is tried once per battle, and never ahead of a known hit when weak

**Small and independent.** Base: current main. It touches the same files as the PP-zero guard (PR #286, branch `directive/pokeagent-pp-zero-move-guard-directive`); see "Avoiding conflicts with PR #286" below.

## Why this exists

A reviewer's ROM run (2026-11-14): Charmander at level 4 with Ember excluded at 0 PP pressed GROWL about 12 times in one wild fight instead of attacking with Scratch. Console: "BATTLE vs #165 L4: SCRATCH (untried)" then "move menu: cursor to GROWL (now on SCRATCH)". `decisions.jsonl` showed GROWL x12, SCRATCH x1.

Claude read the chooser (`src/pokeagent/explorer/behaviours/battle_moves.py`, `BattleMoves.step`). The cause is the definition of "tried":

```
tried = [mv for mv in pool if score(mv)[0]]
```

where `score` wraps `observed_damage` (`src/pokeagent/explorer/battle.py`), which returns tried=1 only when a damage record exists:

```
def observed_damage(data: dict, species, move: str, type_key: str, emax: int) -> tuple[int, float]:
    """(tried, approx damage) for the move chooser's tiebreak: the species-specific move_damage
    record first, then the type-generalised damage_by_type fractions scaled by this enemy's max HP."""
```

Damage is recorded only when the enemy HP drops after the move (the `pending_move` block at the top of `step`). GROWL never drops HP, so it never gets a record, so it is "untried" for ever. In the no-knowledge branch (the `else:` after `if known and any(...)`):

```
target = next((mv for mv in pool if mv not in tried), None) or max(pool, key=lambda mv: score(mv)[1])
ctx.move_reason = "untried" if target not in tried else f"best avg {score(target)[1]:.1f} dmg"
```

the first untried move in menu order is the target, so GROWL stays the target every turn. The log shows the `untried` reason, which is that branch. In the knowledge branch a damaging move never used gets a 1.3 bonus via `kscore`, which has the same blind spot (a move used without damage still looks never used there).

The console line and the `decisions.jsonl` counts above come from the reviewer's run; those logs are local and not in the repo, so the tests below are synthetic.

## Scope (in this order)

1. `src/pokeagent/explorer/behaviours/battle_tried.py` <!-- new: src/pokeagent/explorer/behaviours/battle_tried.py --> - a small pure helper module (under 90 lines) so `battle_moves.py` does not grow.
2. `src/pokeagent/explorer/behaviours/battle_moves.py` (157 lines on main) - three small edits: record a used move, build `tried` through the helper, filter the untried pick. Keep its public names (`pick_catch_move`, `BattleMoves`, `MENU_CURSORS`, `NON_HIT_NOTES`).
3. `src/pokeagent/explorer/behaviours/battle.py` (299 lines on main; the cap is 300) - ONE added line in the battle-end reset, see below. Nothing else there.
4. `tests/test_battle_tried_moves.py` <!-- new: tests/test_battle_tried_moves.py --> - synthetic tests, no ROM, no emulator.

## The work

### battle_tried.py (pure helpers; no emulator, no ROM, no `global`)

Per-battle state lives on the context without a new field (`src/pokeagent/explorer/context.py` is at exactly 300 lines and must not grow). The context already offers:

```
def setdefault(self, key: str, default: Any = None) -> Any:
```

Use `ctx.setdefault("used_moves", set())` for the set of move names pressed this battle.

```
LOW_HP_FRAC = 0.5      # our mon at or below half HP
FOE_KO_FRAC = 0.25     # the foe at or below a quarter of its max HP

def mark_used(ctx, move: str) -> None:
    """Record that this move was pressed this battle (damage or not)."""

def used_moves(ctx) -> set[str]:
    """The moves pressed this battle."""

def reset_used(ctx) -> None:
    """Forget the used moves and clear ctx.pending_move (a pending move left over from the last battle must not mark a move in the next one)."""

def is_damaging(move: str, known_score: float) -> bool:
    """True when the cartridge says the move hits for damage: known_score > 0, or the ROM row has power > 0 (move_by_name(move)). A name the ROM does not know with a score of 0 is non-damaging."""

def tried_moves(pool: list[str], observed: list[str], used: set[str]) -> list[str]:
    """Moves of the pool with a damage record (observed) or already pressed this battle (used), in pool order."""

def explore_pool(pool, tried, damaging, my_hp, my_max, foe_hp, foe_max) -> list[str]:
    """Moves the 'untried first' rule may target: the pool minus tried; and when the mon is weak
    (my_hp <= my_max * LOW_HP_FRAC) or the foe is nearly dead (foe_hp <= foe_max * FOE_KO_FRAC)
    AND at least one damaging move is in the pool, drop the untried non-damaging moves.
    A max of 0 (an unread value) never counts as weak or nearly dead."""
```

`move_by_name` is in `src/pokeagent/explorer/battle.py`: `def move_by_name(name: str) -> dict | None:` (the ROM row, with a `power` key). `damaging` is a callable from move name to bool (so tests need no ROM table). Rules to implement exactly:

- A move pressed this battle counts as tried whether or not it did damage. A status or stat move is therefore the exploration target at most once per battle: after one press it is in `used`, so it is tried, and the existing tiebreak (`max(pool, key=lambda mv: score(mv)[1])`, average observed damage, 0 for GROWL) puts the best damaging move first.
- No positive-reason exception here: leave "setup move against a sleeping foe" and other status value to the queued status-conditions directive. This directive only stops the loop.
- A weak mon or a nearly dead foe never explores a non-damaging move while a damaging one is in the pool. If the pool has no damaging move at all, the old behaviour stands (something has to be pressed).

### battle_moves.py edits (small; a line or two each)

1. Right after `pm = ctx.pending_move` near the top of `step`: `if pm and pm["species"] == species: mark_used(ctx, pm["move"])`. This runs on the step after the A-press and before the damage block clears `pending_move`, so a move that did damage is marked too (harmless: it already has a record).
2. Replace `tried = [mv for mv in pool if score(mv)[0]]` with a call to `tried_moves(pool, [mv for mv in pool if score(mv)[0]], used_moves(ctx))`.
3. In the `else:` (no knowledge) branch, take the untried target from `explore_pool(...)` instead of `[mv for mv in pool if mv not in tried]`. Our HP is `hp` and `mx` (already unpacked at the top of `step`), the foe's is `enemy_hp` and `enemy_max`. `damaging` is `lambda mv: is_damaging(mv, known.get(norm0(mv), (0, ""))[0])`. In the knowledge branch edit 2 alone is enough (a used move loses its 1.3 first-try bonus).

In `src/pokeagent/explorer/behaviours/battle.py`, add ONE new line directly after the existing line `ctx.no_pp = set(); ctx.all_pp_out = 0; ctx.last_move_choice = None` (inside the `if ctx.in_battle:` end-of-battle branch), at the same indent: `reset_used(ctx)`. The import must also fit: count the file after the edit, it must stay at or under 300 lines. If it does not fit, stop and write why in the Status row rather than trimming other code.

### Avoiding conflicts with PR #286 (PP-zero guard)

Claude read the diff of `origin/directive/pokeagent-pp-zero-move-guard-directive`. It edits `battle_moves.py` in four places: the import block (adds `from pokeagent.explorer.behaviours.battle_pp import cursor_step, usable_moves`), the PP block (`avail` becomes `usable`, `pool = usable`), the cursor block (removes the `norm = lambda` line, calls `cursor_step`), and one line after the move-menu branch (`ctx.move_nav = 0`). It also appends `ctx.move_nav = 0` to the existing battle-end reset line in `battle.py`.

To stay clear: base on main (not on the #286 branch), edit only the spots above in `battle_moves.py` (the `tried` line, the `else:` untried pick, one line after `pm = ctx.pending_move`, and your own import line), add ONE new line in `battle.py` and never edit the existing reset line, and do not touch `pool`, `usable`, `avail`, `cursor_step`, `norm`, `move_nav` or the all-PP-out logic. This directive reads `pool` whatever it contains, so there is no semantic overlap. If #286 merges first, the later branch rebases onto main and keeps both sides of any adjacent-line conflict.

### Tests (`tests/test_battle_tried_moves.py`, synthetic only)

Plain pytest. Pure helpers need no emulator; `damaging` is a lambda over a small set of names.

1. `tried_moves(["SCRATCH", "GROWL"], [], {"GROWL"})` is `["GROWL"]`; with observed `["SCRATCH"]` it is both, in pool order.
2. `explore_pool(["GROWL", "SCRATCH"], [], damaging=lambda m: m == "SCRATCH", my_hp=20, my_max=20, foe_hp=20, foe_max=20)` still offers GROWL (healthy, foe healthy): result is GROWL and SCRATCH.
3. Same pool with `my_hp=9, my_max=20` (below half) returns only SCRATCH; with `foe_hp=5, foe_max=20` also only SCRATCH.
4. A pool of only non-damaging moves while weak is unchanged (nothing damaging to prefer).
5. `my_max=0` or `foe_max=0` is not treated as weak.
6. `mark_used` / `used_moves` / `reset_used` on a context from the harness below: the used set empties on reset and `pending_move` is None afterwards.
7. Step-level regression (the reviewer's bug). A battle with GROWL and SCRATCH in the move list, no PP issue, and the knowledge branch empty (monkeypatch `kbattle.ROM_KB` and `bms.ROM_KB` to an empty dict, the way `tests/test_battle_types.py` monkeypatches them to `FAKE_KB`). Drive `BattleMoves().step(ctx)` for 12 turns: after GROWL is pressed once (set `ctx.pending_move` for it as the A-press does, no enemy HP drop), the target is SCRATCH, never GROWL again. Assert GROWL is chosen at most once.
8. Same fight with `bv.hp=3, bv.mx=20` and an untried GROWL: the damaging move is the target on the first step.

Test harness: `tests` is not a package, so copy the small helpers into the new file (do not import across test files). The signatures to copy from `tests/test_battle_types.py` are:

```
def make_ctx(tmp_path, memory=None, **fields) -> ExplorerContext:
def put_box(ctx, text_rows) -> None:
```

There the move menu is drawn with `put_box(ctx, ("FIGHT", "TYPE/", "NORMAL", "29/30", "TACKLE", ">GROWL"))` followed by `ctx.bv = BattleView(kind=1, hp=10, mx=20, species=25, my_sp=4, my_lvl=5, e_lvl=3, cur=">FIGHT")` and `ctx.refresh()`. Copy the `memory=` bytes and the `FAKE_KB` shape from `test_move_choose_decision_carries_the_rule_string` in that file. If a step-level case cannot be made to work in that harness in one honest attempt, say so in the Report and keep tests 1-6 (do not invent a new harness).

## What NOT to do

- Do not change `move_scores`, `observed_damage`, the damage-learning bookkeeping (`damage_dealt`, `move_damage`, `damage_by_type`), the type-effect ledger, or the catch policy (`pick_catch_move`, `src/pokeagent/explorer/behaviours/catch.py`).
- Do not add status-move value logic (sleep, setup, stat drops as a reason to press): that belongs to the queued status-conditions directive.
- Do not touch the PP guard logic (`avail`, `usable`, `pool`, `no_pp`, `all_pp_out`, `move_nav`, the cursor block) and do not create `src/pokeagent/explorer/behaviours/battle_pp.py`.
- Do not add a field to `src/pokeagent/explorer/context.py` (300 lines) or any `global` statement (`tests/test_layers.py`). Do not push `battle.py` or `battle_moves.py` over 300 lines.
- No emulator runs, no ROM, no windows, no real RAM reads in tests. No per-frame RAM read in the new code (use the values `step` already has).
- Do not state where any game copy came from.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12` in this repo)

```
uv run --frozen pytest -q tests/test_battle_tried_moves.py
```
Expected: all pass.

```
uv run --frozen pytest -q tests/test_battle_types.py tests/test_battle_mon_gating.py tests/test_catch_seam.py tests/test_explorer_behaviours.py tests/test_layers.py
```
Expected: no new failures. Claude ran `tests/test_battle_types.py tests/test_explorer_behaviours.py tests/test_layers.py` on main while writing this directive and got `62 passed, 1 warning in 4.12s`; the 300-line check lives in `tests/test_explorer_behaviours.py`.

```
git diff --stat origin/main -- src/pokeagent
```
Expected: `battle_moves.py` (a handful of lines), `battle.py` (+1 line plus the import) and the new `battle_tried.py` only.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command.
- Branch only (`directive/pokeagent-move-chooser-tried-moves-directive`); commit as you go; never commit to or push main; never merge.
- Create no scratch or debug files; anything temporary goes under `.devin-scratch/`.
- Synthetic-proof rule (Robert, 2026-11-07): a synthetic test shows the logic, it does not prove the behaviour. Say so in the Report; Claude does the organic ROM check afterwards before this counts as fixed.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat and test tails in the Report.

## Completion criteria

- [ ] A move pressed this battle is tried whether or not it did damage; a status move is the exploration target at most once per battle. <!-- test: tests/test_battle_tried_moves.py -->
- [ ] A weak mon (at or below half HP) or a nearly dead foe (at or below a quarter) never explores a non-damaging move while a damaging one is in the pool. <!-- test: tests/test_battle_tried_moves.py -->
- [ ] The step-level regression shows GROWL chosen at most once over 12 turns, or the Report says why that harness case was not possible.
- [ ] Used moves reset at battle end; `battle.py` and `battle_moves.py` stay at or under 300 lines; `context.py` unchanged.
- [ ] No change to `move_scores`, `observed_damage`, the catch path or the PP guard code.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails, line counts of `battle.py` and `battle_moves.py`, whether the step-level tests were possible, and one line saying this is synthetic proof only. Then the check Claude runs afterwards with the ROM (Devin cannot): load a wild battle with a lead that knows GROWL and SCRATCH (Ember at 0 PP), run a headless explorer for a few hundred steps and read `decisions.jsonl` to confirm GROWL appears at most once per battle and Scratch is the rest.

## Forbidden Actions

- ROMs, extracted game art, save states and anything derived from them are local and gitignored. Never commit them or add one as a fixture.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor.
- Do not open a window or send input.
- Do not commit to or push main, merge, or deploy.

## Required from User

- The ROM check in the Report section, run by Claude after the verify lane passes. Nothing here blocks the run.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(git diff)
- Exec(git grep)
