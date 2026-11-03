# PokeAgent: hex mapping - WRAM snapshot/diff, named-address registry, screen-text decoder, `pokeagent hex`

**Read first:** `docs/superpowers/specs/2026-11-02-pokeagent-design.md`. Build step 4; depends on
`Agent_Loop_And_CLI_Directive.md` being merged (it adds a subparser to `src/pokeagent/cli.py`). If `cli.py`,
`emulator.py` or `ram.py` is missing from your worktree, stop and write that in the Status row.

## 1. Why this exists

Robert asked (2026-11-02) for hex mapping: a way to detect which RAM bytes mean what, so the agent can be
controlled and interpreted from memory rather than guesswork. Today `ram.RAM_MAP` holds seven addresses
remembered from pret/pokered `wram.asm`, all marked UNVERIFIED. Nothing can confirm them except a human with a
hex editor. This directive gives the repo three tools:

1. **Snapshot/diff** of work RAM (`0xC000-0xDFFF`, 8 KiB) across button presses, with a "find" that keeps only
   the bytes that changed the expected way on every repeat (walk RIGHT three times -> which byte went +1 each
   time? that is X). This is how the seven addresses get calibrated, and how new ones get discovered.
2. **A named-address registry** (JSON data file) so any diff prints `D362 wXCoord 3 -> 4` instead of raw hex,
   and so `GameState` can grow from the registry later without touching code.
3. **A screen-text decoder**: the Game Boy's visible 20x18 tile map is believed to be mirrored at `0xC3A0`
   (`wTileMap`, 360 bytes) and Pokemon Red's text uses a fixed character map. Decoding it turns "what is on
   screen" (dialog, menus, the YES/NO box) into text the console can show and a later prompt can include, with
   no vision model.

Everything below about addresses and the charmap is a claim to verify, not a fact. The registry file marks
each entry `"verified": false` until the controller's calibration run flips it.

Verified facts: test command `uv run pytest -q` (Python 3.12.12). No ROM in your worktree; every test uses
`FakeEmulator`. `emulator.Emulator.read_range(start, length) -> bytes` exists (directive 1).

**Do not list the tree recursively** (`Get-ChildItem -Recurse`, `find`, `tree` are refused by the sandbox and
end the run). Use `git ls-files` if you need a list.

## 2. Scope

Create, in order:

1. `src/pokeagent/data/ram_names.json` and `src/pokeagent/names.py` (`Registry`, `load_registry()`).
2. `src/pokeagent/hexmap.py` (`snapshot`, `diff`, `Change`, `find_consistent`).
3. `src/pokeagent/screentext.py` (`CHARMAP`, `decode_text`, `read_screen_text(emu) -> list[str]`).
4. `pokeagent hex dump | diff | find | screen` subcommands in `cli.py` (one new file `src/pokeagent/cli_hex.py`
   holding the implementations; `cli.py` only registers the subparser).
5. Tests for each.

## 3. The work

### `ram_names.json` + `names.py`

Entry shape: `{"name": "wXCoord", "addr": "0xD362", "size": 1, "encoding": "u8", "verified": false,
"note": "player X on current map"}`. Encodings: `u8`, `u16le`, `u16be`, `bcd` (size N, big-endian digits),
`bitmask`, `bool`, `text` (charmap-decoded, size N), `bytes`. Seed the file with exactly these claims. All
`verified: false` EXCEPT four that the controller confirmed on the real ROM on 2026-11-02 with
`tools/make_baseline.py` (a fresh game read `map=0x26 pos=(3,6) money=3000`, i.e. REDS_HOUSE_2F at the
spawn tile with the starting 3000, and a RIGHT press in the bedroom changed `0xD362` 4->5): mark `wCurMap`, `wYCoord`, `wXCoord`, `wPlayerMoney` as
`"verified": true, "evidence": "make_baseline 2026-11-02"`.

| name | addr | size | encoding | note |
|---|---|---|---|---|
| wTileMap | 0xC3A0 | 360 | text | 20x18 visible screen tiles |
| wPlayerName | 0xD158 | 11 | text | 0x50-terminated |
| wPartyCount | 0xD163 | 1 | u8 | |
| wPartySpecies | 0xD164 | 7 | bytes | 0xFF-terminated |
| wPlayerMoney | 0xD347 | 3 | bcd | |
| wObtainedBadges | 0xD356 | 1 | bitmask | bit0 Boulder ... bit7 Earth |
| wCurMap | 0xD35E | 1 | u8 | |
| wYCoord | 0xD361 | 1 | u8 | |
| wXCoord | 0xD362 | 1 | u8 | |
| wIsInBattle | 0xD057 | 1 | u8 | 0 none, 1 wild, 2 trainer |
| wCurOpponent | 0xD059 | 1 | u8 | |
| wCurrentMenuItem | 0xCC26 | 1 | u8 | |
| wMaxMenuItem | 0xCC28 | 1 | u8 | |
| wJoyIgnore | 0xCD6B | 1 | bitmask | buttons the game is ignoring |
| wSpritePlayerFacing | 0xC109 | 1 | u8 | 0 down 4 up 8 left 0xC right |

`Registry`: `by_name`, `by_addr(addr) -> entry | None` (covers ranges: `0xC3A5` resolves to `wTileMap+5`),
`decode(entry, raw: bytes)`, `read(emu, name)`. `load_registry(path=None)` reads the packaged file via
`importlib.resources`.

### `hexmap.py`

- `WRAM_START = 0xC000`, `WRAM_LEN = 0x2000`.
- `snapshot(emu) -> bytes` via `read_range`.
- `Change(addr: int, old: int, new: int)`; `diff(before, after, base=WRAM_START) -> list[Change]`.
- `find_consistent(snaps: list[bytes], *, delta: int | None = None, base=WRAM_START) -> list[int]`: addresses
  that changed between every consecutive pair; with `delta` set, only those whose change equals `delta` every
  time (so walking RIGHT three times with `delta=1` isolates X). Also `exclude_noisy(snaps_idle: list[bytes])`
  helper: addresses that change while idle (timers, RNG) to subtract from candidates.
- `annotate(changes, registry) -> list[str]` formatting `D362 wXCoord 03 -> 04 (3 -> 4)`.

### `screentext.py`

`CHARMAP` as a dict `{int: str}` seeded with the pokered mapping (unverified): `0x7F` space, `0x80-0x99` A-Z,
`0xA0-0xB9` a-z, `0xF6-0xFF` 0-9, `0xE1` PK, `0xE2` MN, `0xE3` -, `0xE6` ?, `0xE7` !, `0xE8` ., `0xEF` male,
`0xF5` female, `0xF4` comma, `0xF3` /, `0xF1` x, `0xF0` money sign, `0x50` end marker, `0x4E`/`0x4F` newline,
`0x51`/`0x55`/`0x57`/`0x58` prompt/para markers. Unknown bytes decode to `?`. `decode_text(raw: bytes) -> str`
stops at `0x50`. `read_screen_text(emu, registry) -> list[str]`: 18 rows of 20 chars from `wTileMap`, each
row right-stripped; return only rows with any non-space character. Tile bytes outside the charmap (map
graphics) become `.` so a row of overworld tiles shows as dots and a dialog row shows as words.

### `cli_hex.py` subcommands (all boot headless; `--rom` default as in `run`; optional `--state PATH`)

- `hex dump --range D350-D370` - 16 bytes per line, hex, ASCII-ish, registry names in the margin.
- `hex diff --press RIGHT [--press A ...]` - snapshot, press each button in order, snapshot, print annotated diff.
- `hex find --press RIGHT --repeat 3 [--delta 1] [--idle 3]` - take `idle` idle snapshots first to build the
  noise set, then press/snapshot `repeat` times; print candidate addresses with names.
- `hex screen` - print `read_screen_text`.

## 4. What NOT to do

- Do not change `ram.py` / `RAM_MAP` or `GameState`; merging the registry into them is a follow-up after
  calibration.
- Do not mark any entry `verified: true`.
- Do not feed screen text into the prompt yet; that is a later directive once the decoder is confirmed.
- Do not add dependencies; do not open an SDL2 window; do not call the real ROM in tests.
- Do not read outside the worktree, download, or install.

## 5. Verification

- `uv run pytest -q` green. New tests at least: registry loads and `by_addr` resolves inside `wTileMap`;
  `decode` for each encoding (`bcd` of `01 23 45` -> 12345; `bitmask` -> list of set bits); `diff` on two 8 KiB
  buffers reports exactly the bytes changed; `find_consistent` with `delta=1` on four scripted snapshots
  returns only the one incrementing address and drops a noisy timer byte; `exclude_noisy`; `decode_text` of
  `80 81 82 7F A0 50 ...` -> `ABC a`; `read_screen_text` on a fake whose tile map holds one text row and 17
  rows of `0x00` returns that one row; each `hex` subcommand runs against `FakeEmulator` via the injectable
  emulator factory from directive 3 and prints the expected lines.
- `uv run pokeagent hex --help` lists `dump diff find screen`.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-hex-map-discovery-directive`. Never commit to `main`, never push to
  it, never merge.
- Create no scratch or debug files; if unavoidable, under `.devin-scratch/` and it stays.
- Keep every new module under 250 lines.

## 7. Completion criteria

- [ ] `data/ram_names.json` with the 15 seeded entries, all `verified: false`; `names.py` `Registry`
- [ ] `hexmap.py` with `snapshot`, `diff`, `find_consistent`, `exclude_noisy`, `annotate`
- [ ] `screentext.py` with `CHARMAP`, `decode_text`, `read_screen_text`
- [ ] `pokeagent hex dump|diff|find|screen` wired through `cli_hex.py`
- [ ] `uv run pytest -q` green (paste the tail)
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts, and the exact output of the `hex find` test so the controller can compare it with the
real-ROM calibration run.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-hex-map-discovery-directive |
| Base branch | - |
| Base commit | 2da9f9e8224d29d1251dad0bc848502128b377a9 |

**Status log**
- 2026-11-02 21:59 · robert-claude-laptop · none → Draft — build step 4; Robert asked for hex mapping 2026-11-02; queue after Agent_Loop_And_CLI merges
- 2026-11-02 22:37 · robert-claude-laptop · Draft → Queued — prereq Agent_Loop_And_CLI merged (PR #4); tile map 0xC3A0, charmap and border tiles 0x79-0x7E verified on the ROM today
- 2026-11-02 22:38 · robert-claude-laptop · Queued → Approved — lint override: greenfield directive: the cited new paths are files it creates; dispatch-path-missing is a false positive
- 2026-11-02 22:38 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-hex-map-discovery-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6FQS1FQGYQ6ZT9DDNGKB8T9
<!-- queue:end -->
