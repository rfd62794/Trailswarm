# PokeAgent: trainer ledger and battle avoidance - remember which trainers are beaten, head for the next target on the route, avoid or save the rest, and report the party's resistance to an area

**Depends on (merged to main; if missing from your worktree, stop and write that in the Status row):** PR #150 (`memory_nav._person_tile`, `observe_npcs` person-tile rule; branch `fix/route24-blocked-tile`, may still be open: check), PR #136 (the battle record with the `trainer` dict). **Soft dependency:** `Goal_Procedures_Directive.md` (queued): its `AfterVictory` and gauntlet seeds leave a `beaten_trainers(ctx)` seam open; THIS directive supplies the implementation (`explorer/trainer_ledger.py::beaten_trainers`). If the Goal Procedures PR is not merged, add the function anyway and leave its callers to that PR.
**Do not list the tree recursively**; use `git ls-files`.

**Read first (all in the worktree):** `src/pokeagent/knowledge/trainers.py` (`trainers_on`, `party_of`, `boss_party`), `src/pokeagent/knowledge/items_catalog.py` (`load()`, `trainer_prize(cat, cls, party)`, `map_income`), `src/pokeagent/explorer/memory.py` (`observe_npcs`, `npc_at`, `mark_trainer`, the `npcs` entries), `src/pokeagent/explorer/memory_nav.py` (`_person_tile`, `_frontier`, `temp_blocked`), `src/pokeagent/explorer/press_interact.py` (`NPC_BLOCK_FRAMES`, how a person's tile is temp-blocked), `src/pokeagent/explorer/behaviours/battle.py` lines ~236-285 (`trainer_info`, `ctx.trainer_npc["beaten"]`, the `runs/battles.jsonl` record), `src/pokeagent/ramlab/flags.py` (`FlagBit`, `FLAG_LO/FLAG_HI`), `src/pokeagent/ramlab/pipeline.py`, `tools/ram_discover.py` (flag mining, as used for the captain flags `0xD803`, see `docs/KNOWLEDGE.md` "HM01 Cut and the S.S. Anne captain"), `src/pokeagent/knowledge/readiness.py` (`fight`, `MARGIN`), `src/pokeagent/knowledge/party.py`, `src/pokeagent/grind/xpmath.py` (`xp_gain`, `TRAINER_XP`), `src/pokeagent/grind/atlas.py` (`prior_xp`, `Spot`, `rank_spots`), `tools/grind_report.py`, `tools/swarm_merge.py` (`merge_memory`), `tests/test_knowledge.py` / `tests/test_team_readiness.py` (synthetic cartridge patterns).

## 1. Why this exists

Robert (2026-11-07): "Is there a way for the agent to track and remember which battles have already been won, and ignore the NPC involved, to move toward next available combat target on an optimal path?" and "It may be worth exploring ways to avoid certain battles, and tracking whether certain battles are worth saving for later grinding, or if there is an optimal team combination or variety to be able to easily pass through an area without resistance during battle?"

Today the only memory of a won trainer fight is a flag on the NPC entry in the run's map memory (`ctx.trainer_npc["beaten"] = True` in `battle.py`, line ~252) plus the `trainer` dict in `runs/battles.jsonl`. It is keyed by a sprite slot and picture id (`slot3:pic12`), not by the trainer's identity in the ROM, it is not used to choose where to go, and nothing tells beaten from unbeaten trainers on a map the agent revisits or starts a run on. Route 24, 2026-11-07: ~1,500 UP presses into a beaten, stationary Bug Catcher (PR #150's cap now temp-blocks him; the person-tile rule stops him being a frontier). The ROM, meanwhile, lists every trainer on every map (class, party number, tile), so "which trainers are there, how strong, how much XP and money, which I have beaten" is answerable.

## 2. Facts (verified on the live checkout 2026-11-07; pasted because you cannot read `kb/` or `runs/` in the worktree)

- `uv run python --version` prints `Python 3.12.12`. Always `uv run`; never bare `python`. Full suite: `uv run pytest -q` (about 100-210 s; 1557 passed, 1 skipped on the live checkout today, plus one environment-dependent failure `tests/test_resources.py::test_lock_takeover_is_exclusive`, unrelated: ignore it and say so if it fails for you).
- `runs/`, `roms/`, `baselines/`, `kb/rom_tables.json` are gitignored: **no ROM, no `kb/` tables, no `runs/` in your worktree.** Tests use `FakeEmulator`, `tmp_path` and fixture tables passed in as dicts.
- ROM trainer placement (`kb/rom_tables.json` `map_trainers`, resolved by `trainers.trainers_on(map_id)` -> `[{"class", "party", "x", "y", "mons": [(level, species)]}]`, in ROM list order). **Each row has ONLY `class`, `party` (1-based party number within the class) and `x`, `y`. There is NO facing and NO sight range in the drained data**: verified by printing the rows. So the trainer's line of sight is UNVERIFIED; the avoidance logic uses a named guess `SIGHT_GUESS = 4` tiles in the four directions and says so in its log lines and report. Whether the (x, y) are in the same tile frame as the learned maps' `[map, x, y]` positions is also UNVERIFIED (the controller checks it on a checkpoint). Route 24 (map 0x23 = 35), ROM list order: ROCKET p6 (11,15) 15 EKANS 15 ZUBAT; JR.TRAINER(M) p2 (5,20) 14 RATTATA 14 EKANS; JR.TRAINER(M) p3 (11,19) 18 MANKEY; LASS p7 (10,22) 16 PIDGEY 16 NIDORAN(F); YOUNGSTER p4 (11,25) 14 RATTATA 14 EKANS 14 ZUBAT; LASS p8 (10,28) 14 PIDGEY 14 NIDORAN(F); BUG CATCHER p9 (11,31) 14 CATERPIE 14 WEEDLE. Route 25 (map 36): YOUNGSTER p5 (14,2) 15 RATTATA 15 SPEAROW; YOUNGSTER p6 (18,5) 17 SLOWPOKE; JR.TRAINER(M) p2 (24,4) 14 RATTATA 14 EKANS; LASS p9 (18,8) 15 NIDORAN(M) 15 NIDORAN(F); YOUNGSTER p7 (32,3) 14 EKANS 14 SANDSHREW; LASS p10 (37,4) 13 ODDISH 13 PIDGEY 13 ODDISH; HIKER p2 (8,4) 15 MACHOP 15 GEODUDE; HIKER p3 (23,9) 13 GEODUDE x3 13 MACHOP; HIKER p4 (13,7) 17 ONIX.
- Prize and XP: `items_catalog.trainer_prize(cat, cls, party) -> int | None` = the class's base money x the level of the party's LAST mon (the catalog `cat` is `items_catalog.load()`, ROM-derived and gitignored; pass a fixture `cat` in tests: `{"trainers": {...}, "trainer_money": {"LASS": 15, ...}}`). Prize money is paid ONCE per trainer (Robert: trainer prizes are one-time, wild pays nothing). XP per kill: `xpmath.xp_gain(base_exp, enemy_level, trainer=True, participants=1)` = `base_exp * level / 7 * 1.5` (`base_exp` from `species_by_dex[...]["base_exp"]`). Wild XP per encounter on a map: `grind.atlas.prior_xp(row, base_exp)` (measured today: Route 24 96, Route 3 51, Route 2 28).
- Battle record trainer dict (from `battle.py`): `{"map": battle_map, "pic": ..., "x": ..., "y": ...}` where x/y come from the NPC entry (`x`,`y` or the last seen `last`). A trainer who sights the player WALKS UP, so the battle-time tile is not the placement tile: match by the NPC's recorded positions (`npcs[...]["positions"]` keys `"x,y"`, all tiles it was seen on), not only the last one.
- Person-tile rule today (`memory_nav._person_tile`): a tile is a person's if it is in `temp_blocked` or a STATIONARY NPC (`moves is False`) was last seen there; such a tile is never a frontier side. A person physically blocks movement (you cannot walk through a trainer), so a beaten trainer's tile is still IMPASSABLE for routing; it is simply never a target and never a reason to explore.
- Event flags: `wEventFlags` at 0xD747..0xD886 (`ramlab.flags.FLAG_LO/FLAG_HI`; the captain flags were found at 0xD803 bits 0 and 1 by `ramlab`). **The beaten-trainer flag bits are NOT known in this repo.** Devin cannot mine (no ROM, no states). Leave `flag_bit` empty in the ledger schema; the controller fills it (section 6, controller step).
- Beaten is PER SAVE, not per ROM or per swarm: a trainer beaten in agent A's game is not beaten in agent B's game, and a run started from a late checkpoint has beaten trainers it never fought. The shared memory (`ctx.mem.data`, merged across agents by `swarm_merge.merge_memory` with max/union rules) therefore must NOT carry "beaten"; it carries only static knowledge about a trainer (class, party, prize, XP, flag bit). Per-run beaten state lives in the ledger object and the run directory. This is a deliberate correction of the request to merge "beaten" through `swarm_merge`; say so in your report.
- Existing seams: `ctx.mem.data["maps"][str(map)]["npcs"]`, `ctx.mem.temp_blocked` (routing-only, decaying), `WorldGraph(...).path(...)` as used in `learner_hunt.py`, `readiness.fight`, `ctx.battle_log`, `ctx.trainer_npc`, `ctx.battles_won`, `knowledge.party.our_party`.
- **Files you must NOT modify:** `src/pokeagent/explorer/planner*.py`, `ship_gate.py`; no event-flag writes anywhere (read-only RAM: the ledger READS flags, never sets them; a test asserts no `emu.set`/`write` is called).

## 3. Scope (one PR, in order)

1. `explorer/trainer_ledger.py` (pure + thin ctx glue): the ledger, `beaten_trainers(ctx)`, matching battle/NPC records to ROM placements, persistence.
2. `explorer/trainer_route.py` (pure): next combat target on the route; engage / avoid / save decision; routing-only avoidance.
3. `grind/trainer_spots.py` (pure) and a section in `tools/grind_report.py`: trainers as one-time grind options, ranked against wild spots.
4. `knowledge/area_resistance.py` (pure) and a report line: the party's type-chart margin against an area's trainer set (report only).
5. Shared static trainer knowledge in `ctx.mem.data["trainers"]` and `swarm_merge.merge_trainers`.
6. Tests.

## 4. The work

Every threshold is a NAMED constant with a comment that it is an untuned first value. Each new module under 300 lines.

### 4.1 The ledger (`explorer/trainer_ledger.py`)

```python
@dataclass
class TrainerEntry:
    map: int; idx: int                    # idx = index in trainers.trainers_on(map) (ROM list order, stable per ROM)
    cls: str; party: int; x: int; y: int  # ROM placement
    state: str = "unknown"                # "beaten" | "unbeaten" | "unknown"
    source: str = ""                      # "battle_log" | "flag" | "talk_no_battle" | "initial"
    step: int | None = None; flag_bit: tuple[int, int] | None = None   # (addr, bit) once the controller has mined it
class TrainerLedger:
    def __init__(self, placements: dict[int, list[dict]], flag_bits: dict[str, tuple[int, int]] | None = None)
    def entries(self, map_id: int) -> list[TrainerEntry]
    def mark_beaten(self, map_id: int, idx: int, source: str, step: int) -> None
    def match(self, map_id: int, positions: list[tuple[int, int]], enemy_species: list[str] | None = None) -> int | None   # the ROM placement idx an NPC (all tiles it was seen on) corresponds to
    def sync_flags(self, flags: bytes) -> None     # for entries with a flag_bit: state from the live RAM block (beaten iff the bit is set)
def beaten_trainers(ctx) -> set[tuple[int, int, int]]   # {(map, x, y)} of beaten ROM placements: the seam Goal_Procedures' AfterVictory/ProcedureRunner call
```
- **State sources, in priority order:** (1) `flag`: when an entry's `flag_bit` is known, `sync_flags(emu.read_range(0xD747, 320))` makes RAM the truth every `LEDGER_SYNC_EVERY = 50` steps (cheap, not per press); (2) `battle_log`: on a trainer win (`battle.py` sets `ctx.trainer_npc["beaten"]`), the ledger takes the NPC's recorded positions and `enemy_species` from the battle record and calls `match` -> `mark_beaten(..., "battle_log", step)`. `match` picks the ROM placement of that map with the smallest Manhattan distance to ANY recorded tile within `MATCH_MAX_DIST = 6`, tie-broken by the one whose ROM party contains the record's enemy species; no placement within range -> no entry changes and one log line; (3) `talk_no_battle`: pressing A at a ROM placement tile (the NPC faced) and getting text with NO battle starting within `TALK_WAIT_STEPS = 12` presses means the trainer has nothing to fight about = beaten (source `talk_no_battle`; flagged UNVERIFIED in the log line, it assumes an unbeaten trainer always battles when spoken to); (4) `initial`: a run that starts from a checkpoint whose `meta.initial_goals` already include a goal AFTER a map's trainer stage cannot know: entries stay `unknown`, never assumed.
- `unknown` is treated as unbeaten for targeting but never as a hazard (talking to a beaten trainer costs a few presses and turns into `talk_no_battle`). Document this.
- **Persistence:** per-run beaten state is written to `<run dir>/trainers.json` at the same cadence as `levels.jsonl` flushes and at shutdown (atomic write); on start a run reads its own file only if resuming. Shared static knowledge goes to `ctx.mem.data["trainers"]` as `{"<map>:<idx>": {"cls", "party", "prize", "xp", "flag_bit"}}` (NO beaten state). `tools/swarm_merge.py::merge_trainers(dst, src)` (called from `merge_memory`): union of keys; for a key present in both, keep non-empty values, prefer a `flag_bit` that is set over None, and if two non-None `flag_bit` values disagree keep dst's and record `"conflict": true`. Idempotent; malformed input ignored.
- `beaten_trainers(ctx)` returns the beaten set for the CURRENT run's ledger (`ctx.trainer_ledger`, created lazily from `trainers.trainers_on` for the maps visited), never raises, and returns an empty set when there is no ROM data.

### 4.2 Pathing: next target, engage or avoid (`explorer/trainer_route.py`)

```python
SIGHT_GUESS = 4          # UNVERIFIED trainer line of sight, tiles, 4 directions (the kb has no facing/range)
ENGAGE_MARGIN = readiness.MARGIN       # fight() score the party must clear to engage (0.30)
AVOID_BLOCK_FRAMES = 480               # routing-only block of sight-line tiles (same mechanism as temp_blocked)
MAX_TARGET_DETOUR = 40                 # path steps a target may add to the segment route
@dataclass(frozen=True) class TrainerOption: entry: TrainerEntry; steps: int; margin: float | None; action: str   # "engage" | "avoid" | "save" | "ignore"; plus why: str
def options(ledger, map_id, player, graph, route_steps, party_now, kb=None, cat=None) -> list[TrainerOption]
def next_target(opts: list[TrainerOption]) -> TrainerOption | None     # nearest "engage" along the route (smallest steps), ROM order breaks ties
```
- **Beaten trainers**: `ignore`: never a target, never a frontier side, still impassable for routing (they are persons). Wire this into the existing person-tile rule WITHOUT editing the planners: extend `memory_nav._person_tile` to also return True for a tile whose ROM placement the ledger says is beaten and which currently has a stationary NPC on or next to it (the NPC may have moved: use the NPC's recorded positions). One added predicate; the #150 behaviour is otherwise unchanged and its tests stay green.
- **Unbeaten (or unknown) trainers on the segment route** (the planner/goal route over the learned graph, `route_steps` = the path length to the goal): compute the path length to the trainer's APPROACH tile (the tile `TRAINER_APPROACH = 2` before the trainer along the line toward the player's side; a guess, named) and the detour it adds; simulate `readiness.fight(party_now, ROM party)` with the party's CURRENT HP (replace each member's HP with its current HP) -> `margin`. Decisions: `engage` when `margin >= ENGAGE_MARGIN` and the detour is `<= MAX_TARGET_DETOUR` or the trainer stands ON the route (a gauntlet like Nugget Bridge); `avoid` when the sim says the party loses or is thin (`margin < ENGAGE_MARGIN`) AND a route exists that stays out of the trainer's `SIGHT_GUESS` line; `save` when the party would win but the fight is optional and not worth now (4.3); `ignore` otherwise.
- **Avoidance is routing-only and never blocks the only route:** the sight-line tiles of an `avoid` trainer are added to `ctx.mem.temp_blocked` for `AVOID_BLOCK_FRAMES` only if `graph.path(...)` to the goal still exists WITH those tiles blocked; otherwise nothing is blocked and the decision is downgraded to `engage-forced` (log it; the fight then happens and `AfterVictory` heals). Nugget Bridge is a single lane: expect `engage-forced`.
- `next_target` feeds a log line `[trainer_route: next target LASS p8 (10,28): margin +0.61, 9 steps]` and sets `ctx.trainer_target` (a tuple the exploration/`goto` machinery may read); it does NOT drive the press by itself in this PR (no planner edit): a thin behaviour `explorer/behaviours/trainer_hunt.py`, registered right after `LearnerHunt` (and after `TeamHunt` when present), walks the learned graph to the approach tile like `learner_hunt.py` does, gated like it: not battling, no box, no procedure, not while a goal procedure/planner step wants the same tile, per-run cap `TRAINER_HUNT_STEP_CAP = 2000`.

### 4.3 "Save for later grinding" (`grind/trainer_spots.py`)

```python
@dataclass(frozen=True) class TrainerGrind: entry: TrainerEntry; xp: float; prize: int | None; steps: float; xp_per_step: float; margin: float; value: float
def trainer_xp(mons, base_exp) -> float          # sum over the ROM party of xp_gain(base_exp[sp], level, trainer=True)
def rank_trainer_grinds(ledger, map_id, party_now, base_exp, cat, spots, kb=None, top=5) -> list[TrainerGrind]
```
- Value of an unbeaten optional trainer: its XP (`trainer_xp`) plus its one-time prize converted at `YEN_PER_XP = 0.5` (named, untuned: 1 yen is worth half an XP point; the yen figure is Robert's "finite money pool"), divided by the steps to reach and fight it (battle steps from `grind.atlas.PRIOR_BATTLE_STEPS`, travel from the learned graph) = `xp_per_step`; it is eligible only when `readiness.fight` wins with `ENGAGE_MARGIN` (so a grind never walks into a loss). One-time: once beaten it is gone (the ledger removes it).
- `tools/grind_report.py` gains a section "trainers worth saving or taking" listing `rank_trainer_grinds` next to the wild `rank_spots` result so wild vs trainer XP/step is comparable; the report says which wins for the lead's current level. **The grind planner does not change in this PR:** the report and the pure function are the deliverable; making `GrindDrill` pick a trainer is a follow-up (name it `Trainer_Grind_Pick_Directive`). Say so in the report.

### 4.4 Resistance (`knowledge/area_resistance.py`, report only)

`resistance(party: list[Combatant], trainers: list[list[tuple[int, str]]], chart, moves, kb=None) -> dict` returns per trainer `{"party": ..., "margin": float, "worst_member": name, "weak_to": [types]}` and an `area_margin` = the minimum margin over the set (and the mean), using `readiness.fight` and `damage.type_mult` for the "weak_to" list (our types vs their move types). `tools/grind_report.py` prints `area resistance (Route 24, 7 trainers): min margin +0.18 (LASS p7), weak to: FLYING, POISON`. **Report only: no behaviour uses it** (Team_Builder_V2's `team_value` may import it later; do not edit `team_value.py` here, it may not be merged).

### 4.5 Tests (all fixtures; no ROM, no emulator)

`tests/test_trainer_ledger.py`: placements fixture from the Route 24 rows in section 2; `mark_beaten`/`state` round trip through `<run dir>/trainers.json`; `match` picks the right placement for an NPC that walked up (positions list) and returns None out of range; species tie-break; `sync_flags` with a fixture `flag_bits` and a flag block (set bit -> beaten); `talk_no_battle` marks beaten only after `TALK_WAIT_STEPS` presses without a battle; `unknown` is not a hazard; `beaten_trainers(ctx)` seam returns `{(map, x, y)}` and an empty set with no data; a test that no `emu.set`/write call is made anywhere (a recording FakeEmulator).
`tests/test_swarm_merge_trainers.py`: `merge_trainers` union, keeps non-empty, prefers a set `flag_bit`, records a conflict, idempotent, ignores malformed input, never carries `beaten`; `merge_memory` calls it (existing swarm_merge tests green).
`tests/test_trainer_route.py`: next-target selection on a fixture map (a `WorldGraph` fixture with a corridor and the Route 24 trainers): nearest unbeaten along the route; a beaten one is skipped but stays impassable; `engage` / `avoid` / `save` / `engage-forced` from fixture sims (a strong party engages, a weak party avoids when a bypass exists and is forced on a single-lane route); avoidance never blocks the only route; `_person_tile` extension returns True for a beaten trainer's tile, #150 tests unedited and green; `trainer_hunt.applies` False in battle/box/procedure and after the step cap.
`tests/test_trainer_grind.py`: `trainer_xp` against a hand-computed `xp_gain` sum; `rank_trainer_grinds` ranks by `xp_per_step`, drops trainers the sim loses to, drops beaten ones, converts prize with `YEN_PER_XP`; the grind report prints the section (capsys on the pure renderer).
`tests/test_area_resistance.py`: margins and `weak_to` on a synthetic cartridge, `area_margin` min/mean, empty inputs return an empty result.

## 5. What NOT to do

- No edits to `planner*.py`, `ship_gate.py`. No event-flag WRITES, ever (read-only). No RL/bandit. No change to `GrindDrill` or the grind planner's choice (report only). No edit to `team_value.py`. No battle move-choice changes. No emulator runs; no `uv run pokeagent ...`; no reading `kb/` or `runs/`.
- Do not merge "beaten" through `swarm_merge` (section 2: per save); do not assume the (x, y) frame or the trainer's sight range; do not block the only route. Each module under 300 lines, no new dependencies.

## 6. Verification

- `uv run pytest -q tests/test_trainer_ledger.py tests/test_swarm_merge_trainers.py tests/test_trainer_route.py tests/test_trainer_grind.py tests/test_area_resistance.py` - new tests pass (paste the tail).
- `uv run pytest -q` green; paste the before/after tails and `git diff --stat main`; confirm no forbidden file changed and that no event-flag write exists.
- **Controller steps (not Devin; the ROM and the runs are on the laptop):**
  1. Fill `flag_bit`: with `ramlab` (`src/pokeagent/ramlab/flags.py`, `pipeline.py`, `tools/ram_discover.py`) take the runs/states that beat Route 24 and 25 trainers: for each `runs/battles.jsonl` record with `kind == 2`, `trainer.map` in (35, 36) and `won`, diff the 320-byte `wEventFlags` block (0xD747..0xD886) between the state just before the battle and just after; the bit that flips exactly once per trainer and per placement is that trainer's beaten flag. Confirm across >= 3 runs, then write the `(addr, bit)` pairs into a small committed table the ledger loads (`src/pokeagent/data/trainer_flags.json`, keyed `"<map>:<idx>"`; Devin leaves the file with `{}` and the loader tolerant of it).
  2. Verify the (x, y) frame by standing on a checkpoint at Route 24 and comparing a ROM placement with the NPC's learned tile; verify or replace `SIGHT_GUESS` and `TRAINER_APPROACH` from the ROM trainer headers (facing and view range), then update the constants.
  3. Headless run from `runs/checkpoints/nugget_bridge.state`: confirm the ledger marks each bridge trainer beaten after its fight, `[trainer_route]` lines name the next target, and no presses go into a beaten trainer.

## 7. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation is rejected and ends the run. No installs, downloads or fetches.
  Never read outside the worktree.
- **Do not run the `pokeagent` entry point (the sandbox refuses it). Do not list the directory tree recursively; use `git ls-files`.
  Do not read outside the worktree. Create no scratch files; deleting is denied. If something expected is missing, stop and write that in the Status row.**
- Do not search, glob or hunt for a missing file or fact: stop and say so in the Status row.
- Test commands are exactly `uv run pytest -q` and `uv run pytest -q tests/<file>`. Never bare `python`.
- Work only on branch `directive/pokeagent-trainer-ledger-and-battle-avoidance-directive`. Never commit to `main`; never push; never deploy; no `git stash`. Commit on the branch as you go.
- Create no scratch or debug files (deleting is denied and ends the run). If one is truly needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row; do not try another way around it.
- SOLID/SRP/KISS is a hard rule here: small new modules (under 300 lines), no new dependencies.

## 8. Completion criteria

- [ ] `trainer_ledger.py` (states, sources, match, `beaten_trainers` seam, per-run `trainers.json`) and shared static `ctx.mem.data["trainers"]` + `swarm_merge.merge_trainers`; no beaten state in shared memory
- [ ] `trainer_route.py` + `trainer_hunt.py` (next target, engage / avoid / save / engage-forced, routing-only avoidance that never blocks the only route); `_person_tile` extension; #150 tests green
- [ ] `grind/trainer_spots.py` and the `tools/grind_report.py` section; `knowledge/area_resistance.py` and its report line (report only)
- [ ] The five new test files pass; `uv run pytest -q` green (tail pasted); `git diff --stat main` pasted; no forbidden file changed; no flag writes
- [ ] Status row moved to Review with the branch name

## 9. Report

Findings first: test tails (before/after), `git diff --stat`, the final signatures and every named constant, the per-save correction to the merge request, what the matching rule does with a walked-up trainer, how the `_person_tile` extension is written, whether the Goal Procedures PR was merged (and who calls `beaten_trainers`), the exact list of unverified items (sight range, tile frame, flag bits, `talk_no_battle`), and anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-07 16:19 · robert-claude-laptop · none → Draft — Claude 2026-11-07: trainer ledger (per-save beaten state), next-target/avoid/save, resistance report
- 2026-11-07 16:19 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; lint_override: dispatch-path-missing greenfield/gitignored
<!-- queue:end -->
