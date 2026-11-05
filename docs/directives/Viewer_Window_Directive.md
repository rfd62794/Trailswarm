# PokeAgent: the viewer window - Dear PyGui multi-view + focus view, agent adapters, supervisor

**Read first:** `docs/superpowers/specs/2026-11-05-viewer-and-hybrid-design.md` sections 4.1-4.4 and 7a.
**Depends on (both merged to main):** `Viewer_Core_Directive.md` (snapshot, control_server, agent_registry,
human_hold, viewer/{sources,model,layout,commands}) and `Explorer_Behaviours_Directive.md` (the
`pokeagent.explorer` package with `ExplorerContext`) and `World_Legend_And_Ledges_Directive.md` (`explorer/legend.py`;
Sees rows and legend come from it - import, do not re-implement). If any is missing, stop and write that in the Status row.
**Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

V1 gave every agent a contract and the viewer a testable core, but nothing draws yet and no agent speaks the
contract. This directive delivers the window Robert approved (mockup "layout-v4"): one native window, all agents
visible as cards, each with **Render, Sees, Thinking, Steps & Goals**; double-click a card to enlarge it and
hide the others, with an always-visible "◀ All agents" button, Esc, or double-click to return; a control bar.
Toolkit: Dear PyGui (`dearpygui` 2.3.1 is already in `uv.lock`; measured 444 fps for 12 live cards).

V1 facts you build on (already on main):
- `AgentSnapshot` fields: `agent_id, kind, v, state, stop_reason, step, segment{id,name,steps,record},
  goals[{id,name,status,steps}], thinking{want,plan,blocker,driver,rule,button,result,confidence},
  drivers{explorer,rl,human,claude}, drivers_available, recent[{step,driver,text}], human_hold, sees{rows,mode},
  screen{box_text,in_battle,party[{species,level,hp,max_hp}],money,bag_summary}, frame_slot, updated_at`;
  `DriverWindow(maxlen=100)`.
- `ControlServer(snapshot_fn, handlers, host, port, token=None)`: `.start() -> port`, `.stop()`, `.token`;
  requires header `X-PokeAgent-Token`; commands `pause, resume, speed{n}, press{button, source}, steer{on},
  hand_to{driver}, save_state{name}, load_state{name}, hold_release`; a command without a registered handler
  returns 400.
- `agent_registry.register(root, agent_id, kind, port, frame_slot, pid=None, token="")`, `unregister`,
  `list_agents`. `HumanHold(idle_s=3.0)`: `touch, active, release`.
- `viewer.sources.discover(root)`, `HttpShmSource`, `FakeSource`; `viewer.model.ViewerModel` (`poll`,
  `staleness` live/stale/lost); `viewer.layout.grid(n, w, h, ...)`, `FocusState`; `viewer.commands.KEYMAP,
  press_for_key, targets, SPEEDS, next_speed`.
- Frames: `telemetry.FramePublisher(agent_id, emu)` / `FrameSubscriber(agent_id).read() -> (bytes, w, h)`.

## 2. Scope (in order)

1. **Card shape fix** in `viewer/layout.py`: a card is Render and Sees **side by side** (two 10:9 frames wide)
   over a text block 0.75 of a frame tall (Thinking + Steps & Goals). Update `grid` and its tests so the card
   aspect is `2*10 : (9 + 0.75*9)`; assert area-maximal column counts for n = 1..12 at 1920x1000.
2. **Panels as pure view functions** `viewer/panels/` (no Dear PyGui import): `render.py` (frame bytes ->
   RGBA float list at the card size, nearest-neighbour), `sees.py` (rows + legend line; colours per glyph),
   `thinking.py` (want/plan-or-blocker/driver+rule/button->result lines, driver colour, "YOU HAVE IT 2.1s" when
   `human_hold`), `progress.py` (segment strip cells done/current/ahead, "seg N / rec M", step), `focus.py`
   (focus-only extras: recent log lines, party/bag/money, goal list with steps), `registry.py`
   (`PANELS = [...]`, card order). Colours: Explorer green `#5fa85f`, RL orange `#c88a3a`, human pink
   `#c0507f`, Claude blue `#5a8fd6`; dark theme background `#1e1f24`, panes `#141518`.
3. **Dear PyGui shell** `viewer/ui/` (all `dearpygui` imports live only here): `theme.py`, `card.py` (one card:
   texture + text widgets; double-click handler), `grid_view.py`, `focus_view.py` (with the "◀ All agents"
   button), `control_bar.py` (target selector selected/All, Pause/Resume, speed 1x/2x/4x/8x, Steer toggle,
   Hand to <driver> for `drivers_available` only, Save state / Load state… with a name field, Spawn agent…,
   Stop, Release), `keys.py` (keyboard -> `commands.press_for_key`; Esc returns to multi-view; `p` pause,
   `t` speed cycle). Stopped/lost agents dim and show `stop_reason` or "lost".
4. **`viewer/app.py`**: `run(root, fps=30)`: background thread polls `ViewerModel` (snapshots 10 Hz, frames
   30 Hz) over `discover(root)` (re-discovered every 2 s); the UI loop only reads the model (never blocks on the
   network). `--fake N` flag runs with N `FakeSource`s animating synthetic data (for demos and tests).
5. **Entry points**: `pokeagent view [--root .] [--fake N]` in `cli.py`, and `tools/view.py` (thin launcher).
6. **Explorer adapter** `src/pokeagent/adapters/explorer_snapshot.py`: `snapshot_from(ctx: ExplorerContext,
   driver_window, hold) -> AgentSnapshot` (want = current goal name, plan = active behaviour + target, driver =
   `human` while hold else `explorer`, rule = behaviour/rule name, sees.rows = the existing `ascii_vision`
   output or `battle_view` in battle, goals from the goal registry with done/current/ahead and first-reached
   steps, segment from `docs/SEGMENTS.md` ids S1..S8 mapped to goal ids `potion, left_house, first_pokemon,
   won_battle, to_route1, to_viridian, oaks_parcel, deliver_parcel`, record from `runs/best_paths.json` when
   present). Wire into `tools/explore_demo.py`: new flag `--view-port` (default `control_port + 100`; `0`
   disables); start a `ControlServer` there, enable the frame slot, `agent_registry.register` with the token,
   `unregister` on exit. Handlers: pause, resume, speed, press (human presses call `hold.touch()`), steer,
   hold_release, save_state/load_state (files `runs/states/<name>.state` via the emulator's save/load). The
   agent skips its own decision while `hold.active()`; the tk window's key presses also touch the hold.
7. **RL adapter** `src/pokeagent/adapters/rl_snapshot.py` from `tools/rl_train.py`'s status dict (its keys:
   `instance, pid, tag, generation, episode, wins, phase, epsilon, evaluation, current_steps, steps_total,
   steps_avg, steps_best, steps_worst, win_avg, rewards, updated_at`): kind `rl`, driver `rl`, rule
   `explore eps=<epsilon>` / `greedy`, segment id = `tag`, record = `steps_best`. In `rl_train.py`, when
   `--frame-port` is set, also start a `ControlServer` (handlers pause/resume only) and register.
7b. **RL brain line**: add `brain: str = ""` to `snapshot.Thinking` (schema stays v1; unknown/missing is
   fine). The RL adapter fills it with `pokeagent.qdecode.brain_line(table, obs, n_actions)` for the current
   observation - the same "brain" line `tools/webview.py` shows today (it loads the newest
   `runs/**/q_<port>*.json` via `pokeagent.qmodels.load_model(path, schema, actions)` and the last
   `runs/traces/*_<port>.jsonl` record's `final_obs`). `panels/thinking.py` shows it as its own line.
7c. **Web view on the same model** `viewer/web.py` (Robert 2026-11-05: adapt `tools/webview.py` into the
   framework): `pokeagent view --web [--port 8899]` serves a read-only page from the same `ViewerModel` +
   `panels/*` view functions (so the browser shows exactly the native cards: frame PNG, Sees, Thinking incl.
   brain, Steps & Goals). Stdlib `http.server`, bound to `127.0.0.1` only, GET only (no commands - steering stays
   in the native window), page builds DOM with `textContent` (never `innerHTML` with agent data), PNG via Pillow
   as `tools/webview.py` does. It replaces `tools/webview.py`'s hard-coded ports 8890-8895 with registry
   discovery. Leave `tools/webview.py` in place (retired later).
8. **Supervisor** `src/pokeagent/supervisor.py`: `spawn(kind, args) -> pid` (explorer: `[sys.executable,
   "tools/explore_demo.py", "--headless", "--frame-share", ...args]`; rl: `tools/rl_train.py`), `stop(pid)`;
   the control bar's Spawn/Stop call it. Agents register themselves; the supervisor does not write the registry.

## 3. The work

Keep `ui/` thin: every decision (what text, which colour, which cells, which command) comes from `panels/`,
`layout`, `commands` - pure and tested. One Dear PyGui raw texture per agent (`add_raw_texture`, RGBA float,
`set_value` per new frame only when the frame `seq` changed). Card size changes re-create textures only on
resize.

## 4. What NOT to do

- Do not delete or change `tools/watch.py`, `tools/agent_window.py`, `tools/webview.py` (retired later by its
  own directive). Do not change explore_demo's existing HTTP API on `--control-port`, its tk window, or any
  game logic.
- No new dependencies. No module over 300 lines (explore_demo.py may grow by at most 60 lines).
- `snapshot`, `control_server`, `agent_registry`, `adapters/` never import `viewer/`.

## 5. Verification

- `uv run pytest -q` green (baseline = main at dispatch; paste before/after).
- Tests: layout card aspect + area-maximal grid; every panel function on fixture snapshots (incl. missing
  fields, battle mode, human_hold countdown, stopped/lost); explorer adapter on a `FakeEmulator`-backed
  context; RL adapter on a sample status dict; supervisor builds the right argv (do not actually spawn the
  demo); UI smoke: `dpg.create_context()`, build the grid with 6 `FakeSource`s and the focus view for one,
  render no viewport, `dpg.destroy_context()` - if Dear PyGui cannot build widgets without a viewport in your
  sandbox, skip that one test with a clear reason (do not hunt for workarounds).
- `uv run python -c "from pokeagent.cli import main; main(['view', '--help'])"` prints usage.
- Do NOT run `uv run pokeagent ...` or open a window. The controller runs it live on the laptop and measures
  UI >= 30 fps with 12 agents and agent steps/sec unchanged within 5% with the viewer attached.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-viewer-window-directive`. Never commit to `main`, never merge.
- Create no scratch or debug files; if unavoidable, under `.devin-scratch/` and it stays.
- Commit per scope item.

## 7. Completion criteria

- [ ] Layout card shape fixed (item 1)
- [ ] `viewer/panels/*` pure and tested; `viewer/ui/*` Dear PyGui shell; `viewer/app.py`; `--fake N`
- [ ] `pokeagent view` + `tools/view.py`
- [ ] Explorer and RL adapters wired; human hold works in explore_demo
- [ ] Supervisor spawn/stop wired to the control bar
- [ ] `thinking.brain` filled for RL agents; `pokeagent view --web` read-only page on the same model (tests:
      `/data` JSON from FakeSources, PNG route, no POST, binds 127.0.0.1)
- [ ] `uv run pytest -q` green (paste the tail); line counts pasted
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts, grid columns for n = 1..12, what the UI smoke test could and could not exercise, and
anything you had to interpret.
