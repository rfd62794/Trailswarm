# Plan: extend the existing framework to more games

Status: draft, 2026-11-08. Approved in principle by Robert; this runs before the demo video plan.
Decision: extend this repo. No new repo and no framework extraction.

Direction change, settled 2026-11-08 (owner): "we want to try to build a combined or shared memory for red and blue, we want the individuality minimal where possible, and plan for yellow after confirming cross compatibility." The model is assumed compatible ONLY with Generation 1 Pokemon, so there is one memory family, `gen1-pokemon`: Red and Blue now, Yellow only if it passes the compat check. A game declares its family in `GameSpec.memory_family`; Mario, Kirby and the other games are simply not in it and get their own namespace.

## Rule that governs every phase

Pokemon Red behaviour stays byte-identical by default. `--game` defaults to `pokemon-red`, and Red's paths
resolve to where they are today. Each phase is one directive, ends in a stop point, and must leave the Red
golden trace unchanged.

## What the code says today

- The game seam is the RAM map, not the emulator. Only `src/pokeagent/emulator.py` imports PyBoy.
- There is no game abstraction. `registry.py` is a worker-process registry and `adapters/` are viewer
  snapshot adapters, so neither can be extended into one.
- Every store is shared with no game key (the family decision keeps them shared for Red and Blue, so the fix is to key them by memory family, not by game): `runs/maps.json`, `runs/checkpoints`, `runs/bandit.json`,
  `runs/novelty.json`, `kb/*`. Map ids are bare integers, so a second game would silently merge into Red.
- `press()` holds then settles. It has no held state or chord, so it cannot play a real-time game.
- A Red save state loaded under Blue would load silently: state sidecars record no game. A save state is ROM-bound even when memory is shared, so the sidecar keeps the GAME key and a mismatched load stays refused.
- Early evidence for sharing (measured 2026-11-08, Red's `runs/maps.json` against a Blue run's `maps.json`, 15 maps up to Viridian Forest; the Blue runs so far had human interaction, so this is evidence, not a verdict): 2,170 of 2,203 Blue tiles already known to Red; 21 common warps, none different; 35 of 35 stationary NPCs in the same place; 210 of 2,127 Red walls lie between two tiles Blue stood on (126 on Route 1, which has ledges; cause UNCONFIRMED, likely one-way ledges or transient NPCs). A Blue-built kb matched Red's except wild encounters (34 of 57 maps differ) and unexplained `map_trainers` differences at unused ids 105-117 and 231. Blue's real RAM reads matched Red's map through the rival battle; badges, wild battles and later maps are UNMEASURED.
- ROM-gated tests skip silently without the ROM, and `roms/` and `baselines/` are gitignored. A Devin
  worktree has neither, so a green Devin run proves nothing about real emulation.

## ROMs on hand (2026-11-08)

| Game | System | Boots headless | PyBoy module | Notes |
|---|---|---|---|---|
| Pokemon Red | GB | yes | Pokemon Gen 1 | current game |
| Pokemon Blue | GB | yes | Pokemon Gen 1 | RAM reads matched Red's map through the rival battle (measured 2026-11-08); badges, wild battles and later maps unverified. In the `gen1-pokemon` family |
| Pokemon Yellow | GB, MBC5, CGB flag | yes | generic | separate disassembly, full RAM port, so nothing is assumed shared. Not in the family until it passes the compat check (phase 10) |
| Super Mario Land Rev 1 | GB | yes | Super Mario Land | real-time |
| Wario Land 3 | GB | yes | generic | real-time |
| Legend of Zelda Rev 1 | NES, mapper 1 | not tried | none | needs a second backend |
| Tetris Tengen | NES, mapper 3 | not tried | none | needs a second backend |

Wanted, no ROM yet: Kirby's Dream Land, Final Fantasy Adventure.

## Phases

| # | Phase | Who | Verify | Stop point |
|---|---|---|---|---|
| 0 | Merge #165, #166, #167 | Claude | gates | main carries the telemetry and plan_goal changes |
| 1 | Red golden guard: ROM-gated test around `tools/golden_trace.py`, recorded hash, no source change | Claude lane, needs ROM and baselines | test passes twice | a baseline exists to compare against |
| 2 | `game/` package: `GameSpec`, `GAMES`, `--game` and `POKEAGENT_GAME`; move `EXPECTED_SHA1` and `check-rom` behind it | Devin | `tests/test_cli.py`, golden | Red only, no behaviour change |
| 3 | ROM defaults, screen size and button set come from the spec | Devin | grep for the literal, `test_frame_slots`, `test_emulator`, golden | still Red only |
| 4 | Namespace `runs/` and `kb/` by memory family (`gen1-pokemon` stays on today's paths, so Red and Blue share the legacy root); per-game paths only for ROM-bound or measured-different stores (checkpoints, baselines, wild encounter tables); game key in state sidecars; refuse a mismatched state load. Directive: `Game_Namespaced_Stores_Directive.md` | Devin | `test_statemeta`, golden | safe for a second game to run |
| 4a | Compat check: a reusable report between any two games' map memory files and RAM address tables (tile overlap, warp agreement, stationary NPC agreement, wall conflicts, pass/fail against proposed thresholds). Directive: `Game_Compat_Check_Directive.md` | Devin | tests on synthetic files, no ROM | the gate for Yellow exists |
| 4b | Shared family memory: provenance per fact, per-game overlay for disagreements, overlay-first reads, per-game kb overlay (wild encounters). Directive: `Family_Shared_Memory_Directive.md`. Needs 4 and 4a merged | Devin | synthetic tests, golden unchanged | Red and Blue learn into one store |
| 4c | Clean no-touch Blue baseline: a Blue run with no human interaction on a settled engine, recorded as Blue's baseline. The runs so far had human interaction and do NOT count | Claude lane, needs ROM | run log shows no input source other than the agent; compat check run on its `maps.json` | a baseline that can be trusted for Blue; scheduled after phases 4 and 4b |
| 5 | Real-time input beside `press()`: held buttons and chords; `press()` untouched | Devin | `test_emulator`, golden | emulator can play a platformer |
| 6 | Generic explore lane: needs no game knowledge | Devin, then Claude runs it | every GB ROM produces a dossier | Robert sees all five games run |
| 7 | Blue, full support, after 4 to 4c: register Blue in the `gen1-pokemon` family (its spec declares `memory_family`), hash and `check-rom --game pokemon-blue`; rebuild its kb and keep only the differing entries as its overlay (wild encounters; investigate the `map_trainers` ids); extend the RAM check from "matches through the rival battle" to badges, wild battles and later maps; confirm a Red state is refused under Blue and the reverse (needs both ROMs) | Claude lane, needs ROM | `check-rom --game pokemon-blue`, ladder start, compat check on the clean 4c run | first real second game sharing Red's memory |
| 8 | Super Mario Land, then Wario Land: goals and behaviours for real-time play | Devin plus Claude runs | furthest level in a fixed budget | one platformer learns |
| 9 | NES backend spike behind `Emulator`, then Zelda and Tetris | Claude spike first | boots, RAM read, save state | decide whether NES is worth it |
| 10 | Yellow (gated, see below), then Kirby and Final Fantasy Adventure | later | per game | each is its own go |

## Yellow: gated on the compat check

Yellow is a separate disassembly with a full RAM port (see the ROM table), so nothing about Red or Blue carries over by assumption. Yellow enters the `gen1-pokemon` family only if ALL of these hold, and each is a check, not an opinion:

1. Phases 4, 4a, 4b and 7 are merged and Blue's memory is running in the family.
2. A clean Yellow run exists (no human interaction, settled engine) and a ROM-present `check-rom --game pokemon-yellow` passes against Yellow's own address table.
3. `tools/game_compat.py`, run between the family memory and Yellow's `maps.json` with both address tables, returns `pass` and not `insufficient` against the thresholds in `Game_Compat_Check_Directive.md` (PROPOSALS until the owner confirms them).
4. Every address the report lists as different is mapped in Yellow's spec, and every fact Yellow disagrees on goes to Yellow's overlay (`Family_Shared_Memory_Directive.md`).

Anything Yellow differs on goes to its overlay, or Yellow stays out of the family and gets its own namespace like a non-Pokemon game. The owner decides the go after reading the report; failing the check is a normal outcome, not an error.

## The game-agnostic view

The viewer learns no game terms. It has three parts:

1. **Map source, one per game.** It supplies an image per area. Mario builds levels from captured play, Pokemon keeps
   its Kanto map, and a flip-screen game supplies rooms. A scrolling game needs a camera position to take part.
2. **Position contract, shared.** Every agent reports area, x and y, plus a run id and an outcome. The ghost format
   in `tools/mario_maps.py` is the first version.
3. **Viewer.** Two tabs: Gameplay (`tools/watch_game.py`, one large screen) and Map (stitched areas, ghosts, trails, death
   marks, follow the best).

Numerous agents are shown as ghosts. Each attempt is an input sequence, so its positions are recorded once and
replayed together at normal speed. Display cost stays flat however many are shown.

| # | Step | Who | Status |
|---|---|---|---|
| V1 | Search stops retrying save points that keep dying | Claude, needs ROM | built in `tools/watch_mario_land.py` |
| V2 | Per-level map building and ghost tracks | Claude, needs ROM | built in `tools/mario_maps.py` |
| V3 | Position contract on `GameSpec`, Map tab in the viewer | Devin, after phases 2 to 4 | not started |
| V4 | Scored moments: per-attempt score events ranked into a replayable highlights list, kept for the video plan | Claude, needs ROM | built in `tools/mario_moments.py` |
| V5 | Pokemon moves onto the same contract last | Devin | not started |

Check first: `world/model.py` looks event-driven and may be reusable, but `world/` was surveyed as Kanto-specific.

## Phase 6 in more detail

This is the phase that makes the rest worth doing. It is the difference between "the code accepts a game" and
"the framework explores it". The lane runs from a `GameSpec` with no goal ladder:

- Advance through the title screen using a generic rule (press START or A until the screen changes).
- Pick inputs by novelty over a coarse hash of the screen, using the existing `novelty/` and `bandit/` code.
- Log, per game, a dossier: screens reached, a RAM-change profile from `ramlab/` naming candidate addresses for
  position, lives, score and scene, and how often each screen hash recurs.
- Save short frame sequences, so the video plan has real footage per game.

It stays simple on purpose. It will not beat these games. It answers which ones reward deeper work.

## Decisions Robert should see before phase 9

- `cynes`, the likeliest NES library, is GPL-3.0 and this repo is MIT and public. A new dependency with that
  licence needs his call, or the backend stays an optional extra outside the core install.
- Footage rules live in `docs/LEGAL.md` and apply before anything is published.

## Out of scope

Refactoring the ~28 Pokemon-only behaviours. Renaming the package. Porting the goal ladder to platformers.
Perf_Baseline, Spawn_Lock_Followups, Agent_Footprint and Event_Stream, which wait until phase 4 lands.

## Unverified going in

Yellow's claims come from memory of the pret disassemblies; the compat check measures them. For Blue, only the 2026-11-08 comparison above is measured, and it came from runs with human interaction: the clean baseline (phase 4c) and phase 7 extend it. The cause of the wall conflicts (ledges versus transient NPCs) and whether wild battles and badges match are unverified. The compat thresholds are proposals.

## Later question, not scheduled

Whether anything carries over to Crystal as a broader Pokemon family memory, to be judged with the compat check once a Crystal memory file exists. Nothing is designed or reserved for it now.
