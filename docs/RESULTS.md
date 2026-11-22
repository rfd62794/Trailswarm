# Results

These are the measured results so far. Numbers come from the project's own run logs; nothing here is a benchmark against other agents.

## Overnight continuous swarm (2026-11-05 to 06)

The continuous swarm (`tools/swarm.py --continuous --plan curriculum`) ran 8 agents and finished 500 runs. Along the way it:

- reached Cerulean City,
- beat Misty,
- crossed Nugget Bridge (Route 24),
- mapped battles on the way.

Update (2026-11-08): the `to_bill` segment has been solved. Best run `explore-20261107-082910-320` reached Bill's house (map `0x58`) in 2,177 steps on 2026-11-07, at about a 10% success rate over recent attempts. This confirms the segment, not the full curriculum chain.

## Goal chain past Bill (as of 2026-11-15)

The checkpoints on disk now reach well past Bill's house. The `hm01_cut` checkpoint's goals sidecar
(`runs/checkpoints/hm01_cut.state.goals.json`) lists 33 completed goals: everything through `ss_ticket` (S.S. Ticket),
`to_route5`, `to_route6`, `to_vermilion`, `to_ss_anne`, `ss_anne_2f`, `rival_ss_anne`, `ss_anne_captain` and `hm01_cut`.
Bill's house itself is a three-stage goal (`src/pokeagent/explorer/behaviours/goal_talk_bill.py`): monster, console,
human; the stage is read from the RAM sprite table, never from vision (see docs/KNOWLEDGE.md's Bill section, ROM probe
2026-11-15).

## Training controller (slices merged 2026-11-14)

Design: `docs/plans/training-controller-2026-11-13.md`. Slice results measured on the real ROM, seeds 12/13/14,
12,000 steps from `heal_cerulean` (numbers in the plan doc and in the slice directives' Done notes):

- Slice 2 (Target, PR #250): phantom grind-episode starts on never-visited maps went 12 / 11 / 11 -> 0 / 0 / 0;
  leave-Pokecenter share and SHAKE share both fell; total xp was flat-to-up (per-battle xp 111->123, 88->88, 106->120).
  Source: `docs/directives/Training_Controller_Slice2_Target_Directive.md`, plan doc "Slice 2 result".
- Slice 3 (Sustain, PR #259): behaviour-preserving - `decisions.jsonl` byte-identical to main on seeds 12 and 13.
  Source: `docs/directives/Training_Controller_Slice3_Sustain_Directive.md`, plan doc "Slice 3 result".
- Slices 4 (Roster) and 5 (Exit + gym hold) also merged; their changes are owner-moves covered by the unit gates,
  no new run numbers yet.

## Go-Explore (slices merged 2026-11-14)

Design: `docs/plans/go-explore-2026-11-14.md`.

- Slice 1 census (`tools/cell_census.py` over finished run logs, PR #252): 39 / 38 / 42 distinct cells at 4x4-tile
  blocks on the seed 12/13/14 race logs, all at one goal stage (position-only variation so far). Source:
  `docs/directives/GoExplore_Slice1_Cell_Census_Directive.md`.
- Slice 4 (PR #273): a real-ROM smoke of 2 returns x 50 steps exited cleanly and archived 5 organic cells; with the
  cell flags off, `decisions.jsonl` stays byte-identical to main. Source:
  `docs/directives/GoExplore_Slice4_Return_And_Explore_Directive.md`.

## Rewinder (merged 2026-11-15, PR #301)

`pokeagent rewind` plays a finished run back as frames, activity segments and moments - pure playback over the run's
own logs, no ROM and no window. The full suite at merge: 3,206 passed, 1 skipped. Source:
`docs/directives/Rewinder_Slice1_Playback_Core_Directive.md`.

## Battle-text wait (merged, PR #90)

Fresh game, 3,000-step budget, 3 seeds, before versus after the battle-text-wait change. Values are steps to reach the goal, listed per seed.

| goal | before | after |
|---|---|---|
| `to_pewter` | not reached / 2953 / 2630 | 2006 / 1917 / 1847 |

With the change, `beat_brock` was reached on 2 of 3 seeds.

## Fewer wasted presses

An earlier fix cut no-op A presses per run from about 198 to 16-31.

## Mt Moon

Mt Moon was traversed on 3 of 3 seeds on an earlier harness, after the agent gained ROM-derived collision data and multi-floor planning.
