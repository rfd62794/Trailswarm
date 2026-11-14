# PokeAgent: Go-Explore slice 3 (cell harvest) - save a state into the slice-2 archive every few steps or when a new cell key appears, behind one flag, all logic in one small module

**Size:** M. **Model:** swe-2-high. **Assignee:** devin.

**Read first:** `docs/plans/go-explore-2026-11-14.md` (approved by Robert 2026-11-14; sections 3 D2/D4/D5/D8, 4 slice 3, 5). **Depends on slices 1 and 2 being merged**: you import `src/pokeagent/goexplore/cell.py`, `archive.py`, `store.py`. **If any of those three files is absent in your worktree, stop immediately and write "slice 1/2 not merged" in the Status row.** Do not recreate them. Base: main containing both.

## 1. Why this exists

Go-Explore (plan D5) returns to saved cells, so something must save mid-run states into the archive. **Checked on main 2026-11-14: no periodic-save hook exists.** Every `save_state` call site in the explorer is event-driven: goal checkpoints (`src/pokeagent/explorer/press_goals.py:71`), `team_best` (`explorer/press_track.py:64`), the end state (`explorer/press_stop.py:24`), novelty discoveries (`novelty/discoveries.py:174`), anomaly records (`explorer/anomaly_record.py:52`), leg states (`legs/states.py:79,95`). None is keyed by cell and none runs every K steps. `tools/explore_demo.py` has no save flag. So slice 3 adds the hook.

Plan D2 said the flag popcount and party level are "not in run logs" (true: `decisions.jsonl` rows carry map/x/y/goal_stage only). This slice records them live: one `read_snapshot` per check gives all seven cell fields, so the key at harvest time includes `flag_popcount // 4` and the party level bucket. Nothing is wired into `explorer/engine.py`; with the flag off, runs are byte-identical to main. The driver, runner and budget are slice 4.

## 2. Scope (files, in order)

1. `src/pokeagent/goexplore/cell_dump.py` (< 120 lines) + `tests/test_goexplore_cell_dump.py`
2. `tools/explore_demo.py`: **at most +3 lines**, exactly: one `ap.add_argument("--cell-dump", ...)` line and a 2-line `if a.cell_dump:` block with a local import and one `attach(...)` call. The file is 391 lines (already over the 300-line rule); do not reformat, move or trim anything in it, and add no other line. Final `wc -l` must be <= 394.

The plan's section 5 says "explorer/cell_dump.py"; put it in `goexplore/` instead (the slice 2 package, keeps `explorer/` untouched). Touch nothing else.

## 3. The work

### Real code shapes you build on (verified on main, 2026-11-14)

Slice 1, `src/pokeagent/goexplore/cell.py`:
```python
class Cell(NamedTuple):  # map_id, bx, by, goals, flag4: int | None, lvl5: int | None, party_n: int | None
def from_snapshot(s: Snapshot, goals: int) -> Cell      # :50  all seven fields from one Snapshot
def cell_id(c: Cell) -> str                             # :62  filesystem-safe, e.g. "12.2.1.7.5.3.2"
def goals_reached(stage: str) -> int | None             # :40  GOALS.index(stage); len(GOALS) for "done"; None otherwise
```
Slice 2, `goexplore/archive.py`:
```python
@dataclass
class Entry:  # :82   cid: str; state: str ("cells/<cid>.state", relative to the archive root); goals: int; steps: int;
              #       hp: float = 0.0; n_seen: int = 0; novelty: float = 0.0; parent: str | None = None; lineage: str = "organic"
def score(e: Entry) -> tuple[int, int, float]           # :103  (goals, -steps, hp): bigger is better
class Archive:  # :108
    entries: dict[str, Entry]
    def offer(self, e: Entry) -> bool                   # :116  insert, or replace iff score(new) > score(old) (strict; keeps n_seen)
```
Slice 2, `goexplore/store.py`. A state path in an archive must stay inside `cells/`: `load` rejects any `Entry.state` that does not start with `cells/`, contains `..`, or contains a backslash, so always use the string `add_state` returns (forward slashes):
```python
def save(archive: Archive, root: Path) -> None          # :180  atomic archive.json
def load(root: Path) -> Archive                         # :188  empty Archive if no file; ValueError if present but bad
def add_state(emu, root: Path, cid: str, source_run: str | None = None,
              inherit: Path | str | None = None) -> str # :208  saves cells/<cid>.state (tmp then os.replace), calls statefp.stamp, returns "cells/<cid>.state"
def evict(archive: Archive, root: Path, protected: frozenset[str] = frozenset(),
          on_route: frozenset[str] = frozenset()) -> list[str]   # :222  caller calls save() afterwards
```
`statefp.stamp(emu, state, source_run=None, *, inherit=None)` (`statefp.py:92`) writes `<state>.fp.json`; with `inherit` set it keeps a NON-organic start lineage and records `parent`; an organic start leaves the fingerprint organic (no lineage key). `statefp.lineage(Path) -> str` (:78) reads it (a missing sidecar reads `organic`); `statefp.read(Path) -> dict | None` (:62); `statefp.party_hp_fraction(fp: dict) -> float` (:108).

Snapshot, `src/pokeagent/novelty/features.py`:
```python
def read_snapshot(emu) -> Snapshot                      # :32  map, x, y, flags (320 bytes from 0xD747, :11), bag, party, hp ...
```
`Snapshot.party` is a tuple of `(species, level, exp, moves, ident)`; `cell.from_snapshot` already applies `flag_popcount` and `party_bucket`, so it is the only call you need. The goal count: `goal_stage(ctx.goals())` (`explorer/decisions.py:19`, the same call `explorer/engine.py:72` makes every step) returns a ladder goal name or `"done"`; `cell.goals_reached(...)` turns it into the prefix length. `ctx.goals()` is `check_goals(emu, ctx)` (`explorer/context.py:289`); it only records seen maps on the ctx and the engine already calls it every step, so an extra call every few steps changes nothing.

### Where the hook goes (verified: no existing periodic hook)

The headless loop calls `engine.step()` at `src/pokeagent/explorer/headless_loop.py:104` (an attribute lookup on the Engine instance, inside a try/except that logs and continues, :105-106); the windowed loop calls it at `tools/explore_demo.py:377`. `Engine` is created at `tools/explore_demo.py:189` (`engine = Engine(ctx, presser, decision_log=decisions)`). So the whole hook is wrapping `engine.step` on that instance after line 189. `ctx.step` (`explorer/context.py:75`) counts presses and is incremented at `explorer/press.py:46`; `step()` can return without pressing (a wait), so track the last checked step; do not rely on `ctx.step % K`.

`tools/explore_demo.py` already parses `--seed` (:89) and `--stop-at-goal` (:79); nothing there changes. The 2-line block goes right after the `engine = Engine(...)` line:
```python
    if a.cell_dump:
        from pokeagent.goexplore.cell_dump import attach; attach(ctx, engine, a.cell_dump)
```
and the flag: `ap.add_argument("--cell-dump", default=None, help="harvest cells into this Go-Explore archive dir (slice 3); off = byte-identical run")`. No second flag: the cadence is a module constant.

### 3.1 `goexplore/cell_dump.py` (< 120 lines)

```python
CHECK_EVERY = 10     # steps between cell checks; also the "every K steps" save cadence (a check saves only a new or better cell)

class Harvester:
    def __init__(self, ctx, root: Path, every: int = CHECK_EVERY, steps_offset: int = 0, parent: str | None = None) -> None: ...
    def tick(self) -> str | None:   # cid saved this call, else None; NEVER raises
def attach(ctx, engine, root, every: int = CHECK_EVERY, **kw) -> Harvester
```
Behaviour:
- `attach` loads the archive (`store.load(root)`; a ValueError propagates: fail loud at start), refuses a start state whose `statefp.lineage(Path(ctx.opts.state_path))` is `synthetic` (raise `ValueError`; skip the check when `state_path` is empty; `promoted` and `organic` are allowed, plan D8), then replaces `engine.step` with a wrapper: `d = orig(); harvester.tick(); return d`. The wrapper returns exactly what the original returned and adds no exception path.
- `tick`: return at once unless `ctx.step - self.last_check >= every` (then set `last_check`). Then `snap = read_snapshot(ctx.emu)`, `goals = cell.goals_reached(goal_stage(ctx.goals()))` (fall back to `len(ctx.goal_steps)` on None), `cid = cell_id(from_snapshot(snap, goals))`, steps = `ctx.step + steps_offset`.
- Save rule (state files are ~175 KB; never write one that will be rejected): if the archive already holds `cid` and `(goals, -steps) <= (old.goals, -old.steps)`, do nothing. Otherwise `rel = store.add_state(ctx.emu, root, cid, ctx.run_dir.name, inherit=ctx.opts.state_path or None)`, read the sidecar (`statefp.read`) for `hp = statefp.party_hp_fraction(fp)`, build `Entry(cid, rel, goals, steps, hp, parent=<previous distinct cell of this run, or the constructor `parent` for the first>, lineage=statefp.lineage(root / rel))`, then `archive.offer(entry)`, `store.evict(archive, root)`, `store.save(archive, root)`. The first cell of a run has no previous cell: its parent is the `parent` argument (None for an organic checkpoint start; slice 4's driver passes the returned-from cid).
- `Entry.novelty` stays 0.0 here (slice 4 fills it from the run's discoveries); `n_seen` is left to selection.
- Organic rule (plan D8): every cell is stamped through `statefp.stamp` (via `add_state`), so its sidecar carries the fingerprint and, for a non-organic inherited start, the inherited lineage and `parent`; `Entry.parent` carries the cell chain for organic ones. Never edit a state, never call `edit_class` tools.
- A failure inside `tick` (disk, RAM read) is swallowed after `ctx.log(f"[cell dump skipped: {exc!r}]", "res")`, exactly like `Engine._note_novelty` (`explorer/engine.py:115-125`): an observer never stops a run.

### 3.2 Tests (`tests/test_goexplore_cell_dump.py`, `FakeEmulator` + `tmp_path` only)

`FakeEmulator` (`src/pokeagent/emulator.py:216`): `FakeEmulator({addr: byte})`, `.memory`, `.read`, `.read_range`, `.frames`; `save_state` writes `json.dumps(self.memory)` (:268). Useful addresses: map `0xD35E`, y `0xD361`, x `0xD362`, flags start `0xD747` (320 bytes), party count `0xD163`. Build the ctx the way `tests/test_after_victory.py:91` does (`ExplorerContext(emu=..., mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(), run_dir=tmp_path / "run")`, set `ctx.step` by hand). The engine can be a tiny stub object with a `step()` method that bumps `ctx.step` and returns a sentinel. For the party level, either write the party bytes the way `tests/test_novelty.py` does or monkeypatch `read_snapshot` in `cell_dump`.

Required tests: (1) a first tick saves `cells/<cid>.state` + `.fp.json`, `archive.json` lists it, and `cid` equals `cell_id(from_snapshot(...))`; (2) `test_flag_bucket_splits_cells`: setting 4 more flag bits at `0xD747` changes `flag4` and yields a NEW cell (a second file); one extra bit does not; (3) the level bucket: a party max level 4 vs 5 yields different cells; (4) checks run only every `CHECK_EVERY` steps and an unchanged cell is not re-saved (a `save_state` call counter); (5) a higher goals count at the same position replaces the state and keeps `n_seen`; (6) the `attach` wrapper returns exactly the original `step()` result; (7) `test_failing_save_is_swallowed`: a raising `emu.save_state` is logged, `tick` returns None; (8) `test_synthetic_start_refused`: a synthetic start state (write its sidecar with `statefp.write(state, {"v": 1, "lineage": "synthetic"})`) raises ValueError, while an organic one (no sidecar) and an empty `state_path` are accepted; (9) parent chain: cell A then cell B in one run gives `entries[B].parent == A`; (10) every `Entry.state` the harvester writes survives `store.load` (forward slash, inside `cells/`).

## 4. What NOT to do

- No emulator process, no PyBoy, no ROM, no `runs/` access (absent in your worktree; do not look). Tests use `FakeEmulator` and `tmp_path` only.
- Add nothing to `tools/explore_demo.py` beyond the 3 lines; no logic there. No lines in `explorer/context.py`, `explorer/memory.py`, `explorer/behaviours/plan_goal.py`; nothing in `explorer/engine.py`, `explorer/headless_loop.py`, `explorer/press*.py`, or the loop guard (`explorer/behaviours/guards.py`).
- Do not edit `cell.py`, `archive.py`, `select.py`, `store.py`, `census.py`, `statefp.py`, `emulator.py`, `novelty/*`.
- No driver, runner, budget or subprocess code (slice 4). No state surgery, no `edit_class` edits, no extra rows in `decisions.jsonl`, no new log files in the run dir, no new dependency.
- Never push or commit states or ROMs.

## 5. Verification (exact commands, from the worktree root)

Baseline first (Claude ran it on 2026-11-14 on current main): `74 passed, 1 warning in 5.25s`.
```
uv run pytest -q -p no:cacheprovider tests/test_goexplore_*.py tests/test_novelty*.py
```
Expected: 0 failed. If not, stop and write the failing ids; do not fix them.

New tests:
```
uv run pytest -q -p no:cacheprovider tests/test_goexplore_cell_dump.py
```
Expected: all pass, none skipped.
```
wc -l src/pokeagent/goexplore/cell_dump.py tools/explore_demo.py
git diff --stat origin/main
git diff origin/main -- tools/explore_demo.py
git grep -n "cell_dump" -- src tools
```
Expected: `cell_dump.py` < 120; `explore_demo.py` <= 394; the stat lists only `cell_dump.py`, its test, and `tools/explore_demo.py` with 3 insertions and 0 deletions; the explore_demo diff shows exactly the flag line and the 2-line block; the grep hits only `goexplore/cell_dump.py` and the one call in `tools/explore_demo.py`.

Full suite, once, at the end (pytest-xdist is NOT installed; never use `-n`):
```
uv run pytest -q -p no:cacheprovider
```
Expected: 0 failed (base count plus your new tests; skip count unchanged from the base).

**Not yours:** the real-ROM check that a flag-off run's `decisions.jsonl` is byte-identical to main, and a short flag-on harvest smoke (`--cell-dump <dir> --steps 300`), need a ROM and are run by Claude after review. You cannot prove them; do not claim them. Your proof of "off = identical" is the 3-line diff: with no flag, no new code path runs.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch (pytest-xdist is NOT installed: never use `-n`). Never read outside the worktree. Do not search or hunt for missing things: if something named here is missing, stop and write why in the Status row. Never use `python -c`.
- Use `uv run` and Python 3.12 only; no bare `python`.
- Never delete files. Create no scratch or debug files.
- Never commit to main/master, never push to main, never deploy, never merge. Work on branch `directive/goexplore-slice3-cell-harvest`; commit as you go and push the branch.
- No ROM, no `runs/` access.
- 0 failed tests is a hard rule: no "known failures", no skips added to make it pass.
- Do NOT hand-write a `## Queue` block or edit anything between the queue markers.
- Status meaning: set `Review` when the branch is pushed with the work and every check in section 5 passes. If a tool call is genuinely blocked, stop and write why in the Status row.

## 7. Completion criteria

- [ ] `cell_dump.py` exists with `Harvester`, `attach`, `CHECK_EVERY`, < 120 lines; no logic added to `tools/explore_demo.py`.
- [ ] `tools/explore_demo.py` grew by exactly 3 lines (<= 394 total), flag default None.
- [ ] Cell key at harvest includes `flag_popcount // 4` and the level bucket. <!-- test: tests/test_goexplore_cell_dump.py::test_flag_bucket_splits_cells -->
- [ ] A synthetic start is refused; cells go through `statefp.stamp` and carry `parent`. <!-- test: tests/test_goexplore_cell_dump.py::test_synthetic_start_refused -->
- [ ] A failing dump never raises into the run. <!-- test: tests/test_goexplore_cell_dump.py::test_failing_save_is_swallowed -->
- [ ] No file outside section 2 changed; nothing wired into `engine.py`.
- [ ] Baseline gate, new tests and the full suite: 0 failed.

## 8. Report

Findings first: `wc -l` of the two files, the exact 3-line diff, any name that differed from the signatures above (the merged files win; report the difference). Then the real output tails: baseline gate, new tests, the full-suite line. State plainly that no ROM was used and that the flag-off byte-identical check and the 300-step harvest smoke are Claude's, run on the laptop after review.

## Required from User

Nothing for the build. Queue only after slices 1 and 2 have merged.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(docs/plans/go-explore-2026-11-14.md)
- Read(src/pokeagent/goexplore/cell.py)
- Read(src/pokeagent/goexplore/archive.py)
- Read(src/pokeagent/goexplore/store.py)
- Read(src/pokeagent/novelty/features.py)
- Read(tools/explore_demo.py)
- Read(tests/test_after_victory.py)
- Exec(uv run pytest)
- Exec(git diff)
- Exec(git grep)
- Exec(wc)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-goexplore-slice3-cell-harvest-directive |
| Base branch | - |
| Base commit | 17887fa77b57851165da877d8d523089fe590a87 |

**Status log**
- 2026-11-14 03:37 · robert-claude-laptop · none → Queued — Go-Explore design approved by Robert 2026-11-14; slices 1-2 merged (#252, #257).
- 2026-11-14 03:38 · robert-claude-laptop · Queued → Approved — lint override: goexplore/cell_dump.py and tests/test_goexplore_cell_dump.py are new files this directive creates; explorer/cell_dump.py is cited only as the plan's original location that the directive deliberately does not use.
- 2026-11-14 05:52 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-goexplore-slice3-cell-harvest-directive; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M7CTZ0E9D7CKNS32EGYBCQFH
- 2026-11-14 06:03 · dispatcher · launched pid=22712; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-goexplore-slice3-cell-harvest-directive; provisioned: uv sync --frozen; permission-mode=smart (`## Sandbox needs` declared (11 declared need(s); 7 external))
<!-- queue:end -->
