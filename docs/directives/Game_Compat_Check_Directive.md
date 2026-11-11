# PokeAgent: game compatibility check - a repeatable report comparing two games' map memory files and RAM address tables, with pass/fail against stated thresholds

**Size:** S. **Assignee:** devin.

**Depends on `Brain_Compare_And_Run_Reports_Directive.md` merged** (adjusted 2026-11-08 so the map comparison has one implementation): it provides `src/pokeagent/brain/ledges.py` (`classify_wall`, `opposite`, `parse_edge`) and `src/pokeagent/brain/compare.py` (`compare_memory`). Import them; do not rebuild them. If they are missing, stop and write that in the Status row. Otherwise no dependency on the other Multi_Game directives: this reads files and needs no `GameSpec`. `Family_Shared_Memory_Directive.md` imports `src/pokeagent/compat/ledges.py` from here, so this one merges first (that module is now a one-line re-export of the brain one). It is the gate for Yellow (plan phase 10): Yellow does not join the `gen1-pokemon` memory family until this report passes between Yellow and the Red/Blue family.

## 1. Why this exists

On 2026-11-08 Red's `runs/maps.json` (gitignored, so missing in a fresh worktree) was compared by hand with a Blue run's `maps.json` (15 maps up to Viridian Forest; the Blue run had human interaction, so the numbers are early evidence, not a verdict). The result decided the direction "share memory between Red and Blue, plan Yellow after confirming cross compatibility":

- 2,170 of 2,203 Blue tiles already known to Red.
- 21 warps in common, none different.
- 35 of 35 stationary NPCs in the same place.
- 210 of 2,127 Red walls lie between two tiles Blue stood on (126 on Route 1, which has ledges). Cause UNCONFIRMED: one-way ledges or transient NPCs are the guess.

That comparison lived in a throwaway script, so it cannot be repeated for Yellow or re-run when Blue has a clean baseline. This directive turns it into a tool. The script, verbatim (you cannot read outside your worktree; this is the reference for the numbers above):

```python
"""Read-only: does Red's learned map memory agree with what a Blue run actually walked?"""
import json
import sys
from collections import Counter

RED, BLUE = sys.argv[1], sys.argv[2]
red = json.load(open(RED, encoding="utf-8"))["maps"]
blue = json.load(open(BLUE, encoding="utf-8"))["maps"]
DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}


def tiles(m):
    return set(m.get("visited", {}))


def blocked(m):
    return set(m.get("blocked", {}))


def warp_keys(m):
    w = m.get("warps", {})
    if isinstance(w, dict):
        return {k: json.dumps(v, sort_keys=True)[:80] for k, v in w.items()}
    return {json.dumps(x, sort_keys=True)[:80]: "" for x in w}


def static_npcs(m):
    out = set()
    for n in m.get("npcs", {}).values():
        if isinstance(n, dict) and not n.get("moves") and n.get("last"):
            out.add((n.get("pic"), tuple(n["last"])))
    return out


shared = sorted(set(red) & set(blue), key=int)
tot = Counter()
rows = []
for mid in shared:
    r, b = red[mid], blue[mid]
    rt, bt = tiles(r), tiles(b)
    conflicts = 0   # Red says an edge is blocked, but Blue stood on its destination AND on its source
    for e in blocked(r):
        x, y, d = e.split(",")
        dx, dy = DIRS[d]
        src, dst = f"{x},{y}", f"{int(x) + dx},{int(y) + dy}"
        if src in bt and dst in bt:
            conflicts += 1
    rw, bw = warp_keys(r), warp_keys(b)
    common = set(rw) & set(bw)
    wdiff = sum(1 for k in common if rw[k] != bw[k])
    rn, bn = static_npcs(r), static_npcs(b)
    tot.update(blue_tiles=len(bt), overlap=len(bt & rt), blue_only=len(bt - rt), conflicts=conflicts, blocked_red=len(blocked(r)),
               warps_common=len(common), warps_diff=wdiff, warps_blue_only=len(set(bw) - set(rw)),
               npc_blue=len(bn), npc_match=len(bn & rn))
```

Shapes it reads (real, from `runs/maps.json` on 2026-11-08): `{"maps": {"<map_id>": {"visited": {"x,y": count}, "warps": {"x,y,BUTTON": [dest_map, dest_x, dest_y]}, "blocked": ["x,y,BUTTON", ...], "jumps": {"x0,y0,BUTTON": [landing_x, landing_y]}, "npcs": {"<key>": {"pic": .., "slot": .., "positions": {"x,y": n}, "moves": bool, "last": [x, y], ...}}, ...}}}`. A `blocked` entry `"x,y,BUTTON"` means pressing BUTTON on tile (x,y) did not move you. A ledge hop is a `jumps` entry; `MapMemory.learn` (`src/pokeagent/explorer/memory.py`) then also appends the back-edge from the landing tile to `blocked`:

```python
self.m(m0).setdefault("jumps", {})[key] = [x1, y1]          # key = f"{x0},{y0},{button}"
back = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}[button]
bk = f"{x1},{y1},{back}"
```

The RAM address table is `src/pokeagent/data/ram_map.json`, a JSON list of entries like:

```
{"name": "wCurMap", "addr": "0xD35E", "size": 1, "encoding": "u8", "region": "map", "verified": true, "source": "pokered.sym (pret/pokered, symbols branch)", "sym": "wCurMap", "evidence": "make_baseline 2026-11-02"}
{"name": "wMapPalOffset", "addr": "0xD35D", "size": 1, "encoding": "u8", "region": "map", "verified": false, ...}
```

2,792 entries today; `verified` is true only where a real read was checked. A second game's table has the same shape.

A visited-both-ends edge is only a SUSPECT wall conflict, not proof: standing on both tiles does not prove you crossed the edge. The report must therefore split the raw count into ledge-explained and unexplained walls (section 3, `ledges.py`).

## 2. Scope

New package `src/pokeagent/compat/` and a thin CLI. Only these files:

1. `src/pokeagent/compat/__init__.py` <!-- new: src/pokeagent/compat/__init__.py --> - re-exports `compare_memory` (from `pokeagent.brain.compare`), `compare_addresses`, `build_report`.
2. `src/pokeagent/compat/ledges.py` <!-- new: src/pokeagent/compat/ledges.py --> - a re-export only (`from pokeagent.brain.ledges import classify_wall, opposite, parse_edge`), so existing importers keep working. Under 10 lines.
3. (removed: the map comparison is `pokeagent.brain.compare.compare_memory`; there is no maps module under `src/pokeagent/compat`.)
4. `src/pokeagent/compat/addresses.py` <!-- new: src/pokeagent/compat/addresses.py --> - address-table comparison. Under 80 lines.
5. `src/pokeagent/compat/thresholds.py` <!-- new: src/pokeagent/compat/thresholds.py --> - the proposed thresholds and the verdict function. Under 100 lines.
6. `src/pokeagent/compat/report.py` <!-- new: src/pokeagent/compat/report.py --> - assembles the JSON report and the plain summary. Under 100 lines.
7. `tools/game_compat.py` <!-- new: tools/game_compat.py --> - argument parsing and file IO only. Under 80 lines.
8. Tests (listed in the criteria) and a paragraph in `docs/KNOWLEDGE.md`.

## 3. The work

### Inputs and CLI

`uv run python tools/game_compat.py --baseline PATH --candidate PATH [--baseline-addresses PATH --candidate-addresses PATH] [--thresholds PATH] [--baseline-name NAME --candidate-name NAME] [--out PATH]`.

- `--baseline` and `--candidate` are map memory files (`maps.json` shape above). Baseline is the family memory (for example Red's), candidate is the game under test (for example a Blue or Yellow run). Compare over the maps present in BOTH.
- The two address-table arguments are optional and come as a pair; both absent means the address section is `"skipped"`, not passed.
- Output: the JSON report to `--out` (or stdout), then a plain summary of at most 15 lines on stdout. Exit code 0 on `pass`, 1 on `fail`, 3 on `insufficient`, 2 on bad input (a missing or malformed file: print `error: <message>`, never a traceback). Never writes under `runs/` or `kb/` and never reads a ROM.

### ledges.py (wall classifier): specified and built in `Brain_Compare_And_Run_Reports_Directive.md` as `src/pokeagent/brain/ledges.py`; the contract below is unchanged. Do not reimplement it.

`classify_wall(map_doc: dict, edge: str) -> str` returns one of:

- `"ledge_exact"`: `edge` equals the back-edge of a recorded jump in `map_doc["jumps"]`: for each `"x0,y0,B"` -> `[x1,y1]` the edge `f"{x1},{y1},{opposite(B)}"`. Certain: it is the rule `learn()` uses to create it.
- `"ledge_row"`: HEURISTIC. The edge's direction is the opposite of some recorded jump's direction `B`, and the edge's source tile lies on the same row (for UP/DOWN jumps) or column (for LEFT/RIGHT jumps) as that jump's landing tile, in the same map. It covers unjumped columns of a ledge row. It can be wrong on a map with two ledges in one row; every report line that counts it says "heuristic".
- `"plain"`: anything else.

Also export `opposite(button)` and `parse_edge(edge) -> (x, y, button)` (a `ValueError` on a malformed edge; callers count malformed edges as `plain` and report the count). No ROM access.

### Map comparison: specified and built in `Brain_Compare_And_Run_Reports_Directive.md` as `pokeagent.brain.compare.compare_memory`; the contract below is unchanged. `report.py` calls it. Do not reimplement it.

`compare_memory(baseline: dict, candidate: dict) -> dict` over the shared map ids. Return per-map rows and totals:

- `tiles`: candidate tiles, how many the baseline also has (`overlap`), `candidate_only`.
- `warps`: `common` (same `"x,y,BUTTON"` key in both), `different` (common with a different destination), `candidate_only`.
- `npcs`: candidate stationary NPCs (`moves` falsy and `last` present, identified by `(pic, tuple(last))` as in the script), and how many the baseline also has.
- `walls`: for each baseline wall edge whose source AND destination tile the candidate visited (`suspect`, the script's `conflicts`): split by `classify_wall(baseline_map, edge)` into `ledge_exact`, `ledge_row`, `plain`. `unexplained` is the `plain` count. Also `baseline_walls` (total baseline edges on shared maps) for the denominator, and `malformed`.
- Rows list the worst 10 maps by `unexplained` then by `candidate_only`.

Counts are integers; ratios are computed in `thresholds.py` and rounded to 4 places, with a zero denominator giving `null` (never a division error and never an automatic pass).

### addresses.py

`compare_addresses(baseline: list, candidate: list) -> dict`: match entries by `name`. Report: `names_baseline`, `names_candidate`, `in_both`, `only_baseline`, `only_candidate` (counts, plus the first 20 names of each only-list), `addr_different` (in both, different `addr`; list up to 20 with both addresses), `verified_in_baseline` (count of baseline entries with `verified` true), `verified_present` (of those, present in the candidate), `verified_addr_different` (of those present, different `addr`).

### thresholds.py (PROPOSALS, labelled as such everywhere)

`PROPOSED = {...}` with a docstring and a report field `"thresholds_status": "proposed"`. The values are proposals the owner may change; a `--thresholds` JSON file overrides any key and the report records which keys were overridden. Proposals, each with the 2026-11-08 Blue-versus-Red measurement beside it:

| Key | Proposed rule | Measured 2026-11-08 |
|---|---|---|
| `min_shared_maps` | at least 10 shared maps, else verdict `insufficient` | 15 |
| `min_candidate_tiles` | at least 500 candidate tiles on shared maps, else `insufficient` | 2,203 |
| `tile_overlap_min` | `overlap / candidate_tiles >= 0.95` | 2,170 / 2,203 = 0.985 |
| `warps_common_min` | at least 10 common warps, else `insufficient` | 21 |
| `warps_different_max` | 0 different warps among common | 0 |
| `npc_match_min` | `matching / candidate stationary NPCs >= 0.95`, with at least 20 NPCs | 35 / 35 |
| `wall_unexplained_max` | `unexplained / baseline_walls <= 0.02` (ledge-explained edges excluded) | UNMEASURED: 210 / 2,127 = 0.099 raw suspects before the ledge split |
| `verified_addr_different_max` | 0 verified entries with a different address (only when tables are given) | UNMEASURED |
| `verified_present_min` | `verified_present / verified_in_baseline >= 0.95` (only when tables are given) | UNMEASURED |

Verdict: `fail` if any rule with enough evidence is violated; else `insufficient` if any minimum-evidence rule is not met; else `pass`. An address section that was skipped does not block `pass` but the summary says "addresses: skipped". Return the per-rule table (`rule`, `value`, `threshold`, `status` of `pass|fail|insufficient|skipped`) in the report.

### report.py and the summary

JSON keys: `schema` (1), `generated` (ISO time), `baseline_name`, `candidate_name`, `inputs` (the file paths as given, and each file's sha256 so a rerun is recognisable), `memory` (`compare_memory` result), `addresses`, `thresholds_status`, `rules`, `verdict`. The plain summary prints the verdict first, then one line per rule, then the worst three maps, then "thresholds are proposals". It prints no ROM data and no absolute personal paths beyond what the caller passed.

## 4. What NOT to do

- Do not read, write or require a ROM, a save state, `roms/`, `baselines/`, or any file under the real `runs/` or `kb/`. The only inputs are the files named on the command line; tests build their own with `tmp_path`.
- Do not state where any game copy came from, anywhere.
- Do not change `src/pokeagent/data/ram_map.json`, `explorer/memory.py`, `tools/swarm_merge.py`, or any existing file other than `docs/KNOWLEDGE.md`.
- Do not add a dependency or import `pyboy`; do not register a game or touch `game/`.
- Do not hard-code the thresholds in the CLI: they live only in `thresholds.py`.
- Do not edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file.
- No scratch or debug files outside `.devin-scratch/`.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
uv run pytest -q tests/test_compat_addresses.py tests/test_compat_thresholds.py tests/test_compat_cli.py
```
Expected: `Python 3.12.x`; all pass, none skipped.

```
uv run python tools/game_compat.py --baseline tests/fixtures/compat/baseline_maps.json --candidate tests/fixtures/compat/candidate_maps.json
```
Expected: prints a verdict line first and exits 0 (the fixtures are hand-written, small and committed; <!-- new: tests/fixtures/compat/baseline_maps.json --> <!-- new: tests/fixtures/compat/candidate_maps.json --> they must contain no real run data).

```
uv run pytest -q
git diff --stat main -- src/pokeagent/explorer tools/swarm_merge.py
```
Expected: no new failures against main's tail; the diff stat prints nothing.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here; if something expected is missing, stop and write that in the Status row.
- Use `uv run` and Python 3.12 only. Tests are synthetic and headless.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the `directive/pokeagent-game-compat-check-directive` branch; commit as you go.
- Status row done means `Review` with a pushed branch.
- If a tool call is genuinely blocked, stop and write why in the Status row.

## 7. Completion criteria

- [ ] `src/pokeagent/compat/ledges.py` re-exports the brain implementation, and importing `classify_wall` from `pokeagent.compat.ledges` works. <!-- test: tests/test_compat_cli.py -->
- [ ] The report's `memory` section is the output of `pokeagent.brain.compare.compare_memory` on the two inputs (the comparison itself is tested by `tests/test_brain_compare.py`). <!-- test: tests/test_compat_cli.py -->
- [ ] `compare_addresses` counts in-both, only-in-one, different addresses and the verified subset on two small synthetic tables. <!-- test: tests/test_compat_addresses.py --> <!-- new: tests/test_compat_addresses.py -->
- [ ] The verdict is `pass` for a fixture meeting every proposed threshold, `fail` when one rule is violated (one case per rule), and `insufficient` below each minimum; a zero denominator never yields `pass`; a `--thresholds` override changes the verdict and is recorded in the report. <!-- test: tests/test_compat_thresholds.py --> <!-- new: tests/test_compat_thresholds.py -->
- [ ] The CLI writes valid JSON with every key in section 3, prints the verdict first and says "proposals", returns exit codes 0, 1, 3 and 2 as stated, and never creates a file under `runs/` or `kb/`. <!-- test: tests/test_compat_cli.py --> <!-- new: tests/test_compat_cli.py -->
- [ ] No test or fixture needs a ROM, and no existing file other than `docs/KNOWLEDGE.md` changed.

## 8. Report

Findings first: the verdict and rule table for the committed fixtures, any proposed threshold you could not implement as stated, and any real-data surprise (there should be none: say so). Then the command tails from section 5, the diff stat and each new file's line count. State that no real run data was used.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.
- Do not touch `roms/`, `baselines/` or ROM data, and do not state where a game copy came from.

## Sandbox needs

- Read(src/pokeagent/explorer/memory.py)
- Read(src/pokeagent/data/ram_map.json)
- Exec(uv run python --version)
- Exec(uv run python tools/game_compat.py)
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
- 2026-11-08 17:54 · robert-claude-laptop · none → Queued — Approved by Robert 2026-11-08: repeatable compatibility check, the gate for Yellow; plan phase 4a, after phase 4
<!-- queue:end -->
