# Memory facts: what `runs/maps.json` holds, and what may be shared

Every field of the map memory gets exactly one **fact type** and exactly one **area**.

Fact types:

- **world fact (shareable)**: true of the game itself for every player (walls, warps, tile types, a sign's words, where a healer stands).
- **playthrough state (never shared)**: true only of this save or this run (`done` flags, beaten trainers, press counts, `last_seen`, pickups, goal stage, per-run ledgers).
- **derived guess (shareable only with evidence)**: an inference (a `type` and its votes, a grade, a learned pace, a lesson), shareable only together with its evidence field.
- **unclassified: treated as playthrough state (not shared)**: a field that could not be classified with certainty; the safe default holds.

Areas: `navigation`, `interaction`, `battle`, `team_capture`, `economy_items`, `progression`, and `other` for a field that fits none of the six.

## Top-level keys

| Field | Fact type | Area | Reason |
|---|---|---|---|
| `maps` | world fact (shareable) | navigation | container of the per-map records; every field below carries its own label, which wins |
| `bad_warps` | world fact (shareable) | navigation | tombstones of map changes that are not doors (forced walks); true for every player |
| `beats` | derived guess (shareable only with evidence) | interaction | text-triggered button sequences, graded by replays; the grade is the evidence |
| `catches` | playthrough state (never shared) | team_capture | records of what this save caught |
| `events` | playthrough state (never shared) | progression | append-only event records of runs |
| `items` | playthrough state (never shared) | economy_items | append-only item records of runs (what was picked up or used) |
| `grass_ids` | world fact (shareable) | navigation | tile-id blocks where wild encounters happened, per tileset: a property of the tileset |
| `tile_types` | derived guess (shareable only with evidence) | navigation | solid/walkable votes per tile block; known_solid needs 3 solid and 0 walkable votes |
| `interaction_stats` | playthrough state (never shared) | interaction | per-type talk/press/re-talk/heal totals counted by this memory's runs |
| `text_press_stats` | unclassified: treated as playthrough state (not shared) | interaction | named in the directive only; no writer in the files read |
| `text_pace` | derived guess (shareable only with evidence) | interaction | a learned text-advance pace |
| `mash_skill` | unclassified: treated as playthrough state (not shared) | interaction | named in the directive only; no writer in the files read |
| `menus` | unclassified: treated as playthrough state (not shared) | interaction | merged first-wins by merge_memory; its value shape is not written in the files read |
| `move_damage` | derived guess (shareable only with evidence) | battle | damage samples per move; the samples are the evidence |
| `enemy_damage` | derived guess (shareable only with evidence) | battle | damage samples per enemy move; the samples are the evidence |
| `damage_dealt` | derived guess (shareable only with evidence) | battle | damage samples dealt; depends on this team's stats |
| `damage_taken` | derived guess (shareable only with evidence) | battle | damage samples taken; depends on this team's stats |
| `damage_by_type` | derived guess (shareable only with evidence) | battle | damage aggregated by type |
| `item_heal` | derived guess (shareable only with evidence) | economy_items | healing samples per item; the samples are the evidence |
| `battle_lessons` | derived guess (shareable only with evidence) | battle | per-species fights/wins/fled and best move: a lesson |
| `procedures` | derived guess (shareable only with evidence) | interaction | verified menu procedures with ok/fail counts and a learned pace |
| `training` | derived guess (shareable only with evidence) | team_capture | XP-per-step economics per map, measured from runs |
| `threat_by_species` | derived guess (shareable only with evidence) | battle | inferred threat per enemy species |
| `type_effect` | derived guess (shareable only with evidence) | battle | learned type effectiveness; chart_disagreements is its evidence |
| `chart_disagreements` | derived guess (shareable only with evidence) | battle | observed disagreements with the type chart: evidence for type_effect |
| `dv_records` | playthrough state (never shared) | team_capture | DVs of this save's own Pokemon |
| `trainers` | world fact (shareable) | battle | static per-ROM trainer data (class, party, prize, flag bit); 'beaten' is never stored here |
| `grind_points` | derived guess (shareable only with evidence) | team_capture | grind-point ledger, measured against a prior |
| `loops` | derived guess (shareable only with evidence) | navigation | recurring dead (tile, button) actions; decays with a TTL |
| `team_best_level` | playthrough state (never shared) | team_capture | the best level this save's team reached |
| `blackout_tax` | derived guess (shareable only with evidence) | battle | learned blackout step margins per goal |
| `updated` | playthrough state (never shared) | other | save timestamp; describes the file, not the game |

## A map entry (`maps[<id>]`)

| Field | Fact type | Area | Reason |
|---|---|---|---|
| `visited` | world fact (shareable) | navigation | tiles stood on are walkable; the per-tile count is a by-product |
| `blocked` | world fact (shareable) | navigation | confirmed wall edges |
| `warps` | world fact (shareable) | navigation | confirmed door/connection edges to [map, x, y] |
| `last_seen` | playthrough state (never shared) | navigation | step this map was last visited |
| `paths` | world fact (shareable) | navigation | observed move edges and where they led |
| `warp_cand` | derived guess (shareable only with evidence) | navigation | map-change sightings not yet confirmed as a warp |
| `warp_taken` | playthrough state (never shared) | navigation | how often this memory's runs took each warp |
| `warp_disproof` | derived guess (shareable only with evidence) | navigation | this cycle's disproofs of a learned warp: evidence |
| `warp_disproof_total` | derived guess (shareable only with evidence) | navigation | lifetime disproofs of a warp: evidence |
| `jumps` | world fact (shareable) | navigation | one-way ledge hops and their landing tile |
| `fails` | derived guess (shareable only with evidence) | navigation | failed-move counts per edge: evidence for blocked |
| `interactions` | world fact (shareable) | interaction | container of interaction entries; each field below carries its own label |
| `items` | world fact (shareable) | economy_items | item-ball tiles and the item they hold (whether still there is read live) |
| `npcs` | world fact (shareable) | interaction | container of NPC entries; each field below carries its own label |
| `encounters` | derived guess (shareable only with evidence) | team_capture | wild-encounter counts per tile: evidence of grass |
| `outcomes` | derived guess (shareable only with evidence) | progression | per tile, button and goal stage: tries, progress and best presses |
| `demos` | derived guess (shareable only with evidence) | progression | recorded demonstrations: graded hypotheses (see the demo table) |
| `tile_overrides` | world fact (shareable) | navigation | surgery overrides of a tile's kind |

## An interaction entry (`maps[<id>].interactions["x,y,FACING"]`)

| Field | Fact type | Area | Reason |
|---|---|---|---|
| `count` | playthrough state (never shared) | interaction | how often this spot was pressed |
| `text` | world fact (shareable) | interaction | what the spot says (a sign's words), when free of battle/menu lines |
| `pages` | world fact (shareable) | interaction | the ordered dialogue pages, when free of battle/menu lines |
| `presses` | playthrough state (never shared) | interaction | presses each conversation took (newest 10) |
| `menus` | world fact (shareable) | interaction | menus the spot opens |
| `choices` | playthrough state (never shared) | interaction | menu choices this memory's runs made |
| `effects` | derived guess (shareable only with evidence) | interaction | observed RAM effects of the talk: evidence for type |
| `outcomes` | playthrough state (never shared) | interaction | outcome counts of this memory's runs |
| `screens` | playthrough state (never shared) | interaction | screen counts seen while interacting |
| `transitions` | world fact (shareable) | navigation | where the interaction led |
| `npc` | world fact (shareable) | interaction | which sprite stood there (pic, slot, last) |
| `type` | derived guess (shareable only with evidence) | interaction | the voted interaction kind |
| `type_votes` | derived guess (shareable only with evidence) | interaction | votes per kind: the evidence for type |
| `type_conf` | derived guess (shareable only with evidence) | interaction | the winning share of the votes |
| `type_why` | derived guess (shareable only with evidence) | interaction | the reason of the last classification |
| `best_presses` | derived guess (shareable only with evidence) | interaction | fewest presses that completed it |
| `goal` | playthrough state (never shared) | progression | goal stage active when it was last read |
| `done` | playthrough state (never shared) | progression | a giver already gave in some run; retalk_veto refuses on it |
| `done_run` | playthrough state (never shared) | progression | the run that saw the reward |

## An NPC entry (`maps[<id>].npcs[<slot:pic>]`, including its `results`)

| Field | Fact type | Area | Reason |
|---|---|---|---|
| `pic` | world fact (shareable) | interaction | sprite picture id |
| `slot` | world fact (shareable) | interaction | sprite table slot; with pic and first tile it identifies the NPC |
| `positions` | world fact (shareable) | navigation | tiles the NPC was seen on, with counts |
| `first_seen` | playthrough state (never shared) | interaction | step this NPC was first seen |
| `text` | world fact (shareable) | interaction | the longest thing the NPC said, when free of battle/menu lines |
| `talked` | playthrough state (never shared) | interaction | how often this memory's runs talked to it |
| `moves` | derived guess (shareable only with evidence) | navigation | wanderer or static, inferred from positions (its evidence) |
| `last` | playthrough state (never shared) | navigation | tile of the latest sample; the ops match NPCs by it |
| `trainer` | derived guess (shareable only with evidence) | battle | inferred from a trainer battle starting next to it |
| `beaten` | playthrough state (never shared) | battle | set on a win; per save (memory.py mark_trainer docstring) |
| `results` | world fact (shareable) | interaction | container of the talk record; its fields below carry their own labels |
| `results.count` | playthrough state (never shared) | interaction | how often it was talked to |
| `results.text` | world fact (shareable) | interaction | what it said, when free of battle/menu lines |
| `results.pages` | world fact (shareable) | interaction | dialogue pages, when free of battle/menu lines |
| `results.presses` | playthrough state (never shared) | interaction | presses each talk took |
| `results.menus` | world fact (shareable) | interaction | menus the talk opened |
| `results.choices` | playthrough state (never shared) | interaction | choices this memory's runs made |
| `results.type` | derived guess (shareable only with evidence) | interaction | the voted kind of the talk |
| `results.done` | playthrough state (never shared) | progression | a giver already gave in some run; retalk_veto refuses the starter ball on it |

## A demo (`maps[<id>].demos[i]`)

| Field | Fact type | Area | Reason |
|---|---|---|---|
| `at` | derived guess (shareable only with evidence) | navigation | tile the demonstration starts on |
| `facing` | derived guess (shareable only with evidence) | navigation | facing at the start |
| `screen` | derived guess (shareable only with evidence) | interaction | first screen lines it must match |
| `buttons` | derived guess (shareable only with evidence) | progression | the pressed sequence: the hypothesis itself |
| `achieved` | derived guess (shareable only with evidence) | progression | goals reached when recorded: the evidence |
| `source` | derived guess (shareable only with evidence) | other | who recorded it (human or Claude): provenance, fits no gameplay area |
| `end` | derived guess (shareable only with evidence) | navigation | where it ended |
| `grade` | derived guess (shareable only with evidence) | progression | replay grade: the evidence; below 0 it is never replayed |
| `replays` | playthrough state (never shared) | progression | how often this memory's runs replayed it |

Storage will be split by area later, one area at a time, only after the hands-off regression can prove nothing broke; that split is out of scope here and nothing in this labelling changes how or where memory is stored.

## Rules `brain clean` applies

`brain clean` (dry run by default) plans journal edits from the effective data (journal applied); `--write` appends them to `memory_edits.jsonl` with `by = "brain-clean"`, the reason code as `note` and an undo `prior`. It never writes `maps.json`. The journal is the removal record: `brain undo <id>` restores any single edit.

- Playthrough state: `interaction_state_clear` value `done` for every interaction entry with `done`; `npc_state_clear` value `done` for every NPC tile with a `results.done`. Reason `playthrough_state_done`.
- Battle and menu lines: `interaction_prune` / `npc_prune` value `battle_menu` where `text` or any page matches the battle or menu pattern (`explorer/note_filter.py`): flagged pages are dropped and `text` becomes the first remaining page (empty when none remain). Reason `battle_text` or `menu_text` (the first found).
- Contradictory evidence: where two or more facings of one tile hold PC text ("turned on" and "the pc") and exactly one of them is typed `pc`, `interaction_clear` for the untyped ones (reason `contradicts_typed_pc`); such an entry gets no other edit. An entry typed `pc` whose text has no "pc" is kept.
- Conflicting votes: an entry with a `type` and more than one `type_votes` key gets `interaction_state_clear` value `type` (removes `type`, `type_conf`, `type_why`; keeps `type_votes`). Reason `conflicting_type_votes`. Conflicting votes without a `type` plan nothing.
- NPC edits are per tile (the NPC's `last`), at most one per op and tile. NPCs with no `last` cannot be reached by any op and are only counted (`npc_unreachable_skipped`).
- Everything else is untouched. The plan is sorted by map id, key, op, so the same document gives the same plan; a second `brain clean` after `--write` plans nothing.

**Fold before any agent starts.** `MapMemory` re-applies the whole journal on load and before every save, and the swarm merge applies it after merging. While a cleaned journal is unfolded, its clear ops would wipe any `done` or `type` an agent sets again on a cleaned key, and `retalk_veto` and `ReplayBeat` rely on those being set during a run. So: run `brain clean --write` only with no agent alive (it refuses otherwise; a live agent would save over `maps.json` and resurrect the cleaned data), and the very next step is `brain apply --backup` (which also refuses while an agent lives). The fold writes the cleaned data into `maps.json` and moves the journal to `backups/memory_edits-<stamp>.jsonl`, so the ops never replay again and later agent writes survive. Never leave a cleaned journal unfolded while agents run. `merge_memory` keeps the longer note `text`, so do not merge agent copies saved before the fold into the folded memory: they would bring old battle text back.
