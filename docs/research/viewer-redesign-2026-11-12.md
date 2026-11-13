# Viewer redesign and expansion spec (2026-11-12)

Builds on `viewer-ux-standards-2026-11-07.md` (not repeated). Sequenced after `feat/viewer-qol-visuals` merges.
Scope: desktop UI only (Dear PyGui). Web and phone views were dropped by Robert on 2026-11-12.

## 1. Research standards, condensed
**Scope and job.** One viewer family (`src/pokeagent/viewer/ui|panels`, `src/pokeagent/world/`, PNG export). Robert watches runs live on the desktop. Better = watch learning happen, spot stalls fast, see why the agent decided.

**Today.** DPG `view` (cards: health-tinted header, Render/Sees, thinking, progress; `ui/theme.py` HEADER_COLOUR per ok/slow/stalled/anomaly); `world` (shared Kanto, interiors inset/inplace/stretch, side panel); headless PNG export. `src/pokeagent/viewer/web.py` also exists (read-only, GET only, bound to 127.0.0.1 with a Host-header guard); no work is planned on it. No layout persistence, no timeline, no research/training/team surface.

**Industry standard.** Dear ImGui docking: layout is auto-saved to an .ini, and docking is independent of multi-viewport (ocornut/imgui wiki, docking branch, https://github.com/ocornut/imgui/wiki; secondary guides; retrieved 2026-11-12). W&B/Neptune: run table plus parallel coordinates for comparing runs, with an eye toggle to include/exclude (docs.wandb.ai parallel-coordinates; docs.neptune.ai/app/comparison; 2026-11-12). Grafana kiosk/TV mode hides chrome for glanceable use (grafana.com kiosk tutorial).

**Common use.** Compare runs by config diff, filter and pin runs, read one big number coloured by threshold (11-07 doc, Grafana thresholds).

**Similar cases.** pokerl: many sessions streamed onto one shared map (PWhiddy/PokemonRedExperiments, pokerl-map-viz); the PufferLib port added a visit heatmap (reported secondhand). TAStudio: branches store the greenzone and markers, can be loaded and relabelled; branch export/import was listed as not done (tasvideos.org/Bizhawk/TastudioDevelopment, forum 2016-2019; lsnes: nothing found). LiveSplit: Possible Time Save, Sum of Best, switchable comparison (PB / best segments / average) (livesplit.org/components). Git graph: one lane per branch, first parent stays in lane, colour by palette index with main pinned and adjacent lanes distinct (GitX GraphingAPI; gitstack colors.rs, https://docs.rs/crate/gitstack/5.3.0/source/src/graph/colors.rs; neo-git-graph 12-colour cycle, https://www.mintlify.com/asispts/neo-git-graph/features/graph-view). MCTS viewers: depth cap, hide unvisited nodes, click node for detail, auto-fit (gymcts docs, https://gymcts.readthedocs.io/en/latest/visualisation.html; cl-bzh MCTS-Visualizer, https://cl-bzh.github.io/MCTS-Visualizer/). Claude Plays Pokemon overlays: no primary source found, so nothing is borrowed from them.

**Comparison (abridged).**
| Need | Ours | Field | Mark |
|---|---|---|---|
| Layout memory | none | ImGui .ini / DPG init file | gap, cheap |
| Run compare | none | W&B table + parallel coords | gap |
| Branch history | none | TAStudio branches, git lanes | gap |
| Beat the record | segments CLI only | LiveSplit delta / Sum of Best | gap |
| Shared world map | have | pokerl-map-viz | matches |

## 2. Information architecture
Rule: one data contract (the existing snapshot/JSON feeds plus the new JSONL files), one renderer (DPG). The DPG main window is the cockpit; each screen below is a panel or tab in it.

| Screen | Where | Contents |
|---|---|---|
| Live | DPG main pane | World map (agent trails, stuck rings, minimap), roster strip, one headline line per agent (state, steps vs best). |
| Agent detail | DPG focus view | Render/Sees, thinking (want/plan/blocker/result), goals, events since stall began, steps-vs-best delta. |
| Timelines | DPG tab | Foresight branch trails on World (ghost lines, fork pins) plus a git-graph-style tree: lane per branch, main line pinned, marathon forks at milestones, node = save state, click shows frame and outcome. Depth cap and "hide pruned" as in MCTS viewers. |
| Training | DPG tab | XP meters from `xp_rates.jsonl` (rate sparkline per agent), per-map spot ledger (table), "gain left" like Possible Time Save. |
| Research runs | DPG tab | Results table (recipe, fork, metric, delta vs baseline), baseline selector as in LiveSplit comparisons; parallel coordinates later. Table first, no charts. |
| Team | DPG tab (read-only view) | Party/HP/DVs, box, PC swap plan, team-search candidates, floor status. Read-only; swap controls live only in optional phase 5. |
| Media | DPG tab | Clip and screenshot grid with run/step/branch tags. |
| Health/Logs | DPG pane | Stalls, anomalies, byte-check guard result, invariants, log tail, Swarm rows. |

Layout: DPG docking/tabs, so the Live pane stays visible while other tabs are open. Layout is saved and restored between sessions.

## 3. Shared visual language
- **Agent identity:** fixed 8-colour colour-blind-safe palette keyed to slot, reused for map trail, roster chip, label, tree lane, media tag. Letter badge (A..H) as backup so colour is never the only cue. In Timelines the main line uses the agent colour; forks are tints.
- **Health:** four states, always colour plus icon plus word: OK green check, SLOW amber half-clock, STALLED red square, ANOMALY magenta diamond. Shared by card header, roster chip and map ring. `ui/theme.py` values move to the `palette.json` token file.
- **Delta:** green/red for steps vs best (LiveSplit convention); gold = new best.
- **Icons:** one small glyph set (state, branch, fork, clip, party, ledger), drawn once and used by the DPG panels.
- **Theme:** one `palette.json` (bg, pane, text, dim, accent, 4 health, 8 agent) with dark and light variants; Game Boy palette is a skin for game frames only. UI scale from the QoL branch applies to the DPG panels.

## 4. Phased plan (cloud-job sized, after feat/viewer-qol-visuals merges)
1. **Foundation (desktop only, needs no new data).** `palette.json` tokens with light/dark, icon set, DPG layout persistence (stable tags, docking/tabs, init file). Tests: palette loads both variants, layout save/restore round trip, headless DPG snapshot.
2. **Measurement (lands with xp_rates.jsonl and the spot ledger).** Training tab: XP meters, ledger table, delta strip, byte-check result on Health.
3. **Research runs and Media (lands with recipes and the forking runner).** Research runs tab: results table, baseline picker. Media tab: clip and screenshot grid. Team read-only tab (party, box, floor).
4. **Foresight and Timelines (lands with the branching producer).** Timelines tab, World branch trails, marathon fork markers; built first against a recorded fixture file so the UI does not wait on the producer.
5. **Team actions (optional).** DPG-only PC swap and team-search plan controls, gated behind the existing human-hold rule.

## 4b. GUI framework and language choice (Robert 2026-11-12: any GUI method, other languages where they pay)
**Decision: stay on Dear PyGui for the desktop shell; use other languages only on measured hot paths.**
- **Dear PyGui (kept).** Already drives `view` and `world`. The map is drawn as a GPU texture, docking and tabs are built in, there is one process with direct access to the Python snapshot, and RAM is lowest of the Python options (estimate, not measured). Every phase above is panel work, not a rewrite.
- **imgui-bundle (escape hatch).** Same immediate-mode model. Repo https://github.com/pthom/imgui_bundle exists; latest release v1.93.0, dated 21 Oct (year not shown on the releases page). Ships ImPlot and a node editor (Timelines tree; not checked). Move to it only if DPG blocks a phase: panels port mechanically.
- **Rejected:** Qt/PySide6 (rewrite, roughly 2x RAM (estimate, not measured), retained-mode); Tauri/Electron/web shells (web dropped); a Rust egui viewer (a full rewrite in a second language, and the snapshot would have to cross a process boundary).
- **Other languages, where they pay:** (1) clip/screenshot encoding stays in ffmpeg (C) via subprocess (Media module); (2) map stitch/render and heat layers go to numpy first, and Rust via PyO3 only if a profile still shows it hot; (3) the always-on harness daemons (AgentFlow pulse, tick, mailbox, bridge, memory, collective; about 840 MB across the always-on Python services (measured on the laptop, 2026-11-13 02:28Z), each doubled by a 5 MB venv launcher shim) consolidate into one Python process first. A Go single-binary port follows only for whatever stays resident and heavy after that (Go 1.27 is already set up on the laptop). That plan lives in AgentFlow, not here.
- **Blank World capture:** check this before phase 1. GDI capture of a GPU swapchain can read white; the headless DPG snapshot test (phase 1) gives exact screenshots without screen capture.

## 5. Do not copy
- W&B/TensorBoard hosted services or chart-first layouts: we watch games; table before charts.
- TAStudio piano-roll editing and its branch export model: branches are read-only history here.
- A full ImGui docking/multi-viewport rewrite: DPG init files cover it.
- Grafana kiosk chrome: purpose-built small DPG panels.
- Stream-overlay and Twitch vote UIs; layouts modelled on Claude Plays Pokemon (no primary source).
- Steering from a second client, or a live-frame firehose (about 1 Hz snapshots is enough).
- Git-graph extras (merge, rebase, diff): only lanes, nodes, outcomes.
- Web/phone views dropped by Robert 2026-11-12; desktop UI only.
