# PokeAgent: opponent modeling - learn each species by watching it, and plan counters per opponent

**Read first:** `src/pokeagent/explorer/battle.py` (type_effect / damage_by_type / threat_by_species ledgers),
`behaviours/battle.py` (`damage_taken`, `battle_lessons`), `behaviours/battle_moves.py`, `explorer/stats.py`,
`docs/directives/Game_Knowledge_Directive.md` (species base stats, learnsets, trainer parties).
**Depends on:** Game Knowledge merged (learnsets, species data, trainer parties) - if missing, stop.
**Builder:** a Claude builder on the laptop with the ROM, `kb/` and checkpoint copies (gitignored).
**Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-05): "Can our Agent also learn the results of its opponents' action choices? essentially learn how
to run a team it may not have yet by watching how the wild version of the pokemon behaves, and what works and what
doesn't. As well as how to plan effective counters for each opponent, and which pokemon to counter to each
pokemon?"

Today the agent records, per enemy species, the worst move threat it has shown (`threat_by_species`), damage it
took (`damage_taken`), fights/wins/fled (`battle_lessons`), and what our moves did by type (`type_effect`,
`damage_by_type`). It does not keep a per-species model of *what the opponent does and how well it works*, and it
never uses that to choose a lead, a switch-in, or a future team member.

Note on Gen 1 AI: wild Pokemon pick moves essentially at random among their known moves; trainers use simple
rules. So "watching" teaches each species' **move pool at each level and each move's real effect**, not
strategy - which is exactly what an owner needs to know.

## 2. Scope (in order)

1. **Species book** `explorer/species_book.py`, stored in maps.json `species_book[species]`: moves seen by level
   (from "Enemy X used Y!"), per move: uses, damage dealt to us (fraction of our max HP, keyed by our types), status
   inflicted (from battle text: poisoned, paralysed, asleep, confused, stat fell), misses; plus the species' stats as
   observed (enemy level, HP) cross-checked with the drained base stats; and what of ours worked against it (from the
   existing ledgers). Merge it in the swarm (counts add).
2. **"How to run it"** `species_book.playbook(species, level)`: the species' learnset up to `level` (Game Knowledge)
   ranked by *observed* effectiveness where we have data, ROM values where we do not; suggested move set (best
   4 by expected damage vs common opponents on the route, with one status move if its observed effect was useful).
   Used when the agent catches or receives that species (log the plan; the move-learning decision may prefer a
   playbook move over the current rule only when observed data has n >= 5).
3. **Counter planner** `explorer/counters.py`: for an opponent (species, level, known moves), score each of our
   party members: expected damage we deal (our best move x type x STAB x our stats) vs expected damage taken (their
   observed/learned moves vs our types and stats), turns-to-KO both ways. Outputs: best lead, best switch-in when the
   current battler is losing (ratio below a named threshold), and a per-opponent counter table cached in
   maps.json `counters`. Battle behaviour uses it for **trainer battles only** (wild battles keep current logic):
   choose the lead before a gym (reorder through the party procedure from the Magikarp work if merged), and switch
   when the counter planner says another member wins clearly - never into a fainted / sub-25%-HP member, never more
   than one switch per two turns.
   **Switch precedence with Magikarp switch-training** (if merged): while the trainee (Magikarp) leads, its
   turn-one `switch_out_lead` happens first and is not counted against the one-switch-per-two-turns limit; the
   counter planner only chooses WHICH member comes in (its best counter instead of "strongest healthy"). After that
   first turn the counter planner's switch rule applies normally. The trainee is never chosen as a counter.
   Damage math uses the battler's own types (wBattleMon 0xD019/0xD01A, fixed by Battle Types - merged).
4. **Team planning view** (report-only): `tools/team_plan.py` prints, for the next gym's party (trainer data), which
   of our members counters each enemy and which catchable species on the current route (encounter tables) would
   fill a gap - "catch ODDISH on Route 24: GRASS beats Misty's STARYU/STARMIE".
5. Viewer/decision log: rule strings like `counter: SQUIRTLE vs GEODUDE (WATER x2, 2 turns vs 6)`.

## 3. The work

All scoring pure and tested; behaviour changes limited to trainer-battle lead/switch choice with named thresholds
(register them in the Live Control params registry if it exists).

## 4. What NOT to do

- No changes to wild-battle flee/catch/potion logic or move-choice scoring beyond the playbook rule in item 2.
- No new dependencies; no module over 300 lines; never commit ROM bytes or kb/.

## 5. Verification

- `uv run pytest -q` green; tests for species-book updates from battle text, playbook ranking, counter scores
  (a water type counters a rock type; a resisted matchup loses), switch rule limits, swarm merge.
- ROM: a 4,000-step run fills `species_book` for the route's species (report the top 5 entries) and, at a gym
  checkpoint, the counter planner's lead choice and table (report it for Brock from `to_gym.state` if present).

## 6. Rules for this run

- Branch `directive/pokeagent-opponent-modeling-directive` in a scratchpad worktree off main. Never commit to
  `main`. Test command `uv run pytest -q`. Never bare `python`.

## 7. Completion criteria

- [ ] species book + swarm merge; playbook; counter planner + trainer-battle lead/switch; team_plan tool
- [ ] Tests and ROM checks in section 5 pasted

## 8. Report

Species-book sample, counter table for Brock (or the nearest gym), test tail, anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | claude |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-09 19:19 · agentflow-tick · none → Queued — suggested by heartbeat: Needs local ROM/kb verification and a design call on overlap with team_plan; use a Sonnet builder.
<!-- queue:end -->
