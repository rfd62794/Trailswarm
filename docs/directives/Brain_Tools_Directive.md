# PokeAgent: brain tools for Claude - inspect the whole model, and a safe "scalpel" (CLI + MCP first)

**Read first:** `docs/superpowers/specs/2026-11-05-viewer-and-hybrid-design.md` sections 4 and 5, and
`docs/superpowers/specs/2026-11-05-atlas-overlay-note.md` (where this goes next).
**Depends on:** `World_Legend_And_Ledges_Directive.md` merged (`explorer/legend.py`, `explorer/tilekind.py`).
If missing, stop and write that in the Status row. **Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-05): "tools for you [Claude] to inspect the model in full, and perform surgery when necessary" -
and later a UI that overlays the model on a real view of the game. This directive is phase 1: **machine-facing
tools Claude can call** (CLI with JSON output + MCP tools), plus the edit journal that makes surgery safe.
Phase 2 (a visual inspector in the viewer) and phase 3 (overlay on ROM-rendered maps) build on the same pure
functions and are separate directives.

Everything the agent knows lives in `runs/maps.json` (per map: `visited`, `blocked`, `warps`, `warp_cand`,
`warp_taken`, `jumps`, `fails`, `interactions`, `npcs`, `encounters`, `outcomes`, `items`; globally
`tile_types`, `grass_ids`, `bad_warps`, battle lessons, damage tables, beats, demos) and in RL Q-tables
(`runs/**/q_*.json` via `pokeagent.qmodels.load_model(path, schema, actions)` / `save_model`; `tools/qview.py`
is the current CLI editor with `--patch-save`).

**The overwrite problem:** every running agent holds `maps.json` in memory and rewrites the whole file in
`MapMemory.save()` (`src/pokeagent/explorer/memory.py`), and the swarm merges copies back (`tools/swarm.py`
`merge_memory`). A direct edit is reverted by the next save. The existing fix for one case is the `bad_warps`
tombstone list applied on load and in the merge; this directive generalises it.

## 2. Scope (in order)

1. **Edit journal** `src/pokeagent/explorer/edits.py`: `runs/memory_edits.jsonl`, one JSON line per edit
   `{"id", "ts", "op", "map", "key", "value", "note", "by"}`. Ops: `wall_add`, `wall_remove` (key `x,y,DIR`),
   `warp_remove` (also appends to `bad_warps`), `warp_add` (value `[m,x,y]`), `jump_add`, `jump_remove`,
   `interaction_clear` (key `x,y,FACING`), `npc_trainer` (value bool), `npc_forget`, `tile_kind` (key `x,y`,
   value a legend kind; `tilekind.classify` honours overrides first), `visited_clear`, `undo` (value = id of the
   edit to invert). `apply(data, edits) -> data` is pure and idempotent. `MapMemory` applies the journal on load
   **and again immediately before every save**; `swarm.merge_memory` applies it after merging.
2. **Live reload**: control-server command `reload_edits` (no args); explore_demo's handler calls
   `MapMemory.apply_edits()`.
3. **Brain query library** `src/pokeagent/brain/` (pure, no UI): `maps_summary(data)`, `map_view(data, map_id,
   overlay)` (rows of legend glyphs + per-tile overlay values: visits, encounters, fails, outcome progress for a
   goal stage), `tile_facts(data, map_id, x, y)` (every fact about one tile incl. journal edits touching it),
   `find(data, query)` (e.g. kind=trainer, text contains, item name, warps to map N), `diff(a, b)` (what changed
   between two maps.json snapshots - for "what did this run learn"), `lessons(data, kind)` (battle/type/damage
   tables summarised), `q_summary(path)` and `q_state(path, obs)` (via `qmodels` + `qdecode`).
4. **CLI** `pokeagent brain <cmd>` and `tools/brain.py` with JSON output by default (`--text` for humans):
   `maps`, `map <id> [--overlay visits|encounters|fails|outcomes:<goal>]`, `tile <map> <x> <y>`, `find ...`,
   `diff <a.json> <b.json>`, `lessons <kind>`, `edit <op> <map> <key> [--value ...] --note "..."`,
   `edits [--map N]`, `undo <id>`, `apply --backup` (fold the journal into maps.json: refuses while any registry
   entry in `runs/agents/` is alive; copies maps.json to `runs/backups/maps-<ts>.json` first), `q <path>
   [--obs ...] [--set OBS ACTION VALUE]` (backup copy before any write; `--patch-save` preset ported from qview).
5. **MCP tools** in `src/pokeagent/mcp_server.py` (same functions, JSON results): `brain_maps`, `brain_map`,
   `brain_tile`, `brain_find`, `brain_diff`, `brain_lessons`, `brain_edit`, `brain_undo`. They read
   `runs/maps.json` from the repo root (or a `maps_path` argument) and never write it directly - edits go to the
   journal.

## 3. The work

All logic in `pokeagent.brain` and `pokeagent.explorer.edits` is pure and tested; CLI and MCP are thin wrappers.
Output stable JSON (sorted keys) so Claude can diff results between calls.

## 4. What NOT to do

- Never write `maps.json` while a registered agent is alive; never write a Q-table without a backup copy.
- Do not change learning rules; edits are data applied by the journal.
- No UI in this directive (phase 2). No new dependencies; no module over 300 lines.

## 5. Verification

- `uv run pytest -q` green (paste before/after).
- Tests: every journal op applies and is idempotent; `undo` inverts; `MapMemory.save()` re-applies the journal
  (simulate an agent holding stale data that would revert an edit - the edit survives); `merge_memory` applies
  it; `tile_kind` override wins in `classify`; `map_view` / `tile_facts` / `find` / `diff` / `lessons` on a
  fixture; `apply` refuses while a live registry entry exists and backs up otherwise; Q `--set` backs up first.
- `uv run python -c "from pokeagent.cli import main; main(['brain', '--help'])"` prints usage; MCP tools are
  callable directly as functions in tests.
- Do NOT run `uv run pokeagent ...` (sandbox refuses the entry point).

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-brain-tools-directive`. Never commit to `main`.
- Create no scratch or debug files; if unavoidable, under `.devin-scratch/` and it stays.

## 7. Completion criteria

- [ ] Edit journal applied on load, before save and in the swarm merge; `reload_edits`
- [ ] `pokeagent.brain` query library; `pokeagent brain` CLI (JSON); MCP brain_* tools
- [ ] `apply` with backup and live-agent refusal; Q edits with backup
- [ ] Tests in section 5 pass; `uv run pytest -q` green (paste the tail)
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts, one example JSON output per CLI command, anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-brain-tools-directive |
| Base branch | - |
| Base commit | d88defb92bc8de47bf77526586df27c56448a4db |
| Model | swe-2-flash-max |

**Status log**
- 2026-11-05 20:16 · robert-claude-laptop · none → Queued — Robert approved all 2026-11-05 (live surgery tools for Claude); dep World Legend merged
- 2026-11-05 20:16 · robert-claude-laptop · Queued → Approved — lint override: greenfield directive: cited new paths are files it creates; dep merged
- 2026-11-05 20:16 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-brain-tools-directive; lane=explicit; model=swe-2-flash-max; persona=steady-builder; agent_id=01M6Q6W56MBEFZ7JEWAC7DG7H4
<!-- queue:end -->
