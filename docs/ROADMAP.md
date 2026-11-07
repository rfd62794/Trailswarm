# PokeAgent: direction, layers, roadmap

Written 2026-11-03 00:50 after the first evening. Owner Robert; Claude plans and reviews; Devin builds from
directives; the explorer demo is the living spike that every directive must leave improved.

## Direction (one sentence)

One tool, `pokeagent`, in which a cheap rule-based agent plays Pokemon Red from the game's own data (RAM, tile
map, ROM tables), learns the world and the beats into a knowledge base that every run and every agent shares,
and asks a human or Claude only at genuinely new situations - all of it watchable, steerable and measurable.

## Prior art (what the field does; use, do not reinvent)

- **Peter Whidden's PokemonRedExperiments (2023)**: PyBoy + reinforcement learning (PPO) with reward shaping
  from RAM (exploration, levels, badges). Lesson: RAM-derived rewards and massively parallel headless
  emulators are what make learning fast; pure RL needed millions of frames to leave Pallet Town. We keep the
  parallel-emulator idea (swarm.py) and the RAM-reward idea (goals.json detectors) without the neural net.
- **"Claude Plays Pokemon" (Anthropic, 2025) and "Gemini Plays Pokemon" (2025)**: LLM agents with a tool
  harness: RAM reads, a navigation/pathfinding tool, screenshot plus a tile overlay, and a persistent knowledge
  base and notes. Lesson: the harness (memory, pathfinder, structured state) mattered more than the model;
  the models wasted most tokens on navigation and menus. Our split - dumb agent for navigation and menus,
  Claude for judgment - is the direct response.
- **PokeAgent Challenge (NeurIPS 2025 competition track)** and the pokemon-red gym wrappers: standardised
  RAM-based observations (map, position, party, badges, events) and event-flag progress metrics. Lesson:
  the event-flag table is the canonical progress signal; our `triggers`/`unknown_flags` capture is the same idea.
- **Game-AI standards for "logic switch" agents**: behaviour trees (selector/sequence over conditions) for the
  per-step policy, GOAP/HTN planning over preconditions and effects for goals, blackboard memory shared between
  behaviours. Our explorer is already shaped like this (readiness -> battle -> box -> goto -> replay -> plan ->
  explore is a selector); the Explorer_Policy_Module directive should make it an explicit behaviour tree.
- **pret/pokered disassembly**: the ground truth for addresses, charmap, map ids, item ids, type chart and move
  data. We verify each claim on the ROM before relying on it (docs/KNOWLEDGE.md).
- **Save-state search**: emulator checkpoints make one-step lookahead and segment re-runs exact and cheap
  ("save-scumming to fast-map"); speedrunning communities use the same idea with TAS tools.

## Layers (SOLID/SRP/KISS: one job per module, dependencies point downward)

| Layer | Modules (status) | Job |
|---|---|---|
| 0 Emulation | emulator, ram, hexmap, names(+ram_names.json), screentext (all merged) | PyBoy seam, RAM facts, decoding |
| 1 Perception | textbox (dir 7), vision/ascii (demo), battle state (dir 12, new) | what is on screen / in RAM right now |
| 2 Memory & knowledge | mapmem (dir 8), kb (dir 9), demos + review (dir 11), KNOWLEDGE.md | what we have learned; graded, shared |
| 3 Policy & planning | policies/explorer (dir 11), planner + goals.json (dir 11), LLMPolicy (merged as backend/prompt/decision), hybrid (dir 11) | choose the next button |
| 4 Interfaces | viewer GUI (dir 6), MCP server (dir 5, building), control API (demo), CLI (merged) | humans and Claude watch and steer |
| 5 Operations | swarm (demo), checkpoints/branching (dir 10, new), review reports | run many, rewind, measure |

Rule: a layer imports only from layers below it. The demo is the one place that wires all layers together.

## GUI (replan, feeds the Viewer directive)

Four regions, each owning one kind of information: (1) game screen; (2) agent log (thinking, button, result,
graded replays, stalls); (3) world: SEES (tile map as text) and REMEMBERS (map memory), no text in it;
(4) dialog and status: current box/menu text, goals, battle flag, party/bag/money. Human keys steer from any
region; the same four regions become MCP resources so Claude sees exactly what Robert sees.

## Phases and milestones

- **Phase 0, bootstrap (done 2026-11-02)**: repo, emulator seam, backend, loop, CLI, hex tooling, verified
  RAM facts (map, position, money, bag, PC box, tile map, charmap, frames, party count, species, battle flag),
  baseline state, explorer demo reaching the first four goals in one run (14 / 42 / 116 / 264 steps).
- **Phase 1, consolidation (directives 5-11)**: MCP server; viewer with human steering; text-box awareness;
  map memory; world KB (tile types, NPCs, triggers); explorer policy module with `--policy explorer|claude|hybrid`.
  Milestone: `pokeagent run --policy explorer` reproduces the demo with the demo file under 80 lines; Claude
  plays through the MCP tools.
- **Phase 2, beats and battles (directives 10, 12, 13)**: checkpoints and save-state branching (segment
  re-runs, one-step lookahead on unknown choices); battle state from RAM and the battle menu grammar; battle
  math from ROM data (type chart, move power) with a rule-based move chooser. Milestone: rival battle won
  without A-mashing, with HP-aware item use; every goal segment re-run from its checkpoint by the swarm.
- **Phase 3, the campaign (goals.json 5-13)**: Route 1, parcel, Pokedex, Poke Balls, first catch, Pokecenter,
  training, Viridian Forest, Brock. Milestone: Boulder Badge by the dumb agent with at most N Claude consults,
  measured by the review tool.
- **Phase 4, scale and guide**: swarm as the default learner between watched runs; hybrid mode budgets; a
  nightly report (goal steps, stalls, consults, new KB facts); then Misty and beyond.
- **Other games**: Pokemon Blue first (same engine), then Yellow, Crystal, a non-Pokemon GB game - see
  docs/superpowers/specs/2026-11-06-layered-methods-design.md "New game onboarding".

## Open decisions for Robert

- How many Claude consults per run are acceptable in hybrid mode (cost ceiling)?
- Keep the explorer's HTTP control API after MCP lands, or MCP only?
- Starter policy for the campaign: fixed, random per run, or the one that measures best?
