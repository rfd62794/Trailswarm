# PokeAgent: agent footprint - save shared memory on change not every 10 steps, render frames only for a live reader, import nothing a headless run does not use, and budget RSS and steps/s per agent

## Why this exists

Robert 2026-11-07: make the harness "faster, more efficient, less resource intensive, but still just as feature rich";
"I approve all recommendations." Follows `Perf_Baseline_Directive.md` (headless without Tk, route cache, party
memo, buffered jsonl, perf probe). Do not start before Perf_Baseline has merged; your branch must contain it.

Measured 2026-11-07 (inventory on main 5716f75; file:line cited):

- **The biggest waste is the memory save cadence.** `src/pokeagent/explorer/press.py:141-142` saves `MapMemory`
  when `step % 10 == 0`; `MapMemory.save` (`src/pokeagent/explorer/memory.py:293-299`) does `apply_edits`, then
  `json.dumps(indent=1)` of the WHOLE memory, a tmp write and `os.replace`. The shared `runs/maps.json` is 8,711,892
  bytes (70 maps); one serialisation took 0.24 s on this laptop. A 60,000-step run therefore performs about 6,000
  saves: roughly 50 GB of JSON written and about 24 minutes of serialisation per marathon (arithmetic from the
  cadence and the one timed sample, not a timed run). The live marathon has no `--maps` argument
  (`tools/explore_demo.py:63` default) so it writes the shared file directly; swarm agents write per-agent copies
  (`runs/swarm/agent0-1048.json`, 6.8 MB) that `tools/swarm_merge.py` merges under `merge_lock` (:260) with
  `replace_durably` (:242). Other save sites: `engine.py:103-104`, `press.py:142`, `legacy.py:76`, `demos.py:72`.
  `PROMOTE_FLUSH_STEPS = 500` (`loop_memory.py:33`) governs loop-veto folds, not saves.
- **Frames are rendered whether or not anyone watches.** `src/pokeagent/telemetry.py` `FramePublisher.publish()`
  (slot `pokeagent_frames_<port>_<pid>`, :21-23) renders with `emu.tick_rendered(1)` + `emu.frame_rgb()` and writes a
  seqlock; there is no reader check. `tools/explore_demo.py:310-313` publishes every `frame_every` ticks when
  `--frame-share` is on (the marathon uses 4). The viewer reads frames for every agent every tick at 30 fps even in
  world mode (`viewer/app.py:164-187`, `sources.py` frame via `telemetry.py:127`, 69,120 bytes per read).
- **Headless imports.** `python -X importtime` of `pokeagent.explorer.engine`, `pokeagent.emulator`,
  `pokeagent.explorer.behaviours`: pyboy 352 ms cumulative, of which `pyboy.plugins.window_sdl2` 136 ms pulls `sdl2`
  (80 ms) and `pyboy.api.screen` pulls numpy (84 ms); `src/pokeagent/emulator.py:10` imports PIL; `pokeagent.explorer`
  imports `legacy.py:14` which imports the emulator at package import. `tools/explore_demo.py:23` imports tkinter and
  `:27` PIL.ImageTk at module level (Perf_Baseline removes the Tk root for headless; the imports may remain). No
  tkinter/dearpygui/cv2/matplotlib on the engine path. dearpygui is imported in 43 files under `src/pokeagent/viewer`.
- **No explorer memory numbers exist.** The AgentFlow resource sampler ledger
  (`resource-runs.jsonl`, 946 rows) has agent kinds claude-subagent/devin/verify-suite only; no pokeagent/swarm/explore
  rows. One point reading of the live marathon: python PID working set 151.7 MB (frame-share on, port 8790).
- `tools/swarm.py:7-9` docstring says visit counts "add"; `merge_memory` keeps the max.

Read first: Perf_Baseline_Directive.md and its merged code; `explorer/memory.py`, `press.py:120-145`, `engine.py`,
`telemetry.py`, `tools/swarm.py` (merge cadence, resource sampling if any), `tools/swarm_merge.py:240-290`,
`src/pokeagent/emulator.py`, `src/pokeagent/explorer/__init__.py` and `legacy.py` (import chain).

## Scope (in this order; probe before and after each with `tools/perf_probe.py`)

1. Memory save on change, bounded by time and steps, compact on disk.
2. Frames only for a live reader.
3. Lazy imports on the headless path.
4. Per-agent RSS and steps/s in the swarm's own telemetry, with budgets as tests.
5. Docstring fix in `tools/swarm.py`; tests; KNOWLEDGE.md paragraph.

## The work

### 1. Save on change

- `MapMemory` gains a dirty flag set by every mutating method (visited, blocked, warps, npcs, encounters, items,
  events, catches, edits journal, loops table, trainers, grind points). If `memory.py` cannot take it under 300 lines,
  put the flag and the save policy in a new `explorer/memory_save.py` (under 120 lines) that wraps `save`.
- Save policy: save when dirty AND (`SAVE_MIN_STEPS = 500` steps since the last save OR `SAVE_MIN_SECONDS = 60` s
  elapsed OR a run-ending event: done, blackout, segment stop, `os._exit` paths). Constants named and untuned. The
  save at `press.py:141-142` becomes a call to the policy; the end-of-run saves stay unconditional.
- On disk: `json.dumps(separators=(",", ":"))` (no indent) for the per-agent and shared files; the loader must accept
  both. Measure the size drop and paste it.
- Shared-file safety: when the agent writes the SHARED `runs/maps.json` directly (no `--maps`), take the same
  `merge_lock` the swarm uses around the replace (reuse `tools/swarm_merge.py` lock helper by moving it into
  `src/pokeagent/explorer/memory_lock.py` so both import it; `swarm_merge` keeps working).
- Test: a fixture memory with N mutations saves once per window, not per step; a run-ending event saves immediately;
  an untouched memory never saves; compact JSON round-trips through load.

### 2. Frames only for a live reader

- The frame slot header gains a reader heartbeat (a float timestamp the reader writes when it reads). `FramePublisher
  .publish()` renders only when `now - reader_ts < READER_LIVE_S = 2.0`; otherwise it skips `tick_rendered` and does
  plain `tick`. The viewer's frame reader writes the heartbeat on every read (`telemetry.py:127` path). Agents started
  without `--frame-share` are unchanged.
- The default for swarm agents becomes `--frame-share` ON with on-demand rendering (so the World view can focus any
  agent) if and only if the probe shows the no-reader cost is within 1% of steps/s; otherwise keep it off by default
  and say so.
- Test: publisher with a stale heartbeat does not call `tick_rendered`; with a fresh one it does; the viewer reader
  updates the heartbeat.

### 3. Lazy imports

- `src/pokeagent/emulator.py`: import PIL only inside the functions that need it. `src/pokeagent/explorer/__init__.py`
  / `legacy.py`: do not import the emulator at package import time (import where used). `tools/explore_demo.py`:
  tkinter and PIL.ImageTk imported only in the windowed branch (Perf_Baseline already keeps Tk out of headless; make
  the imports follow). pyboy's own sdl2/numpy imports are PyBoy's; do not patch the dependency, but check whether
  `PyBoy(..., window="null")` or the headless option avoids loading `window_sdl2`, and use it if so.
- Test: `tests/test_headless_imports.py` imports the engine and behaviours with `tkinter`, `PIL.ImageTk` and
  `dearpygui` blocked in `sys.modules` and asserts success; a second test asserts `sdl2` is not imported by
  `pokeagent.explorer.behaviours` alone.

### 4. Budgets

- `tools/swarm.py` (or the supervisor module it uses) samples each agent's RSS (psutil is already a dependency? check
  `pyproject`; if not, use `ctypes`/`GetProcessMemoryInfo` on Windows and `/proc` on Linux, under 60 lines in
  `src/pokeagent/resources.py` or a new `agent_rss.py`) and steps/s (from the control API `/status` step counter) every
  30 s, writing `runs/swarm/agent_stats.jsonl` rows {ts, agent, pid, rss_mb, steps_per_s}. `pokeagent review swarm`
  prints the median and max per run.
- Budgets as constants: `AGENT_RSS_BUDGET_MB = 200`, `AGENT_MIN_STEPS_PER_S = 20` (headless), both untuned, and a
  review warning line when exceeded. No test can measure the real agent in a worktree; test the sampler on the
  current process and the review formatting on a fixture.

### 5. Docs

- Fix `tools/swarm.py:7-9` ("visit counts add" -> "visit counts take the max").
- `docs/KNOWLEDGE.md`: "Agent footprint" paragraph: save policy, reader heartbeat, budgets, how to read agent_stats.

## What NOT to do

- Do not change what the memory contains or how `merge_memory` merges; only when and how it is written.
- Do not change the viewer's rendering (that is `Viewer_Pull_Model_Directive.md`); only add the reader heartbeat
  write where frames are read.
- Do not touch `planner*.py`, `ship_gate.py`, behaviours' decisions. `context.py`/`memory.py` stay under 300.
- No new dependency unless `pyproject` already lists it (say which you used). No scratch files outside
  `.devin-scratch/`; never read outside the worktree; the ROM and `runs/` are absent in a worktree (say so where a
  measurement is the controller's).

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run pytest -q tests/test_memory_save_policy.py tests/test_frame_publisher_heartbeat.py tests/test_headless_imports.py tests/test_agent_stats.py tests/test_explorer_behaviours.py tests/test_swarm_merge*.py
```
Expected: all pass (list the test files that exist with `ls tests/test_swarm*`).

```
uv run pytest -q
```
Expected tail: ~1908+ passed, 40 skipped (ROM-gated), 0 failed.

```
wc -l src/pokeagent/explorer/memory.py src/pokeagent/explorer/memory_save.py src/pokeagent/explorer/memory_lock.py src/pokeagent/telemetry.py src/pokeagent/emulator.py tools/swarm.py
```
Expected: every file under `src/pokeagent/explorer/` under 300.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download, fetch, or read outside
  the working directory. Never open a window.
- Branch only; commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row.

## Completion criteria

- Saves happen on the policy, compact JSON, shared-file lock; frames render only for a live reader; headless import
  tests pass; agent_stats rows and review lines exist; docstring fixed; suites green; sizes under 300.
- Status row set to Review with the diff stat, test tails, the measured maps.json size before/after compaction, and
  the controller's measurement list (probe table before/after; a 2,000-step headless run's save count and bytes).

## Report

Diff stat, test tails, wc -l line, size numbers, constants chosen, what the controller must measure.
