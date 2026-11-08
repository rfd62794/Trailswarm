# PokeAgent: viewer pull model - poll agents at 1-2 Hz, render from cache, frames only for what is on screen, and a swarm page that shows grades and next segments

## Why this exists

Robert 2026-11-07 approved: "The World view polls each agent's control API at 1 to 2 Hz and renders at 30 fps from
cached state, with frames only for the focused card. UX polish then builds on a stable, cheap data feed: the health
badge, stall and break cards, Stadium pane, and a swarm page that shows the curriculum's grades and the next segment
per slot." Independent of Perf_Baseline (viewer code only); pairs with `Agent_Footprint_Directive.md` item 2 (reader
heartbeat on the frame slot: this directive WRITES the heartbeat whenever it reads a frame).

Measured 2026-11-07 (inventory on main; `src/pokeagent/viewer/`):

- `viewer/app.py:164-187`: the poll thread sleeps `1/fps` per tick, `fps` default 30 (:214). Every tick calls
  `model.poll` (`viewer/model.py:47-55`), which runs EVERY source on an 8-worker pool and waits. Per agent per tick:
  `snapshot()` is throttled to `SNAPSHOT_HZ = 10` (app.py:27, `_Throttle` :30-49), an HTTP GET `/snapshot` (`sources.py`,
  0.5 s timeout); `frame()` runs EVERY tick and reads shared memory (`telemetry.py:127`), copying 160x144x3 = 69,120
  bytes per read, for every agent, even in world mode where `world_view.py` reads no frames. Registry rescan every 60
  ticks (app.py:168-175).
- Health: `HEALTH_POLL_S = 1.0` (`viewer/health_classify.py:16`), `poll_due` (`health.py:88-90`), stats `runs/stalls`,
  `runs/anomalies`, `runs/anomalies.jsonl` (health.py:142-144); invariants on a one-shot worker (health.py:235). PR #155
  moved classification off the render path.
- World view: `world/model.py` `POLL_S = 0.2` (:19); `WorldModel.poll` (:109-119) GETs `/events?since=`. Stadium pane
  (`stadium_pane.py:78-90`) takes battle cards from `WorldModel.stadium(now)` and frames from `model.frame`; live frame
  re-upload at most every `FRAME_S = 0.1` s (:19, :52). Cards and focus: `grid_view.py:92`, `focus_view.py:61`,
  `web.py:48,93` call `model.frame` each UI refresh.
- Staleness: `LIVE_S = 2.0`, `LOST_S = 10.0` (model.py:16, 74), prune after 60 s (:42). Registry: agents write
  `<root>/runs/agents/<id>.json` (`agent_registry.py`), `list_agents` prunes dead pids (:58-62).
- Control API (`control_server.py`, 193 lines): GET `/snapshot` (:130), GET `/events?since=N` (:122), POST `/command`
  (:153); `/status`, `/goals`, `/screen`, `/map`, `/vision`, `/peek`, `/sprites` live in `tools/explore_demo.py:220-278`.
  `AgentSnapshot` keys: agent_id, kind, v, state, stop_reason, step, segment, goals, thinking, drivers,
  drivers_available, recent, sees, screen, human_hold, claude_hold_s, extra, frame_slot, updated_at.
- Sizes: app.py 222, health.py 269, ui/window.py 280, ui/world_view.py 282, ui/card.py 291, stadium_pane.py 90,
  model.py 88, sources.py 106. The directive rule for viewer modules is under 300 lines each.
- Measured tonight: the World view ran at 27-28 fps idle and dropped to 7 fps while the laptop was loaded (three
  Devin suites + the marathon), i.e. the viewer competes for the same CPU as the agents it watches.

Read first: `viewer/app.py`, `viewer/model.py`, `viewer/sources.py`, `viewer/health.py`, `viewer/ui/grid_view.py`,
`focus_view.py`, `world_view.py`, `stadium_pane.py`, `world/model.py`, `telemetry.py` (frame slot layout),
`docs/research/viewer-ux-standards-2026-11-07.md` (the research the viewer follows), `Viewer_UX_V1_Directive.md`.

## Scope (in this order)

1. Decouple polling from rendering: a poll cadence per source kind, independent of fps.
2. Frames only for what is on screen.
3. Reader heartbeat on the frame slot.
4. The swarm page: per-slot grade, segment, next job, steps/s and RSS (from Agent_Footprint's agent_stats when
   present), stall/break state, with the existing health badge.
5. Tests, budget test for poll cost, KNOWLEDGE.md / research doc note.

## The work

### 1. Poll cadences

- `viewer/model.py` / `app.py`: snapshots at `SNAPSHOT_HZ_IDLE = 2` for unfocused agents and `SNAPSHOT_HZ_FOCUS = 10`
  for the focused one; registry rescan every 2 s as today; health every 1 s as today; world `/events` at
  `POLL_S = 0.2` for the focused agent and 1.0 s for others (constants named, untuned). The render loop reads only
  cached state; no network or shared-memory access from the UI thread.
- The worker pool runs only sources that are DUE this tick; a source whose last call has not returned is skipped,
  not queued (no pile-up when an agent is slow).

### 2. Frames on screen only

- `model.frame(agent)` is called only for cards currently visible in the grid, the focus view's agent, and the Stadium
  pane's live card; the poller reads frames only for that set (`visible_frame_set()` maintained by the views). In world
  mode with the Stadium pane hidden, no frames are read at all.
- Frame reads for visible cards run at `CARD_FRAME_HZ = 10`, the focus view at `FOCUS_FRAME_HZ = 30`, Stadium at the
  existing `FRAME_S = 0.1`.

### 3. Reader heartbeat

- Whenever a frame is read from the shared slot, write the reader timestamp into the slot header field defined by
  Agent_Footprint item 2 (coordinate the header layout in `telemetry.py`: if that directive has not landed, add the
  field here with the same name `reader_ts` and a layout version bump, and say so).

### 4. Swarm page

- A new top-level window `SWARM_PAGE` (tagged in `ui/tags.py`, persisted by the init-file layout like the Stadium pane,
  toggled from the View menu, default visible in swarm runs): one row per agent/slot with: id, state (live/lost/dead),
  current segment and grade (from `runs/segments.json` via the scorecard reader; "n/a" when absent), next job from the
  curriculum (read-only; the curriculum file the supervisor writes), steps/s and RSS (from `runs/swarm/agent_stats.jsonl`
  when present, blank otherwise), health state and reason (existing `HealthStore`), last goal landed. Click a row to
  focus the agent (existing focus command). Module `ui/swarm_page.py` under 300 lines; data assembly in
  `viewer/swarm_rows.py` (pure, under 200 lines) polled at 1 Hz on the poll thread.
- Keep the UX rules from the research doc: native window only, no charts-first layout, no extra windows beyond this
  page, dark theme tokens as the other panes.

### 5. Tests and docs

- `tests/test_viewer_poll_cadence.py`: with a fake clock, per-source due logic (idle vs focused, skipped when busy);
  `tests/test_viewer_frames_visible_only.py`: frames read only for the visible set; `tests/test_viewer_swarm_rows.py`:
  row assembly from fixture files, blanks when files are absent; `tests/test_viewer_swarm_page.py` headless
  (`dpg.create_context()` only; no viewport, no input; the hard rule: nothing may open a window on Robert's screen).
- A poll-cost budget test: with 12 fake agents, one poll tick performs at most N source calls (compute N from the
  cadences; assert it) and zero frame reads in world mode with Stadium hidden.
- `docs/KNOWLEDGE.md` viewer paragraph updated; a short addendum in the research doc's "Do not copy" / recommendations
  table noting the pull model.

## What NOT to do

- Do not change `snapshot.py`, the adapters, `control_server.py` endpoints, or what agents publish; this is viewer-side.
- Do not change the card layout, the Stadium pane behaviour, health classification, or the layout-persistence tags
  from PR #155 beyond adding the new page's tag.
- Do not add a web rewrite, charts, or new dependencies.
- Every file under `src/pokeagent/viewer/` under 300 lines (split as #155 did with mixins).
- No scratch files outside `.devin-scratch/`; never read outside the worktree; never open a viewport in tests.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run pytest -q tests/test_viewer*.py tests/test_world_view.py
```
Expected: all pass (the one ROM-gated skip in test_world_view.py:303 remains).

```
uv run pytest -q
```
Expected tail: ~1908+ passed, 40 skipped (ROM-gated), 0 failed.

```
wc -l src/pokeagent/viewer/*.py src/pokeagent/viewer/ui/*.py src/pokeagent/world/*.py
```
Expected: every file under 300.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download, fetch, or read outside
  the working directory. Never create a Dear PyGui viewport or send input.
- Branch only; commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row.

## Completion criteria

- Poll cadences per source, frames only for visible cards, reader heartbeat written, swarm page present and
  persisted in the layout, budget test green, suites green, sizes under 300.
- Status row set to Review with diff stat, test tails, the wc -l line, and the controller's real-window checklist
  (Robert opens `pokeagent world` with the swarm: fps under load, swarm page rows, frames only when focused).

## Report

Diff stat, test tails, wc -l line, constants chosen, what Robert should look at in the real window.
