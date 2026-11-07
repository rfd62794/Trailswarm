# PokeAgent: Team Builder V2 - value-ranked catching, a Pokedex objective and a `team_ready` gate, so the team is built early and the Gyarados is just one candidate

**Depends on (all merged to main; if one is missing from your worktree, stop and write that in the Status row):** PR #142 (`knowledge/readiness.py`
`team_readiness` / `TeamReadiness` / `MemberNeed` / `TEAM_GAP` / `LEAD_HURT` / `TEAM_MIN`, the `gyarados` ladder goal, `trainee_slot_for`, `explorer/training.py::team_for`)
and PR #143 (`knowledge/cut_learner.py::pick_target`, `behaviours/learner_hunt.py`, `catch_list.catch_target_map`, `ctx.hunt_grass`).
**Do not list the tree recursively**; use `git ls-files`.

**Read first (all in the worktree):** `src/pokeagent/knowledge/readiness.py` (`assess`, `team_readiness`, `fight`, `MARGIN`), `knowledge/party.py` (`Combatant`, `trainer_mon`, `at_level`, `our_party`),
`knowledge/trainers.py` (`boss_party`, `GYM_BOSSES`, `LEADER_BOSSES`, `RIVAL_BOSSES`), `knowledge/encounters.py` (`where_to_catch`, `species_on`, `slot_chances`, `map_name`),
`knowledge/cut_learner.py` (the `pick_target` / `LearnerTarget` pattern to copy: pure, tables passed in, `distance` callable), `explorer/catch_list.py`, `explorer/behaviours/catch.py`,
`explorer/behaviours/learner_hunt.py` (the walk-to-grass sibling to copy), `explorer/behaviours/party_order.py`, `explorer/behaviours/plan_goal.py`, `explorer/training.py`,
`src/pokeagent/goals.py`, `src/pokeagent/magikarp.py`, `src/pokeagent/data/campaign.json`, `grind/xpmath.py` (`exp_for_level`, `xp_needed`, `xp_gain`), `grind/atlas.py` (`prior_xp`),
`explorer/economy/budget.py` (`reserve`, `spendable`, `blackout_cost`), `explorer/economy/floor.py` (`potion_floor`, `FLOOR_MIN`), `explorer/economy/heal_items.py` (`heal_count`),
`explorer/restock.py` (`ball_price`), `docs/ROADMAP.md`, and the tests named in section 4.5.

## 1. Why this exists

Robert (2026-11-07): "work toward team optimization and capture earlier on. We can have a team before Magikarp, and the Gyarados is a bit of a side quest goal, we don't know that the goal pays toward
the long term plan or is simply a quick gate to Pokedex and team variety expansion." And: "explore all starters equally" and "optimize for a no blackout run" (blackouts spend a finite money pool:
trainer prizes are one-time, wild pays nothing, measured today; a Gen 1 blackout halves the money, `economy/budget.py::blackout_cost`).

Robert (2026-11-07, later): "The ability to complete the pokedex gates certain items later, we should train this as a goal along the way to complete where possible, while being cost efficient, and find the best
catch methods for each opportunity, including exploring and exploiting special moves and status, like paralyze and burn. It also needs to recognize the overpower gate, where the high level lead pokemon will always
wipe a wild pokemon, and explore ways to avoid this, like having a level band across the party, or a lower level last option for wild exploit."
This directive carries the Pokedex objective and the "catcher" role. The catch METHODS (status, minimum damage, ball choice, the overpower switch) are a separate, later directive (`Catch_Methods_Directive.md`); here we only
reserve the seam for them (section 4.4) and the `catcher` roster slot.

What exists today (read from the code 2026-11-07, after PR #142 and #143):
- `team_readiness(party, boss, label)` judges the whole party against one boss with the lead hurt (`LEAD_HURT` = 0.5). It treats a MAGIKARP specially (judged as the GYARADOS it becomes at L20).
- The `gyarados` goal is a LADDER goal right after `nugget_bridge` (`campaign.json`): "raise the bought Magikarp to Gyarados". That makes ONE candidate (Magikarp -> Gyarados) a mandate and says nothing about
  the other mons. `plan_goal.py` forces the gate to `EVOLVE_LEVEL + TEAM_GAP` (26) whenever a Magikarp is in the party at that stage, `GRIND_BATTLES_GYARADOS` = 120 battles, then settles by `GYARADOS_IDLE_CAP` / `GYARADOS_STEP_CAP`.
- Catching is reactive: `catch_list.catch_wanted` answers only "can learn an HM we still need" or "new species while dex < 10 and a `dex10` goal is ahead". Nothing ranks species by what they add to the team or to the Pokedex,
  and nothing sends the agent to a map to find one except the Cut-only `learner_hunt`. The only Pokedex gate in the repo is the `route2_gate` / `hm05_flash` pair in `campaign.json` (note: "Oak's aide wants 10 species caught"; `hm05_flash`
  needs `dex10`, and its item id is a candidate, not verified). `catch_list.dex_owned_count(emu)` counts the owned bits (wPokedexOwned 0xD2F7, 19 bytes).
- The wild tables already hold the early options (pasted in section 2): Nidoran(M)/(F) on Route 22 (west of Viridian, before Brock), Pikachu/Caterpie in Viridian Forest, Paras/Clefairy in Mt Moon, Oddish on Route 24/25.

This directive replaces "the Gyarados is the plan" with "a value-ranked catch plan in which the Gyarados is one candidate, the Pokedex is a standing cost-weighted objective, and a `team_ready` gate sits before the ship stage".

**Old draft folded in / superseded:** `docs/directives/Team_Builder_Directive.md` (2026-11-05, never queued) is SUPERSEDED by this file.
- Folded in: its "team plan scores candidate teams from {owned} + {catchable on reachable routes} against the next bosses" (now `team_value.py`), "targeted catching within a detour budget" (now `catch_plan.py` + `team_hunt`),
  "catch only planned targets" (now the `catch_wanted` seam), "never release/discard Pokemon" (kept in section 5), and its named-constant rule.
- Superseded, NOT in this PR: shopping goals and Mart reserve rules (shopping stays as it is; we only READ `budget.reserve` / `spendable`), PC deposit/withdraw party management (out of scope unless trivially reusable: it is
  not, so the plan simply stops at 6), status-first catching (moves to `Catch_Methods_Directive.md`), DV keep-best, the metrics/cockpit section, general training allocation (the merged `trainee_slot_for` already does the useful part),
  and the battle-simulator rollouts.
- Its "Magikarp switch training" dependency is merged (PR #142 and earlier); `buy_magikarp` is untouched.

## 2. Facts (verified on the live checkout 2026-11-07; pasted because you cannot read `kb/` or `runs/` in the worktree)

- `uv run python --version` prints `Python 3.12.12`. Always `uv run`; never bare `python`.
- Full suite: `uv run pytest -q` (about 100 s; 1557 passed, 1 skipped on the live checkout today, plus one environment-dependent failure `tests/test_resources.py::test_lock_takeover_is_exclusive` (a lock/process test, unrelated; ignore it and say so if it fails for you)). Per item: `uv run pytest -q tests/<file>`.
- `roms/`, `baselines/`, `runs/`, `kb/rom_tables.json` and `kb/hm_compat.json` are gitignored. **Your worktree has NO ROM, no `kb/` tables, no `.state` baselines and no `runs/` data.**
  Every test uses `FakeEmulator` (`from pokeagent.emulator import FakeEmulator`: `FakeEmulator({addr: byte, ...})`, `.memory`, `.read`, `.read_range`, `.set`) and FIXTURE tables passed in as dicts.
  Copy the synthetic cartridge pattern from `tests/test_team_readiness.py` (its own `SYN`-style dict plus the `_species` / `_mv` helpers) and `tests/test_cut_learner.py` (the `WILD` fixture, `party_mem` helper,
  `ExplorerContext` construction for behaviour tests). Do NOT edit `tests/test_knowledge.py`.
- Data shapes: `wild_by_map` is `{map id (str in the JSON): {"grass_rate": int, "grass": [[level, SPECIES] x10], "water_rate": int}}`. Slot chances per encounter (Gen 1) are `slot_chances()` =
  51,51,39,25,25,25,13,13,11,3 of 256. Per-species rows in `species_by_dex`: `{hp, atk, def, spd, spc, type1, type2, catch_rate, base_exp, name, moves1, growth}`; `growth` is `MEDIUM_FAST | MEDIUM_SLOW | FAST | SLOW`
  (`exp_for_level` takes it). Species names use the ROM spelling, e.g. `NIDORAN(M)`, `NIDORAN(F)`.
- **The kb has NO evolution table and NO in-game trade table** (keys of `kb/rom_tables.json`: source, moves, type_chart, species_by_dex, dex_of_internal, name_of_internal, learnsets, items, wild_by_map, trainers, map_trainers).
  So evolution levels come from a small constant dict you add in `team_value.py` (section 4.1), and in-game trades are OUT OF SCOPE (say "trades: out of scope, no table" in the module docstring and the report).
- **Pokedex gate thresholds are NOT verified in this repo** (the only recorded one is 10, from the `route2_gate` note). They are a constant `DEX_GATES = (10, 30, 50)` with the comment "thresholds to verify on the ROM; candidates
  10, 30, 50 (Oak's aides); only 10 is recorded in campaign.json". Do not claim more. The controller verifies them on the ROM later and edits the constant.
- `grind/atlas.py::prior_xp(row, base_exp)` = expected XP per wild encounter on a map for ONE participant (no sharing). Measured on the live tables today: Route 1 23, Route 2 28, Route 22 26, Viridian Forest 38,
  Route 3 51, Route 24 96, Route 6 130. `src/pokeagent/explorer/economy/hp_stats.py` is an HP-LOSS statistic, NOT an XP source: do not use it for XP. The fixed fallback when no map table is available is
  `XP_PER_FIGHT_FALLBACK = 40` (a named constant; roughly the Route 2-3 range), halved for a switched-out trainee (Gen 1 splits experience among participants).
- Experience still needed, from `exp_for_level` on the live growth groups: SLOW (Magikarp) L13 -> L20 = 7,254 XP; MEDIUM_SLOW (starters, Oddish, Nidoran) L1 -> L16 = 2,535 XP.
  `species_by_dex`: MAGIKARP base_exp 20, SLOW; GYARADOS base_exp 214, SLOW, WATER/FLYING; NIDORAN(M) 60, MEDIUM_SLOW; NIDORAN(F) 59; PIKACHU 82, MEDIUM_FAST; CATERPIE 53, MEDIUM_FAST; PARAS 70, MEDIUM_FAST;
  CLEFAIRY 68, FAST; ODDISH 78, MEDIUM_SLOW; ABRA 73, MEDIUM_SLOW; catch rates: NIDORAN 235, ODDISH 255, CATERPIE 255, PARAS 190, PIKACHU 190, ABRA 200, CLEFAIRY 150, MAGIKARP 255, GYARADOS 45.
- The campaign's remaining bosses come from `trainers.boss_party(goal, kb, starter_names)`; the ladder order of boss goals is `training.TRAIN_LEVEL_BY_GOAL` sorted by `GOALS.index` (beat_brock, to_mt_moon (strongest Mt Moon trainer),
  beat_misty, rival_ss_anne, beat_surge, ... beat_champion). Today's first rival party (Red, class `RIVAL2`): `[[19, PIDGEOTTO], [16, RATICATE], [18, KADABRA], [20, WARTORTLE]]` (variant by our starter).
  BROCK (ROM): `[[12, "GEODUDE"], [14, "ONIX"]]`.
- Budget facts: `budget.reserve(goals, money, ref_money=0)` = `FLOOR(300) + 100 * bosses beaten + blackout_cost(money) // 2`; `budget.spendable(goals, money, ref_money=0)`; `floor.FLOOR_MIN` = 1 Potion;
  `restock.ball_price()` is 200 by default (read from the ROM items table when present); `heal_items.heal_count(bag)`; `goals.bag_contents(emu)` -> `{item id: qty}` (Poke Ball = 0x04); `ctx.blackouts_row` is the blackout streak.
- Existing seams to reuse: `ctx.goals()` (the goal dict; `ctx` itself is the `st` that `check_goals` reads), `ctx.mem.data["maps"]` (learned maps), `WorldGraph(...).path(...)` as used in `learner_hunt.py`,
  `perceive.party_hp(emu) -> (hp, max_hp)`, `perceive.lead_level(emu)`, `explorer.world.SHIP_MAPS` / `DUNGEON_MAPS`, `ctx.center_intent`, `ctx.view` (`m`, `x`, `y`, `battling`, `box`), `ctx.proc`.
- **Files you must NOT modify:** `src/pokeagent/explorer/ship_gate.py`, `planner.py`, `planner_east.py`, `planner_checkpoint.py`, `tools/seg_*.py`, `tools/segments.py`. Read them if you must.

### The Red wild grass rows (drained from the ROM, `kb/rom_tables.json` `wild_by_map`; chance = share of grass encounters, from the 51/51/39/25/25/25/13/13/11/3 slot table)

| map id | name | grass rate | slots (level SPECIES, slot 0..9) | catch-plan species (chance per encounter) |
|---|---|---|---|---|
| 0x0C | Route 1 | 25 | 3 PIDGEY, 3 RATTATA, 3 RATTATA, 2 RATTATA, 2 PIDGEY, 3 PIDGEY, 3 PIDGEY, 4 RATTATA, 4 PIDGEY, 5 PIDGEY | none |
| 0x0D | Route 2 | 25 | 3 RATTATA, 3 PIDGEY, 4 PIDGEY, 4 RATTATA, 5 PIDGEY, 3 WEEDLE, 2 RATTATA, 5 RATTATA, 4 WEEDLE, 5 WEEDLE | WEEDLE L3-5 (0.152) |
| 0x21 | Route 22 | 25 | 3 RATTATA, 3 NIDORAN(M), 4 RATTATA, 4 NIDORAN(M), 2 RATTATA, 2 NIDORAN(M), 3 SPEAROW, 5 SPEAROW, 3 NIDORAN(F), 4 NIDORAN(F) | NIDORAN(M) L2-4 (0.395), NIDORAN(F) L3-4 (0.055) |
| 0x33 | Viridian Forest | 8 | 4 WEEDLE, 5 KAKUNA, 3 WEEDLE, 5 WEEDLE, 4 KAKUNA, 6 KAKUNA, 4 METAPOD, 3 CATERPIE, 3 PIKACHU, 5 PIKACHU | PIKACHU L3-5 (0.055), CATERPIE L3 (0.051), METAPOD L4 (0.051), WEEDLE (0.449) |
| 0x3B | Mt Moon 1F | 10 | 8 ZUBAT, 7 ZUBAT, 9 ZUBAT, 8 GEODUDE, 6 ZUBAT, 10 ZUBAT, 10 GEODUDE, 8 PARAS, 11 ZUBAT, 8 CLEFAIRY | PARAS L8 (0.051), CLEFAIRY L8 (0.012) |
| 0x3C | Mt Moon B1F | 10 | 8 ZUBAT, 7 ZUBAT, 7 GEODUDE, 8 GEODUDE, 9 ZUBAT, 10 PARAS, 10 ZUBAT, 11 ZUBAT, 9 CLEFAIRY, 9 GEODUDE | PARAS L10 (0.098), CLEFAIRY L9 (0.043) |
| 0x3D | Mt Moon B2F | 10 | 9 ZUBAT, 9 GEODUDE, 10 ZUBAT, 10 GEODUDE, 11 ZUBAT, 10 PARAS, 12 PARAS, 10 CLEFAIRY, 12 ZUBAT, 12 CLEFAIRY | PARAS L10-12 (0.148), CLEFAIRY L10-12 (0.062) |
| 0x0E | Route 3 | 20 | 6 PIDGEY, 5 SPEAROW, 7 PIDGEY, 6 SPEAROW, 7 SPEAROW, 8 PIDGEY, 8 SPEAROW, 3 JIGGLYPUFF, 5 JIGGLYPUFF, 7 JIGGLYPUFF | JIGGLYPUFF L3-7 (0.105) |
| 0x0F | Route 4 | 20 | 10 RATTATA, 10 SPEAROW, 8 RATTATA, 6 EKANS, 8 SPEAROW, 10 EKANS, 12 RATTATA, 12 SPEAROW, 8 EKANS, 12 EKANS | none new (EKANS) |
| 0x23 | Route 24 | 25 | 7 WEEDLE, 8 KAKUNA, 12 PIDGEY, 12 ODDISH, 13 ODDISH, 10 ABRA, 14 ODDISH, 13 PIDGEY, 8 ABRA, 12 ABRA | ODDISH L12-14 (0.246), ABRA L8-12 (0.152) |
| 0x24 | Route 25 | 15 | 8 WEEDLE, 9 KAKUNA, 13 PIDGEY, 12 ODDISH, 13 ODDISH, 12 ABRA, 14 ODDISH, 10 ABRA, 7 METAPOD, 8 CATERPIE | ODDISH L12-14 (0.246), ABRA L10-12 (0.148), CATERPIE L8 (0.012) |
| 0x10 / 0x11 | Route 5 / Route 6 (identical) | 15 | 13 ODDISH, 13 PIDGEY, 15 PIDGEY, 10 MANKEY, 12 MANKEY, 15 ODDISH, 16 ODDISH, 16 PIDGEY, 14 MANKEY, 16 MANKEY | ODDISH L13-16 (0.348) |

(Your fixtures copy these rows; the arithmetic is `encounters.where_to_catch` / `species_on` / `slot_chances`: do not hard-code the chances.)

## 3. Scope (one PR, in order)

1. `src/pokeagent/knowledge/team_value.py` (pure): value of a candidate party member, including the Pokedex term and the `catcher` role.
2. `src/pokeagent/knowledge/catch_plan.py` (pure): ranked "catch species S on map M" actions, including cheap new-species actions with no boss value.
3. The ladder change: `gyarados` -> `team_ready` (campaign.json, goals.py, plan_goal.py, a pure detector helper), keeping the Magikarp switch-training machinery as an action.
4. The behaviour seam: `catch_list.catch_wanted` takes the plan's wants; `behaviours/catch.py` passes them; new `behaviours/team_hunt.py` walks to the best action's map (sibling of `learner_hunt.py`).
5. Tests: `tests/test_team_value.py`, `tests/test_catch_plan.py`, `tests/test_team_hunt.py`; update the existing tests named in 4.3.

## 4. The work

Starters are explored EQUALLY (Robert): no new code may read `opts.starter` or branch on a starter name for scoring, and every test that touches a starter runs for all three lines
(`@pytest.mark.parametrize` over Squirtle, Bulbasaur, Charmander parties). Every threshold below is a NAMED module constant, with a comment saying it is an untuned first value.

### 4.1 `knowledge/team_value.py` (pure, no emulator, no ROM; under 300 lines; split a `knowledge/dex_value.py` if it would pass that)

```python
EVOLUTIONS: dict[str, tuple[str, int]]   # species -> (next form, level), level evolutions only; stone / trade evolutions stay the base form
# Gen 1 (pokered). The kb has no evolution table, so this is a constant; KEEP IT SMALL and say in the docstring that it is not ROM-verified:
#   SQUIRTLE (WARTORTLE,16) WARTORTLE (BLASTOISE,36) BULBASAUR (IVYSAUR,16) IVYSAUR (VENUSAUR,32) CHARMANDER (CHARMELEON,16) CHARMELEON (CHARIZARD,36)
#   MAGIKARP (GYARADOS,20) NIDORAN(M) (NIDORINO,16) NIDORAN(F) (NIDORINA,16) CATERPIE (METAPOD,7) METAPOD (BUTTERFREE,10) WEEDLE (KAKUNA,7) KAKUNA (BEEDRILL,10)
#   ODDISH (GLOOM,21) PARAS (PARASECT,24) ABRA (KADABRA,16)
BOSS_HORIZON = 6               # remaining bosses scored (beyond that a member is speculation); untuned
CONTRIB_MARGIN = 0.10          # X: a member also "contributes" when it raises the hurt-lead sim margin by at least this much; untuned
COST_PER_FIGHT = 0.01          # value units per training fight (100 fights = one boss contribution); untuned
XP_PER_FIGHT_FALLBACK = 40     # see section 2; halved for a switched-out trainee
TRAINEE_SHARE = 0.5
MAGIKARP_START_LEVEL = 5       # ASSUMPTION (not verified): used only when no Magikarp is owned; an owned one uses its real level
DEX_GATES = (10, 30, 50)       # owned-count thresholds that unlock items (Oak's aides); ONLY 10 is recorded in campaign.json - the rest are to verify on the ROM
DEX_GATE_VALUE = 1.0           # value of reaching the next gate, in boss-contribution units, spread over the species still missing to reach it; untuned
DEX_FLOOR_VALUE = 0.05         # a new species with no gate in sight still counts a little (variety); replaces the old flat bonus; untuned
CATCHER_BAND = 6               # a "catcher" is a member whose level is >= this many below the lead's (the lower-level wild-exploit option); untuned

@dataclass(frozen=True)
class Candidate:  species: str; level: int; source: str      # source: "party-evolution" | "wild:<map id>" | "magikarp" | "catcher"
@dataclass(frozen=True)
class MemberValue:
    candidate: Candidate; target_level: int | None            # the lowest level the sim needs for the team to be ready (None = never enough by MAX_LEVEL)
    contributes: tuple[str, ...]                              # boss labels it contributes to
    gain: float; fights: int; cost: float; dex: float; catcher: float; value: float   # value = gain + dex + catcher - cost

def form_at(species: str, level: int) -> str            # the form a mon has at `level`, following EVOLUTIONS
def fights_to_reach(species: str, from_level: int, to_level: int, xp_per_fight: float | None, kb=None, trainee: bool = False) -> int
def pokedex_value(species: str, owned_count: int, owned_species: frozenset[str], gates=DEX_GATES) -> float
def catcher_value(party: list, lead_level: int, wild=None, kb=None) -> float   # wild = [(level, species)] of the planned map; no wild data -> 0.0 (cannot prove a safe hit)
def member_value(candidate, party, bosses, xp_per_fight=None, owned_species=(), owned_count=0, kb=None) -> MemberValue
def candidates_for(party, wild_by_map, maps, magikarp_level: int | None, kb=None) -> list[Candidate]
```

- `bosses` = `[(label, [(level, species)])]` for the next `BOSS_HORIZON` boss goals not yet met, built by the caller from `trainers.boss_party` (the caller owns the goals/kb lookups; the module itself takes the list).
- A member "contributes" to boss `b` when `team_readiness(party + [member at L], b).ready` and NOT `team_readiness(party, b).ready`, OR the hurt-lead margin
  (`fight([replace(lead, hp=int(lead.hp * LEAD_HURT)), *others], theirs, chart, moves)`, the same sim `team_readiness` uses) improves by at least `CONTRIB_MARGIN`. `gain` = the count of bosses it contributes to
  (each 1.0, in order; no discount). The candidate is simulated at the level the sim needs (`target_level`: the lowest L from the caught level up to `MAX_LEVEL` at which it contributes; a candidate that already contributes
  at its caught level has target = caught level). Reuse `readiness.team_readiness`, `fight`, `trainer_mon`, `at_level`; do NOT copy their logic, and do not edit `readiness.py` beyond (at most) exporting a small helper.
- `fights` = `fights_to_reach(species, caught_level, target_level, xp_per_fight)` = `ceil(xp_needed(growth, caught_level, target_level) / xp)`, with `xp` = `xp_per_fight` (a caller-supplied expected XP per fight, normally
  `grind.atlas.prior_xp` of the map it trains on) or `XP_PER_FIGHT_FALLBACK`; a trainee (switched out) earns `TRAINEE_SHARE` of it. `cost = fights * COST_PER_FIGHT`.
- **Pokedex is a standing objective, not a flat bonus (Robert).** `pokedex_value(S, owned_count, owned_species)` is 0 when `S` (its base form) is already owned; otherwise `DEX_FLOOR_VALUE` plus, when a gate `G` in `DEX_GATES` with
  `G > owned_count` exists, `DEX_GATE_VALUE / (G - owned_count)` (progress toward the NEXT gate: each missing species is worth a share of the gate's item, so the last species before a gate is worth the most). Past the last gate only the floor
  remains. It is a function of the owned COUNT (`catch_list.dex_owned_count`), so it needs no table beyond `DEX_GATES`. `member_value.dex` is that number. Because it enters `value`, a species with no boss contribution can still have `value > 0`.
- **`catcher` role (Robert's "lower level last option for wild exploit").** `catcher_value(party, lead_level, wild=None, kb=None)` = a small positive value (`CATCHER_VALUE = 0.15`, named, untuned) when NO member of the party is within `CATCHER_BAND` levels BELOW the lead
  (nobody can fight a wild mon without wiping it: the overpower gate), else 0. **HARD RULE (Robert, 2026-11-07): "a cheap low-level member only has value as the catcher if they can cause damage. Magikarp does not apply without an attack to cause damage."** A member counts as a catcher ONLY if it has a DAMAGING move (`power > 1`) whose expected damage against the route's wild species is `> 0` and `< that wild mon's HP` (`knowledge/damage.expected_damage`, evaluated on the species of the planned map at their lowest slot level; use the minimum roll, i.e. `expected_damage` scaled by `MIN_ROLL = 217/255 / AVG_ROLL`, a named constant, so a hit that can KO at min roll is not 'safe'). A Splash-only Magikarp (below L15, where it learns Tackle) is NOT a catcher; a status-only move set is NOT a catcher either (status moves are a bonus for the catch methods, never the qualification). `catcher_value` returns 0 for a non-qualifying member, and a candidate qualifies for `source="catcher"` only under this rule. A candidate whose caught level is `<= lead_level - CATCHER_BAND` and that qualifies gets `source="catcher"` and `member_value.catcher = catcher_value(...)`.
  So the plan prefers catching one low-level mon as the party's wild-capture slot when the party has none. This directive only SCORES the role; choosing it in battle belongs to `Catch_Methods_Directive.md`. Do not add battle code for it.
- `candidates_for`: (a) every wild species in grass tables of the maps in `maps` (the reachable set the caller passes), each at the lowest level its table gives, with `form_at` applied at the level the sim will test it;
  (b) the evolutions of current party members (so training the lead's own line is scored like the others: `source="party-evolution"`); (c) ONE Magikarp candidate (`source="magikarp"`, species MAGIKARP, judged as its GYARADOS
  projection via `EVOLUTIONS`/`trainer_mon("GYARADOS", ...)`) from `magikarp_level` (the owned Magikarp's level, or `MAGIKARP_START_LEVEL` when none is owned), so the Gyarados is scored exactly like every other candidate and
  can lose. (d) In-game trades: out of scope. Species with no `species_by_dex` row, or not in a `wild_by_map` slot, are skipped silently. Water slots are not candidates (no Surf yet), as in `cut_learner`.
- It never raises on empty inputs (returns `[]` / a zero-value `MemberValue`).

### 4.2 `knowledge/catch_plan.py` (pure; under 300 lines)

```python
TEAM_SIZE = 6
CATCH_HP_FACTOR = 2.0          # untuned: a weakened (<=35% HP) target is about twice as catchable as the raw (catch_rate + 1) / 256
BALL_MARGIN = 2                # spare balls on top of the expected need
STEPS_PER_BALL = 20            # presses spent on one throw (weaken + ITEM menu); untuned
MAP_DISTANCE_FALLBACK = 12     # steps per map-id of distance when the learned graph has no path (|map id difference|)
RISK_LEVEL_MARGIN = 4          # a map whose strongest wild level exceeds the lead level by more than this is skipped (no-blackout run)
CHEAP_STEPS = 600              # an action at or under this many steps is "cheap" (new-species-here actions are always kept up to this)

@dataclass(frozen=True)
class CatchAction:
    species: str; map: int; name: str; levels: tuple[int, int]; chance: float; rate: int
    value: float; steps: float; score: float; balls: int; blocked: str   # blocked == "" when doable now, else the reason ("no balls" ...)
    detour: float; member: "MemberValue"

def p_catch(catch_rate: int) -> float          # min(0.95, (catch_rate + 1) / 256 * CATCH_HP_FACTOR)  (Catch_Methods_Directive replaces this with the real formula)
def expected_balls(catch_rate: int) -> int     # ceil(1 / p_catch) + BALL_MARGIN
def plan_catches(party, here_map, goals, money, balls, owned_count, bosses, wild_by_map, known_maps, lead_level, *, distance=None,
                 magikarp_level=None, xp_for_map=None, owned_species=(), kb=None) -> list[CatchAction]
```

- From the current party, position, badges (via `goals`), money and the Pokedex owned count: candidates from `team_value.candidates_for`, maps = every map in `wild_by_map` that is in `known_maps` or within a sane id distance, scored by `member_value`.
  `steps` = `detour` (the caller's `distance(here_map, map)`; default `abs(map id diff) * MAP_DISTANCE_FALLBACK`; the caller passes a graph-path length as `learner_hunt._graph_dist` does) +
  `256 / rate / max(chance, 1e-6)` (expected grass steps to find the species) + `balls * STEPS_PER_BALL`. `score = value / steps * 1000` (cost-efficiency: balls, detour, encounter chance all sit in `steps`). Rank by `score`, then `value`, then lower map id. Only `value > 0` actions are returned.
- **Cheap new species with no boss value are first-class:** because `value` includes `pokedex_value`, an action whose species is new to the Pokedex and whose `steps <= CHEAP_STEPS` is returned even when `gain == 0`. This is how the Pokedex objective
  gets trained "along the way": the agent grabs a new species when it is on or near the route and the cost is low, and the ladder is never blocked by it.
- **Capped by the reserve and the potion floor:** the plan never plans balls beyond `budget.spendable(goals, money)` (so a hunt never dips into `budget.reserve`), and the caller (team_hunt) refuses to hunt below `floor.FLOOR_MIN` heal items (4.4).
- Pass the graph distance, not the default: in PR #143 the default `|map id|` distance preferred Route 5 over Route 6 and the fix was the graph-path distance (see that PR's Status log).
- Cap at `TEAM_SIZE`: a party of 6 returns `[]` (PC deposit/withdraw is OUT OF SCOPE, the plan stops at 6). An action is `blocked="no balls"` when `balls == 0` and `budget.spendable(goals, money)` could not buy `expected_balls` at
  `restock.ball_price()`; maps whose strongest wild level exceeds `lead_level + RISK_LEVEL_MARGIN` (using `encounters.species_on`) are dropped, not returned. Buying balls stays with the existing `Restock`; do not touch shopping.
- Early-catch requirement: on a fixture of the rows in section 2 with a Brock-stage party, the plan must be able to return Route 22 NIDORAN(M)/(F) (before Brock), Viridian Forest PIKACHU / CATERPIE, Mt Moon PARAS / CLEFAIRY and
  Route 24/25 ODDISH as actions when they are reachable and affordable; which wins is decided by the numbers, not hard-coded. No species is special-cased (no `if species == "NIDORAN(M)"`).

### 4.3 The ladder change: `gyarados` becomes `team_ready`

Smallest change that satisfies the intent: RENAME the ladder goal at the same position (right after `nugget_bridge`, before `to_bill`), widen what settles it, and make the Magikarp training an ACTION the plan chooses.
(The alternative, `gyarados` back to a side goal with `SIDE_GOALS = ["gyarados"]`, would still leave `plan_goal.py` keyed on the ladder position for its 26-level gate; take it only if the rename turns out larger, and say so in the Status row.)

Exact edits (name each in your report):
- `src/pokeagent/data/campaign.json`: the goal `gyarados` -> `team_ready` (`name`: "A party that beats the next boss (hurt-lead sim)"; same `after: nugget_bridge`, `to_bill.after` becomes `team_ready`, `special: true`, `needs: []`).
- `src/pokeagent/goals.py`: the `"gyarados": gyarados_goal_settled(...)` entry becomes `"team_ready": team_ready_settled(emu, st, seen)`; `SIDE_GOALS` stays `[]`; update the comment above it.
- New pure helper `team_ready_settled(emu, st, seen)` (put it in `magikarp.py` next to `gyarados_goal_settled`, or a new `team_ready.py` if `magikarp.py` would pass 150 lines): True when `st.get("had_team_ready")` (sticky), or
  `st.get("team_ready_ok")` (set by `plan_goal` each step from `team_for(goals, party_all).ready` for the next boss, then latched into `had_team_ready`), or `st.get("team_ready_skipped")` (step cap), or `st.get("team_ready_nodata")`
  (no ROM/boss data: never block). It must NEVER block the route. `gyarados_goal_settled` / `gyarados_goal` stay in `magikarp.py` unchanged (the Gyarados evolution still settles through `team_ready_ok` because the sim then sees it).
- `explorer/behaviours/plan_goal.py`: the three `== "gyarados"` stage checks (the `gyarados_stage` line, `_team_need`, and `gy` / `goal = "gyarados"` in `_budgeted`) become `== "team_ready"`; the `ctx.gyarados_*` fields become `ctx.team_ready_*`
  (`explorer/context.py`); the budget key becomes `"team_ready"`. The forced gate `EVOLVE_LEVEL + TEAM_GAP` in `_team_need` applies ONLY when the plan's top action is the Magikarp candidate (`ctx.team_plan[0].member.candidate.source == "magikarp"`)
  or `ctx.train_member` names a MAGIKARP; otherwise the stage's training level is whatever `required_level` gives and the catch plan does the team work. `GRIND_BATTLES_GYARADOS` and `GYARADOS_STEP_CAP` / `GYARADOS_IDLE_CAP` keep their names
  and values (they describe the Magikarp action); the step cap and idle settle now set `ctx.team_ready_skipped`.
- The Magikarp machinery is UNCHANGED: `buy_magikarp`, `party_order.py`, `switch_out.py`, `magikarp.trainee_slot*`, `switch_candidate`, `perceive.lead_level` team seam. A Magikarp that loses the plan simply stays in the party as it does today.
- `magikarp_goal_settled` and the `buy_magikarp` goal are NOT changed.
- Tests that will need updating (update, do not delete): `tests/test_goal_order.py` (the `EXPECTED` ladder line 21, `test_side_goals_stay_empty_and_gyarados_sits_in_the_ladder` ~lines 47-54), `tests/test_campaign.py`
  (the ladder list line 21, the `names`/`key` ordering assertion ~lines 211-212), `tests/test_magikarp.py` (`test_buy_magikarp_sits_before_mt_moon_and_gyarados_is_a_ladder_goal` ~60-64, `test_gyarados_never_blocks_the_ladder` ~84-88, and the
  evolved-Magikarp assertion ~80), `tests/test_team_readiness.py` (the `gyarados` ladder-goal block ~lines 91-104 and the plan_goal stage tests ~149-209: they keep their meaning with `team_ready` and the Magikarp-chosen case), and anything else the full run shows.

### 4.4 The behaviour seam

- `catch_list.catch_wanted(species, party, dex_owned, upcoming, owned=False, wants=None)`: new optional `wants: dict[str, str] | None` (species -> reason, e.g. `"planned: value 1.4 (contributes to MISTY, RIVAL)"` or
  `"planned: new species 8/10 toward the Pokedex gate, 140 steps"`). When `species` is in `wants`, return that reason AFTER the HM check and before the dex check; `wants=None` keeps today's behaviour exactly (all existing `catch_list` tests pass
  unedited). `behaviours/catch.py` passes `wants=ctx.team_wants` and its `(not owned or want.startswith("can learn"))` condition also admits `want.startswith("planned")`. NO other change to `catch.py` (weaken to <=35% then throw stays as is;
  the status / minimum-damage / ball-choice / overpower-switch logic is the NEXT directive, `Catch_Methods_Directive.md`, and is out of scope here).
- `ctx.team_plan: list` and `ctx.team_wants: dict[str, str]` and `ctx.team_hunt_steps: int` (new context fields). New `behaviours/team_hunt.py`, registered right after `LearnerHunt()` in `default_behaviours()` (before `Frontier()`).
  `applies` re-arms `ctx.hunt_grass` ONLY when it set it (do not clobber `learner_hunt`'s: `learner_hunt` runs first and a True from it must survive), and refreshes the plan at most every `PLAN_REFRESH_STEPS = 50` steps or on a
  map / party-size / owned-count / goal-set change (cache key), building the inputs the way `learner_hunt._pick` does (`our_party`, `table(None, "wild_by_map")`, `ctx.mem.data["maps"]`, graph distance, `catch_list.dex_owned_count(ctx.emu)`) plus `bosses` from
  `trainers.boss_party` for the next `BOSS_HORIZON` boss goals. `team_wants` holds only actions whose map is the CURRENT map or on the planned route to the top action.
- `team_hunt` (walk like `learner_hunt`): when the best doable action is on another reachable map and `detour <= TEAM_HUNT_BUDGET = 400` path steps, walk the learned graph to it (`Decision(p[0], "team_hunt_walk", ...)`);
  on the target map set `ctx.hunt_grass = True` and return None (frontier seeks grass, `Catch` throws at a wanted species). Log once per target: `[team_hunt: NIDORAN(M) on Route 22 (0x21), L2-4, 40%/encounter, value 1.3, cost 310 steps]`.
  A per-run cap `TEAM_HUNT_STEP_CAP = 3000` steps (`ctx.team_hunt_steps`) after which it stops for the run (it must never block the route).
- **Gates (all must hold, else `applies` is False and `team_wants` is cleared):** not battling, no text box, `ctx.proc is None`, `ctx.center_intent is None`;
  NOT a boss segment: the next unmet ladder goal is not a `beat_*` / `rival_*` goal, the map is not in `SHIP_MAPS` or `DUNGEON_MAPS`; no hunt while `ctx.blackouts_row > 0`;
  HP: `party_hp(emu)` fraction >= `TEAM_HUNT_MIN_HP = 0.6`; supplies: `heal_items.heal_count(bag) >= floor.FLOOR_MIN` (the potion floor) and `balls >= 1`;
  money: the plan was built with `budget.spendable` so a hunt never plans a purchase that dips into `budget.reserve`.
- No RL/bandit hook, no new buying, no PC use. The `Catch` behaviour is the only thing that throws.

### 4.5 Tests (all fixtures; no ROM, no emulator)

`tests/test_team_value.py`:
1. A member that enables a boss win scores positive: fixture party that fails a two-mon fixture boss under the hurt-lead sim; adding a candidate with a type advantage makes `team_readiness(...).ready` true -> `gain >= 1`, `value > 0`, `contributes` names the boss.
2. A useless member (cannot damage the boss) has `gain == 0`; for a new species its `value == dex + catcher - cost`; for an owned species its `dex == 0`.
3. Training cost reduces value: the same candidate with a lower caught level (more fights) has a strictly lower `value`; `fights_to_reach` against a hand-computed `ceil(xp_needed(...)/xp)`; the trainee share doubles the fights.
4. `form_at`: SQUIRTLE at 15 -> SQUIRTLE, 16 -> WARTORTLE, 36 -> BLASTOISE; MAGIKARP 19 -> MAGIKARP, 20 -> GYARADOS; a species not in the table is itself.
5. `pokedex_value`: owned -> 0; owned_count 9 (gate 10) is worth more than owned_count 4; owned_count past the last gate gives only `DEX_FLOOR_VALUE`; monotone in progress toward the gate.
6. `catcher_value`: MAGIKARP L10 (moves SPLASH only) is REJECTED as a catcher; MAGIKARP L15 (TACKLE) qualifies against a PIDGEY L3 fixture when the min-roll TACKLE does not KO it (and is rejected if it would); a status-only mon (e.g. a fixture with only SING/STUN-type moves) is rejected; a party whose weakest member is within `CATCHER_BAND` of the lead -> 0; a lone L20 lead -> `CATCHER_VALUE`; a low-level candidate gets `source="catcher"` only when nobody already fills the band.
7. `candidates_for`: contains exactly one Magikarp candidate; contains each wild species of the passed maps once; the three starters are symmetric (`@pytest.mark.parametrize` over the Squirtle / Bulbasaur / Charmander parties: same wild tables, candidate lists differ only by that line's party-evolution entries).
8. Empty party / empty bosses / empty tables return empty or zero without raising.

`tests/test_catch_plan.py`:
1. Ranking on the section 2 fixture rows for a Brock-stage party (a lone starter around L10, boss BROCK): sorted by `score` descending, contains Route 22 NIDORAN(M); an action with boss gain outranks an equally cheap dex-only one.
2. Early-catch reachability: with `known_maps` containing 0x21, 0x33, 0x3B, 0x23 the plan contains an action for each of NIDORAN(M), PIKACHU, PARAS, ODDISH, none hard-coded (assert they appear when the fixture bosses make them contribute AND when only the Pokedex term applies).
3. Pokedex-only actions: with a boss no candidate helps against, a new species with `steps <= CHEAP_STEPS` is still returned (`gain == 0`, `value > 0`); the same species far away (steps above the cheap bound and tiny score) ranks last; an owned species is not returned.
4. Cap: a party of 6 returns `[]`; a party of 5 returns actions.
5. Cost: the same species is ranked lower when `distance` is larger; `balls == 0` and no spendable money gives `blocked="no balls"`; planned balls never exceed `budget.spendable`; a map whose max wild level exceeds `lead_level + RISK_LEVEL_MARGIN` is absent.
6. Magikarp: with its target (L20) far above the others it can lose; with a boss only a Gyarados beats it wins; it is one candidate scored through the same `member_value` path.
7. `p_catch(255) > p_catch(45)`; `expected_balls` decreases with a higher catch rate.

`tests/test_team_hunt.py` (use the `ExplorerContext` construction and `FakeEmulator` helpers from `tests/test_cut_learner.py`; the `learner_hunt` tests there are the template):
1. The `team_ready` detector: `check_goals` with a ready team -> met and sticky; with `st["team_ready_skipped"]` -> met; with `st["team_ready_nodata"]` -> met; with a Magikarp-only weak party and none of those -> not met.
   `GOALS.index("team_ready") == GOALS.index("nugget_bridge") + 1`; `to_bill` follows it; `"gyarados" not in GOALS`; `campaign.selectable("team_ready")` is True.
2. Settle: drive the step counter past `GYARADOS_STEP_CAP` -> `ctx.team_ready_skipped` and the goal reads True; below it stays False. The forced `EVOLVE_LEVEL + TEAM_GAP` gate applies only when the plan's top action is the Magikarp candidate.
3. `catch_wanted(..., wants={"NIDORAN(M)": "planned: ..."})` returns the planned reason for it; `wants=None` is unchanged; `catch.py`'s admit condition accepts `planned`.
4. `TeamHunt.applies` is False: battling, in a boss segment (next unmet goal is `beat_brock`), on a ship map, with 0 heal items, 0 balls, HP below `TEAM_HUNT_MIN_HP`, `blackouts_row > 0`, after `TEAM_HUNT_STEP_CAP`, with a party of 6, and it must not clear a `hunt_grass` that `learner_hunt` set.
5. `TeamHunt.step` on a `WorldGraph` fixture: walks toward the best action's map (returns a `Decision` with rule `team_hunt_walk`); on the target map sets `hunt_grass` and returns None; no route known -> None; `detour > TEAM_HUNT_BUDGET` -> None.
6. The behaviour order: `default_behaviours()` has `TeamHunt` after `LearnerHunt` and before `Frontier` (update the existing order assertion in `tests/test_explorer_behaviours.py`).

## 5. What NOT to do

- No RL / bandit changes (`bandit/`, `GrindBudget`, `GRIND_BLACKOUTS`, `record_battle_result` stay). No edits to `ship_gate.py`, `planner.py`, `planner_east.py`, `planner_checkpoint.py`, `tools/seg_*.py`, `tools/segments.py`.
- No PC box automation (deposit / withdraw); the plan stops at a party of 6. Never release or discard Pokemon. No shopping changes (`shopping.py`, `restock.py` are read-only here). No changes to the Magikarp buy goal (`buy_magikarp`, `magikarp_goal_settled`), `party_order.py`, `switch_out.py`.
- No battle-time catch logic (status moves, min-damage, ball choice, the overpower switch): that is `Catch_Methods_Directive.md`. `catch.py` changes only by the `wants` pass-through.
- No in-game trade code (no table exists); no stone evolutions; no water/Surf candidates. No change to `MARGIN`, `LEAD_HURT`, `TEAM_GAP`, `TEAM_MIN`, `CAP_ABOVE_TABLE`, `TRAIN_LEVEL_BY_GOAL`, or the flee / potion thresholds.
- No emulator runs by you, no `uv run pokeagent ...`, no reading `kb/` or `runs/` (they are not in your worktree). Every module under 300 lines, no new dependencies.

## 6. Verification

- `uv run pytest -q tests/test_team_value.py tests/test_catch_plan.py tests/test_team_hunt.py` - new tests pass.
- `uv run pytest -q tests/test_goal_order.py tests/test_campaign.py tests/test_magikarp.py tests/test_team_readiness.py tests/test_explorer_behaviours.py tests/test_cut_learner.py` - the updated and neighbouring tests pass (the cut_learner tests pass unedited).
- `uv run pytest -q` green; paste the before/after tails and `git diff --stat main`; confirm no forbidden file changed.
- **Controller validation (not Devin; the ROM is on the laptop):** a headless run from `runs/checkpoints/to_route22.state` (or the nearest early checkpoint) showing a Nidoran catch and the `team_ready` gate; then `nugget_bridge -> team_ready`; the controller also verifies `DEX_GATES` on the ROM.

## 7. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation is rejected and ends the run. No installs, downloads or fetches.
  Never read outside the worktree.
- **Do not run the `pokeagent` entry point (the sandbox refuses it). Do not list the directory tree recursively; use `git ls-files`.
  Do not read outside the worktree. Create no scratch files; deleting is denied. If something expected is missing, stop and write that in the Status row.**
- Do not search, glob or hunt for a missing file or fact: stop and say so in the Status row.
- Test commands are exactly `uv run pytest -q` and `uv run pytest -q tests/<file>`. Never bare `python`.
- Work only on branch `directive/pokeagent-team-builder-v2-directive`. Never commit to `main`; never push; never deploy; no `git stash`. Commit on the branch as you go.
- Create no scratch or debug files (deleting is denied and ends the run). If one is truly needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row; do not try another way around it.
- SOLID/SRP/KISS is a hard rule here: small new modules (under 300 lines), no new dependencies.

## 8. Completion criteria

- [ ] `knowledge/team_value.py` (`member_value`, `pokedex_value`, `catcher_value`, `candidates_for`, `form_at`, `fights_to_reach`, the named constants incl. `DEX_GATES`) and `knowledge/catch_plan.py` (`plan_catches`, `CatchAction`, `p_catch`, `expected_balls`); pure, tested
- [ ] `gyarados` ladder goal replaced by `team_ready` (campaign.json, goals.py, plan_goal.py, context fields), never blocks, Magikarp machinery unchanged and chosen only when its candidate wins
- [ ] `catch_wanted(wants=...)` + `catch.py` pass-through; `behaviours/team_hunt.py` registered after `LearnerHunt`; all gates in 4.4
- [ ] The three new test files pass; the updated existing tests pass; `uv run pytest -q` green (tail pasted); `git diff --stat main` pasted; no forbidden file changed
- [ ] Status row moved to Review with the branch name

## 9. Report

Findings first: test tails (before/after), `git diff --stat`, the final signatures, the exact values of every named constant, the rename list (every function / field / test that changed for `gyarados` -> `team_ready`),
the plan output on the section 2 fixture (ranked actions with value / steps / score for a Brock-stage party and for a Misty-stage party), whether you kept the rename or fell back to a side goal and why, and anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-team-builder-v2-directive |
| Base branch | - |
| Base commit | cb732b47c9a207a4a6d6d9bc46740ba3010795d4 |

**Status log**
- 2026-11-07 15:16 · robert-claude-laptop · none → Draft — Claude 2026-11-07: value-ranked catch plan, Pokedex objective, team_ready gate (supersedes Team_Builder_Directive draft)
- 2026-11-07 15:17 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; lint_override candidate: dispatch-path-missing on greenfield modules/tests and gitignored kb/ evidence paths
- 2026-11-07 15:17 · robert-claude-laptop · Queued → Draft — Claude: lint path fix (hp_stats full path)
- 2026-11-07 15:18 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07: catcher requires a damaging move (Robert); lint path fix; lint_override: dispatch-path-missing on greenfield modules/tests and gitignored kb/ paths
- 2026-11-07 15:21 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing / verification-path-missing on greenfield modules (team_value.py, catch_plan.py, dex_value.py, tests) and gitignored kb/*.json evidence; known false positives.
- 2026-11-07 15:21 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-team-builder-v2-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6VTS7Y1KSVFM8YCHATZQNZ6
- 2026-11-07 15:26 · dispatcher · launched pid=18156; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-team-builder-v2-directive; provisioned: uv sync --frozen
<!-- queue:end -->
