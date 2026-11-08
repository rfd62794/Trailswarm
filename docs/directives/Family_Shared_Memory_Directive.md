# PokeAgent: shared gen1-pokemon family memory - Red and Blue learn into one store, each fact records who saw it, and a disagreement goes to the observing game's overlay

**Size:** M. **Assignee:** devin.

**Depends on the amended `Game_Namespaced_Stores_Directive.md` (plan phase 4) being merged, and on `Game_Compat_Check_Directive.md` being merged** (this directive imports its ledge classifier, the module `ledges.py` in the `compat` package, missing on main until that directive merges). Start from a main where the amended phase 4 has added the `stores.py` module of the `game` package (missing before it merges) with `store_path(..., scope=...)` and `LEGACY_FAMILY`. If `git grep -n -e "def store_path" -e "def classify_wall" -- src` finds fewer than two lines at the start, stop and write that in the Status row.

## 1. Why this exists

Owner direction, settled 2026-11-08: "we want to try to build a combined or shared memory for red and blue, we want the individuality minimal where possible, and plan for yellow after confirming cross compatibility." The model is assumed compatible only with Generation 1 Pokemon, so the memory family is `gen1-pokemon` (`LEGACY_FAMILY`): Red and Blue now, Yellow only if it passes the compat check. A game declares its family in `GameSpec.memory_family`; Mario, Kirby and the rest are simply not in it.

Phase 4 routes the paths: Red and Blue both resolve `runs/maps.json` to the legacy root. That alone is not enough, because the merge in `tools/swarm_merge.py` has no idea two games exist. This directive adds the memory semantics.

Measured 2026-11-08 comparing Red's `runs/maps.json` with a Blue run's `maps.json` (15 maps up to Viridian Forest; the Blue run had human interaction, so this is early evidence):

- 2,170 of 2,203 Blue tiles already known to Red; 21 warps in common, none different; 35 of 35 stationary NPCs in the same place.
- 210 of 2,127 Red walls lie between two tiles Blue stood on (126 on Route 1, which has ledges). Cause UNCONFIRMED: one-way ledges or transient NPCs are the guess.
- A Blue-built kb matched Red's except wild encounters (34 of 57 maps differ) and unexplained differences in `map_trainers` at unused ids 105-117 and 231.
- Blue's real RAM reads matched Red's map through the rival battle. Badges, wild battles and later maps are UNMEASURED.

Real shapes in this repo today (pasted because you cannot read outside the worktree; they were read from `runs/maps.json` and the code on 2026-11-08):

A map record in `runs/maps.json` (`doc["maps"][str(map_id)]`), keys seen: `blocked, demos, encounters, fails, interactions, jumps, last_seen, npcs, outcomes, visited, warp_cand, warp_taken, warps`. Examples:

```
"visited": {"11,35": 8388, "11,34": 7552}          # "x,y" -> visit count
"warps":   {"11,35,DOWN": [0, 11, 0]}               # "x,y,BUTTON" -> [dest_map, dest_x, dest_y]
"blocked": ["10,28,UP", "9,28,UP", "9,31,DOWN"]     # list of "x,y,BUTTON": pressing BUTTON on tile (x,y) does not move you
"jumps":   {"5,26,DOWN": [5, 28]}                   # "x0,y0,BUTTON" -> [landing_x, landing_y]: a ledge hop of 2 tiles
```

How a ledge becomes a wall, from `MapMemory.learn` in `src/pokeagent/explorer/memory.py`:

```python
if m1 == m0 and exact:   # the press moved us EXACTLY 2 tiles in a straight line
    self.m(m0).setdefault("jumps", {})[key] = [x1, y1]          # key = f"{x0},{y0},{button}"
    back = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}[button]
    bk = f"{x1},{y1},{back}"                                    # the LANDING tile cannot go back the way it came
    if bk not in blocked:
        blocked.append(bk)
```

and an ordinary wall (same function): a press that moves nothing, not `npc_ahead`, failed twice (`fails[key] >= 2`) or `confirmed`, appends `f"{x0},{y0},{button}"` to `blocked`. A later press that does move clears it ("moved - cleared a false wall"). `explorer/tilekind.py` `ledge_dir(memory_map, x, y)` marks the tile one step from a jump's start toward its landing as the ledge tile.

The merge, from `tools/swarm_merge.py` `merge_memory(dst, src, edits=None)` (306 lines):

```python
for k in s.get("blocked", []):
    if k not in d["blocked"]:
        d["blocked"].append(k)          # union, never removes
d["warps"].update(s.get("warps", {}))   # last writer wins: a disagreeing warp OVERWRITES
...
jm.update(s.get("jumps", {}))           # union; last writer wins on a clashing key
npcs: positions are max-merged per position; cur["moves"] = len(cur["positions"]) > 1; cur["last"] = e.get("last", cur.get("last"))
```

`merge_file_into(shared, own)` (swarm_merge.py:298) holds `merge_lock(shared)`, loads the shared doc, calls `merge_memory(dst, json.loads(own.read_text()), edits=...)` and writes atomically. An agent's own file is seeded from the shared file at `tools/swarm_continuous.py:161` (`shutil.copy(src, cfg["own"])`). `MapMemory` itself is at 299 lines (ceiling 300): do NOT edit `explorer/memory.py` or `explorer/context.py`.

Two consequences the design depends on:

1. A visited-both-ends test is NOT proof of a disagreement. Standing on both tiles of a blocked edge proves nothing about crossing the edge (you can reach both by another route). The only direct proof of a crossing is a `paths` edge (`m["paths"]["x,y,BUTTON"]["to"]`), and the explore demo runs with `record_paths=False`, so it is usually absent.
2. A ledge can wall an edge that neither game has jumped yet: `blocked` holds `9,28,UP` and `10,28,UP` but `jumps` only records some columns of the same ledge row.

## 2. Scope

New package `src/pokeagent/family/` (each module single-purpose, under 150 lines, none over 600 anywhere), `tools/swarm_merge.py` (one hook, at most 12 added lines), `tools/swarm_continuous.py` (one hook, at most 6 added lines), tests, and `docs/KNOWLEDGE.md`.

1. `src/pokeagent/family/__init__.py` <!-- new: src/pokeagent/family/__init__.py --> - re-exports `fold_agent_memory`, `effective_memory`, `family_active`.
2. `src/pokeagent/family/active.py` <!-- new: src/pokeagent/family/active.py --> - `family_active(game, shared_path) -> bool`.
3. `src/pokeagent/family/provenance.py` <!-- new: src/pokeagent/family/provenance.py --> - read, update and write the provenance sidecar.
4. `src/pokeagent/family/disagree.py` <!-- new: src/pokeagent/family/disagree.py --> - find the facts in an agent's file that contradict the shared doc.
5. `src/pokeagent/family/overlay.py` <!-- new: src/pokeagent/family/overlay.py --> - read and write a game's overlay file; `effective_memory(shared, overlay)`.
6. `src/pokeagent/family/fold.py` <!-- new: src/pokeagent/family/fold.py --> - `fold_agent_memory(...)`, the single entry the merge calls.
7. `src/pokeagent/family/report.py` <!-- new: src/pokeagent/family/report.py --> - the disagreement report (JSON lines plus one summary line).
8. `src/pokeagent/family/kb_overlay.py` <!-- new: src/pokeagent/family/kb_overlay.py --> - build and read the per-game kb overlay.
9. `tools/swarm_merge.py` and `tools/swarm_continuous.py` - the two hooks.
10. `docs/KNOWLEDGE.md` - a paragraph.

## 3. The work

### Files and shapes (decided)

Every file below is located relative to the `shared` path the merge was called with (`shared.parent`), never relative to the working directory and never through a `store_path` call made inside these modules, so a test that passes a `tmp_path` shared file writes only under `tmp_path`. In production `shared` is the real shared maps file, which `store_path` already resolved for the family at the call site:

- Shared doc: the `shared` argument itself (the existing maps file, unchanged schema; gitignored, so missing in a fresh worktree).
- Provenance: `family_provenance.json` in `shared.parent` (a data file the run creates, missing until the first non-founder fold). Shape: `{"version": 1, "facts": {"<map_id>/<section>/<key>": ["pokemon-blue", ...]}}` where section is one of `visited, warps, blocked, jumps, npcs`. The list is the games that OBSERVED the fact. A fact with NO entry is attributed to the founding game `pokemon-red` (everything that predates this directive). Adding an observer to an absent entry yields `["pokemon-red", "<game>"]` only when the fact was already in the shared doc before this fold; a fact new to the shared doc gets just the observing game.
- Overlay: `overlay/<game.key>/maps.json` under `shared.parent`. Same schema as `maps.json`, holding ONLY the facts that game disagrees on, plus one extra list per map, `blocked_not`: edges the shared doc calls blocked that this game has proof are open. Created on first disagreement, never otherwise.
- Disagreement report: `family_disagreements.jsonl` in `shared.parent` (also created by the run), one JSON object per line: `{"ts", "game", "map", "section", "key", "shared": <value>, "overlay": <value>, "kind": "<kind>"}`.

### When the family code runs: Red-only stays unchanged

`family_active(game, shared_path)` is True iff `game.memory_family == LEGACY_FAMILY` AND (`game.owns_legacy_paths` is False OR the provenance file in `shared.parent` already exists). So a Red-only repo never creates a provenance, overlay or report file, `merge_file_into` takes the exact old code path, and the bytes of `runs/maps.json` are identical to today's: `tests/test_golden_red.py` hash must not change. The first time any other game folds, the provenance file is created and from then on Red folds also record provenance. A game whose family is not `gen1-pokemon` never touches any of this (it has its own family root).

### Disagreement rules, per section (decided)

`find_disagreements(shared_map, agent_map, game, mid)` returns the agent facts that contradict the shared doc. Nothing else is a disagreement; counters (`visited`, `encounters`, `fails`, `warp_taken`) are observation counts and keep max-merge.

| Section | Disagreement | Goes to |
|---|---|---|
| `warps` | same `"x,y,BUTTON"` key, different `[map,x,y]` | the agent's value goes to its overlay; the shared value stays |
| `jumps` | same key, different landing | same |
| `npcs` | same npc key, both records have `moves` false, and `last` differs | same |
| `blocked` | see the wall section below | see below |
| `visited`, `interactions`, `encounters`, `tile_types` | never a disagreement | merged as today. Dialogue text difference between versions is UNMEASURED; do not handle it here |

Everything that is not a disagreement is passed to the existing `merge_memory(dst, filtered_src)` unchanged, so all current merge rules (max, union, tombstones, edits journal) keep working. `fold_agent_memory` therefore (1) finds disagreements, (2) removes them from a COPY of the agent doc, (3) calls the existing `merge_memory` on that copy, (4) writes the removed facts to the game's overlay, (5) updates provenance for every fact the agent file contained, (6) appends the report lines. Idempotent: folding the same agent file twice changes nothing and writes no duplicate report line (key the report on `(game, map, section, key, overlay value)`).

### Ledge and one-way walls (decided; how the code can tell, and where it cannot)

A wall edge `"x,y,BUTTON"` in the shared doc that the agent's file does not carry is NOT a disagreement just because both end tiles are walkable. The classifier in the `ledges.py` module of the `compat` package (from `Game_Compat_Check_Directive.md`) labels each blocked edge of one map document, in this order:

1. `ledge_exact`: the edge equals the derived back-edge of a recorded jump: for each `"x0,y0,B"` in `jumps` with landing `[x1,y1]`, the edge `f"{x1},{y1},{opposite(B)}"`. This is certain: it is the same rule `learn()` uses to create it.
2. `ledge_row`: the edge's direction is the opposite of a recorded jump's direction `B` and its source tile lies on the same row (for UP/DOWN jumps) or column (for LEFT/RIGHT) as that jump's landing, in the same map. This is a HEURISTIC (it covers the unjumped columns of a ledge row, such as `9,28,UP` beside `5,28`). It can be wrong on a map with two different ledges in one row. It is labelled as a heuristic everywhere it appears.
3. `plain`: anything else.

What the family code does with them: `ledge_exact` and `ledge_row` edges are one-way terrain, never evidence against a wall, and never moved to an overlay. For a `plain` blocked edge the agent's file lacks, the only PROVEN contradiction is a `paths` crossing: the agent's `m["paths"]` has `"x,y,BUTTON"` whose `to` is the tile one step in BUTTON's direction in the same map. Then the edge goes into the agent's overlay `blocked_not` (the shared wall stays; the other game still has it) and a report line of kind `wall_open` is written. Without a `paths` crossing it cannot be proved: the edge stays in the shared doc exactly as the union merge does today, and a `wall_suspect` report line is written ONLY when the agent stood on both end tiles (`visited` contains both) and the edge classifies `plain`. What it cannot tell, stated plainly: a transient NPC that was standing in the way when the wall was confirmed also produces a `plain` wall with both ends walkable; the code cannot distinguish that from a game difference, so those are reported as suspects and are not acted on. The 126 Route 1 candidates measured on 2026-11-08 are expected to land mostly in `ledge_exact` and `ledge_row`; the exact split is UNMEASURED and is part of the report.

A wall the AGENT carries and the shared doc lacks is not a disagreement either: it goes into the shared doc by the existing union (provenance records only the agent's game), exactly as a wall learned by one Red agent does today.

### Reads: overlay first, then shared

`effective_memory(shared: dict, overlay: dict | None) -> dict` returns a deep copy of `shared` where, per map: `warps`, `jumps` and `npcs` entries in the overlay replace the shared ones; `blocked` is `(shared blocked + overlay blocked) minus overlay blocked_not`; nothing else changes. With `overlay` None or empty it returns an equal copy (a test asserts equality of `json.dumps(..., sort_keys=True)`).

The read hook is the seeding copy at `tools/swarm_continuous.py:161`: when `family_active(game, shared)` the agent's own file is written from `effective_memory(shared, overlay_of(game))` instead of `shutil.copy`. When not active the line behaves exactly as today. `MapMemory` is NOT edited (it is at the size ceiling). Any other consumer that reads `runs/maps.json` directly (the viewer, `statemeta.tile_snapshot`) keeps reading the shared doc; list each such reader found by `git grep -n "maps.json" -- src tools` in the Report with a one-line decision, and do not change them.

### Both ways

Learning from Blue flows into the same shared store as Red: both games' agents go through `merge_file_into`, which calls `fold_agent_memory` with the running game (`resolve_game(None)`, so `POKEAGENT_GAME` is honoured). A test folds a Blue-labelled agent doc and then a Red-labelled one into the same shared doc and asserts each sees the other's new facts, each fact's provenance lists the right games, and a Red-only fact is not removed by a later Blue fold.

### kb overlay

`kb_overlay.build_overlay(base: dict, game_kb: dict) -> dict` returns only the top-level keys of `game_kb` that differ from `base` and, for dict-valued keys, only the entries that differ (so a wild-encounter table stores only the maps that differ). `kb_overlay.read(base, overlay)` returns the base with the overlay applied (overlay entries replace base entries). Path: `overlay/<game.key>/rom_tables.json` under the directory of the base kb file passed in (an explicit `base_path` argument, never a `store_path` call). This module is key-agnostic on purpose: the key names for wild encounters and `map_trainers` are NOT pasted here because they were not verified in this repo, so do not hard-code them; tests use synthetic dicts. It also writes `kb/overlay/<key>/disagreements.json` listing the changed top-level keys and entry counts, so the `map_trainers` ids 105-117 and 231 differences are visible and not silently adopted. Two rules follow. (a) A Blue kb rebuild writes ONLY to the overlay path above; no code in this directive or the Blue phase may write the shared base kb file, and a test asserts that `build_overlay` plus its writer leave a synthetic base file byte-identical. (b) Wiring `knowledge/kb.py` to read the overlay is DEFERRED to full Blue support (plan phase 7): `ROM_KB` is gitignored data produced from a local ROM, and `knowledge/kb.py` is a 3-line module read at import. Until phase 7 lands, a Blue process reads the shared base tables, so its wild-encounter and `map_trainers` data are Red's, which the 2026-11-08 comparison showed differ (34 of 57 maps for wild encounters). Say this in the Report and in `docs/KNOWLEDGE.md`; the module and its tests are the deliverable here.

## 4. What NOT to do

- Do not edit `src/pokeagent/explorer/memory.py`, `explorer/context.py` or any file at its size ceiling.
- Do not change the schema of `runs/maps.json`, `bandit.json`, `novelty.json` or checkpoint files, and do not add a game key or provenance inside them.
- Do not create any file under `runs/` or `kb/` when only Red has ever written. `family_active` is the gate; a test proves it.
- Do not move a fact out of the shared doc into an overlay without a rule from the table; unproven walls stay shared.
- Do not treat both-ends-walkable as a disagreement. Do not infer a crossing from `visited`.
- Do not hard-code kb key names, and do not touch `roms/`, `baselines/` or any ROM data. Never state where a game copy came from.
- Do not register Blue or Yellow, add real-time input, or edit `game/` beyond importing from it.
- Do not edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file.
- No file over 600 lines; each new module single-purpose; no new dependency; no scratch files outside `.devin-scratch/`.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
uv run pytest -q tests/test_family_active.py tests/test_family_provenance.py tests/test_family_disagree.py tests/test_family_overlay.py tests/test_family_fold.py tests/test_family_kb_overlay.py tests/test_swarm_merge_loops.py tests/test_swarm_merge_trainers.py
```
Expected: `Python 3.12.x`; all pass. If `tests/test_swarm_merge.py` does not exist, say so in the Report and run the swarm tests that `git grep -l "merge_memory" -- tests` names.

```
uv run pytest -q
git diff --stat main -- src/pokeagent/explorer tools/golden_trace.py tests/test_golden_red.py
```
Expected: no new failures against main's tail (ROM-gated tests skip here); the diff stat prints nothing.

```
wc -l src/pokeagent/family/*.py tools/swarm_merge.py tools/swarm_continuous.py
```
Expected: no file over 600 lines.

Claude's verify lane (ROM present, fresh worktree of the PR head with `roms/` and `baselines/` junctioned): `uv run pytest -q tests/test_golden_red.py` must pass with the recorded hash unchanged. Report it as NOT run in the Devin worktree.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here; if something expected is missing, stop and write that in the Status row.
- Use `uv run` and Python 3.12 only. Tests are synthetic and headless: hand-built dicts shaped like section 1, `tmp_path` for every file, no ROM, no emulator, no real `runs/` or `kb/`.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the `directive/pokeagent-family-shared-memory-directive` branch; commit as you go.
- Status row done means `Review` with a pushed branch; leave the rest to the pipeline.
- If a tool call is genuinely blocked, stop and write why in the Status row.

## 7. Completion criteria

- [ ] `family_active` is False for Red when no provenance file exists, True for a non-founder family member, True for Red once the provenance file exists, and False for a game whose `memory_family` is not `gen1-pokemon`. <!-- test: tests/test_family_active.py --> <!-- new: tests/test_family_active.py -->
- [ ] Red-only: folding a Red agent doc with the family inactive creates no file and leaves the shared doc byte-identical to the old `merge_memory` result. <!-- test: tests/test_family_fold.py --> <!-- new: tests/test_family_fold.py -->
- [ ] Provenance: a new Blue fact lists `["pokemon-blue"]`; a Blue fact already in the shared doc lists `["pokemon-red", "pokemon-blue"]`; an unrecorded fact is read as Red's. <!-- test: tests/test_family_provenance.py --> <!-- new: tests/test_family_provenance.py -->
- [ ] A differing warp, jump landing and stationary NPC position each go to the folding game's overlay, leave the shared value in place, and write one report line each; a moving NPC and a visit-count difference are not disagreements. <!-- test: tests/test_family_disagree.py --> <!-- new: tests/test_family_disagree.py -->
- [ ] Wall handling: a `ledge_exact` edge and a `ledge_row` edge are never moved and never reported as suspects; a `plain` wall with a `paths` crossing goes to `blocked_not` with kind `wall_open`; a `plain` wall with both ends visited and no crossing stays shared and is reported as `wall_suspect`; a `plain` wall with an end not visited is not reported. <!-- test: tests/test_family_disagree.py -->
- [ ] `effective_memory` applies warps, jumps, npcs and `blocked_not`; with no overlay it equals the shared doc. Reads check the overlay first, then shared. <!-- test: tests/test_family_overlay.py --> <!-- new: tests/test_family_overlay.py -->
- [ ] Both ways: a Blue fold then a Red fold into one shared doc leaves both games' new facts present with correct provenance, and folding the same file twice changes nothing. <!-- test: tests/test_family_fold.py -->
- [ ] `build_overlay` keeps only differing entries and `read` reapplies them; a synthetic base and game kb differing in one map's entries and one unrelated key round-trip, and writing the overlay leaves a synthetic base kb file byte-identical. <!-- test: tests/test_family_kb_overlay.py --> <!-- new: tests/test_family_kb_overlay.py -->
- [ ] The two hooks add at most 12 and 6 lines, behave as before when the family is inactive, and `git diff --stat main` shows no change under `src/pokeagent/explorer/`. <!-- test: tests/test_swarm_merge.py -->
- [ ] No file over 600 lines.

## 8. Report

Findings first: the observed split of `ledge_exact`, `ledge_row`, `plain` wall counts on any synthetic fixture you built (state clearly that no real data was used), every reader of `runs/maps.json` found with your decision, whether `tests/test_swarm_merge.py` existed, and any rule above you could not implement as written. Then the command tails from section 5, the diff stat and each new file's line count. State plainly that the golden test and any real-data comparison were NOT run.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.
- Do not touch `roms/`, `baselines/` or ROM data, and do not state where a game copy came from.

## Sandbox needs

- Read(tools/swarm_merge.py)
- Read(tools/swarm_continuous.py)
- Read(src/pokeagent/compat/ledges.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git diff)
- Exec(git grep)
- Exec(wc)
