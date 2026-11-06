# PokeAgent: live control - hot-reloadable parameters, warm restart onto new code, and a stall feed for Claude

**Read first:** `docs/directives/Brain_Tools_Directive.md` (the edit journal and `reload_edits` - layer 1 of the
same system), `docs/superpowers/specs/2026-11-05-viewer-and-hybrid-design.md` sections 4.3 and 5.
**Depends on:** `Viewer_Window_Directive.md` merged (explore_demo's view `ControlServer`, the `EmuBridge` job
queue in `src/pokeagent/adapters/bridge.py`, `src/pokeagent/supervisor.py`). If missing, stop and write that in the
Status row. **Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-05): "How do we give you tools to be able to make on the fly changes to the model as issues are
observed? I know this moves toward a hot-loaded model." Approved design, three layers, safest first:
1. **Data** (what the agent believes): Brain Tools journal + `reload_edits` (separate directive).
2. **Parameters** (how the rules behave): this directive.
3. **Code** (the rules themselves): a **warm restart** - save state, relaunch on the new code from that exact
   frame - instead of in-process module reloading (stale references and a broken edit could kill a live run).
Plus the feed that tells Claude something went wrong: stall events.

Today's tuning knobs are module constants (e.g. `behaviours/frontier.py` `REVERSE_PENALTY = 2`, `TABU_LEN = 8`,
`RETARGET_MARGIN = 3`; `PICKUP_DETOUR` in the item-ball work; the train level `--train-level 8`; flee/potion HP
fractions and stall windows inside the battle and guard behaviours). Changing one needs a code edit and a restart.

## 2. Scope (in order)

1. **Params registry** `src/pokeagent/explorer/params.py`: `Param(name, default, kind, min, max, doc)`;
   `PARAMS` registry; `P(name)` getter used everywhere a tuning constant is read (keep the module constants as
   the defaults so behaviour is unchanged when no file exists). Register at least: REVERSE_PENALTY, TABU_LEN,
   RETARGET_MARGIN, PICKUP_DETOUR (if present), TRAIN_LEVEL, FLEE_HP_FRACTION, POTION_HP_FRACTION, the loop-guard
   windows (60/6, 40-A, 150/2) and the shake length (25). Values come from `runs/policy_params.json`
   (`{"version": n, "values": {...}, "history": [{"ts","by","note","changes"}]}`) when present; out-of-range or
   unknown names are rejected with a clear error, never silently used.
2. **`reload_params`** command on the view ControlServer (marshalled through the EmuBridge, applied between
   steps); `params_version` added to the snapshot and to every `decisions.jsonl` line so the review tool can
   grade a change.
3. **CLI + MCP**: `pokeagent params list|get|set NAME VALUE --note ...|history` (writes the file atomically and
   appends history; `set` then calls `reload_params` on every live registered agent), MCP tools `params_list`,
   `params_set`.
4. **Warm restart** `checkpoint_restart` command: on the emulator thread, save state to
   `runs/states/restart-<agent>-<ts>.state`, flush memory (`MapMemory.save()`), write
   `runs/agents/<id>.restart.json` (`{state, argv, git_sha_before}`), exit 0. `supervisor.py` gains
   `restart(agent_id)`: relaunch the agent's argv with `--state <saved>` on the current checkout, and if the new
   process exits non-zero or stops registering within 60 s, relaunch once more on the previous commit's code from
   a `git worktree` of `git_sha_before` (record which happened). CLI `pokeagent restart <agent>` and MCP
   `agent_restart`.
5. **Stall feed**: the existing loop/stall guards append to `runs/stalls.jsonl` (`{ts, agent, step, map, x, y,
   goal_stage, behaviour, signature, recovery}`); CLI `pokeagent stalls --since <ts>` and MCP `stalls_recent` so
   Claude can watch it.

## 3. The work

Behaviour must be identical with no params file (all defaults). Keep every new module under 300 lines; the
params getter is a dict lookup - no per-step file I/O.

## 4. What NOT to do

- No in-process module reload (`importlib.reload`) of behaviours.
- Never write `runs/maps.json` directly here (edits are the journal's job); the only write is the agent's own
  normal `MapMemory.save()` during `checkpoint_restart`, which re-applies the journal before writing (Brain Tools),
  so no journal edit is lost. Never kill processes the supervisor did not
  spawn.
- No new dependencies.

## 5. Verification

- `uv run pytest -q` green (paste before/after); a test that runs the selector with no params file and asserts
  identical decisions to the constants.
- Tests: params range validation; `reload_params` applies between steps (fake emulator); history appended;
  `params_version` in snapshot and decision lines; `checkpoint_restart` writes state + restart record and exits
  (fake); supervisor restart relaunches with `--state`, falls back on failure (fake process launcher); stall
  lines written by the guards.
- Do NOT run `uv run pokeagent ...` in the sandbox. Controller check on the laptop: change REVERSE_PENALTY on a
  live run and see `params_version` change; warm-restart a live run and see it continue from the same tile.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-live-control-directive`. Never commit to `main`.
- Create no scratch or debug files; if unavoidable, under `.devin-scratch/` and it stays.

## 7. Completion criteria

- [ ] params registry + file + `reload_params`; params_version in snapshots and decisions
- [ ] `pokeagent params` CLI + MCP tools
- [ ] `checkpoint_restart` + supervisor restart with rollback; CLI + MCP
- [ ] stall feed + CLI/MCP reader
- [ ] Tests in section 5 pass; `uv run pytest -q` green (paste the tail)
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts, the list of registered params with defaults, anything that did not fit.
