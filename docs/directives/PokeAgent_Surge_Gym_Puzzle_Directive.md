# PokeAgent: Lt. Surge gym trash-can puzzle and reaching Surge (goal beat_surge)

Repo: PokeAgent. Branch: directive/pokeagent-surge-gym-puzzle (create it from origin/main in your worktree).
Status: Pending (write "Blocked: <why>" here if you stop early).

## Why

The explorer can now cut the Vermilion tree and enter the gym (map 0x5C), but Lt. Surge sits behind electric barriers that open only after two
trash cans are found (the "puzzle" need on the beat_surge row of campaign.json). Nothing handles it, so the run wanders the gym until a cap.
Robert's decision (2026-11-16): explore BOTH solving modes in ONE module with a mode flag. SEARCH is the default (the agent finds the cans by
trying them); ORACLE is optional (reads the game's own lock values and goes straight to the cans). In SEARCH mode the RAM lock values may be
read ONLY to log and score the attempt (a referee), never to choose a can.

## Read first (at origin/main, in your worktree)

- src/pokeagent/explorer/behaviours/goal_talk.py: GOAL_TALKS, APPROACH, _hold_clear (reuse unchanged).
- src/pokeagent/explorer/fan_club.py: GYM, GYM_DOOR, PLANNER_MAPS, the _ask/_toward route pattern over the injected ctx.route_plan.
- src/pokeagent/explorer/field_cut.py and behaviours/field_cut.py: a menu/press behaviour with PRESS_CAP, MAX_TRIES, COOLDOWN, state(ctx).
- src/pokeagent/explorer/loop_memory.py: NEVER_VETO and the comment under it.
- src/pokeagent/knowledge/team_floor.py (FLOOR_BY_GOAL beat_surge = 22) and explorer/training_ctl/exit_rule.py (hold_clear). Reuse, do not change.
- src/pokeagent/data/campaign.json: the beat_surge row (detector badge 2, needs cut and puzzle).
- src/pokeagent/atlas/walkgrid.py: cell_tiles, rom_cave_planner (plan, plan.follow, plan.trees, plan.warp_tiles).
- src/pokeagent/explorer/behaviours/__init__.py: default_behaviours() order.
- tests/test_explorer_behaviours.py: the layering test (explorer may not import atlas; no module over 300 lines) and the fake-emulator style.
- src/pokeagent/data/ram_map.json: wFirstLockTrashCanIndex 0xD743, wSecondLockTrashCanIndex 0xD744, wGymTrashCanIndex 0xCD5B (all verified false).
- tools/explore_headless.py and tools/explore_demo.py: where ctx.route_plan is built (maps = fan_club.PLANNER_MAPS) and how options are parsed.

## Probe facts (data from a read-only real-ROM probe by the controller; you cannot run the ROM)

- Map 0x5C Vermilion Gym, 10x18 cells. Surge at (5,1). Trainers at (9,6), (3,8), (0,10); an NPC at (4,14). Exit warps (4,17) and (5,17).
  Electric barrier cells x 4-5, y 4-5 (closed state observed).
- RAM: wFirstLockTrashCanIndex 0xD743, wSecondLockTrashCanIndex 0xD744, wGymTrashCanIndex 0xCD5B.
- Lock event bits are NOT named in the repo (probe: D772=0x00, D773=0x1E, no lock open). Treat any "lock opened" bit as UNVERIFIED. Detect the
  barrier open by (a) the screen text "The 1st electric lock opened!" and "The 2nd electric lock opened!", and (b) the reset text "Nope, there's
  only trash here! Hey! The electric locks were reset!". The controller checked: these strings are NOT in the repo text tables, so mark them UNVERIFIED in a
  comment and match loosely (lower-cased words "electric lock", "opened", "reset", "only trash"). Barrier open is also visible as the barrier
  cells' tile ids changing on the live tile map (UNVERIFIED; log it, do not depend on it alone).
- 15 cans, id = col*3 + row with col = (x-1)/2, row = (y-7)/2. Table, idx: can (x,y) -> stand tile, facing:
  0:(1,7)->(1,6) DOWN; 1:(1,9)->(1,10) UP; 2:(1,11)->(1,12) UP; 3:(3,7)->(3,6) DOWN; 4:(3,9)->(3,10) UP; 5:(3,11)->(3,12) UP;
  6:(5,7)->(5,6) DOWN; 7:(5,9)->(5,10) UP; 8:(5,11)->(5,12) UP; 9:(7,7)->(7,6) DOWN; 10:(7,9)->(7,10) UP; 11:(7,11)->(7,12) UP;
  12:(9,7)->(9,8) UP; 13:(9,9)->(9,10) UP; 14:(9,11)->(9,12) UP.
  Stand tiles were picked from the walkable grid; cans 4 and 12 use the tile below because trainers block the tile above.
  Derive can positions IN CODE from the ROM grid (tile 0x1B in cell_tiles) via the injected planner; keep this table ONLY as the test fixture.
- Red behaviour (UNVERIFIED in the repo; background knowledge): the first lock is one random can; the second lock is an orthogonal neighbour of
  the first (no diagonals); a wrong can after the first lock resets both locks (re-randomized).
- Team at the probe: L19-20 plus an L30 lead; beat_surge team floor 22 (2 members); Surge's lead is Raichu L24. Readiness and training holds exist already.

## Scope (exact files)

<!-- new: src/pokeagent/explorer/gym_puzzle.py -->  pure logic, no emulator, no atlas import, under 300 lines.
<!-- new: src/pokeagent/explorer/behaviours/gym_puzzle.py -->  the GymPuzzle behaviour (name "gym_puzzle"), under 300 lines.
<!-- new: tests/test_gym_puzzle.py -->  synthetic tests.
Edit: src/pokeagent/explorer/behaviours/__init__.py (import, __all__, register GymPuzzle just BEFORE GoalTalk in default_behaviours).
Edit: src/pokeagent/explorer/loop_memory.py (add "gym_puzzle" to NEVER_VETO, with a one-line comment: it self-caps, like field_cut).
Edit: src/pokeagent/explorer/behaviours/goal_talk.py (a beat_surge row in GOAL_TALKS and in APPROACH only; no other change).
Edit: src/pokeagent/atlas/walkgrid.py (rom_cave_planner only: expose plan.cells_with_tile(map_id, tile) returning the (x, y) cells whose stepping
tile equals tile, built from the tiles it already computes) and tests/test_walkgrid.py (one test for it).
Edit: src/pokeagent/explorer/fan_club.py (add GYM to the planner map set) is NOT needed if you instead union frozenset({0x5C}) at the two tool
call sites; pick the smaller change and keep test_fan_club-style tests green.
Edit: tools/explore_headless.py and tools/explore_demo.py (the --gym-puzzle-mode flag, planner maps, option plumbing).
Edit: the options dataclass in explorer/context.py only if that is where the other flags live (a field gym_puzzle_mode: str = "search").

## The work

1. gym_puzzle.py (pure): GRID facts passed in, not hard-coded. Functions and state:
   - can_cells(planner, map_id) -> sorted list of can cells from plan.cells_with_tile(map_id, 0x1B); can_id(cell) with the col*3+row rule.
   - neighbours(cell_set, cell): orthogonal neighbours only, restricted to real cans.
   - stand_tile(cell, walkable, blocked): the tile above (facing DOWN) else below (facing UP), whichever is walkable and not a trainer/NPC tile.
   - A Search state machine: next_can() returns the can to try; record(result) where result is one of "first", "second", "reset", "nothing".
     Order: with no first lock, try cans in a fixed spiral/row order skipping already-tried ones; after a first-lock hit try only its UNTRIED
     orthogonal neighbours; on reset clear tried-sets and start over (keep a reset count). Caps: MAX_PER_ATTEMPT (15 cans) and MAX_TOTAL (60 cans
     per run), after which it reports "gave up".
   - Oracle: given the two RAM values (first, second) the plan is [first, second]; if a value is 0 or not a real can, fall back to SEARCH.
   - IMPORTANT: Search.next_can() takes NO RAM argument. The referee values go only to log lines and to a score dict (cans tried, resets, hits).
2. src/pokeagent/explorer/behaviours/gym_puzzle.py: applies only when ctx.view.m == 0x5C, goal beat_surge pending (ctx.goals()), barrier still closed, not in battle, no
   dialog box, ctx.proc is None, and the readiness/hold check already used by goal_talk (_hold_clear) is NOT consulted here: the puzzle may run
   while the team trains elsewhere only if the agent is in the gym already; keep it simple and do not add any new hold. Steps: ask the injected
   ctx.route_plan for a path to the stand tile (the fan_club _ask pattern with learned walls and temp blocks); walk; face the can (a turn
   press); press A once; read the screen text for the result (one A press per can, then let advance_dialog finish the text; do not press
   through text yourself); feed record(). Caps modelled on field_cut: PRESS_CAP per can, MAX_TRIES per can, COOLDOWN after a give-up, plus the
   Search caps. When the text says the second lock opened (or the barrier cells read open), set state "open" and stop applying.
3. Mode flag: values "search" (default) and "oracle". Plumb it from env POKEAGENT_GYM_PUZZLE_MODE, then the CLI flag --gym-puzzle-mode on both
   tools (CLI wins over env), into ExplorerOptions. Reject other values with a clear error.
4. Logging: every A press at a can writes one run-log line through ctx.log (res channel) with: mode, can id, can cell, referee D743 and D744
   (and CD5B) read AFTER the press, and the result. One summary line when the puzzle ends (opened, gave up) with the score dict.
5. goal_talk: add "beat_surge": (0x5C, 5, 2, "UP", "Lt. Surge") to GOAL_TALKS and "beat_surge" to APPROACH. Surge is at (5,1) so the stand tile is
   (5,2) facing UP. Add a REQUIRES-style guard so it does not walk to Surge while the barrier is closed: use the gym_puzzle state (open flag)
   from a tiny helper in explorer/gym_puzzle.py, not a new hold. _hold_clear stays unchanged and still gates APPROACH goals.
6. Registration: GymPuzzle before GoalTalk in default_behaviours (so the puzzle runs before the walk to Surge).

## Synthetic tests (tests/test_gym_puzzle.py; fake RAM and fake screen, no ROM, no emulator binary)

- neighbour rule: orthogonal only, no diagonals, edge cans have fewer neighbours, using the fixture table above.
- search finds both locks: a fake game (first lock random seed, second = a neighbour) is solved within the caps for many seeds.
- reset restarts: a wrong can after the first lock clears the tried-sets and the reset counter increments.
- oracle goes straight: with D743 and D744 set it plans exactly two cans; with a zero value it falls back to search.
- referee values never change search choices: run Search twice with the same fake game but different RAM values fed to the logger only; the
  can sequence is identical.
- behaviour fires only on map 0x5C, only with beat_surge pending, the barrier closed, and no battle or dialog box; silent elsewhere.
- caps: per-attempt, total and press caps end the behaviour and it stops applying; "gym_puzzle" is in NEVER_VETO.
- layering: the existing explorer layering test stays green (no atlas import, modules under 300 lines).

## What NOT to do

- No ROM offsets, bytes or opcodes in code, docs or tests (RAM symbol addresses already in ram_map.json are fine to reference by name or address).
- No SRAM writes, no RAM writes of any kind to solve the puzzle (read-only; the oracle only READS the two lock values).
- No explorer -> atlas imports (planners are injected through ctx, as ctx.route_plan is).
- No changes to training, readiness, team_floor, exit_rule or the gym hold logic. No GUI. No new web views.
- Do not touch other behaviours' logic beyond the one-line registrations and the goal_talk rows named above.

## Verification (run exactly these, from the worktree root)

uv run pytest -q -p no:cacheprovider -rfEs tests/test_gym_puzzle.py tests/test_explorer_behaviours.py tests/test_loop_memory.py tests/test_walkgrid.py tests/test_campaign.py tests/test_team_floor.py
uv run pytest -q -p no:cacheprovider -rfEs

The full serial suite must end with 0 failed. Paste the real output tails. No --help commands, no other test runners.

## Rules for this run

- NON-INTERACTIVE. No installs, no fetches, no network. Never read outside the worktree.
- No scratch files except under .devin-scratch/ (delete it before the final commit).
- Do not hunt for missing files: if something named here does not exist, stop and write why in the Status row.
- Work on branch directive/pokeagent-surge-gym-puzzle; commit and push that branch only. Never commit to main, never push main, never merge.
- Each new module small and single-purpose (SOLID/SRP/KISS); split before 300 lines.

## Forbidden Actions

Running the ROM or any emulator, editing or creating save states, SRAM or RAM writes, force-push, history rewrite, deleting branches, merging,
touching main, editing live config, changing repo visibility, publishing anything, or editing other repos.

## Required from User

The controller (not Devin) runs the real-ROM check from the gym save in BOTH modes (search and oracle) and the A/B comparison, and checks the
UNVERIFIED items (lock text strings, barrier-open detection, lock-bit names, the neighbour and reset rules). Devin: list in your report every
UNVERIFIED assumption you coded against so the controller can confirm each one.

## Completion criteria

- All files in Scope done; the focused tests and the full serial suite pass with 0 failed; layering test green.
- Default mode is search; oracle selectable by env and CLI; search never reads RAM to choose a can (covered by a test).
- beat_surge row present in GOAL_TALKS and APPROACH; goal_talk logic otherwise unchanged; NEVER_VETO updated.
- Branch pushed; working tree clean; .devin-scratch removed.

## Report

Findings first (what you built, which design choices, every UNVERIFIED assumption), then evidence (the real test output tails for both
commands), then a recommended next action (the real-ROM checks above). Keep it short and list the head sha of the pushed branch.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-pokeagent-surge-gym-puzzle-directive |
| Base branch | - |
| Base commit | d60b76a694a293bc0f3d15ee940847515d7237a4 |
| Head commit | 4ef866819535f97acb349ac7496047a7ae3e6bf9 |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-16 08:17 · robert-claude-laptop · none → Queued
- 2026-11-16 08:17 · robert-claude-laptop · Queued → Approved
- 2026-11-16 08:17 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-pokeagent-surge-gym-puzzle-directive; lane=default; model=swe-2-high; perm=accept-edits; persona=steady-builder; agent_id=01M7J83N4GSPH942S2D7H82K78
- 2026-11-17 19:58 · dispatcher · In progress → Approved — dispatch rolled back: stale dispatch marker (stage provision)
- 2026-11-17 20:07 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-pokeagent-surge-gym-puzzle-directive; lane=default; model=swe-2-high; perm=accept-edits; persona=steady-builder; agent_id=01M7P33MS1M9FZM82QH19WNS93
- 2026-11-17 20:22 · dispatcher · In progress → Approved — dispatch rolled back: stale dispatch marker (stage provision)
- 2026-11-17 20:22 · dispatcher · launched pid=7444; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-pokeagent-surge-gym-puzzle-directive; resynced: merged main into directive/pokeagent-pokeagent-surge-gym-puzzle-directive (1 commit(s), clean); provisioned: uv sync --group vision; uv run --no-project python -c "import shutil, pathlib; shutil.copytree(r'C:\Github\PokeAgent\roms', 'roms', dirs_exist_ok=True); shutil.copytree(r'C:\Github\PokeAgent\kb', 'kb', dirs_exist_ok=True); shutil.copytree(r'C:\Github\PokeAgent\baselines', 'baselines', dirs_exist_ok=True); shutil.copytree(r'C:\Github\PokeAgent\runs\checkpoints', 'runs/checkpoints', dirs_exist_ok=True); pathlib.Path('roms/verify.env').write_text('POKEAGENT_ROM=\"roms/Pokemon Red.gb\"\n')"; permission-mode=accept-edits (no `## Sandbox needs` — default deny)
- 2026-11-17 20:53 · devin · Approved → Blocked — Work COMPLETE and pushed (branch head eae401e; full serial suite 3436 passed/1 skipped). Only the status flip failed: queue still says Approved (dispatch was never recorded as In progress) and refuses Approved->Review and Approved->In progress for actor devin.
- 2026-11-17 20:57 · robert-claude-laptop · Blocked → Review — Devin finished: head eae401e8, full serial suite 3436 passed/1 skipped, 107 focused. Blocked only because the status flip was refused (row never recorded In progress). Needs review + verify + real-ROM gym check (search and oracle modes) before merge. [origin] spent: devin 31 min est. n/a
- 2026-11-17 21:09 · robert-claude-laptop · Review → Blocked — SENT BACK (controller real-ROM check, head eae401e8, vermilion_gym_entry.state, seed 1, --fast-text, 8000 steps, both modes): 0 hits, gave up after 15 cans, beat_surge not reached. (1) Oracle is not an oracle: logged 'lock indices [14, 0]' then walked cans 0..14 in order; must go straight to D743's can, then D744's. (2) Every press logged 'nothing' although CD5B (wGymTrashCanIndex) equals the pressed can each time, so the press registered; the can text is missed - suspect --fast-text dismissing the box before the read; classify from any text box in the press window plus D743/D744 changes; test with and without --fast-text. (3) Search pressed the right can (14 = D743) and logged 'nothing' (D744 5->0 after): count a hit on D743/D744 change or lock text. (4) D743 re-randomized while walking (14->2->0->14) after 'miss' retries: log it, do not assume the first lock is fixed; replace one-pass 'gave up' with a capped loop. Gate before Review: controller re-runs both modes on the real ROM; oracle must open both locks. Logs: controller scratchpad surge/search.json, oracle.json.
- 2026-11-17 21:09 · robert-claude-laptop · Blocked → Queued — Requeue for the fix round described in the previous Blocked note (oracle routing, outcome detection under --fast-text, hit on D743/D744 change, capped retry loop). Same branch.
- 2026-11-17 21:10 · robert-claude-laptop · Queued → Approved
- 2026-11-17 21:10 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-pokeagent-surge-gym-puzzle-directive; lane=default; model=swe-2-high; perm=accept-edits; persona=steady-builder; agent_id=01M7P6PTCABPXXNG5PNK9208ZX
- 2026-11-17 21:18 · dispatcher · launched pid=13532; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-pokeagent-surge-gym-puzzle-directive; resynced: merged main into directive/pokeagent-pokeagent-surge-gym-puzzle-directive (7 commit(s), clean); provisioned: uv sync --group vision; uv run --no-project python -c "import shutil, pathlib; shutil.copytree(r'C:\Github\PokeAgent\roms', 'roms', dirs_exist_ok=True); shutil.copytree(r'C:\Github\PokeAgent\kb', 'kb', dirs_exist_ok=True); shutil.copytree(r'C:\Github\PokeAgent\baselines', 'baselines', dirs_exist_ok=True); shutil.copytree(r'C:\Github\PokeAgent\runs\checkpoints', 'runs/checkpoints', dirs_exist_ok=True); pathlib.Path('roms/verify.env').write_text('POKEAGENT_ROM=\"roms/Pokemon Red.gb\"\n')"; permission-mode=accept-edits (no `## Sandbox needs` — default deny)
- 2026-11-17 21:35 · devin · In progress → Review — Fix round done, head 68adc6bcfd715e9c0d6eef7f195f5b0a6b8ba33e. (1) Oracle is now a real oracle: it reads D743/D744 live every step via set_locks - D743's can while unarmed, then the armed D744's can; a 0/non-can value falls back per-pick, and a moved first index re-picks the walk. (2)+(3) Verdict is two-source: fresh ctx.dialog pages + moved last_text in the press window (explicit lock lines win), else the referee diff of (D743,D744) around the press - unarmed+pair-moved->first (D744 armed) or reset, armed+armed-can->second, armed+other+moved->reset, unmoved->nothing. Presses that flashed the box under --fast-text now score instead of logging 'nothing'. (4) Search runs a capped loop: passes over the can order, attempts<=4, total<=60, resets still clear tried-sets; every D743/D744 move is logged. UNVERIFIED coded against: lock text strings; D744=0 reads 'unarmed' (a can-0 second lock is a blind spot - RAM-only verdict cannot see it); reset re-randomizes D743 and clears D744; pressing the armed D744 can opens lock 2; barrier tile-id change still a logged-only signal. Tests: focused 114 passed; full serial suite '3447 passed, 1 skipped, 2 warnings in 328.88s' (0 failed; skip = no-ROM gate). Next: controller re-runs vermilion_gym_entry.state in BOTH modes with and without --fast-text; oracle must open both locks. [origin] spent: devin 47 min est. n/a
- 2026-11-17 21:46 · robert-claude-laptop · Review → Blocked — Round-2 real-ROM check (head 68adc6bc, vermilion_gym_entry.state, seed 1, 8000 steps, fast and slow text): ORACLE PASSES - both locks, beat_surge settled at step 637 (Raichu L24 beaten), identical with/without --fast-text. SEARCH opens both locks at step 1713 (17 tries, 3 resets, 2 hits, text verdicts correct) but never reaches Surge: beat_surge routes to 'nearest known tile to Lt. Surge' (5,5) and oscillates (5,5)<->(5,6)/(4,5) to step 8000 because UP from (5,5) is a wall LEARNED while the barrier was closed. One fix: on 'opened' (and on any reset), forget learned walls/blocked edges on the barrier cells x4-5,y4-5 and their entry edges, and let beat_surge re-plan via the ROM route plan (GYM is in ROUTE_MAPS now). Add a synthetic test: walls learned on barrier cells are cleared by the opened event and the goal path then passes the barrier. Gate: controller re-runs search on the real ROM; it must settle beat_surge.
- 2026-11-17 21:46 · robert-claude-laptop · Blocked → Queued — Requeue round 3: forget barrier walls on opened/reset so search reaches Surge (see previous note). Same branch.
- 2026-11-17 21:46 · robert-claude-laptop · Queued → Approved
- 2026-11-17 21:47 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-pokeagent-surge-gym-puzzle-directive; lane=default; model=swe-2-high; perm=accept-edits; persona=steady-builder; agent_id=01M7P8STW2C79JTVG1VM15CA3N
- 2026-11-17 21:55 · dispatcher · launched pid=9896; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-pokeagent-surge-gym-puzzle-directive; resynced: merged main into directive/pokeagent-pokeagent-surge-gym-puzzle-directive (8 commit(s), clean); provisioned: uv sync --group vision; uv run --no-project python -c "import shutil, pathlib; shutil.copytree(r'C:\Github\PokeAgent\roms', 'roms', dirs_exist_ok=True); shutil.copytree(r'C:\Github\PokeAgent\kb', 'kb', dirs_exist_ok=True); shutil.copytree(r'C:\Github\PokeAgent\baselines', 'baselines', dirs_exist_ok=True); shutil.copytree(r'C:\Github\PokeAgent\runs\checkpoints', 'runs/checkpoints', dirs_exist_ok=True); pathlib.Path('roms/verify.env').write_text('POKEAGENT_ROM=\"roms/Pokemon Red.gb\"\n')"; permission-mode=accept-edits (no `## Sandbox needs` — default deny)
- 2026-11-17 22:05 · devin · In progress → Review — Round 3 done, head 4ef86681. Fix: a lock verdict (first/reset/second) now forgets learned walls touching the barrier cells (x4-5,y4-5) - new memory_purge.purge_walls_touching(data, map_id, cells) drops 'blocked' edges AND their fail counters where either endpoint is a barrier cell, called from GymPuzzle._judge on any result != 'nothing', logged with the dropped keys. This targets the bounce: UP out of (5,5), learned bumping the CLOSED gate, left beat_surge oscillating under an open gate since _approach rules out blocked directions and nothing re-presses them. Forget also runs on 'reset' (the barrier's state moved either way) and on 'first' (the first gate opens too). No goal_talk change needed: the APPROACH mechanic walks unmapped stand tiles and, with the wall gone, presses through and visits (5,4)->(5,2); forget also lets the ROM route plan re-plan (GYM already in ROUTE_MAPS). Tests: 3 new - unit (edges on/into cells drop, others + order kept, fails cleared), opened-forgets-walls-then-strict-WorldGraph-path-(5,5)->(5,2)=UPx3, reset-forgets-walls. Evidence: focused '117 passed'; full serial '3450 passed, 1 skipped, 2 warnings in 313.06s' (0 failed; skip = no-ROM gate). UNVERIFIED carried over from round 2 (lock strings, referee model, D744=0 blind spot, reset semantics). Next: controller re-runs vermilion_gym_entry.state SEARCH on the real ROM; it must settle beat_surge. [origin] spent: devin 57 min est. n/a
- 2026-11-17 22:21 · robert-claude-laptop · Review → Blocked — Round-3 real-ROM check (head 4ef86681, gym entry, seed 1, --fast-text): ORACLE still passes (beat_surge at step 637). Wall-forget works (log: 'forgot learned walls [5,5,UP ...]'). SEARCH fails on the CAPS, not logic: this seed's locks differed from round 2; verdicts were right (first at can 2 by text, reset on wrong neighbour can 1 by text) but MAX_TOTAL=60 / MAX_ATTEMPTS=4 ran out after ~40 presses and 4 resets, then it patrolled to 8000. Round 2 only passed by luck of the draw. Fix round 4: (1) raise caps so success is near-certain: MAX_TOTAL ~250, attempts bounded only by MAX_TOTAL; (2) after a 'first' hit, try that can's orthogonal neighbours (only ones that are cans) in a fixed order and remember which neighbours were wrong for THAT first-lock position (after a reset the first lock re-randomizes, so clear that memory then); (3) do not re-press a can already answered 'nothing' since the last reset. Synthetic test: a simulated game with random locks per seed (100 seeds) solves within MAX_TOTAL in >= 99%. Gate: controller real-ROM search runs on seeds 1, 2 and 3 must all settle beat_surge.
- 2026-11-17 22:21 · robert-claude-laptop · Blocked → Queued — Requeue round 4: search caps + neighbour memory (see previous note). Same branch.
- 2026-11-17 22:22 · robert-claude-laptop · Queued → Approved
- 2026-11-17 22:22 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-pokeagent-surge-gym-puzzle-directive; lane=default; model=swe-2-high; perm=accept-edits; persona=steady-builder; agent_id=01M7PATF6M27WEXS9226R8FTXA
<!-- queue:end -->
