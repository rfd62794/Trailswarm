# Trailswarm: label every maps.json field as shareable fact or private state, and add an audit and a non-destructive cleaner

**Size:** M. **Assignee:** devin.

## 1. Why this exists

Red's own `runs/maps.json` (gitignored, so missing in a fresh worktree; do not look for it) was audited on 2026-11-08. Counts only, no dialogue:

- 16,476 interaction entries, 3,985 with text. About 3,209 of those match a rough battle-text pattern, 672 a menu or save-screen pattern.
- 756 spots were pressed 100 or more times.
- 8 entries carry PC text but are not typed `pc`. 20 entries have conflicting `type_votes`.
- 10 interaction entries and 14 NPC `results` carry `done` flags. `done` is playthrough state, not a world fact: an NPC `results` with `type` giver and `done` true (slot2 at (6,3) on map 40) makes `retalk_veto` refuse the starter ball, and a ported demo on map 38 achieving `left_house` fires on arrival at (0,2) through `ReplayBeat`, wasting steps.
- Map 38: `0,2,UP` is typed `pc` (count 1043) with Mom's dialogue as its text; a bogus `0,2,DOWN` (count 338) has the text "... turned on | the PC.". That is contradictory evidence about which facing is the PC.

Red's memory with all of this, untouched, never finished the potion goal in 600 steps, while cold runs with no memory did it by step 35. Before any of this memory is shared between agents or published, it needs a written line between world facts, playthrough state and guesses, a way to measure how dirty a file is, and a way to clean it that never edits the original and loses nothing silently. A separate directive (`Interaction_Text_Capture_Fix_Directive.md`) stops new bad notes at the source. This directive depends on nothing in it and may be run in any order; the two share an idea (battle and menu lines do not belong in a note), so a regex list may be repeated here, but keep the two independent and do not import from the other's new files.

### The audit logic to port (pasted, because you cannot read the original)

This is the throwaway audit that produced the numbers above. Port its checks into a pure module; do not copy its `sys.argv`/`print` style.

```python
BATTLE = re.compile(r"\bwild\b|go! |fainted|got away|exp\. points|sent\s*\|?\s*out|defeated|used [a-z]+!", re.I)
MENU = re.compile(r"pok.dex \||badges|>fight|item run|now saving|saved\s*\|?\s*the game", re.I)

def text_of(e):
    return " ".join([e.get("text") or ""] + list(e.get("pages") or []))

# per map m in data["maps"], per (key, e) in m["interactions"] ; key is "x,y,FACING"
#   not a dict                                  -> "interaction_not_a_dict"  (skip it)
#   text_of(e).strip() == ""                    -> "interaction_no_text"; else "interaction_with_text"
#   BATTLE.search(text)                         -> "text_has_battle_lines"
#   MENU.search(text)                           -> "text_has_menu_lines"
#   e.get("done")                               -> "per_run_flag_done"
#   e.get("type") == "pc" and "pc" is not a word in text.lower() -> "type_pc_but_no_pc_in_text"
#   "turned on" in t.lower() and "the pc" in t.lower() and e.get("type") != "pc" -> "pc_text_but_type_not_pc"
#   (e.get("count") or 0) >= 100                -> "pressed_100_plus_times"
#   len(e.get("type_votes") or {}) > 1          -> "conflicting_type_votes"
# per tile (x,y) of a map: if two or more facings hold non-empty text and the texts repeat -> "same_text_on_several_facings_of_a_tile"
# per (sid, n) in m["npcs"], n a dict: r = n.get("results") or {}
#   r.get("done")                               -> "npc_results_done"
#   BATTLE.search(text_of(r))                   -> "npc_text_has_battle_lines"
#   not n.get("moves") and len(n.get("positions") or {}) > 1 -> "nonmoving_npc_many_positions"
# m["demos"] is a list (or a dict of demos): count them.
# top level: report sorted(data) and the sizes of these keys when present:
#   bad_warps, beats, catches, trainers, training, procedures, loops, events
# every finding records the first example location "map:key" and a count; the output has counts and locations only, never text.
```

Top-level and per-map key names seen in the code (a starting list, not complete; step 1 completes it from the code): top level `maps`, `bad_warps`, `beats`, `catches`, `events`, `items`, `grass_ids`, `tile_types`, `interaction_stats`, `text_press_stats`, `text_pace`, `mash_skill`, `menus`, `move_damage`, `enemy_damage`, `damage_dealt`, `damage_taken`, `damage_by_type`, `item_heal`, `battle_lessons`, `procedures`, `training`, `threat_by_species`, `type_effect`, `chart_disagreements`, `dv_records`, `trainers`, `grind_points`, `loops`, `team_best_level`, `updated`. Per map: `visited`, `blocked`, `warps`, `last_seen`, `paths`, `warp_cand`, `warp_taken`, `warp_disproof`, `warp_disproof_total`, `jumps`, `fails`, `interactions`, `items`, `npcs`, `encounters`, `outcomes`, `demos`. Interaction entry: `count`, `text`, `pages`, `presses`, `menus`, `choices`, `effects`, `outcomes`, `screens`, `transitions`, `npc`, `type`, `type_votes`, `type_conf`, `type_why`, `best_presses`, `goal`, `done`. NPC entry: `pic`, `slot`, `positions`, `first_seen`, `text`, `talked`, `moves`, `last`, `trainer`, `results` (itself `count`, `text`, `presses`, `menus`, `choices`, plus `type` and `done` once typed).

## 2. Scope

In order:

1. `docs/MEMORY_FACTS.md` <!-- new: docs/MEMORY_FACTS.md --> (the field classification).
2. A pure audit module `src/pokeagent/explorer/memory_audit.py` <!-- new: src/pokeagent/explorer/memory_audit.py --> and a thin tool `tools/audit_memory.py` <!-- new: tools/audit_memory.py -->.
3. A pure cleaner module `src/pokeagent/explorer/memory_clean.py` <!-- new: src/pokeagent/explorer/memory_clean.py --> and a thin CLI `tools/clean_memory.py` <!-- new: tools/clean_memory.py -->.
4. Synthetic-fixture tests: `tests/test_memory_audit.py` <!-- new: tests/test_memory_audit.py --> and `tests/test_memory_clean.py` <!-- new: tests/test_memory_clean.py -->.

## 3. The work

1. **`docs/MEMORY_FACTS.md`.** Get the real field list from the code, not only from section 1: read `src/pokeagent/explorer/memory.py` and its mixins `memory_nav.py`, `memory_tiles.py`, `memory_warps.py`, `memory_purge.py`, `interaction_types.py` (for the interaction `type` fields), and `tools/swarm_merge.py` (its `merge_memory` shows which keys are merged between agents, which tells you what is treated as shared). Use `grep` over `src/pokeagent/explorer` for `setdefault("` and `["<key>"]` to find keys written elsewhere. Write one table per record kind: top-level keys, a map entry, an interaction entry, an NPC entry (including its `results`), and a demo. Every field gets exactly one class:
   - **world fact (shareable)**: true of the game itself for every player (walls, warps, tile types, a sign's words, where a healer stands).
   - **playthrough state (never shared)**: true only of this save or this run (`done` flags, beaten trainers, counts of presses, `last_seen`, what was picked up, goal stage, `recent` or per-run ledgers).
   - **derived guess (shareable only with evidence)**: an inference (a `type` guess and its `type_votes`, `type_conf`, `type_why`, a grade, a learned pace, a lesson), shareable only when its evidence field is kept with it.
   Each row has the field name, the class, and a one-line reason. Add a short final section "Rules the cleaner applies" listing section 3 step 3's rules, and mark any field you could not classify with certainty as "unclassified: treated as playthrough state (not shared)" so the safe default holds. Do not put any real dialogue, ROM data or sample from a real file in the document.
2. **Audit module and tool.** `memory_audit.py` exposes `audit(doc: dict) -> dict` (pure, no I/O, no printing, never mutates `doc`), returning `{"counts": {class_name: n}, "examples": {class_name: "map:key"}, "top_level_keys": [...], "top_level_sizes": {...}}` using the checks pasted in section 1, and `summary(report: dict) -> str` (a plain multi-line text, counts and locations only). `tools/audit_memory.py` is a thin script: `uv run python tools/audit_memory.py <path-to-maps.json> [--json]` prints the plain summary, or the JSON when `--json` is given, and exits 0. It reads the file, never writes anything, and never prints note text. Keep the regexes as module constants.
3. **Cleaner module and CLI.** `memory_clean.py` exposes `clean(doc: dict) -> tuple[dict, list[dict]]`: a NEW document (built with `copy.deepcopy`, the input is never edited in place) and a quarantine list. Every removal appends one record `{"where": "map:key[:field]", "field": ..., "value": <the removed value>, "reason": <short code>}`, so nothing disappears without a trace. Rules:
   - Strip playthrough state: remove `done` from every interaction entry and from every NPC `results`; reason `playthrough_state_done`. Add other playthrough fields only if your MEMORY_FACTS table classifies them as playthrough state and the rule is one line.
   - Remove battle and menu lines from notes: for `text` and each item of `pages` in an interaction entry and an NPC `results`, drop a whole page or text that matches the battle or menu regex (a page that is entirely such a line); reason `battle_text` or `menu_text`. If `text` is removed, set it to the first remaining page, or the empty string.
   - Contradictory evidence: when two facings of one tile both have PC text but only one is typed `pc` (the pc_text_but_type_not_pc case beside a `type == "pc"` entry), quarantine the untyped entry whole; reason `contradicts_typed_pc`. When an entry has more than one `type_votes` key, keep the entry but remove its `type` and `type_conf` and quarantine them with reason `conflicting_type_votes`. An entry typed `pc` whose text has no "pc" is kept (the type is the stronger evidence).
   - Everything not matched by a rule is copied through unchanged, including unknown keys.
   `tools/clean_memory.py` is a thin script: `uv run python tools/clean_memory.py <input maps.json> --out-dir <dir>`. It reads the input, calls `clean`, and writes two new files into `--out-dir`: `<stem>.clean.v<N>.json` and `<stem>.quarantine.v<N>.json`, where N is the lowest integer starting at 1 for which neither file exists. It refuses (nonzero exit, writes nothing) if the output path equals the input path, never overwrites an existing file, never modifies the input, and prints the two paths and the rule counts. Write with the same UTF-8 and trailing-newline style `MapMemory.save` uses.
4. **Tests (synthetic fixtures only; Red's real file is not available).** Build small dicts in the test files with invented text. Required:
   - `test_audit_counts_each_class`: a fixture with one entry for each audited class; assert the counts and that no note text appears in `summary(...)`.
   - `test_clean_does_not_mutate_the_input`: `copy.deepcopy` the fixture first; after `clean`, assert the input equals its copy and the returned document is a different object.
   - `test_every_removed_item_is_in_the_quarantine`: for a fixture hitting every rule, assert that each field present in the input and absent from the output has a quarantine record with the matching `where`, `field` and a non-empty `reason`. Compute "removed" by walking both documents, not by trusting the count.
   - One test per rule: `done` stripped from an interaction and from NPC `results`; a battle page and a menu page dropped while an ordinary dialogue page stays; the untyped bogus facing quarantined beside a typed `pc` entry; conflicting `type_votes` leaves the entry without `type` and with a quarantine record; unrelated keys copied through unchanged.
   - `test_cli_writes_versioned_files_and_never_overwrites`: run the CLI function (give `tools/clean_memory.py` a `main(argv)` and import it as `tests/test_status_interactions.py` imports `status`, with `sys.path.insert` of the `tools` directory) into `tmp_path` twice; assert `v1` then `v2` files, the input file is byte-identical, and a run whose output would equal the input exits nonzero and writes nothing.
   - `test_every_documented_field_is_classified`: parse the table rows of `docs/MEMORY_FACTS.md` and assert each has one of the three class labels (or the "unclassified" label), so the document cannot rot into an empty table.
5. Keep every new file under 600 lines. Each module has one job: audit does not clean, clean does not write files, the tools do not hold logic.

## 4. What NOT to do

- Do not run the cleaner or the audit on any real `maps.json`, and do not look for one. Running them on Red's real file, and the hands-off check afterwards, are Claude's job.
- Do not touch `src/pokeagent/game/` or `src/pokeagent/cli.py`; a separate run changes them.
- Do not change `retalk_veto.py`, `loop_veto.py` or `planner.py`, and do not change `MapMemory`, `swarm_merge.py` or any existing runtime module; this directive only adds files.
- Do not make the cleaner write in place, delete an input, or drop anything without a quarantine record.
- Do not add a ROM, a `kb/` table or any game data to the repo. Test text is invented.
- Do not run, edit or re-record `tests/test_golden_red.py`. It skips in the worktree. Report it NOT run. Claude's ROM-present check runs it before merge. This change adds files only and should not change any recorded hash; if one does change, say so in the report so it is re-recorded from a base-commit run in the same PR.
- Do not print or log note text from any fixture-like real source.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

```
uv run pytest -q -p no:cacheprovider tests/test_memory_audit.py tests/test_memory_clean.py
```
Expected: all pass.

```
uv run pytest -q -p no:cacheprovider tests/test_status_interactions.py tests/test_explorer_behaviours.py
```
Expected: same result as on your base commit, no new failures. Report any pre-existing failure separately.

```
git diff --stat main -- src/pokeagent/game src/pokeagent/cli.py src/pokeagent/explorer/planner.py src/pokeagent/explorer/retalk_veto.py src/pokeagent/explorer/loop_veto.py src/pokeagent/explorer/memory.py tools/swarm_merge.py
```
Expected: no output.

```
uv run pytest -q -p no:cacheprovider tests/test_golden_red.py -rs
```
Expected: it skips in the worktree. Report it as NOT run, with the skip reason.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here. If something expected is missing, stop and write that in the PR description.
- Use `uv run` and Python 3.12 only.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- If a tool call is genuinely blocked, stop and write why in the PR description.

## 7. Completion criteria

- [ ] `docs/MEMORY_FACTS.md` classifies every field of the top level, a map entry, an interaction entry, an NPC entry and a demo into exactly one of the three classes. <!-- test: tests/test_memory_clean.py -->
- [ ] The audit reports the classes from section 1 as JSON and as a plain summary, with counts and locations only. <!-- test: tests/test_memory_audit.py -->
- [ ] The cleaner returns a new document and never edits its input; every removed item has a quarantine record with a reason. <!-- test: tests/test_memory_clean.py -->
- [ ] The CLI writes versioned output files, never overwrites, and refuses to write over the input. <!-- test: tests/test_memory_clean.py -->
- [ ] Only new files were added (no existing runtime file edited); no file over 600 lines; nothing under `src/pokeagent/game` or `src/pokeagent/cli.py` touched.

## 8. Report

Findings first: the fields you could not classify with certainty, any field in the real code that section 1 did not list, and whether the three rules needed any judgement call. Then the command tails from section 5, including `tests/test_golden_red.py` reported NOT run and why. Name anything that did not fit.

## Required from User

Nothing before the run. Afterwards, and not part of this directive: Claude runs the real cleaner on Red's real `runs/maps.json` (output to a new versioned file, original untouched), reviews the quarantine list, and does the hands-off check (a Red run with the cleaned memory against the potion goal). Claude also runs the ROM-present check, including `tests/test_golden_red.py`, before merge.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(src/pokeagent/explorer/memory.py)
- Read(src/pokeagent/explorer/memory_nav.py)
- Read(src/pokeagent/explorer/memory_tiles.py)
- Read(src/pokeagent/explorer/memory_warps.py)
- Read(src/pokeagent/explorer/memory_purge.py)
- Read(src/pokeagent/explorer/interaction_types.py)
- Read(tools/swarm_merge.py)
- Read(tests/test_status_interactions.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git diff)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-08 18:57 · robert-claude-laptop · none → Queued — Drafted by Claude for Robert 2026-11-08: field labels, repeatable memory audit, and a cleaner that writes a new file plus quarantine
<!-- queue:end -->
