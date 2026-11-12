# PokeAgent: Perf_Baseline counter targets - route cache that survives exploration, one real party read per step, probe counts real work

## Why this exists

Trailswarm #188 (Perf_Baseline, merge b57902f7f, head 74d7448) landed the headless-without-Tk loop, the perf probe, a
route cache, a party memo and buffered jsonl. It was merged MERGE_WITH_NITS because decisions are byte-identical and
steps/s rose, but two of its counter targets were missed and the probe misreports one of them. This directive closes
that gap.

Measured on the laptop, 2026-11-11: `tools/perf_probe.py --steps 2000 --seed 1`, `baselines/bedroom.state`, empty
maps. Base = main before #188 with a stubbed tkinter; candidate = #188 head 74d7448.

| measure | base | candidate | #188 target |
|---|---|---|---|
| steps/s | 41.3 | 47.75 | - |
| `decisions.jsonl` md5 | 574fa3e0... | 574fa3e0... (two runs) | byte-identical |
| `world.path` calls | 3,706 | 3,706 | - |
| `world._bfs_node` calls | 9,109 | 7,412 (3.71/step) | < 0.3/step |
| `world.neighbours` calls | 3.22M | 3.12M (~1559/step) | ~100/step |
| `neighbours` cumulative time | 7.9 s | 1.6 s | - |
| `path` cumulative time | 8.16 s | 3.1 s | - |
| public `read_party` calls/step | 11.88 | 11.88 | - |
| real `_read_party` calls/step | 11.88 | 2.94 | <= ~1 |

Why each miss happens (read the code, do not take this on faith):

- Route cache: `_bfs_node` is exactly 2 per `path` call (strict, then optimistic): 7,412 = 2 x 3,706. The cache
  scores almost no hits because its key includes `maps_version()` (`src/pokeagent/explorer/world.py:32`), which folds
  in `len(visited)` per map, and `NavMixin._mem_version()` (`src/pokeagent/explorer/memory_nav.py:89`) embeds it. On
  fresh memory the agent visits a new tile almost every step, so the key rolls almost every step. A newly visited tile
  does not change a route already planned over known walls, so visited-count is the wrong invalidator. The per-node
  `neighbours` memo shares the same rolling key, which is why its call count barely fell.
- Party reads: `read_party` / `read_party_count` in `src/pokeagent/ramstructs.py:123-152` memoize per
  (emulator frame, `_ram_rev`). One agent step presses a button and ticks about 11.6 frames, so the key changes
  about 1.5 times per press; the real `_read_party` runs 2.94 times per step instead of at most about 1.
- Probe attribution: `tools/perf_probe.py` `COUNTS` (line 72) counts the public memoized wrappers (`read_party`,
  `read_party_count`), so its "read_party 11.88/step" is call volume at the wrapper, not real RAM reads. It cannot
  show whether the memo works.
- Review nit: `tools/explore_demo.py` `_exit_headless` (lines 315-319) wraps `close_frame_shm(); shutdown(ctx);
  close_logs(); emu.close()` in ONE try/except, so a raising `shutdown(ctx)` skips `close_logs()` and the
  console.log drain.
- Base `explore_demo` created `tk.Tk()` even with `--headless` (fixed by #188). The probe must also be run with an
  existing `maps.json`, since empty-map results can understate cache hits.

Read first: `docs/directives/Perf_Baseline_Directive.md` (the original contract; do not redo its items);
`src/pokeagent/explorer/world.py`; `src/pokeagent/explorer/memory_nav.py`; `src/pokeagent/ramstructs.py`;
`tools/perf_probe.py`; `tools/explore_demo.py` lines 300-330; `tests/test_world_route_cache.py`,
`tests/test_perceive_memo.py`, `tests/test_headless_no_tk.py`.

## Scope (in this order; one commit per work package)

### WP1 - route cache keyed on what actually invalidates a route
Change `maps_version` / `_mem_version` / `cached_route` / `_route_graph` and the shared neighbour memo so that
VISITING NEW TILES does not roll the key, while a change that can alter a path does. Key on: blocked sets, warps,
jumps, static-NPC tiles, `temp_blocked`, beaten-trainer tiles (everything `_mem_version` reads today EXCEPT the
`len(visited)` term). Because `visited` can matter to a goal predicate (frontier goals test "unvisited"), a cached
route must additionally be dropped when its target tile has been visited since it was cached, or when the agent is
off the cached path (existing behaviour); a goal predicate that reads `visited` must stay correct, not just fast.
Prefer a per-map version of the routing-relevant data (or a dirty counter bumped at the write sites) over a global
hash recomputed every call, if it keeps `memory.py` / `context.py` under 300 lines. Target on the seeded probe:
`_bfs_node` < 0.3 calls/step, `neighbours` as close to ~100/step as the design allows (report the real number).
Files: `world.py`, `memory_nav.py` (add a small new module under `src/pokeagent/explorer/` if either would pass 300
lines; keep every explorer file under 300 and every other file <= 600).

### WP2 - one real party read per agent step
Memoize the party read per AGENT STEP, not per emulator frame, invalidated by any change of the RAM write revision
(`_ram_rev`: write or load_state). A press that does not write RAM through the adapter must not force a re-read;
battle start/end and any adapter write must. Keep the public `read_party` / `read_party_count` signatures; keep the
stub-emulator bypass (an emulator without a step marker or frames counter reads every time). The step marker is the
smallest thing available on the existing context/adapter without adding fields to `explorer/context.py` or
`memory.py` (for example a step counter the adapter already exposes, or one bumped where `ctx.step` increments).
Target: real `_read_party` <= ~1/step on the seeded probe (report the real number).

### WP3 - the probe counts real work, and runs against seeded maps
In `tools/perf_probe.py`: add `_read_party` (the real decode) alongside the public wrappers in `COUNTS`, keep
`_bfs_node` and `neighbours`, and label rows so "wrapper calls" and "real work" are visibly different. The `--maps
PATH` option already exists (line 173): confirm it copies the given maps.json into the scratch work dir (never
mutates the source) and add a test that it does; if it does not, fix it. The probe must let the controller report
both an empty-maps and a seeded-maps run; two invocations are enough, do not build more than a small `--compare` of
two saved `.prof` files if you add anything.

### WP4 - `_exit_headless` drains logs even if shutdown raises
In `tools/explore_demo.py`, restructure `_exit_headless` so each of `close_frame_shm()`, `shutdown(ctx)`,
`close_logs()`, `emu.close()` and `ctl.stop()` runs independently (try/except per call, or a small helper that runs a
list and swallows per-item errors); `close_logs()` must run even when `shutdown(ctx)` raises. Do not change the
`os._exit(0)` contract or the windowed path.

## What NOT to do

- Do not change any decision: a fixed `--seed` and state must give a byte-identical `decisions.jsonl` before and
  after. You have no ROM in the worktree, so say so; the controller runs the md5 check. The unit tests below are your
  proof, and the controller's probe run is an extra, not the only proof.
- Do not touch the emulator tick cadence, `box_pace`, `frames_per_step`, the viewer, or any other directive's scope.
- Do not add fields to `explorer/context.py` or `explorer/memory.py` beyond their 300-line ceiling.
- Do not add skips (`pytest.mark.skip`, `skipif`, `importorskip`); the ROM-gated skip count must stay 41.
- Every new acceptance test must FAIL on the pre-change code and run without the ROM (fake emulator, synthetic maps).
- No new dependency; no scratch files outside `.devin-scratch/`; never read outside the worktree; do not search
  or hunt for files that are missing, stop and say so in the Status row.

## Tests (new or extended; each must fail without its change)

- WP1 `tests/test_world_route_cache.py`: (a) synthetic map, cache a route, then mark new tiles visited elsewhere:
  `cached_route` returns the cached route with no new `_bfs_node` call; (b) add a wall or blocked tile ON the cached
  path: the route is re-searched and avoids it; (c) the rule is fixed: a cached route stays a HIT after the agent visits new tiles, as long as no wall, warp
  or blocked edge on or adjacent to that route changed; the cache key / invalidation is a per-map version of the
  blocking-edge set (blocked, warps, jumps), NOT `len(visited)`; the test asserts the hit (zero new `_bfs_node` calls)
  after visits and after a wall change far from the route; (d) a goal predicate reading `visited` returns
  the same path as the uncached BFS after visits; (e) warp, jump, temp_blocked, static-NPC and beaten-tile changes
  each invalidate. A counter test: N steps of walking a synthetic corridor produce `_bfs_node` calls / N < 0.3.
- WP2 `tests/test_perceive_memo.py`: a fake emulator counting `read` / `read_range` on the party addresses. The test
  that FAILS on pre-change code: several frames and presses within one agent step with no RAM write between them
  produce exactly one real `_read_party` (today it is one per frame window, about 1.5 per press). Also: an adapter
  write (and `load_state`) causes a re-read. Regression guard only (passes today, must keep passing): a stub
  emulator without the marker/frames counter still reads every time (`_party_key` / `_memoized`,
  `src/pokeagent/ramstructs.py` lines 112-152).
- WP3 `tests/test_perf_probe.py` (extend): the test that FAILS on pre-change code asserts the new real-work `COUNTS`
  rows (`_read_party`, `_bfs_node`, `neighbours`) are present, distinct from the wrapper rows, on the synthetic
  `.prof` fixture. Regression guard only (already passes on main, `tools/perf_probe.py` lines 134-136): `--maps`
  copies the file into the work dir and leaves the source unchanged.
- WP4 `tests/test_headless_no_tk.py` or a new `tests/test_exit_headless.py`: `shutdown` raises, `close_logs` is
  still called (and `emu.close`, `ctl.stop`).

## Verification (exact commands, from the repo root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

```
uv run pytest -q -p no:cacheprovider tests/test_world_route_cache.py tests/test_perceive_memo.py tests/test_perf_probe.py tests/test_headless_no_tk.py tests/test_explorer_behaviours.py tests/test_explorer.py
```
Expected: all pass (add any new test file you create to this list).

```
uv run pytest -q -p no:cacheprovider
```
Expected tail: 0 failed, 41 skipped (ROM-gated baseline), passed count at or above main's.

```
wc -l src/pokeagent/explorer/*.py tools/perf_probe.py tools/explore_demo.py src/pokeagent/ramstructs.py
```
Expected: every `src/pokeagent/explorer/` file under 300 lines; `tools/explore_demo.py` may exceed it (a tool); any
other file you add or edit <= 600.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download, fetch, or read outside
  the working directory. Never open a window or send input.
- Branch only; commit as you go; never commit to or push main; never merge; never deploy.
- Run every test command through `uv run`, never bare `python`.
- If a tool call is genuinely blocked, stop and write why in the Status row.

## Completion criteria

- WP1-WP4 landed with the tests above, each failing on the old code and passing on the new.
- Full suite: 0 failed, 41 skipped, no new skips; size ceilings held.
- Status row set to Review with the diff stat, test tails, `wc -l` output, and the controller's measurement list.

## Report

Diff stat, test tails, `wc -l`, and per work package the expected probe effect. Controller measurements to take on
the main checkout with the ROM (same state, seed 1, 2000 steps): `uv run python tools/perf_probe.py --steps 2000
--seed 1 --state baselines/bedroom.state` once with empty maps and once with `--maps` a seeded maps.json copy;
expect `_bfs_node` < 0.3/step, `neighbours` per step near ~100, real `_read_party` <= ~1/step, and `decisions.jsonl`
md5 identical to 574fa3e0... for the empty-maps run (compare the seeded run base vs candidate).

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never merge; never push to main.

## Required from User

- Nothing blocks the run. After Review, the controller runs the ROM probe (empty and seeded maps) and the decisions.jsonl md5 check described in the Report section.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-perf-counter-targets-directive |
| Base branch | - |
| Base commit | c2f29940494336be4a2ee36f05da02961ab2b436 |
| Model | swe-2-flash-max |

**Status log**
- 2026-11-11 · robert-claude-laptop · none → Draft — Drafted by Claude: #188 missed its route-cache and party-read counter targets; measured 2026-11-11
- 2026-11-11 08:15 · robert-claude-laptop · Draft → Queued — merged via #189 (review MERGE_WITH_NITS, nits fixed; verify 0 failed / 41 ROM skips); Robert 2026-11-11 07:15 PokeAgent focus + permanent full approval
- 2026-11-11 08:15 · robert-claude-laptop · Queued → Approved
- 2026-11-11 19:24 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-perf-counter-targets-directive; lane=explicit; model=swe-2-flash-max; perm=accept-edits; persona=steady-builder; agent_id=01M76J83FRJMBVJR8R6BDNEVHP
- 2026-11-11 19:33 · dispatcher · launched pid=2780; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-perf-counter-targets-directive; provisioned: uv sync --frozen; permission-mode=accept-edits (no `## Sandbox needs` — default deny)
<!-- queue:end -->
