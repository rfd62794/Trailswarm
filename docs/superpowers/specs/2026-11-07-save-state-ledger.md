# Save-state ledger: know what a state is before a run resumes from it

Date: 2026-11-07. Status: fingerprint + leg-state stamp + curriculum refusal shipped (branch `fix/leg-state-respawn-ledger`);
ledger, selection and `pokeagent states` CLI proposed below.

## Why (evidence, 2026-11-07)

The swarm ran the captain segment from `runs/checkpoints/ss_anne_captain@63.state`. That state, and every other ship-stage
checkpoint, was a bad ancestor. RAM read from each file with one headless emulator (map 0xD35E, respawn = wLastBlackoutMap
0xD719, party from 0xD163/0xD16B):

| State | Saved | Map | Respawn | Party (species, level, HP) | Potions |
|---|---|---|---|---|---|
| checkpoints/to_vermilion.state | 11-07 08:28 | Vermilion (5) | Cerulean (3) | Magikarp L12 0/27; Wartortle L29 6/79 | 0 |
| checkpoints/to_ss_anne(.best).state | 11-07 08:27 | 1F (0x5F) | Cerulean | same, 6/79 | 0 |
| checkpoints/ss_anne_2f(.best).state | 11-07 08:27 | 2F (0x60) | Cerulean | same | 0 |
| checkpoints/ss_anne_captain@61(.best).state | 11-06 22:25 | 0x61 | Cerulean (sidecar: no respawn field) | same | 0 |
| checkpoints/ss_anne_captain@63.state | 11-06 22:26 | bow (0x63) | Cerulean (sidecar: no respawn field) | same | 0 |
| checkpoints/rival_ss_anne.state | 11-06 01:15 | 0x42 | Cerulean | Magikarp L9; L22 | 0 |
| legs/states/99_13_6.state (same tile as @63) | 11-07 | bow (0x63) | Vermilion (5) | Magikarp L12 27/27; Wartortle L29 79/79 | 0 |
| legs/states/* on Vermilion and ship maps (49 files, e.g. 97_19_3, 96_2_4, 95_27_0, 5_*) | 11-07 | various | Vermilion (5) in all 49 | 48 at full HP (27/27, 79/79); one at 51/82 | 0 |

Across all 229 states scanned: respawn 5 x69, 0 x61, 3 x52, 2 x21, 1 x20, 15 x6.
Money in the Cerulean-respawn states is 11,258 (BCD 0x011258): the agent could afford potions and the free Pokecenter heal.

Two holes let the bad ancestors through (both already half-handled by PR #122, which added `checkpoint_goals.respawn_behind`):
1. `read_respawn` only looked at the goals sidecar. @61/@63 predate the `respawn` field, so they read as "unknown", and unknown
   counts as "not behind". `seg_store.ckpt` also fell back to a behind-Vermilion state when it was the only one.
2. Leg states (`runs/legs/states`, `--save-leg-states`) carried no metadata at all, so good states (respawn 5, full HP, same tile)
   were invisible to anything choosing a resume point.

Why the checkpoints carry Cerulean: the Vermilion Pokecenter heal does set the respawn (the nurse flow; nothing in `src/` writes
0xD719, only reads it, and every healthy leg state has respawn 5 with full HP). But a checkpoint is written the moment its goal
fires (`press_goals.py` -> `write_completed(..., respawn)`), and `to_vermilion` fires on arrival, before the heal. A later run that
boards hurt (the 11-06 pre-#122 runs did) saves `to_ss_anne` and `ss_anne_2f` with respawn still 3, and the next segment starts
from them: the defect is inherited, run after run.

## Shipped now

* `src/pokeagent/statefp.py`: `fingerprint(emu)` / `stamp(emu, state)` write `<state>.fp.json` (v, map, x, y, respawn, badges,
  money, party [species, level, hp, max_hp], heal_items, bag_slots, frames, source_run). Best effort, never raises.
* `legs/states.py`: `LegStateSaver` stamps each state it saves; rotation (`.1`, `.2`) and eviction carry the stamp.
* `checkpoint_goals.read_respawn` falls back to the fingerprint; `copy_sidecar` copies it with the state.
* `tools/seg_store.refusal` / `ckpt_valid`: a ship-stage checkpoint whose respawn is Pallet..Cerulean is not a valid segment start;
  the frontier falls back to the segment that remakes it (to_vermilion -> to_ss_anne heals in Vermilion first). The scheduler logs
  each refusal once. `tools/stamp_states.py runs/checkpoints` stamps legacy states from RAM (one headless emulator).

## Proposed: the ledger (two small modules)

`statefp.py` stays the only thing that reads RAM. New `statelog.py` (the ledger) only reads/writes JSON and never touches an emulator:

* `entries(dir) -> list[Entry]`: state path + fingerprint + age, read from the `.fp.json` files (no central file to corrupt, no lock).
* `select(entries, want) -> Entry | None`: `want` is a small dataclass per consumer: map (or goal), respawn must be >= a map rank,
  min party HP fraction, min lead level, min heal_items. Ranking: satisfy the hard filters, then strongest party
  (sum of level x HP fraction), then newest. A boss segment passes `min_hp=0.8`; a ship segment passes `respawn_ahead_of=Vermilion`.
* `status(entry) -> fresh | stale | retired`: stale = fingerprint missing or older than the code that reads it (`v`); retired = moved to
  `runs/retired/` with a reason line, never deleted (deletes stay confirm-first).
* Consumers: `seg_store.ckpt` (checkpoints) and `legs/attach.plan` (drill starts) call `select` instead of picking by file name or mtime.
  For a ship stage with no acceptable checkpoint, `select` over `runs/legs/states` can supply the same-map state (here
  `99_13_6.state` would have replaced `@63`).

`pokeagent states` CLI (in `cli.py`, 40 lines): `states list [--map M] [--bad]` prints one row per state (map, pos, respawn, party,
HP%, money, source run); `states check` exits 1 on any ship state with respawn behind Vermilion or a missing stamp (the invariant
checker calls the same function); `states restamp` is `tools/stamp_states.py`; `states retire PATH --why TEXT`.

Not in scope: event flags and a bag inventory beyond the heal-item count (add to `fingerprint` as a consumer needs them, bump `v`);
a database (the sidecars are the ledger).

## Rival / captain note (separate from the ledger)

From `runs/battles.jsonl` and 4,390 `transitions.jsonl`: 309 blackouts left a ship map for Cerulean (95 on 2F vs the rival, 208 at
the bow). In all 224 losses with a logged party (of 309 blackouts; 79 had no party record) the party was Magikarp 0/27 plus Wartortle at 6/78 or 6/79 (one 1/78), with no potions in the bag; the rival killed with Pidgeotto (61 times), Raticate (22), Kadabra (7), starter (2). After PR #122 the 2F rival losses stopped and the bow sailors (Tentacool L17 31x, Machop L17 27x) took over, all on the same 6/79 start. The rival's S.S. Anne team
(ROM trainer table, `kb/rom_tables.json` RIVAL2 party 1-3): Pidgeotto L19, Raticate L16, Kadabra L18, starter L20; the lead was L29.
The loss is HP and item use, not level.
