# PokeAgent: Go-Explore slice 2 (archive, select, store) - pure cell archive with a score-replace rule, seeded weighted selection, and an atomic on-disk store with safe eviction

**Size:** M. **Model:** swe-2-high. **Assignee:** devin.

**Read first:** `docs/plans/go-explore-2026-11-14.md` (approved by Robert 2026-11-14; sections 3 D2/D3/D4/D8, 4 slice 2, 5). **Depends on slice 1 being merged** (`GoExplore_Slice1_Cell_Census_Directive.md`): you import `src/pokeagent/goexplore/cell.py` (`Cell`, `cell_id`, `parse_id`). **If `src/pokeagent/goexplore/cell.py` is absent in your worktree, stop immediately and write "slice 1 not merged" in the Status row.** Do not recreate it. Base: main containing slice 1.

## 1. Why this exists

Seed 12, heal_cerulean -> beat_misty, 12000 steps: 46% of steps went to training trips pinned to maps never reached, beat_misty not reached, SHAKE 7.2% (`docs/plans/training-controller-2026-11-13.md` section 1); one long run pays for its own earlier mistakes forever. Go-Explore keeps an archive of distinct places (cells, slice 1) so a bad branch costs one bounded budget, not the rest of the run. This slice is the archive's pure core, no emulator process and no ROM: which state represents a cell (D3 "score"), which cell to return to next (D3 selection, seeded and deterministic), and how the archive lives on disk under `runs/goexplore/<run-id>/` (D4: `archive.json` written atomically, states + sidecars via `statefp.stamp`, capped at 1,000 cells, safe eviction). Slices 3-5 (harvest, driver, A/B) plug into these three modules; nothing is wired into the explorer here.

## 2. Scope (files, in order)

1. `src/pokeagent/goexplore/archive.py` (< 120 lines) + `tests/test_goexplore_archive.py`
2. `src/pokeagent/goexplore/select.py` (< 120 lines) + `tests/test_goexplore_select.py`
3. `src/pokeagent/goexplore/store.py` (< 120 lines) + `tests/test_goexplore_store.py`

Touch nothing else (`goexplore/__init__.py` and `cell.py` already exist from slice 1; do not edit them).

## 3. The work

### Real code shapes you build on (verified on main, 2026-11-14)

Atomic write pattern, `src/pokeagent/statefp.py:51-54` (copy the idea, same directory tmp then `os.replace`):
```python
def write(state: Path, fp: dict) -> None:
    tmp = sidecar(state).with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(fp, sort_keys=True), encoding="utf-8")
    os.replace(tmp, sidecar(state))
```
`statefp.py` other functions you use (all `from pokeagent import statefp`): `SUFFIX = ".fp.json"` (:14); `sidecar(state: Path) -> Path` (:20) = the state path with `.fp.json` appended to its name; `stamp(emu, state: Path, source_run: str | None = None, *, inherit: Path | str | None = None) -> dict` (:92) fingerprints the emulator's RAM and writes the sidecar (call it right after the state file is saved; best effort, never raises on RAM read failures); `read(state: Path) -> dict | None` (:62); `lineage(state: Path) -> str` (:78) returns `organic | synthetic | promoted`; `party_hp_fraction(fp: dict) -> float` (:108) = sum HP / sum max HP, 0.0 when unknown.

The goals sidecar (`src/pokeagent/checkpoint_goals.py:23-27`): `SUFFIX = ".goals.json"`, `sidecar(state) -> Path` = `<state name>.goals.json`. Use `checkpoint_goals.sidecar` when deleting a cell's files.

`FakeEmulator` (`src/pokeagent/emulator.py:216`): in-memory, no ROM. Constructor (:219): `FakeEmulator(memory: dict[int, int] | None = None, *, game: GameSpec = RED)`. It has `.memory` (dict addr -> byte), `.frames: int`, `.read(addr)`, `.read_range(start, length)`, and (:268, :271):
```python
    def save_state(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.memory))

    def load_state(self, path: Path) -> None:
        check_state_game(path, self.game)
        self.memory = _RamDict({int(k): v for k, v in json.loads(Path(path).read_text()).items()}, owner=self)
        self._ram_rev += 1
```
Verified: `e = FakeEmulator({0xD35E: 12, 0xD362: 9, 0xD361: 5}); e.save_state(p); statefp.stamp(e, p, "r1")` leaves `p` and `p.fp.json` and returns `{'v': 1, 'map': 12, 'x': 9, 'y': 5, 'respawn': 0, 'badges': 0, 'money': 0, 'party': [], 'heal_items': 0, 'bag_slots': 0, 'frames': 0, 'source_run': 'r1'}`; `statefp.lineage(p) == "organic"`.

From slice 1 (`goexplore/cell.py`): `class Cell(NamedTuple)` with fields `map_id, bx, by, goals, flag4, lvl5, party_n`; `cell_id(c) -> str` (filesystem-safe, e.g. `"12.2.1.7.5.3.2"`); `parse_id(s) -> Cell`. Read the merged file for the exact names before you use them; if a name here differs, the merged file wins and you report the difference.

### 3.1 `archive.py`

```python
@dataclass
class Entry:
    cid: str                      # cell_id(...) of the cell
    state: str                    # path relative to the archive root, e.g. "cells/<cid>.state"
    goals: int                    # goals reached when the state was written
    steps: int                    # total emulator steps to get here
    hp: float = 0.0               # party HP fraction (statefp.party_hp_fraction)
    n_seen: int = 0               # times select chose this cell
    novelty: float = 0.0          # sum of features.weight() of keys first seen in the producing run (D3); NOT capped here
    parent: str | None = None     # cid of the cell this state was reached from
    lineage: str = "organic"
    def to_dict(self) -> dict     # asdict
    @staticmethod
    def from_dict(d: dict) -> "Entry"   # ignores unknown keys, defaults missing optional ones

def score(e: Entry) -> tuple[int, int, float]:
    return (e.goals, -e.steps, e.hp)        # bigger is better: more goals, then FEWER steps, then higher HP

class Archive:
    def __init__(self, cap: int = 1000) -> None        # self.cap, self.entries: dict[str, Entry]
    def __len__(self) -> int
    def offer(self, e: Entry) -> bool
    def mark_seen(self, cid: str) -> None              # n_seen += 1; KeyError-safe (ignore unknown cid)
    def children_of(self, cid: str) -> list[str]       # sorted cids whose entry.parent == cid
    def best_per_goals(self) -> set[str]               # for each distinct entry.goals, the cid with the max score (ties: the smaller cid)
```
Replace rule (`offer`), D3: a new cell is inserted (True). For an existing cid the offered entry replaces the stored one **only if `score(new) > score(old)` (strictly)**; the replacement takes every field of the new entry except `n_seen`, which is kept from the old one (return True). Equal or worse score: stored entry unchanged (return False). `offer` never evicts and never raises on a full archive (eviction is `store.evict`). Pure: no I/O.

### 3.2 `select.py`

```python
def rarity(n_seen: int) -> float                               # 1 / sqrt(n_seen + 1)   (same shape as novelty/tracker.py:38)
def progress(e: Entry, on_route: bool = False) -> float        # 1 + e.goals + min(5.0, e.novelty) + (1.0 if on_route else 0.0)
def weight(e: Entry, on_route: bool = False) -> float          # progress * rarity
def choose(archive: Archive, rng: random.Random, on_route: frozenset[str] = frozenset()) -> str | None
```
`choose`: iterate `sorted(archive.entries)`, weights from `weight(e, cid in on_route)`, draw `r = rng.random() * total`, return the first cid whose cumulative weight exceeds `r` (the last cid if rounding falls through); `None` for an empty archive. It does NOT mutate the archive (the caller does `archive.mark_seen`). Deterministic for a given seed and archive: the caller passes `random.Random(base_seed)`; never touch the global `random` module. `on_route` (cids on the route to the current stage goal) is supplied by the caller: no planner code here.

### 3.3 `store.py`

```python
ARCHIVE_FILE = "archive.json"
VERSION = 1

def atomic_write(path: Path, text: str) -> None
    # tmp file in the SAME directory (name includes os.getpid()), write, os.replace(tmp, path); on any exception unlink the tmp (missing_ok) and re-raise; the old file is never half-written.
def save(archive: Archive, root: Path) -> None
    # root created if missing; archive.json = {"v": 1, "cap": cap, "entries": {cid: entry.to_dict()}} via json.dumps(sort_keys=True), through atomic_write.
def load(root: Path) -> Archive
    # no archive.json -> empty Archive(); present but unreadable/invalid/other version -> raise ValueError with the path (never silently return empty: a killed driver must not "resume" into nothing).
def add_state(emu, root: Path, cid: str, source_run: str | None = None, inherit: Path | str | None = None) -> str
    # saves emu state to root/"cells"/f"{cid}.<pid>.tmp" then os.replace to root/"cells"/f"{cid}.state"; then statefp.stamp(emu, final_path, source_run, inherit=inherit); returns the relative name "cells/<cid>.state".
def evict(archive: Archive, root: Path, protected: frozenset[str] = frozenset(), on_route: frozenset[str] = frozenset()) -> list[str]
```
`evict` (D4): while `len(archive) > archive.cap`, remove one cell: the **lowest `select.weight(e, cid in on_route)`** among candidates, ties broken by smaller cid. A candidate is a cid that is **not** in `archive.best_per_goals()`, **not** in `protected` (the caller passes the path to the current frontier), and has **no children** left in the archive (`children_of(cid) == []`; recompute each round, so removing a leaf can free its parent). Removing = `del archive.entries[cid]` and unlinking (missing_ok) its state file, `statefp.sidecar(state)` and `checkpoint_goals.sidecar(state)` under `root`. If no candidate exists, stop and return what was evicted even if still over cap (never drop a protected or best-per-goals cell to make room). Returns the evicted cids in order. The caller calls `save` afterwards.

### 3.4 Tests (all synthetic, `tmp_path`, `FakeEmulator`; no ROM, no `runs/`)

`tests/test_goexplore_archive.py`:
- `test_new_cell_is_inserted`; `test_better_score_replaces_and_keeps_n_seen`: old `n_seen=3`, new has more goals -> stored, `n_seen == 3`, offer True.
- `test_replace_rule_order`: more goals beats fewer steps; same goals, fewer steps beats more steps; same goals and steps, higher hp wins.
- `test_equal_or_worse_score_is_rejected`: equal score -> False and the stored object unchanged (identity/field check); worse -> False.
- `test_best_per_goals_and_children_of`: three entries over two goal counts (one tie) -> the exact set; `children_of` sorted and exact.
- `test_entry_dict_round_trip_and_unknown_keys`.

`tests/test_goexplore_select.py`:
- `test_rarity_matches_formula` (n=0 -> 1.0, n=3 -> 0.5); `test_progress_terms`: goals, novelty capped at 5.0 (`novelty=99` adds exactly 5.0), `on_route` adds 1.0.
- `test_seeded_selection_is_deterministic`: 20 entries; two `random.Random(7)` give identical 50-draw sequences (with `mark_seen` between draws) and `random.Random(8)` gives a different one; the global `random` state is untouched (set `random.seed(1)`, record `random.random()` before/after pattern, or assert via `random.getstate()` equality).
- `test_choose_empty_is_none`; `test_choose_does_not_mutate` (all `n_seen` unchanged after `choose`).
- `test_rare_cells_are_favoured`: two equal-progress entries, one with `n_seen=99` -> over 2000 seeded draws the fresh one is picked clearly more (assert `> 2x` with a fixed seed so it never flakes).
- `test_on_route_boosts_weight`.

`tests/test_goexplore_store.py`:
- `test_save_load_round_trip` (archive.json has `"v": 1`, sorted keys, entries equal after load, `cap` preserved).
- `test_atomic_write_never_leaves_a_half_file`: save once; then monkeypatch `os.replace` (on the `store` module's `os`) to raise `OSError`; the second `save` raises, `archive.json` still holds the FIRST content and parses, and no `*.tmp` is left in the directory.
- `test_no_tmp_left_after_success`.
- `test_load_missing_is_empty_and_corrupt_raises` (write garbage / `{"v": 99}` -> `ValueError`).
- `test_add_state_writes_state_and_stamped_sidecar`: `FakeEmulator({0xD35E: 12, 0xD362: 9, 0xD361: 5})`, `add_state(emu, root, "12.2.1.0.-.-.-")` -> returns `"cells/12.2.1.0.-.-.-.state"`, the file exists, `statefp.read(...)["map"] == 12`, `statefp.lineage(...) == "organic"`, no tmp left.
- `test_evict_drops_lowest_weight_leaf`: cap 3, 5 entries (create real files for them via `add_state`): the two lowest-weight eligible cells go, their state + `.fp.json` + `.goals.json` (create a dummy goals sidecar) are deleted from disk, the survivors' files remain.
- `test_evict_never_drops_best_per_goals`: a low-weight cell that is the best of its goals count survives while a higher-weight non-best cell is evicted instead; with everyone best-per-goals or protected, `evict` returns `[]` and the archive stays over cap.
- `test_evict_never_drops_protected_or_cells_with_children`: a parent with a live child is kept; after the child is evicted the parent becomes eligible in the same call if still over cap.
- `test_evict_is_deterministic`: same archive twice -> same evicted list (ties by cid).

## 4. What NOT to do

- No emulator process, no PyBoy, no ROM, no `tools/explore_demo.py`, no `runs/` access (absent; do not look). Tests use `FakeEmulator` and `tmp_path` only.
- Do not edit `cell.py`, `__init__.py`, `statefp.py`, `checkpoint_goals.py`, `emulator.py`, `novelty/*`, or anything under `explorer/`. No lines in `explorer/context.py`, `explorer/memory.py`, `explorer/behaviours/plan_goal.py`; nothing wired into `explorer/engine.py`; no driver, runner, budget or harvest code (slices 3-4).
- Do not use the global `random` module, wall-clock time or `os.getpid()`-dependent ordering in selection or eviction (the pid appears only in tmp file names).
- Do not add a `bitmask`, a second score term, a different cap, or a different eviction rule than D3/D4 above. No new dependency. Never push or commit states or ROMs.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

First confirm slice 1 is present: `src/pokeagent/goexplore/cell.py` must exist (if not: stop, see "Read first").

**Baseline first** (run on the unmodified base). Claude ran it on 2026-11-14 on current main: `36 passed, 1 warning in 1.17s`.
```
uv run pytest -q -p no:cacheprovider tests/test_novelty*.py tests/test_goexplore_cell.py tests/test_goexplore_census.py
```
Expected: 0 failed (the two goexplore files exist once slice 1 is merged; if a name is missing, stop and write it in the Status row). If not 0 failed, stop and write the failing ids; do not fix them.

New tests:
```
uv run pytest -q -p no:cacheprovider tests/test_goexplore_archive.py tests/test_goexplore_select.py tests/test_goexplore_store.py
```
Expected: all pass, none skipped.

```
wc -l src/pokeagent/goexplore/archive.py src/pokeagent/goexplore/select.py src/pokeagent/goexplore/store.py
```
Expected: each < 120.

```
git diff --stat origin/main
git status --short
```
Expected: only the six files of section 2 (three modules, three test files).

Full suite, once, at the end (pytest-xdist is NOT installed; never use `-n`):
```
uv run pytest -q -p no:cacheprovider
```
Expected: 0 failed (base count plus your new tests; skip count unchanged from the base). Record the base count first if you can.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch (pytest-xdist is NOT installed: never use `-n`). Never read outside the working directory. Do not search, glob or hunt for missing things: if something named here is missing, stop and write why in the Status row.
- Use `uv run` and Python 3.12 only; no bare `python`.
- Create no scratch or debug files; if you need one, put it under `.devin-scratch/` and leave it there (deleting is denied).
- Never commit to main/master, never push to main, never deploy, never merge. Work on branch `directive/goexplore-slice2-archive`; commit as you go and push the branch.
- No ROM, no `runs/` access, no `tools/explore_demo.py`.
- 0 failed tests is a hard rule: no "known failures", no skips added to make it pass.
- Do NOT hand-write a `## Queue` block or edit anything between the queue markers.
- Status meaning: set `Review` when the branch is pushed with the work and every check in section 5 passes. If a tool call is genuinely blocked, stop and write why in the Status row.

## 7. Completion criteria

- [ ] `archive.py`, `select.py`, `store.py` exist with the signatures above, each < 120 lines, pure apart from `store`'s file I/O.
- [ ] Score replace rule: strictly better replaces and keeps `n_seen`; equal or worse is rejected. <!-- test: tests/test_goexplore_archive.py::test_equal_or_worse_score_is_rejected -->
- [ ] Seeded selection is deterministic and leaves global `random` untouched. <!-- test: tests/test_goexplore_select.py::test_seeded_selection_is_deterministic -->
- [ ] Eviction never drops a best-per-goals, protected, or has-children cell. <!-- test: tests/test_goexplore_store.py::test_evict_never_drops_best_per_goals -->
- [ ] `archive.json` is written atomically (a failing replace leaves the old file intact, no tmp). <!-- test: tests/test_goexplore_store.py::test_atomic_write_never_leaves_a_half_file -->
- [ ] No file outside section 2 changed; no wiring into the explorer.
- [ ] Baseline gate, new tests and the full suite: 0 failed.

## 8. Report

Findings first: the six files with exact `wc -l`, any name that differed from slice 1's merged `cell.py`, any deviation from the signatures and why. Then the real output tails: baseline gate, new tests, the full-suite line. State plainly that no ROM and no real run data were used; slice 3 (harvest) and slice 4 (driver, one real 50-step smoke return) are separate directives, and the real-ROM work is Claude's on the laptop.

## Required from User

Nothing for the build. Queue only after slice 1 has merged.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(docs/plans/go-explore-2026-11-14.md)
- Read(src/pokeagent/goexplore/cell.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git diff)
- Exec(git status)
- Exec(wc -l)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Approved |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-13 23:43 · robert-claude-laptop · none → Queued — Waits for slice 1 merge before approval/dispatch.
- 2026-11-14 00:41 · robert-claude-laptop · Queued → Approved — lint override: goexplore/archive.py, select.py, store.py and their tests are new files this directive creates; novelty/tracker.py is shorthand for src/pokeagent/novelty/tracker.py (exists); unreadable/invalid/other is prose naming three error cases, not a path.
<!-- queue:end -->
