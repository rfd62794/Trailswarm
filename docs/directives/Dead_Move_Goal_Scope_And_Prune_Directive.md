# Trailswarm: the shared dead-move table is scoped to the goal stage, never vetoes the planner's own move, and is pruned of wrong entries

**Size:** M. **Assignee:** devin.

## 1. Why this exists

Measured 2026-11-08. A Blue run seeded with all of Red's memory spent over 1,200 steps pacing around the bedroom PC at map 38 (0x26), tile (0,2), never pressing A, with the goal `potion` unmet. 255 dead-move entries had been ported in. Three of them were `38,0,2,RIGHT`, `38,0,2,DOWN` and `38,0,2,LEFT`, each at 3 runs (`LOOP_PROMOTE_RUNS`), with this run as the third vote. The entry for `38,0,2,UP` had only one run, so it was not active.

**The cause is NOT proven.** What is measured: the shared key has no goal in it, so a move that was useless once a goal was finished stays dead for an agent that still needs it, and three of four directions at the tile were active vetoes. What is not shown: that those vetoes alone caused the pacing. The directive therefore ships three independent guards (scope, planner bypass, contradiction drop) plus a pruner, and each is tested on its own. Do not claim in the report that the bug is fixed; claim only what the tests show.

The pieces today, all under `src/pokeagent/explorer/` unless noted:

`loop_memory.py` (181 lines) builds and reads the shared table `mem.data["loops"]`:

```python
LOOP_RUNS_KEPT = 10; LOOP_PROMOTE_RUNS = 3; LOOP_TTL_DAYS = 7; PROBE_EVERY = 200

def shared_key(map_id: int, x: int, y: int, button: str) -> str:
    return f"{map_id},{x},{y},{button}"          # e.g. "38,0,2,RIGHT": no goal in it

def valid_entry(e) -> bool:   # {"runs": [str,...], "last": number, "clear": number}, bool is not a number
def clean_table(loops) -> dict:   # valid entries only, by reference; {} for anything not a dict
def active(e: dict, now: float) -> bool:
    return (len(e["runs"]) >= LOOP_PROMOTE_RUNS and e["last"] > e["clear"]
            and now - e["last"] < LOOP_TTL_DAYS * 86400)
def fold_shared(data: dict, keys: list[str], run_id: str, now: float) -> list[str]:   # returns dropped keys

class _Entry:  count: int = 0; veto_until: int = 0; last: int = 0; vetoes: int = 0
class LoopLedger:
    def record(self, sit: Situation, action: str, progressed: bool, step: int) -> LoopEvent | None
    def veto_keys(self) -> list[str]:
        return [shared_key(sit.map, sit.x, sit.y, action) for (sit, action), e in self.e.items() if e.vetoes > 0]
```

`Situation` is a frozen dataclass `(map, x, y, facing, text, battle)`. Leave it unchanged.

`loop_veto.py` is the seam. These are the real lines that matter:

```python
def _shared_entry(ctx, sit: Situation, button: str) -> dict | None:
    return clean_table(ctx.mem.data.get("loops")).get(shared_key(sit.map, sit.x, sit.y, button))

def of(ctx) -> Loops:            # Loops is made on first use, i.e. on the first Engine.step
    if ctx.loops is None:
        ctx.loops = Loops()
    return ctx.loops

def check(ctx, selector, decision):
    loops = of(ctx); sit = situation_of(ctx); loops.sit = sit
    if not decision.button or decision.behaviour in NEVER_VETO or sit.battle:
        return decision
    source = None
    if loops.ledger.vetoed(sit, decision.button, ctx.step):
        source = "run"
    else:
        dead_id = shared_key(sit.map, sit.x, sit.y, decision.button)
        entry = _shared_entry(ctx, sit, decision.button)
        if entry is not None and active(entry, time.time()):
            if ctx.step - loops.probes.get(dead_id, -PROBE_EVERY) >= PROBE_EVERY:
                loops.probes[dead_id] = ctx.step; loops.probe_key = dead_id
                return decision                      # one probe per key per window
            source = "shared"
            ...                                      # logs a 'promote' row once per key
    if source is None:
        return decision
    ...                                              # re-choose up to MAX_RECHOOSE times, else veto_exhausted

def record(ctx, decision, reasons: list[str]) -> None:   # after the press; reasons non-empty = progress
    ...
    if sit is not None and decision.behaviour not in NEVER_VETO and not sit.battle:
        loops.ledger.record(sit, decision.button, progressed, ctx.step)
    if ctx.step % PROMOTE_FLUSH_STEPS == 0: fold(ctx, loops)

def fold(ctx, loops=None) -> None:
    for key in fold_shared(ctx.mem.data, loops.ledger.veto_keys(), ctx.run_dir.name, time.time()):
        loops.row(ctx, {"step": ctx.step, "kind": "expire", "key": key, "source": "shared"})
```

The order in `Engine.step` (`engine.py` lines 48-63) is: `decision = self.selector.choose(ctx)` (this is where `plan_goal` runs, among other behaviours), then `loop_veto.check(ctx, self.selector, decision)`, then `veto(ctx, decision)` (retalk), then `toss_veto`. So `check` sees the planner's finished move: a `Decision` with `behaviour == "plan_goal"` and `rule` set from the plan text. `Decision` is in `behaviours/base.py` with fields including `button`, `rule`, `behaviour`, `why`, `driver`.

`goal_stage` is in `decisions.py`:

```python
def goal_stage(goals: dict) -> str:
    """The first goal not yet reached (the stage the explorer is working on), or "done"."""
    return next((g for g in GOALS if not goals.get(g)), "done")
```

It is called as `goal_stage(ctx.goals())`. Stage ids come from `data/campaign.json` and are plain identifiers such as `potion`.

`tools/swarm_merge.py` (306 lines) `merge_loops(dst: dict, src: dict, now: float | None = None) -> None` unions `runs` (capped to `LOOP_RUNS_KEPT`), maxes `last` and `clear`, then drops entries that are malformed, older than `LOOP_TTL_DAYS`, or cleared (`clear >= last`) with fewer than `LOOP_PROMOTE_RUNS` runs. It is idempotent today and must stay so. The merge loop that finishes it:

```python
    for key, e in list(dloops.items()):
        if not valid_entry(e):
            del dloops[key]
        elif now - e["last"] >= LOOP_TTL_DAYS * 86400 or (e["clear"] >= e["last"] and len(e["runs"]) < LOOP_PROMOTE_RUNS):
            del dloops[key]
```

It is called as `merge_loops(dst, src)` at `swarm_merge.py` line 187 inside `merge_memory`. Tests load tools by path, with this helper (copy it):

```python
TOOLS = Path(__file__).resolve().parents[1] / "tools"
def _load(name):
    spec = importlib.util.spec_from_file_location(f"tool_{name}_ml", TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod); return mod
```

Existing test files for this area, which must keep passing: `tests/test_loop_memory.py`, `tests/test_loop_persistence.py`, `tests/test_loop_veto_engine.py`, `tests/test_swarm_merge_loops.py`. `tests/test_loop_veto_engine.py` shows how to build a context: `ExplorerContext(emu=FakeEmulator(...), mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(), run_dir=tmp_path, stable_frames=10)`, a `Stub` behaviour with `applies(ctx)` and `step(ctx)` returning `Decision(button, rule)`, and `Selector([...])`.

## 2. Scope

In order. All new code goes in NEW small modules; every file stays under 600 lines.

1. `src/pokeagent/explorer/loop_scope.py` <!-- new: src/pokeagent/explorer/loop_scope.py --> : the scoped key format and tolerant parsing.
2. `src/pokeagent/explorer/loop_prune.py` <!-- new: src/pokeagent/explorer/loop_prune.py --> : the pure pruner (expired, malformed, contradictory) and `strip_votes`.
3. `tools/loop_prune.py` <!-- new: tools/loop_prune.py --> : a small CLI around the pruner.
4. Minimal edits (each a few lines) to `loop_memory.py`, `loop_veto.py` and `tools/swarm_merge.py` to call the new modules.
5. Tests, in a first file `tests/test_loop_scope.py` <!-- new: tests/test_loop_scope.py -->
6. and a second file `tests/test_loop_prune.py` <!-- new: tests/test_loop_prune.py -->

## 3. The work

### 3.1 Goal-scoped keys (`loop_scope.py`)

New key format: `"{map},{x},{y},{BUTTON},{stage}"` (five comma-separated parts; the stage is last). Old format: exactly four parts.

```python
def scoped_key(map_id: int, x: int, y: int, button: str, stage: str) -> str   # stage "" -> the old 4-part key
def parse_key(key) -> tuple[int, int, int, str, str | None] | None
    # (map, x, y, button, stage); stage is None for an old 4-part key; None for anything malformed
    # (not a str, wrong part count, non-int map/x/y, button not in {"UP","DOWN","LEFT","RIGHT","A","B","START","SELECT"})
```

Replace any comma in a stage id with `_` inside `scoped_key` so parsing stays unambiguous. `parse_key` never raises, whatever it is given (None, ints, empty string, a very long string).

Edits:
- `LoopLedger`: `_Entry` gets `stage: str = ""`. `record(...)` gets a new keyword `stage: str = ""` that is stored on the entry when a veto event is produced (the stage the loop was seen under, not the stage at fold time). `veto_keys()` returns `scoped_key(..., e.stage)` for entries with `vetoes > 0`. An empty stage produces the old key, so existing tests that never pass a stage keep their keys.
- `loop_veto.py`: `Loops` gets `stage: str = ""`, set in `check` right next to `loops.sit = sit` to `goal_stage(ctx.goals())` (import it from `pokeagent.explorer.decisions`). `_shared_entry` and the key built in `check` use `scoped_key(sit.map, sit.x, sit.y, button, loops.stage)`. `record` passes `stage=loops.stage` to `ledger.record`. Keep `loops.stage` set for the whole press, because `record` runs after the press, when the goal may have just been reached.
- **Old-format keys are read tolerantly.** A 4-part key parses as unscoped (`stage is None`). It is NEVER applied as a veto under any stage (applying it everywhere is exactly the bug). It is left in the table untouched by readers and removed by the pruner once it is past `LOOP_TTL_DAYS` (it also drops through the existing TTL rule in `fold_shared` and `merge_loops`). A malformed key or entry is ignored and never raises.
- `merge_loops` and `fold_shared` must treat the five-part and four-part keys as plain strings (they already do); do not change their merge arithmetic.

### 3.2 The planner is never blocked by shared history (`loop_veto.check`)

Design reasoning, so you do not reopen it: `plan_goal` runs inside `selector.choose`, before `check`. By the time `check` runs, the planner's move is already chosen, so the veto is applied to the planner's own answer. The smallest correct rule:

> In `check`, a decision with `decision.behaviour == "plan_goal"` skips the SHARED-table veto and the shared probe entirely. The in-run ledger veto (`loops.ledger.vetoed`) still applies to it.

Why this and not more: the in-run ledger is what stops a run looping on itself (the same screen, same button, no progress, 3 times). That must keep working for the planner too, so the planner is exempt only from other runs' history, never from its own. Implement it as a guard on the `else:` branch that reads the shared entry (`elif decision.behaviour != "plan_goal":` or an equivalent early skip), plus the same guard in `_vetoed` is NOT needed (a re-chosen candidate that is `plan_goal` is also exempt: pass the candidate's behaviour into the check, or apply the same condition where `cand` is tested). Put the helper `shared_applies(decision_behaviour: str) -> bool` in `loop_scope.py` so the rule is one named, testable function.

### 3.3 Contradiction rule and pruner (`loop_prune.py`)

```python
def prune_loops(loops, now: float) -> dict[str, str]:
    """Remove bad entries from ``loops`` IN PLACE; return {removed_key: reason}. Pure apart from that mutation.
    Reasons: "malformed" (bad key or bad entry shape), "expired" (now - last >= LOOP_TTL_DAYS*86400),
    "contradictory" (see below). Anything that is not a dict: return {} and touch nothing. Never raises."""
```

Contradiction rule: group entries by `(map, x, y, stage)` (stage `None` is its own group). If the group holds entries for ALL FOUR of `UP`, `DOWN`, `LEFT`, `RIGHT`, every entry in the group is dropped (reason `"contradictory"`): an agent that stood on a tile cannot have every direction dead, so those entries are wrong. Presence of an entry is enough, active or not (in the measured case `UP` had a single run and the tile would still be caught). `A` and `B` entries do not count toward the four and are never dropped by this rule. Process order: malformed, then expired, then contradictory, so a group is judged only on entries that survived.

```python
def strip_votes(loops) -> int:
    """For memory ported from a DIFFERENT game: set ``runs`` to [] on every valid entry (a ported entry carries no
    votes, so it must be re-earned in the new game: active() needs LOOP_PROMOTE_RUNS runs). Keep the keys, ``last``
    and ``clear``. Returns the number of entries changed. Malformed entries are ignored, never raised over.
    Idempotent."""
```

`strip_votes` is only a function. Do NOT call it from anywhere in this PR and do not read the Family_Shared_Memory directive (missing until its branch merges); a later directive will call it. Export it so `from pokeagent.explorer.loop_prune import strip_votes` works.

### 3.4 Wiring

- `tools/swarm_merge.py` `merge_loops`: after the existing final `for key, e in list(dloops.items()):` loop, add `prune_loops(dloops, now)` (import it lazily like the other imports in that function). Return type stays `None`; keep the change to a few lines. Merging the same `src` twice must still change nothing.
- `loop_memory.py` `fold_shared`: after its existing drop of stale/malformed entries, call `prune_loops` and extend `dropped` with the extra keys it returns, so the existing `expire` rows are logged for them. Import inside the function to avoid a circular import if needed. Keep `fold_shared` returning `list[str]`.
- Run start: in `loop_veto.of(ctx)`, when `Loops()` is first created, call `prune_loops(clean?...)` on `ctx.mem.data.get("loops")` (the raw dict, not `clean_table`'s copy, because the pruner mutates it) and, if it removed anything, `ctx.log(f"[loops: pruned {n} dead-move entries at start ({a} expired, {b} malformed, {c} contradictory)]", "res")`. Log nothing when `n == 0`. This is the single line at run start. Do not touch `src/pokeagent/cli.py`.
- `tools/loop_prune.py`: `uv run python tools/loop_prune.py <maps.json> [--dry-run]` loads the JSON file, runs `prune_loops` on its `loops`, prints one line `pruned N (expired a, malformed b, contradictory c)` and the removed keys with their reasons, and writes the file back only when not `--dry-run` and N > 0 (write atomically: temp file in the same directory, then `os.replace`). A missing file or invalid JSON prints one line and exits 1 without writing. Keep it under 80 lines and put the logic in `loop_prune.py` under `src/`, not in the tool.

### 3.5 Tests (all synthetic: `FakeEmulator`, `tmp_path`, plain dicts; no ROM, no `kb/`, no `runs/`)

`tests/test_loop_scope.py`:
1. **Goal-scope failure reproduction.** Build a table whose `RIGHT`/`DOWN`/`LEFT` entries at map 38, tile (0,2) are scoped to stage `A` with 3 runs, fresh `last`, `clear` 0. Under stage `B` (set the context's goals so `goal_stage` returns `B`; if building goals is awkward, monkeypatch `pokeagent.explorer.loop_veto.goal_stage`), `loop_veto.check` lets a `Stub` behaviour's `RIGHT` through (no re-choose, no `veto` row). Under stage `A` the same press is vetoed. Assert both; the second proves the test can fail.
2. `scoped_key`/`parse_key` round trip, 4-part old keys, and malformed inputs (None, 7, "", "a,b", "1,2,3,SIDEWAYS", "x,1,2,UP", a 10,000-character string) all return without raising.
3. Old-format key with 3 fresh runs is never applied as a veto (assert no veto under any stage).
4. A ledger veto records the stage it was seen under: loop three fruitless presses under stage `A`, change the stage to `B`, and `veto_keys()` still ends in `,A`.

`tests/test_loop_prune.py`:
5. **Planner bypass.** With an ACTIVE shared entry (3 runs, matching scoped key) for the button, a `Stub` named `plan_goal` is pressed (not vetoed) while a `Stub` with another name is vetoed. And **within-run loop detection still works for the planner**: pressing the planner's button 3 times fruitlessly via `record` makes the 4th `check` veto it (`source` `run`).
6. **Contradiction rule.** UP/DOWN/LEFT/RIGHT entries on one tile and stage are all dropped with reason `contradictory`, even when one has only 1 run; three directions plus an `A` entry drops nothing; the same four directions split across two stages drop nothing; a different tile's entries survive.
7. `prune_loops` returns the right `{key: reason}` for expired, malformed and mixed tables, is idempotent (second call returns `{}`), and returns `{}` without raising for `None`, a list, a string, and an int.
8. **Idempotent merge.** `merge_loops(dst, src, now=NOW)` twice equals once (compare with `json.dumps(..., sort_keys=True)`), including a contradictory group in `src`, which must be gone from `dst` after the first merge.
9. `fold_shared` returns the pruned keys in its dropped list.
10. `strip_votes` empties `runs` on valid entries, keeps `last`/`clear`/keys, returns the count, ignores malformed entries, is idempotent, and afterwards `active(entry, now)` is False for an entry that had 3 runs.
11. The run-start prune: build the context with a `loops` table containing one expired and one contradictory group, call `loop_veto.of(ctx)`, assert the table is cleaned and exactly one log line starting `[loops: pruned` was written (capture it from `ctx.log`; see how `tests/test_loop_veto_engine.py` reads logs and copy it); with a clean table assert no such line.
12. `tools/loop_prune.py`: with `tmp_path / "maps.json"`, `--dry-run` leaves the file byte-identical and a real run removes the bad keys; a missing file exits 1. Run it through `subprocess.run([sys.executable, str(TOOLS / "loop_prune.py"), ...])` or import it with the `_load` helper above and call its `main(argv)` returning an exit code; pick the second (no subprocess) and make `main(argv: list[str] | None = None) -> int`.

**Red behaviour must stay unchanged.** `tests/test_golden_red.py` pins the sha256 of a 400-step Red trace and **skips in your worktree** (no ROM, no `kb/rom_tables.json`, no baselines). Do not try to make it run. In your report, state that it was **NOT run**, and why. Claude's ROM-present check runs it before merge. Add a synthetic stand-in in `tests/test_loop_scope.py` instead: with no `loops` table in `mem.data`, and with an empty one, `check`'s result for every behaviour name is identical to before the change (the original decision comes back, no rows written). If you believe this PR must change the golden hash, STOP: do not edit `EXPECTED_SHA256`. Write in the PR description that the hash is expected to change and why, so a base-commit run can re-record it in the same PR (the file's own rule: "if a change is deliberate, re-record it from a base-commit run in the same PR"). It should not change: a Red run with no ported loops has an empty shared table.

## 4. What NOT to do

- Do not touch `src/pokeagent/game/` or `src/pokeagent/cli.py`. A separate Devin run is changing those.
- Do not change `retalk_veto.py`, `retalk_memory.py` or `toss_veto` behaviour, the `NEVER_VETO` set, `LOOP_NO_PROGRESS_N`, `LOOP_VETO_STEPS`, `LOOP_PROMOTE_RUNS`, `LOOP_TTL_DAYS` or `PROBE_EVERY`.
- Do not change the in-run ledger's counting, veto timing or `Situation`.
- Do not read, copy, print or commit any ROM, `kb/`, `runs/`, `roms/` or `baselines/` file. They are not in your worktree, and that is correct. Do not say where any game copy came from.
- Do not call `strip_votes` from production code, depend on the Family_Shared_Memory directive, or touch the `docs/` plan files.
- Do not edit `tests/test_golden_red.py` or its `EXPECTED_SHA256`.
- Do not grow `loop_memory.py` or `loop_veto.py` beyond the few lines named; new logic lives in the new modules. No file over 600 lines.
- Do not add dependencies, network calls or a new config section.
- Do not change existing tests' intent. If an existing test asserts an exact key from `veto_keys()` and the stage now appears in it, update only that assertion and list each such change in the report.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

```
uv run pytest -q -p no:cacheprovider tests/test_loop_scope.py tests/test_loop_prune.py
```
Expected: all pass, none skipped.

```
uv run pytest -q -p no:cacheprovider tests/test_loop_memory.py tests/test_loop_persistence.py tests/test_loop_veto_engine.py tests/test_swarm_merge_loops.py
```
Expected: all pass. Report any assertion you had to update.

```
uv run pytest -q -p no:cacheprovider tests/test_golden_red.py -rs
```
Expected: SKIPPED (no ROM). Report it as NOT run.

```
uv run pytest -q -p no:cacheprovider -x -n auto tests
```
Expected: the same result as on your base commit with no new failures; report pre-existing failures and skips separately.

```
git diff --stat main -- src/pokeagent/game src/pokeagent/cli.py
```
Expected: no output.

```
git diff --stat main -- src/pokeagent/explorer/retalk_veto.py src/pokeagent/explorer/retalk_memory.py
```
Expected: no output.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here. If something expected is missing, stop and write that in the PR description.
- Use `uv run` and Python 3.12 only. Never `uv run python -c`; put code in test files.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- If a tool call is genuinely blocked, stop and write why in the PR description.

## 7. Completion criteria

- [ ] A shared entry scoped to stage A does not veto under stage B, and does under A. <!-- test: tests/test_loop_scope.py -->
- [ ] Old-format keys parse tolerantly, never veto, and malformed keys never raise. <!-- test: tests/test_loop_scope.py -->
- [ ] A `plan_goal` decision is not vetoed by shared history, and is still vetoed by the run's own ledger. <!-- test: tests/test_loop_prune.py -->
- [ ] All four directions dead at one tile and stage are dropped; three are not. <!-- test: tests/test_loop_prune.py -->
- [ ] `prune_loops` returns removed keys with reasons, is idempotent, and is called from `merge_loops`, `fold_shared` and run start (one log line, none when nothing removed). <!-- test: tests/test_loop_prune.py -->
- [ ] `merge_loops` stays idempotent. <!-- test: tests/test_loop_prune.py -->
- [ ] `strip_votes` exists, is exported and tested, and is called nowhere in production code. <!-- test: tests/test_loop_prune.py -->
- [ ] Nothing under `src/pokeagent/game` or `src/pokeagent/cli.py` changed; no file over 600 lines.
- [ ] `tests/test_golden_red.py` reported NOT run, with a note on whether the hash is expected to change.

## 8. Report

Findings first: what each guard does and which test proves it, plainly saying the PC pacing cause is not proven. Then any existing assertion you changed, the golden status (NOT run, hash expected unchanged or not), and the command tails from section 5.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(src/pokeagent/explorer/loop_memory.py)
- Read(src/pokeagent/explorer/loop_veto.py)
- Read(src/pokeagent/explorer/decisions.py)
- Read(tools/swarm_merge.py)
- Read(tests/test_loop_veto_engine.py)
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
- 2026-11-08 17:52 · robert-claude-laptop · none → Queued — Drafted by Claude, approved by Robert 2026-11-08: scope shared dead moves to goal stage, let goal plans outrank them, prune contradictions
<!-- queue:end -->
