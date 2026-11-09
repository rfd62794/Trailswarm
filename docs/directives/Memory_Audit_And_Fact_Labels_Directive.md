# Trailswarm: label every maps.json field as shareable fact or private state, and add `brain audit` and `brain clean` on the existing journal

**Size:** M. **Assignee:** devin.

## 1. Why this exists

Red's own `runs/maps.json` (gitignored, so missing in a fresh worktree; do not look for it) was audited on 2026-11-08. Counts only, no dialogue:

- 16,476 interaction entries, 3,985 with text. About 3,209 of those match a rough battle-text pattern, 672 a menu or save-screen pattern.
- 756 spots were pressed 100 or more times.
- 8 entries carry PC text but are not typed `pc`. 20 entries have conflicting `type_votes`.
- 10 interaction entries and 14 NPC `results` carry `done` flags. `done` is playthrough state, not a world fact: an NPC `results` with `type` giver and `done` true (slot2 at (6,3) on map 40) makes `retalk_veto` refuse the starter ball, and a ported demo on map 38 achieving `left_house` fires on arrival at (0,2) through `ReplayBeat`, wasting steps.
- Map 38: `0,2,UP` is typed `pc` (count 1043) with Mom's dialogue as its text; a bogus `0,2,DOWN` (count 338) has the text "... turned on | the PC.". That is contradictory evidence about which facing is the PC.

Red's memory with all of this, untouched, never finished the potion goal in 600 steps, while cold runs with no memory did it by step 35. Before this memory is shared between agents or published, it needs a written line between world facts, playthrough state and guesses, a way to measure how dirty a file is, and a way to clean it that never edits the original in place and loses nothing silently.

**Build on the existing brain tooling; do not build a parallel tool.** `pokeagent brain` (`src/pokeagent/cli_brain.py`, logic in `src/pokeagent/brain/`) already inspects the memory, and every surgery goes through the edit journal `memory_edits.jsonl` (`src/pokeagent/explorer/edits.py`, per-op mutations in `src/pokeagent/explorer/edits_ops.py`). Each journal line is `{id, ts, op, map, key, value, note, by, prior?}`; `prior` is captured by `edits.prior_state` at edit time so `undo` can restore exactly what the edit changed; `edits.apply` replays the journal over a loaded document and is pure and idempotent; the brain `apply` fold (its backup flag) is the only way the journal is folded into `maps.json`. So **the removal record IS the journal**: no separate quarantine file and no separate cleaned-file format. Existing ops: `wall_add`, `wall_remove`, `warp_remove`, `warp_add`, `jump_add`, `jump_remove`, `interaction_clear`, `npc_trainer`, `npc_forget`, `tile_kind`, `visited_clear`, and `undo`. The existing signatures you extend:

```python
# explorer/edits.py
OPS = ("wall_add", ..., "visited_clear", "undo")          # DIRECT_EDITS = OPS[:-1]
def append_edit(path, *, op, map_id, key, value=None, note="", by="", prior=None) -> dict
def prepare(op, map_id, key, value=None)                  # validates, returns (map_id, key, value)
def prior_state(data, op, map_id, key, value=None)        # the undo payload
def apply(data, edits) -> dict                            # pure, idempotent
# explorer/edits_ops.py
FORWARD = {op_name: fn(data, edit_record)}                # per-op mutation
def invert_edit(data, e)                                  # undo: restore e["prior"]
# brain/fileops.py
def effective_data(maps_path) -> (data_with_journal_applied, journal_path)
```

`mcp_brain.py` and `cli_brain.py edit` both take their op list from `edits.DIRECT_EDITS`, so a new op shows up in both with no other change. `tests/test_brain_edits.py` is the model for op tests (a `_data()` fixture, a parametrized `test_every_direct_op`, idempotence and undo tests).

**Merge order against `Brain_Compare_And_Run_Reports_Directive.md`: Brain_Compare merges first.** Both add one call line to `cli_brain._add_commands` and a few exports to `src/pokeagent/brain/__init__.py`; whichever is second rebases over those two additions (keep both) before its PR is opened. They share no other file.

A separate directive (`Interaction_Text_Capture_Fix_Directive.md`) stops new bad notes at the source. This directive depends on nothing in it and may run in any order; the two share an idea (battle and menu lines do not belong in a note), so keep them independent and do not import from its new files.

### The audit logic to port (pasted, because you cannot read the original)

This is the throwaway audit that produced the numbers above. Port its checks into a pure module; do not copy its `sys.argv` and `print` style.

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

Top-level and per-map key names seen in the code (a starting list, not complete; step 1 completes it from the code): top level `maps`, `bad_warps`, `beats`, `catches`, `events`, `items`, `grass_ids`, `tile_types`, `interaction_stats`, `text_press_stats`, `text_pace`, `mash_skill`, `menus`, `move_damage`, `enemy_damage`, `damage_dealt`, `damage_taken`, `damage_by_type`, `item_heal`, `battle_lessons`, `procedures`, `training`, `threat_by_species`, `type_effect`, `chart_disagreements`, `dv_records`, `trainers`, `grind_points`, `loops`, `team_best_level`, `updated`. Per map: `visited`, `blocked`, `warps`, `last_seen`, `paths`, `warp_cand`, `warp_taken`, `warp_disproof`, `warp_disproof_total`, `jumps`, `fails`, `interactions`, `items`, `npcs`, `encounters`, `outcomes`, `demos`, `tile_overrides`. Interaction entry: `count`, `text`, `pages`, `presses`, `menus`, `choices`, `effects`, `outcomes`, `screens`, `transitions`, `npc`, `type`, `type_votes`, `type_conf`, `type_why`, `best_presses`, `goal`, `done`. NPC entry: `pic`, `slot`, `positions`, `first_seen`, `text`, `talked`, `moves`, `last`, `trainer`, `results` (itself `count`, `text`, `presses`, `menus`, `choices`, plus `type` and `done` once typed).

## 2. Scope

In order:

1. `docs/MEMORY_FACTS.md` <!-- new: docs/MEMORY_FACTS.md --> (the field classification).
2. `src/pokeagent/explorer/note_filter.py` <!-- new: src/pokeagent/explorer/note_filter.py --> : the two regexes and the pure helpers both the audit and the new journal ops use (single purpose).
3. New journal ops (section 3 step 3) in `src/pokeagent/explorer/edits.py` and `src/pokeagent/explorer/edits_ops.py`, with undo, tests added to `tests/test_brain_edits.py`.
4. `src/pokeagent/brain/audit.py` <!-- new: src/pokeagent/brain/audit.py --> (pure audit) and `src/pokeagent/brain/cleanplan.py` <!-- new: src/pokeagent/brain/cleanplan.py --> (pure planner that turns a document into journal edits).
5. `brain audit` and `brain clean` subcommands: argparse and emit only, in a new `src/pokeagent/cli_brain_memory.py` <!-- new: src/pokeagent/cli_brain_memory.py --> (because `cli_brain.py` is already about 277 lines and brain modules stay at or under 300), attached by one small call in `cli_brain.py`'s `_add_commands`; export the two logic functions from `src/pokeagent/brain/__init__.py`.
6. Tests: `tests/test_brain_audit.py` <!-- new: tests/test_brain_audit.py --> and `tests/test_brain_clean.py` <!-- new: tests/test_brain_clean.py -->.

Size rules: no file over 600 lines anywhere, and the brain modules (`src/pokeagent/brain/*.py` and `cli_brain*.py`) stay at or under 300 lines, the limit `Brain_Tools_Directive.md` set. `edits.py` is about 216 lines, `edits_ops.py` about 225 and `cli_brain.py` about 277 today. So put the four new ops' mutation and inversion functions in a new `src/pokeagent/explorer/edits_ops_notes.py` <!-- new: src/pokeagent/explorer/edits_ops_notes.py --> from the start and register them in `FORWARD` and `invert_edit`; keep `edits.py` changes to the `OPS` tuple, `prepare` and `prior_state`. If any file would still pass its limit, split it first and say so in the report.

## 3. The work

1. **`docs/MEMORY_FACTS.md`.** Get the real field list from the code, not only from section 1: read `src/pokeagent/explorer/memory.py` and its mixins `memory_nav.py`, `memory_tiles.py`, `memory_warps.py`, `memory_purge.py`, `interaction_types.py` (the interaction `type` fields), `edits_ops.py` (what the journal can change) and `tools/swarm_merge.py` (`merge_memory` shows which keys are merged between agents, i.e. treated as shared). Also read these files, which write interaction, NPC and top-level keys: `src/pokeagent/explorer/interaction_record.py`, `src/pokeagent/explorer/press_interact.py`, `src/pokeagent/explorer/demos.py` and `src/pokeagent/explorer/trainer_ledger.py`. Do not search or grep the tree; a key you find nowhere in the named files and the lists in section 1 is classed "unclassified". Write one table per record kind: top-level keys, a map entry, an interaction entry, an NPC entry (including its `results`), and a demo. Every field gets exactly one class:
   - **world fact (shareable)**: true of the game itself for every player (walls, warps, tile types, a sign's words, where a healer stands).
   - **playthrough state (never shared)**: true only of this save or this run (`done` flags, beaten trainers, counts of presses, `last_seen`, what was picked up, goal stage, per-run ledgers).
   - **derived guess (shareable only with evidence)**: an inference (a `type` guess and its `type_votes`, `type_conf`, `type_why`, a grade, a learned pace, a lesson), shareable only when its evidence field is kept with it.
   Each row has the field name, the class and a one-line reason. Add a final section "Rules `brain clean` applies" listing step 4's rules, and mark any field you could not classify with certainty as "unclassified: treated as playthrough state (not shared)" so the safe default holds. Put no real dialogue, ROM data or sample from a real file in the document.
2. **`note_filter.py`.** Holds `BATTLE` and `MENU` (the regexes above), `is_noise(text) -> str | None` returning `"battle_text"`, `"menu_text"` or `None`, and `prune_note(entry: dict) -> dict | None`: for an interaction entry or an NPC `results` dict, drops each item of `pages` that `is_noise` flags, rebuilds `text` as the first remaining page (or the empty string when none remain, and also when `text` itself is noise), and returns the `prior` payload if anything changed, else `None`. The payload holds only the keys the entry actually had (`{"text": old_text, "pages": old_pages}` when both existed). The forward op rewrites only keys that already exist and never creates `text` or `pages`; `invert_edit` restores the keys in the payload and DELETES a key that the payload lacks (never sets it to None), so undo returns the original document exactly, including an entry that had no `pages` or no `text` key. Pure; no file IO.
3. **New journal ops (narrowly scoped, each with undo).** Add to `OPS` before `"undo"` (so `DIRECT_EDITS` grows), to `prepare` (key shape and value check), to `prior_state` (the undo payload), to `edits_ops.FORWARD`, and to `invert_edit`:
   - `interaction_state_clear`: key `x,y,FACING` (an edge key, as `interaction_clear`); value must be one of `"done"` or `"type"`. Forward: `"done"` removes the `done` flag from that interaction entry; `"type"` removes `type`, `type_conf` and `type_why` (keeps `type_votes` as the evidence of why). No entry, no change. `prior`: the dict of the removed fields' old values, or `None`.
   - `npc_state_clear`: key `x,y` (a tile key, matching NPCs by last-seen tile as `npc_forget` does through `edits_ops.npcs_at`); value must be `"done"`. Forward: removes `results.done` from each NPC at that tile; NPCs at the tile without it are untouched. `prior`: `{npc_id: old_done_value}` for those that had it, `None` when none did. NPCs are matched by their `last` position only (as `npcs_at` does): an NPC with no `last` can never be reached by this op or by `npc_prune`.
   - `interaction_prune`: key `x,y,FACING`; value must be `"battle_menu"`. Forward: `note_filter.prune_note(entry)` on that interaction entry. `prior`: that function's payload (the old `text` and `pages`).
   - `npc_prune`: key `x,y`; value `"battle_menu"`. Forward: `prune_note` on `results` of each NPC at that tile. `prior`: `{npc_id: payload}` for the NPCs actually changed, `None` when none were. NPCs with no `last` are unreachable, as above.
   Rules: each op is pure and idempotent under `apply` (replaying it changes nothing more), a missing map, entry or field is a no-op, and an invalid value is rejected by `prepare` with a `ValueError` naming the allowed values. `undo` of each restores exactly the prior state (including re-adding a removed `done` flag and the old pages). Do not change the meaning of any existing op.
4. **`src/pokeagent/brain/audit.py`.** `audit(doc: dict) -> dict` (pure, no IO, no printing, never mutates `doc`): `{"counts": {class_name: n}, "examples": {class_name: "map:key"}, "top_level_keys": [...], "top_level_sizes": {...}}` using the checks pasted in section 1 (use `note_filter` for the regexes), and `summary(report: dict) -> str`: plain multi-line text, counts and locations only, never note text.
5. **`src/pokeagent/brain/cleanplan.py`.** `plan_clean(doc: dict) -> list[dict]` (pure; `doc` is the effective data, journal already applied) returns planned edits `{"op", "map", "key", "value", "note"}`, where `note` is the short reason code; it carries no dialogue. Rules:
   - Playthrough state: `interaction_state_clear` value `"done"` for every interaction entry with `done`; `npc_state_clear` value `"done"` for every NPC whose `results` has `done`. Reason `playthrough_state_done`.
   - Battle and menu lines: `interaction_prune` for an interaction entry, and `npc_prune` for an NPC `results`, whose `text` or any page is flagged by `is_noise`. Reason `battle_text` or `menu_text` (the first one found).
   - Contradictory evidence: where two facings of one tile both have PC text ("turned on" and "the pc") but only one is typed `pc`, `interaction_clear` for the untyped one; reason `contradicts_typed_pc`. For an entry that has a `type` AND more than one `type_votes` key, `interaction_state_clear` value `"type"`; reason `conflicting_type_votes` (an entry with conflicting votes but no `type` plans nothing, so a second plan is empty). An entry typed `pc` whose text has no "pc" is kept (the type is the stronger evidence).
   - NPC edits are per tile, not per NPC: `npc_state_clear` and `npc_prune` act on every NPC whose `last` is that tile, so plan at most one edit per `(op, map, key, value)` (the key is `"x,y"` from `last`), even when several NPCs on the tile need it. NPCs with no `last` are skipped by the planner (no op can reach them, so planning them would never converge); the dry run reports their count as `npc_unreachable_skipped` and the second plan stays empty.
   - An entry planned for `interaction_clear` (the contradicting facing) gets no other edit: skip its `done`, `type` and prune edits. An `npc_state_clear` and an `npc_prune` on one tile are different ops and both stay; each changes a different field, so neither becomes a no-op because of the other.
   - Everything not matched is untouched. The plan is deterministic (sorted by map id, then key, then op) and each rule's edits are independent, so the same plan comes out of the same document.
6. **CLI.** In `cli_brain_memory.py` define `add_commands(bsub, common)` (the same `common` parent parser `cli_brain.py` builds, which carries `--maps` and `--text`) and call it from `cli_brain._add_commands` with one line, so both `pokeagent brain ...` and `tools/brain.py` get the commands. Add:
   - `brain audit`: reads `fileops.effective_data(args.maps)[0]`, prints the audit report as JSON (sorted keys, the default for the whole CLI) or the plain `summary` with `--text`. Read-only.
   - `brain clean`: builds the plan from the effective data. **Default is a dry run**: prints the plan counts per reason, and the planned edits (op, map, key, reason; no dialogue), and writes nothing. With `--write` it first **refuses (exit 1, writes nothing) while any agent is alive**, using `fileops.live_agents(args.maps)` exactly as the fold does. Then it appends the edits to the journal: for each planned edit, in order, run `edits.prepare`, then `edits.prior_state` against a working copy; if the prior is `None` (the edit would change nothing now) skip it and count it as `skipped_noop`, otherwise `edits.append_edit(jpath, ..., by="brain-clean", note=<reason>, prior=...)`, then apply that one record to the working copy so a later edit on the same entry sees the earlier one's result. It prints the number written and a reminder that the journal must now be folded. It never writes `maps.json`; the brain `apply` fold stays the only fold. Running `brain clean` again after `--write` yields an empty plan, because the effective data already has the journal applied.

   **Why these ops are one-shot cleanups, and what happens after a fold (state this plainly in the docs and the report).** `MapMemory` re-applies the whole journal on load and again before every save, and the swarm merge applies it after merging (`edits.py` docstring, `tools/swarm_merge.py`). So while the journal is unfolded, a clear op wipes any `done` or `type` an agent later sets on a cleaned key, and `retalk_veto` and `ReplayBeat` rely on those being set during a run. `fold_journal` is what ends this: it writes the folded data to `maps.json` and then moves the journal file to `backups/memory_edits-<stamp>.jsonl`, so the ops never replay again and later `done` or `type` values written by agents survive normally. So the design is: `--write` only with no agent alive (a live agent saves over `maps.json` and would resurrect cleaned data), and the very next step is the fold (the `apply` command with its backup flag, which itself refuses while an agent lives), before any agent starts. Never leave a cleaned journal unfolded while agents run. This is correct for how `fold_journal` and `merge_memory` work because it needs no change to `MapMemory`, `merge_memory` or the fold; making the ops standing rules instead would force every agent's `done` handling to know about them. One consequence: `merge_memory` keeps the longer note `text`, so merging agent copies saved before the fold can bring old battle text back; do not merge pre-fold agent copies after the fold.
7. **Tests (synthetic fixtures only; Red's real file is not available).** Invented text only.
   - In `tests/test_brain_edits.py`, add the four ops to the parametrized every-op test and add: `test_new_ops_undo_restores_prior` (apply the op, then an `undo` record of it, assert the document equals the original), `test_new_ops_are_idempotent`, and `test_prepare_rejects_bad_values_for_new_ops`.
   - `tests/test_brain_audit.py`: `test_audit_counts_each_class` (one entry per audited class; assert counts and that no note text appears in `summary`), `test_audit_does_not_mutate_input`, `test_every_documented_field_is_classified` (parse the table rows of `docs/MEMORY_FACTS.md`; each row has one of the three class labels or the "unclassified" label).
   - `tests/test_brain_clean.py`: one test per rule through `plan_clean` (the `done` flags on an interaction and on NPC `results`; a battle page and a menu page pruned while an ordinary page stays; the untyped bogus facing cleared beside a typed `pc` entry; conflicting `type_votes` clears `type`); `test_dry_run_writes_nothing` (call the CLI `main` on a `tmp_path` `maps.json`, assert no journal file exists); `test_write_appends_journal_with_prior_and_never_touches_maps_json` (assert `maps.json` bytes unchanged, every journal record has a non-None `prior`, `by == "brain-clean"` and a `note`); `test_write_refuses_while_an_agent_is_alive` (monkeypatch `fileops.live_agents` to return one id; assert exit 1 and no journal file); `test_npc_edits_are_deduped_per_tile` (two NPCs on one tile that both have `done` plan one `npc_state_clear`; an NPC with no `last` is skipped and counted); `test_clear_and_prune_on_one_npc_tile_both_apply`; `test_conflicting_votes_without_type_plans_nothing`; `test_prune_undo_deletes_keys_the_entry_never_had` (an entry with no `pages` key: after prune and undo there is still no `pages` key); `test_every_planned_item_is_in_the_journal` (with `skipped_noop` zero, the number of journal lines equals the plan length, and `edits.apply` of the journal over the original removes exactly what the plan says, found by walking both documents); `test_clean_then_undo_all_restores_the_original` (append an `undo` for each journal id in reverse; `edits.apply` result equals the original); `test_second_clean_has_an_empty_plan`.
8. Every new module has one job: the audit does not clean, the planner does not write, the CLI holds no logic.

## 4. What NOT to do

- Do not build a second CLI, a `tools/` script, a quarantine file or a `.clean.vN.json` format. Journal edits are the removal record.
- Do not run `brain clean --write` or the brain `apply` fold on any real `maps.json`, and do not look for one. Running the real cleaner on Red's real file and the hands-off check afterwards are Claude's job.
- Do not make `brain clean` write `maps.json`, delete the journal, or fold anything.
- Do not change the behaviour of an existing op, `MapMemory`, `tools/swarm_merge.py` or the brain `apply` command.
- Do not touch `src/pokeagent/game/` or `src/pokeagent/cli.py`; a separate run changes them.
- Do not change `retalk_veto.py`, `loop_veto.py` or `planner.py`.
- Do not add a ROM, a `kb/` table or any game data to the repo. Test text is invented.
- Do not run, edit or re-record `tests/test_golden_red.py`. It skips in the worktree. Report it NOT run. Claude's ROM-present check runs it before merge. This change adds ops and files and should not change any recorded hash; if one does change, say so in the report so it is re-recorded from a base-commit run in the same PR.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

```
uv run pytest -q -p no:cacheprovider tests/test_brain_edits.py tests/test_brain_audit.py tests/test_brain_clean.py
```
Expected: all pass.

```
uv run pytest -q -p no:cacheprovider tests/test_brain_query.py tests/test_status_interactions.py tests/test_explorer_behaviours.py
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

- [ ] `docs/MEMORY_FACTS.md` classifies every field of the top level, a map entry, an interaction entry, an NPC entry and a demo into exactly one of the three classes. <!-- test: tests/test_brain_audit.py -->
- [ ] `brain audit` reports the classes from section 1 as JSON and as a plain summary, with counts and locations only. <!-- test: tests/test_brain_audit.py -->
- [ ] The four new ops apply, are idempotent, and undo restores the prior state exactly. <!-- test: tests/test_brain_edits.py -->
- [ ] `brain clean` is a dry run by default; `--write` refuses while an agent is alive, appends journal edits with a non-None `prior`, never writes `maps.json`, and a second run plans nothing. The docs and report state that the journal must be folded before any agent starts, and why. <!-- test: tests/test_brain_clean.py -->
- [ ] Every planned removal is a journal record, and undoing all of them restores the original document. <!-- test: tests/test_brain_clean.py -->
- [ ] No file over 600 lines and no brain module over 300 (split first if needed); nothing under `src/pokeagent/game` or `src/pokeagent/cli.py` touched.

## 8. Report

Findings first: the fields you could not classify with certainty, any field in the real code that section 1 did not list, whether any file had to be split for size, and whether the rules needed a judgement call. Then the command tails from section 5, including `tests/test_golden_red.py` reported NOT run and why. Name anything that did not fit.

## Required from User

Nothing before the run. Afterwards, and not part of this directive: Claude runs `brain clean` (dry run, then `--write`) on Red's real `runs/maps.json`, reviews the plan and the journal, folds with the brain `apply` fold (backup flag) when no agent is alive, and does the hands-off check (a Red run with the cleaned memory against the potion goal). Claude also runs the ROM-present check, including `tests/test_golden_red.py`, before merge.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(src/pokeagent/cli_brain.py)
- Read(src/pokeagent/brain/__init__.py)
- Read(src/pokeagent/brain/fileops.py)
- Read(src/pokeagent/explorer/edits.py)
- Read(src/pokeagent/explorer/edits_ops.py)
- Read(src/pokeagent/explorer/memory.py)
- Read(src/pokeagent/explorer/memory_nav.py)
- Read(src/pokeagent/explorer/memory_tiles.py)
- Read(src/pokeagent/explorer/memory_warps.py)
- Read(src/pokeagent/explorer/memory_purge.py)
- Read(src/pokeagent/explorer/interaction_types.py)
- Read(src/pokeagent/explorer/interaction_record.py)
- Read(src/pokeagent/explorer/press_interact.py)
- Read(src/pokeagent/explorer/demos.py)
- Read(src/pokeagent/explorer/trainer_ledger.py)
- Read(tools/swarm_merge.py)
- Read(tests/test_brain_edits.py)
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
