# PokeAgent: Rewinder slice 1 - a pure run-playback core: any step of a finished run as one frame, plus activity segments and moments

**First slice of the Rewinder milestone** (`docs/ROADMAP.md`, "Milestone: Rewinder"). Base: current main. Finish-line metric this moves: Rewinder done-condition 1 (`DIRECTION.md`, "Watchability lane").

## Why this exists

Robert, 2026-11-15: "Could we build a Rewinder that instead uses the graphics and maps we have already, and simply plays the steps back?" What he enjoys in this project is watching a run and working out for himself where and why the agent got stuck. Today that only works live: nothing lets him go back to step 3,000 of a finished run and look.

Claude checked a real 8,000-step run folder read-only on 2026-11-15. Every run already writes what playback needs, so no video and no new logging is required for the first version:

- `transitions.jsonl`: one row per press with where the player was, where it ended up, facing, button, any open text box, the battle flag.
- `decisions.jsonl`: the behaviour and rule that made each press, the goal being worked on, and what the press did.
- `levels.jsonl`: the party (species, level, HP) each time it changed.

`src/pokeagent/review/load.py` already reads all three (and more) into one `RunData`. The World view already draws a player sprite on the stitched map from a `Track` (`src/pokeagent/world/model.py`). The missing piece is the join: "give me the state of the run at step N" in the shape the drawing code takes. This directive builds that join as pure code with no window and no ROM. Slice 2 (not this directive) puts a scrubber on it in the viewer.

## Scope (in this order)

1. `src/pokeagent/rewind/__init__.py` <!-- new: src/pokeagent/rewind/__init__.py --> - package docstring and the public names.
2. `src/pokeagent/rewind/frames.py` <!-- new: src/pokeagent/rewind/frames.py --> - `Frame`, `Rewind`. Under 150 lines.
3. `src/pokeagent/rewind/segments.py` <!-- new: src/pokeagent/rewind/segments.py --> - the activity table and segment builder. Under 120 lines.
4. `src/pokeagent/rewind/moments.py` <!-- new: src/pokeagent/rewind/moments.py --> - moment detection. Under 120 lines.
5. `src/pokeagent/rewind/cli.py` <!-- new: src/pokeagent/rewind/cli.py --> - `pokeagent rewind`. Under 120 lines.
6. `src/pokeagent/cli.py` - register the new subcommand (one import and one call, the way the `world` command's `add_parser` is registered there).
7. Tests: `tests/test_rewind_frames.py`, `tests/test_rewind_segments.py`, `tests/test_rewind_moments.py`, `tests/test_rewind_cli.py` <!-- new: tests/test_rewind_frames.py --> <!-- new: tests/test_rewind_segments.py --> <!-- new: tests/test_rewind_moments.py --> <!-- new: tests/test_rewind_cli.py -->.

Read-only, do not touch: everything under `src/pokeagent/viewer/`, `src/pokeagent/world/`, `src/pokeagent/explorer/`, `src/pokeagent/review/`. If one of them needs a change to make this work, stop and say so in the Status row.

## The work

Existing facts, pasted because the worktree cannot be searched. `uv run python --version` prints `Python 3.12.12`.

```
# src/pokeagent/review/load.py
def jsonl(path, skipped=None) -> list[dict]            # tolerant: missing file -> [], corrupt line skipped
def resolve_run_dir(run: str, runs_dir: Path) -> Path | None
def load_run(run_dir: Path) -> RunData
class RunData: run_dir, name, runs_dir, meta: dict, decisions: list[dict] (press rows only), event_rows, transitions: list[dict],
               levels: list[dict], goal_frames, battles, dossier, milestones, after_victory, skipped_rows, start_time, crashed

# one real row of each file (step 500 of an 8,000-step run)
decisions:   {"step": 500, "behaviour": "battle_moves", "rule": "fight", "button": "A", "map": 13, "x": 6, "y": 2,
              "goal_stage": "beat_brock", "box": false, "battle": true, "outcome": "none", "reversal": false}
transitions: {"step": 500, "from": [13, 6, 2], "button": "A", "to": [13, 6, 2], "moved": false, "textbox": "none", "text": "",
              "facing": "RIGHT", "source": "agent", "battle_flag": 1, "battle_turn": 0}
levels:      {"step": 15, "frame": 192, "map": 2, "cause": "out_of_battle",
              "party": [[112, 3, 58, 10, 16], [36, 8, 335, 25, 25], [165, 8, 660, 23, 23], [176, 15, 2212, 34, 38], [113, 4, 64, 17, 17]]}
# decisions "outcome" values: moved | blocked | box | map_change | goal | none (src/pokeagent/explorer/decisions.py)

# src/pokeagent/world/model.py
TRAIL  # module constant: the Track.path maxlen
@dataclass
class Track: id: str; map: int = -1; x: int = 0; y: int = 0; facing: str = "DOWN"; step: int = 0;
             prev: tuple[int, int, int] | None = None; moved_at: float = 0.0;
             path: deque (maxlen=TRAIL) of (map, x, y); goal: str = ""; hold: bool = False; stalled: bool = False;
             battle: BattleCard | None = None; last_seq: int = 0

# src/pokeagent/explorer/behaviours/__init__.py
def default_behaviours() -> list[Behaviour]     # every behaviour object has a `name` str; decisions rows carry that name
```

The order of the five numbers in a `levels` party entry is written by `src/pokeagent/explorer/party_log.py`. Read that file and use its field order; do not guess it from the sample above.

### frames.py (pure; no emulator, no ROM, no window)

- `PartyRow(species: int, level: int, hp: int, max_hp: int)` and `Frame` are frozen dataclasses. `Frame` fields: `step, map, x, y, facing, button, behaviour, rule, outcome, goal_stage, in_battle, battle_turn, textbox, text, moved, source, party: tuple[PartyRow, ...]`.
- `Rewind.from_run(data: RunData) -> Rewind` indexes the three row lists by their `step` field once. `Rewind.first_step`, `Rewind.last_step`, `len(rewind)` (number of distinct steps that have a transitions row).
- `Rewind.frame(step: int) -> Frame`: position, facing, button, text box and battle flag come from the transitions row AT that step, or the nearest earlier one; the position shown is the row's `to`. Behaviour, rule, outcome and goal stage come from the decisions row at that step, or the nearest earlier one. The party is the latest levels row at or before the step. `step` below `first_step` clamps to the first frame; above `last_step` clamps to the last.
- `Rewind.track(step: int, agent_id: str = "rewind", trail: int | None = None) -> Track`: a `world.model.Track` for that step, with `path` filled from the positions of the preceding moved presses (oldest first, at most `trail` or `TRAIL` points), `prev` set to the position before the last move, `goal` = the frame's goal stage, `step` = the step. `battle`, `hold`, `stalled` stay at their defaults.

> RULE: lookups are by the `step` field with a carry-forward, never by list position. Rows can be missing (a decision that pressed nothing writes no decisions row) and files can be absent; a run with transitions but no decisions or levels must still play, with empty strings and an empty party.

> RULE: `frame()` on an 8,000-step run must not scan the lists. Build sorted step arrays once in `from_run` and use `bisect`.

### segments.py (pure)

- `ACTIVITY: dict[str, str]` maps every behaviour name to one of these activities: `move`, `battle`, `text`, `menu`, `heal`, `shop`, `catch`, `wait`, `other`. Read each file under `src/pokeagent/explorer/behaviours/` for its `name` and what it does, and choose the activity from that.
- `activity(frame: Frame) -> str`: `battle` whenever `frame.in_battle`; otherwise `ACTIVITY.get(frame.behaviour, "other")`.
- `Segment(start: int, end: int, activity: str)` and `segments(rw: Rewind) -> list[Segment]`: maximal runs of consecutive steps with the same activity, in step order, covering `first_step..last_step` with no gaps and no overlaps.
- `shares(segs) -> dict[str, float]`: fraction of steps per activity, summing to 1.0 (empty input gives `{}`).

> RULE: no activity called "training". Telling a training fight from any other fight needs the agent's training state, which is not logged per step yet (Rewinder slice 4). Do not infer it from rule names.

### moments.py (pure)

`Moment(step: int, kind: str, label: str)` and `moments(rw: Rewind, data: RunData) -> list[Moment]`, sorted by step. Kinds and their sources:

- `map_change`: a transitions row whose `from` map differs from its `to` map. Label: `map A -> B` (ids as numbers; names are a later slice).
- `battle_start` / `battle_end`: the battle flag going 0 -> nonzero / nonzero -> 0 between consecutive frames.
- `goal`: a decisions row with `outcome == "goal"`. Label: the row's `goal_stage`.
- `level_up`: between two consecutive levels rows, a species whose highest level rose. Compare by species id, not by slot (the party is reordered often). Label: `species N: Lx -> Ly`.

### cli.py and the registration

`pokeagent rewind RUN [--runs DIR] [--at STEP] [--segments] [--moments] [--json]`. `RUN` is resolved with `resolve_run_dir`; an unknown run prints one line to stderr and exits 2. With no flag it prints a three-line summary (steps covered, activity shares, moment counts by kind). `--at` prints that step's frame. `--json` prints the same data as JSON. It never opens a window and never needs the ROM.

### Tests (synthetic fixtures only; no real run data, no ROM)

Build small `RunData` objects by hand (10 to 40 rows). Cover at least: carry-forward when a step has no decisions row; clamping below and above the range; a run with transitions only; `track()` path order, length cap and `prev`; segments cover the range with no gap or overlap and `shares` sums to 1.0; every name from `default_behaviours()` is a key of `ACTIVITY` (one test, so a new behaviour cannot be forgotten); each moment kind fires once on a fixture built for it and `level_up` survives a party reorder; the CLI's exit code 2 on an unknown run and its `--json` output parsing as JSON (write a tiny run folder under `tmp_path`).

## What NOT to do

- No viewer code, no Dear PyGui, no PNG or GIF output. That is slice 2.
- No new log files and no change to what a run writes. That is slices 3 and 4.
- No map names, species names or ROM tables. Ids only.
- Do not read real run folders in tests.

## Verification (exact commands, from the worktree root)

```
uv run --frozen pytest -q tests/test_rewind_frames.py tests/test_rewind_segments.py tests/test_rewind_moments.py tests/test_rewind_cli.py
```
Expected: all pass.

```
uv run --frozen pytest -q -p no:cacheprovider -rfEs
```
Expected: 0 failed. Report the exact last line.

```
git diff --stat origin/main
```
Expected: the new `src/pokeagent/rewind/` files, the four test files and `src/pokeagent/cli.py` only.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. If a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command.
- Branch only; commit as you go; never commit to or push main; never merge.
- Create no scratch or debug files; anything temporary goes under `.devin-scratch/`.
- If blocked, stop and write why in the Status row. Done means `Review`, with the diff stat and test tails in the Report.

## Completion criteria

- [ ] `Rewind.frame(step)` returns the right frame with carry-forward and clamping. <!-- test: tests/test_rewind_frames.py -->
- [ ] `Rewind.track(step)` returns a `Track` the World drawing code can take, with an ordered, capped path. <!-- test: tests/test_rewind_frames.py -->
- [ ] Segments cover the run exactly once and every default behaviour has an activity. <!-- test: tests/test_rewind_segments.py -->
- [ ] The four moment kinds are detected. <!-- test: tests/test_rewind_moments.py -->
- [ ] `pokeagent rewind` prints the summary, a frame, segments and moments, as text and JSON. <!-- test: tests/test_rewind_cli.py -->
- [ ] Full suite: 0 failed. No file outside Scope changed.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, the two pytest tails, the `ACTIVITY` table as chosen, and the party field order found in `party_log.py`. Then the check Claude runs afterwards on the laptop (Devin cannot, so do not run it): the pokeagent rewind command against a real 8,000-step run folder: the summary, `--at 500` compared by hand with that run's own rows, and the time `Rewind.from_run` plus 1,000 `frame()` calls take.

## Forbidden Actions

- ROMs, extracted game art, save states and anything derived from them are local and gitignored. Never commit them or add one as a fixture.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor.
- Do not open a window or send input.
- Do not commit to or push main, merge, or deploy.

## Required from User

- Nothing blocks the run. Robert approves this directive; Claude runs the laptop check in the Report after the verify lane passes.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(git diff)
- Exec(git grep)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-rewinder-slice1-playback-core-directive |
| Base branch | - |
| Base commit | 38ec0f56cfa6b68c6881706ec11e0165e2428a43 |

**Status log**
- 2026-11-15 12:12 · agentflow-tick · none → Queued — suggested by heartbeat: Fully specified pure-code slice (no ROM/window); prerequisites confirmed on disk; check against a real run stays with Claude
- 2026-11-15 13:05 · robert-claude-laptop · Queued → Approved
- 2026-11-15 13:06 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-rewinder-slice1-playback-core-directive; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M7G66SK7YXF87TNFMADCRA5Y
<!-- queue:end -->
