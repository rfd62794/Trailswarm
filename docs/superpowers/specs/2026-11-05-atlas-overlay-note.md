# Atlas: the model overlaid on the real game map (design note, not yet a directive)

Robert, 2026-11-05: "this also clearly could expand into a UI System where I can translate its learnings onto a
UI Map of the actual game system, as there are also ROM Editors that allow for full map control and extensive
editing, and combined with the Model Translation, we could overlay the actual model logic onto a real view of the
game and its components."

## The idea

ROM map editors (for Gen 1 Red/Blue they read pret/pokered's data formats) draw every map in full from the
cartridge: map header -> width/height, blockset, tileset graphics, border block, warps, signs, object events
(NPCs, trainers, item balls), connections to neighbouring maps. The agent's model is keyed by the same map ids and
tile coordinates. Rendering the real map from the ROM and drawing the model on top gives:

- **Truth vs belief:** the ROM says where every wall, warp, sign, trainer and item ball *is*; the model says what
  the agent *believes*. Differences are exactly the bugs worth surgery (a false wall, a missed warp, a forced-walk
  "door").
- **Learning made visible:** visit heat, goal-keyed outcomes, encounter spots, ledge jumps and planned routes drawn
  over real pixels instead of ASCII.
- **Live view:** each agent's position and current route on the atlas while it plays (a panel in the viewer).
- **Editing:** surgery on the overlay (the Brain Tools journal), and - far later and only on a copy of the ROM -
  experiments with map edits, the way ROM hackers do.

## Layers (same rule: one job per module, dependencies downward)

1. `pokeagent.atlas.rom_maps` (layer 0/1): drain map headers, blocksets, tilesets, warps, signs, objects and
   connections from the ROM using pokered offsets, each verified against facts the agent already knows (Pallet
   Town's warps match `runs/maps.json`; the lab's three pic-61 objects at (6,3)/(7,3)/(8,3)).
2. `pokeagent.atlas.render` : map -> RGB image (8x8 tiles, 32x32 blocks) with a per-tile coordinate grid.
3. `pokeagent.brain` (Brain Tools phase 1) supplies the model facts per tile; `pokeagent.atlas.compare` computes
   truth-vs-belief differences.
4. UI (phase 2/3): an Atlas panel in the viewer and a full-screen Atlas tool (Dear PyGui textures, zoom/pan,
   overlay toggles, click a tile for `tile_facts`).

## Order

Brain Tools phase 1 (Claude-facing CLI + MCP + journal) -> Game Knowledge drain (moves, species, encounters,
trainers) -> Atlas layer 1-2 with ROM verification -> compare -> UI. Each step is its own directive.
