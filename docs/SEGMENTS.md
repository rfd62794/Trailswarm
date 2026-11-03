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

Grading a segment variant: fewer presses wins when the end condition is met; a variant that loses HP it did
not need to lose, or that triggered a stall, ranks below one that did not (review_runs.py reports waste per
run; the battle log reports HP per turn). Human and Claude presses inside a segment are kept as demonstrations
but graded by the same rule, so a human shortcut only survives if it keeps winning.
