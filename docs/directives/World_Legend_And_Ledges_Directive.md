# PokeAgent: world legend - tile kinds (wall, object, grass, ledge, NPC, trainer), ledge-aware routing, goal-keyed tile outcomes

**Read first:** `docs/superpowers/specs/2026-11-05-viewer-and-hybrid-design.md` (sections 4.2 Sees, 5).
**Depends on:** `Explorer_Behaviours_Directive.md` merged (the `src/pokeagent/explorer/` package with
`memory.py` (MapMemory), `perceive.py` (ascii_vision), `decisions.py`). If that package is missing from your
worktree, stop and write that in the Status row. **Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-05): the agent should learn wild grass as different from interactions, NPCs as one kind of
thing and grass/battles as another, impassable objects as different from walls, and ledges that "allow jumping
DOWN but not UP. This allows faster traversal when exploited correctly for a goal." He also asked whether it
memorises per-tile results by the command used and the goal at the time.

What memory already has (in `runs/maps.json`, per map): `blocked` (`"x,y,DIR"` confirmed walls),
`warps` (`"x,y,DIR" -> [map, x, y]`), `jumps` (`"x,y,DIR" -> [x1, y1]`: a press that moved exactly 2 tiles;
the reverse edge from the landing is added to `blocked`), `interactions` (`"x,y,FACING" -> {count, text,
presses, menus, choices}`), `npcs` (`"slotN:picP" -> {pic, slot, positions, last, text, talked, moves}`),
`encounters` (`"x,y" -> count` of wild battles started there), and globally `tile_types[tileset][block] ->
{solid, walkable}` and `grass_ids[tileset][block] -> count`. Per-tile results are keyed by tile + button,
**not by goal**.

What is missing:
- The renderers ignore most of it: `ascii_vision` shows only `@ N # . ? W`; `render_memory` only
  `@ N W i # .`. Grass, ledges, trainers and objects never appear.
- `pokeagent.navigation.shortest_path` (BFS used by options/RL) ignores `jumps`: a route down a ledge
  is modelled as a one-tile step onto an unvisited ledge tile and is dropped, so ledge shortcuts are never
  planned. Current code (`src/pokeagent/navigation.py` lines 43-58):

```python
        visited = set(d.get('visited', {}))
        blocked = set(d.get('blocked', []))
        warps = d.get('warps', {})
        for name, (dx, dy) in DIRS.items():
            key = f'{cx},{cy},{name}'
            if key in warps:  # observed transition beats a stale 'blocked' (fade artifacts)
                m1, x1, y1 = warps[key]
                nxt = (m1, x1, y1)
            elif key in blocked:
                continue
            else:
                nxt = (m, cx + dx, cy + dy)
            if nxt in prev:
                continue
            if nxt != goal and nxt[0] == m and f'{nxt[1]},{nxt[2]}' not in visited:
                continue  # only learned-walkable tiles; warp landings count as known
```
- No record of which press, under which goal, actually led toward that goal from a tile.

## 2. Scope (in order)

1. `src/pokeagent/explorer/legend.py`: one table of tile kinds and glyphs, the single source for every renderer
   and for the viewer (V2 imports it for its legend line).
2. `src/pokeagent/explorer/tilekind.py`: `classify(memory_map: dict, tile_types, grass_ids, tileset, x, y,
   block, npcs_here, trainers) -> str` returning a kind from the legend, by the precedence in section 3.
3. Trainers: when a battle starts with `battle_flag == 2` (wIsInBattle 0xD057 = 2 for trainer battles,
   verified in the demo) right after talking to or being approached by an NPC, mark that NPC entry
   `"trainer": true` (and `"beaten": true` after a win). Do it in `MapMemory` (one new method) and call it from
   the battle behaviour where battles start/end are already detected.
4. Both renderers (`ascii_vision` for Sees and `MapMemory.render_memory` for Remembers) use `tilekind.classify`
   + `legend` glyphs, and each returns its legend string (`legend.line(kinds_present)`).
5. Ledge-aware BFS in `navigation.shortest_path`: a `jumps` edge `"x,y,DIR" -> [x1, y1]` is a one-way edge to
   `(m, x1, y1)`; the landing counts as known. Order of checks: warps, then jumps, then blocked, then step.
6. Goal-keyed tile outcomes: `MapMemory.record_outcome(map, x, y, button, goal_stage, progressed: bool,
   presses_to_goal: int | None)` into `maps[m]["outcomes"]["x,y,BUTTON"][goal_stage] = {"n", "progress",
   "best"}` (counts, and the fewest presses-to-goal seen). Fill it from the decision log at the end of each goal
   segment (the presses since the last goal event are back-filled with `presses_to_goal`). World facts
   (walls, warps, jumps, grass) stay goal-free on purpose - physics does not depend on the goal.

## 3. The work

Legend (glyph, kind, meaning) - exactly these:

| glyph | kind | meaning |
|---|---|---|
| `@` | you | the player |
| `N` | npc | an NPC (sprite table) not known to battle |
| `T` | trainer | an NPC that started a trainer battle (`t` once beaten) |
| `#` | wall | terrain the player cannot enter (tile id learned solid, no interaction) |
| `o` | object | solid tile with an interaction: sign, PC, bookshelf, item ball |
| `~` | grass | tile whose block id is in `grass_ids` for this tileset |
| `!` | encounter | grass tile where a wild battle actually started (`encounters`) |
| `v` `^` `<` `>` | ledge | a recorded jump, glyph = jump direction (one-way) |
| `W` | warp | door/stairs/edge (`warps`) |
| `i` | interaction | walkable spot with a recorded interaction (talk spot facing something) |
| `.` | walkable | visited / learned walkable |
| `?` | unknown | never tried |

Precedence when several apply: `@`, `T`/`t`, `N`, `W`, ledge, `o`, `#`, `!`, `~`, `i`, `.`, `?`.
The ledge glyph is drawn on the **ledge tile itself**: the tile between the jump's start and its landing
(start + one step in the jump direction), which is where the ledge appears on screen.

## 4. What NOT to do

- Make every change inside the `pokeagent.explorer` package and `navigation.py`; `tools/explore_demo.py`
  picks the changes up through its imports and must not grow.

- Do not change how anything is learned (thresholds, confirmations) except adding `trainer`/`beaten` and
  `outcomes`. Do not change existing keys of `maps.json`; only add.
- Do not touch `tools/rl_*.py`, the viewer package, or `telemetry.py`.
- No new dependencies; no module over 300 lines.

## 5. Verification

- `uv run pytest -q` green (baseline = main at dispatch; paste before and after counts).
- Tests: `classify` for each kind and the precedence order on a synthetic memory dict; both renderers on a
  synthetic map show `~ ! v o T #` where expected and return a legend containing only present kinds;
  `shortest_path` on a synthetic map with a ledge: a route that needs the jump is found and uses it, the
  reverse route does not go up the ledge; a trainer is marked after a scripted battle start with flag 2;
  `record_outcome` aggregates n/progress/best correctly.
- Do NOT run `uv run pokeagent ...` (sandbox refuses the entry point). The controller runs a ROM check on
  Route 1 (ledges) on the laptop.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-world-legend-and-ledges-directive`. Never commit to `main`.
- Create no scratch or debug files; if unavoidable, under `.devin-scratch/` and it stays.

## 7. Completion criteria

- [ ] `legend.py`, `tilekind.py`; both renderers use them and return a legend
- [ ] trainers marked; ledge-aware BFS; `record_outcome` filled at goal events
- [ ] Tests in section 5 pass; `uv run pytest -q` green (paste the tail)
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts, a rendered Sees and Remembers sample from your synthetic test map, and anything that
did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Approved |
| Assigned to | devin |
| Branch | - |
| Base branch | - |
| Model | swe-2-flash-max |

**Status log**
- 2026-11-05 18:43 · robert-claude-laptop · none → Queued — Robert approved all 2026-11-05; depends on E1 (merged PR #30 a39b464)
- 2026-11-05 18:44 · robert-claude-laptop · Queued → Approved — lint override: greenfield directive: cited new paths are files it creates; dependency E1 merged
<!-- queue:end -->
