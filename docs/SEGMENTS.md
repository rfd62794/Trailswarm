# Segments (beats) of the opening, named

A segment runs from one goal boundary to the next. Each has a start state (a save state the demo writes to
`runs/checkpoints/<goal>.state` the first time that goal is reached in a run), an end condition (the next
goal's detector in goals.json), a record (fewest presses, from runs/best_paths.json) and the beats inside it
(text-triggered press sequences in runs/maps.json `beats`). The swarm re-runs one segment at a time with
`tools/swarm.py --segment <goal>` (agents start from the previous checkpoint and stop when the goal lands), so
many variants of the same segment are tried and graded without replaying the whole opening.

| # | segment | start | ends when | record (presses) | beats inside | notes |
|---|---|---|---|---|---|---|
| S1 | Bedroom to PC: withdraw the POTION | baseline (bedroom, (4,6)) | bag has POTION | 14 | "BCN turned on the PC." (9) | path UUUULLLLU then A, WITHDRAW ITEM, POTION, How many? A, CANCEL, LOG OFF |
| S2 | House to Pallet Town | potion checkpoint | map not 0x25/0x26 | 24 | none | stairs (7,2) UP, door (3,7) DOWN; back out of the PC first |
| S3 | Pallet Town to the starter | left_house checkpoint | party count > 0 | 74 | Oak's speech (one-time), ball offer, nickname NO | trigger at the north gap (11,1); balls (6,3)/(7,3)/(8,3) faced from y=4 |
| S4 | Rival battle in the lab | first_pokemon checkpoint | battle ended on the same tile | 89 | rival challenge text; FIGHT -> move 1 x ~7 | walk toward the lab door to trigger it; 14 turns; HP 10/16 -> 4/8 typical |
| S5 | Lab to Route 1 | won_battle checkpoint | map 0x0C seen | 92 (one run) | rival leaves text | north gap again; first wild battles; flee below 40% HP |
| S6 | Route 1 to Viridian City | to_route1 checkpoint | map 0x01 seen | - | - | not yet reached by any agent |
| S7 | Viridian Mart: Oak's Parcel | to_viridian checkpoint | bag has 0x46 | - | - | goals.json goal 6 |
| S8 | Back to Oak: Pokedex | oaks_parcel checkpoint | START menu shows POKeDEX | - | - | goals.json goal 7 |
| S9 | Pewter to Route 3 | beat_brock checkpoint | map 0x0E seen | - | - | push east out of Pewter (connection E) |
| S10 | Route 3 to Route 4 | to_route3 checkpoint | map 0x0F seen | - | - | push north along Route 3 (connection N); ledge tiles and trainers on the way |
| S11 | Route 4 west to Mt Moon 1F | to_route4 checkpoint | map 0x3B seen | - | - | entrance warp (18,5); the Pokecenter 0x44 door (11,5) is on the way and heals |
| S12 | Mt Moon 1F to B1F | to_mt_moon checkpoint | map 0x3C seen | - | - | a ladder maze: exploration + learned warps, never scripted |
| S13 | Mt Moon B1F to B2F | mt_moon_b1f checkpoint | map 0x3D seen | - | - | B1F warp (17,11) leads down; the fossil room is optional |
| S14 | B2F back up and out | mt_moon_b2f checkpoint | on Route 4 (0x0F) at x >= 24 after B2F | - | - | the exit warp lands at (24,5), east of the cave; leaving by the west entrance (18,5) does not count |
| S15 | Route 4 east to Cerulean | through_mt_moon checkpoint | map 0x03 seen | - | - | push east on Route 4 (connection E) |
| S16 | Cerulean Pokecenter | to_cerulean checkpoint | map 0x40 seen | - | - | door at Cerulean (19,17); walk in (heals when weak) |
| S17 | Cerulean Gym: Misty | heal_cerulean checkpoint | wObtainedBadges bit1 (0xD356 & 2) | - | - | gym door (30,19) -> map 0x41; train on Route 24 first when the lead is under the train level |
| S18 | Route 24 (Nugget Bridge) | beat_misty checkpoint | map 0x23 seen | - | - | Cerulean's north connection; bridge trainers |
| S19 | Route 25 to Bill's house | nugget_bridge checkpoint | map 0x58 seen | - | - | push east from Route 24 into Route 25 (0x24); the house is the warp at (45,3) |
| S20 | Bill: S.S. TICKET | to_bill checkpoint | bag has item 0x3F | - | - | talk to Bill through the transformation sequence |

Grading a segment variant: fewer presses wins when the end condition is met; a variant that loses HP it did
not need to lose, or that triggered a stall, ranks below one that did not (review_runs.py reports waste per
run; the battle log reports HP per turn). Human and Claude presses inside a segment are kept as demonstrations
but graded by the same rule, so a human shortcut only survives if it keeps winning.

## Curriculum (daisy chain)

`uv run python tools/swarm.py --continuous --plan curriculum --agents N` hands each free slot one segment by need
instead of one huge run: 70% unsolved segments (weakest first), 20% the frontier (the segment after the furthest
checkpoint, started from that goal's best checkpoint), 10% polish of solved segments (explorers hunting tiny gains),
plus a replay slot whenever a new best is waiting for confirmation. A segment is solved at >= 90% over its last 20
attempts. Each job starts from the PREVIOUS segment's best checkpoint (`runs/checkpoints/<goal>.best.state`, else
`<goal>.state`), stops at its own end (`--stop-at-goal`, or `--stop-at-map` for a sub-segment) and gets a step budget of
3x the best solve's presses (1,500 to 6,000; 3,000 with no solve yet).

* A faster solve is a candidate until a re-run with the same seed, starter, box pace and starting map memory (kept
  under `runs/segments/inputs/`) solves again; then it is `confirmed` and its end state becomes `<goal>.best.state`.
* A segment with < 30% solved after >= 20 attempts is split at the maps its failed attempts reached (first entry into
  each map id); the pieces (`<goal>@<map hex>`, last `<goal>@end`) have their own checkpoints and stats and chain back.
* Stats live in `runs/segments.json`. `uv run python tools/segments.py` ingests finished runs and prints segment,
  tries, rate, best, expected frames (failures cost their frames plus 3,600), confirmed, share of slots, and the
  chained personal best; `tools/status.py` shows the same table.
