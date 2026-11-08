# PokeAgent: performance baseline - headless runs without the Tk event loop, one route search per target, one party read per step, buffered logs, and a repeatable perf probe

## Why this exists

Robert, 2026-11-07: "explore ways to make the codebase faster, more efficient, and less resource demanding, where
possible" (the laptop runs the marathon agent, the World view, Devin runs and verify suites at once; tonight it sat at
0.4 GB free RAM and Devin dispatches were held). The first marathon run (explore-20261107-191457-26240) did 60,000
steps in about 110 minutes: about 9 steps/s, at about 11.6 emulated frames per step, i.e. roughly 105 emulated
frames per second, while PyBoy headless can run thousands. The loop around the emulator is the cost.

Measured 2026-11-07 (cProfile of a 2,000-step `tools/explore_demo.py --headless` run from `baselines/bedroom.state`
on main 09219b0, under laptop load; total 111.6 s under the profiler, about 17.9 steps/s; buckets by file/function
regex, so coarse):

| bucket | tottime | share | hottest function |
|---|---|---|---|
| PyBoy tick/emulation | 28.9 s | 25.9% | `emulator.py:102 tick`, 27.1 s, 18,634 calls (9.3 ticks per press) |
| decision logic | 31.0 s | 27.8% | `explorer/world.py:55 neighbours`, 5.8 s, 1,936,764 calls; `goals.check_goals` 2.6 s / 20,882 calls; `world._bfs_node` 1.4 s / 5,483 calls |
| Tk GUI loop | 18.4 s | 16.5% | `_tkinter tkapp.call`, 18.0 s, 25,530 calls; 9,280 Tk frame callbacks; `Text.see()` from the log function 19.9 s cumulative |
| other (dict.get etc.) | 18.2 s | 16.3% | `dict.get`, 4.8 s, 25,249,359 calls |
| socket/select wait | 10.5 s | 9.4% | `select.select`, 8.4 s (control API) |
| file I/O / json | 2.6 s | 2.3% | `json.encoder._iterencode_dict`, 1.3 s, 3,955,909 calls |
| RAM/screen reads | 2.0 s | 1.8% | `perceive.py:72 ascii_vision`, 0.4 s, 1,547 calls |
| logging | 0.05 s | 0.04% | (the Tk cost of the log widget is counted under Tk) |

Per step (2,000 steps, 2,009 presses): `read_party` 5.66 calls, `read_party_count` 5.66, `read_snapshot` 1.00,
`world.path` 0.95, `world._bfs_node` 2.74, `memory_nav.choose_local` 1.81, `json.dumps` 2.87.

How the headless run is driven today (`tools/explore_demo.py`, 381 lines): line 124 creates `root = tk.Tk()` with a
screen Label, a 78x28 `tk.Text` console, a vision Label and a dialog Label UNCONDITIONALLY; the `log` closure (line
139-140) does `con.insert("end", ...)` and `con.see("end")` on every log line even when headless; line 369
`root.withdraw()` hides the window when `--headless` (so the window still exists, flashes on screen at creation,
and its Text widget keeps growing); line 365 `root.after(1 if a.headless else 16, frame)` and line 376
`root.mainloop()` make Tk's event loop drive every step; line 363 `os._exit(0)` ends a headless run. Hard rule in this
repo: nothing may open a window or send input on Robert's screen except the viewer he asked for; a headless run that
creates a Tk root violates it.

`src/pokeagent/explorer/world.py` (143 lines): `neighbours` at :55, `path` at :80 (`limit=5000`), `_bfs_node` at
:100; there is an `_npc_cache` at :44 and no route cache. `memory_nav.py` is 154 lines. `engine.py` is 158 lines.
`explorer/context.py` and `memory.py` are at 299 lines (ceiling 300, `tests/test_explorer_behaviours.py::
test_explorer_package_layering_and_size`).

Read first: `tools/explore_demo.py` in full; `src/pokeagent/explorer/world.py`, `memory_nav.py`, `engine.py`;
`src/pokeagent/control_server.py` (the socket/select cost); the `read_party` / `read_party_count` definitions
(`grep -rn "def read_party" src/pokeagent`); `docs/KNOWLEDGE.md` press-cost notes.

## Scope (in this order; measure after each item with the probe from item 1)

1. `tools/perf_probe.py` (new): a repeatable probe. Runs `explore_demo` headless for N steps under cProfile from a
   given state into a scratch runs dir and prints the bucket table above (buckets as named functions, not regex
   guesses where you can do better), steps/s, and the per-step call counts. Pure Python, no new dependency. Its
   output is the before/after evidence for every other item; paste its table in the Status row before and after.
2. Headless without Tk: in `tools/explore_demo.py`, when `--headless`, never import or create Tk. Drive the run with
   a plain loop (`while not ctx.done: frame()`), keep the control API thread, keep the `os._exit(0)` semantics for
   swarm parents, and make `log` append to the run's log file (or a bounded in-memory ring the control API `/status`
   can serve) instead of a Text widget. The windowed path stays as it is. Split the file if it passes 300 lines
   (`tools/explore_demo.py` may stay over; it is a tool, but keep the new headless loop in a small module such as
   `src/pokeagent/explorer/headless_loop.py` under 150 lines so it is testable).
3. One route search per target: in `world.py`/`memory_nav.py`, cache the last BFS result keyed by (start map, goal
   key, a version counter of the map memory and `temp_blocked`); re-run only when the key changes or the agent leaves
   the cached path; memoise `neighbours` per node per memory version. Target: `_bfs_node` under 0.3 calls per step on
   the probe, `neighbours` under 200,000 calls per 2,000 steps. Correctness first: the cached path must be invalidated
   on any wall/warp/NPC/temp_blocked change (there is a memory version or dirty flag to add in `memory.py` only if it
   stays under 300 lines; otherwise a counter on the `WorldGraph` owner).
4. One party read per step: `read_party` and `read_party_count` are called 5.66 times per step each; memoise per
   (step, battle) on the existing context without new fields (a small `perceive` cache keyed by `ctx.step`), so a
   step reads the party at most once unless a press changed it.
5. Buffered jsonl: `transitions.jsonl`, `decisions.jsonl` and the other per-step appends go through one buffered
   writer flushed every 50 steps and on exit/`os._exit` paths (register the flush before `_exit`), so a crash loses at
   most 50 steps. `json.dumps` per step should drop below 1.
6. Control API wait: find why `select.select` shows 8.4 s in the main thread profile (serve_forever poll interval, or a
   blocking accept on the main thread); make the server thread's poll interval 0.5 s and ensure no socket wait sits
   on the stepping thread.
7. Tests: `tests/test_headless_no_tk.py` (running the headless entry with `tkinter` blocked in `sys.modules` works;
   a sentinel asserts `tkinter` is never imported in headless mode), `tests/test_world_route_cache.py` (cache hit,
   invalidation on each change kind, identical paths to the uncached BFS on a fixture map), `tests/test_perceive_memo.py`,
   `tests/test_jsonl_buffer.py` (flush on count and on exit). `tests/test_explorer_behaviours.py` stays green.

## What NOT to do

- Do not change any behaviour's decisions: the probe run's `decisions.jsonl` for a fixed `--seed` and state must be
  identical before and after items 3-6 (add this as a test on a short fixture run if the ROM is available in your
  worktree; it is not, so say so and rely on the unit tests; the controller runs the identical-decisions check).
- Do not touch the emulator adapter's tick cadence, `box_pace`, `frames_per_step`, or the viewer.
- Do not add fields to `explorer/context.py` or `memory.py` beyond the 300-line ceiling.
- No new dependency; no scratch files outside `.devin-scratch/`; never read outside the worktree; the ROM and
  `runs/` are absent in a worktree, so the probe itself cannot be run by you (write it, test its bucketing on a
  recorded `.prof` fixture you create synthetically), and say so.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run pytest -q tests/test_headless_no_tk.py tests/test_world_route_cache.py tests/test_perceive_memo.py tests/test_jsonl_buffer.py tests/test_explorer_behaviours.py tests/test_explorer.py
```
Expected: all pass.

```
uv run pytest -q
```
Expected tail at main 09219b0 or later: ~1908+ passed, 40 skipped (ROM-gated), 0 failed.

```
wc -l tools/explore_demo.py src/pokeagent/explorer/headless_loop.py src/pokeagent/explorer/world.py src/pokeagent/explorer/memory_nav.py src/pokeagent/explorer/context.py src/pokeagent/explorer/memory.py
```
Expected: every file under `src/pokeagent/explorer/` under 300.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download, fetch, or read outside
  the working directory. Never open a window.
- Branch only; commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row.

## Completion criteria

- Headless runs create no Tk root (test proves it); route cache, party memo, buffered jsonl and the control API
  change exist with tests; suites green; sizes under 300; `tools/perf_probe.py` committed with a `--help` and a
  fixture-based test.
- Status row set to Review with the diff stat and test tails, plus the list of measurements the controller must take
  with the probe (before: the table above; after: your expected deltas per item).

## Report

Diff stat, test tails, wc -l line, and for each of items 2-6 the expected effect on the probe's buckets.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-07 21:07 · robert-claude-laptop · none → Queued — Claude 2026-11-07 from Robert's efficiency request; cProfile evidence pasted (Tk loop 16.5%, BFS 28%, emulator 26%)
<!-- queue:end -->
