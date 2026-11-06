# PokeAgent: World View - every agent living in its own game, all of it flowing up to one live Kanto view

**Read first:** `docs/superpowers/specs/2026-11-05-atlas-overlay-note.md`, `src/pokeagent/control_server.py`,
`src/pokeagent/snapshot.py`, `src/pokeagent/adapters/explorer_snapshot.py` + `bridge.py`, `src/pokeagent/viewer/`.
**Depends on:** the world-map renderer branch `feat/atlas-world-map` merged (`pokeagent.atlas`: ROM map render,
stitched Kanto `WorldLayout`, `to_world`, overlay layers). If missing, stop.
**Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-05): "I'm also looking for the High-Level View Rendering that uses the actual game assets logic
and components, while also displaying the agents freely within. The question becomes how we allow the agents to
live within the game, while passing ALL of the information up to the top-level view, for ALL Agents."

Design answer: each agent keeps living in **its own real emulator** (its own save state, RNG, NPC positions) - that
is what keeps the game real. What flows up is **information, not pixels**: every agent publishes a typed event
stream, and one World View process merges all streams onto one ROM-rendered Kanto, drawing each agent with the
game's own player sprite at its real coordinates.

## 2. Scope (in order)

1. **Event bus (agent side):** a bounded ring buffer (e.g. 4,000 events) per agent, filled on the emulator thread,
   served by the existing token-guarded ControlServer as `GET /events?since=<seq>` (JSON list, monotonically
   increasing `seq`). Event types (one small dataclass each, schema-versioned like the snapshot): `move` (map, x,
   y, facing, step), `map_change`, `decision` (behaviour, rule, button, outcome, driver), `battle_start` /
   `battle_turn` / `battle_end` (species, levels, HP, move, effect), `item` (gained/used), `goal`, `learn` (new
   wall / warp / jump / encounter / interaction type - the memory delta), `stall`, `human_hold`.
2. **Aggregator (viewer side):** `pokeagent.world.model`: polls every registered agent's `/events` on a
   background thread (concurrent, bounded timeouts - same rules as the viewer poller), keeps per-agent tracks
   (positions, path, current goal, party summary) and a **union of learnings** with per-agent attribution
   (who learned this wall first).
3. **Real-asset rendering:** decode the player and NPC overworld sprites from the ROM (sprite graphics + the
   per-direction frames) in `pokeagent.atlas.sprites`; draw each agent as the player sprite facing its direction,
   tinted / outlined in its agent colour with a small id label; animate smoothly between `move` events (walk
   frames, 16 px per step over the move's frames); draw static map objects (NPCs, trainers, item balls, signs)
   from the ROM object data, and for the selected agent overlay its live NPC positions.
4. **World View window** (Dear PyGui, inside the existing viewer as a third mode; also `pokeagent world`). Modes
   become `grid | world | focus`: a toolbar toggle switches grid <-> world; double-clicking an agent card (grid) or an
   agent marker / stadium panel (world) enters focus on that agent; leaving focus (◀ button, Esc, double-click)
   returns to the mode it came from and releases the hold exactly as today. Steering stays focus-only. Extend
   `viewer/layout.py` FocusState with a `return_mode` and test the transitions. the stitched Kanto texture with zoom/pan, all agents live, trails, toggleable learning layers
   (from the overlay module), the disagreement layer; hover = agent/tile tooltip; click an agent = open its focus
   card; click a tile = everything known about it (ROM truth + union of beliefs + who learned it); a side feed of
   recent events across all agents (filterable: battles, items, goals, stalls).
4b. **Stadium views** (Robert: "specialized Stadium-Views that the Agent goes to when a fight begins, allowing
   the fight to be observed separately. But I want to be able to see the multiples across the entire map,
   wandering around"): the world map always keeps every agent visible. When an agent's `battle_start` arrives,
   its map marker switches to a battle badge (crossed swords + enemy species) and a **stadium panel** opens in a
   strip beside the map: one tile per agent currently in battle, showing that agent's live frame (the existing
   shared-memory frame) plus a battle card built from the battle events - both sides' species, levels, HP bars,
   last move with its multiplier/effect, turn count, and the counter planner's pick if present. Panels close a few
   seconds after `battle_end` (result shown). Click a stadium panel to open that agent's focus view. Later phase
   (not this directive): render the stadium from ROM battle sprites instead of the live frame.
5. **Export:** `pokeagent world --png out.png` renders the current world state to an image (for sharing).

## 3. The work

Pure model + pure render functions (numpy) tested without a display; Dear PyGui code thin. The event bus must not
slow agents: append-only ring buffer, no I/O on the emulator thread beyond the append, serialisation on the HTTP
thread from a snapshot copy.

## 4. What NOT to do

- No shared emulator or "one world" simulation: agents stay independent real games.
- No GUI windows or OS input during testing on Robert's machine (headless only; Robert does the live check).
- No new dependencies; modules <= 300 lines; never commit ROM-derived images or bytes.

## 5. Verification

- `uv run pytest -q` green; tests: event ring buffer (bounded, since-cursor, ordering), aggregator merge of two
  fake agents (union + attribution), sprite decode on synthetic 2bpp data, world-coordinate placement, smooth
  interpolation between two moves, PNG export of a fake world.
- ROM (headless): decode the player sprite and draw 4 fake agents at known tiles of the rendered world; save the
  PNG in the scratchpad and report its path. Agent steps/sec with the event bus on vs off differ by < 3%.

## 6. Rules for this run

- Branch `directive/pokeagent-world-view-directive` off main. Never commit to `main`. Test command
  `uv run pytest -q`. Never bare `python`.

## 7. Completion criteria

- [ ] event bus + `/events`; aggregator with union of learnings
- [ ] ROM sprites; animated agents on the stitched world; world mode in the viewer; PNG export
- [ ] tests and headless ROM checks pasted

## 8. Report

Event schema, PNG path, steps/sec measurement, test tail, anything that did not fit.
