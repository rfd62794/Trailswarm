# PokeAgent: brain tools - a Model Map inspector and a safe "scalpel" for editing what the agent learned

**Read first:** `docs/superpowers/specs/2026-11-05-viewer-and-hybrid-design.md` sections 4 and 5.
**Depends on:** `World_Legend_And_Ledges_Directive.md` and `Viewer_Window_Directive.md` merged
(`explorer/legend.py`, `explorer/tilekind.py`, `viewer/ui/theme.py`). If missing, stop and write that in the
Status row. **Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-05): "Can you build a Tool for directly looking at the Model Map, as well as the Scalpel for
Brain Surgery as it were?" Everything the agent knows lives in `runs/maps.json` (per map: `visited`, `blocked`,
`warps`, `warp_cand`, `warp_taken`, `jumps`, `fails`, `interactions`, `npcs`, `encounters`, `outcomes`, `items`;
globally `tile_types`, `grass_ids`, `bad_warps`, battle lessons, beats, demos) and in the RL Q-tables
(`runs/**/q_*.json`, read/written by `pokeagent.qmodels.load_model(path, schema, actions)` / `save_model`;
`tools/qview.py` is today's command-line editor). Today the only way to inspect or fix a wrong fact (a false
wall, a forced-walk "warp", a mislabelled trainer) is to hand-edit JSON while hoping no agent overwrites it.

**The overwrite problem:** every running agent holds `maps.json` in memory and rewrites the whole file on
`MapMemory.save()` (`src/pokeagent/explorer/memory.py`), and the swarm merges copies back (`tools/swarm.py`
`merge_memory`). A direct edit is silently reverted by the next save. The existing fix for one case is the
`bad_warps` tombstone list, applied on load and in the merge. This directive generalises that.

## 2. Scope (in order)

1. **Edit journal** `src/pokeagent/explorer/edits.py`: `runs/memory_edits.jsonl`, one JSON line per edit
   `{"ts", "op", "map", "key", "value", "note", "by"}`. Ops: `wall_add`, `wall_remove` (key `x,y,DIR`),
   `warp_remove` (adds to `bad_warps`), `warp_add` (value `[m,x,y]`), `jump_add`, `jump_remove`,
   `interaction_clear` (key `x,y,FACING`), `npc_trainer` (value bool), `npc_forget`, `tile_kind` (key `x,y`,
   value a legend kind - an override that `tilekind.classify` honours first), `visited_clear`.
   `apply(data, edits) -> data` is pure and idempotent. `MapMemory` applies the journal on load **and again
   immediately before every save**; `swarm.merge_memory` applies it after merging. So an edit made while agents
   run survives their next save.
2. **Live reload command**: control-server command `reload_edits` (no args) - handlers in explore_demo call
   `MapMemory.apply_edits()` so a running agent picks an edit up at once.
3. **Model Map inspector** `src/pokeagent/viewer/brain/` (Dear PyGui, same theme as the viewer), started by
   `pokeagent brain [--maps runs/maps.json]` and `tools/brain.py`:
   - Map list (id, name from `pokeagent.names` when known, tiles known, warps, items) with search.
   - Tile grid of the selected map: one cell per known tile, glyph + colour from `legend`, overlays toggled from
     a bar: visit heat, encounters, goal outcomes (choose a goal stage: colour = progress rate), fails.
   - Click a tile -> inspector panel listing every fact about it (visits, blocked edges, warps with
     destinations as clickable links to that map, jumps, interactions with text, NPC/trainer/item, outcomes per
     goal stage, journal edits touching it).
   - World graph tab: maps as nodes, warps as edges (simple force or grid layout), click to open a map.
4. **Scalpel** (inside the inspector): every editable fact in the tile panel has an action (toggle wall per
   direction, remove/add warp, remove jump, clear interaction, mark/unmark trainer, override tile kind, clear
   visits). Each action asks for a one-line note, writes a journal entry (never edits maps.json directly), shows
   it as pending until an agent or the inspector's "Apply to file" (only when no agent is registered alive in
   `runs/agents/`) folds it in. "Apply to file" first copies `maps.json` to
   `runs/backups/maps-<timestamp>.json`. An "Undo" on a journal entry appends the inverse op.
5. **Q-table tab** (scalpel for RL brains): open a `q_*.json`, list states by visit count / value spread
   (reuse `pokeagent.qdecode` for readable state names), edit one action value; writes go through `save_model`
   after copying the file to `runs/backups/`. Port `qview.py --patch-save` as a one-click "never A on SAVE"
   preset.
6. Viewer integration: a "Brain" button in the V2 control bar opens the inspector on the focused agent's map
   and tile.

## 3. The work

Keep `apply`, overlay computations and the tile-fact listing pure (in `viewer/brain/model.py`), tested without
a display; Dear PyGui code thin in `viewer/brain/ui.py`.

## 4. What NOT to do

- Never write `maps.json` while a registered agent is alive; never write a Q-table without a backup copy.
- Do not change learning rules; edits are data, applied by the journal.
- No new dependencies; no module over 300 lines.

## 5. Verification

- `uv run pytest -q` green (paste before/after).
- Tests: every journal op applies and is idempotent; inverse ops undo; `MapMemory.save()` re-applies the
  journal (simulate an agent holding stale data that would revert an edit - the edit survives); `merge_memory`
  applies it; `tile_kind` override wins in `classify`; tile-fact listing on a fixture map; overlay values;
  "Apply to file" refuses while a live registry entry exists and makes a backup otherwise; Q edit backs up then
  writes. UI smoke under `dpg.create_context()` without a viewport (skip with a reason if impossible).
- `uv run python -c "from pokeagent.cli import main; main(['brain', '--help'])"` prints usage.
- Do NOT run `uv run pokeagent ...` or open a window. The controller opens it live on the laptop.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-brain-tools-directive`. Never commit to `main`.
- Create no scratch or debug files; if unavoidable, under `.devin-scratch/` and it stays.

## 7. Completion criteria

- [ ] Edit journal applied on load, before save, and in the swarm merge; `reload_edits` command
- [ ] `pokeagent brain`: map list, tile grid with overlays, tile inspector, world graph
- [ ] Scalpel actions -> journal; Apply to file with backup and live-agent refusal; Undo
- [ ] Q-table tab with backup-before-write and the SAVE preset
- [ ] Tests in section 5 pass; `uv run pytest -q` green (paste the tail)
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts, a description of each tab, and anything that did not fit.
