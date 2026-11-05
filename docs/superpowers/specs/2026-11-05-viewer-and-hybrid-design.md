# PokeAgent: one native viewer, and Explorer + RL learning together

Written 2026-11-05 with Robert (brainstorm in the Claude CLI). Supersedes the "GUI" section of
`docs/ROADMAP.md` and the scope of `docs/directives/Viewer_And_Human_Steering_Directive.md` (Draft).
Base: `origin/repoman/rl-success-and-context` @ `bd2aef8` (the RL work; see "Prerequisite" below).

## 1. Why

Two problems, one design.

1. **Watching is scattered.** Four viewers grew up one per approach: `tools/explore_demo.py` (tk, four
   panes, one agent), `tools/agent_window.py` (one tk window per agent), `tools/watch.py` (tk tile grid of
   the swarm), `tools/webview.py` (browser). Robert does not know which to open, and none shows everything
   he wants. He has "different ideas at different times", so the viewer must be one tool whose parts are
   small, swappable modules (SOLID/SRP/KISS is a hard rule in this portfolio).
2. **The learner got worse.** The rule-based Explorer (Nov 2-3) reached the potion, the house exit, the
   starter, the rival win, Route 1, Viridian and Oak's Parcel inside a day. It needed a hand-written guard
   for every stall (sign loops, ledge cycles, endless A). The project then moved to tabular Q-learning on
   low-level buttons (ladders, curricula, gauntlets); two days later RL is re-learning things the Explorer
   already did, and Robert says "the hard-coded button press method worked better than RL somehow".
   The research (below) says every agent that went far in Pokemon is a hybrid: deterministic navigation
   underneath, a decider on top. The goal is to make the Explorer the backbone and let RL learn where the
   Explorer is weak, so stalls become data instead of patches.

## 2. What Robert decided (his words in quotes)

- "A SINGLE ... window, holding the subviews and controls." Native desktop, **not browser-based**.
  "It can be a single native desktop window, faster is better." Willing to "build custom modules ... or
  replace any dependency".
- **All agents visible at once**, each with the full per-agent detail: "I want to see their render, as
  well as what they see and are thinking and steps/goals."
- **Double-click a card** enlarges that agent full-window and hides the others, "provided there's controls
  to get back to multiview".
- Explorer and RL should **learn together** (he asked "is there a way"; the shape in section 5 is the
  research-backed answer he approved with "proceed in full").
- Build with Devin as well (model `swe-2-flash-max`, "SWE 2 Fast Max").

## 3. Goals, non-goals, anti-goals

Goals
- One window, `uv run pokeagent view`, that finds every running agent and shows each as a card with
  Render, Sees, Thinking, Steps & Goals; a focus view; a control bar; keyboard steering.
- The viewer never slows an agent. Agents run at full speed whether 0, 1 or 2 viewers are attached.
- A shared agent snapshot contract so any agent kind (Explorer, RL, hybrid, swarm worker) shows up the
  same way, including **who made each decision** (Explorer / RL / human / Claude).
- The Explorer becomes the base policy of a hybrid agent: a generic stuck-watchdog replaces the bespoke
  guards; RL chooses among Explorer behaviours; a Go-Explore archive drives where the swarm explores.
- Measurable: every phase ends with numbers from `tools/status.py` / `review_runs.py` against the Explorer
  records in `docs/SEGMENTS.md` (S1 14, S2 24, S3 74, S4 89, S5 92).

Non-goals
- A web viewer, remote viewing, streaming/recording overlays (later, if ever; the snapshot contract
  makes them possible without designing for them now).
- Neural networks / GPU training. Tabular and counting methods only in this design.
- Rewriting the emulator, RAM, perception or MCP layers.

Anti-goals (would be a failure even if it "works")
- A dashboard that looks pretty but where Robert still cannot tell *why* an agent did something.
- A viewer whose frame rate or a blocked socket stalls emulation.
- A new god-file. No module over 600 lines (the repo ratchet), one job per module, layers import downward.
- Re-learning by RL what the Explorer already does reliably (navigation, menus, scripted beats).
- Losing what the RL branch built: tables, options, BFS navigation, evaluation gates stay usable.

## 4. The viewer

### 4.1 Toolkit (decided by measurement)

Spike 2026-11-05, 12 cards each a 160x144 frame at 2x plus 8 lines of text, all updated every frame:
tkinter 68 fps, **Dear PyGui 444 fps** (GPU textures, `add_raw_texture` + `set_value`). Robert: faster is
better. **Dear PyGui** (MIT, pip wheel for Windows/3.12) is the toolkit. It is the only new runtime
dependency. All Dear PyGui calls live in `viewer/ui/` so a later swap (imgui-bundle, Qt) touches one
package.

### 4.2 Layout (Robert's choices; mockup `layout-v4` in `.superpowers/brainstorm/`)

- **Multi-view (default):** a grid of agent cards that reflows for 1-12 agents (columns = ceil(sqrt(n)),
  wide aspect). Header strip: agent count, best record per current segment, swarm-wide driver split.
- **Card:** header `id · segment · step`; Render (live frame, nearest-neighbour upscale) beside Sees
  (tile map as text; battle view when in battle); Thinking (want, plan or blocker, driver + rule, button,
  result; a thin driver-share bar for the last 100 presses); Steps & Goals (segment strip S1..Sn done /
  current / ahead, `seg N / rec M`). Stopped agents dim and show why they stopped, with restart / remove.
- **Focus view:** double-click a card -> that agent fills the window with larger panels (bigger render,
  full Sees with sees|remembers toggle, a scrolling decision log, party/bag/money, goal list with presses
  per goal). Back to multi-view: an always-visible **"◀ All agents"** button, **Esc**, or double-click.
- **Control bar (bottom, always):** target selector (selected card or All), Pause/Resume, speed 1x/2x/4x/8x,
  Steer (keyboard goes to the selected agent), Hand to RL / Hand to Explorer, Save state, Load state…,
  Spawn agent…, Stop. Keys follow the existing demo: arrows, `a`=A, `s`=B, Enter=START, Shift=SELECT,
  `p` pause, `t` turbo cycle. Keys only reach an agent when Steer is on for it (no accidental presses).
- Colours: Explorer green, RL orange, human pink, Claude blue, consistently in cards, bars and logs.
  Dark theme.

### 4.3 Architecture (observer pattern; one job per module)

```
agent process (any kind)                         viewer process (pokeagent view)
  AgentStatusBuilder -> snapshot dict  --HTTP GET /snapshot (5-10 Hz)-->  sources/http_source
  FramePublisher (telemetry.py, shm)   --shared memory seqlock (30 Hz)--> sources/frame_source
  command handler      <--HTTP POST /command {"cmd":..}--                  commands.py
supervisor (pokeagent supervise / inside view) owns spawn/stop/restart; writes the agent registry
runs/agents/<id>.json  {id, kind, pid, port, frame_slot, started}   <- discovery for the viewer
```

- **Snapshot contract v1** (`src/pokeagent/snapshot.py`, layer 2-3 boundary, stdlib dataclasses +
  `to_dict`/`from_dict`, schema version field). Fields: `v, agent_id, kind, state
  (running|paused|stopped|done), stop_reason, step, segment {id,name,steps,record}, goals [{id,name,
  status done|current|ahead, steps}], thinking {want, plan, blocker, driver explorer|rl|human|claude,
  rule, button, result, confidence}, drivers {explorer,rl,human,claude} (counts over last 100 presses),
  recent [{step, driver, text}] (last 20), sees {rows: [str], mode overworld|battle|menu, legend},
  screen {box_text, in_battle, party [{species, level, hp, max_hp}], money, bag_summary}, frame_slot,
  updated_at`. Unknown fields are ignored; missing fields render as "—".
- **Commands v1** (`POST /command`, JSON `{"cmd": name, ...}` -> `{"ok": bool, "error"?: str}`):
  `pause, resume, speed{n}, press{button}, steer{on}, hand_to{driver}, save_state{name},
  load_state{name}`. Supervisor commands: `spawn{kind, args}, stop{id}, restart{id}, remove{id}`.
- **Agent side:** one small module per job: `snapshot.py` (contract), `status_builder.py` (fills a
  snapshot from RAM/memory/policy state; each agent kind supplies a thin adapter), `control_server.py`
  (stdlib `http.server` on a thread: GET /snapshot, POST /command; replaces the ad-hoc control APIs in
  explore_demo and rl_train), registry write/remove in `agent_registry.py`.
- **Viewer side (`src/pokeagent/viewer/`, layer 4):** `sources/` (AgentSource protocol: `snapshot()`,
  `frame()`, `send(cmd)`; HTTP + shm implementation; a fake source for tests), `model.py` (latest snapshot
  per agent, staleness), `layout.py` (grid maths, focus state; pure, testable), `panels/` (render, sees,
  thinking, progress, focus extras; a registry so a new panel is one file), `controls.py` (bar + key
  routing -> commands), `ui/` (all Dear PyGui code), `app.py` (wiring + main loop, small).
- UI loop at 30 Hz; snapshot polling and frame reads on a background thread; the UI only ever reads the
  latest value (drop stale). A dead agent shows "stale Ns" then "lost", never blocks.

### 4.4 Retirement

When the new viewer covers an old one, the old one goes (git history keeps it): `tools/watch.py`,
`tools/agent_window.py`, `tools/webview.py`, and the tk window inside `tools/explore_demo.py` (the demo
runs headless + publishes snapshots and frames). `tools/trace_view.py` and `tools/qview.py` stay (offline
tools). Retirement is its own directive after Robert has used the new viewer.

## 5. Explorer + RL learning together

Research summary (2026-11-05; Sonnet research agents, one source re-checked by Claude): Whidden et al.
"Pokemon Red via Reinforcement Learning" (arXiv 2502.19920) - pure PPO with heavy shaping reaches Cerulean
and agents exploit shaped rewards; the NeurIPS 2025 PokeAgent Challenge paper (arXiv 2603.15563) - hybrids
scale better than pure RL on long RPGs; Claude/Gemini Plays Pokemon - a navigation tool plus a high-level
decider; Go-Explore (Ecoffet et al., Nature 2021) - archive of cells, return via save state, then explore;
options framework (Sutton/Precup/Singh 1999); shielding / action masking; learning from demonstrations
(DQfD). Shipped game AI: behaviour-tree backbone, scripted stuck watchdogs, learned parts in narrow slots.

The shape, in build order (each step must leave the demo and the viewer better):

1. **Explorer as behaviours.** Extract the Explorer policy from `tools/explore_demo.py` (1,562 lines) into
   `src/pokeagent/explorer/` as named behaviours, each with an explicit start condition, termination and
   failure: `advance_dialog, menu, battle, goto, replay_beat, plan_goal, frontier, catch, heal`. The
   selector order stays the demo's. This updates the Draft `Explorer_Policy_Module_Directive.md`. Parity
   check: the extracted Explorer reaches S1-S5 from `baselines/bedroom.state` within 25% of the demo's
   recorded steps.
2. **One stuck-watchdog.** A generic watchdog (no new tile, map, text or RAM event for N presses on <=K
   tiles) replaces the bespoke loop guards: it masks the looping behaviour/action and forces the next one
   (shielding), and logs `{signature, location, behaviour, recovery, resumed}` to
   `runs/stalls.jsonl`. The old guards are removed only when the watchdog matches them on the parity run.
3. **RL picks behaviours, not buttons.** A tabular Q selector over a small state (map id, coarse x/y bucket,
   goal stage, box/battle flag, last stall signature) and the Explorer behaviours as actions (options
   framework; reuses `options.py`). The Explorer's own choice is the default and the Q table is **seeded
   from Explorer runs** (do what the Explorer did, with a prior bonus). RL takes over a decision only where
   it has measured better (fewer presses to the next goal, no stall); otherwise the Explorer rule stands.
   Every decision is attributed (`driver`, `rule`, `confidence`) for the viewer.
4. **Stall recovery is learned.** From `runs/stalls.jsonl`, a small bandit per stall signature picks the
   recovery (behaviour, direction, random-walk shake); the watchdog uses it. This is what turns "write a
   guard" into learning.
5. **Go-Explore archive.** Cells = (map id, x//4, y//4, badges, key items). Each cell keeps a save state,
   best steps to reach it and visit count. Swarm workers pick a cell weighted toward rarely visited and
   frontier cells, load its state, run the hybrid agent for a budget, and add new cells. Replaces
   `--segment`-only reruns as the swarm's default mode; segment records stay.
6. **Sparse rewards only:** goal milestones and new cells. No dense shaping (the paper shows exploitation).

The low-level RL ladder (`tools/rl_*`, `rl_env.py`) is kept and not extended; skills it trained remain
callable as options where they beat the Explorer behaviour (e.g. menus), decided by measurement.

## 6. Constraints

- uv + Python 3.12; commands via `uv run`. Dear PyGui is the only new dependency.
- Layers import downward only (`docs/ROADMAP.md`); viewer is layer 4, supervisor and archive layer 5.
- No file over 600 lines; new code in small modules with tests (pytest; UI logic tested through pure
  modules and the fake source; Dear PyGui code kept thin).
- ROM and save states are gitignored; never committed. RAM addresses verified against the ROM before use
  (`docs/KNOWLEDGE.md`).
- Devin directives must say: do not list the tree recursively; do not run `uv run pokeagent ...` smoke
  checks in the sandbox (the entry point is refused) - use `uv run python -m pytest` and module imports.
- Commits from Claude go through a scratchpad worktree (the live checkout blocks `git commit`). Merge commit,
  not squash; independent review + green tests before any merge.

## 7. Prerequisite

`origin/repoman/rl-success-and-context` (71 commits, +4.3k lines) is not on `main`. Devin worktrees start
from `main`, and this design builds on that branch's `options.py`, `navigation.py`, `qmodels.py`,
`telemetry.py`. It is reviewed and merged to `main` first (gates: independent review, green suite).

## 8. Left to the builder

Exact Dear PyGui widget structure and theming; grid sizing details; the polling thread design; how each
agent kind's adapter fills the snapshot; the watchdog's N and K (start from the demo's guards: 60 presses
on <=6 tiles, 40 A presses on one tile); Q state bucketing details; cell weighting formula.

## 9. Calls Claude made (Robert may override)

- Dear PyGui over imgui-bundle and Qt (measured, simplest texture API; swap contained in `viewer/ui/`).
- HTTP per agent for snapshots/commands + existing shared memory for frames (no ZeroMQ dependency).
- A registry directory `runs/agents/` for discovery instead of port scanning.
- Focus view adds a scrolling log and party/bag panel; multi-view cards omit them to stay legible.
- Steering requires Steer on for the target (prevents stray keypresses into the wrong agent).
- Old viewers retired in a separate directive after Robert has used the new one.
- Build order: viewer track and Explorer extraction in parallel (independent files); watchdog, RL
  selector, recovery bandit and archive in sequence after the extraction.
