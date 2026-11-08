# Trailswarm: a sanitized, allow-list progress export from a maps.json-shaped file

**Size:** S. **Assignee:** devin.

## 1. Why this exists

The agents' shared memory, `runs/maps.json`, is the project's main learned asset: which tiles can be walked, which edges are blocked, where the doors go. It also holds text read from the game screen (NPC and sign dialogue, menu text, item text). Nobody can publish or share it today without hand-cleaning, and a deny-list would leak the next field someone adds.

Measured on 2026-11-08 from the real `runs/maps.json` (key names only; no text was read): 32 top-level keys and 70 map entries, with 16 distinct per-map keys. Most of them carry text or per-run state. This directive builds a function and a standalone tool that write a small shareable file by ALLOW-LIST: only fields named in the code are written, and every other field, known or future, is dropped by default.

This directive only exports. It does not read an export back, merge one into anything, or publish anything.

## 2. Scope

New files only. Each is single-purpose; no file over 600 lines.

1. `src/pokeagent/share/__init__.py` <!-- new: src/pokeagent/share/__init__.py --> - one-line docstring, imports nothing.
2. `src/pokeagent/share/progress_export.py` <!-- new: src/pokeagent/share/progress_export.py --> - the pure allow-list export function. No file I/O. Under 140 lines.
3. `tools/export_progress.py` <!-- new: tools/export_progress.py --> - standalone CLI (does NOT go through `src/pokeagent/cli.py`). Under 70 lines.
4. `tests/test_progress_export.py` <!-- new: tests/test_progress_export.py --> - the tests below.

## 3. The work

### Facts you need (pasted; do not go looking)

Real shape of a `maps.json` document, from `src/pokeagent/explorer/memory.py` and `tools/swarm_merge.py`, confirmed against key names in the real file:

Top-level keys (32): `maps, updated, tile_types, beats, grass_ids, enemy_damage, items, item_heal, menus, move_damage, team_best_level, damage_dealt, damage_taken, events, catches, training, battle_lessons, procedures, bad_warps, damage_by_type, type_effect, threat_by_species, mash_skill, blackout_tax, text_pace, text_speed, text_press_stats, interaction_stats, chart_disagreements, dv_records, trainers, loops`. The export reads only `maps`.

`maps` is `{"<map id as decimal string>": <map entry>}`. A map entry created by `Memory.m()`:

```python
{"visited": {}, "blocked": [], "warps": {}, "last_seen": 0}
```

Per-map keys seen in the real file: `visited, blocked, warps, last_seen, interactions, demos, warp_taken, npcs, encounters, fails, jumps, warp_cand, outcomes, items, warp_disproof, warp_disproof_total`; the code also writes `paths`.

Types and key formats (from the code above):

```
visited : {"x,y": int visit count}                      e.g. {"4,5": 12}
blocked : ["x,y,DIR", ...]                              DIR in UP DOWN LEFT RIGHT; e.g. "4,1,UP"
warps   : {"x,y,DIR": [dest_map, dest_x, dest_y]}       e.g. {"7,2,UP": [37, 3, 7]}
last_seen : int (a step counter)
jumps   : {"x,y,DIR": [x, y]}                           ledge hops
```

Text-bearing and other fields that must NOT be exported (examples, not a deny-list; the allow-list is what protects you):

```
interactions: {"x,y,DIR": {"count": int, "text": str, "presses": list, "effects": list,
                           "menus": list, "choices": list, "outcomes": dict, "screens": dict, "transitions": list, "npc": dict}}
npcs        : {"slotN:picM": {"pic": int, "slot": int, "positions": {"x,y": int}, "first_seen": int,
                              "text": str, "talked": int, "moves": bool, "last": [x, y], "results": dict}}
items       : {"x,y": {"pic": int, "text": str, "item": None-or-str, "seen": int, "picked": int}}
demos       : [{"at": [...], "facing": str, "screen": [str, ...], "buttons": [...], "achieved": [...], "source": str, ...}]
```

Top-level `menus`, `events`, `items`, `catches`, `trainers`, `battle_lessons` and `procedures` may hold names or text too. All of this is dropped because none of it is on the allow-list.

### The export function

`export_progress(doc: object, game: str) -> tuple[dict, ExportStats]` in `progress_export.py`. `ExportStats` is a frozen dataclass of ints: `maps_kept`, `maps_dropped`, `tiles_dropped`, `blocked_dropped`, `warps_dropped` (counts of malformed entries skipped).

The output, and nothing else:

```json
{
  "schema_version": 1,
  "kind": "trailswarm-progress-export",
  "game": "pokemon-red",
  "maps": {
    "37": {
      "walkable": [[3, 6], [3, 7]],
      "blocked": [[4, 1, "UP"]],
      "warps": [{"from": [7, 2, "UP"], "to": [0, 5, 6]}],
      "stats": {"walkable_tiles": 2, "blocked_edges": 1, "warps": 1, "total_visits": 14}
    }
  },
  "totals": {"maps": 1, "walkable_tiles": 2, "blocked_edges": 1, "warps": 1}
}
```

Rules:

- `game` must be in the constant `GAMES = ("pokemon-red", "pokemon-blue")`; anything else raises `ValueError`. Adding a game is a deliberate code edit.
- Constants at module top: `SCHEMA_VERSION = 1`, `KIND = "trailswarm-progress-export"`, `DIRS = ("UP", "DOWN", "LEFT", "RIGHT")`. Keep the list of output field names in ONE tuple, `OUTPUT_MAP_FIELDS = ("walkable", "blocked", "warps", "stats")`, so a test can pin it.
- Build every output value from parsed integers and the fixed `DIRS` words. NEVER copy a string, list or dict from the input into the output. That is what makes the allow-list real: a marker string cannot be carried by an int.
- Map id: the key must match `^\d{1,3}$` and be 0..255, else drop the map (`maps_dropped`). Output keys are decimal strings, sorted by integer value.
- `walkable`: from the KEYS of `visited`; each key must match `^(\d{1,3}),(\d{1,3})$` with both 0..255; the value must be an `int` (not `bool`) `>= 0`, else the tile is dropped (`tiles_dropped`). Output sorted `[x, y]` lists. `total_visits` is the sum of kept values.
- `blocked`: each item must be a string matching `^(\d{1,3}),(\d{1,3}),(UP|DOWN|LEFT|RIGHT)$`; output `[x, y, "DIR"]`, sorted, unique.
- `warps`: key must match the blocked format; value must be a list of exactly three ints, each 0..255 and not `bool`; output `{"from": [x, y, "DIR"], "to": [m, x, y]}`, sorted by `from`.
- A map entry that is not a dict is dropped. A `doc` that is not a dict, or has no `maps` dict, raises `ValueError`.
- Do not include `last_seen`, `visited` counts per tile, `jumps`, `npcs`, `interactions`, `items`, `demos`, `updated`, or anything else. Do not add a path, a user name, a hostname or a timestamp. The output is deterministic.
- Serialize in the CLI with `json.dumps(out, indent=1)` plus a newline (ASCII-escaped, the default).

### The CLI

```
uv run python tools/export_progress.py [MAPS_JSON] --game pokemon-red --out OUT.json
```

- `MAPS_JSON` defaults to `runs/maps.json`. `--game` is required, choices from `GAMES`. `--out` is required (no default path, so nothing is written to a surprising place).
- `main(argv: list[str] | None = None) -> int`. Exit 0 on success; exit 2 with a stderr message on unreadable JSON or a `ValueError`, writing no output file.
- Writes with a temp file in the same folder and `os.replace`.
- Prints one stderr summary line: `kept maps=N tiles=N blocked=N warps=N; dropped maps=N tiles=N blocked=N warps=N`.
- Never modifies the input file.

### Tests (names are the contract), in `tests/test_progress_export.py`

All input is synthetic and built inside the test.

- `test_shape_and_values`: a small valid doc exports exactly the documented shape, sorted, with the right stats and totals.
- `test_markers_in_every_text_and_unknown_field_never_reach_the_output_bytes`: THE key test. Build an input where unique marker strings (for example `MARK_A01` .. `MARK_A40`, each used once) are planted in: every text-bearing field in the pasted shapes (`interactions` text, presses, effects, menus, choices, outcomes keys, screens keys, transitions, npc; `npcs` text and positions keys and the slot key; `items` text and item; `demos` screen and buttons and source), top-level `menus`, `events`, `items`, `catches`, `trainers`, `battle_lessons`, `procedures`; several brand-new unknown keys at top level and inside a map entry and inside nested dicts (`future_field_x`); map id keys (`"37MARK_B"`); `visited` keys (`"3,6MARK_C"`) and values (`"MARK_D"`); `blocked` items (`"4,1,UPMARK_E"`); `warps` keys and values (`["MARK_F", 1, 2]`); and `updated`. Alongside, include valid data so the export is non-empty. Call `export_progress`, serialize with `json.dumps(out, indent=1)`, encode to bytes with `utf-8`, and assert that for every marker `marker.encode() not in raw`. Also assert the output is non-empty (`totals.maps >= 1`), so a blank export cannot pass by accident. Also run the same check through the CLI against a file on disk and read the written file's bytes.
- `test_unknown_future_field_is_dropped_by_default`: add `{"brand_new_stat": 5}` inside a map entry and at the top level; the output has no `brand_new_stat`, and the map's keys equal exactly `set(OUTPUT_MAP_FIELDS)`.
- `test_output_field_names_are_pinned`: assert `OUTPUT_MAP_FIELDS == ("walkable", "blocked", "warps", "stats")` and the top-level key set equals `{"schema_version", "kind", "game", "maps", "totals"}`. Adding a field must be a conscious test change.
- `test_rejects_unknown_game_and_bad_documents`: `ValueError` for `game="mario-land"`, for a non-dict doc, and for a doc with no `maps`.
- `test_malformed_entries_are_dropped_and_counted`: out-of-range ints, `bool` values, a 2-element warp destination, a non-dict map entry; each is dropped and the stats count it.
- `test_deterministic_and_input_not_mutated`: shuffle the input dict order; byte-identical output; the input equals a deep copy taken before.
- `test_cli_happy_path_and_bad_input`: via `main([...])`; exit 0 and a file on success; exit 2 and no output file on invalid JSON or an unknown game.
- `test_cli_does_not_modify_the_input_file`: compare bytes before and after.

## 4. What NOT to do

- No ROM, no emulator, no PyBoy. Tests use synthetic data only. No network, no downloads, nothing read outside the worktree.
- Do not read, copy, print or commit `runs/`, `kb/`, `baselines/` or `roms/`. They are not in your worktree, and that is correct. Do not look for a real `maps.json`; build the synthetic input from this directive.
- Do not write a deny-list or a "strip these keys" loop. The output is assembled from parsed integers only.
- Do not write an importer, a merge into `Memory`, `tools/swarm_merge.py` or any other store, or any code that reads an export back.
- Do not change `src/pokeagent/explorer/`, `src/pokeagent/game/`, `src/pokeagent/cli.py`, the emulator, or `tools/swarm_merge.py`. A separate Devin run is changing `game/` and `cli.py`.
- Do not publish, upload or commit any exported file. Do not add a dependency.
- Do not add a skip, `xfail` or a `needs_rom` marker.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

```
uv run pytest -q -p no:cacheprovider tests/test_progress_export.py
```
Expected: all pass, 0 skipped.

```
uv run pytest -q -p no:cacheprovider tests/test_swarm_merge_loops.py tests/test_swarm_merge_trainers.py
```
Expected: same result as on your base commit; no new failures.

```
uv run python -c "import pathlib; [print(p, len(p.read_text().splitlines())) for p in map(pathlib.Path, ['src/pokeagent/share/progress_export.py','tools/export_progress.py'])]"
```
Expected: each under 600 lines (targets are in section 2).

```
git diff --stat main -- src/pokeagent/explorer src/pokeagent/game src/pokeagent/cli.py tools/swarm_merge.py
```
Expected: no output.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here. If something expected is missing, stop and write that in the PR description.
- Use `uv run` and Python 3.12 only.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- Hard rules: no file over 600 lines; one purpose per module.
- If a tool call is genuinely blocked, stop and write why in the PR description.

## 7. Completion criteria

- [ ] No marker planted in any text-bearing or unknown field, key or value appears anywhere in the output bytes, in the function result or the CLI file. <!-- test: tests/test_progress_export.py -->
- [ ] The export is non-empty for valid data and has exactly the documented shape, with a game key and schema version 1. <!-- test: tests/test_progress_export.py -->
- [ ] A brand-new unknown field is dropped by default, and the output field names are pinned by a test. <!-- test: tests/test_progress_export.py -->
- [ ] Malformed entries are dropped and counted; bad documents and unknown games raise. <!-- test: tests/test_progress_export.py -->
- [ ] The CLI writes atomically, exits 2 without writing on bad input, and never modifies its input. <!-- test: tests/test_progress_export.py -->
- [ ] Nothing in the paths listed in section 4 changed; no new file is over 600 lines; nothing reads an export back.

## 8. Report

Findings first: confirm the output is assembled from parsed integers only, list any input shape in section 3 that did not match what you found in the code you were allowed to read (`src/pokeagent/explorer/memory.py` is in the worktree and you may read it), and the marker count used in the key test. Then the command tails from section 5.

## Required from User

Nothing during the run. Publishing any export is the owner's decision, made later and separately; this directive only builds the exporter.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(src/pokeagent/explorer/memory.py)
- Read(tools/swarm_merge.py)
- Write(src/pokeagent/share)
- Write(tools/export_progress.py)
- Write(tests/test_progress_export.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git diff)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-08 17:18 · robert-claude-laptop · none → Queued — Drafted by Claude at Robert's request 2026-11-08: allow-list export of map progress with no game text
<!-- queue:end -->
