# Marathon Watch: stall detector for single long runs

Repo: PokeAgent (this worktree). Branch: directive/pokeagent-marathon-watch (never commit to main, never push, never merge).
Base: origin/main. Build it in your worktree only.

## Rules for this run
- NON-INTERACTIVE. No installs, no fetches, no network.
- Never read outside the worktree. No scratch files except under .devin-scratch/.
- Do not hunt for missing files or symbols. If something named here is absent or differs, stop and write why in the Status row.
- No ROM runs, no emulator, no starting or stopping any process while building or testing. All tests are synthetic.
- Verification only: `uv run pytest -q -p no:cacheprovider -rfEs <the new test files>`, then the full serial suite `uv run pytest -q -p no:cacheprovider -rfEs`. Zero failures or it is not done. Do not use bare python/pip/pytest anywhere.
- SOLID/SRP/KISS: small new modules (each well under ~150 lines), one job each.

## Why
tools/swarm_watch.py (ProgressWatch) catches `hung` (no transition for HUNG_S) and `loop` (over WINDOW_PRESSES presses no new goal AND fewer than MIN_NEW_TILES new tiles; XP/level gain via pokeagent.training_progress also resets it). Single marathon runs trickle new tiles or XP and so never trip it. Real stalls it MISSED today (controller-observed):

1. Bill's house patrol: 4,000+ steps on map 0x58 after ss_ticket, "no frontier: patrolling", loop_veto "no progress x257".
2. Cerulean Bike Shop 0x42: 1,250 steps patrolling with goal to_route5 pending.
3. Cerulean <-> Route 5 oscillation for thousands of steps (the stage had no target).
4. Post-ship detour: after the S.S. Anne the agent walked back north to Route 24 and spent ~4,500 steps (frontier exploring + grinding; new tiles and XP kept resetting the loop rule).
5. Diglett's Cave: "STALL #106" from step 845 to 4000 while ss_anne_captain was pending.

Common thread: no new campaign GOAL for thousands of steps while tiles/XP still trickle in.

## Facts already checked (origin/main), use them, do not re-derive
- Run dir `runs/explore-<ts>-<pid>/` (gitignored; do not commit anything under runs/). Files: meta.json (has `tag`, `seed`, `start`, `steps`; NO control port today), transitions.jsonl (one line per press, key `to` = [map, x, y], so press count = line count), goal_frames.jsonl (one line per goal: goal, step, frame, optional skipped), levels.jsonl (party per battle end; read with pokeagent.training_progress marks/gained), progress.jsonl (rows: step, reasons, since), loops.jsonl, decisions.jsonl, console.log (ring file; contains lines `thinking: <why>`, `--- step N/M  map=0x.. pos=(..)  ... goals: ...`, and "STALL #N detected here - escalating with X"), claude_hold.json (lease; lease_active skips judging).
- `pokeagent.goals.GOALS` is the ordered goal list; pending goals = GOALS minus goals in goal_frames.jsonl (ignore the ones in the run's own start state: the meta `start` goal).
- control_server.py (POST /command, JSON `{"cmd": ...}`) already has `save_state {name}` (NAME_RE ^[A-Za-z0-9_-]{1,64}$). It has NO stop command.
- guards.py emits the in-run "STALL #N" escalation (ctx.stalls counter).
- find_run_dir in swarm_watch finds by seed; the marathon watcher must find by meta.json `tag` prefix instead.

## Build

<!-- new: tools/marathon_watch.py -->
CLI only (argparse, glue, JSON output). `uv run python tools/marathon_watch.py --tag marathon- [--runs-dir runs] [--run <dir>] [--once] [--interval 60] [--stop] [--port N]`. One JSON line per check per run to stdout: `{"t","run","tag","step","status":"ok|stalled|held|young","reason","detail","bundle"}`. Without --once it loops every --interval seconds until Ctrl+C. Exit code 0 always (the overseer reads the lines).

<!-- new: src/pokeagent/marathon/__init__.py -->
<!-- new: src/pokeagent/marathon/reader.py -->
RunView: incremental, read-only parse of one run dir (byte-offset reads like swarm_watch, whole lines only). Exposes: press count, current map, map-segment list `[(map, first_press, last_press)]`, goal steps in order, pending goals, last-goal press, last XP/level-gain press, last "STALL #" count and the press of the first one in the current escalation burst, top `thinking:` lines of the last 400 presses (console.log tail only; tolerate rotated/missing file). Find runs: scan `runs/explore-*` whose meta.json `tag` starts with the prefix (skip unreadable). Reuse `swarm_watch.find_run_dir`-style mtime logic where it fits; import `lease_active` and `training_progress` rather than copying. Never touches any process.

<!-- new: src/pokeagent/marathon/rules.py -->
Pure functions over a RunView, each returning None or `(code, detail)`. Thresholds are module constants, in presses, tunable via CLI flags:
- `hung`: delegate to ProgressWatch.check()'s hung branch. Do NOT reimplement; instantiate or factor out minimally in swarm_watch (a small non-breaking refactor is allowed only if tests/test_swarm_watch.py stays green unchanged).
- `goal_budget`: presses since last goal (or since run start) > GOAL_BUDGET = 2500. No per-stage par step data exists in the repo (legs/par.py and segment_par.py are frame costs from ROM grids, not usable here), so use the constant. Grind stages (pending goal in a small GRIND_GOALS tuple you define next to the constant from goals/knowledge: stages that train toward a level floor) get GRIND_BUDGET = 6000, and there a level/XP gain (levels.jsonl via tp.gained) toward the floor resets the clock; tiles never do. Outside grind stages XP does NOT reset this rule.
- `map_dwell`: one map continuously > DWELL_PRESSES = 2000 presses with no goal landing and no floor-directed XP gain (dungeon maps in pokeagent.explorer.world.DUNGEON_MAPS get 2x). Catches patterns 1, 2, 4.
- `oscillation`: >= OSC_TRANSITIONS = 40 transitions between the same unordered pair of maps in the trailing 1500 presses with no goal. Catches pattern 3.
- `guard_stall`: >= STALL_ESCALATIONS = 25 distinct "STALL #" escalations since the last goal (the counter can reach 100+). Catches pattern 5 (note: confirm pending goal appears in the bundle).
Rule order = priority: hung, guard_stall, oscillation, map_dwell, goal_budget. First hit wins; all hits are listed in `detail`.
Skip entirely (status `held`) while a claude lease is active; skip (`young`) before 300 presses.

<!-- new: src/pokeagent/marathon/bundle.py -->
Writes the stall bundle `runs/stalls/<run-name>-<reason>-<press>.json` (mkdir as needed; atomic tmp+rename). Fields: run id, tag, press/step, reason code, all hits, current map, current goal = first pending goal, next 3 pending goals, last-goal step and name, map sequence summary (last 30 segments with press ranges), top 8 repeated `thinking:` lines with counts, STALL count, timestamp. Idempotent: an episode key is (run, reason, last-goal step); if a bundle with that key exists, write nothing and report its path. A new goal landing starts a new episode.

<!-- new: src/pokeagent/marathon/actions.py -->
Optional actions on STALLED, each failure-tolerant (never raise, report in the JSON line):
- save state: POST `{"cmd":"save_state","name":"stall-<press>"}` to 127.0.0.1:<port> with stdlib urllib, 3 s timeout. Port comes from --port or meta.json `control_port` if present. Add that one key (additive) to explore_demo's meta.json write (`control_port`: a.control_port) with a test in tests that already cover meta; skip the save with `save: "no port"` when absent. Once per episode.
- `--stop`: default is report only. With --stop, request a clean stop. There is no stop command today, so add a minimal `stop` command to COMMAND_ARGS + the handlers dict in explore_demo that sets the run's done flag the same way a step cap does (find how ctx.done is set; stop and write why in Status if that needs more than ~15 lines). Keep control_server tests green.

## Tests (synthetic only)
<!-- new: tests/test_marathon_watch.py -->
<!-- new: tests/test_marathon_rules.py -->
<!-- new: tests/test_marathon_bundle.py -->
Build fake run dirs in tmp_path with helper writers (transitions, goal_frames, levels, console.log lines). Cases, each asserting the exact reason code:
1. Bill's house: map 0x58 for 4,000 presses after a goal, thinking "no frontier: patrolling" repeated -> map_dwell (or goal_budget if listed first by priority; assert the documented order) and the bundle lists the repeated thinking line.
2. Bike Shop 0x42: 1,250 presses with to_route5 pending, then continue to 2,600 -> flags goal_budget at > 2500, not before.
3. Cerulean <-> Route 5 alternating for 3,000 presses -> oscillation.
4. Route 24 detour: 4,500 presses, a new tile every ~40 presses and XP gain every ~300 presses while the floor is already met -> flagged (map_dwell or goal_budget), proving tiles/XP do not reset these rules.
5. Diglett's Cave: console.log with STALL #1..#106 between presses 845 and 4000, ss_anne_captain pending -> guard_stall, bundle names ss_anne_captain as current goal.
6. HEALTHY long grind: pending grind goal, 5,000 presses on one map with floor-directed level gains every ~400 presses -> status ok. Also a healthy run that lands a goal every ~800 presses -> ok.
7. Hung (no transition growth, injected clock) reuses ProgressWatch; claude_hold.json -> held; <300 presses -> young.
8. Idempotence: two checks of the same stall = one bundle; a new goal then a new stall = a second bundle.
9. CLI: --tag prefix selects only matching runs; --once prints one valid JSON line per run; no process or network is touched (the save action is tested with a stub server on an ephemeral port).

## Done means
- New test files green, full serial suite green (zero failed), no edits to tests/test_swarm_watch.py.
- `uv run python tools/marathon_watch.py --help` runs. Do not run it against real runs.
- Brief section appended to the repo's tools docs only if a tools README already lists tools (do not create docs).
- Status row: files added, thresholds as built, the test tail, any rule you could not implement and why.

## Forbidden Actions
- Editing or reading the main checkout, any live runs/ data, ROMs, saves, or anything outside the worktree.
- Starting, stopping, signalling or attaching to any emulator/agent/swarm process; any ROM run; any network call other than the stub in tests.
- Touching protected repos (TeleseroAdminSuite2026, DialerListPulse), tools/swarm.py behaviour, or swarm_watch rules/constants (only the allowed non-breaking refactor above).
- Committing to main, pushing, merging, force-push, history rewrite, marking the directive Done.
- Installs (uv add, pip), editing lockfiles, pyproject dependencies.
- Web views or HTML output; this is a CLI and JSON only.

## Required from User
Controller (not Devin) runs this after merge, against real marathons: `uv run python tools/marathon_watch.py --tag marathon- --once`, compares flags with what was observed today (patterns 1-5), tunes GOAL_BUDGET / DWELL_PRESSES / OSC_TRANSITIONS / STALL_ESCALATIONS if a healthy leg flags, then decides whether the overseer loop reads the JSON lines and whether to enable --stop.

## Decisions (controller, 2026-11-15)

- Budgets are constants (no per-stage par step data exists; legs/par.py and segment_par.py are frame costs). Keep them CLI-tunable.
- Add `control_port` to explore_demo's meta.json; `--port` stays the fallback.
- `--stop`: add a small `stop` command to the explore_demo control server if it stays within ~15 lines; otherwise ship report-only and say so in the Report.
- GRIND_GOALS: derive from the repo's own training/hold stages (team_ready, the gym holds that enforce a team floor, grind episodes) rather than a hand list; list what you derived in the Report.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Blocked |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-15 21:48 · robert-claude-laptop · none → Queued
- 2026-11-16 00:08 · robert-claude-laptop · Queued → Approved — lint override: Cited paths are the new files this directive creates (tools/marathon_watch.py, src/pokeagent/marathon/*, tests) and gitignored runs/ areas named only as data locations.
- 2026-11-16 00:08 · dispatcher · Approved → Blocked — preflight: needs: Read(C:/Github/PokeAgent./**)
<!-- queue:end -->
