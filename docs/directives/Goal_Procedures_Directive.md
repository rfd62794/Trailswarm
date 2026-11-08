# PokeAgent: goal procedures - learned, graded step scripts per goal, and a post-victory decision (push on, heal, or continue)

**Read first (all in the worktree; if one is missing, stop and write that in the Status row):** `src/pokeagent/explorer/behaviours/__init__.py` (the selector order, `default_behaviours()`), `explorer/behaviours/base.py` (`BehaviourBase`, `Decision`, `no_press`),
`explorer/behaviours/procedures.py` (the EXISTING menu-task behaviour; its module name `procedures` is taken, so the new package below is `pokeagent/procedures/` and the new behaviours live in `explorer/behaviours/after_victory.py` and `explorer/behaviours/procedure_runner.py`),
`explorer/behaviours/goto.py` and `explorer/behaviours/replay_beat.py` (how a destination and a recorded sequence are executed and graded), `explorer/demos.py` (`grade_replay`, `matching_demo`), `explorer/behaviours/battle.py` lines ~236-285 (where a battle ends, `ctx.trainer_npc`, `trainer_info`, the `runs/battles.jsonl` record),
`explorer/press.py` (`write_transition`: the `transitions.jsonl` row shape), `tools/review_runs.py` (how `runs/best_paths.json` is produced from `transitions.jsonl` + `runs/milestones.json`), `knowledge/trainers.py` (`trainers_on`, `party_of`, `boss_party`), `knowledge/readiness.py` (`fight`, `MARGIN`, `_chart`),
`knowledge/party.py` (`our_party`, `trainer_mon`, `Combatant`), `explorer/economy/outside_use.py` (`walk_to_center`, `potion_beats_walk`, `field_wants`, `YEN_PER_FRAME`), `explorer/economy/floor.py` (`potion_floor`, `FLOOR_MIN`), `explorer/behaviours/heal.py` and `explorer/behaviours/use_items.py` (what heal intent they already read),
`explorer/world.py` (`WorldGraph`, `POKECENTER_MAPS`), `legs/par.py` (`par`), `docs/directives/Defined_Interactions_Directive.md` (old draft), and `docs/ROADMAP.md` (the "GOAP/HTN planning over preconditions and effects" line, ~line 27).
**The planners are read-only for this directive:** `explorer/planner.py`, `planner_east.py`, `planner_checkpoint.py`, `ship_gate.py`. **Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-07): "It also needs to learn optimal button press and event patterns, such on nugget bridge, and after victory, check party, push forward or heal should be focus. How do we build goal-focused agents?"
Earlier (2026-11-05/07): menus are explored with B as the safe default, and known menu paths are memorized. (Menu-path memory is NOT in this PR: see section 5.)

Where things stand (read from the code and the live runs today):
- The planner reaches a goal one step at a time over the learned world; `runs/best_paths.json` already holds, per goal, the shortest recorded button sequence between consecutive goals (4,764 run directories under `runs/`, ~one `transitions.jsonl` each), and `ReplayBeat` can replay demos, but nothing turns a goal into a
  reusable, preconditioned, graded SCRIPT with a stated expected effect. A fight-heavy stretch such as Nugget Bridge (Route 24) is just "walk north and let battles happen": there is no memory of "trainer 3 of 6 comes next, I am at 40% HP, is it worth pushing on".
- After a trainer win the agent does whatever the next behaviour wants. The decision "check the party, then push forward or heal" is implicit in the grind gate and the potion rule, and is never made, logged or graded at the moment it matters.
- `outside_use.py` already prices a Pokecenter walk against a Potion, and `readiness.fight` already simulates a party against a ROM trainer party. Both are reusable for the post-victory decision.

"How do we build goal-focused agents?" Answer implemented here, in the HTN/GOAP spirit of the ROADMAP line: a goal owns a PROCEDURE = ordered steps, each with a PRECONDITION (a RAM predicate), an ACTION (a short button script, a waypoint, or a named behaviour call) and an EXPECTED EFFECT (a RAM predicate again);
procedures are learned from the best organic runs, graded after every attempt like demos, never trusted blindly (a failing step is downgraded and the existing exploration takes over), and the generic between-fights decision is a behaviour of its own (`AfterVictory`).

**Old draft folded in:** `Defined_Interactions_Directive.md` (2026-11-05, never queued). Folded in: the idea of a scripted, verified interaction as a step kind (`interact`: stand on a tile, face a direction, press A, expect an effect), and its "heal only when needed" principle (now the `AfterVictory` heal branch).
Superseded / not in this PR: the interaction TYPE classifier and repeat-policy table, memorised conversation text, the adaptive text-pace rule, and the metrics section (they remain a draft for a later directive).

## 2. Facts (verified on the live checkout 2026-11-07; pasted because you cannot read `kb/` or `runs/` in the worktree)

- `uv run python --version` prints `Python 3.12.12`. Always `uv run`; never bare `python`. Full suite: `uv run pytest -q` (about 100-210 s; 1557 passed, 1 skipped on the live checkout today, plus one environment-dependent failure
  `tests/test_resources.py::test_lock_takeover_is_exclusive` that is unrelated: ignore it and say so if it fails for you).
- `roms/`, `baselines/`, `runs/`, `kb/rom_tables.json` are gitignored: **no ROM, no `kb/`, no `runs/` in your worktree.** Tests use `FakeEmulator` (`from pokeagent.emulator import FakeEmulator`, `FakeEmulator({addr: byte})`, `.memory`, `.read`, `.read_range`, `.set`), `tmp_path`, and fixture tables/files you write into the test.
  Copy the patterns of `tests/test_cut_learner.py` (ExplorerContext + behaviour tests) and `tests/test_team_readiness.py` (the synthetic cartridge for `fight` / `readiness`).
- `transitions.jsonl` row (one per press, from `explorer/press.py::write_transition`): `{"step": 1, "from": [38, 4, 6], "button": "UP", "to": [38, 4, 5], "moved": true, "textbox": "none", "text": ..., "facing": "UP", "source": "agent"}`; `from`/`to` are `[map, x, y]`; `textbox` is `"dialog"` or `"none"`.
- `runs/milestones.json`: `{goal id: [{"run": "explore-YYYYMMDD-HHMMSS", "step": N}, ...]}`. `tools/review_runs.py` builds `runs/best_paths.json`: `{goal: {"run", "length", "start": [m,x,y], "end": [m,x,y], "buttons": [...], "sources": {...}}}` from the presses between consecutive goals' first steps (copy its segmentation rule; the tool is a script, import nothing from it unless you restructure it into a small function you add under `pokeagent/procedures/`).
- `runs/battles.jsonl` (one JSON object per battle, written in `battle.py`): keys include `start` (step), `kind` (1 wild, 2 trainer), `turns`, `won`, `run`, `battle_map`, `stage`, `trainer` (`{"map", "pic", "x", "y"}` when pinned to an NPC), `party_before` / `party_after` (rows `[species, level, exp, hp, max_hp]`). It is the source for "which trainer on this map was beaten in THIS run".
- **Beaten-trainer event flags are NOT verified in this repo** (no address in `ram_map.json` or `docs/KNOWLEDGE.md`). A step precondition "trainer N on this map beaten" therefore reads the run's own record: `ctx.trainer_npc["beaten"]` NPC entries (set in `battle.py`) and the run's `runs/battles.jsonl` `trainer` rows. If the flags are verified later the predicate gets a second source; leave a clearly named seam (`beaten_trainers(ctx) -> set[(map, x, y)]`).
- Trainer placement (ROM, drained into `kb/rom_tables.json` `map_trainers`; `trainers.trainers_on(map)` resolves each row's party with `trainers.party_of`). x/y are as drained; **whether they are in the same tile frame as the learned maps' `[map, x, y]` positions is UNVERIFIED** (the controller checks it on the checkpoint). Route 24 is map 0x23 = 35, Route 25 is 0x24 = 36:

  | map | class | party # | (x, y) | party (level species) |
  |---|---|---|---|---|
  | 35 Route 24 | BUG CATCHER | 9 | (11, 31) | 14 CATERPIE, 14 WEEDLE |
  | 35 | LASS | 8 | (10, 28) | 14 PIDGEY, 14 NIDORAN(F) |
  | 35 | YOUNGSTER | 4 | (11, 25) | 14 RATTATA, 14 EKANS, 14 ZUBAT |
  | 35 | LASS | 7 | (10, 22) | 16 PIDGEY, 16 NIDORAN(F) |
  | 35 | JR.TRAINER(M) | 3 | (11, 19) | 18 MANKEY |
  | 35 | ROCKET | 6 | (11, 15) | 15 EKANS, 15 ZUBAT |
  | 35 | JR.TRAINER(M) | 2 | (5, 20) | 14 RATTATA, 14 EKANS |

  (Listed south to north by y descending, which is the walking order from Cerulean if the player enters at the south end: an ASSUMPTION; the ROM list order is Rocket, Jr(5,20), Jr(11,19), Lass, Youngster, Lass, Bug Catcher, which is NOT the walking order. The Jr.Trainer at (5,20) stands off the main line.)
  Route 25 (map 36, continues north-east after the bridge): YOUNGSTER p5 (14,2) 15 RATTATA 15 SPEAROW; YOUNGSTER p6 (18,5) 17 SLOWPOKE; JR.TRAINER(M) p2 (24,4) 14 RATTATA 14 EKANS; LASS p9 (18,8) 15 NIDORAN(M) 15 NIDORAN(F); YOUNGSTER p7 (32,3) 14 EKANS 14 SANDSHREW; LASS p10 (37,4) 13 ODDISH 13 PIDGEY 13 ODDISH;
  HIKER p2 (8,4) 15 MACHOP 15 GEODUDE; HIKER p3 (23,9) 13 GEODUDE x3 13 MACHOP; HIKER p4 (13,7) 17 ONIX. (Route 25 is not seeded in this PR; it is here so a miner or a later seed has the rows.)
- S.S. Anne maps (`atlas/map_names.json`): 94 VERMILION_DOCK, 95 SS_ANNE_1F, 96 SS_ANNE_2F, 97 SS_ANNE_3F, 98 SS_ANNE_B1F, 99 SS_ANNE_BOW, 100 SS_ANNE_KITCHEN, 101 SS_ANNE_CAPTAINS_ROOM, 102 SS_ANNE_1F_ROOMS, 103 SS_ANNE_2F_ROOMS, 104 SS_ANNE_B1F_ROOMS (`explorer.world.SHIP_MAPS` = ids 0x5E..0x68).
  Placement rows: maps 95 (1F corridor) has NONE; 96 (2F corridor) has `RIVAL1 p1 (36, 4)` resolving to `[(5, SQUIRTLE)]` (**this looks wrong**: that is the Oak's-lab rival party; the S.S. Anne rival is class `RIVAL2` in `trainers.RIVAL_BOSSES["rival_ss_anne"]` (first party 1, groups of three by our starter). Do NOT seed the rival from this row; use `trainers.boss_party("rival_ss_anne", ...)`; report the discrepancy);
  99 BOW: SAILOR p1 (4,4) 18 MACHOP 18 SHELLDER, SAILOR p2 (10,8) 17 MACHOP 17 TENTACOOL; 102 1F_ROOMS: GENTLEMAN p1 (2,3) 18 GROWLITHE x2, GENTLEMAN p2 (11,4) 19 NIDORAN(M) 19 NIDORAN(F), YOUNGSTER p8 (11,14) 21 NIDORAN(M), LASS p11 (13,11) 18 PIDGEY 18 NIDORAN(F);
  103 2F_ROOMS: GENTLEMAN p3 (10,2) 23 PIKACHU, FISHERMAN p1 (13,4) 17 GOLDEEN 17 TENTACOOL 17 GOLDEEN, GENTLEMAN p5 (0,14) 17 GROWLITHE 17 PONYTA, LASS p12 (2,11) 18 RATTATA 18 PIKACHU; 104 B1F_ROOMS: SAILOR p3 (0,13) 21 SHELLDER, SAILOR p4 (2,11) 17 HORSEA 17 SHELLDER 17 TENTACOOL,
  SAILOR p5 (12,3) 18 TENTACOOL 18 STARYU, SAILOR p6 (22,2) 17 HORSEA x3, SAILOR p7 (0,2) 20 MACHOP, FISHERMAN p2 (0,4) 17 TENTACOOL 17 STARYU 17 SHELLDER.
  So the 1F/2F **corridors** hold no ROM trainer besides that suspect row; the trainers are in the ROOMS (102-104) and bow (99), which the agent need not enter. The S.S. Anne seed is therefore a corridor/boss-path procedure (steps by waypoint and the rival boss fight), with the room trainers listed as OPTIONAL gauntlet steps that the seed marks `optional: true`.
- Readiness API: `readiness.fight(ours: list[Combatant], theirs: list[Combatant], chart, moves) -> float` (>= 0: every enemy down, HP fraction left on the mons that fought; < 0: we lose), `readiness.MARGIN` = 0.30, `readiness._chart(kb)`, `knowledge.kb.table(kb, "moves")`. `Combatant.hp` is MAX HP; to judge the party as it is NOW, `dataclasses.replace(c, hp=current_hp)`
  using the party read from RAM (`ramstructs.read_party(emu)` gives each member's `hp`, `max_hp`).
- Heal economics: `outside_use.walk_to_center(ctx)` returns `(frames, grass_tiles, center_map)` or None; `outside_use.potion_beats_walk(frames, grass_tiles, hp, mx)`; `outside_use.field_wants(ctx)`; `YEN_PER_FRAME = 0.1`; `floor.FLOOR_MIN = 1` Potion; `heal_items.heal_count(bag)`; `goals.bag_contents(emu)`. `ctx.center_intent` is the existing "go heal" intent field (read it in `heal.py` before using it).
- Behaviour order today (`default_behaviours()`): `SettleWait, LoopGuard, PartyOrder, PostTalkSettle, Readiness, AnomalyWait, ReplayInterrupt, BattleTextWait, Battle, SwitchOut, Catch, BattleMoves, CaveEscape, CaveTopUp, UseItems(active_only), NamingKeyboard, BeatStart, BoxSettle, AdvanceDialog, Menu, Procedures, Goto, ReplayBeat, StallGuard, Heal, Restock, UseItems, GoalTalk, GrindDrill, ExploreBurst, Pickup, PlanGoal, LearnerHunt, Frontier`
  (plus `TeamHunt` after `LearnerHunt` once the Team_Builder_V2 PR merges; register relative to those, not by index).
- Checkpoint states for the controller (gitignored): `runs/checkpoints/nugget_bridge.state` (written when Route 24 is first entered), `beat_misty.state`, `heal_cerulean.state`, `ss_anne_2f.state`. There is no `to_route24` state.

## 3. Scope (one PR, in order)

1. `src/pokeagent/procedures/` package: schema, predicates, store, grading (pure, no emulator beyond RAM reads through a small reader).
2. Learning: `tools/procedures_mine.py` plus two hand-seeded procedures (Nugget Bridge, S.S. Anne corridor).
3. `AfterVictory` behaviour (`explorer/behaviours/after_victory.py`) and its pure decision module (`pokeagent/procedures/after_victory_rules.py`).
4. `ProcedureRunner` behaviour (`explorer/behaviours/procedure_runner.py`).
5. Tests: `tests/test_procedures.py`, `tests/test_procedures_mine.py`, `tests/test_after_victory.py`, `tests/test_procedure_runner.py`; update `tests/test_explorer_behaviours.py` (the default order).

## 4. The work

Every threshold is a NAMED constant with a comment saying it is an untuned first value. Each new module under 300 lines (split before passing it).

### 4.1 The `pokeagent/procedures/` package

```
procedures/__init__.py      # re-exports Procedure, Step, load, save, grade
procedures/schema.py        # dataclasses + JSON (de)serialisation + validation
procedures/predicates.py    # the precondition / effect vocabulary (pure, over a small State snapshot)
procedures/store.py         # runs/procedures/<goal>.json load/save, atomic write, grading
procedures/after_victory_rules.py   # the push / potion / heal / continue decision (pure)
```

JSON on disk, `runs/procedures/<goal>.json` (the directory is created on first save; `runs/` is gitignored, so no procedure file is ever committed; the SEEDS live in `src/pokeagent/procedures/seeds/<goal>.json` and are copied to `runs/procedures/` only if no file exists there):

```json
{"version": 1, "goal": "nugget_bridge", "source": "seed|mined",
 "attempts": 0, "successes": 0, "best_frames": null, "best_presses": null, "disabled": false,
 "steps": [
  {"id": "s1", "optional": false,
   "pre": {"all": [{"map": 35}, {"region": [35, 9, 29, 13, 33]}, {"hp_frac_min": 0.5}]},
   "action": {"kind": "goto", "map": 35, "x": 11, "y": 34},
   "effect": {"all": [{"at": [35, 11, 34]}]},
   "ok": 0, "fail": 0, "max_presses": 80, "max_frames": 2400},
  {"id": "s2", "pre": {"all": [{"map": 35}, {"not": {"trainer_beaten": [35, 11, 31]}}]},
   "action": {"kind": "behaviour", "name": "fight_trainer", "at": [35, 11, 31]},
   "effect": {"all": [{"trainer_beaten": [35, 11, 31]}]}, "ok": 0, "fail": 0, "max_presses": 200, "max_frames": 6000}
 ]}
```

- Predicate vocabulary (`predicates.py`, all pure functions of a `State` snapshot dict `{map, x, y, hp, hp_max, party, badges, flags, beaten, bag}` that a small `read_state(ctx)` fills from RAM and the run's records): `map`, `at: [m,x,y]`, `region: [m, x0, y0, x1, y1]`, `hp_frac_min`, `hp_frac_max`,
  `flag: [addr, bit]` (event flag by address and bit, as `goals.py` reads them), `badge: n`, `has_item: id`, `trainer_beaten: [m, x, y]` (via `beaten_trainers(ctx)`, section 2), `party_size_min`, plus `all`, `any`, `not`. An unknown key makes the predicate FALSE and is logged once (never raise, never treat unknown as true).
- Action kinds: `buttons` (a short list of button names, at most `MAX_SCRIPT = 40`), `goto` (map, x, y; executed over `WorldGraph` exactly as `goto.py` does, but without touching `ctx.goto`), `behaviour` (a NAMED call from a small registry in the runner: `fight_trainer`, `talk`, `heal_here`; an unknown name fails the step), `interact` (stand at `[m,x,y]`, face a direction, press `A` once, advance dialog with the existing behaviours; effect is a predicate).
- Grading (`store.grade(proc, step_id, ok, presses, frames)`): per-step `ok`/`fail` counters; a procedure-level `attempts`/`successes`, `best_frames`/`best_presses` kept when a full run succeeds with fewer. **Never trusted blindly:** `DOWNGRADE_FAILS = 2` - a step with `fail >= DOWNGRADE_FAILS` and `fail > ok` is skipped (the runner returns None for it so exploration continues) until a later success outside the runner resets it; `DISABLE_AFTER = 3` consecutive failed attempts set `disabled: true`
  for the rest of the run (the file keeps the counts; the miner may refresh the steps). Grades are written at the end of each attempt, never mid-step.
- `load(goal)` returns None for a missing, unreadable or wrong-`version` file, never raises.

### 4.2 `tools/procedures_mine.py` (learning) and the two seeds

```
uv run python tools/procedures_mine.py [--runs runs] [--out runs/procedures] [--goal GOAL ...]
```

For each goal in `GOALS` (or the `--goal` list), pick the best organic run exactly as `review_runs.py` does (fewest presses between the previous goal's first step and this goal's first step, from `runs/milestones.json` and each run's `transitions.jsonl`), skip segments under `MIN_SEGMENT = 4` presses or above `MAX_SEGMENT = 1500`,
and build a procedure from the segment's rows:
- **Waypoints:** every row where `to[0] != from[0]` (a warp) yields a `goto` step to the `to` position with effect `at`; a long run of moves with no map change is compressed to a waypoint every `WAYPOINT_EVERY = 12` moved rows and at every turn of more than `TURN_MIN = 2` direction changes in 4 rows (named, untuned). Preconditions are `map` + `region` around the previous waypoint.
- **Interactions:** a row with `textbox == "none"` followed by a row with `textbox == "dialog"` yields an `interact` step at the `from` position with the row's `facing`; effect = the position unchanged and (when known) the item/flag change is NOT guessed: effect is `{"all": [{"at": [..]}]}` only.
- **Battles:** each `runs/battles.jsonl` record of this run whose `start` step falls inside the segment and has `kind == 2` yields a `behaviour: fight_trainer` step at the record's `trainer` `[map, x, y]` (when present), with effect `trainer_beaten`; wild fights (`kind == 1`) are NOT steps (they are noise).
- Output goes to `runs/procedures/<goal>.json` with `source: "mined"`, counts zero. Re-mining never overwrites a procedure with `attempts >= 3` and a better success rate unless `--force`.
- The tool prints one line per goal (steps, source run, presses) and a final count; it never writes outside `--out`. A missing `runs/` is a clean "nothing to mine" exit 0.

**Hand seeds** (`src/pokeagent/procedures/seeds/nugget_bridge.json`, `seeds/ss_anne_corridor.json`; keyed to the goal ids `nugget_bridge` and `ss_anne_2f`/`rival_ss_anne` as the ladder names them - read `GOALS` for the exact ids and cite them in your report):
- `nugget_bridge`: preconditions `map 35` + `hp_frac_min 0.5` for the first step; then one `fight_trainer` step per ROM trainer on map 35 in the walking order assumed in section 2 (south to north by y descending), each with effect `trainer_beaten`, then the Rocket (11, 15) last; the off-line Jr.Trainer (5, 20) is `optional: true`.
  Between steps NO heal logic is written here: `AfterVictory` makes that decision (4.3). Generate the step list FROM `trainers.trainers_on(35)` at seed-build time through a small helper `seed_gauntlet(map_id, trainers, order)` so the seed is code, not retyped numbers; the seeds committed as JSON are produced by a test-covered function, and a unit test asserts the JSON matches the helper's output for the section 2 fixture table.
  The approach tile for each trainer is `TRAINER_APPROACH = 3` tiles before it along the direction of travel (north: y + 3), named and unverified; the actual walk is the existing planner/exploration (a `goto` to the approach tile, then `fight_trainer`).
- `ss_anne_corridor`: waypoint steps through maps 95 -> 96 (the boundary and stair warps come from the learned maps at run time, NOT invented: the seed holds only the map ids and `goto` steps with `x`/`y` null, which the runner resolves with `WorldGraph.path(...)` to "any tile of that map"; a step whose target tile is null is satisfied by arriving on the map), then a `fight_trainer` step for the boss rival taken from
  `trainers.boss_party("rival_ss_anne", ...)` (NOT the suspect row). The ROOM trainers of maps 99, 102, 103, 104 are listed `optional: true` steps. Do not hard-code corridor coordinates.

### 4.3 `AfterVictory` (behaviour `explorer/behaviours/after_victory.py`, rules in `procedures/after_victory_rules.py`)

Registered RIGHT AFTER the battle behaviours: `... Battle(), SwitchOut(), Catch(), BattleMoves(), AfterVictory(), CaveEscape(), ...`. It applies for ONE decision per trainer win: `ctx.battles_won` increased since its last decision (store `ctx.after_victory_seen: int`), not battling, no text box, `ctx.proc is None`.
It never presses anything in battle and never changes move choice; it only DECIDES, logs, and sets an intent for behaviours that already exist.

```python
PUSH_MARGIN = readiness.MARGIN         # fight() score the NEXT trainer must clear with the party as it is now (0.30)
PUSH_MIN_LEAD_HP = 0.35                # never push on with the lead below this HP fraction
PUSH_MIN_ALIVE = 2                     # ... and at least this many members above 0 HP (a party of 1: PUSH_MIN_ALIVE = 1)
HEAL_WALK_MAX_FRAMES = 4000            # a Pokecenter round trip above this many frames is "too far": prefer a Potion or push
LOOKAHEAD = 2                          # how many remaining trainers on the path are simulated (the next one decides; the second warns)

@dataclass(frozen=True)
class VictoryDecision:
    action: str          # "push" | "potion" | "heal" | "continue"
    next_trainer: str    # e.g. "LASS p7 (10,22): 16 PIDGEY, 16 NIDORAN(F)" or "" when none left
    margin: float        # fight() score vs the next trainer (None when unknown)
    hp_frac: float; lead_hp_frac: float; alive: int
    why: str

def decide(party_now: list[Combatant], remaining: list[list[tuple[int, str]]], bag: dict, walk: tuple | None, kb=None) -> VictoryDecision
```

Decision (first match wins; `remaining` = the not-yet-beaten trainers' parties in path order, `walk` = `outside_use.walk_to_center(ctx)` or None):
1. No remaining trainer on this map/path -> `continue` ("path clear: carry on", no sim).
2. Simulate `fight(party_now, trainer_mon parties of remaining[0], chart, moves)` (and the LOOKAHEAD-th for the log). If the score is `>= PUSH_MARGIN` AND `lead_hp_frac >= PUSH_MIN_LEAD_HP` AND `alive >= PUSH_MIN_ALIVE` -> `push`.
3. Otherwise (the party would not hold) heal: if a heal item is carried and `outside_use.potion_beats_walk(...)` says the Potion is cheaper than the walk (or no Pokecenter is known), `potion` (sets the same intent `UseItems`/`outside_use.field_wants` already honours; read `use_items.py` first); else if `walk` exists and `walk[0] <= HEAL_WALK_MAX_FRAMES`, `heal` (sets `ctx.center_intent` as `heal.py` expects; read it first);
   else if the score is still >= 0 (we win, just thinly) -> `push` with `why` "no cheaper heal; thin margin"; else `continue` with `why` "cannot win the next trainer and nowhere to heal: procedure/exploration decides".
4. Missing data (no kb tables, an unknown species) -> `continue` with `why` "no sim data" (never blocks the route).

The behaviour builds `party_now` from `our_party(emu)` with each member's HP replaced by its CURRENT HP (`ramstructs.read_party`), `remaining` from `trainers.trainers_on(map)` minus `beaten_trainers(ctx)` (ordered by the active procedure's step order when one exists, else by walking distance `abs(dx) + abs(dy)` from the player), and logs ONE line per decision:
`[after_victory] push: next LASS p7 (10,22) 16 PIDGEY 16 NIDORAN(F), margin +0.52, party 78% (lead 70%), 3 alive` (or `heal: ... Pokecenter walk 1800 frames` / `potion: ...`). It also appends the decision (without any ROM data) to `runs/after_victory.jsonl`, one object per decision, for later grading; a failure to write is swallowed with one log line.
If an active procedure step is waiting on this victory, the decision is also stored as `ctx.after_victory` so the runner can read it.

### 4.4 `ProcedureRunner` (behaviour `explorer/behaviours/procedure_runner.py`)

Registered immediately BEFORE `Frontier()` and after `PlanGoal()` / `LearnerHunt()` (and `TeamHunt()` when present) - i.e. between the planner and exploration, as requested. NOTE for the report: `PlanGoal` returns a decision whenever the learned world reaches the goal, so the runner acts mainly where the planner has nothing; if the controller wants procedures to outrank the planner, that is a one-line change in the order (not edited here, the planners are read-only).

- `applies`: not battling, no text box, `ctx.proc is None`, `ctx.goto` empty, the NEXT UNMET goal (via `ctx.goals()` and `GOALS`) has a loaded, enabled procedure, and the first not-done, not-downgraded step's precondition holds NOW. Loading is cached per goal for `RELOAD_EVERY = 200` steps.
- `step`: executes ONE press per call (never a loop): a `buttons` step pops its next button; a `goto` step takes the first move of `WorldGraph.path(...)` (like `goto.py`); a `behaviour` step calls the registry entry (`fight_trainer` walks adjacent to the trainer tile and presses `A`; nothing in battle); an `interact` step is one `A` at the tile then lets the dialog behaviours run.
  The step is DONE when its effect predicate holds. It is FAILED when `max_presses` or `max_frames` are exceeded, when its precondition stops holding for `PRE_LOST_STEPS = 5` consecutive calls, or when the map leaves the procedure's maps. On FAIL: record `fail` on the step (`store.grade`), log `[procedure nugget_bridge: step s2 failed (...) - exploring]`, clear the runner state and return None so exploration/the planner take over;
  on a completed procedure record the success with presses and frames. A step whose precondition is false is NOT failed, it simply does not apply (the next behaviours run).
- The runner NEVER blocks the ladder: per-run cap `RUNNER_STEP_CAP = 4000` presses spent inside procedures (`ctx.proc_steps`), after which it stops for the run. Bounded by presses and frames everywhere; no unbounded `while`.
- It reads `ctx.after_victory`: a `heal` / `potion` decision pauses the current procedure (the step stays pending) until the party is healed or `HEAL_PAUSE_MAX = 600` steps pass; a `push` resumes; `continue` does nothing special.
- New context fields (`explorer/context.py`): `after_victory_seen: int = 0`, `after_victory: Any = None`, `proc_steps: int = 0`, `procedure_run: Any = None` (the runner's state). Do not reuse `ctx.proc` (that is the menu-task state of `behaviours/procedures.py`).

### 4.5 Tests (all fixtures; no ROM, no emulator run)

`tests/test_procedures.py`: (1) JSON round trip: a Procedure with every predicate kind and action kind serialises and loads back equal; a wrong `version` / corrupt file returns None; (2) predicates: each key true/false on a fixture `State`, `all`/`any`/`not`, an unknown key is False and logged once;
(3) grading: success increments `ok` and `successes` and keeps `best_frames`/`best_presses` only when lower; a step with 2 fails and `fail > ok` is downgraded (skipped); 3 consecutive failed attempts set `disabled`; a later success resets the step; (4) `seed_gauntlet` on the section 2 Route 24 fixture table yields the six main-line steps in south-to-north order with the Jr.Trainer (5,20) optional,
and the committed `seeds/nugget_bridge.json` equals the helper's output; the `ss_anne_corridor` seed has null-coordinate map steps and room trainers `optional`, and takes the rival from `boss_party("rival_ss_anne")` (fixture).

`tests/test_procedures_mine.py`: a fixture `runs/` under `tmp_path` with two runs' `transitions.jsonl`, a `milestones.json` and a `battles.jsonl`: the miner picks the shorter segment, emits a `goto` per warp, an `interact` where `textbox` flips none -> dialog, a `fight_trainer` for a `kind == 2` battle with a `trainer` row and NOTHING for a wild one; compresses straight runs to waypoints every `WAYPOINT_EVERY`; skips under-length segments; does not overwrite a better-graded existing file without `--force`; exits 0 with no `runs/`.

`tests/test_after_victory.py`: fixture synthetic cartridge (copy the pattern of `tests/test_team_readiness.py`) with a fixture next trainer: (1) a healthy party that clears `PUSH_MARGIN` -> `push` with the margin logged; (2) the same party with the lead at 20% -> not push -> with a Potion and a far Pokecenter -> `potion`; with no Potion and a near Pokecenter (walk under `HEAL_WALK_MAX_FRAMES`) -> `heal`;
(3) a party that loses outright with nowhere to heal -> `continue`; (4) a thin win with no cheaper heal -> `push` with the "thin margin" reason; (5) no remaining trainer -> `continue` without a sim; (6) missing data -> `continue`; (7) the behaviour applies once per win (`after_victory_seen`) and not while battling/boxed; (8) all three starter lines (`@pytest.mark.parametrize`) behave alike.

`tests/test_procedure_runner.py` (ExplorerContext + FakeEmulator + a tiny `WorldGraph` fixture as in `tests/test_cut_learner.py`): (1) precondition gating: false precondition -> `applies` False; true -> a press; (2) a `goto` step moves toward the target and completes on the effect; (3) abort: exceeding `max_presses` records a `fail`, logs, clears state and returns None;
(4) a downgraded step is skipped; a disabled procedure never applies; (5) `RUNNER_STEP_CAP` stops it; (6) an `AfterVictory` `heal` decision pauses a pending step and `push` resumes it; (7) `default_behaviours()` order: `AfterVictory` right after `BattleMoves`, `ProcedureRunner` right before `Frontier` and after `PlanGoal` (update the order assertion in `tests/test_explorer_behaviours.py`).

## 5. What NOT to do

- No edits to `explorer/planner.py`, `planner_east.py`, `planner_checkpoint.py`, `ship_gate.py`, `tools/seg_*.py`, `tools/segments.py`. No RL / bandit code. No changes to battle MOVE choice (`BattleMoves`, `battle_moves.py`) or to `Battle`'s win/flee/potion thresholds; `AfterVictory` runs after a battle is over and presses nothing in battle.
- No emulator runs by you, no `uv run pokeagent ...`; no reading `kb/`, `runs/` or `baselines/` (not in your worktree). No new heal or shopping mechanics: `AfterVictory` only sets the intents the existing `Heal` / `UseItems` already read; if no existing field fits, LOG the decision and write that in the Status row.
- **Menu-path memory is NOT in this PR.** Note it as the follow-up `Menu_Path_Memory_Directive.md`: it would live in `src/pokeagent/procedures/menu_paths.py` with its store at `runs/procedures/menus.json` (a per-menu-screen record of the button path that worked, with B as the safe default and known paths replayed), extending the existing `behaviours/procedures.py` PROCEDURES table rather than replacing it. Do not create those files.
- No procedure file under `runs/` is committed (gitignored); the committed seeds live in `src/pokeagent/procedures/seeds/`. Never trust a procedure: every step is bounded and graded. Each module under 300 lines, no new dependencies. Do not use the word "child" for spawned processes (say subagent) and do not rename existing identifiers.

## 6. Verification

- `uv run pytest -q tests/test_procedures.py tests/test_procedures_mine.py tests/test_after_victory.py tests/test_procedure_runner.py tests/test_explorer_behaviours.py` - new and updated tests pass (paste the tail).
- `uv run pytest -q` green; paste the before/after tails and `git diff --stat main`; confirm no forbidden file changed.
- **Controller validation (not Devin; the ROM is on the laptop):** a headless run from `runs/checkpoints/nugget_bridge.state` (Route 24, first entry) showing the Nugget Bridge gauntlet with `[after_victory]` decisions logged after each trainer win (push / potion / heal), `runs/procedures/nugget_bridge.json` graded after the attempt, and a failing step handing control back to exploration. The controller also checks whether the ROM trainer (x, y) frame matches the learned map positions and whether the walking order assumed in section 2 is right.

## 7. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation is rejected and ends the run. No installs, downloads or fetches.
  Never read outside the worktree.
- **Do not run the `pokeagent` entry point (the sandbox refuses it). Do not list the directory tree recursively; use `git ls-files`.
  Do not read outside the worktree. Create no scratch files; deleting is denied. If something expected is missing, stop and write that in the Status row.**
- Do not search, glob or hunt for a missing file or fact: stop and say so in the Status row.
- Test commands are exactly `uv run pytest -q` and `uv run pytest -q tests/<file>`. Never bare `python`.
- Work only on branch `directive/pokeagent-goal-procedures-directive`. Never commit to `main`; never push; never deploy; no `git stash`. Commit on the branch as you go.
- Create no scratch or debug files (deleting is denied and ends the run). If one is truly needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row; do not try another way around it.
- SOLID/SRP/KISS is a hard rule here: small new modules (under 300 lines), no new dependencies.

## 8. Completion criteria

- [ ] `procedures/` package (schema, predicates, store with grading and downgrade/disable rules, after_victory_rules); JSON round trip and grading tested
- [ ] `tools/procedures_mine.py` plus the two committed seeds generated by `seed_gauntlet`; miner tested on a fixture `runs/`
- [ ] `AfterVictory` registered right after `BattleMoves`; decisions logged and appended to `runs/after_victory.jsonl`; push/potion/heal/continue tested on fixture parties vs fixture trainers
- [ ] `ProcedureRunner` registered after `PlanGoal` and before `Frontier`; precondition gating, bounded steps, abort-to-exploration and the step cap tested
- [ ] The four new test files pass; `tests/test_explorer_behaviours.py` order updated; `uv run pytest -q` green (tail pasted); `git diff --stat main` pasted; no forbidden file changed
- [ ] Status row moved to Review with the branch name

## 9. Report

Findings first: test tails (before/after), `git diff --stat`, the final signatures and the exact value of every named constant, the exact goal ids the seeds are keyed to, the Route 24 step list the seed produced, how `AfterVictory` hands off heal and potion intents (which existing fields) or why it only logs,
the order assumption for the bridge, the S.S. Anne RIVAL1 row discrepancy, and anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-goal-procedures-directive |
| Base branch | - |
| Base commit | dccf81faf6eb1ed42156ef2b7dbafb527a235423 |

**Status log**
- 2026-11-07 15:27 · robert-claude-laptop · none → Draft — Claude 2026-11-07: goal procedures (learned, graded step scripts), AfterVictory decision, ProcedureRunner
- 2026-11-07 15:27 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; lint_override: dispatch-path-missing on greenfield modules/tests and gitignored kb/runs paths
- 2026-11-07 19:34 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing is the known false positive on PokeAgent directives; dependency PR #154 (Loop_Memory) is merged
- 2026-11-07 19:35 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-goal-procedures-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6W99FWZ4KE4HJ131S4BRZ07
- 2026-11-07 19:42 · dispatcher · launched pid=11212; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-goal-procedures-directive; provisioned: uv sync --frozen
<!-- queue:end -->
