# Unlock layer: recognise and use what a goal just made possible (2026-11-07)

Status: spec only. Follows PR "HM01 Cut recognition" (flag detectors, `cut_taught`, `behaviours/goal_talk.py`).

## Problem
Capabilities arrive silently: the agent got Cut and kept treating every Cut tree as a wall. Three gaps: (1) goals whose detector
does not mean what its name says, (2) a capability that exists in the bag/party but nothing reads it, (3) world changes
(passable trees, new routes) that no planner knows about. `campaign.agent_capabilities()` is env-only (`POKEAGENT_CAPS`), so
`campaign_reachable` / `selectable` still wall off everything behind a `needs: ["cut"]` goal after Cut is taught.

## 1. Capabilities from RAM, not env
New `pokeagent/unlocks.py` with `capabilities(emu) -> frozenset[str]`: `cut` iff `campaign.party_knows_move(emu, 15)` (and the HM flag
0xD803.0 for the "option exists" state, returned as `cut_available`); later `surf` (move 57), `strength` (70), `flash` (148), `bike` (bag 0x06),
`poke_flute` (bag 0x49). `campaign.agent_capabilities()` unions the env override with `unlocks.capabilities(emu)` when an emulator is passed;
`tools/swarm.py weakest_segment` and `overnight.py` pass the segment's start state so Cut-gated goals become selectable once `cut_taught` is true.
Each capability gets a one-line log when it first turns true (`[unlock: cut]`), recorded in `runs/events` for the swarm digest.

## 2. World change: cut trees passable
- Today `atlas/walkgrid.walk_grid` = `np.isin(cell_tiles, walkable_ids(rom, tileset))`; the tree tile is not in the ROM collision list, so
  it is a wall. pokered `engine/overworld/cut.asm` treats overworld tile 0x3D (and the gym-tileset tree tile 0x50) as cuttable; verify both ids against the ROM
  with a `ram_checks`-style check (stand facing the tree, USE CUT, read `wTileInFrontOfPlayer` before and after) before relying on them.
- `walk_grid(rom, hd, unlocked=frozenset())`: with `"cut"` in `unlocked`, `CUT_TREE_TILES` count as walkable but carry a cost (a cut = ~40 presses),
  and BFS returns the tree cell as a waypoint flagged `needs_interaction="cut_tree"`. `rom_planner` / `rom_cave_planner` take `unlocked` from `unlocks.capabilities`.
- `explorer/world.WorldGraph` learns the tree cell as `blocked` today; add `cut_trees` per map in `maps.json` (x, y, state: standing|cut) so memory
  stops re-learning it as a wall; `memory_tiles` marks the cell `tree` in the legend instead of `solid`.

## 3. Defined interaction: `cut_tree`
A new `behaviours/cut_tree.py` (sibling of `goal_talk.py`, same walk-face-act shape): when the path's next cell is a standing cut tree and `cut` is unlocked,
face it, run the use-HM sequence from `item_policies/key_items.py` (START -> POKeMON -> party member that knows CUT -> CUT; the field-move entry is
the first menu row after the member's stats), confirm the tree cell turns walkable (tilemap changes, `wTileInFrontOfPlayer`), then step through.
Failure: cooldown and mark the tree `failed` (not a wall). Same pattern later for `surf` (water edge) and `strength` (boulder).

## 4. Newly reachable goals (data, not code)
Once `cut` is a RAM capability the existing `needs` tags do the work; check each in `campaign.json` and give it a segment start state:
`vermilion_gym_entry` (tree in front of the gym; then `beat_surge`, which also needs the `puzzle` tag), `to_route9` (tree at Route 9 x=4),
`celadon_gym_entry` / `beat_erika`, and the Route 2 shortcut (Viridian Forest bypass: tree east of Pewter-side Route 2) and Diglett's Cave entrance as new
optional goals with `map_past_x`/`map` detectors (ids from `atlas/rom_maps`), placed off the chain's critical path.

## 5. Rule: every goal needs a verified detector
Allowed kinds: item, map, party, party_move, badge, event flag. `"unverified"` is a temporary state, not a detector.
- `invariants/milestones.py` (or a new `invariants/detectors.py` in `run_all`): for each campaign goal with `detector == "unverified"` or a map detector whose note says
  "talk/give/get", emit a WARN `Finding` "chain blocker: <goal> has no verified detector"; if it is the first unmet goal of a swarm run
  (`runs/segments.json` stats) escalate to ERROR so it shows in the swarm log instead of passing through `infer_unverified`.
- Add `tools/ram_discover.py --goal <id> --from <state> --script <buttons>` to mine a flag the way this PR did (diff 0xD747-0xD87B across a scripted replay, replay twice, write `evidence`).
- Remaining unverified today: `rival_ss_anne` (battle-won flag; mine from the 2F rival fight the same way). Reached-by-map goals worth re-mining: Fan Club chairman, Oak's aide, Bill.

## Order of work
(1) `unlocks.py` + `agent_capabilities` (small, unblocks selection) -> (2) invariant checker + `rival_ss_anne` flag -> (3) tree tile verification + `walk_grid(unlocked)` ->
(4) `cut_tree` behaviour with a headless test from a Vermilion state with a Cut-capable member -> (5) goal data + segment start states.
