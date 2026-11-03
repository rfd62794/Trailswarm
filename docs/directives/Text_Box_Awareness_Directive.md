# PokeAgent: text-box awareness - detect dialog, menu and YES/NO boxes from the tile map and tell the agent

**Read first:** `docs/superpowers/specs/2026-11-02-pokeagent-design.md`. Depends on
`Hex_Map_Discovery_Directive.md` being merged (it provides `src/pokeagent/screentext.py` with `CHARMAP` and
`decode_text`). If `src/pokeagent/screentext.py` is missing from your worktree, stop and write that in the Status
row; do not recreate it. Also needs `agent.py`, `prompt.py`, `console.py`, `runlog.py`, `cli.py`. **Do not list the
tree recursively** (`Get-ChildItem -Recurse`, `find`, `tree` are refused by the sandbox and end the run); use
`git ls-files`.

## 1. Why this exists

The agent reads RAM only, and `GameState` has no dialog or menu flag, so a model standing in front of a text box
keeps pressing movement buttons that do nothing, or loops on A without knowing a menu is open. The screen's tile map
already carries the answer. Verified on the real ROM (2026-11-02):

- The visible 20x18 tile map is at WRAM `0xC3A0` (360 bytes, row-major, 20 per row). The START menu rendered there
  as readable text.
- Charmap: `0x7F` space, `0x80-0x99` A-Z, `0xA0-0xB9` a-z, `0xF6-0xFF` 0-9, `0xBA` e-acute, `0xED` the menu cursor
  arrow, `0x50` string terminator.
- Box border tiles: `0x79` top-left, `0x7A` top/bottom edge, `0x7B` top-right, `0x7C` left/right edge, `0x7D`
  bottom-left, `0x7E` bottom-right.
- With no box open, rows 12-17 are all tile `0x10` in the bedroom, and overworld rows hold map tiles (values like
  `0x01`, `0x06`, `0x2D`). A dialog box occupies rows 12-17 inside a `0x79..0x7E` frame; the START menu is a frame
  on the right side, rows 0-13.
- UNVERIFIED: the "more text" arrow tile (`0xEE`, bottom-right inside a dialog) and the exact YES/NO frame position.
  Mark both as unverified in code comments and in the module docstring.

Test command `uv run pytest -q` (Python 3.12). No ROM in your worktree; all tests use hand-built tile maps and
`FakeEmulator` (`.set(addr, value)`, `.memory`, `read_range` returns bytes).

## 2. Scope

Create, in order:

1. `src/pokeagent/textbox.py` - `TextBoxInfo`, `detect_text_box`.
2. Edits: `prompt.py` (optional `textbox`), `console.py` (textbox line), `agent.py` (read tile map, pass it in, log it,
   optional auto-advance), `cli.py` (`--auto-advance-dialog` on `run`).
3. `tests/test_textbox.py`, plus additions to the prompt, console and agent tests.
4. Demo integration: replace the local `box_open`/`frame_lines`/`box_text`/`is_menu` helpers in `tools/explore_demo.py` with imports from `pokeagent.textbox` (and `pokeagent.screentext`); the demo must still run (`uv run python -m py_compile tools/explore_demo.py` passes; do not run the demo itself, it opens a window).

## 3. The work

### `textbox.py`

```python
TILEMAP_ADDR = 0xC3A0; COLS = 20; ROWS = 18          # 360 bytes
@dataclass(frozen=True)
class TextBoxInfo:
    kind: Literal["none", "dialog", "menu", "yesno"]
    text: str = ""
    cursor_row: int | None = None      # screen row (0-17) holding the 0xED cursor inside a menu/yesno frame
    more_arrow: bool = False           # tile 0xEE inside the dialog's bottom-right interior (UNVERIFIED byte)
def detect_text_box(tilemap: bytes) -> TextBoxInfo: ...   # raises ValueError if len != 360
```

Algorithm: find frames. Frame presence is a two-byte check: a `0x79` immediately followed by `0x7A` in the tile map, never a one-byte scan for `0x79`. A dialog is a frame whose `0x79` is at column 0 of row 12 (or 11). A frame starts at a `0x79` whose row continues with one or more `0x7A` then a `0x7B`; the
left column below it is `0x7C` down to a `0x7D` whose row continues `0x7A...0x7E`. Record `(top, left, bottom, right)`
for every complete frame; incomplete ones are ignored. Decode each interior row with `screentext.decode_text` after
replacing `0xED` with `0x7F` (cursor) and `0xEE` with `0x7F`; strip rows; drop empty ones.

Classification, in this priority: **yesno** = a frame at most 8 columns wide whose interior text lines include `YES`
and `NO`; **dialog** = a frame with `left == 0`, `right == 19` and `top` in 11-12; **menu** = a frame with
`right == 19`, `left >= 8` and `top <= 1`; otherwise `kind="none"`. `text` is the interior lines joined by a single
space (menu and yesno: joined by `" | "`). If a yes/no box and a dialog are both open, report `yesno` and prefix its
text with the dialog text and `" // "`.

Byte recipes (use these in tests so nothing is guessed). Start from `bytes([0x10]) * 360`; row `r` begins at `r*20`.

- Dialog: row 12 = `0x79` + 18 x `0x7A` + `0x7B`; rows 13-16 = `0x7C` + 18 content tiles + `0x7C`; row 17 = `0x7D` +
  18 x `0x7A` + `0x7E`. Content for "HELLO THERE!" in row 14: `0x87 0x84 0x8B 0x8B 0x8E 0x7F 0x93 0x87 0x84 0x91
  0x84 0xE7` then `0x7F` padding to 18 (check each against `CHARMAP`; if `CHARMAP` maps differently, build the
  expected bytes from `CHARMAP` in the test helper instead). Rows 13, 15, 16 content = 18 x `0x7F`. The more-arrow
  case sets row 16, column 18 to `0xEE`.
- Menu: columns 10-19, rows 0-13. Row 0 = `0x79` + 8 x `0x7A` + `0x7B`; rows 1-12 = `0x7C` + 8 content + `0x7C`;
  row 13 = `0x7D` + 8 x `0x7A` + `0x7E`. Put `0xED` + "ITEM" in row 4 of the content (cursor at interior column 0)
  and "SAVE" in row 6. The rest of the screen stays `0x10`/`0x7F`.
- YES/NO: columns 14-19, rows 7-11 over the same background. Row 7 = `0x79` + 4 x `0x7A` + `0x7B`; rows 8-10 =
  `0x7C` + 4 content + `0x7C`; row 11 = `0x7D` + 4 x `0x7A` + `0x7E`. Row 8 content `0xED` + "YES" and row 9 content
  `0x7F` + "NO" + `0x7F`; expect `kind="yesno"`, `cursor_row == 8`.
- No box: the all-`0x10` map, and an "overworld" map filled with `0x01 0x06 0x2D` repeating, both `kind="none"`.

### `prompt.build_prompt`

New signature: `build_prompt(state, recent, notes, step, max_steps, textbox: TextBoxInfo | None = None)`. When
`textbox` is not None and `kind != "none"`, the first block of the prompt is:

`A TEXT BOX IS OPEN: <text>. Finish this interaction before moving: A advances text, UP/DOWN then A picks a menu
item, B closes a menu.`

Everything else is unchanged; with `None` or `"none"` the prompt is byte-identical to today's.

### `agent.py`, `console.py`, `cli.py`

- Each step the agent calls `info = detect_text_box(emu.read_range(0xC3A0, 360))` and passes it to `build_prompt`.
  Log entries gain `textbox_kind` and `textbox_text` (always present; `"none"` and `""` when no box).
- `console.print_step(..., textbox: TextBoxInfo | None = None)` prints, after the `button:` line and only when a box
  is open, `textbox:  dialog "Hello there!..."` (kind, then the text in double quotes, cut at 40 characters with
  `...` appended when cut).
- `Agent.__init__` gains `auto_advance_dialog: bool = False`. When true and `info.kind == "dialog"` and
  `info.more_arrow`, the step presses `Button.A` without calling the backend: `Decision("A", thinking="auto-advance
  dialog")`, logged with `"source": "auto"` and `backend_ms` 0, not counted as a failure. At most 20 auto presses in
  a row; the 21st step goes to the model and the counter resets whenever a step is not auto.
- `pokeagent run --auto-advance-dialog` (store_true, default off) passes the flag through.

## 4. What NOT to do

- Do not add a field to `GameState` and do not touch `ram.py`, `emulator.py`, `backend.py`, `decision.py`.
- Do not modify `screentext.py` (use `CHARMAP`/`decode_text` as they are; work around gaps in `textbox.py`).
- Do not add OCR, vision, dependencies, or an SDL2 window in tests; do not read outside the worktree.
- Do not mark `0xEE` or the YES/NO position as verified.

## 5. Verification

- `uv run pytest -q` green. New tests at least: dialog recipe -> `kind="dialog"` with the expected text and
  `more_arrow` False, then True with the `0xEE` byte; menu recipe -> `menu`, `cursor_row == 4`, text contains ITEM and
  SAVE; yes/no recipe -> `yesno`, `cursor_row == 8`; both "no box" maps -> `none`; a truncated frame (missing
  `0x7E`) -> `none`; wrong length raises `ValueError`; `build_prompt` with a dialog starts with the exact
  `A TEXT BOX IS OPEN:` sentence and with `None` is identical to the old output; `print_step` textbox line exact
  string including the 40-character cut; an `Agent` run on a `FakeEmulator` whose tile map holds a dialog logs
  `textbox_kind == "dialog"`; auto-advance presses A with `StubBackend` never called, logs `"source": "auto"`, and
  stops auto after 20 in a row.
- `uv run pokeagent run --help` lists `--auto-advance-dialog`.
- Controller check (not yours): on the real ROM, open the START menu and confirm `textbox: menu`.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-text-box-awareness-directive`. Never commit to `main`, never push to it,
  never merge.
- Create no scratch or debug files; if unavoidable, under `.devin-scratch/` and it stays.
- Keep every new module under 250 lines.

## 7. Completion criteria

- [ ] `textbox.py` (`TextBoxInfo`, `detect_text_box`) under 250 lines, unverified bytes marked
- [ ] `prompt.py`, `console.py`, `agent.py`, `cli.py` edits as in section 3
- [ ] Tests in section 5 pass; `uv run pytest -q` green (paste the tail)
- [ ] Demo integration (section 2 item 4): `tools/explore_demo.py` imports from `pokeagent.textbox`; `uv run python -m py_compile tools/explore_demo.py` passes
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts, the three tile-map recipes as built in the tests with their detected `TextBoxInfo`, and any
place `CHARMAP` disagreed with the bytes in section 3.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Draft |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-02 · robert-claude-laptop · none → Draft — text-box awareness; needs Hex_Map_Discovery merged (screentext.py)
<!-- queue:end -->
