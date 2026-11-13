# Viewer redesign and expansion spec (2026-11-12)

Builds on `viewer-ux-standards-2026-11-07.md` (not repeated). Sequenced after `feat/viewer-qol-visuals` merges.

## 1. Research standards, condensed
**Scope and job.** One viewer family (`src/pokeagent/viewer/ui|panels`, `src/pokeagent/world/`, `viewer/web.py`, PNG export). Robert watches runs live, sometimes on a phone. Better = watch learning happen, spot stalls fast, see why the agent decided.

**Today.** DPG `view` (cards: health-tinted header, Render/Sees, thinking, progress; `ui/theme.py` HEADER_COLOUR per ok/slow/stalled/anomaly); `world` (shared Kanto, interiors inset/inplace/stretch, side panel); `web.py` (read-only, GET only, bound to 127.0.0.1 with a Host-header guard, so a phone cannot reach it yet); headless PNG export. No layout persistence, no timeline, no research/training/team surface.

**Industry standard.** Dear ImGui docking: layout is auto-saved to an .ini, and docking is independent of multi-viewport (ocornut/imgui wiki, docking branch; secondary guides; retrieved 2026-11-12). W&B/Neptune: run table plus parallel coordinates for comparing runs, with an eye toggle to include/exclude (docs.wandb.ai parallel-coordinates; docs.neptune.ai/app/comparison; 2026-11-12). Grafana kiosk/TV mode hides chrome for glanceable use (grafana.com kiosk tutorial; Skykit notes chrome still leaks on mobile, so build a purpose-made small view).

**Common use.** Compare runs by config diff, filter and pin runs, read one big number coloured by threshold (11-07 doc, Grafana thresholds).

**Similar cases.** pokerl: many sessions streamed onto one shared map (PWhiddy/PokemonRedExperiments, pokerl-map-viz); the PufferLib port added a visit heatmap (reported secondhand). TAStudio: branches store the greenzone and markers, can be loaded and relabelled; branch export/import was listed as not done (tasvideos.org/Bizhawk/TastudioDevelopment, forum 2016-2019; lsnes: nothing found). LiveSplit: Possible Time Save, Sum of Best, switchable comparison (PB / best segments / average) (livesplit.org/components). Git graph: one lane per branch, first parent stays in lane, colour by palette index with main pinned and adjacent lanes distinct (GitX GraphingAPI; gitstack colors.rs; neo-git-graph 12-colour cycle). MCTS viewers: depth cap, hide unvisited nodes, click node for detail, auto-fit (gymcts docs; cl-bzh MCTS-Visualizer). Claude Plays Pokemon overlays: no primary source found, so nothing is borrowed from them.

**Comparison (abridged).**
| Need | Ours | Field | Mark |
|---|---|---|---|
| Layout memory | none | ImGui .ini / DPG init file | gap, cheap |
| Run compare | none | W&B table + parallel coords | gap |
| Branch history | none | TAStudio branches, git lanes | gap |
| Beat the record | segments CLI only | LiveSplit delta / Sum of Best | gap |
| Phone watching | 127.0.0.1 only | Grafana kiosk | gap |
| Shared world map | have | pokerl-map-viz | matches |

## 2. Information architecture
Rule: one data contract (the existing snapshot/JSON feeds plus the new JSONL files), two renderers. DPG is the desk cockpit; web is the phone cockpit and the results surface. The phone is read-only and never steers.

| Screen | Where | Contents |
|---|---|---|
| Live | DPG main + web `/` | World map (agent trails, stuck rings, minimap), roster strip, one headline line per agent (state, steps vs best). Web = roster + small map + alert list. |
| Agent detail | DPG focus view + web `/a/<id>` | Render/Sees, thinking (want/plan/blocker/result), goals, events since stall began, steps-vs-best delta. |
| Timelines | DPG pane + web `/timelines` | Foresight branch trails on World (ghost lines, fork pins) plus a git-graph-style tree: lane per branch, main line pinned, marathon forks at milestones, node = save state, click shows frame and outcome. Depth cap and "hide pruned" as in MCTS viewers. |
| Training | DPG tab + web `/training` | XP meters from `xp_rates.jsonl` (rate sparkline per agent), per-map spot ledger (table), "gain left" like Possible Time Save. |
| Research runs | web `/runs` (DPG opens it) | Results table (recipe, fork, metric, delta vs baseline), baseline selector as in LiveSplit comparisons; parallel coordinates later. Table first, no charts. |
| Team | DPG tab + web `/team` (read-only) | Party/HP/DVs, box, PC swap plan, team-search candidates, floor status. Swaps are DPG-only actions. |
| Media | web `/media` + DPG list | Clip and screenshot grid with run/step/branch tags. |
| Health/Logs | DPG pane + web `/health` | Stalls, anomalies, byte-check guard result, invariants, log tail, Swarm rows. |

Phone must-haves: Live, Agent detail, Health, Timelines (read), Training. Layout: single column, 16 px gutter, large status chips, no hover. Phone access needs a deliberate step: a bind option (tailnet interface plus token) in `web.py`, keeping the Host check and GET-only.

## 3. Shared visual language
- **Agent identity:** fixed 8-colour colour-blind-safe palette keyed to slot, reused for map trail, roster chip, label, tree lane, media tag. Letter badge (A..H) as backup so colour is never the only cue. In Timelines the main line uses the agent colour; forks are tints.
- **Health:** four states, always colour plus icon plus word: OK green check, SLOW amber half-clock, STALLED red square, ANOMALY magenta diamond. Shared by card header, roster chip, map ring, web chip. `ui/theme.py` values move to a token file the web page also reads.
- **Delta:** green/red for steps vs best (LiveSplit convention); gold = new best.
- **Icons:** one small glyph set (state, branch, fork, clip, party, ledger), drawn once, used in both renderers.
- **Theme:** one `palette.json` (bg, pane, text, dim, accent, 4 health, 8 agent) with dark and light variants; Game Boy palette is a skin for game frames only. UI scale from the QoL branch applies to both renderers.

## 4. Phased plan (cloud-job sized, after feat/viewer-qol-visuals merges)
1. **Foundation (needs no new data).** `palette.json` tokens with light/dark, icon set, `web.py` shell with nav and responsive Live/Agent/Health pages, tailnet bind plus token option, DPG layout persistence (stable tags + init file). Tests: routes read-only, token required off loopback, headless page snapshot.
2. **Measurement (lands with xp_rates.jsonl and the spot ledger).** Training tab and `/training`: XP meters, ledger table, delta strip, byte-check result on Health.
3. **Research runs (lands with recipes and the forking runner).** `/runs` results table, baseline picker, Media grid, Team read-only page (party, box, floor).
4. **Foresight and Timelines (lands with the branching producer).** Branch-tree pane/page, World branch trails, marathon fork markers; built first against a recorded fixture file so the UI does not wait on the producer.
5. **Team actions (optional).** DPG-only PC swap and team-search plan controls, gated behind the existing human-hold rule.

## 5. Do not copy
- W&B/TensorBoard hosted services or chart-first layouts: we watch games; table before charts.
- TAStudio piano-roll editing and its branch export model: branches are read-only history here.
- A full ImGui docking/multi-viewport rewrite: DPG init files cover it.
- Grafana kiosk as the phone view (chrome leaks): purpose-built small pages.
- Stream-overlay and Twitch vote UIs; layouts modelled on Claude Plays Pokemon (no primary source).
- Steering from the phone, or a live-frame firehose to it (about 1 Hz snapshots).
- Git-graph extras (merge, rebase, diff): only lanes, nodes, outcomes.
