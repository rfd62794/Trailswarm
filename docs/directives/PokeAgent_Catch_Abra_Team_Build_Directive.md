# PokeAgent: Catch an Abra and keep it (goal catch_abra) - the first step of an alternative "abra" team build

Repo: PokeAgent (remote rfd62794/trailswarm; `git remote -v` shows https://github.com/rfd62794/Trailswarm.git). Branch: directive/pokeagent-catch-abra-team-build (create it from origin/main in your worktree).
Status: Pending (write "Blocked: <why>" here if you stop early).

## Why

Robert's direction (2026-11-17): "a run focused on building a Team with an Abra, as a Goal. And this gives us another alternative Team Build to explore later."
Two purposes. (1) A new goal that catches an Abra and keeps it in the party. Abra's only starting move is Teleport, and Teleport has no badge check
(Fly does: Thunderbadge), so an Abra in the party opens a later Mew Glitch probe on Route 25 (see docs/directives/PokeAgent_Glitch_Trainer_Escape_Directive.md
and docs/research/gen1-glitches-2026-11-15.md; that probe is NOT part of this directive). (2) An alternative TEAM BUILD ("abra") next to the builds
the save library already tells apart, for later exploration. Starters stay equal: no starter preference anywhere in this work.

## Facts established by the controller (pasted because the run cannot read outside its worktree or fetch anything)

pokered citations (pret/pokered master, read 2026-11-17):

- data/wild/maps/Route24.asm lines 1-24: `def_grass_wildmons 25` (encounter rate 25). Slots 0-9. Red slots: 0 WEEDLE 7, 1 KAKUNA 8, 2 PIDGEY 12, 3 ODDISH 12, 4 ODDISH 13,
  5 ABRA 10, 6 ODDISH 14; then the shared tail (both versions): 7 PIDGEY 13, 8 ABRA 8, 9 ABRA 12. Abra slots: 5 (L10), 8 (L8), 9 (L12).
- data/wild/maps/Route25.asm lines 1-27: `def_grass_wildmons 15`. Red slots: 0 WEEDLE 8, 1 KAKUNA 9, 2 PIDGEY 13, 3 ODDISH 12, 4 ODDISH 13, 5 ABRA 12, 6 ODDISH 14, 7 ABRA 10, 8 METAPOD 7, 9 CATERPIE 8.
  Abra slots: 5 (L12), 7 (L10).
- data/wild/probabilities.asm lines 17-26 (slot chance out of 256): 0:51 1:51 2:39 3:25 4:25 5:25 6:13 7:13 8:11 9:3.
  So per grass encounter: Route 24 Abra = (25+11+3)/256 = 39/256 = 15.2% (L10 9.8%, L8 4.3%, L12 1.2%); Route 25 Abra = (25+13)/256 = 38/256 = 14.8% (L12 9.8%, L10 5.1%).
  The encounter rate byte (25 vs 15) scales how often a grass step triggers a battle; Route 24 is the better hunting ground.
- Other Red source (NOT in scope, mention only): data/events/prizes.asm lists ABRA as a Game Corner prize at 180 coins (Red) and data/events/prize_mon_levels.asm gives it level 9 in Red. A grep of the wild files for Routes 5-10 returned 0 ABRA.
- data/pokemon/base_stats/abra.asm line 13: `db TELEPORT, NO_MOVE, NO_MOVE, NO_MOVE ; level 1 learnset`; catch rate 200 (line 7); the TM/HM list (lines 17-21) includes TELEPORT, PSYCHIC_M, FLASH.
  UNVERIFIED: whether a wild Abra at L10-L12 knows only Teleport (the controller read the base-stat file only, not the wild-mon move generation); the plan below is safe either way because it never fights first.
- data/moves/moves.asm line 113: `move TELEPORT, SWITCH_AND_TELEPORT_EFFECT, 0, PSYCHIC_TYPE, 100, 20`.
- engine/battle/effects.asm `SwitchAndTeleportEffect` (line 810), enemy branch `.handleEnemy` (lines 855-880): in a wild battle (wIsInBattle == 1) the enemy Teleport SUCCEEDS
  (the wild mon flees) whenever the wild level is >= the player's active mon level (lines 861-863 `cp b / jr nc, .enemyMoveWasSuccessful`). If the wild level is lower it succeeds unless
  a random number in [0, playerLevel+wildLevel] is below wildLevel/4 (lines 864-874), i.e. it almost always succeeds. A thrown ball resolves on OUR turn before the Abra acts.
  Consequence: the catch plan is ONE ball on turn 1 of the encounter (or a status that stops it acting: sleep/paralysis if the party has such a move);
  NEVER weaken it first (a damaging move gives it its turn and it teleports away). If the throw fails the Abra then flees: expect one ball per encounter, no second chance.
  Ball stock needed: BALLS_MIN balls (default 12, a constant) before the hunt starts; buying balls is NOT in this directive (say so in the report if stock is short).
- engine/menus/start_sub_menus.asm: `.fly` (line 132) starts with `bit BIT_THUNDERBADGE, a / jp z, .newBadgeRequired` (lines 133-134), whereas `.teleport` (lines 205-226)
  has NO badge check: only `CheckIfInOutsideMap`, then it sets BIT_FLY_WARP and BIT_ESCAPE_WARP and warps to the last Pokemon Center. That is why a caught Abra is useful early.

PokeAgent facts (at origin/main cb4bb0ed in this worktree; every name below was grepped):

- Route 24 is map 35 (0x23): goal `nugget_bridge` is `{"map": [35]}` (src/pokeagent/data/campaign.json line 27, goals.py line 119 `"nugget_bridge": 0x23 in seen`). Route 25 is map 0x24 (0x58 Bill's house is its only warp, goals.py comment).
  The ladder around it: `beat_misty -> nugget_bridge -> team_ready -> to_bill -> ss_ticket` (campaign.json lines 26-30). Both Abra maps are reachable by the agent: nugget_bridge and to_bill are existing, done goals.
- Wild tables come from the kb (kb/rom_tables.json, gitignored, ROM-derived): `wild_by_map` keyed by map id as a string; tests/test_catch_plan.py line 32 has Route 24's grass list ending `[10,"ABRA"],[14,"ODDISH"],[13,"PIDGEY"],[8,"ABRA"],[12,"ABRA"]`. A worktree has no ROM tables, so tests use synthetic kb dicts (tests/test_catch_plan.py shows the shape).
- Existing catch machinery (reuse, do not rewrite):
  - src/pokeagent/explorer/behaviours/catch.py (219 lines; keep it under 300): `Catch.step` asks `catch_list.catch_wanted(sp_name, our_party(...), dex_owned_count(...), upcoming_needs(...), owned=..., wants=ctx.team_wants)`, then `_policy_hint` calls `knowledge.catch_policy.decide(...)`; `full_party_slot(ctx, party)` marks a deposit pick when the party is full.
  - src/pokeagent/knowledge/catch_policy.py `decide(...)` order: skip (trainer, no ball, MAX_TURNS 8) -> overpower gate -> `_status_step` (status first if it gains >= STATUS_MIN_GAIN) -> weaken with `WEAKEN_TARGET = 0.35` (a damage_move while HP > 35%) -> throw. For an Abra the weaken step is exactly wrong (it flees on its first turn); this directive adds a flee-species rule BEFORE the weaken step.
  - src/pokeagent/explorer/catch_list.py: `catch_wanted(...)`, `NEVER_CATCH = frozenset({"KAKUNA"})`, `HM_MOVE`, `upcoming_needs(goals)`.
  - src/pokeagent/knowledge/catch_plan.py + team_value.py already value ABRA (EVOLUTIONS has "ABRA": ("KADABRA", 16)); tests/test_catch_plan.py already ranks `ODDISH/ABRA@Route24`. `ctx.team_wants` (context.py line 185) is the species->reason map Catch reads; src/pokeagent/explorer/behaviours/team_hunt.py (182 lines) walks to the top planned catch's map.
  - src/pokeagent/bandit/hook.py `wild_flee(ctx, rule_flee)` returns the rules' answer unchanged when the rules would try a catch (line 34 comment "not the bandit's call"). Do not change it.
- Closest analogue of a team-member acquisition goal: `buy_magikarp`. goals.py: `"buy_magikarp": magikarp_goal_settled(emu, st, seen)` (src/pokeagent/magikarp.py, 127 lines) is settled when owned OR no longer possible (< 500 money, full party) OR Mt Moon 1F was seen. Its step cap and bookkeeping live in explorer/magikarp_deferral.py (`BUY_STEP_CAP`, ctx.buy_skipped, ctx.buy_steps; context.py lines 166-167). Copy that shape: a sticky pure settle function, a step cap on ctx, one plan_goal bookkeeping hook. `cut_learner` (goals.py: `g["cut_learner"] = g["hm01_cut"] and cut_learner_settled(...)`) is the other analogue, with `LEARNER_STEP_CAP` in knowledge/cut_learner.py and the learner_hunt behaviour (explorer/behaviours/learner_hunt.py) that walks to a grass map for a species.
- Team floor (src/pokeagent/knowledge/team_floor.py): `TEAM_FLOOR_MEMBERS = 2`; `FLOOR_BY_GOAL` has beat_brock 12 ... beat_surge 22; `check(goal, party, boss, kb)` counts only "sendable" non-Magikarp members (a damaging move that hurts a boss mon) at or above the floor, capped at the sendable members there are. An Abra with only Teleport is NOT sendable, so it neither counts toward the floor nor can it block it. Do not edit team_floor.py. The party-slot policy below depends on this.
- Release / deposit: `catch.full_party_slot` -> `team_plan.release_candidate(party, protected=..., values=...)` (knowledge/team_plan.py line 297) picks the lowest-value unprotected slot; `protected` holds the trainee and needed HM learners. A wild Abra in the party must become protected while the build is "abra".
- A team build concept ALREADY EXISTS in the save library: src/pokeagent/team_fp.py `build_key(fp, kb)` = members sorted by (species line, level rounded down to 5) joined as `LINE:L<band>`, e.g. `ABRA:L10|CHARMANDER:L15`; moves are not part of a build; `species_line` uses knowledge/team_value.EVOLUTIONS. The library (src/pokeagent/statelib/library.py, start_pick.py, cells.py) and the curriculum (tools/seg_store.py, tools/seg_sched.py, tools/seg_ingest.py `build_attempt` records `build` and `cell`) index by that derived key. So an Abra build needs NO new library code: a state whose team holds an ABRA line already has a build key containing `ABRA:`. What does NOT exist is a way to ASK a run to build that way: there is no named build flag today. This directive adds the minimal named flag `build` ("" default, "abra") and nothing else. (src/pokeagent/party_rules.py is the rule registry, `RULES = (Rule("wild-never-catch", ...),)`; do NOT add a rule for Abra, it is not a violation.)
- Save-state names: the real checkpoint is `runs/checkpoints/nugget_bridge.state` (+ `.fp.json`, `.goals.json`), gitignored, present on the controller's machine; a synthetic copy is committed at tests/fixtures/review/runs/checkpoints/nugget_bridge.state (fp: `{"v":1,"synthetic":true,"map":35,"badges":2,"party":[[133,10,23,23]],"money":1500}`). Checkpoints are written by explorer/press_goals.py and named after the goal; the new goal's checkpoint would be `catch_abra.state`.

## Scope (exact files; keep every NEW source file under 300 lines)

<!-- new: src/pokeagent/knowledge/flee_catch.py -->  pure logic, no emulator: FLEE_SPECIES, `flee_on_turn(species_name, moves)`. Under 150 lines.
<!-- new: src/pokeagent/abra_goal.py -->  the pure settle function `catch_abra_settled(...)` plus constants (ABRA_STEP_CAP, BALLS_MIN). Under 120 lines.
<!-- new: src/pokeagent/explorer/abra_hunt.py -->  the walk-to-Abra-grass helper (model on explorer/behaviours/learner_hunt.py; may be a behaviour module if that is the repo's shape). Under 200 lines.
<!-- new: tests/test_catch_abra.py -->  synthetic tests.
Edit: src/pokeagent/data/campaign.json (one new row, see "The work" 1) and tests/test_goal_order.py (the EXPECTED prefix list covers the first 26 ids; update it for the new row, nothing else).
Edit: src/pokeagent/goals.py (the new detector entry in check_goals), src/pokeagent/knowledge/catch_policy.py (call flee_catch before the weaken step; at most about 15 lines), src/pokeagent/explorer/catch_list.py (catch_wanted returns a reason for ABRA when build == "abra"), src/pokeagent/explorer/behaviours/catch.py (protect an ABRA slot in `full_party_slot` when build == "abra"; stay under 300 lines), src/pokeagent/explorer/context.py (ExplorerOptions.build: str = ""; ctx fields abra_steps/abra_skipped modelled on buy_steps/buy_skipped), src/pokeagent/explorer/behaviours/__init__.py (one registration), tools/explore_headless.py and tools/explore_demo.py (the `--build` flag, env POKEAGENT_BUILD, CLI wins; reject values other than "" and "abra").
Do not touch: team_floor.py, the training controller, readiness, bandit/hook.py, party_rules.py, statelib, planner_*.py beyond what the run proves it must.

## The work

1. Goal `catch_abra` (campaign.json): `after: "team_ready"`, so it sits between team_ready and to_bill (after nugget_bridge, before beat_surge, which is later in the ladder); change `to_bill`'s `after` to `catch_abra`. Hand-coded detector in goals.py `catch_abra_settled(emu, st, seen)`, sticky like buy_magikarp. Settled when ANY of:
   (a) opts.build != "abra" (default runs: the goal is auto-settled and the ladder is unchanged - this keeps every existing build and test untouched);
   (b) an ABRA (or its line, KADABRA/ALAKAZAM, names via knowledge.kb tables) is in the party;
   (c) the step cap ABRA_STEP_CAP is spent (ctx.abra_skipped);
   (d) fewer than BALLS_MIN balls in the bag AND no money for any (log this case; do not buy balls here).
   Pure function, kb passed in, ids resolved by name through `table(kb, "name_of_internal")`, never hard-coded.
2. Reaching an Abra map: when the goal is open, set `ctx.team_wants = {"ABRA": "catch_abra goal (build abra)"}` and hunt grass on Route 24 (map 35; nearest first) falling back to Route 25 (0x24), through the same walk-to-grass machinery learner_hunt/team_hunt use; do not invent a new pathfinder. Cap at ABRA_STEP_CAP steps (default 3000, a constant, UNTUNED).
3. Turn-1 throw (knowledge/flee_catch.py): `FLEE_SPECIES = frozenset({"ABRA"})` plus `flee_on_turn(name, moves)`: true for a species in FLEE_SPECIES, or any wild whose known moves are all in {TELEPORT, ROAR, WHIRLWIND} (kb move names). In `catch_policy.decide`, after the may_throw / ball checks and BEFORE the overpower gate's damage logic and the `WEAKEN_TARGET` damage_move step: if flee_on_turn is true and turn == 0 (the first policy turn of this battle) return `CatchStep("throw", ball=<best ball>, why="flee species: throw on turn 1 (it teleports on its own turn)")`. The existing `_status_step` may run on turn 0 only when the active mon has a sleep/paralysis/freeze move with gain >= STATUS_MIN_GAIN as today (UNVERIFIED that any early party has one) - sleep stops the Abra acting. Never a damage_move on a flee species. If a throw fails and the wild is still there, throw again (the existing MAX_TURNS 8 still ends it).
   `Catch.step` already skips a battle with no ball: keep that, and make the log line say "no ball: Abra encounter let go".
4. Keep Abra in the party: while `ctx.opts.build == "abra"`, `full_party_slot` adds every ABRA-line slot to `protected` (never the deposit pick); the bandit and switch code stay untouched. The build flag makes the catch itself wanted (catch_list: ABRA wanted with reason "catch_abra goal (build abra)" even when the dex/HM rules would not want it). If the party is full (6), the existing lowest-value deposit pick applies to a NON-Abra member; if no unprotected member exists, skip the catch with the existing "party full" log.
5. Party-slot policy that does not break the team floor: the Abra takes a free slot only when the party has fewer than TEAM_SIZE (6) members, otherwise it replaces the single lowest-value unprotected member via the existing `release_candidate`; never the trainee, never a needed HM learner (existing protection). Because an Abra with only Teleport is not "sendable", team_floor.check ignores it: the floor is computed over the other members exactly as today, so the Abra can neither satisfy nor block it. Do not edit team_floor.py or the training target code; add one test that proves floor.check's verdict is identical with and without an ABRA (L10, Teleport) member in the party.
6. The "abra" build: only the named flag above plus the derived library key. Add to tests/test_catch_abra.py one test that `team_fp.build_key` of a synthetic fp with an ABRA member contains `ABRA:` and equals the key with the Abra at a different level inside the same 5-level band. No library, curriculum or party_rules changes.
7. Logging: one run-log line per Abra encounter through ctx.log ("res" channel): level, turn, action (throw/status/skip), ball, result (caught/fled/no ball); one summary line when the goal settles (caught, cap, no balls) with step count and encounters.

## Synthetic tests (tests/test_catch_abra.py; fake kb dicts, fake Combatants, no ROM, no emulator)

- flee_on_turn: ABRA true; PIDGEY false; a mon whose moves are only {TELEPORT} true; a mon with TACKLE false.
- decide on turn 0 with a flee species returns a throw (never damage_move) even at 100% HP; with a sleep-capable active mon it may return the status step; on turn 1 after a failed throw it throws again; a non-flee species is unchanged (weakens first as today; reuse the tests/test_catch_policy.py fixtures).
- catch_abra_settled: default build -> settled; build abra, no Abra -> open; Abra in party -> settled and sticky; Kadabra/Alakazam count; step cap spent -> settled; no balls and no money -> settled.
- catch_wanted: ABRA wanted for build abra, not wanted for build "" (existing behaviour), KAKUNA still never wanted.
- full_party_slot: a full party with an ABRA never picks the Abra slot when build == "abra"; picks it normally when build == "".
- floor invariance: team_floor.check identical with and without an ABRA member.
- build key: see work item 6.
- layering: the existing explorer layering test (explorer may not import atlas; modules under 300 lines) stays green.

## What NOT to do

- No ROM offsets, bytes or opcodes in code, docs or tests. Never publish ROMs. No SRAM or RAM writes, no save-state edits, no cheats to make an Abra appear.
- No Mew Glitch code or probes, no Teleport menu use, no Fly; this directive only acquires and keeps the Abra.
- No starter preference: the build flag must not depend on or choose a starter.
- No changes to team_floor, training, readiness, bandit/hook.py, party_rules, the library or curriculum code.
- No explorer -> atlas imports. No GUI, no web views.
- Do not buy balls, do not use the Game Corner (a later option only).

## Verification (run exactly these from the worktree root; every file in the first command was run by the controller on origin/main and passed: 46 passed)

uv run --frozen pytest -q -p no:cacheprovider tests/test_catch_plan.py tests/test_team_floor.py tests/test_goal_order.py tests/test_party_rules.py tests/test_team_fp.py tests/test_catch_policy.py
uv run --frozen pytest -q -p no:cacheprovider tests/test_catch_abra.py

The second command targets the file this run creates; it must end with 0 failed. Also run, as one focused command, any other test file you edited or that a grep for `team_ready` or `to_bill` in tests/ shows depends on the ladder, and paste it. xdist is not in the default group: do not install it, run serially. Paste the real output tails. No --help commands, no other test runners.

## Rules for this run

- NON-INTERACTIVE. No installs, no fetches, no network. Never read outside the worktree.
- No scratch files except under .devin-scratch/ (delete it before the final commit).
- Do not hunt for missing files: if something named here does not exist, stop and write why in the Status row.
- Work on branch directive/pokeagent-catch-abra-team-build; commit and push that branch only. Never commit to main, never push main, never merge.
- Each new module small and single-purpose (SOLID/SRP/KISS); split before 300 lines.

## Forbidden Actions

Running the ROM or any emulator, editing or creating save states, SRAM or RAM writes, force-push, history rewrite, deleting branches, merging,
touching main, editing live config, changing repo visibility, publishing anything, or editing other repos.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(git diff)
- Exec(git grep)
- Exec(git status)
- Exec(git add)
- Exec(git commit)

## Required from User

The controller (not Devin) runs the real-ROM check from `runs/checkpoints/nugget_bridge.state` with `--build abra`: reach Route 24, meet an Abra (about 1 in 6.5 grass encounters on Route 24), throw on turn 1, confirm the ball lands or the Abra teleports, confirm the Abra stays in the party and the build key reads `ABRA:`. The controller also confirms the UNVERIFIED items: the wild Abra's moves (Teleport only), no early party status move, deposit behaviour with a full party, and that the real-ROM kb names ABRA/KADABRA/ALAKAZAM. Devin: list in your report every UNVERIFIED assumption you coded against.

## Completion criteria

- All files in Scope done; both verification commands pass with 0 failed; the layering test is green; no new module over 300 lines.
- Default runs are unchanged: with build "" the goal reads settled and no existing behaviour differs (covered by tests).
- With build "abra" the goal asks for an Abra on Route 24/25, throws on turn 1 and never weakens a flee species, protects the Abra from deposit, and leaves team_floor.check's verdict unchanged.
- Branch pushed; working tree clean; .devin-scratch removed.

## Report

Findings first (what you built, design choices, every UNVERIFIED assumption), then evidence (real test output tails), then the recommended next action (the controller's real-ROM check above). Keep it short and list the head sha of the pushed branch.

## Status row text (for the queue, when you finish)

"Review: catch_abra goal + flee-species turn-1 throw + build flag abra implemented on directive/pokeagent-catch-abra-team-build (head <sha>); synthetic tests only; real-ROM check from nugget_bridge.state is the controller's."

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Approved |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-17 21:21 · robert-claude-laptop · none → Queued — Robert 2026-11-17: Abra team build as a goal. Merged as docs PR #328 (5021e481). Approve after the Surge fix round returns (one heavy local job at a time).
- 2026-11-18 00:45 · robert-claude-laptop · Queued → Approved — lint override: kb/rom_tables.json is gitignored ROM-derived data that dispatch provisioning copies into the worktree (copytree kb); knowledge/flee_catch.py is a NEW file this directive creates (src/pokeagent/knowledge/); Exec(git push) is redundant with the default push path every PokeAgent run already uses (Surge rounds 1-5 pushed without a grant) and the deny rule still governs.
- 2026-11-18 01:21 · agentflow-tick · Approved → Blocked — dispatch refused (deterministic, no retry): sandbox needs refused: Exec(git push) matches deny rule Exec(git push --)
- 2026-11-18 01:23 · robert-claude-laptop · Blocked → Queued — Sandbox needs fixed on main by PR #330 (Exec(git push) removed; verified 3455/0/0). Requeue.
- 2026-11-18 01:37 · robert-claude-laptop · Queued → Approved — lint override: kb/rom_tables.json is gitignored ROM-derived data that dispatch provisioning copies into the worktree; knowledge/flee_catch.py is a NEW file this directive creates.
<!-- queue:end -->
