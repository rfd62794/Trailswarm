# PokeAgent: Perf_Route_Cache_Hits - make the route cache actually hit, and make the probe count the real searches

## Why this exists

Directive `Perf_Counter_Targets_Directive.md` (branch `directive/pokeagent-perf-counter-targets-directive`, head 8861063) re-keyed the route cache so that visiting new tiles no longer rolls the key. Its probe now reports `world._bfs_node` 0.00/step, which looks like a win and is not one.

Measured by the controller on 2026-11-11 on head 8861063: `tools/perf_probe.py --steps 2000 --seed 1`, `baselines/bedroom.state`, empty maps.

| measure | main | head 8861063 |
|---|---|---|
| `decisions.jsonl` md5 | 574fa3e03bc51a12adee0a34aac1eb5a | 574fa3e03bc51a12adee0a34aac1eb5a (identical, must stay so) |
| steps/s | 43.5 | 41.3 |
| `world._bfs_node` per step (probe) | 3.71 | 0.00 (misleading, see below) |
| cProfile `_bfs_route` calls | - | 9,109 |
| cProfile `_bfs_walk` calls (the real search) | - | 8,779 |
| route-cache hit rate | - | about 3.6% (330 of 9,109) |
| `world.edges` calls | - | 3.12M |
| `world.neighbours` per step | about 1,559 | 1,559 (unchanged) |
| `_suffix_edges_ok` calls | - | 32 |
| real `_read_party` per step | - | 1.16 (already fine, do not touch) |

What the numbers mean:

- The probe says `_bfs_node` 0.00 only because `WorldGraph._bfs` in `src/pokeagent/explorer/world.py` (about line 164) now calls `_bfs_route` directly, bypassing the counted `_bfs_node`. The probe counts a function nobody calls any more. The real search is `_bfs_walk`: 8,779 of them in 2,000 steps, the same volume as before.
- `_suffix_edges_ok` ran only 32 times. A cache hit has to pass through it, so hits almost never reach the revalidation path. Something earlier in `_bfs_route` (the key lookup, `ent[0] is self.maps`, the `nodes is None` miss branch, or `start in nodes`) is rejecting nearly every call. That is the bug to find.
- `neighbours` per step did not move because `edges`/`neighbours` volume is dominated by those 8,779 real searches (each expands many nodes). Fix the hit rate and this falls with it, unless another caller is driving it (WP3).

Pasted facts, because you cannot read outside this worktree. The current cache code (head 8861063), in `WorldGraph`:

```python
def _route_key(self, goal_fn, limit) -> tuple | None:
    sig = _goal_sig(goal_fn)
    if sig is None:
        return None
    return (id(self.maps), self._route_version(), self.strict, self.blocked_now,
            self.allowed_maps, sig, limit)

def _bfs_route(self, start, goal_fn, limit):
    key = self._route_key(goal_fn, limit)
    full, seen = self._version(), self._visited_total()
    if key is not None:
        ent = _ROUTES.get(key)
        if ent is not None and ent[0] is self.maps:
            src, nodes, buttons, full_v, seen_v = ent[1:]
            if nodes is None:
                if start == src and full_v == full and seen_v == seen:
                    return None
            elif start in nodes:
                i = nodes.index(start)
                if self._suffix_edges_ok(nodes, buttons, i) and goal_fn(nodes[-1]):
                    return list(nodes[i:]), list(buttons[i:])
    r = self._bfs_walk(start, goal_fn, limit)
    if key is not None:
        if len(_ROUTES) >= _CACHE_CAP:
            _ROUTES.clear()
        _ROUTES[key] = (self.maps, start, None if r is None else tuple(r[0]),
                        None if r is None else tuple(r[1]), full, seen)
    return r
```

`path()` runs a strict search first and, if that finds nothing, an optimistic one with `strict = False` (so `self.strict` is part of the key and the two passes cache separately). `_bfs` calls `_bfs_route` directly; `_bfs_node` also calls it and is used by other modules (grep `_bfs_node` under `src/`).

Hypotheses to test, not facts (the diagnosis is WP2): the key may change between consecutive calls for the same goal (`blocked_now` is a frozenset of tiles an NPC occupies and may roll every step; `_route_version()` may still change; `_goal_sig` may differ between calls); or `start in nodes` fails because the new start is a node past the cached route; or a stored MISS (`nodes is None`) is never reused because `seen` rolls on every new tile; or the cache stores a route only for the strict pass while the optimistic pass is what runs. Measure which one it is.

Read first: `src/pokeagent/explorer/world.py` (whole file, it is the subject); `src/pokeagent/explorer/memory_nav.py`; `tools/perf_probe.py` (`COUNTS`, line 73 onward); `tests/test_world_route_cache.py`; `tests/test_perf_probe.py`; `docs/directives/Perf_Counter_Targets_Directive.md` (the parent; do not redo its work packages).

## Scope (in this order; one commit per work package)

### WP1 - the probe counts real work

In `tools/perf_probe.py`: add `world._bfs_walk` (real searches) and `world.edges` to `COUNTS`; keep `world._bfs_route` as call volume. Label rows so wrapper call volume and real work are visibly different (for example a `kind` column: `wrapper` for `_bfs_route`, `read_party`, `read_party_count`; `real` for `_bfs_walk`, `edges`, `neighbours`, `_read_party`). Report cache hit rate as `1 - _bfs_walk / _bfs_route` when both are present.

Guard test: it must fail if a search bypasses the counter. Every `_bfs*` method defined on `WorldGraph` must be either listed in `COUNTS` or listed in an explicit `NOT_COUNTED` allow-list in the probe with a one-line reason. Adding a new `_bfs_*` method without touching the probe must fail the test.

### WP2 - diagnose the cache miss, then fix it

First, a test with a scripted walk on a synthetic corridor/room map (no ROM, no emulator): call `path(start, goal_fn)` repeatedly with the SAME goal function while the start advances one tile along the planned route each call. Under a `monkeypatch`, record for each consecutive pair of calls which components of `_route_key` differ (`_route_version()`, `strict`, `blocked_now`, `allowed_maps`, `sig`, `limit`), whether `start in nodes`, and whether `_suffix_edges_ok` was reached. Put that table in the assertion failure message (do not leave a print). The test asserts the target behaviour below, so it FAILS on the current code until the fix lands.

Then fix the cause the table shows. Target behaviour: a repeated goal along a planned route is a cache hit. Walking a synthetic corridor of N tiles with one fixed goal does exactly 1 real search (`_bfs_walk`) for the strict pass, not N. Cases that must still re-search: a wall or blocked edge ON the remaining path; the agent stepping off the path; a warp, jump, `temp_blocked`, static-NPC or beaten-tile change; `blocked_now` changing in a way that touches the path; a goal predicate that no longer accepts the cached target. A goal predicate reading `visited` must return the same path as the uncached BFS after visits.

On the controller probe (see Required from User) the targets are: real searches (`_bfs_walk`) < 0.5 per step, `neighbours` toward about 100 per step (report the real number), steps/s above main's 43.5. Do not overfit the number: a hit that returns a wrong route is worse than a miss.

### WP3 - only if `neighbours`/`edges` is driven by something other than route search

After WP2, if the unit-level counter test shows `neighbours`/`edges` volume still high on a synthetic run, find which caller drives it (cProfile caller stats in the test, or count calls by caller name) and memoize at that caller with an explicit invalidation (the same version token the route cache uses). Add a test that the memo returns the fresh answer after a wall, warp, jump, `blocked_now` or visited change that can affect it. If route search is already the only large driver, skip WP3 and say so in the report.

Files: `src/pokeagent/explorer/world.py`, `src/pokeagent/explorer/memory_nav.py`, `tools/perf_probe.py`, tests. If `world.py` would pass 300 lines (explorer ceiling), move the route cache into a small new module under `src/pokeagent/explorer/`; keep every explorer file under 300 lines and every other file at 600 or less.

## What NOT to do

- Do not change any decision: a fixed `--seed` and state must give a byte-identical `decisions.jsonl` (md5 574fa3e03bc51a12adee0a34aac1eb5a on the controller probe above). You have no ROM in the worktree, so you cannot check it; the unit tests are your proof and the controller runs the md5 check.
- Do not touch `_read_party` / `ramstructs.py` (1.16/step is fine), the emulator tick cadence, `box_pace`, `frames_per_step`, the viewer, `src/pokeagent/game`, or any other directive's scope.
- Do not add skips (`pytest.mark.skip`, `skipif`, `importorskip`); the ROM-gated skip count must stay 41.
- Every new acceptance test must FAIL on the pre-change code and run without the ROM (synthetic maps, no emulator).
- No new dependency; no scratch files outside `.devin-scratch/`; never read outside the worktree; do not search or hunt for a ROM, a state, `maps.json` or `kb/` data. If something expected is missing, stop and write that in the Status row.
- Do not widen the cache to a global "any route near here" scheme; keep the per-goal-signature design and fix why it misses.

## Verification (exact commands, from the repo root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

```
uv run pytest -q -p no:cacheprovider tests/test_world_route_cache.py tests/test_perf_probe.py tests/test_perceive_memo.py tests/test_headless_no_tk.py tests/test_explorer_behaviours.py tests/test_explorer.py
```
Expected: all pass (add any new test file you create to this list).

```
uv run pytest -q -p no:cacheprovider
```
Expected tail: 0 failed, 41 skipped (ROM-gated baseline), passed count at or above the base's.

```
wc -l src/pokeagent/explorer/*.py tools/perf_probe.py
```
Expected: every `src/pokeagent/explorer/` file under 300 lines; any other file you add or edit at 600 or less.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download, fetch, or read outside the working directory. Never open a window or send input. Do not search, glob or hunt beyond the files named here.
- Use `uv run` and Python 3.12 only; never bare `python`.
- Branch only; commit as you go; never commit to or push main; never merge; never deploy.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- If a tool call is genuinely blocked, stop and write why in the Status row.

## Completion criteria

- [ ] Probe `COUNTS` includes `_bfs_walk` and `edges` as real work and labels wrapper vs real; the guard test fails when a `_bfs*` search method is neither counted nor allow-listed. <!-- test: tests/test_perf_probe.py -->
- [ ] The scripted-walk test shows a repeated goal along a planned route does 1 real search for N steps, and fails on the old code. <!-- test: tests/test_world_route_cache.py -->
- [ ] Wall on path, off path, warp, jump, `temp_blocked`, static-NPC, beaten-tile and `visited`-reading goal cases all give the same route as an uncached BFS. <!-- test: tests/test_world_route_cache.py -->
- [ ] WP3 either landed with an invalidation test, or the report says why it was skipped.
- [ ] Full suite: 0 failed, 41 skipped, no new skips; size ceilings held.

## Report

Findings first: the key-component table from the WP2 test (which component changed between consecutive calls) and the one-line root cause; then diff stat, test tails, `wc -l`, and per work package the expected probe effect. State plainly that the ROM probe and md5 check were NOT run.

## Required from User

Nothing blocks the run. After Review, the controller measures on the main checkout with the ROM and `baselines/bedroom.state` (seed 1, 2000 steps): `uv run python tools/perf_probe.py --steps 2000 --seed 1 --state baselines/bedroom.state` with empty maps, and once more with `--maps` a seeded maps.json copy. Expect real `_bfs_walk` < 0.5/step, `neighbours` near 100/step, steps/s above 43.5, and the empty-maps `decisions.jsonl` md5 equal to 574fa3e03bc51a12adee0a34aac1eb5a (compare the seeded run base vs candidate).

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never merge; never push to main.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Draft |
| Assigned to | devin |
| Branch | - |
| Base branch | directive/pokeagent-perf-counter-targets-directive |

**Status log**
- 2026-11-11 · robert-claude-laptop · none → Draft — Drafted by Claude: head 8861063 cache hit rate about 3.6%; probe counts a bypassed function
<!-- queue:end -->
