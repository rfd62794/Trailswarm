# Trailswarm: layered methods (umbrella design)

Written 2026-11-06 with Robert. Status: approved; every decision below is settled unless marked
"builder's call". This is the umbrella: it fixes how the methods fit together and the build order. Each
item still gets its own directive or spec. It extends `docs/ROADMAP.md` (the Layers table is unchanged, see
section 2) and `docs/superpowers/specs/2026-11-05-viewer-and-hybrid-design.md` (section 5 is the learning
design this builds on).

## 1. Intent

Trailswarm's contribution is the method, not "AI plays Pokemon". The method has six parts:

1. A cheap rule-based backbone (the Explorer) does the navigation, menus and scripted beats.
2. Learning is used only where it measurably wins (exact save-state A/B, section 7a of the hybrid design).
3. Human input is noise: recorded, graded, half-weighted, dropped if it loses.
4. Claude is the engineer in the loop (reviews stalls, edits rules and knowledge), not the player.
5. Shared knowledge is readable: JSON/Markdown a person can open and fix, not weights.
6. Checkpoints are rewindable: every claim can be re-run from a save state.

Prior art, by name only: PokemonRedExperiments and pokerl-map-viz, pokemonred_puffer, Claude Plays Pokemon,
Gemini Plays Pokemon, the NeurIPS PokeAgent Challenge, Continual Harness, PokeLLMon, Metamon, PokeChamp,
pret/pokered, Data Crystal, stable-retro, pkmn/engine. Where we differ: those either learn everything (RL)
or hand everything to an LLM; we keep the rules and learn in narrow slots.

## 2. The layer map

Dependencies point down only (ROADMAP rule: a layer imports only from layers below it). Four decision
layers, plus three cross-cutting mechanisms that may call any decision layer through its public interface.

| Layer | Job | Method | Modules today |
|---|---|---|---|
| Strategy | which goal or segment next; when to escalate | curriculum; LLM planner only on escalation | `campaign.py`, `goals.py`, `checkpoint_goals.py`, `curriculum.py`, `data/campaign.json`, `intervene/` (Claude asks) |
| Tactics | which behaviour for this situation | behaviour bandit now, RL over behaviours later | `options.py`, `qmodels.py`, `learning.py`, `decision.py`, `human_hold.py` |
| Operations | do the behaviour | Explorer rules, A*/par paths, battle rules | `explorer/` (engine, planner, `behaviours/`, battle, `toss_guard.py`), `navigation.py`, `knowledge/`, `atlas/` (walk grid) |
| Reflex | press buttons, read RAM | none (deterministic) | `emulator.py`, `emu_thread.py`, `ram.py`, `ramworld.py`, `hexmap.py`, `names.py`, `screentext.py`, `ramlab/` |

Cross-cutting, around all four:

| Mechanism | Job | Where |
|---|---|---|
| Go-Explore archive | cells with save states; swarm workers start from rare or frontier cells | `runs/archive/`, supervisor writes (hybrid design 7a) |
| Save-state lookahead | try each candidate a few presses ahead, keep the best, reload | battles, menus, ledges only; budgeted |
| Swarm evolution | CMA-ES over policy parameters (thresholds, weights), not over buttons | `swarm*.py`, `supervisor.py`; new `evolve/` module (builder's call: name) |

Interfaces (viewer, `world/`, MCP, control server, `adapters/`) sit beside the stack as ROADMAP layer 4.
They read snapshots and send commands; they are not decision layers.

Rule for the stack: Strategy calls Tactics by naming a goal; Tactics calls Operations by naming a
behaviour; Operations calls Reflex by naming a button. Nothing calls up. A lower layer reports upward only
through return values and the snapshot (`driver`, `rule`, `confidence`).

## 3. Compatibility matrix

Combines cleanly: Explorer + bandit; Explorer + Go-Explore; Explorer + lookahead; bandit + lookahead
(lookahead is how the bandit gets its exact A/B); Go-Explore + CMA-ES (the archive supplies start states,
evolution scores policy parameters on them); LLM planner + anything, on escalation only; DAgger on
behaviour-level choices.

| Conflict | Rule |
|---|---|
| Pixel-based RL vs the rules for control of the buttons | Not allowed. One controller per decision, per the layer map. RL chooses a behaviour; it never presses a button while a behaviour is running. The low-level RL ladder (`tools/rl_*`) stays frozen. |
| Curiosity bonus vs tight segment budgets | No curiosity bonus. Exploration comes from the Go-Explore archive (new cell = small + reward only), and a segment run has a hard press budget (3x best, `docs/SEGMENTS.md`). |
| Evolution and gradient RL tuning the same parameters | Disjoint parameter sets. CMA-ES owns continuous policy parameters (thresholds, flee HP, weights). The bandit/RL owns the discrete behaviour choice per Q-state. A parameter has exactly one owner, listed in a table in the evolve module. |
| Behaviour cloning on raw human input | No. Human presses enter only as graded hypotheses at behaviour level, at half the weight of an Explorer demonstration, dropped if the next goal is not reached sooner (hybrid design 5.8). Presses right after a hold ends are excluded. |
| World-model learning vs the emulator | Redundant. The emulator is an exact, deterministic, rewindable model; use save states for lookahead and A/B. No learned dynamics model. |

## 4. Shields before penalties

Irreversible actions get hard guards in code, so the learner can never try them. Penalties only teach the
learner about things that are reversible but costly.

| Shield | State |
|---|---|
| Never toss an item | built: `explorer/toss_guard.py` (PR #97) |
| Never release a Pokemon | to build |
| Never deposit the last fighter, or the only HM user needed ahead | to build (needs the HM list from section 6) |
| Save only from the PC's box-change flow | to build; no other save path is offered to any driver |

Shields mask the action (as the stuck-watchdog masks a looping behaviour) and log the attempt, so a blocked
attempt is itself a signal for the viewer.

Rewards (sparse, per hybrid design 5.6; magnitudes are builder's call, the ordering is fixed):

| Event | Sign | Size |
|---|---|---|
| Goal reached | + | large |
| New Go-Explore cell | + | small |
| Each button press | - | tiny (this is what makes fewer presses win) |
| Stall (watchdog fired) | - | medium |
| Blackout | - | large |
| Item tossed or released, or money lost | - | large (should be unreachable; the penalty catches a shield gap) |

No dense shaping. A penalty never replaces a shield.

## 5. Targets: Goal, then Segment, then Leg, then Step

Goal (`data/campaign.json`) -> Segment (`docs/SEGMENTS.md`; one goal boundary to the next, with a record) ->
Leg (one point-to-point walk inside a segment) -> Step (one press). Each level has a number to beat.

**Legs and par.** A leg's par is the exact cheapest path in frames on the ROM collision grid. Cost model:

- walk 16 frames per tile, bike 8;
- grass carries encounter risk (priced, not forbidden; builder's call: cost per grass tile, tuned from
  encounter logs);
- one-way ledges are directed edges (jump down only);
- trainer line of sight is a trigger cost (a fight is a fixed detour plus battle frames);
- NPCs are temporary blocks, never walls: plan as if they move, replan on contact. Only ROM-static
  collision is a wall.

Legs stack into segments; efficiency = par / actual frames, per leg and per segment. A segment's par is the
sum of its leg pars plus fixed costs for beats (text, menus). A builder is building `src/pokeagent/legs/`
and `tools/leg_report.py` now; this section fixes the vocabulary they use. Par feeds the World view (par
lines, section 9) and the swarm's polish allocation (largest gap between actual and par first).

## 6. Team and Inventory layer

A new Operations-level module family, `src/pokeagent/team/` (builder's call: name), consulted by Strategy
when a campaign gate needs something. Built in this order:

1. **Ball buying.** Keep a ball reserve sized to the catch need-list; buy at the Mart when money allows and
   the reserve is short.
2. **Catch need-list.** Campaign gates drive it. `campaign.json` already has `needs: ["cut"]` (Vermilion
   Gym entry, Thunder Badge, Route 9, Celadon Gym entry, Rainbow Badge) and `needs: ["dex10"]` (HM05
   Flash). The list maps each need to a catch target: a Pokemon that can learn the HM move (Cut, Flash,
   Surf, Strength) with room in the team. "dex10" means ten Pokedex entries before the Flash gate. Note
   that **Squirtle cannot learn Cut**, so a Squirtle start makes a Cut user a mandatory catch. Learnability
   comes from the ROM's learnset and HM compatibility tables, not from memory.
3. **Team optimisation, rules first.** Use ROM data: the type chart, move data, and the real teams of gym
   leaders and rivals (trainer party tables). Rules score a team against the next gym. The behaviour bandit
   then chooses between a few team plans (for example "train the starter" vs "catch and train a
   counter"); a plan is graded by the segment result like any other bandit arm.
4. **PC management.** Swaps between party and box; storing items when the bag is full; Gen 1 box-full
   means no catching (so check before a catch run); a box change needs a save (the section 4 shield). It
   goes through the existing box flow (`explorer/behaviours/box_settle.py`).

HM users are a protected resource: the section 4 shields read this module's "needed ahead" list.

## 7. The RAM/ROM toolkit

Source: `docs/research/reports/RAM ROM tooling for game agents.md`. The toolkit is a self-contained package
inside this repo (builder's call: `src/pokeagent_ramrom/`) that imports nothing from `pokeagent`, so it can
be split into its own repo later. The agent depends on it, never the reverse.

| Part | Content |
|---|---|
| Address table | Generated from a pinned pokered `symbols` branch `.sym` file. Each entry: name, bank, address, length, type as a stable-retro type string (`\|u1`, `>u2`, `>d2` for BCD), short note. Explicit bank field. |
| Verifier | Automatic check of the table against the ROM and a known save state: revision check on load, each entry must land where the ROM says. Fails the test suite when a pin changes. |
| Typed readers | Read-only: party, bag, box, map, position, flags, sprites (`$C100`/`$C200` tables), battle. Replace hand-held addresses in `ram.py` over time. |
| Writers | Own module, never imported by readers. Party, event and warp writes, used by tests and section 8. |
| Bridge | Agent-vs-agent play (section 8) and a stable-retro `data.json` export. |

Reuse rules, in order: (1) depend on a package; (2) copy a small piece; (3) fork last. Copied files carry a
header with source URL, commit and licence, plus an entry in `THIRD_PARTY.md`. pokemonred_puffer showed no
licence in the research, so it is a design reference only. **Never commit ROM-derived or pokered-derived
data**: commit generators and tests, and produce the table at setup time into a gitignored path. Modded
ROMs (built from pokered with changed tables) are test harnesses only, never a source of truth.

### Two layers

- **Hardware layer, identical for every Game Boy game**: the OAM sprite table at 0xFE00 (x, y, tile and
  flags for every sprite), the VRAM background tile maps at 0x9800/0x9C00, palettes, and tile hashing, which
  groups identical tiles automatically.
- **Game adapter, one per title**: generated from its pret disassembly where one exists (pokered for Red/Blue,
  pokeyellow, pokecrystal), with the same generator and verifier. The agent only talks to the adapter
  interface, never to a game's addresses.

## 8. Agents meeting

**Live info by proximity.** Agents share the Shared Map (atlas/world, `[x, y, map]` per agent in the
pokerl-map-viz style). When two agents are on the same map within a set distance (builder's call: 8
tiles), they exchange NPC positions, trainer-defeated flags and open warps for that map through the
knowledge store. This is information only; no game state moves between them.

**Agent-vs-agent battles, two modes**, chosen by purpose:

| Mode | Use | How | Limits |
|---|---|---|---|
| Watchable live battle | show two agents fighting | PyBoy 2.9 `serial_shared_memory` link: one shared serial buffer, one process per player, interrupt-based serial | The official example only trades; a Colosseum battle over the same link is untested (spike first). Save states do not work while linked, so no rewind. |
| Learning battle | train and grade battle choices | Opponent-team injection in a single emulator: write the opponent party into the enemy party area | Rewindable. The injected team must be written after the trainer-load routine zeroes the enemy party (`read_trainer_party`): hook the point after it and write there. The `wEnemyParty` address comes from the .sym via the toolkit, not from Data Crystal. |

Spike order: injection first (it serves learning and rewinds), live link second. The exact serial handshake
bytes are unverified; read `home/serial.asm` in pokered before building the link.

## 9. The World view

- **Follow mode** (in progress): the camera tracks a chosen agent.
- **NPCs**: for each map, draw NPCs from the agent closest to that map's activity (the closest agent on
  the map). When no agent is on the map, draw last-seen positions, dimmed with an age. Static placement
  comes from the pret object files via the toolkit; live movement from agents.
- **Par lines**: draw each leg's par path beside the actual path, coloured by efficiency (section 5).

## 10. Language rewrites

Only where a bottleneck is measured and the measurement is recorded in the directive. Candidates: the
pkmn/engine battle simulator (Zig) for lookahead and team-scoring speed, and world-view composition.
Default stays Python. A rewrite sits behind the same interface as the module it replaces.

## 11. New game onboarding

- **Day one in any Game Boy game**: emulator, save states, swarm, hardware perception, map memory that learns
  walls by bumping, Go-Explore novelty.
- **Memory discovery**: `tools/ram_discover.py` diffs RAM around events. Games with a disassembly get a
  generated table; games without one get a draft table from discovery, verified in play.
- **Claude as engineer for each game**: writes the adapter, the campaign goals and the shields.
- **What transfers between games**: sprite and tile recognition trained on emulator-made labels, bandit priors
  (advance dialog, back out of unknown menus, explore the frontier), and shields (never confirm destructive
  prompts). What doesn't transfer: game facts such as gym teams, HM gates and par routes.
- **Order**: Pokemon Blue (nearly free), then Yellow (one generated table), then Crystal (new engine, has a
  disassembly), then a non-Pokemon top-down Game Boy game (first test without a disassembly).
- **Metric**: hours from a cold start to the first goal, per game, compared with the previous game.

## 12. Build order and status

| Item | Status |
|---|---|
| PR #96 Route 24 | done |
| PR #97 never-toss shield | done |
| PR #98 Route 25 | done |
| Behaviour bandit (Tactics) | in progress |
| Legs and par (`legs/`, `tools/leg_report.py`) | in progress |
| Balls and the catch list | in progress |
| Follow mode (World view) | in progress |
| Team optimisation | next; needs ROM tables from the toolkit or `tools/rom_tables.py` |
| RAM/ROM toolkit (address table + verifier first) | next; unblocks injection, NPCs, remaining shields |
| NPCs in the World view | next; after toolkit readers |
| Agent meetings (proximity, then injection, then live link) | next |
| PC management and the remaining shields | next; after team optimisation |
| CMA-ES swarm evolution | next; after par exists (par is its fitness signal) |
| Pokemon Blue adapter | next |
| New game onboarding (Yellow, Crystal, non-Pokemon) | later |

Dependencies: legs/par -> World par lines, CMA-ES fitness, polish allocation. Toolkit -> NPCs, injection,
remaining shields. Catch list -> team optimisation -> PC management. Bandit -> team-plan choice.

## 13. Builder's calls (collected)

Package names (`pokeagent_ramrom`, `team/`, `evolve/`); reward magnitudes; grass-tile cost; proximity
radius (8 tiles); Q-state bucketing for the team-plan bandit; how a shield reports a blocked attempt to
the viewer; how far ahead "HM user needed ahead" looks. Everything else here is decided.

## 14. Constraints carried over

uv + Python 3.12 via `uv run`; no module over 600 lines; layers import downward; ROM and save states never
committed; live-run gates are Claude verification steps on the laptop; merge commit, not squash.
