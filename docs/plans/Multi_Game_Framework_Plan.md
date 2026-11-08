# Plan: extend the existing framework to more games

Status: draft, 2026-11-08. Approved in principle by Robert; this runs before the demo video plan.
Decision: extend this repo. No new repo and no framework extraction.

## Rule that governs every phase

Pokemon Red behaviour stays byte-identical by default. `--game` defaults to `pokemon-red`, and Red's paths
resolve to where they are today. Each phase is one directive, ends in a stop point, and must leave the Red
golden trace unchanged.

## What the code says today

- The game seam is the RAM map, not the emulator. Only `src/pokeagent/emulator.py` imports PyBoy.
- There is no game abstraction. `registry.py` is a worker-process registry and `adapters/` are viewer
  snapshot adapters, so neither can be extended into one.
- Every store is shared with no game key: `runs/maps.json`, `runs/checkpoints`, `runs/bandit.json`,
  `runs/novelty.json`, `kb/*`. Map ids are bare integers, so a second game would silently merge into Red.
- `press()` holds then settles. It has no held state or chord, so it cannot play a real-time game.
- A Red save state loaded under Blue would load silently: state sidecars record no game.
- ROM-gated tests skip silently without the ROM, and `roms/` and `baselines/` are gitignored. A Devin
  worktree has neither, so a green Devin run proves nothing about real emulation.

## ROMs on hand (2026-11-08)

| Game | System | Boots headless | PyBoy module | Notes |
|---|---|---|---|---|
| Pokemon Red | GB | yes | Pokemon Gen 1 | current game |
| Pokemon Blue | GB | yes | Pokemon Gen 1 | believed to share Red's RAM layout, unverified |
| Pokemon Yellow | GB, MBC5, CGB flag | yes | generic | separate disassembly, full RAM port |
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
| 4 | Namespace `runs/` and `kb/` by game, with Red on today's paths; game key in state sidecars; refuse a mismatched state load | Devin | `test_statemeta`, golden | safe for a second game to run |
| 5 | Real-time input beside `press()`: held buttons and chords; `press()` untouched | Devin | `test_emulator`, golden | emulator can play a platformer |
| 6 | Generic explore lane: needs no game knowledge | Devin, then Claude runs it | every GB ROM produces a dossier | Robert sees all five games run |
| 7 | Blue: hash, `kb/` rebuild, measured RAM check against Red's map | Claude lane, needs ROM | `check-rom --game pokemon-blue`, ladder start | first real second game |
| 8 | Super Mario Land, then Wario Land: goals and behaviours for real-time play | Devin plus Claude runs | furthest level in a fixed budget | one platformer learns |
| 9 | NES backend spike behind `Emulator`, then Zelda and Tetris | Claude spike first | boots, RAM read, save state | decide whether NES is worth it |
| 10 | Yellow, Kirby, Final Fantasy Adventure | later | per game | each is its own go |

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

Blue and Yellow claims come from memory of the pret disassemblies. Phase 7 measures them.
