# PokeAgent: PP-zero move guard - never press a move with no PP left, and take the Struggle path on the first all-zero read

**Independent of the save-library directives.** Base: current main.

## Why this exists

Robert, 2026-11-14: "Agent also gets stuck trying Ember even when out of PP, instead of Scratch or Tackle or whatever other move Charmeleon has at that time."

Claude read the move chooser (`src/pokeagent/explorer/behaviours/battle_moves.py`, `BattleMoves.step`). PP is read correctly (battle copy `wBattleMonPP`, low 6 bits, via `read_battle_view(ctx.emu).battle_mon.pp`), and a PP filter exists (`avail`, lines 85-95) plus a refusal marker (`ctx.no_pp`, lines 77-84). Two holes remain, and the whole guard has NO test (`git grep -n "no_pp\|pp_out" -- tests` finds nothing):

1. **`move_nav > 5` escape.** The code walks the cursor to the target with DOWN presses; after 5 presses it gives up and presses A on whatever is under the cursor: `chosen = cursor_mv if ctx.move_nav > 5 else target` (around line 130, comment "never bounce: after 5 moves take what is under the cursor"). The game remembers the last move used, so the cursor starts on Ember; if Ember has 0 PP and the cursor walk is slow or blocked, A is pressed on the empty move. The game refuses ("No PP left for this move!"); the refusal handler (L77-84) marks it in `ctx.no_pp` only on the NEXT loop, and only if the move-list screen is still visible. `ctx.move_nav` is also never reset when the move menu is left without a choice (it resets only inside the choose branch), so stale counts carry into later turns and trigger the escape early.
2. **All-zero read.** When `avail` is empty (every move 0 PP, refused, or a stale `wBattleMon` reading as zeros) the first step falls through with the full move list (`pool = avail or moves`) and only presses B for Struggle on the SECOND consecutive step (`ctx.all_pp_out > 1`, lines 91-95). The first step can therefore press A on an empty move.

Real logs: Claude searched the `runs/` console logs for "was refused" and `pp_out_struggle` and found no recorded loop, so there is no real trace to quote; the fix rests on the two code paths above and on Robert's report.

## Scope (in this order)

1. `src/pokeagent/explorer/behaviours/battle_pp.py` <!-- new: src/pokeagent/explorer/behaviours/battle_pp.py --> - a small pure helper module for the PP logic, so `battle_moves.py` does not grow. Under 80 lines.
2. `src/pokeagent/explorer/behaviours/battle_moves.py` - use the helpers; keep its public names (`pick_catch_move`, `BattleMoves`, `MENU_CURSORS`, `NON_HIT_NOTES`).
3. `src/pokeagent/explorer/behaviours/battle.py` - one added line in the battle-end reset (line ~231, see below).
4. `tests/test_battle_pp_guard.py` <!-- new: tests/test_battle_pp_guard.py --> - synthetic tests, no ROM, no emulator.

## The work

### battle_pp.py (pure; no emulator, no ROM)

```
def usable_moves(moves: list[str], pp_bytes: tuple[int, ...] | None, no_pp: set[str]) -> list[str]:
    """Moves of the menu list (slot order) that can be pressed: PP (byte & 0x3F) above 0 and not in no_pp.
    pp_bytes None = a stale battle struct (no PP data at all): every move not in no_pp counts as usable."""

def cursor_step(cursor_mv: str, target: str, usable: list[str], nav: int) -> tuple[str, str | None]:
    """("press_a", move) when the move under the cursor is the target, or (nav > 5, the walk has gone on too long) when
    it is any usable move; otherwise ("down", None). Never ("press_a", m) for an m that is not in usable."""
```
Rules to implement exactly:
- `pp & 0x3F` is current PP (the top two bits are PP Ups). A slot is usable iff its PP is above 0 and its name is not in `no_pp`. A slot index at or beyond `len(pp_bytes)` is unusable. Only `pp_bytes is None` (no PP data) makes every slot usable; a real all-zero read returns an empty list.
- Never press A on a move under the cursor that is not in `usable`. Replace the `move_nav > 5` take-what-is-under-the-cursor escape: past 5 cursor presses, press A only when the cursor move is in `usable` (any usable move is acceptable then); otherwise keep walking DOWN (wrapping the list).
- If `usable` is empty (real all-zero read, or every move refused): on the FIRST such step press B so the game leaves the move list and runs Struggle on its own. The decision tag stays `pp_out_struggle`. Keep counting `ctx.all_pp_out`; drop the `> 1` delay.
- Reset `ctx.move_nav = 0` whenever the move menu is not on screen (the branches of `BattleMoves.step` that run when `cursor_mv` or `move_lines` is empty) and when the battle ends: `src/pokeagent/explorer/behaviours/battle.py` line ~231 already resets `ctx.no_pp`, `ctx.all_pp_out`, `ctx.last_move_choice` when `ctx.in_battle` ends - add `ctx.move_nav = 0` there.
- Keep the refusal handler (L77-84): a screen containing "PP" or "DISABLED" still moves `ctx.pop("last_move_choice")` into `ctx.no_pp`.
- When Ember is unusable the pool given to the scorer is `usable`, so the best remaining DAMAGING move wins (Scratch or Tackle for a Charmeleon). Do not change `move_scores` (`src/pokeagent/explorer/battle.py`); it already scores a 0-PP move as 0.

### Tests (`tests/test_battle_pp_guard.py`, synthetic only)

Plain pytest, tuples for PP bytes. Required cases:
1. `usable_moves(["SCRATCH", "GROWL", "EMBER", "LEER"], (35, 40, 0, 30), set())` excludes EMBER.
2. PP Up bits: `0xC0` (PP 0 with two PP Ups) is unusable; `0x45` (PP 5, one PP Up) is usable.
3. `no_pp={"SCRATCH"}` removes SCRATCH even with PP above 0.
4. All four PP 0 returns an empty list; `pp_bytes=None` returns the full list (stale read).
5. `cursor_step`: cursor on EMBER (0 PP) never returns `("press_a", "EMBER")` for any `nav` (try 0, 5, 6, 50); cursor on a usable non-target move returns press-A only once `nav > 5`.
6. A step-level test of `BattleMoves.step` is optional: `git grep -ln "BattleMoves" -- tests` shows how existing tests stub the view; if a stub is practical, prove that an all-zero PP read yields `Decision("B", "pp_out_struggle", ...)` on the FIRST step. If it is not practical, say so in the Report; do not invent a new harness.

## What NOT to do

- Do not change `move_scores`, the catch policy (`src/pokeagent/explorer/behaviours/catch.py`), `pick_catch_move`, the damage-learning bookkeeping (`pending_move`, `damage_dealt`), or any switch/party logic.
- Do not touch `src/pokeagent/explorer/behaviours/switch_out.py`, `party_order.py` or `src/pokeagent/knowledge/team_plan.py` (the `Lead_And_Wild_Switch_Directive.md` owns those).
- No emulator runs, no ROM, no windows, no real RAM reads in tests.
- Do not add a per-frame RAM read; reuse the `read_battle_view` call already in `step`.
- Do not state where any game copy came from.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12` in this repo)

```
uv run --frozen pytest -q tests/test_battle_pp_guard.py
```
Expected: all pass.

```
uv run --frozen pytest -q tests/test_battle_mon_gating.py tests/test_battle_types.py tests/test_catch_seam.py tests/test_explorer_behaviours.py
```
Expected: no new failures (existing files that import `BattleMoves`). Claude ran this exact command on main while writing the directive; the tail is in the PR description.

```
git diff --stat origin/main -- src/pokeagent
```
Expected: `battle_moves.py`, `battle.py` (the one reset line) and the new `battle_pp.py` only.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command.
- Branch only (`directive/pokeagent-pp-zero-move-guard-directive`); commit as you go; never commit to or push main; never merge.
- Create no scratch or debug files; anything temporary goes under `.devin-scratch/`.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat and test tails in the Report.

## Completion criteria

- [ ] `usable_moves` excludes 0-PP moves (low 6 bits), honours PP Up bits and `no_pp`, returns an empty list for a real all-zero read and the full list for a missing read. <!-- test: tests/test_battle_pp_guard.py -->
- [ ] `cursor_step` never returns a press-A on an unusable move. <!-- test: tests/test_battle_pp_guard.py -->
- [ ] An all-zero PP read presses B (`pp_out_struggle`) on the first step, not the second.
- [ ] `ctx.move_nav` resets when the move menu is not showing and when the battle ends.
- [ ] No change to `move_scores`, the catch path, `switch_out.py` or `party_order.py`.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails, and whether the optional step-level test was possible. Then the check Claude runs afterwards with the ROM (Devin cannot): load a battle state whose lead knows Ember, patch Ember's PP byte to 0, run a headless explorer for a few hundred steps and read `decisions.jsonl` to confirm Scratch or Tackle is chosen, no A is pressed on EMBER and no `pp_out_struggle` loop appears; then a second state with all four PP bytes at 0 to see Struggle fire once.

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

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Review |
| Assigned to | devin |
| Branch | directive/pokeagent-pp-zero-move-guard-directive |
| Base branch | - |
| Base commit | 9303e9dbb35216265a215d503df5156439e43b0d |
| Head commit | 810e74b465e584378ad34368d929841decb09117 |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-14 14:26 · robert-claude-laptop · none → Queued
- 2026-11-14 14:28 · robert-claude-laptop · Queued → Approved
- 2026-11-14 15:34 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-pp-zero-move-guard-directive; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M7DW9CE32R6ZKTBXD6TWTSB9
- 2026-11-14 15:43 · dispatcher · launched pid=13180; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-pp-zero-move-guard-directive; provisioned: uv sync --frozen; permission-mode=smart (`## Sandbox needs` declared (3 declared need(s), repo-scoped only))
- 2026-11-14 15:46 · devin · In progress → Review — Done. battle_pp.py (new, pure): usable_moves masks PP bytes & 0x3F, honours PP Up bits and no_pp, slot beyond len unusable, None read = all usable; cursor_step never returns press_a on an unusable move (nav>5 escape now requires the cursor move be usable). battle_moves.py uses both: empty usable -> B 'pp_out_struggle' on the FIRST step (all_pp_out still counted, >1 delay dropped); pool = usable so the scorer only sees pressable moves; ctx.move_nav=0 when the move menu is not on screen. battle.py: ctx.move_nav=0 added to the battle-end reset line. Refusal handler unchanged; move_scores, catch path, switch_out, party_order, team_plan untouched. Tests: new tests/test_battle_pp_guard.py, 14 passed - `uv run --frozen pytest -q tests/test_battle_pp_guard.py` -> '14 passed'. Regression: `uv run --frozen pytest -q tests/test_battle_mon_gating.py tests/test_battle_types.py tests/test_catch_seam.py tests/test_explorer_behaviours.py` -> '79 passed'. Diff stat vs origin/main -- src/pokeagent: battle.py 2+/-1, battle_moves.py 23 +/-, battle_pp.py +25 (only). Step-level stub was practical (make_ctx/put_box harness): all-zero PP read yields Decision('B','pp_out_struggle') on the first step; stale struct (species 0) does NOT B out; cursor parked on a 0-PP EMBER presses DOWN for 8 straight steps, never A. Committed 810e74b, pushed. [origin] spent: devin 3 min est. n/a
<!-- queue:end -->
