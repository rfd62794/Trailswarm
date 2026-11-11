# PokeAgent: Perf_Baseline review fixes - the probe must survive the run's exit, buffered logs must flush on a crash, and the route cache must only key on immutable goal state

**Base branch:** `directive/pokeagent-perf-baseline-directive` (PR #188, head `473bccd9e`). Work on top of it; do not start from main.

## 1. Why this exists

An independent review of PR #188 (2026-11-10 22:50) returned CHANGES-NEEDED. The controller confirmed findings 1 and 2 in the code.

1. **The perf probe cannot finish a run (HIGH).** `src/pokeagent/explorer/headless_loop.py` line 44-45:

   ```python
   def run(ctx, engine, *, jobs, on_exit=None, agent_view=None, frame_pub=None, frame_every: int = 2,
           exit_fn=os._exit) -> None:
   ```

   The default `exit_fn=os._exit` is bound when the module is imported. `tools/perf_probe.py` line 143 swaps `os._exit` for `_trap_exit` only after that import, and `tools/explore_demo.py` never passes `exit_fn`. So at `ctx.done` the real `os._exit(0)` runs and the process dies before `prof.dump_stats`; no table is printed. `tests/test_perf_probe.py` only tests bucketing on a synthetic profile, so it cannot catch this.

2. **The buffered-log tail is lost on a crash or Ctrl-C (MEDIUM).** In `headless_loop.run`, `on_exit()` (line 83-84) runs only on the clean `ctx.done` path; the loop has no `try/finally`. An exception from `emu.tick` / `agent_view.tick`, or a KeyboardInterrupt, skips it. `JsonlBuffer` has no atexit hook (the only `atexit.register` in `tools/explore_demo.py` is `agent_view.close`, line 203). Up to 50 steps of transitions, decisions and progress are lost.

3. **The route cache can key on mutable state (LOW-MEDIUM, latent).** In `src/pokeagent/explorer/world.py`, `_goal_sig` accepts any hashable closure cell value, including identity-hashed objects (`ctx`, `self`, a `Decision`) whose mutable state is not in the key. No current caller is stale, but the cache is on by default for every `WorldGraph.path`.

4. **`LogRing` (headless_loop.py) flushes a file write on every log line** and its `tail` is never served by `/status`, though the module docstring says the control API serves it.

## 2. Scope

In order:
1. `src/pokeagent/explorer/headless_loop.py`: `exit_fn` resolved at call time; `try/finally` around the loop so `on_exit()` always runs; `LogRing` flushes on the 50-step cadence, not per line; correct the docstring claim about `tail` (drop it; do not wire a new endpoint).
2. `tools/explore_demo.py`: `atexit.register(<the JsonlBuffer>.close)` next to the existing `atexit.register(agent_view.close)`; restore the three startup log banners ("Explorer demo...", "Remote control...", "map memory...") on the headless path.
3. `src/pokeagent/explorer/world.py`: `_goal_sig` returns `None` (no caching) unless every closure cell value is an `int`, `str`, `bool`, `float`, `None`, `tuple` or `frozenset` (recursively for tuples/frozensets).
4. Tests: `tests/test_perf_probe.py`, `tests/test_jsonl_buffer.py`, `tests/test_world_route_cache.py` (extend these; new test files only if a test does not fit).

## 3. The work

1. Change the signature to `exit_fn=None` and the exit to `(exit_fn or os._exit)(0)`. Add a test that monkeypatches `os._exit` to a recorder, runs `run()` with a fake engine/ctx that reaches `ctx.done` after a few ticks, and asserts the recorder was called and `run()` returned control (no real exit).
2. Wrap the loop in `try: ... finally: on_exit and on_exit()`, keeping the clean path's behaviour (on_exit once, then `exit_fn(0)`). `on_exit` must not run twice: guard it or rely on `JsonlBuffer.close()` being idempotent and say which. Add a test that raises inside the loop after N < 50 buffered lines and asserts those lines are on disk.
3. Restrict `_goal_sig` as in §2.3. Add a test that a goal closing over a mutable object gets no cache entry, and that a goal closing over ints/tuples still hits the cache.
4. `LogRing`: flush on the same 50-step cadence as `JsonlBuffer`, and in `close()`.

## 4. What NOT to do

- Do not change any agent decision logic, the BFS algorithm, the party memo, or the control server.
- Do not add sleeps or throttling to the headless loop.
- Do not touch `src/pokeagent/explorer/context.py` or `memory.py` (both at 299 lines; the layering test caps explorer files below 300).
- Do not add skips or xfails. Do not edit existing assertions except where §3 requires.
- Do not commit anything under `roms/` or `runs/`.

## 5. Verification

Python is 3.12 (`uv run python --version` -> `Python 3.12.12`, checked 2026-11-10).

- `uv run pytest -q tests/test_perf_probe.py tests/test_jsonl_buffer.py tests/test_world_route_cache.py tests/test_headless_no_tk.py tests/test_explorer_behaviours.py` -> all pass (before this directive: 3 + 5 + 6 + 5 + 30 passed).
- `uv run pytest -q` -> 0 failed, and exactly 41 skipped (all ROM-gated; PR #188 reported 2407 passed / 41 skipped).

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and ends the run. Never install, download or fetch. Never read outside the working directory.
- Use exactly the commands in §5. Do not run other builds, type-checkers or process listings.
- Create no scratch or debug files; if one is needed it goes under `.devin-scratch/` and stays. Do not delete anything.
- One shell command at a time: no `&&`/`;` chains, no `$(...)`, no heredocs.
- Commit with a plain single-line message: `git commit -m "one line"`. Never commit to main, never merge, never push to the default branch, never deploy.
- Do not search, glob or hunt for anything this directive does not name. If something named here is missing, stop and write that in the Status row.
- If a command is refused, stop and report Blocked naming the refused command.

## 7. Completion criteria

- [ ] The probe test runs `run()` to completion with `os._exit` patched.
- [ ] A crash inside the loop leaves every buffered line on disk (test).
- [ ] `_goal_sig` caches only immutable closure values (test both ways).
- [ ] `LogRing` no longer flushes per line; docstring corrected; banners restored.
- [ ] §5 commands pass: 0 failed, 41 skipped.
- [ ] Status row set to Review with the branch.

## 8. Report

What changed per item, the pasted tails of both §5 commands, and anything in §1 you found to be inaccurate.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Done |
| Assigned to | devin |
| Branch | directive/pokeagent-perf-baseline-review-fixes-directive |
| Base branch | directive/pokeagent-perf-baseline-directive |
| Base commit | 473bccd9e75f7f39c9148c2a0e9ce9f92da265ee |
| Head commit | 74d7448aa43a2ee8bb771f8d8bec5f3f674a78ef |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-10 22:44 · robert-claude-laptop · none → Queued — Independent review of Trailswarm #188 CHANGES-NEEDED (probe exit, crash flush, route-cache key); controller confirmed findings 1-2 in code
- 2026-11-10 22:44 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing is the known false positive on PokeAgent directives; Robert approved all recs 2026-11-10
- 2026-11-11 06:45 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-perf-baseline-review-fixes-directive; lane=default; model=swe-2-high; perm=accept-edits; persona=steady-builder; agent_id=01M756T9VBE6T4EP5RFHVB8R11
- 2026-11-11 06:54 · dispatcher · launched pid=17564; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-perf-baseline-review-fixes-directive; provisioned: uv sync --frozen; permission-mode=accept-edits (no `## Sandbox needs` — default deny)
- 2026-11-11 07:05 · devin · In progress → Review — All 4 findings fixed + tested; targeted 54 passed, full suite 2412 passed / 41 skipped / 0 failed; commit 74d7448 pushed [origin] spent: devin 11 min est. n/a
- 2026-11-11 08:03 · robert-claude-laptop · Review → Done — note: Landed via #188 (branch fast-forwarded to 74d7448, merged b57902f7f); independent review MERGE_WITH_NITS; suite 2412 passed 0 failed 41 skipped.
<!-- queue:end -->
