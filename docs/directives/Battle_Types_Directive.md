# PokeAgent: battle types - fix STAB to the active battler, learn effectiveness from the battle text, generalise by type

**Read first:** `docs/superpowers/specs/2026-11-05-viewer-and-hybrid-design.md` section 5.
**Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-05): "Does our model recognize and learn from when a not very effective attack and type is used,
as well as the types of the pokemon it's facing and the types for moves?"

What exists (`src/pokeagent/explorer/battle.py` `move_scores`, used by `behaviours/battle_moves.py`):

```python
    chart = {(a, d): e for a, d, e in ROM_KB["type_chart"]}
    enemy_types = {ROM_KB["moves"]["1"]["type"]} if False else set()
    et1, et2 = emu.read(0xCFEA), emu.read(0xCFEB)
    ...
    enemy_types = {inv.get(et1, "?"), inv.get(et2, "?")}
    my_types = {inv.get(emu.read(0xD170), "?"), inv.get(emu.read(0xD171), "?")}
    ...
        eff = 1.0
        for t in enemy_types:
            eff *= chart.get((mv["type"], t), 1.0)
        stab = 1.5 if mv["type"] in my_types else 1.0
        score = mv["power"] * eff * stab * mv["accuracy"] if pp > 0 else 0.0
```

So: **types are known** (enemy types from wEnemyMon 0xCFEA/0xCFEB; move types, power, accuracy and the type chart
drained from the cartridge into `kb/rom_tables.json`), and move choice multiplies power x effectiveness x STAB x
accuracy. Observed damage is recorded in `damage_dealt` keyed by our species+level, move, enemy species+level,
and used only as a tiebreak.

Gaps:
1. **STAB reads the wrong Pokemon.** 0xD170/0xD171 are wPartyMon1's types (party slot 1), not the battler in
   play. In pokered, wBattleMon starts at 0xD014: species 0xD014, HP 0xD015-6, level-in-box 0xD017, status
   0xD018, **type1 0xD019, type2 0xD01A**, then moves 0xD01C-F (the code already reads moves here) and PP
   0xD02D-30 (also already read here). After a switch or a faint, STAB is computed for the wrong Pokemon.
2. **The battle text is ignored.** "It's super effective!", "It's not very effective...", "It doesn't affect
   <ENEMY>..." and critical hits are never parsed, so the agent never checks the type chart against reality and
   never learns a matchup it has no chart entry for.
3. **Learning does not generalise.** `damage_dealt` is keyed by enemy *species*: a lesson against one BUG/POISON
   Pokemon teaches nothing about the next one.
4. **The enemy's moves are not typed.** "Enemy X used Y!" is parsed for the name only; the move type/power from
   the ROM table is never used to judge how dangerous the opponent is.
5. Dead line: `enemy_types = {...} if False else set()`.

## 2. Scope (in order)

1. Verify 0xD019/0xD01A on the ROM is not possible in your sandbox - write a unit test with `FakeEmulator`, and
   add both addresses to `docs/KNOWLEDGE.md` as "from pokered wBattleMon layout, consistent with the moves at
   0xD01C and PP at 0xD02D already in use; controller verifies on the ROM". Switch `my_types` to them. Remove the
   dead line.
2. `explorer/battle_text.py`: `parse_effect(text) -> {"effect": "super"|"weak"|"none"|None, "crit": bool}` for
   the four messages (match case-insensitively on "super effective", "not very effective", "doesn't affect",
   "critical hit").
3. Effectiveness ledger in memory: `data["type_effect"]["<MOVE_TYPE>><DEF1>/<DEF2>"] = {"super", "weak", "none",
   "neutral", "n"}` updated after each of our attacks (neutral when a damaging move hit with no effect message).
   `chart_disagreements` list when the observed effect contradicts the ROM chart (expected: never - it is a check
   on the drained table).
4. Generalised damage lessons: alongside the existing `damage_dealt` key, record
   `damage_by_type["<MOVE>|<DEF1>/<DEF2>"]` (mean fraction of enemy max HP per hit, n). `move_scores` uses the
   ROM score as before; the observed tiebreak looks up the species key first, then the type key.
5. Enemy threat: from "used <MOVE>!" look up the ROM move (type, power); record `threat_by_species` and compute a
   simple threat score (power x effectiveness against our battler's types x STAB). The battle behaviour's existing
   potion/flee rule may use it only as an additional input when HP is already below its current threshold - do
   not change the thresholds.
6. Viewer: the battle `sees` view (`battle_view`) and the snapshot's `thinking.rule` show the chosen move with
   its multiplier and types, e.g. `EMBER x2 FIRE>GRASS/POISON STAB`.

## 3. The work

Keep type ids/names in one table (move the inline `names` dict into `battle.py` module scope or a small
`types.py`); Gen 1 type ids: NORMAL 0, FIGHTING 1, FLYING 2, POISON 3, GROUND 4, ROCK 5, BUG 7, GHOST 8, FIRE 20,
WATER 21, GRASS 22, ELECTRIC 23, PSYCHIC 24, ICE 25, DRAGON 26.

## 4. What NOT to do

- Do not change HP thresholds, flee/potion rules, catch logic, or the move-learning rule.
- Do not edit `kb/rom_tables.json` (ROM-derived, gitignored); read it only.
- No new dependencies; no module over 300 lines.

## 5. Verification

- `uv run pytest -q` green (paste before/after).
- Tests: STAB uses 0xD019/0xD01A (fake battler with types different from party slot 1); `parse_effect` on the
  four messages and on plain text; ledger update and chart-disagreement detection; type-keyed damage lookup
  fallback; threat score for a sample enemy move; the formatted rule string.
- Do NOT run `uv run pokeagent ...` or the demo. Controller ROM check: read 0xD019/0xD01A during a battle and
  compare with the species' types; a 3,000-step run records `type_effect` entries with no chart disagreements.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-battle-types-directive`. Never commit to `main`.
- Create no scratch or debug files; if unavoidable, under `.devin-scratch/` and it stays.

## 7. Completion criteria

- [ ] STAB from the active battler; dead line removed; KNOWLEDGE.md entry
- [ ] `battle_text.parse_effect`; `type_effect` ledger with disagreement check; `damage_by_type`; enemy threat
- [ ] Rule string shows multiplier and types
- [ ] Tests in section 5 pass; `uv run pytest -q` green (paste the tail)
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts, and anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Review |
| Assigned to | devin |
| Branch | directive/pokeagent-battle-types-directive |
| Base branch | - |
| Base commit | 693a070d8d7840c8688bff459b89c9c8427372c4 |
| Head commit | 7dcc2f06f72dfe7a1d8d6c596c140fa219169b2a |
| Head remote | rfd62794/pokeagent |
| Model | swe-2-flash-max |

**Status log**
- 2026-11-05 19:34 · robert-claude-laptop · none → Queued — Robert asked 2026-11-05 (type learning); STAB reads party slot 1
- 2026-11-05 19:43 · robert-claude-laptop · Queued → Approved — lint override: greenfield directive: cited new paths are files it creates
- 2026-11-05 19:43 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-battle-types-directive; lane=explicit; model=swe-2-flash-max; persona=steady-builder; agent_id=01M6Q4Z8KYRVZ2X524BCHC1H63
- 2026-11-05 19:45 · dispatcher · launched pid=3080; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-battle-types-directive; provisioned: uv sync --frozen
- 2026-11-05 20:01 · devin · In progress → Review — 285 passed, 5 skipped (uv run pytest -q). STAB now reads wBattleMon 0xD019/0xD01A; battle_text.py parses super/weak/none/crit; type_effect + chart_disagreements + threat_by_species + damage_by_type ledgers live in MapMemory.data; move_choose Decision.rule and battle sees carry 'EMBER x2 FIRE>GRASS/POISON STAB'. ROM verification of 0xD019/0xD01A deferred to controller per directive. [origin] spent: devin 16 min est. n/a
<!-- queue:end -->
