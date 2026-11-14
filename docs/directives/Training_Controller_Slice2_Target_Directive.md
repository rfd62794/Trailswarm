# PokeAgent: Training Controller slice 2 (Target) - one visited, reachable training point per session; break the train_target <-> grind_episode import cycle

**Size:** M. **Model:** swe-2-high. **Assignee:** devin.

**Read first:** `docs/plans/training-controller-2026-11-13.md` (sections 2, 3, 4 item 2, 5, 6 and the "floor holds without a ledger" invariant). Slice 1 (shadow controller) is merged: `src/pokeagent/explorer/training_ctl/{state,controller,adapters}.py`, tests `tests/test_training_ctl_shadow.py`. Base: main at `7deae1b` (#245 merged: laptop-only test fixes) or later.

## 1. Why this exists

Measured on seed 12 (heal_cerulean -> beat_misty, 12000 steps, `rev-c3/runs/explore-20261113-045255-6868/console.log`): 13 grind-episode starts, 10 on VIRIDIAN_FOREST (0x33), 1 on MT_MOON_B1F (0x3C), 2 on ROUTE_24. The agent never reached 0x33 or 0x3C, so 11 episodes were phantom pins: 5,551 steps (46% of the run); 11 of 13 ended "hurt with no potion" or "party membership changed".

Why `grind/points.py` chose them: `choose()` only skips a point with no learned route (`travel_steps(...) >= FAR_TRAVEL`) when `only_maps is not None` (`points.py:178`). `train_target.only_maps` returns None for a stage with no allow-list (here `heal_cerulean`, `stage_maps.allowed` returns None) and while `train_route_live` is False, so the ledger's atlas-seeded prior points on never-visited maps win on xp/min. Nothing checks that the agent has ever been on the point's map.

Also: `train_target.py` imports `grind_episode` (only for `route_kw`), and `grind_episode.py:25` imports `train_target`. That is the cycle slice 2 breaks: episode start calls Target; Target never imports `grind_episode`.

## 2. Scope (files, in order)

1. NEW `src/pokeagent/explorer/training_ctl/target.py` (~90 lines).
2. NEW `tests/test_training_ctl_target.py`.
3. `src/pokeagent/explorer/train_target.py`: delete `route_kw` and the `grind_episode` import. Keep `stage_target`, `stage_training`, `only_maps` unchanged.
4. `src/pokeagent/explorer/grind_episode.py`: `_try_start` calls Target (line ~200); drop the `train_target` import (:25); try to delete the lazy import workaround in `_trainee_ok` (:106), see section 3 step 6.
5. `src/pokeagent/explorer/behaviours/plan_goal.py`: remove the `train_target` import (:16, shared line) and the `**train_target.route_kw(ctx)` kwarg (:133). Net lines <= 0.
6. `src/pokeagent/explorer/behaviours/grind_drill.py`: `applies()` (:43-44) reads a Target query.
7. `tests/test_train_target.py`: remove/adapt the four `route_kw` tests (lines 53-57, 77-92, 95-98); nothing else.

## 3. The work

**Current shapes (verified on df3e521).**

The cycle. `train_target.py`:
```python
from pokeagent.explorer import grind_episode          # train_target.py:13 - used ONLY by route_kw
def route_kw(ctx) -> dict:                             # train_target.py:36-52 - DELETE (whole function)
    ep = grind_episode.active(ctx) ...
```
`grind_episode.py`:
```python
from pokeagent.explorer import party_log, story_blockers, train_route, train_target   # :25
...
def _try_start(ctx, st):                               # :177
    ...
    pt = gp.choose(_ledger(ctx, st), levels or [lvl], need, (ctx.view.m, ctx.view.x, ctx.view.y), ctx.mem,
                   trainee_slot=slot, blocked=story_blockers.blocked_tiles(ctx),
                   only_maps=train_target.only_maps(ctx))                              # :199-202
    if pt is None:
        return None, "no grind point fits"
    pt.patch = gp.patch_of(ctx.mem.data.get("maps", {}), pt.map_id) or pt.patch        # :205
```
`behaviours/plan_goal.py` (300 lines, at the cap):
```python
:16  from pokeagent.explorer import after_heal, party_log, area_grind, grind_episode, magikarp_deferral, par_follow, retalk_memory, train_route, train_target
:133 ... heading=getattr(ctx, "facing", None), **train_target.route_kw(ctx)) or planned  # to the grass (the live episode's map if one runs); keep the planner's exit press if no route yet
```
Line 16 stays but loses `, train_target` (net 0, `grind_episode` stays: plan_goal uses it elsewhere). On :133 drop `, **train_target.route_kw(ctx)` and the now-stale comment text about the live episode; keep the rest of the call. Do not add or reflow any other line. Do not touch `context.py`, `memory.py`.

`grind_drill.py` reader:
```python
:43  return (grind_episode.active(ctx) is not None
:44          or 0 < (getattr(ctx, "gate_lvl", None) or lead_level(ctx.emu)) < getattr(ctx, "train_need", 0))
```
The choose signature (do NOT edit `grind/points.py`):
```python
def choose(ledger: "GrindLedger", party_levels: list, need_level: int, current_map, mem=None,
           trainee_slot: int | None = None, blocked=frozenset(), only_maps=None) -> GrindPoint | None   # points.py:190
```
`GrindLedger(points: dict[int, GrindPoint] | None = None, path=None)`; `.points` is `{map_id: GrindPoint}` (`points.py:210-214`). `travel_steps(maps, current, map_id)` (`points.py:140`) returns `FAR_TRAVEL` (10_000) when `WorldGraph(maps).path` finds no learned route from the `(map, x, y)` position.

How visited maps / learned paths are already known (there is no other source; do not look for one): `ctx.mem.data["maps"]` (`MapMemory`, `explorer/memory.py`): `maps[str(map_id)]["visited"]` is `{"x,y": count}` and is non-empty once the agent stood on the map; `maps[str(map_id)]["warps"]` are learned warps. Do NOT call `ctx.mem.m(id)` to test (it `setdefault`s an entry and would mark the map known); read `ctx.mem.data.get("maps", {}).get(str(map_id))` instead.

**Step 1: `training_ctl/target.py`.** Pure functions, no import of `grind_episode`. Imports allowed: `pokeagent.grind.points as gp`, `pokeagent.explorer.train_target` (for `only_maps`), `story_blockers`. Shape:

```python
def known(ctx, point) -> bool:
    """A point the agent can actually train at: the map has been visited AND a learned route reaches it from here."""
    maps = ctx.mem.data.get("maps", {})
    if not (maps.get(str(point.map_id)) or {}).get("visited"):
        return False                                   # never stood on that map: a phantom pin
    here = (ctx.view.m, ctx.view.x, ctx.view.y)
    return gp.travel_steps(maps, here, point.map_id) < gp.FAR_TRAVEL   # no learned path -> reject

def choose(ctx, ledger, levels, need, slot=None):
    """The ONE training point for a session, or None (empty ledger / nothing known fits): the existing scorer
    gp.choose over only the points that pass known(). Never invents a point."""
    pts = {m: p for m, p in ledger.points.items() if known(ctx, p)}
    if not pts:
        return None
    return gp.choose(gp.GrindLedger(pts), levels, need, (ctx.view.m, ctx.view.x, ctx.view.y), ctx.mem,
                     trainee_slot=slot, blocked=story_blockers.blocked_tiles(ctx),
                     only_maps=train_target.only_maps(ctx))

def wants_training(ctx) -> bool:
    """grind_drill.applies' read: an episode is live, or the trainee is under the train need.
    Exit (slice 5) will absorb the under-level half; until then it lives here, behaviour identical."""
    ep = ctx.__dict__.get("_grind_state", {}).get("episode")     # read the dict; do NOT import grind_episode
    return ep is not None or 0 < (getattr(ctx, "gate_lvl", None) or lead_level(ctx.emu)) < getattr(ctx, "train_need", 0)
```
(`lead_level` from `pokeagent.explorer.perceive`.) Keep the module under ~120 lines.

**Step 2: `grind_episode._try_start`.** Replace the `gp.choose(...)` call (:199-202) with `pt = target.choose(ctx, _ledger(ctx, st), levels or [lvl], need, slot)` (import `from pokeagent.explorer.training_ctl import target`). Keep the `if pt is None: return None, "no grind point fits"` and everything after unchanged. Remove `train_target` from the import on :25 (`gp` stays: `patch_of`, `GrindLedger`, `episode_result` are used elsewhere in the file). `_ledger()` stays as is (it still seeds from `runs/grind_atlas.json`; that is the "prior" path, and `known()` is what rejects its phantom points). An empty ledger (no `grind_points.json`, no atlas, no table) yields no points, so `target.choose` returns None and the episode never starts: the existing "no grind point fits" path, which caches 200 steps.

**Step 3: delete `route_kw`** and the `grind_episode` import from `train_target.py`; fix its module docstring's last bullet ("an episode already live ... train_route retargets") to say the retarget now lives with the episode (GrindDrill walks it).

**Step 4: plan_goal.py** as above; check `wc -l`.

**Step 5: grind_drill.py** `applies()`: replace lines 43-44 with `return target.wants_training(ctx)` (import `from pokeagent.explorer.training_ctl import target`); drop `lead_level` from the `perceive` import only if now unused there. `step()` still uses `grind_episode.active` (:47) and keeps its import.

**Step 6: the lazy import in `grind_episode._trainee_ok` (:106)** says `trainee_gate -> behaviours -> grind_drill -> this module`. The plan calls it the half-broken cycle. Try deleting it (hoist `from pokeagent.explorer.trainee_gate import trainee_check` to the top) and extend `test_fresh_process_imports` (below) with fresh-process imports of `pokeagent.explorer.grind_episode` and of `pokeagent.explorer.trainee_gate` and run it, in fresh processes. If both import cleanly, keep it hoisted. If either raises ImportError (grind_drill still imports grind_episode for `step()`), restore the lazy import, and say so in the Report: do not refactor further.

**Known behaviour delta (state it in the Report, do not "fix" it):** removing `route_kw` means plan_goal's `train_route.step` no longer retargets to a live episode's map when that episode's maps exclude Route 24. Episodes that START while `train_route_live` are already pinned to Route 24 by `only_maps`; the delta only touches an episode begun before the stage. The real-ROM A/B is Claude's.

## 4. What NOT to do

- Do not touch `grind/points.py` (scoring, `choose`, `_best`), `grind/points_io.py`, `grind/stage_maps.py`, or the ledger files (`runs/grind_points.json`, `runs/xp_spots.json`, `runs/grind_atlas.json`).
- Do not move the `train_route_live` writer (`behaviours/grind_loop.py:32`, plan_goal :129) - slice 3.
- Do not touch Roster (`trainee_gate`, `magikarp.trainee_slot_for`, `party_order`, `switch_out`), Sustain/heal (`planner.py`, `grind_heal`, `after_heal`, `retreat_heal`), Exit (`grind.py`, `GrindBudget`, `ctx.grind`), the gym hold / `floor_unmet` / `gate_lifted` logic (slice 5), the loop guard (`center_visit`, `LoopGuard`), Mart/restock.
- Add no lines to `explorer/context.py`, `explorer/memory.py`, `explorer/behaviours/plan_goal.py`. plan_goal and context must each be net <= 0 vs the base.
- Never invent a point: with an empty ledger Target returns None (the agent explores for grass). No fallback point, no hard-coded map list.
- No ROM runs, no `tools/explore_demo.py`, no ROM files touched. The seed-12 A/B is done afterwards by Claude on the laptop.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

**Baseline first.** On the unmodified base run:
```
uv run pytest -q -p no:cacheprovider tests/test_grind_points.py tests/test_grind_episode.py tests/test_train_target.py tests/test_training_v2_slice3.py tests/test_training_ctl_shadow.py
```
Expected on your base: 0 failed. (On `df3e521` two `tests/test_training_ctl_shadow.py` tests failed on Windows because `training.boss_need_for` reads local pokered boss data; that is fixed on main by the `fix/shadow-test-hermetic` merge, which pins the no-data path with monkeypatch. Do NOT edit `tests/test_training_ctl_shadow.py`.) If the baseline is not 0 failed, stop and write the failing ids in the Status row; do not fix them.

After your changes the same command must give 0 failed: the baseline count minus the removed/adapted `route_kw` tests; report the real number.

New tests, `tests/test_training_ctl_target.py` (use `make_ctx`, `use_ledger` from `tests/test_grind_episode.py` and the `MAPS`/`_ledger` helpers' style from `tests/test_train_target.py`):
- `test_never_visited_map_point_is_rejected`: ledger has a high-prior point on 0x33 whose map entry has no `visited` (or is absent) and a lower point on a visited, learned-path map; `target.choose` returns the lower one; with only the 0x33 point it returns None.
- `test_point_with_no_learned_path_is_rejected`: map visited but `travel_steps` is FAR (no warp chain from the current map): None.
- `test_empty_ledger_returns_none`: `GrindLedger({})` (and a ledger with no points) -> None; and `grind_episode.start(ctx)` returns False with `no_point_until` set (never invents a point).
- `test_known_point_is_chosen_by_the_existing_scorer`: two known points, the higher xp/min wins, identical to `gp.choose` on the same ledger.
- `test_target_module_does_not_import_grind_episode`: `"grind_episode" not in` the module's source imports (e.g. `inspect.getsource`), plus `train_target` has no attribute `grind_episode` and no `route_kw`.
- `test_wants_training_matches_the_old_applies_read`: live episode -> True; under-level, no episode -> True; level at need -> False.
- `test_episode_start_skips_a_phantom_forest_pin`: reproduce the seed-12 shape end to end: ctx on map 3 (Cerulean), `stage_goal="heal_cerulean"`, `train_route_live=False`, ledger = {0x33 high prior (never visited), ROUTE24 visited with a learned warp}; `grind_episode.start(ctx)` begins an episode on ROUTE24, never 0x33.

```
uv run pytest -q -p no:cacheprovider tests/test_grind_points.py tests/test_grind_episode.py tests/test_train_target.py tests/test_training_v2_slice3.py tests/test_training_ctl_shadow.py tests/test_training_ctl_target.py
```
Expected: 0 failed, none skipped.

```
wc -l src/pokeagent/explorer/behaviours/plan_goal.py src/pokeagent/explorer/context.py src/pokeagent/explorer/training_ctl/target.py
git diff --stat origin/main -- src/pokeagent/explorer/behaviours/plan_goal.py src/pokeagent/explorer/context.py src/pokeagent/explorer/memory.py
```
Expected: plan_goal.py <= 300 lines and its diff is net <= 0 (about -1: the kwarg and comment; line 16 changes in place), context.py exactly 300 and not in the diff, memory.py not in the diff, target.py < 120 lines.

Import-order check, as a test (no `python -c` in this run): add `test_fresh_process_imports` to `tests/test_training_ctl_target.py`. It runs `subprocess.run([sys.executable, "-c", <code>], capture_output=True, text=True)` twice, once with `import pokeagent.explorer.grind_episode, pokeagent.explorer.train_target, pokeagent.explorer.training_ctl.target, pokeagent.explorer.behaviours.grind_drill` and once with `import pokeagent.explorer.train_target` alone, and asserts `returncode == 0` for both (a fresh interpreter catches an import cycle that a warm test process hides). Then `git grep -n "route_kw\|train_target" -- src` must show `train_target` imported only by `training_ctl/target.py` (and its own file), `route_kw` nowhere.

```
uv run pytest -p no:cacheprovider -q
```
Expected: 0 failed (the base count plus your new tests; the skip count unchanged from the base). Record the base count first if you have time; run the full suite once, at the end.

```
git status --short
```
Expected: only the files in section 2 plus this directive's Queue block.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt for missing things: if something named here is missing, stop and write why in the Status row.
- Use `uv run` and Python 3.12 only; no bare `python`.
- Create no scratch or debug files; if you need one, put it under `.devin-scratch/` and leave it there (deleting is denied).
- Never commit to main/master, never push to main, never deploy, never merge. Work on branch `directive/training-ctl-slice2-target`; commit as you go and push the branch.
- No ROM runs and no `tools/explore_demo.py`; never touch ROM files.
- 0 failed tests is a hard rule: no "known failures", no skips added to make it pass.
- Do NOT hand-write a `## Queue` block or edit anything between the queue markers.
- Status meaning: set `Review` when the branch is pushed with the work and every check in section 5 passes. If a tool call is genuinely blocked, stop and write why in the Status row.

## 7. Completion criteria

- [ ] `training_ctl/target.py` exists, pure, no `grind_episode` import, reached by `grind_episode._try_start`. <!-- test: tests/test_training_ctl_target.py -->
- [ ] A point on a never-visited map, or with no learned path, is never chosen. <!-- test: tests/test_training_ctl_target.py::test_never_visited_map_point_is_rejected -->
- [ ] An empty ledger returns None and never invents a point. <!-- test: tests/test_training_ctl_target.py::test_empty_ledger_returns_none -->
- [ ] `train_target` no longer imports `grind_episode`; `route_kw` and its plan_goal use are gone; the :106 lazy import is deleted or its blocker reported.
- [ ] `grind_drill.applies` reads `target.wants_training`; behaviour identical.
- [ ] plan_goal.py and context.py net <= 0 lines; no lines added to memory.py.
- [ ] Gate tests and the full suite: 0 failed.
- [ ] `grind/points.py`, ledger files, gym-hold/floor logic, Roster/Sustain/Exit, loop guard untouched.

## 8. Report

Findings first: what changed per file, the exact `wc -l` numbers, whether the :106 lazy import could be deleted (and the ImportError if not), the removed/adapted `route_kw` tests. Then the real output tails: the baseline gate run, the new gate run, the import check, and the full-suite line. State plainly that no ROM was used; the real-ROM seed-12 A/B (episode starts on never-visited maps must be 0; Route 24 xp/1k >= 210; SHAKE <= 7.2%; heal + leave-PC < 12.9%) and the seed-13 sanity run are Claude's on the laptop after merge. Name the known behaviour delta (no `route_kw` retarget for an episode begun before the stage).

## Required from User

Nothing for the build. After merge, Claude runs the seed-12 and seed-13 A/B on the laptop.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(docs/plans/training-controller-2026-11-13.md)
- Read(src/pokeagent/grind/points.py)
- Read(src/pokeagent/explorer/grind_episode.py)
- Read(src/pokeagent/explorer/train_target.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git diff)
- Exec(git grep)
- Exec(git status)
- Exec(wc)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-training-controller-slice2-target-e25888 |
| Base branch | - |
| Base commit | 5c035e16150cbae4625a7081225c5377b2aa2ea4 |

**Status log**
- 2026-11-13 23:43 · robert-claude-laptop · none → Queued — Robert approved all recs 2026-11-14; base includes #245.
- 2026-11-13 23:45 · robert-claude-laptop · Queued → Approved — lint override: training_ctl/target.py is the new module this directive creates (Step 1), so it is correctly absent from main.
- 2026-11-13 23:46 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-training-controller-slice2-target-e25888; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M7C61EME9J437GGPGBQR05PN
<!-- queue:end -->
