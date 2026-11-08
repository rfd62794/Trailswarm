# PokeAgent viewer UI/UX: standards, use cases, similar cases (2026-11-07)

## 1. Scope and the job
Unify and revamp the Dear PyGui viewer (World, Tiles, Stadium, plus the old tk `tools/explore_demo.py`). The user is one person (Robert) watching 2-6 agents learn, steering occasionally, and diagnosing stalls/breaks fast. "Better" = diagnose faster (why is it stuck, since when) while staying watchable at a glance.

## 2. What we do today (paths under C:\Github\PokeAgent)
- `src/pokeagent/viewer/app.py`: poll thread, 10 Hz snapshots / 30 Hz frames, `--fake N`, `--web` read-only page (`web.py`). Dear PyGui measured 444 fps for 12 cards vs tk 68 (spec 2026-11-05 section 4.1).
- Modes (`modes.py`): World (default; all agents on one Kanto map, `ui/world_view.py`; side panel `ui/world_side.py` = layer toggles, Stadium strip max 8 battle panels, tile info, event feed) and Tiles (`ui/grid_view.py`, `card.py`: render / sees / thinking / steps+goals). Focus view on double-click, Esc or "All agents" back (`focus_view.py`, `keys.py`). Stadium is a strip inside World, currently buggy.
- Card cap 8 (6..12) with paging, focused agent pinned (`view_cap.py`). Status line "Mode | Agents | Selected | Follow" (`modes.status_text`).
- Steering: arrows/a/s/Enter, `p` pause, `t` speed; keys only to the focused agent, 120 ms throttle (`steering.py`); human press = human hold, 3 s auto-pause, "YOU HAVE IT" (spec 4.2; `human_hold.py`). Control API `/status /goals /screen /vision /sprites /peek /map`, POST `/press /pause /resume /goto /say`.
- Published per agent (`snapshot.py` v1): state/stop_reason, segment (+record), goals (done/current/ahead), thinking (want/plan/blocker/driver/rule/button/result/confidence), driver-share counts, last 20 events, sees grid, party (species/level/hp/DVs), money, human_hold, claude_hold_s.
- Diagnosis data lives OUTSIDE the viewer: `runs/stalls/*.json`, `runs/anomalies/*.png+.state` (endless_battle etc.), `src/pokeagent/invariants/`, `novelty/discoveries`, `tools/segments.py` (attempts, rate, best, expected, share). No viewer panel reads them.
- Gaps seen in code (grep): no replay/scrub in the viewer; no layout persistence (no init_file use); no alert surface beyond a dimmed stopped card.

## 3. Industry standard (observability / debug UIs)
1. Dear PyGui init files: window positions and docking persist between sessions if windows have stable string tags; `save_init_file`, `configure_app(init_file=)`. https://dearpygui.readthedocs.io/en/latest/documentation/init-files.html (current docs); https://github.com/hoffstadt/DearPyGui/discussions/1088 (load_init_file = read-only default; set_init_file = persist).
2. Grafana stat panels: one big value coloured by thresholds, base colour = "good"; dynamic status is computed in the query and mapped to colour. https://docs.aws.amazon.com/grafana/latest/userguide/thresholds.html (v9-era docs). Lesson: glanceable state colour, not text.
3. OBS Studio: dockable, pop-out panels with a Lock UI toggle; Multiview shows 8 scenes with click-to-select (layout options added 2018). Source: OBS commit mirror https://git.tjdev.de/mirror/obs-studio (weak; official docs not retrieved).
4. PyBoy `--debug`: separate sprite/tile/game-area windows, `L` cycles views. https://docs.pyboy.dk/plugins/index (current). Debug panes are opt-in, never the default.
5. Dear ImGui docking: layout lives in an .ini the toolkit writes automatically (secondary guide: https://instagit.com/ocornut/imgui/dear-imgui-docking-system.md).

## 4. Common use cases (experiment / emulator tooling)
1. W&B workspaces: saved views are shared snapshots of panel layout; Run Comparer shows only config/metric differences across runs; up to 20 pinned runs. https://docs.coreweave.com/products/wandb/track/workspaces.md and .../runs/compare-runs.md (hosted copy of W&B docs; undated).
2. TensorBoard-style viewers: regex tag filter, multi-run overlay, EMA smoothing (a third-party clone documents the pattern: https://pypi.org/project/tb-like/). Official TensorBoard docs not retrieved; pattern, not citation.
3. BGB: debugger windows opened from a Window menu; any breakpoint puts it in a slower mode (the cost of debugging is explicit). https://bgb.bircd.org/manual.html (v1.6.6).
4. mGBA 0.6.0 (2017-07-16): sprite viewer, memory viewer, memory search, execution tracing as separate on-demand tools. https://mgba.io/2017/07/16/mgba-0.6.0/
5. BizHawk: RAM Watch, RAM Search, Input Display, TAStudio piano roll as separate tools. https://tasvideos.org/BizHawk/PreviousReleaseHistory (secondary; official wiki not retrieved).

## 5. Similar use cases (watching agents play)
1. Claude Plays Pokemon (Twitch, Feb 2025): reasoning on the left, live gameplay on the right. https://techcrunch.com/2025/02/25/anthropics-claude-ai-is-playing-pokemon-on-twitch-slowly/ (2025-02-25). Party/goal panels NOT confirmed by any source found.
2. Gemini Plays Pokemon: a minimap above the game that fills in like fog-of-war as it explores. https://rentry.org/gpp-about-20250612 (archived 2025-06-12).
3. Peter Whidden's PokemonRedExperiments: a broadcast wrapper streams many training sessions onto ONE shared global map in a separate viewer (pokerl-map-viz). https://github.com/PWhiddy/PokemonRedExperiments (undated). Closest cousin of our World view.
4. LiveSplit: Delta against a chosen comparison (PB / best segments), Possible Time Save, Sum of Best, Graph; layout edited by right-click. https://livesplit.org/components/ (undated). Maps onto our segment table (record vs current).
5. Twitch Plays Pokemon: on-screen input display with a bar chart of leading inputs and who voted. https://bulbapedia.bulbagarden.net/wiki/Twitch_Plays_Pokemon (community wiki). Pattern: show recent inputs by source (we already colour by driver).

## 6. Comparison table
Mark: M = matches, G = gap, D = deliberate difference.

| Row | Ours | Standard | Common | Similar | Mark |
|---|---|---|---|---|---|
| Multi-agent overview | World map + Tiles grid, 8-card cap | OBS multiview (8) | W&B run list/pins | Whidden shared map | M |
| Single-agent focus | Double-click focus, Esc back | PyBoy per-view windows | W&B run page | CPP single stream | M |
| Map + position | World map, trails, Sees text | - | - | Gemini minimap, Whidden map | M |
| Party/HP/levels | In snapshot; cards unclear | Grafana stat tiles | - | unconfirmed on CPP | G (verify on card) |
| Current goal + plan | Thinking want/plan, goal strip | - | - | LiveSplit split list | M |
| Decision/thought log | Last 20 events, driver colours | - | tb text/filter | CPP left-side reasoning | M |
| Battle view | Stadium strip, buggy | - | - | - | G (fix first) |
| Stall/break alerts | None in viewer; data in runs/stalls, anomalies, invariants | Grafana threshold colours | - | - | G (biggest) |
| Timeline / replay | None | BizHawk TAStudio, mGBA trace | TensorBoard step axis | LiveSplit Graph | G |
| Human steering + noise rule | Focused-only keys, 3 s hold, half weight | OBS Lock UI (idea) | - | TPP input display | M / D (noise rule is ours) |
| Performance (6 cards) | 444 fps at 12 cards measured | BGB debug slows emulation | - | - | M |
| Keyboard-first | arrows, p, t, Tab, Esc; no jump-to-agent/panel keys | ImGui conventions | - | - | partial G |
| Layout persistence | None | DPG/ImGui init file | W&B saved views | LiveSplit layouts | G (cheapest) |
| Delta vs record | segments.py CLI only | - | W&B comparer | LiveSplit Delta | G |

## 7. Ranked recommendations (cheapest first)
1. Layout persistence: stable tags on every window + `init_file`, read-only default plus a "Save layout" item (row: layout persistence).
2. Stall/break state on cards and a World-view badge: colour the card header by state (ok / slow / stalled / anomaly), fed from `runs/stalls`, `runs/anomalies`, invariant findings; click opens the anomaly png/.state (row: stall alerts; Grafana computed-status).
3. Fix Stadium, then make it a toggleable pane rather than a mode (row: battle view; PyBoy/BGB opt-in panes).
4. Delta strip per card: current segment steps vs record, LiveSplit style green/red, from `Segment.record` and `tools/segments.py` (row: delta vs record).
5. Keyboard pass: 1-6 jump to agent, `[` `]` cycle, `g` goals, `l` log, `?` key overlay; steering still only when focused (row: keyboard-first).
6. Decision log as a filterable, driver-coloured focus pane with a "since stall began" marker (row: thought log).
7. Replay last: keep the 20-event ring plus anomaly states as a short per-agent timeline and scrub only through that (row: timeline). No full TAS tooling.

Do not copy: a browser/web rewrite (Robert chose native); Twitch chat-vote UI; stream overlays/OBS compositing (non-goal); W&B/TensorBoard hosted services or chart-first layouts (we watch games, not loss curves); BizHawk piano-roll editing; dense multi-window debug sprawl (PyBoy/mGBA tools are opt-in); anything modelled on Claude/Gemini stream layouts we could not confirm.

Addendum 2026-11-07 (pull model): the data feed now follows the same discipline as the recommendations — polls on a per-source cadence (2/10 Hz snapshots idle/focused, 0.2/1.0 s events focused/idle, frames only for on-screen cards) and renders at fps from cached state; the frame slot carries a reader heartbeat (`reader_ts`, header layout v2) so agents can render only while watched. One new window beyond the ranked list: the Swarm page — one row per slot (state, segment + curriculum grade, next segment, steps/s + RSS, health, last goal) — an opt-in native pane like the Stadium one, not a chart-first layout.

## 8. Sources
All retrieved 2026-11-07 via WebSearch/WebFetch (search-result summaries; several official docs not retrievable, flagged above): DPG init files and discussion 1088; AWS Grafana thresholds; OBS commit mirror; docs.pyboy.dk/plugins; CoreWeave W&B docs; tb-like (PyPI); bgb.bircd.org/manual.html; mgba.io 0.6.0 post (2017-07-16); tasvideos BizHawk history; TechCrunch (2025-02-25); rentry Gemini about (2025-06-12); PWhiddy/PokemonRedExperiments; livesplit.org/components; Bulbapedia TPP.
Not found: official TensorBoard/Ray/OBS docs, a confirmed Claude-stream party/goal panel, any OpenAI hide-and-seek viewer source.
