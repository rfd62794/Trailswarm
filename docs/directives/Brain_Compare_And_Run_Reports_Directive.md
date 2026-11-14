# Trailswarm: `brain compare`, `brain assists` and `brain seed` replace three one-off scratch scripts

**Size:** M. **Assignee:** devin.

## 1. Why this exists

On 2026-11-08 three jobs were done with throwaway scripts that cannot be repeated or tested: comparing two games' map memory, measuring how much human help a run got, and porting one memory into a seeded copy. They belong in the existing `pokeagent brain` tooling (`src/pokeagent/cli_brain.py`, pure logic in `src/pokeagent/brain/`, standalone entry `tools/brain.py`). Brain modules stay at or under 300 lines (the limit `Brain_Tools_Directive.md` set) and no file goes over 600.

Evidence, measured 2026-11-08 (counts only):

- Compare, Red's `runs/maps.json` against a Blue run's (both gitignored, so missing in a fresh worktree): 2,170 of 2,203 Blue tiles already known to Red; 21 warps in common, none different; 35 of 35 stationary NPCs in the same place; 210 of 2,127 Red walls lie between two tiles Blue stood on (126 on Route 1, which has ledges). Cause of the 210 UNCONFIRMED: one-way ledges or transient NPCs are the guess.
- Assists: a run with human presses mixed in could not be told apart from an unaided one, so "did the agent reach this milestone itself" was answered by eye.
- Seed: porting everything Red learned into a new file, dropping the per-map wild encounter tables and the shared dead-move table (`loops`), was a six-line script.

### Overlap with `Game_Compat_Check_Directive.md` and how it is reconciled

`docs/directives/Game_Compat_Check_Directive.md` (queued) plans the same map comparison under `src/pokeagent/compat/` with its own `ledges.py` and `maps.py`. **This directive owns the comparison implementation**: `src/pokeagent/brain/compare.py` and `src/pokeagent/brain/ledges.py`. The Game_Compat directive was edited on this branch to import them instead of building its own, and it keeps its address-table comparison, thresholds, report and the compat CLI. So this directive merges first; Game_Compat and `Family_Shared_Memory_Directive.md` (which imports the compat ledges module, kept as a one-line re-export) follow.

### The scratch sources, pasted (you cannot read them)

The comparison script. Port its checks; do not copy its `sys.argv` and `print` style. A is the baseline ("red"), B the candidate ("blue").

```python
DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}

def tiles(m):    return set(m.get("visited", {}))
def blocked(m):  return set(m.get("blocked", {}))     # list of "x,y,BUTTON"

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

shared = sorted(set(red) & set(blue), key=int)       # only maps present in both
for mid in shared:
    r, b = red[mid], blue[mid]
    rt, bt = tiles(r), tiles(b)
    conflicts = 0   # red says an edge is blocked, but blue stood on its destination AND on its source
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
    # totals: blue_tiles=len(bt), overlap=len(bt & rt), blue_only=len(bt - rt), conflicts, blocked_red=len(blocked(r)),
    #         warps_common=len(common), warps_diff=wdiff, warps_blue_only=len(set(bw) - set(rw)),
    #         npc_blue=len(bn), npc_match=len(bn & rn)
```

Shapes (real, from `runs/maps.json` on 2026-11-08): `{"maps": {"<map_id>": {"visited": {"x,y": count}, "warps": {"x,y,BUTTON": [dest_map, dest_x, dest_y]}, "blocked": ["x,y,BUTTON", ...], "jumps": {"x0,y0,BUTTON": [landing_x, landing_y]}, "npcs": {"<key>": {"pic": .., "slot": .., "positions": {"x,y": n}, "moves": bool, "last": [x, y], ...}}, ...}}}`. A `blocked` entry `"x,y,BUTTON"` means pressing BUTTON on tile (x,y) did not move you. A ledge hop is a `jumps` entry, and `MapMemory.learn` (`src/pokeagent/explorer/memory.py`) then also appends the back-edge from the landing tile to `blocked`:

```python
self.m(m0).setdefault("jumps", {})[key] = [x1, y1]          # key = f"{x0},{y0},{button}"
back = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}[button]
bk = f"{x1},{y1},{back}"
```

The seed script:

```python
data = json.load(open(src, encoding="utf-8"))
dropped = 0
for m in data["maps"].values():
    if m.pop("encounters", None) is not None:
        dropped += 1
loops = len(data.pop("loops", {}) or {})
json.dump(data, open(dst, "w", encoding="utf-8"))
print("maps:", len(data["maps"]), "encounter tables dropped:", dropped, "dead-move entries dropped:", loops, "top-level keys kept:", len(data))
```

Run-directory files `brain assists` reads (real shapes, from `src/pokeagent/explorer/press.py` and `press_goals.py`):

- `transitions.jsonl`, one JSON object per press: `{"step": int, "from": [map, x, y], "button": "A", "to": [map, x, y], "moved": bool, "textbox": "dialog" or "none", "text": str, "facing": "UP", "source": "agent" or "human" or "claude" (any other string is a non-assist driver), ...}`. `source` human or claude marks a press made by a person or by Claude through the control server; those are the assists.
- `goal_frames.jsonl`, one object per goal first reached in the run: `{"goal": "<goal id>", "step": int, "frame": int}`.
- `meta.json`: an object that may hold `"initial_goals": [goal ids]`, goals already done at the start (a missing key means none).
- The goal ladder, in order, is `pokeagent.goals.GOALS` (a list of ids). The stage at a step is the first goal that is neither an initial goal nor reached at or before that step, or `"done"`. This is the same first-unreached rule as `explorer.decisions.goal_stage`, which reads one goals dict and has no step argument, applied here per step over the step-indexed goal frames.

## 2. Scope

In order:

1. `src/pokeagent/brain/ledges.py` <!-- new: src/pokeagent/brain/ledges.py --> and `src/pokeagent/brain/compare.py` <!-- new: src/pokeagent/brain/compare.py -->, then `brain compare`.
2. `src/pokeagent/brain/assists.py` <!-- new: src/pokeagent/brain/assists.py --> , then `brain assists`.
3. `src/pokeagent/brain/seed.py` <!-- new: src/pokeagent/brain/seed.py --> , then `brain seed`.
4. `src/pokeagent/cli_brain_runs.py` <!-- new: src/pokeagent/cli_brain_runs.py --> : the three subcommands' argparse and emit only, attached by one small call in `cli_brain.py`'s `_add_commands`; export the logic functions from `src/pokeagent/brain/__init__.py`.
5. Tests: `tests/test_brain_compare.py` <!-- new: tests/test_brain_compare.py -->, `tests/test_brain_assists.py` <!-- new: tests/test_brain_assists.py -->, `tests/test_brain_seed.py` <!-- new: tests/test_brain_seed.py -->.

## 3. The work

### brain compare A B

`uv run python tools/brain.py compare A.json B.json [--text]`. A is the baseline, B the candidate; both are plain maps files (no journal is applied; this compares what the files say). Output JSON (sorted keys) or `--text`.

- `ledges.py`: `opposite(button)`, `parse_edge(edge) -> (x, y, button)` (a `ValueError` on a malformed edge; callers count malformed edges as `plain` and report the count) and `classify_wall(map_doc: dict, edge: str) -> str`, one of:
  - `"ledge_exact"`: `edge` equals the back-edge of a recorded jump in `map_doc["jumps"]`: for each `"x0,y0,B"` -> `[x1,y1]` the edge `f"{x1},{y1},{opposite(B)}"`. Certain: it is the rule `learn()` uses to create it.
  - `"ledge_row"`: HEURISTIC. The edge's direction is the opposite of some recorded jump's direction B, and the edge's source tile lies on the same row (for UP/DOWN jumps) or column (for LEFT/RIGHT jumps) as that jump's landing tile, in the same map. It can be wrong on a map with two ledges in one row; every report line that counts it says "heuristic".
  - `"plain"`: anything else.
- `compare.py`: `compare_memory(baseline: dict, candidate: dict) -> dict` over the shared map ids only. Per-map rows and totals:
  - `tiles`: candidate tiles, how many the baseline also has (`overlap`), `candidate_only`.
  - `warps`: `common` (same `"x,y,BUTTON"` key in both), `different` (common with a different destination), `candidate_only`.
  - `npcs`: candidate stationary NPCs (`moves` falsy and `last` present, identified by `(pic, tuple(last))`) and how many the baseline also has.
  - `walls`: for each baseline wall edge whose source AND destination tile the candidate visited (`suspect`, the script's `conflicts`), split by `classify_wall(baseline_map, edge)` into `ledge_exact`, `ledge_row`, `plain`. `unexplained` is the `plain` count. Also `baseline_walls` (total baseline edges on shared maps) as the denominator, and `malformed`.
  - Rows list the worst 10 maps by `unexplained`, then by `candidate_only`.
  - The return shape is fixed (Game_Compat's `thresholds.py` and its fixtures read these exact keys; do not rename them):
    ```python
    {
      "totals": {
        "tiles": {"candidate": 2203, "overlap": 2170, "candidate_only": 33},
        "warps": {"common": 21, "different": 0, "candidate_only": 4},
        "npcs": {"candidate": 35, "overlap": 35},
        "walls": {"baseline_walls": 2127, "suspect": 210, "ledge_exact": 60,
                  "ledge_row": 66, "plain": 84, "unexplained": 84, "malformed": 0},
      },
      "rows": [  # worst 10 maps, same per-map keys as "totals" plus "map"
        {"map": 12, "tiles": {...}, "warps": {...}, "npcs": {...}, "walls": {...}},
      ],
      "shared_maps": 14,
    }
    ```
    The numbers are illustrative only; a test asserts the key sets of `totals`, each sub-dict and each row.
  Counts are integers. A zero denominator in any ratio the text output prints shows as `n/a`, never a division error. The module judges nothing (no pass or fail); thresholds belong to `Game_Compat_Check_Directive.md`.

### brain assists RUN_DIR

`uv run python tools/brain.py assists RUN_DIR [--gap N] [--text]` (default `--gap 20` steps). Read-only; a missing `transitions.jsonl` is an error message and exit 1; missing `goal_frames.jsonl` or `meta.json` is treated as empty.

- `assists.py`: `assists_report(transitions: list, goal_frames: list, initial_goals: list, goals_order: list, gap: int = 20) -> dict`, pure (the CLI loads the files and passes `pokeagent.goals.GOALS`; tests pass their own short ladder).
- Assist presses are those whose `source` is `human` or `claude`. Group consecutive assist presses into clusters: a new cluster starts when the map changes or the step gap to the previous assist press exceeds `gap`. Each cluster: `map`, `step_start`, `step_end`, `presses`, `by_source` (counts), `goal_stage` (the stage at `step_start`) and `buttons` (counts per button).
- `goal_ends`: for each goal in `goal_frames` in step order: `goal`, `step`, `assists_in_stage` (assist presses with a step after the previous goal's end step, or after 0 for the first, up to and including this goal's step) and `unaided` (true when that count is zero).
- Top level: `total_presses`, `by_source` (counts for every source string seen), `assist_presses`, `clusters` (list), `goal_ends` (list), `unaided_goals` (the goals flagged unaided), `final_stage` (the stage after the last press) and `milestone_unaided` (true when at least one goal was reached in the run and every reached goal is unaided).
- No dialogue or `text` field is copied into the output.

### brain seed SRC DST

`uv run python tools/brain.py seed SRC.json DST.json [--no-encounters] [--no-loops] [--no-demos] [--no-playthrough-state] [--text]`. The flags are named strip options; **each is off by default**, so with no flag the seeded file equals the source (the scratch script stripped encounters and loops by default; the new command does not). The command prints (JSON, or `--text`) what it removed: `{"maps": n, "removed": {"encounters": <map tables dropped>, "loops": <entries dropped>, "demos": <demos dropped across maps>, "playthrough_state": {"interaction_done": n, "npc_results_done": n}}, "top_level_keys_kept": n}`.

- `--no-encounters`: pop `encounters` from every map. `--no-loops`: pop the top-level `loops`. `--no-demos`: pop `demos` from every map. `--no-playthrough-state`: remove the `done` flag from every interaction entry and from every NPC `results` (that is all it does; do not widen it).
- `seed.py`: `seed_memory(data: dict, *, no_encounters=False, no_loops=False, no_demos=False, no_playthrough_state=False) -> tuple[dict, dict]` returns a NEW document (`copy.deepcopy`; the input is never mutated) and the removal counts.
- The CLI loads SRC through `fileops.effective_data` (so journal edits beside SRC are applied, which is what an agent would see), refuses (exit 1, writes nothing) when DST equals SRC or already exists, and writes DST as UTF-8 JSON. It never writes SRC or the journal.

### Tests (synthetic fixtures only; no real run data, no ROM)

- `tests/test_brain_compare.py`: `classify_wall` (jump `"5,26,DOWN"` -> `[5,28]` makes `"5,28,UP"` exact; `"9,28,UP"` on the same row is `ledge_row`; a wall elsewhere or with the wrong direction is `plain`; a malformed edge raises in `parse_edge` and is counted not raised by `compare_memory`); `compare_memory` on two hand-built documents with exact expected counts for tile overlap, warp common and different, stationary NPC matches (a moving NPC excluded), the wall split, and only shared map ids compared; the CLI through `cli_brain.main(["compare", a, b])` on `tmp_path` files prints valid JSON.
- `tests/test_brain_assists.py`: a hand-built `transitions.jsonl` with agent, human and claude presses across two maps proves cluster boundaries (map change, step gap), `by_source`, the stage at a cluster start, `assists_in_stage` and `unaided` per goal, and `milestone_unaided` both true and false; a missing `goal_frames.jsonl` is tolerated; the output contains none of the `text` strings.
- `tests/test_brain_seed.py`: no flags leaves the output equal to the input; each flag removes exactly its data and the printed counts match; the input object is unchanged; the CLI refuses DST equal to SRC and an existing DST; SRC bytes are identical afterwards.

## 4. What NOT to do

- Do not touch `src/pokeagent/game/` or `src/pokeagent/cli.py`.
- Do not change `Game_Compat_Check_Directive.md`'s queue block, or build the compat package, thresholds or address comparison here.
- Do not change `MapMemory`, `edits.py`, `edits_ops.py` or `tools/swarm_merge.py`. Do not add journal ops (the memory audit directive owns that).
- Do not read any real run directory or `runs/maps.json`, a ROM, `kb/` or `baselines/`. All fixtures are built in the tests with `tmp_path`.
- Do not print or copy dialogue or note text into any output.
- Do not run, edit or re-record `tests/test_golden_red.py`. It skips in the worktree. Report it NOT run. Claude's ROM-present check runs it before merge. This change adds files only and should not change any recorded hash; if one does change, say so in the report so it is re-recorded from a base-commit run in the same PR.
- No file over 600 lines and no brain module over 300 lines.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

```
uv run pytest -q -p no:cacheprovider tests/test_brain_compare.py tests/test_brain_assists.py tests/test_brain_seed.py
```
Expected: all pass, none skipped.

```
uv run pytest -q -p no:cacheprovider tests/test_brain_edits.py tests/test_brain_query.py
```
Expected: same result as on your base commit, no new failures. Report any pre-existing failure separately.

```
git diff --stat main -- src/pokeagent/game src/pokeagent/cli.py src/pokeagent/explorer tools/swarm_merge.py
```
Expected: no output.

```
uv run pytest -q -p no:cacheprovider tests/test_golden_red.py -rs
```
Expected: it skips in the worktree. Report it as NOT run, with the skip reason.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here. If something expected is missing, stop and write that in the PR description.
- Use `uv run` and Python 3.12 only.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- If a tool call is genuinely blocked, stop and write why in the PR description.

## 7. Completion criteria

- [ ] `brain compare` reports tile overlap, warp agreement, stationary NPC agreement and the wall split (suspect, `ledge_exact`, `ledge_row`, unexplained) for the shared maps of two documents, and `classify_wall` behaves as specified. <!-- test: tests/test_brain_compare.py -->
- [ ] `brain assists` groups assisted presses into clusters by map and step gap, gives the stage at each cluster start, each goal's end step, per-goal unaided flags and `milestone_unaided`. <!-- test: tests/test_brain_assists.py -->
- [ ] `brain seed` with no flags copies the document, each strip flag removes exactly its data and prints what it removed, and SRC is never modified. <!-- test: tests/test_brain_seed.py -->
- [ ] The comparison implementation lives in `src/pokeagent/brain/compare.py` and `src/pokeagent/brain/ledges.py` only, so `Game_Compat_Check_Directive.md` can import it.
- [ ] No file over 600 lines and no brain module over 300; nothing under `src/pokeagent/game`, `src/pokeagent/cli.py` or `src/pokeagent/explorer` changed.

## 8. Report

Findings first: any behaviour of the scratch scripts you could not reproduce, any source value in `transitions.jsonl` beyond agent, human and claude that the fixtures or code revealed, and any file you split for size. Then the command tails from section 5, including `tests/test_golden_red.py` reported NOT run and why. Name anything that did not fit.

## Required from User

Nothing before the run. Afterwards Claude runs the three commands on the real files and runs the ROM-present check, including `tests/test_golden_red.py`, before merge.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(src/pokeagent/cli_brain.py)
- Read(src/pokeagent/brain/__init__.py)
- Read(src/pokeagent/brain/fileops.py)
- Read(src/pokeagent/goals.py)
- Read(tests/test_brain_query.py)
- Exec(uv run python --version)
- Exec(uv run python tools/brain.py)
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
- 2026-11-11 07:25 · robert-claude-laptop · none → Draft — queue block added so the directive lints (PR #182 verify failed on lint_scope: no queue block)
- 2026-11-14 15:17 · robert-claude-laptop · Draft → Queued — Robert 2026-11-14: unblock Pokemon Blue. This is the missing dependency of Game_Compat_Check (blocked 11-11), which gates Family_Shared_Memory (Red+Blue).
<!-- queue:end -->
