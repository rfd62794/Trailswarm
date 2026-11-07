# PokeAgent: Viewer UX V1 - layout persistence, stall/break state on cards, and Stadium as a toggleable pane

**Depends on:** the Stadium opponent fix (PR branch `fix/stadium-opponent`, landing separately). Item 3 below is built on it. **Devin must STOP AND REPORT (write it in the Status row, do items 1 and 2, leave item 3 unstarted) if the opponent reader it needs is absent from your worktree:** `world/model.py::BattleCard` fields `species` / `enemy_level` / `enemy_hp` / `enemy_max_hp` must be filled with the OPPONENT's data (not our own party) by the world model, and `WorldModel.stadium(now)` must return correct cards. Check this first by reading `src/pokeagent/world/model.py` (around the `BattleCard` dataclass and `stadium()`) and `tests/test_world_view.py`; do not "fix" the opponent reader yourself.

**Read first (all in the worktree; if one is missing, stop and write that in the Status row):** `docs/research/viewer-ux-standards-2026-11-07.md` (sections 2, 6, 7; the "Do not copy" list in section 7 is BINDING: no browser/web rewrite, no Twitch chat-vote UI, no stream overlays/OBS compositing, no W&B/TensorBoard-style hosted or chart-first layouts, no piano-roll editing, no dense multi-window debug sprawl),
`docs/superpowers/specs/2026-11-05-viewer-and-hybrid-design.md` (section 4.1 the 444 fps measurement and budget, section 4.2 the steering rules), `src/pokeagent/viewer/app.py` (the `poller()` thread, `run()`), `viewer/ui/window.py` (`_populate`: the single main window, `_build`), `viewer/ui/card.py`, `viewer/ui/world_side.py` (layer toggles, the Stadium strip, tile info, event feed), `viewer/ui/world_view.py`, `viewer/ui/control_bar.py`, `viewer/ui/theme.py`, `viewer/modes.py`, `viewer/model.py`, `viewer/sources.py`, `world/model.py`, `world/stadium.py`, `snapshot.py`,
`src/pokeagent/stalls.py` (`load_dossiers`, `cluster`), `src/pokeagent/invariants/runner.py` (`run_all`, `has_errors`), `src/pokeagent/invariants/findings.py` (`Finding`), and the existing viewer tests named in 4.4. **Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

From the merged research doc (its section 7, the three cheapest ranked recommendations; this PR is exactly those three and nothing else): (1) layout persistence, (2) stall/break state on cards and a World-view badge, (3) Stadium as a toggleable pane. The job (section 1 of the doc): one person (Robert) watching 2-6 agents learn, steering occasionally, and diagnosing stalls/breaks fast. "Better" = diagnose faster (why is it stuck, since when) while staying watchable at a glance.

The biggest gap (doc section 6, "Stall/break alerts"): the diagnosis data lives OUTSIDE the viewer. `runs/stalls/*.json` (one dossier per stalled run), `runs/anomalies/*.png` + `.state` (endless_battle and others) and the invariant checker are read by no viewer panel; the only alert surface is a dimmed stopped card.

Binding hard rules for this PR: **no changes to steering** (the rules in the 2026-11-05 spec section 4.2: human input is noise, 3 s hold, keys only to the focused agent; do not touch steering.py, keys.py or commands.py (the human-hold logic lives with them; there is no viewer human_hold.py on this branch)); **keep the measured 444 fps budget** (12 cards, spec 4.1): no per-frame file reads, stalls/anomalies polled at <= 1 Hz on the EXISTING poll thread; **no web rewrite**; no new windows outside the one main viewport.

## 2. Facts (verified on the live checkout 2026-11-07; pasted because you cannot read `runs/` in the worktree)

- `uv run python --version` prints `Python 3.12.12`. Always `uv run`; never bare `python`. Full suite: `uv run pytest -q` (about 100-210 s; 1557 passed, 1 skipped on the live checkout today, plus one environment-dependent failure `tests/test_resources.py::test_lock_takeover_is_exclusive`, unrelated: ignore it and say so if it fails for you). Dear PyGui is `dearpygui>=2.0` (pyproject).
- `runs/`, `roms/`, `baselines/`, `kb/rom_tables.json` are gitignored: **no run data in your worktree.** Tests build fixture dossier/anomaly/finding data in `tmp_path`.
- **The current window structure (read from `viewer/ui/window.py`, line ~233):** ONE top-level window, `dpg.add_window(tag=self._win, no_collapse=True, no_move=True, no_resize=True, no_title_bar=True, no_scrollbar=True, ...)`, with everything else (grid area, focus area, `world_area`, `world_side`, the Stadium strip inside `world_side`) as CHILD windows/containers of it, plus `viewer_tex` (texture registry). There is no menu bar today (`control_bar.py` builds a control bar). Consequence for item 1: Dear PyGui's `init_file` stores the positions/sizes/docking of TOP-LEVEL windows; child windows are not persisted. So the persistence in this PR applies to the new **Stadium pane**, which becomes a real top-level window (item 3), and to any window you give a stable tag; the fixed main window stays fixed. The research doc's claim that every window can be persisted is therefore only partly true here: say so in your report.
- `app.py::run`: `poller()` loops `model.poll(...)`, `world.poll(...)`, `time.sleep(1.0 / fps)` at `--fps` (default 30), and re-discovers sources every ~60 ticks. This is the thread that must host the new 1 Hz refresh (tick counter, like the rediscovery one).
- Agent identity: the registry entries under `runs/agents/` look like `{"id": "explore-17696", "kind": "explorer", "pid": 17696, "port": ..., "frame_slot": ..., "token": ..., "started": ...}` - the agent id is `explore-<pid>`. The run directory is `runs/explore-YYYYMMDD-HHMMSS-<pid>/`. **The join key between an agent card and its run data is the pid suffix:** a dossier/anomaly whose `run` ends with `-<pid>` belongs to agent `explore-<pid>` (the pid can be reused across days, so also require the run's timestamp to be at or after the agent's `started` epoch minus a small slack, `JOIN_SLACK_S = 120`). Never read the token or print registry entries.
- Stall dossier `runs/stalls/<run>.json` keys: `run, t (ISO local time, e.g. "2026-11-07T15:39:51"), slot, reason, presses, map, x, y, segment, seed, starter, goal_stage, signature, signature_key, dominant, histogram, text_on_screen, sprites_near, start_state, likely_cause, decisions_tail`. Reader: `stalls.load_dossiers(root: Path) -> list[dict]` (it globs `root / "runs" / "stalls" / "*.json"`, keeps rows with a `signature`). Example: `"reason": "no new goal and only 3 new tiles in the last 600 presses"`, `"likely_cause": "pressing into a sprite: person-not-wall class"`.
- Anomalies: files `runs/anomalies/<run>-<step>-<type>.png` and `.state` (e.g. `explore-20261105-224401-19936-2940-endless_battle.png`), and rows in `runs/anomalies.jsonl`: `{"ts": "2026-11-05T22:55:20-0500", "run": ..., "step": 2940, "frame": 34368, "type": "endless_battle", "map": 59, "x": 30, "y": 7, "details": {...}, "cause_hint": ..., "decisions": [...]}`. There is NO existing reader function for the directory: add `anomalies_for(root) -> list[AnomalyRef]` in the new health module (parse the file stem: run, step, type; pair `.png` and `.state`; read `anomalies.jsonl` only for `cause_hint`, tolerant of bad lines).
- Invariants: `invariants.runner.run_all(runs_dir: Path, load_states=False, rom=None) -> list[Finding]` where `Finding(check, level in ERROR|WARN|INFO, kind, message, data)`; `has_errors(findings)`. `run_all` reads several files and can take seconds: it MUST NOT run on the render thread or inside the 30 Hz loop. Findings are global (warps, milestones, states, segments, tables), not per agent.
- `snapshot.py` (v1) publishes per agent: state/stop_reason, segment (+record), goals, thinking, driver-share counts, last 20 events, sees grid, party, money, human_hold, claude_hold_s. **Nothing for stall/anomaly health.** Rule for this PR: add the health data to what the VIEWER polls (a new `viewer/health.py` fed from the files above), NOT to what agents publish; do not change `snapshot.py` or the adapters.
- Provenance (standing rule, section 7): the health data shown by the viewer is read-only and already carries whatever provenance its source file has; do not add provenance fields to what agents publish. A dossier or anomaly from a synthetic-lineage run may be shown with a `(synthetic)` suffix in the panel line when the dossier carries `provenance`; absent means unlabelled.
- The research doc's gaps relevant here: "no layout persistence (no init_file use)"; the Stadium "strip inside World" (`world_side.py`, max `stadium.MAX_CARDS` panels, `Slot` per card with a live frame and HP bars) is a strip, not a toggleable pane.
- Existing viewer test patterns (use them, name them in your report): `tests/test_viewer_core.py`, `tests/test_viewer_fixes.py` (line ~256: `dpg = pytest.importorskip("dearpygui.dearpygui")` then `dpg.create_context()` with NO viewport), `tests/test_viewer_agents.py` (~164, also calls `dpg.setup_dearpygui()` and skips when headless), `tests/test_viewer_panels.py`, `tests/test_viewer_tiles_world.py`, `tests/test_viewer_focus_steering.py`, `tests/test_viewer_no_frame_hint.py`, `tests/test_world_view.py`, `tests/test_world_events.py`, `tests/test_world_follow.py`, `tests/test_world_legend.py`.
- **Files you must NOT modify:** `src/pokeagent/viewer/steering.py`, `src/pokeagent/viewer/ui/keys.py`, `src/pokeagent/viewer/commands.py` (steering and keys), `snapshot.py`, `adapters/*`, `src/pokeagent/viewer/web.py` (read-only page; no rewrite), `world/model.py` (the opponent reader belongs to the other PR), any explorer behaviour, `ship_gate.py`, `planner*.py`.

## 3. Scope (one PR, in order)

1. Layout persistence: stable tags on every window/pane, `init_file`, a committed read-only default layout, a "Save layout" menu item.
2. Stall/break state: `viewer/health.py` (pure classification + readers), polled at <= 1 Hz on the existing poll thread; card header colour ok / slow / stalled / anomaly; a World-view badge (anomaly + invariant counts); clicking opens the anomaly image / state path in the side panel.
3. Stadium as a toggleable pane (depends on the opponent fix; stop-and-report if absent).
4. Tests (pure functions first; Dear PyGui logic under `create_context` without a viewport).

## 4. The work

Every threshold is a NAMED constant with a comment that it is an untuned first value.

### 4.1 Layout persistence

- Stable tags: every window and pane the viewer creates gets a named tag constant in ONE place (`viewer/ui/tags.py`: `MAIN_WINDOW`, `STADIUM_PANE`, `WORLD_SIDE`, `HEALTH_PANEL`, ...). Existing tags already in use (`world_area`, `world_side`, `grid_area`, `focus_area`, `viewer_tex`) keep their strings; the main window's tag (`self._win`) is given a constant too. A test asserts the set of top-level window tags equals the documented list, so a new unlabelled window fails the suite.
- `init_file`: before the viewport is created, `dpg.configure_app(init_file=<path>, docking=True, docking_space=False)` (verify these keyword names exist in the installed Dear PyGui 2.x by reading the signature with `inspect`/`help` in a test, not by guessing; if a keyword is missing, use the supported subset and say so in your report). The path is `runs/viewer/layout.ini`.
- Read-only default: `src/pokeagent/viewer/default_layout.ini` (committed, hand-written, a single `[Window][...]` section for the Stadium pane with a sane `Pos=` and `Size=`; note in the report that the ImGui ini keys windows by their label/name, which is UNVERIFIED for Dear PyGui tags, so Robert's real-window check confirms it). On start, if `runs/viewer/layout.ini` does not exist, copy the default there (create `runs/viewer/`); NEVER write to the committed default.
- "Save layout": a viewport menu bar (`dpg.add_viewport_menu_bar`) with `View > Save layout` (calls `dpg.save_init_file(<runs/viewer/layout.ini>)` and logs one line) and `View > Reset layout` (copies the default over `runs/viewer/layout.ini`; applies on next start, say so in the menu text), plus the `View > Stadium pane` checkbox from 4.3. No keyboard shortcuts for any of these (key handling is out of scope and the steering rules stay untouched).
- Pure helper `viewer/layout_file.py`: `ensure_layout(default: Path, target: Path) -> Path` (copy-if-missing, never overwrite, never raise on a read-only target), `reset_layout(default, target)`. Tested without Dear PyGui.

### 4.2 Stall/break state on cards and a World-view badge

New `src/pokeagent/viewer/health.py` (pure except the readers; under 300 lines; split if it grows):

```python
JOIN_SLACK_S = 120            # a run belongs to an agent if it started no earlier than agent.started - this
STALL_FRESH_S = 900           # a dossier newer than this makes the card "stalled"
STALL_SLOW_S = 3600           # an older dossier (up to this) leaves the card "slow"
ANOMALY_FRESH_S = 600         # an anomaly newer than this makes the card "anomaly" (the highest priority)
HEALTH_POLL_S = 1.0           # the refresh cadence on the poll thread (<= 1 Hz)
INVARIANT_EVERY_S = 60.0      # how often a one-shot worker re-runs the invariant checker

OK, SLOW, STALLED, ANOMALY = "ok", "slow", "stalled", "anomaly"

@dataclass(frozen=True)
class AnomalyRef: run: str; step: int; type: str; png: Path | None; state: Path | None; mtime: float; cause_hint: str = ""
@dataclass(frozen=True)
class Health: state: str; reason: str; anomaly: AnomalyRef | None = None; dossier_run: str | None = None

def run_pid(run: str) -> str | None                      # "explore-20261107-153827-24324" -> "24324"
def anomalies_for(root: Path) -> list[AnomalyRef]        # lists runs/anomalies/*.png|*.state, pairs them, newest first; tolerant of junk file names and a missing dir
def classify(agent_id: str, started: float | None, dossiers: list[dict], anomalies: list[AnomalyRef], now: float) -> Health
def break_summary(findings: list[Finding]) -> dict       # {"errors": n, "warns": n, "top": [first 3 ERROR messages]}
class HealthStore:                                       # holds the last snapshot of everything above; thread-safe get/set
    def refresh(self, root: Path, now: float) -> None    # cheap: stat() the stalls dir and anomalies dir mtimes first, re-read only what changed
    def health(self, agent_id: str, started: float | None) -> Health
    def breaks(self) -> dict
    def request_invariants(self, root: Path, now: float) -> None   # starts ONE daemon worker thread running run_all when INVARIANT_EVERY_S has passed and none is running; a failure stores {"unavailable": message}
```

- `classify` priority: **anomaly** (an `AnomalyRef` whose run joins this agent via `run_pid` + `JOIN_SLACK_S` and is newer than `ANOMALY_FRESH_S`) > **stalled** (a dossier for a joined run with `t` within `STALL_FRESH_S`; `reason` = the dossier `likely_cause` plus its `reason`, shortened to 120 chars) > **slow** (a joined dossier older than `STALL_FRESH_S` and within `STALL_SLOW_S`) > **ok**. Dossier `t` is local ISO time without zone; parse it as local time. An agent with no joined data is `ok` with reason "".
- Poll wiring (`app.py::poller`): a tick counter; every `fps * HEALTH_POLL_S` ticks call `store.refresh(root, time.time())` and `store.request_invariants(root, time.time())`. NO file read anywhere in the render path: the card and side panel read `store.health(...)` / `store.breaks()` (dict lookups). `refresh` stats directory mtimes first so a quiet second costs two `stat` calls. The invariant worker is a separate short-lived daemon thread (one at a time) so a slow `run_all` never delays `model.poll`. `--fake N` agents get a deterministic fake health (one stalled, one anomaly) so the colours can be seen without runs; keep it behind the existing fake path.
- Card header colour: in `viewer/ui/card.py` / `theme.py` add a mapping `HEADER_COLOUR = {ok: <current header colour>, slow: amber, stalled: red, anomaly: magenta}` and apply it with the existing header-tint mechanism (the code already tints the header for the selected card: read `set_selected` and the theme setup and reuse it; a state change re-themes only when the value changes - memoise by state, like the card's other `_memo` keys). The "dimmed stopped card" behaviour is unchanged. The card also shows the one-line `reason` as a tooltip on the header (no per-frame text rebuild: only on state change).
- World-view badge: a small text/badge in the World view side panel header, e.g. `Health: 1 stalled, 1 anomaly | invariants: 0 errors` coloured by the worst state; `invariants: unavailable` when the worker failed; `invariants: checking...` before the first result. Click on the badge expands the `HEALTH_PANEL` section of the side panel: one line per non-ok agent (`agent: state - reason`), the invariant top-3 ERROR messages, and one line per recent anomaly.
- Click an anomaly line (or the card header of an anomaly card): opens it in the SIDE PANEL, no external window and no OS shell call: the `.png` is loaded once on click via `dpg.load_image` into the existing `viewer_tex` texture registry and shown in a fixed-size image slot in the panel (a cached texture keyed by path; the previous one is deleted), and the `.state` path and `cause_hint` are shown as selectable text under it. A missing file shows "file missing" instead of raising.

### 4.3 Stadium as a toggleable pane (built on the opponent fix)

- Turn today's Stadium strip (inside `world_side.py`) into a pane that is a real top-level window with tag `STADIUM_PANE` (movable and resizable, so `init_file` can persist it), shown/hidden by `View > Stadium pane` (a menu checkbox; default: shown in World mode, hidden in Tiles mode as today's strip behaves; the choice is remembered for the run only, not persisted beyond the layout file). The pane contains the same `Slot` widgets (live frame + `stadium.lines(card)` + HP bars) fed by `WorldModel.stadium(now)`, max `stadium.MAX_CARDS`, with the same "Stadium - N in battle" title text; `world_side.py` keeps the layer toggles, tile info and event feed, and loses only the strip.
- Stadium is no longer a mode: nothing about `modes.py` changes except that no code path assumes the strip lives in the side panel (`modes.status_text` unchanged).
- Click on a Stadium slot still focuses that agent (`on_focus`), exactly as today. The opponent data shown (`species`, `enemy_level`, enemy HP) comes ONLY from `BattleCard` as filled by the world model (the other PR); this PR adds no reader of its own for the opponent.
- If the opponent reader is absent in your worktree (see the Depends line): do items 1 and 2, do NOT start item 3, write in the Status row exactly what was missing, and move the Status row to Review with items 1-2 done.

### 4.4 Tests (no GUI windows, no OS input)

Hard rules: no viewport, no `dpg.show_viewport`, no `setup_dearpygui` where avoidable, no `SendInput`/key simulation, no screen capture. Dear PyGui logic is tested under `dpg.create_context()` without a viewport (the pattern of `tests/test_viewer_fixes.py` line ~256; wrap in `pytest.importorskip("dearpygui.dearpygui")`, and `dpg.destroy_context()` in a `finally`); anything that needs `setup_dearpygui` follows `tests/test_viewer_agents.py` (skip when headless).

`tests/test_viewer_health.py` (pure, no Dear PyGui): `run_pid`; `anomalies_for` on a `tmp_path` dir with paired and unpaired `.png`/`.state`, junk names, a missing dir; `classify` for every state and the priority order (anomaly beats stalled beats slow beats ok), the pid join with `JOIN_SLACK_S` (a same-pid run from the previous day does NOT join), dossier time parsing (local ISO), freshness boundaries at exactly `STALL_FRESH_S` / `STALL_SLOW_S` / `ANOMALY_FRESH_S`; `break_summary`; `HealthStore.refresh` re-reads only on a changed mtime (count `open` calls via monkeypatch), never raises on a corrupt dossier; `request_invariants` starts at most one worker and stores `{"unavailable": ...}` when `run_all` raises (monkeypatch `run_all`); a test that `HealthStore.health`/`breaks` perform NO file I/O (monkeypatch `Path.open`/`read_text`/`glob`/`stat` to raise and call them).
`tests/test_viewer_layout_file.py`: `ensure_layout` copies when missing, never overwrites, survives a read-only target; `reset_layout`; the committed `default_layout.ini` exists and parses as `[Window][...]` sections with `Pos=` and `Size=`; the tag-constants test (documented top-level window tags equal the set built by a fake populate).
`tests/test_viewer_health_ui.py` (Dear PyGui under `create_context`, no viewport): applying a card header theme for each state memoises (the theme is created once per state), the badge text formats for `0 stalled`, `1 stalled, 1 anomaly`, `unavailable`, `checking...`; clicking an anomaly line loads the texture once (monkeypatch `dpg.load_image` with a fake returning a small RGBA buffer), deletes the previous one, shows "file missing" for a missing path; the poller wiring calls `refresh` once per `fps * HEALTH_POLL_S` ticks (a fake clock/tick loop, not a thread).
`tests/test_viewer_stadium_pane.py` (needs the opponent fix): the pane exists as a top-level window with tag `STADIUM_PANE`, toggles shown/hidden through the menu callback, slot count and title text follow `WorldModel.stadium` (use the existing fixtures in `tests/test_world_view.py`), `world_side` no longer builds the strip, focusing from a slot still works, `modes.status_text` unchanged.
Existing tests stay green unedited except where a moved widget forces an update (list each one in your report). The steering tests (`tests/test_viewer_focus_steering.py`) are NOT edited.

## 5. What NOT to do

- No change to steering, keys, human hold or commands (the 3 s hold, noise rule, focused-only keys all stay). No new keyboard shortcuts. No web rewrite and no change to `web.py`. No per-frame file reads; nothing added to the 30 Hz path except dict lookups. No new top-level windows other than the Stadium pane. No external windows or OS shell calls to open images or paths.
- Do not change `snapshot.py`, `adapters/*`, `world/model.py` (the opponent reader is the other PR's), or any agent/explorer code; do not add health to what agents publish. Do not run the viewer, create a viewport, or send any input on the laptop: tests only. No emulator runs and no entry-point invocation of any kind.
- Not in this PR (ranked 4-7 in the research doc): the delta-vs-record strip, the keyboard pass, the filterable decision log, replay/scrub. No chart-first layouts, no hosted dashboards, no stream overlays.
- No new dependencies; each module under 300 lines; no changes to `runs/` contents (read-only; the only file the viewer writes is `runs/viewer/layout.ini` via the menu).

## 6. Verification

- `uv run pytest -q tests/test_viewer_health.py tests/test_viewer_layout_file.py tests/test_viewer_health_ui.py tests/test_viewer_stadium_pane.py` - new tests pass (paste the tail; a Dear PyGui test may be skipped headless: say which).
- `uv run pytest -q tests/test_viewer_core.py tests/test_viewer_fixes.py tests/test_viewer_agents.py tests/test_viewer_panels.py tests/test_viewer_tiles_world.py tests/test_viewer_focus_steering.py tests/test_viewer_no_frame_hint.py tests/test_world_view.py tests/test_world_events.py tests/test_world_follow.py tests/test_world_legend.py` - the neighbouring viewer tests stay green.
- `uv run pytest -q` green; paste the before/after tails and `git diff --stat main`; confirm no forbidden file changed (steering, keys, snapshot, adapters, web, world/model).
- **Controller validation:** Robert's real-window check (section 9). The controller does not drive the window; it reads the result.

## 7. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation is rejected and ends the run. No installs, downloads or fetches.
  Never read outside the worktree.
- **Do not run the `pokeagent` entry point (the sandbox refuses it). Do not list the directory tree recursively; use `git ls-files`.
  Do not read outside the worktree. Create no scratch files; deleting is denied. If something expected is missing, stop and write that in the Status row.**
- Do not search, glob or hunt for a missing file or fact: stop and say so in the Status row.
- Test commands are exactly `uv run pytest -q` and `uv run pytest -q tests/<file>`. Never bare `python`.
- Work only on branch `directive/pokeagent-viewer-ux-v1-directive`. Never commit to `main`; never push; never deploy; no `git stash`. Commit on the branch as you go.
- Create no scratch or debug files (deleting is denied and ends the run). If one is truly needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row; do not try another way around it.
- SOLID/SRP/KISS is a hard rule here: small new modules (under 300 lines), no new dependencies.
- **Standing rule (Robert, 2026-11-07, verbatim): "We can use synthetic data and states and saves throughout, with a standing rule that a synthetic result must be verified by organic data and states and saves, as a proof system."** Every learned record this work writes carries `"provenance": "organic" | "synthetic" | "unknown"`, taken from the start state's lineage (`statefp` lineage, PR #147: if it is not merged or a state has no lineage record the value is `"unknown"`, never guessed, and `unknown` is treated like organic for display and like synthetic for promotion: it can never be promoted by itself). Synthetic-born records are HYPOTHESES: usable for drills, A/B and planning, NEVER a chain best, a confirmed segment, a shared-memory veto or a KNOWLEDGE fact until an organic run reproduces them, at which point they are promoted (same semantics as state promotion). Tests use fixture lineage values only.

## 8. Completion criteria

- [ ] Stable window tags in `viewer/ui/tags.py`; `init_file` configured; committed read-only `default_layout.ini` copied to `runs/viewer/layout.ini` when missing; `View > Save layout` / `Reset layout` menu items
- [ ] `viewer/health.py` (classify, anomalies_for, break_summary, HealthStore) polled at <= 1 Hz on the existing poll thread with the invariant worker off-thread; card header colours ok / slow / stalled / anomaly; World-view badge and health section; anomaly click shows the image and the state path in the side panel
- [ ] Stadium pane: top-level `STADIUM_PANE` window toggled from the menu, strip removed from `world_side`, built on the opponent fix (or: item 3 not started and the Status row says what was missing)
- [ ] The four new test files pass; neighbouring viewer tests green; `uv run pytest -q` green (tail pasted); `git diff --stat main` pasted; no forbidden file changed
- [ ] Status row moved to Review with the branch name

## 9. Report

Findings first: test tails (before/after), `git diff --stat`, the final signatures and every named constant, the tag list, which `configure_app` keywords the installed Dear PyGui supports, how the card header colour is applied, where the 1 Hz refresh sits in `poller()`, the join rule you used for agent to run, and whether item 3 was done or stopped.

**Robert's real-window check (5 items; not run by Devin: the controller asks Robert to start the viewer himself and report pass/fail per line):**
1. Start the viewer with at least 3 agents (or `--fake 6`): the window opens at the usual size, cards render, and frame rate feels unchanged (no stutter while the health refresh runs; the old 444 fps figure is the reference).
2. A stalled agent (or the `--fake` stalled one) shows a RED card header with the likely cause on hover, an anomaly agent shows a MAGENTA header, and a healthy one keeps the normal header; the World view badge matches the counts.
3. Click an anomaly line or card: the anomaly image and the `.state` path appear in the side panel, no other window opens, and clicking a missing file shows "file missing" without an error.
4. `View > Stadium pane` toggles the Stadium window on and off; with an agent in battle it shows the OPPONENT (species, level, HP) correctly; drag and resize the pane, choose `View > Save layout`, close and restart: the pane returns where you left it. `View > Reset layout` plus a restart returns it to the default place.
5. Steering is unchanged: keys go only to the focused agent, a human press holds the agent for 3 s with "YOU HAVE IT", and none of the new menu items react to keystrokes.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Approved |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-07 15:45 · robert-claude-laptop · none → Draft — Claude 2026-11-07: viewer layout persistence, stall/break state, Stadium pane (depends on fix/stadium-opponent)
- 2026-11-07 15:46 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; depends on fix/stadium-opponent; lint_override: dispatch-path-missing on greenfield test file and gitignored runs/kb paths
- 2026-11-07 16:24 · robert-claude-laptop · Queued → Draft — Claude: reword entry-point mentions (preflight), add provenance rule
- 2026-11-07 16:25 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; entry-point mentions reworded; provenance rule; lint_override: dispatch-path-missing greenfield/gitignored
- 2026-11-07 16:27 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing / verification-path-missing on gitignored kb/rom_tables.json, runs/anomalies.jsonl and the new tests/test_viewer_stadium_pane.py; known false positives. Entry-point mentions reworded. Dependency fix/stadium-opponent merged as PR #149.
<!-- queue:end -->
