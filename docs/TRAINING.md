# Training: who trains, where, and when to heal

Several systems decide how the agent levels its party. The newer ones live in
`src/pokeagent/explorer/training_ctl/` (one owner per decision) and `src/pokeagent/grind/` (the ledgers
they consult). Design history: `docs/plans/training-controller-2026-11-13.md`.

## The training controller

One facade, one owner per question; the pieces are frozen dataclasses and pure queries:

- `state.py` / `adapters.py` - `TrainingState` and the thin ctx readers that fill it.
- `target.py` - the ONE training point for a session. A point must be real: its map has been visited and
  a learned route reaches it. An empty ledger, or one with nothing reachable, chooses none - it never
  invents a spot (the phantom-Viridian-Forest bug this fixed: 11 of 13 episode starts had pinned maps the
  agent never stood on).
- `roster.py` - the ONE owner of "which party slot is the switch-trainee" (`trainee_slot`), behind which
  the six old call sites sit with identical arguments. Team identity uses a monotonic faint counter, so a
  heal can never re-trigger a reorder.
- `sustain.py` - the heal rule's one owner: `heal_now()` packages the grinding / needs-heal / potion
  verdicts, and `publish(ctx, value)` is the single writer of `train_route_live`.
- `exit_rule.py` - the gym-hold flags' one writer/reader pair (`gym_hold_seen`, `floor_unmet`), at the
  exact points the old code used.
- `controller.py` - a shadow observer: `observe()` re-derives the training values and compares them with
  the live flags, logging mismatches; it never writes ctx.

## Where to grind

- `grind/points.py` - the shared ledger of known-good grind spots, one `GrindPoint` per map: measured
  xp/min versus the ROM-derived prior, blackout rate, provenance, and the level band the point is good
  for. `choose()` picks the best point for the trainee's level. Ledger file: `runs/grind_points.json`;
  the swarm-shared copy merges by episode id so organic data is never overwritten by a synthetic run.
- Level bands - `grind/xp_buckets.py` buckets each measured episode by the trainee's 5-level bucket
  (L5-9, L10-14, ...): a solo L6's rate is not a switch-trained L12's. `choose()` prefers the trainee's
  own bucket once it holds enough measured episodes.
- The XP-spots ledger - `explorer/xp_spots.py` records rolling XP rates per (map, 5-level band) cell into
  `runs/xp_spots.json`, shared across runs and merged cell-by-cell under a lock. Measurement only: it
  picks no spot.
- Solo viability - `grind/solo_viable.py` asks whether the trainee can win a map's wild fights alone
  (>= 0.75 chance-weighted win share with >= 0.10 mean HP left, entering battle above 60% HP) and what
  the nurse round trip costs. A solo-viable point within 320 steps outranks every other point - solo XP
  is full XP, the switch trick pays half at best. Missing data (an empty encounter mix, an unknown
  species, a partial slot table) is never viable.

## Opt-in learners

Both are off by default; the flags turn them on per run (see docs/CLI.md).

### Behaviour bandit (`--bandit`, `src/pokeagent/bandit/`)

At flagged decision points - fight/flee, heal/push on, grind/skip - Thompson sampling over a shared table
picks the arm instead of the explorer's default. The shared table is `runs/bandit.json`; each run writes
its own `bandit_delta.json` (merged into the table, so a kill loses only open episodes). On the swarm,
`--bandit` + `--bandit-share F` runs it in a share of the slots; the rest are the control group.

### Novelty (`--novelty`, `src/pokeagent/novelty/`)

Each step the tracker reads the game state and counts features (tiles, maps, event flags, items, species,
moves) against the swarm-wide table `runs/novelty.json`; rarity is `1/sqrt(1 + runs that found it)`.
First-time features log to `runs/discoveries.jsonl` and the run writes a `novelty_delta.json`. Only
explorer-role slots are steered and paid the bonus; other roles still count and discover.

## Build selection and the save library

`pokeagent states library build` scans `runs/checkpoints/` and `runs/legs/states/` and writes
`runs/states/library.json`: every checkpoint and leg state indexed by team build, verdict (the party
rules), and metrics (steps, faints, a readiness score against the next boss). Retention keeps the best 3
leg states per (segment, build) - it is a ranking only; nothing is deleted. `library list` prints the
entries; `library validate` re-runs the party rules and prints RETIRABLE lines with the nearest clean
ancestor.

Because a segment can start from more than one saved state, `statelib/start_pick.py` picks WHICH
(state, build) a curriculum job starts from: `exploit` 60% / `alternative` 25% / `promising` 15%
(untuned; overridable in `runs/curriculum_builds.json`). Details in docs/SEGMENTS.md, "Build selection".

The rest of the ledger commands - `pokeagent states {list,check,promote,restamp,retire}` - are in
docs/CLI.md.
