# Trailswarm: an interaction note holds only the dialogue of that interaction, and the PC planner finds a typed PC spot

**Size:** M. **Assignee:** devin.

## 1. Why this exists

Measured on 2026-11-08 on `runs/maps.json` (gitignored, so missing in a fresh worktree; do not look for it). Counts only:

- 16,476 interaction entries, 3,985 with text. About 3,209 of those match a rough battle-text pattern and 672 a menu or save-screen pattern. So most notes are not dialogue.
- 756 spots were pressed 100 or more times.
- 8 entries carry PC text but are not typed `pc`. 20 entries have conflicting `type_votes`.
- Control run: Red with its own memory, untouched, 600 steps from the bedroom, never completed the potion goal (292 `plan_goal` and 252 `replay_demo` decisions, 1 A press on map 38). Cold runs with no memory did it by step 35 unaided.
- Specific case, map 38: `0,2,UP` is typed `pc` (count 1043) but its text is Mom's dialogue and contains no "pc". A bogus `0,2,DOWN` (count 338) has the text "... turned on | the PC.". `interaction_spots` (`src/pokeagent/explorer/world.py:127`) matches text only, so it returns only the bogus DOWN spot, and `src/pokeagent/explorer/planner.py:55-57` then paces DOWN and UP forever.

### The capture mechanism, read from the code (not yet run; section 3 step 1 proves it)

Two paths put non-dialogue text into a note. Both are in `src/pokeagent/explorer/`.

1. **An interaction that never closes across a battle or a menu.** `press.py:105-111` keeps `ctx.dialog` and resets it only when `not box_before` (`press.py:107-108`). While a text box stays open from one press to the next, which is what happens when a trainer's talk runs into the battle intro, `ctx.inter` stays open. Each such press runs the `if box_before:` block of `press_interact.py` (around lines 19-33), which at `press_interact.py:24-26` overwrites `entry["text"]` with `" / ".join(ctx.dialog)[:400]` whenever that is longer. When the box finally closes, `close_interaction` calls `add_pages(entry, list(ctx.dialog))` at `interaction_record.py:32`, and `add_pages` (`interaction_record.py:15-20`) copies every distinct fragment of the last 12 dialog items, battle lines included, into `entry["pages"]`. Nothing checks the battle flag (`0xD057`) or `is_menu` before this.
2. **A box that opens after a non-A press is recorded as an interaction.** `press_interact.py:105-110` (`if box_after and not ctx.inter and ctx.proc is None:`) calls `ctx.mem.interact(before[0], before[1], before[2], ctx.facing, text)` for any press that leaves a box open: a wild-battle intro after a step, or the START menu. `text` here is `box_text(tm2)` from `press.py:105`, which includes menu rows (only `ctx.last_text` and `ctx.dialog` exclude menus, at `press.py:106`). `memory.py:181-182` stores that as the entry's first text, so the tile you stood on gets a "talk" entry made of battle or menu text. The A branch of the same function (`elif name == "A":`) does the same with `text if box_after else ""` when the box is a menu.

These are the two code paths that fit the numbers (battle text in 3,209 notes, menu text in 672). I have not run them. If your failing test in step 1 does not reproduce the bad note on the current code, stop guessing: report which path you tried and what the note held, and find the real path with more failing tests before writing any fix.

The relevant existing signatures:

```python
# interaction_record.py
def add_pages(entry: dict, dialog: list) -> None: ...
def close_interaction(ctx, inter: dict, pos_after: tuple) -> str: ...
# press_interact.py
def record_interaction(ctx: ExplorerContext, fr: PressFrame) -> None: ...
# world.py:127
def interaction_spots(maps: dict, needle: str) -> list[tuple[int, int, int, str]]: ...
```

## 2. Scope

In order:

1. A new test file with failing synthetic tests (the three capture cases below).
2. The smallest fix in `src/pokeagent/explorer/press_interact.py` and/or `src/pokeagent/explorer/interaction_record.py`, and a new small helper module if the logic needs one.
3. `interaction_spots` in `src/pokeagent/explorer/world.py` honouring typed entries, plus its test.

## 3. The work

1. **Failing tests first.** Create `tests/test_interaction_text_capture.py` <!-- new: tests/test_interaction_text_capture.py -->. Build the context as `make_ctx` and `put_box` do in `tests/test_explorer_behaviours.py` (a `FakeEmulator` with map `0xD35E`, x `0xD362`, y `0xD361`, an `ExplorerContext` with `MapMemory(tmp_path / "maps.json")`; the box is drawn at tile map `0xC3A0` with `0x79 0x7A` for the top edge and `0x7C` side edges; a menu has the `0xED` cursor tile). Drive real presses through `Presser(ctx).press(name, source, why)` from `pokeagent.explorer.press`, as `tests/test_intervene_lease.py` does near line 128, so the whole path `press_and_read` then `record_interaction` runs. Copy those two helpers into the new test file; do not import from another test module. Tests:
   - `test_battle_after_a_talk_does_not_add_to_the_note`: press A facing a spot with a one-page dialogue box, then change the screen to a battle intro (set `0xD057` to 1 or 2 and draw a box with a wild-battle line such as "WILD PIDGEY appeared!"), press again. Assert the entry's `text` and every item of `pages` contain none of the battle line, and the interaction was closed (`ctx.inter is None`) or at least stopped recording.
   - `test_a_menu_does_not_add_to_the_note`: the same with the START menu drawn (a box with `0xED` and a row such as "POKeDEX"). Assert the note holds only the dialogue. Also cover a menu that appears after a movement press: assert no interaction entry is created for the tile (the contact branch at `press_interact.py:105`).
   - `test_ordinary_multi_page_dialogue_still_records`: three pages of plain dialogue, then the box closes. Assert `pages` holds the three pages in order and `text` is the fullest dialogue. This must pass before and after your fix.

   Run them on the unmodified code. Report which of the first two fail and with what note. If one passes on the current code, that path is not the mechanism: say so in the report and in the test docstring, and keep the test as a guard.
2. **Fix it, smallest correct change.** The note must be written only from dialogue. Suggested shape, adjust to what the failing tests show: a tiny helper (for example `is_dialogue_state(ctx, tm)` returning false when `0xD057` is non-zero or `is_menu(tm)`), used (a) at `press_interact.py:21-26` so the text and pages are not extended in a battle or a menu, and the open interaction is finished with `ctx.mem.finish_interaction` and cleared when a battle starts, and (b) at `press_interact.py:105` and the A branch so a battle intro or a menu never opens an interaction entry. Keep the existing behaviour for item balls, trainer talks (`trainer_ledger.note_talk` still receives its `box_after`) and `ball_result`. If a helper is needed it goes in a new file `src/pokeagent/explorer/interaction_gate.py` <!-- new: src/pokeagent/explorer/interaction_gate.py --> with no other content.
3. **`interaction_spots` honours typed entries.** In `src/pokeagent/explorer/world.py` change `interaction_spots(maps, needle)` so an entry also matches when `e.get("type", "")` equals the needle compared in lower case (so needle "PC" finds an entry typed `pc`), and so spots matched by type come first in the returned list, before text-only matches. Text matching stays exactly as it is. This makes `planner.py:55-57` reach the real `0,2,UP` spot first; do not change `planner.py`. Add `test_interaction_spots_finds_a_typed_pc_entry_with_no_pc_text` to the new test file, using a synthetic maps dict with this shape (invented dialogue, not from the real file): `{"38": {"interactions": {"0,2,UP": {"type": "pc", "count": 5, "text": "hello there"}, "0,2,DOWN": {"count": 2, "text": "turned on | the PC."}}}}`. Assert the first result is `(38, 0, 2, "UP")`, and that the DOWN spot is still returned after it (text matching kept). Add a case with no typed entry that still returns the text match.
4. Keep each new or edited file under 600 lines.

## 4. What NOT to do

- Do not touch `src/pokeagent/game/` or `src/pokeagent/cli.py`; a separate run changes them.
- Do not change `retalk_veto.py`, `loop_veto.py` or `planner.py`.
- Do not clean, rewrite or read any real `maps.json`. Cleaning existing bad notes is a different directive. This one only stops new ones.
- Do not add a ROM, a `kb/` table or any game data to the repo. All tests use hand-written synthetic memory.
- Do not run, edit or re-record `tests/test_golden_red.py`. It skips in the worktree. Report it NOT run. Claude's ROM-present check runs it before merge. If your change alters a hash it records (it should not, since the change only affects what is written to notes), say so in the report so it is re-recorded from a base-commit run in the same PR.
- Do not rename identifiers or reformat code you are not changing.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

```
uv run pytest -q -p no:cacheprovider tests/test_interaction_text_capture.py
```
Expected: all pass after the fix. Report the output before the fix too (which tests failed and the note each produced).

```
uv run pytest -q -p no:cacheprovider tests/test_explorer_behaviours.py tests/test_interaction_types.py tests/test_cave_sinks.py tests/test_status_interactions.py tests/test_intervene_lease.py
```
Expected: same result as on your base commit, no new failures. Report any pre-existing failure separately.

```
git diff --stat main -- src/pokeagent/game src/pokeagent/cli.py src/pokeagent/explorer/planner.py src/pokeagent/explorer/retalk_veto.py src/pokeagent/explorer/loop_veto.py
```
Expected: no output.

```
uv run pytest -q -p no:cacheprovider tests/test_golden_red.py -rs
```
Expected: it skips in the worktree. Report it as NOT run, with the skip reason.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here. If something expected is missing (for example `runs/maps.json`), stop and write that in the PR description.
- Use `uv run` and Python 3.12 only.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- If a tool call is genuinely blocked, stop and write why in the PR description.

## 7. Completion criteria

- [ ] A battle that begins right after a talk adds nothing to the note's `text` or `pages`. <!-- test: tests/test_interaction_text_capture.py -->
- [ ] A menu adds nothing to the note, and a box that opens after a movement press creates no interaction entry for a battle or menu. <!-- test: tests/test_interaction_text_capture.py -->
- [ ] Ordinary multi-page dialogue still records all its pages in order. <!-- test: tests/test_interaction_text_capture.py -->
- [ ] `interaction_spots` returns a typed `pc` entry with no "pc" in its text, listed before text-only matches, and text matching still works. <!-- test: tests/test_interaction_text_capture.py -->
- [ ] The failing-first output is in the report, and the confirmed mechanism (or the statement that it was not reproduced) is stated with file:line.
- [ ] No file touched under `src/pokeagent/game`, `src/pokeagent/cli.py`, `planner.py`, `retalk_veto.py` or `loop_veto.py`; no file over 600 lines.

## 8. Report

Findings first: which of the two paths reproduced (with the exact bad note each produced before the fix), the file:line of the confirmed mechanism, and the fix in one paragraph. Then the command tails from section 5, including `tests/test_golden_red.py` reported NOT run and why. Name anything that did not fit.

## Required from User

Nothing before the run. Afterwards Claude runs the ROM-present check (including `tests/test_golden_red.py`) before merge. Cleaning the existing bad notes in Red's real `maps.json` is the next directive (`Memory_Audit_And_Fact_Labels_Directive.md`), not this one.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(src/pokeagent/explorer/press.py)
- Read(src/pokeagent/explorer/press_interact.py)
- Read(src/pokeagent/explorer/interaction_record.py)
- Read(src/pokeagent/explorer/world.py)
- Read(tests/test_explorer_behaviours.py)
- Read(tests/test_intervene_lease.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git diff)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Approved |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-08 18:57 · robert-claude-laptop · none → Queued — Drafted by Claude for Robert 2026-11-08: notes collect battle and menu text; prove the path with failing tests, then fix; typed PC lookup
- 2026-11-08 19:54 · robert-claude-laptop · Queued → Approved
<!-- queue:end -->
