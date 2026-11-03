# PokeAgent: map memory - visited tiles, blocked moves and warps per run, an ASCII map in the prompt, a transitions log

**Read first:** `docs/superpowers/specs/2026-11-02-pokeagent-design.md`. Depends on `Agent_Loop_And_CLI_Directive.md`
being merged (it is): `agent.py`, `prompt.py`, `runlog.py`, `console.py`, `cli.py`, `ram.py`, `emulator.py` must exist.
If any is missing from your worktree, stop and write that in the Status row. `src/pokeagent/textbox.py` (from
`Text_Box_Awareness_Directive.md`) may or may not be merged yet; section 3 says how to cope with both. **Do not list
the tree recursively** (`Get-ChildItem -Recurse`, `find`, `tree` are refused by the sandbox and end the run); use
`git ls-files`.

## 1. Why this exists

The agent wanders because it has no memory of where it has been: each step is a fresh `claude -p` call and the
only continuity is a free-text notes file. Robert wants it to remember the map and to see how many button presses the
opening really needs. Verified on the real ROM (2026-11-02):

- RAM: `0xD35E` map id (`0x26` = REDS_HOUSE_2F upstairs, `0x25` = downstairs), `0xD361` Y, `0xD362` X, `0xD347`
  money (3 bytes BCD, 3000 at start). The player spawns upstairs at (3,6); the baseline state is at (4,6). A RIGHT
  press in the bedroom changed `0xD362` 4 -> 5. Y grows downward (DOWN is y+1).
- `0xD163` party count and `0xD356` badges are still UNVERIFIED. The START menu showed POKeMON while `party_count`
  read 0, so treat `party_count` as suspect and do not build anything on it.
- Ground truth from Robert (2026-11-02): the staircase is in the upper-RIGHT corner of the upstairs room; the front
  door downstairs (map `0x25`) is at (3,7) or (4,7). These go into `docs/KNOWLEDGE.md` as ground truth for tests of
  the map memory, and are NOT fed to the agent prompt (the agent has to discover them).
- The baseline save state `baselines/bedroom.state` is gitignored and not in your worktree; the ROM is absent too.
  All tests use `FakeEmulator` (`.set(addr, value)`, `.memory`, `read_range` returns bytes). Test command
  `uv run pytest -q` (Python 3.12). No new dependencies.

## 2. Scope

Create, in order:

1. `src/pokeagent/mapmem.py` - `MapMemory`, `render_ascii`.
2. `src/pokeagent/transitions.py` - `transition_record(...)`, `TransitionWriter`.
3. Edits: `prompt.py` (`map_view`), `agent.py` (feed memory, write `maps.json` and `transitions.jsonl`).
4. `docs/KNOWLEDGE.md` (new, short, see below).
5. `tests/test_mapmem.py`, `tests/test_transitions.py`, additions to the prompt and agent tests.
6. Demo integration: `tools/explore_demo.py` replaces its local `MapMemory` class with `pokeagent.mapmem.MapMemory` (same runs/maps.json file, same schema); the demo's extra fields (interactions presses/menus/choices) must survive a load/save round-trip.

## 3. The work

### `mapmem.py`

Positions are `(map_id: int, x: int, y: int)`. Directions are the strings `UP DOWN LEFT RIGHT` with deltas
UP (0,-1), DOWN (0,+1), LEFT (-1,0), RIGHT (+1,0).

```python
class MapMemory:
    def __init__(self) -> None: ...
    def record_step(self, step: int, before: tuple[int,int,int], button: str,
                    after: tuple[int,int,int], textbox_kind: str = "none") -> None
    def view(self, map_id: int, x: int, y: int, radius: int = 6) -> str       # ascii + counts, for the prompt
    def to_json(self) -> dict;  @classmethod from_json(cls, d: dict) -> "MapMemory"
    def save(self, path: Path) -> None;  @classmethod load(cls, path: Path) -> "MapMemory"
def render_ascii(mem: MapMemory, map_id: int, x: int, y: int, radius: int = 6) -> str
```

`record_step` always marks `after` visited (count +1; the map's `last_seen = step`; also mark `before` once so the start tile
exists). Then, only when `button` is a direction: if `after` differs in map id, store
`warps[(m, x, y, dir)] = after`; else if `after == before` and `textbox_kind == "none"`, add `(m, x, y, dir)` to
`blocked`; else (moved) remove `(m, x, y, dir)` from `blocked` if present (a blocked guess that proved wrong, for
example a turn-in-place press). With a text box open, nothing is learned except visits. Non-direction buttons learn
nothing. If `textbox.py` is not on `main`, the agent passes `"none"`. Human presses (from the viewer) reach `record_step` through the same hook as agent presses, so human moves are learned too.

`render_ascii` returns `2*radius+1` lines of `2*radius+1` characters (no trailing strip), joined by `"\n"`, rows
`y-radius..y+radius`, columns `x-radius..x+radius`. Priority per cell: `@` the player; `W` a tile that has any warp
leaving it; `.` visited; `#` the tile you could not enter (the neighbour of a blocked `(x,y,dir)`), only if not
visited; space unknown. `view()` returns that block, then two lines: `Tiles visited on this map: N` and
`Unexplored directions from here: UP, DOWN` (directions whose neighbour is neither visited nor blocked-from-here;
`none` when empty).

JSON shape, EXACT (a demo being written elsewhere reads this file with the real module; map ids are decimal
strings, tuples are comma strings):
`{"maps": {"38": {"visited": {"4,6": 3}, "blocked": ["4,6,UP"], "warps": {"4,6,LEFT": [37, 3, 6]}, "last_seen": 12}},
"updated": "2026-11-02T22:40:00"}`. `visited` maps `"<x>,<y>"` to the visit count; `blocked` is a list of
`"<x>,<y>,<DIR>"`; `warps` maps `"<x>,<y>,<DIR>"` to `[new_map, new_x, new_y]` and lives inside its map (keyed by the
map you left); `last_seen` is the step of the latest visit to that map; `updated` is an ISO timestamp set on every
`to_json`. In memory, `last_seen` is per map (drop any per-tile last_seen). Round-trip must be lossless apart from
`updated`. `load` must tolerate a missing file (empty memory). Per map, an optional `"interactions": {"<x>,<y>,<DIR>": {"count": n, "text": "<first dialog text or empty when nothing happened>"}}` is recorded when an A press is made facing DIR: a text box opened stores its text; nothing opened stores an empty text, so a silent wall is tested once. The explorer demo (`tools/explore_demo.py`) already writes this key, and the module must load it.

### `--maps PATH`

`pokeagent run --maps PATH` loads an existing `maps.json` into the `MapMemory` before step 1 (default
`runs/maps.json`, shared across runs; absent file = empty memory). The agent saves to that shared path every step and
also saves a per-run copy to `runs/<ts>/maps.json` at the end of the run (and each step, as above). Memory therefore
accumulates across runs. `Agent.__init__` gains `map_memory: MapMemory | None = None` and `maps_path: Path | None
= None`; `cli.py` builds them from `--maps`.

### `transitions.py` and the agent

`transition_record(step, before, button, after, textbox_kind) -> dict` returns at least these keys:
`{"step": 12, "from": [38, 4, 6], "button": "RIGHT", "to": [38, 5, 6], "moved": true, "textbox": "none"}`
(`moved` is `before != after`; `textbox` is the kind detected BEFORE the press). `TransitionWriter(path)` has
`write(record)` appending one JSON line to `runs/<ts>/transitions.jsonl`. In `Agent`, per step: read the position
before the press, press, read it again, then `mem.record_step(...)`, `writer.write(...)`, and
`mem.save(maps_path)` (and the per-run copy `run_dir / "maps.json"`; the run directory is the one `RunLog` already created; read `runlog.py` for its
real attribute). The text-box kind comes from `detect_text_box(emu.read_range(0xC3A0, 360)).kind` if
`pokeagent.textbox` imports (use `try/except ImportError` once at module level), else `"none"`. This makes "A presses
through the opening" and every move result measurable from `transitions.jsonl` alone.

### `prompt.build_prompt`

Add `map_view: str | None = None` (keyword, last). When set, insert after the recent-steps lines a section
`## Map memory (what you have explored)` containing the `view()` text and the legend line
`@ you, . visited, # blocked, W warp/door, blank unknown. Y grows downward.` With `None` the prompt is unchanged.
The agent passes `mem.view(state.map_id, state.x, state.y)`.

### `docs/KNOWLEDGE.md`

Headed "Ground truth - for tests and humans, not fed to the agent": Robert's two facts, the verified RAM addresses,
charmap and border tiles (section 1 here and in `Text_Box_Awareness_Directive.md`), and the UNVERIFIED list.

## 4. What NOT to do

- Do not modify `tools/make_baseline.py`, `emulator.py`, `ram.py`, `backend.py`, `decision.py`.
- Do not put the staircase or door facts (or any coordinates from `KNOWLEDGE.md`) in the prompt or in `mapmem.py`.
- No pathfinding, stuck detection, vision or auto-movement; memory and display only.
- No dependencies, no SDL2 window in tests, no reads outside the worktree.

## 5. Verification

- `uv run pytest -q` green. New tests at least: an unchanged direction press with no text box adds the blocked edge;
  the same press with `textbox_kind="dialog"` adds nothing but a visit; a map-id change stores the warp
  `(0x26,4,6,"LEFT") -> (0x25,3,6)` shape; a later successful move through a blocked edge removes it; non-direction
  buttons learn nothing; `render_ascii` for a tiny scripted memory returns exactly this string (map 38, visits (4,6) and
  (5,6), blocked `(5,6,RIGHT)` and `(4,6,UP)`, warp from `(38,4,6,"LEFT")`, player (5,6), `radius=2`):
  `"     \n #   \n W@# \n     \n     "`; `view()` counts and the `Unexplored directions` line; `to_json`/`from_json` and
  `save`/`load` round-trip in `tmp_path`; `to_json` for a scripted memory equals the section 3 example exactly (except
`updated`); a missing path loads as empty memory; `--maps` accumulates across two runs; `transition_record` has
  at least the six keys of section 3 (the demo adds `text`, `facing` and `source`); `TransitionWriter` writes valid JSON lines; an `Agent` run on a `FakeEmulator` (scripted `StubBackend`) leaves `maps.json` and a
  `transitions.jsonl` with one line per step; `build_prompt` with `map_view` contains the heading and legend, and
  without it is identical to the old output; `docs/KNOWLEDGE.md` exists and mentions `0x26` and `upper-RIGHT`.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-map-memory-directive`. Never commit to `main`, never push to it, never
  merge.
- Create no scratch or debug files; if unavoidable, under `.devin-scratch/` and it stays.
- Keep every new module under 250 lines.

## 7. Completion criteria

- [ ] `mapmem.py` (`MapMemory`, `render_ascii`) and `transitions.py` under 250 lines each
- [ ] `prompt.py`, `agent.py`, `cli.py` (`--maps`) edits; `maps.json` and `transitions.jsonl` written per run
- [ ] `docs/KNOWLEDGE.md` created with the ground-truth facts
- [ ] Tests in section 5 pass; `uv run pytest -q` green (paste the tail)
- [ ] Demo integration (section 2 item 6): `tools/explore_demo.py` uses `pokeagent.mapmem.MapMemory`; interaction fields survive a load/save round-trip
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts, a sample `transitions.jsonl` line, the 13x13 map from a scripted run, and whether
`pokeagent.textbox` was importable.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Draft |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-02 · robert-claude-laptop · none → Draft — map memory + transitions log; Agent_Loop merged; text box directive optional
<!-- queue:end -->
