# PokeAgent: legal state verify - prove an edited state is legal by game logic, and let a verified descendant be reused safely

**Depends on (all merged on main as of 2026-11-07):** state surgery (`src/pokeagent/surgery.py`, `tools/state_edit.py`, `statefp.is_synthetic`, the synthetic gate in `tools/seg_ingest.py` and `tools/seg_store.py`),
the ledger (`src/pokeagent/statelog.py`, `src/pokeagent/statescmd.py`), `statefp.py`. If one is missing from your worktree, stop and write that in the Status row.
**Read first:** `src/pokeagent/surgery.py`, `tools/state_edit.py`, `src/pokeagent/statefp.py`, `src/pokeagent/statescmd.py`, `src/pokeagent/statelog.py`, `src/pokeagent/explorer/stats.py`, `src/pokeagent/ramstructs.py`,
`src/pokeagent/grind/xpmath.py`, `src/pokeagent/novelty/discoveries.py` (`odd_map`), `src/pokeagent/atlas/walkgrid.py`, `src/pokeagent/knowledge/hm_compat.py`, `src/pokeagent/knowledge/moves.py`,
`tools/seg_ingest.py` (`_synthetic_start`, `record_attempt`, `record_confirm`), `tools/seg_store.py` (`ckpt`, `ckpt_valid`, `replayable`), `docs/KNOWLEDGE.md` (the position-RAM note near line 22),
`tests/test_surgery.py`, `tests/test_state_fingerprint.py`. **Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-07): "We also need to work on a legal state verify method, to be able to verify a valid synthetic state, results in a later organic state, both being legal by game logic, and being able to reuse later
state progress from synthetic or edit states without risk of illegal actions or game breakers."

State surgery lets us write RAM, but nothing says the result is a state the game could reach. The ROM-validated finding that motivates this: `set_level` leaves the OLD experience on a raised level (a Magikarp edited to L20 still
carries L12 experience, which the game would never produce), so the result is already illegal by game logic. Without a verifier, a drill or A/B run from an edited state can hit a game breaker, and a later state "descended"
from a bad edit could be mistaken for an organic one. Three pieces: a read-only legality checker (section 4.1), an organic envelope (4.2), and lineage stamps with a promotion rule (4.3), plus the CLI hooks (4.4).

## 2. Facts (verified on the live checkout 2026-11-07; pasted because you cannot read `kb/` or `runs/` in the worktree)

- **Fingerprint** (`statefp.py`, v1, keys sorted; real `runs/checkpoints/ss_anne_captain.state.fp.json`; rows are `[species, level, hp, max_hp]`; `edited`, `synthetic`, `parent` are written by `tools/state_edit.py`):

```json
{"badges": 2, "bag_slots": 11, "frames": 14069, "heal_items": 0, "map": 101, "money": 14858, "party": [[133, 13, 29, 29], [179, 30, 82, 82]], "respawn": 5, "source_run": "explore-20261107-125805-24428", "v": 1, "x": 0, "y": 7}
```

- **`statefp.is_synthetic(state)`** is True when the sidecar has `synthetic` true. Today it is used by `seg_ingest._synthetic_start` / `record_attempt` / `record_confirm` (no attempt, no checkpoint copy, no best, a candidate best is rejected),
  `seg_store.ckpt` / `ckpt_valid` (never a segment start) and `seg_store.replayable` (a best whose start is synthetic cannot be confirmed). `tools/stamp_states.py` skips synthetic states without `--force`.
- **ROM tables** (`kb/rom_tables.json`, gitignored, drained from the ROM; top-level keys `source, moves, type_chart, species_by_dex, dex_of_internal, name_of_internal, learnsets, items, wild_by_map, trainers, map_trainers`):
  `species_by_dex[dex]` = `{hp, atk, def, spd, spc, type1, type2, catch_rate, base_exp, name, moves1, growth}`; `growth` is one of `MEDIUM_FAST` (80 species), `MEDIUM_SLOW` (39), `SLOW` (26), `FAST` (5).
  Example: `{"hp": 20, "atk": 10, "def": 55, "spd": 80, "spc": 20, "type1": "WATER", "type2": "WATER", "catch_rate": 255, "base_exp": 20, "name": "MAGIKARP", "moves1": ["SPLASH"], "growth": "SLOW"}`.
  `learnsets[NAME]` = `{"evolves": [{"how": "level"|"trade"|..., "level": N, "into": "NAME"}], "learnset": [[level, "MOVE"], ...]}`. Real rows: MAGIKARP `evolves` = `[{"how": "level", "level": 20, "into": "GYARADOS"}]`, WARTORTLE -> BLASTOISE at 36,
  ODDISH -> GLOOM at 21, KADABRA `{"how": "trade", "level": 1, "into": "ALAKAZAM"}`. `moves[id]` = `{name, effect, power, type, accuracy, pp}`. `dex_of_internal[internal id]` -> dex number; `name_of_internal[internal id]` -> name
  (133 MAGIKARP, 22 GYARADOS, 179 WARTORTLE, 185 ODDISH).
  `kb/items.json` (`items_catalog.build`): `items[id]` = `{id, name, price, sell, use_class, key_item, battle, overworld}`; the catalog covers ids 1..83 only (HM items sit above it: `docs/campaign_goals.md` says HM01 is 0xC4 and
  the bag then holds it; HM01-05 = 0xC4..0xC8 and TM01-50 = 0xC9..0xFA are the pokered layout, only 0xC4 is confirmed in this repo).
  `kb/hm_compat.json` = `{"source", "hms": {"cut": [...], "fly": [...], "surf": [...], "strength": [...], "flash": [...]}}`: HMs ONLY. **There is no TM compatibility table in the repo**: a move that is not in the level-up
  learnset / `moves1` / HM list cannot be proven legal, so it is a WARNING, never a violation.
- **Existing helpers to reuse (do not rewrite):** `explorer/stats.py`: `dvs(mon)`, `stat_exp(mon)`, `stat_value(base, dv, stat_exp_value, level, hp=False)`, `base_stats_of(species)`, `computed_stats(mon, base)`, `STAT_KEYS`;
  `grind/xpmath.py::exp_for_level(growth, n)` (cumulative XP, the Gen 1 cubic formulas; 0 for n <= 1);
  `ramstructs.py`: `read_party`, `decode_party_mon`, `PARTY_MON1`=0xD16B, `PARTY_MON_SIZE`=44, `read_bag`/`decode_item_list`, `BAG_CAPACITY`=20; party struct offsets: species +0, HP +1/+2, box level +3, status +4, moves +8..+11,
  exp +14..+16 (3 bytes, big-endian), stat exp +17..+26, DVs +27..+28, PP +29..+32 (low 6 bits PP, top 2 bits PP Ups), level +33, max HP +34/+35, stats +36..+43.
  `ramworld.py`: `read_money`, `read_badges`, `read_pokedex(emu) -> (owned, seen)` (dex numbers), `BADGES`=0xD356, `MONEY`=0xD347, `POKEDEX_OWNED`=0xD2F7, `POKEDEX_SEEN`=0xD30A (19 bytes each, one bit per species, both verified in `ram_map.json`).
  `novelty/discoveries.py::odd_map(map_id)` = a map id outside the normal list or named UNUSED (the glitch-map rule). `atlas/walkgrid.py::walk_grid(rom_bytes, map_header)` -> bool array (h*2, w*2) of walkable cells, `atlas/rom_maps` supplies the `MapHeader`
  (`map_id, tileset, h, w` in blocks).
- **Event flags: what is verified.** `wEventFlags` (0xD747, 320 bytes) is verified as a region (bits grow with progress), but only TWO individual flags are confirmed and replay-verified: `0xD803` bit 1 = the captain's back rubbed (`ss_anne_captain`) and bit 0 = got HM01
  (`hm01_cut`) (both in `campaign.json` as `flag` detectors). The eight gym-beaten flag bits and the S.S. Ticket flag are NOT verified anywhere in the repo, so those checks are warnings. Item ids confirmed: S.S. Ticket = 0x3F (`goals.SS_TICKET`), HM01 = 0xC4.
- **Position RAM:** `docs/KNOWLEDGE.md` records that writing only 0xD361/0xD362 leaves the map-view pointer (`wCurrentTileBlockMapViewPointer`, 0xD35F..0xD360, `verified: false` in `ram_map.json`) unshifted, so the screen is one tile off. **The relation between
  (map, x, y) and the pointer is NOT derived anywhere in the repo.** You cannot derive it (no ROM): implement the check as a stub that returns the warning `view pointer relation unverified` and leave a documented hook (`expected_view_pointer(map_w, x, y) -> int | None` returning `None`). The controller derives the relation from organic states afterwards.
- `surgery._set_level` today writes box level (+3), level (+33), max HP (+34/+35), HP and the four stats from the formula, and leaves experience (+14..+16) unchanged.

## Repo facts (verified 2026-11-07 on the live checkout; they are pasted because you cannot look outside the worktree)

- `uv run python --version` prints `Python 3.12.12`. Always `uv run`; never bare `python`.
- Full suite: `uv run pytest -q` (about 80-120 s; 1419 passed, 18 skipped on a clean tree per the controller). Per item:
  `uv run pytest -q tests/<file>`.
- `roms/`, `baselines/` and `runs/` are gitignored. **Your worktree has NO ROM, no `.state` baselines and no `runs/` data.**
  Every test uses `FakeEmulator` (`from pokeagent.emulator import FakeEmulator`, defined in `src/pokeagent/emulator.py`):
  `FakeEmulator({addr: byte, ...})` with `.memory` (dict), `.read(addr)`, `.read_range(start, n)`, `.set(addr, v)`,
  `.frames`, and `save_state(path)` / `load_state(path)` which write/read the memory dict as JSON. Use `tmp_path` for files.
- The existing test helper to copy from is `tests/test_state_fingerprint.py::world()`, which builds a FakeEmulator on map 0x61:

```python
LEAD = 0xD16B
def world(respawn=5, hp=79, mx=79, level=29, potions=2):
    emu = FakeEmulator({0xD35E: 0x61, 0xD362: 13, 0xD361: 6, 0xD719: respawn, 0xD356: 0b11,
                        0xD347: 0x00, 0xD348: 0x12, 0xD349: 0x34, 0xD057: 0, 0xD163: 1, 0xD164: 179})
    for off, v in ((0, 179), (1, hp >> 8), (2, hp & 255), (33, level), (34, mx >> 8), (35, mx & 255)):
        emu.memory[LEAD + off] = v
    emu.memory.update({0xD31D: 1, 0xD31E: 0x14, 0xD31F: potions, 0xD320: 0xFF})
    return emu
```

  That file also shows how tests import the `tools/` scripts: `sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))`
  then `import seg_store as ss`.
- **Files you must NOT modify** (another agent is working on the walk-off there): `src/pokeagent/explorer/ship_gate.py`,
  `planner.py`, `planner_east.py`, `planner_checkpoint.py`. Read them if you must; do not edit them.

## 3. Scope (one PR, in order)

1. Pure read-only checker `src/pokeagent/legality.py` (+ small sibling modules if it would pass 300 lines: e.g. `legality_party.py`, `legality_bag.py`, `legality_world.py`).
2. `src/pokeagent/envelope.py` (organic envelope from fingerprints).
3. Lineage and edit class in `statefp.py` + a new `src/pokeagent/lineage.py` (classification, promotion rule); the seg_ingest / seg_store gate generalised to lineage.
4. CLI (the `states` subcommands, implemented in `statescmd.py`): `check --legal [--envelope]` and `promote`, and `tools/state_edit.py` runs the checker and fixes `set_level` experience.
5. Tests: `tests/test_legality.py`, `tests/test_envelope.py`, `tests/test_lineage.py`; update `tests/test_surgery.py` for the exp rewrite.

## 4. The work

### 4.1 `legality.check` (never writes; takes a loaded emulator)

```python
@dataclass(frozen=True)
class Legality:
    ok: bool                       # no violations (warnings do not fail)
    violations: list[str]          # "<invariant>: <what> (bytes ...)"
    warnings: list[str]            # unverifiable or unverified checks
    checked: list[str]             # invariant names that actually ran

def check(emu, kb: dict | None, *, catalog: dict | None = None, hm: dict | None = None, rom: bytes | None = None) -> Legality
```

`kb` = the `rom_tables.json` dict, `catalog` = the `kb/items.json` dict, `hm` = the `hm_compat` table, `rom` = ROM bytes (only for the walk-grid check). Without `kb` the table-dependent invariants are not run and are listed as a warning (`no kb: party tables skipped`), never a violation.
Each invariant is its own small function named below; each violation string starts with the invariant name and names the bytes/addresses (e.g. `party_stats: slot 1 attack 0xD19F..A0 = 120, formula band 50..61`). `check` calls them in this order and never raises (a read failure is a violation `read: <addr>`).

(a) Party
- `party_structure`: count 1..6 (0xD163), species list 0xD164.. matches the struct species bytes, 0xFF terminator after the last, each species a valid internal id (`name_of_internal`), level 1..100, box level (+3) == level (+33), HP <= max HP, `1 <= max HP`.
- `party_stats`: stats stored in the struct must lie in the BAND `[stat_value(base, dv, 0, level), stat_value(base, dv, stat_exp, level)]` for each of HP, attack, defense, speed, special (use `explorer.stats.dvs/stat_exp/stat_value`; base stats from `species_by_dex` via `dex_of_internal`; the HP DV is derived by `dvs`).
  Why a band and not equality: the Gen 1 game recomputes stats on level-up and on some other events, not when stat experience is earned, so an organic mon can hold stats computed with LESS stat exp than it carries now (stat exp only grows). If the ROM validation finds an organic mon outside the band, the invariant is wrong (report it).
- `party_exp`: experience (+14..+16) must satisfy `exp_for_level(growth, level) <= exp < exp_for_level(growth, level + 1)` using the species' `growth` (level 100: `exp <= exp_for_level(growth, 100)`).
- `party_moves`: moves (+8..+11) are valid move ids (`moves` table) or 0, with no zero before a non-zero; each must be in `moves1(species)` or the level-up learnset of the species or any of its PRE-evolutions (walk `learnsets[*].evolves` backwards) at level <= the mon's level, or an HM the species can learn (`hm`); a move that is none of these is the WARNING `party_moves: slot S move NAME not provable (TM/other source; no TM table)`.
- `party_pp`: each PP byte's low 6 bits <= `base_pp + ups * (base_pp // 5)` (capped at 61 for the formula; `ups` = top 2 bits), and a move id of 0 has PP byte 0.
- `party_evolution`: for a species whose pre-form evolves BY LEVEL into it (`evolves` with `how == "level"`), a mon of the evolved species below that level is a violation (`party_evolution: slot S GYARADOS L12 < 20`). A pre-form AT OR ABOVE its evolution level is only a warning (`evolution pending`; the game evolves after a battle and the player can cancel it).
  This invariant is the least certain: if the ROM validation finds an organic hit (a wild or gift evolved form below the level), downgrade it to a warning and say so in the report.
(b) `bag`: count byte 0..20; every item id in the catalog (1..83) or 0xC4..0xFA (HM/TM range, see facts); qty 1..99; no duplicate ids; the 0xFF terminator sits right after the last pair.
(c) `money`: the three bytes are valid BCD (every nibble <= 9) and the value <= 999999.
(d) `badges`: badge byte bits vs the gym-beaten event flags: the flags are unverified, so this is the single warning `badges: gym-beaten flags unverified` (the byte itself is read and listed in `checked`).
(e) `key_items`: HM01 (0xC4) in the bag => `0xD803` bit 0 set (violation `key_items: HM01 in bag but 0xD803 bit0 clear`); the S.S. Ticket (0x3F) => its flag unknown => warning.
(f) `world`: `map` (0xD35E) must not be `novelty.discoveries.odd_map(map)` (violation `world: glitch map 0x..`); respawn (0xD719) in 0..10 (violation otherwise); with `rom` given and a known header, the player's (x, y) must be inside the map (`0 <= x < w*2`, `0 <= y < h*2`) and the cell walkable per `walk_grid` (violation `world: (x,y) not walkable on map 0x..`); without `rom` the walk check is listed as `skipped: no rom` in warnings. The view-pointer relation is the stub warning described in the facts.
(g) `pokedex`: owned bitfield is a subset of seen; every party species' dex number is owned (violations `pokedex: ...`).
`checked` lists the invariants that ran; `ok` is `not violations`.

### 4.2 `envelope.py` (empirical second gate)

From the fingerprints (`.fp.json`, via `statefp.read`) of every organic state (no `lineage` other than organic; `synthetic` not true) under `runs/checkpoints/` and `runs/legs/states/`, build per stage the maxima that the fingerprint carries: lead (max level over party rows), party size, money, badges, `bag_slots`, `heal_items`.
Stage key: the checkpoint's stem when it is a ladder goal (`goals.GOALS`), else `badges:<n>`. (The fingerprint has no full bag, so "first-seen items" is NOT buildable from it; leave it out and say so in the report. Do not bump `statefp.VERSION`.)
`build(dirs) -> dict` (pure JSON in, JSON out, deterministic), `within_envelope(fp, stage, env, slack_levels=3, slack_money=0.20) -> tuple[bool, list[str]]` (reasons: `lead L45 > envelope max L38 + 3`, `money 90,000 > 14,858 * 1.2`). A stage with no organic data is "unknown" (returns `(True, ["no organic data for stage X"])`: it cannot refuse). A legal but out-of-envelope state is "legal, unreachable".

### 4.3 Lineage and promotion

Fingerprint keys (additive, `v` stays 1): `lineage` (`organic` | `synthetic` | `promoted`), `edit_class` (`organic_equivalent` | `shortcut`, only on edited states), `legal` = `{"ok": bool, "violations": [...], "checked_at": "<UTC ISO>"}`, `edit_context` = `{"money_before": N, "parent_lineage": "..."}`.
- `statefp.lineage(state) -> str`: the `lineage` key when valid; else `"synthetic"` if `synthetic` is true (every state `tools/state_edit.py` wrote before this PR); else `"organic"`. A missing or unreadable sidecar reads `"organic"` (legacy checkpoints). `statefp.is_organic(state)` is `lineage == "organic"`. **`statefp.is_synthetic` becomes `lineage == "synthetic"`** (a promoted state is NOT synthetic).
- `lineage.edit_class(edited: dict, edit_context: dict, catalog: dict | None, envelope_info) -> str` from the `edited` dict `state_edit` stores (keys of `surgery.WHITELIST`). `organic_equivalent` only if EVERY edit is: `heal` (always); `respawn` to a town that an organic state at or before this stage has as its respawn (`envelope` can answer: a set of respawn ids seen); `give` where every item has `price > 0` in the catalog AND `money_before - new_money >= sum(price * qty)` (the cost was actually deducted); `take` (tossing/selling); `set_hp` to a value <= the current HP (damage).
  `shortcut` for: `set_level`, a `money` increase or any `money` edit not paired with a purchase, free `give`, `set_hp` above current, `position`. Empty/unknown -> `shortcut`.
- `tools/state_edit.py` stamps `lineage: "synthetic"`, `edit_class`, `edit_context` (money before, parent lineage) and `legal` (section 4.4) in addition to what it writes now. An edit applied to a state that is itself not organic keeps `lineage: "synthetic"` and its edit_class is `shortcut` unless the parent's edit_class was organic_equivalent too.
- **Inheritance (no laundering).** A run's own checkpoints and end state are stamped by `press_goals.record_goals` / `press_stop.save_end_state` through `statefp.stamp`, which writes a fresh fingerprint with no lineage (reads as organic). Add the run's start state path to the explorer options next to `state_stem` (`ExplorerOptions.state_path: str = ""`, set where `--state` is parsed: find every place that sets `state_stem` by reading `tools/explore_headless.py`, `tools/explore_demo.py` and `src/pokeagent/explorer/context.py`) and give `statefp.stamp(..., inherit: Path | None = None)`: when `inherit` is given and that state's lineage is not organic, the new fingerprint gets the same `lineage` (`synthetic` stays `synthetic`, `promoted` stays `promoted`) and `parent` = its name; both `press_goals` stamp calls and `save_end_state` pass `inherit=ctx.opts.state_path or None`.
- **Promotion** `lineage.promote(end_state, start_state, emu, kb, ...) -> tuple[bool, list[str]]`: allowed only if (1) the start's lineage is `synthetic` AND its `edit_class` is `organic_equivalent`; (2) `legality.check(emu loaded with end_state)` is ok; (3) `within_envelope` holds for the end state's fingerprint and stage. On success the END state's sidecar gets `lineage: "promoted"`, `legal`, `parent` (the start's name) and `promoted_from`; on failure nothing is written and the reasons are returned. A `shortcut` lineage is never promoted ("stays synthetic forever").
- **The gate (what a promoted state may and may not do).** A promoted state MAY seed drills, A/B runs and segment starts (`seg_store.ckpt`/`ckpt_valid` keep refusing only `is_synthetic`). It may NEVER yield a chain best or confirmation: change `seg_ingest._synthetic_start`/`record_attempt`/`record_confirm` and `seg_store.replayable` to refuse when the start is NOT organic (`not statefp.is_organic`), i.e. synthetic and promoted. The refusal behaviour is the existing one (no attempt, no checkpoint copy, no best; a candidate best is rejected). `tools/stamp_states.py` keeps skipping non-organic states without `--force`.

### 4.4 CLI

- `states check --legal [--envelope] [--rom ROM] [--dir D ...]` (handler `cmd_check` in `statescmd.py`; keep the existing `check` behaviour when the flags are absent): loads each state into ONE headless emulator (build it through a module function `make_emulator(rom)` as `tools/state_edit.py` does, so tests replace it), runs `legality.check` and prints per state `ok` or each violation / warning line; `--envelope` also prints `within_envelope` reasons (JSON only, no emulator). Exit 1 on any violation (warnings never fail). `kb` is loaded from `kb/rom_tables.json` (and `kb/items.json`, `kb/hm_compat.json`) when present, else `check` prints the no-kb warning and the table invariants are skipped.
- The `promote` subcommand (positional END state, a `--from` option for the START state, optional `--rom`; new handler `cmd_promote`) runs `lineage.promote` and prints the result.
- `tools/state_edit.py`: after `surgery.apply` and before saving, run `legality.check` on the edited emulator; compute the violations the INPUT state already had (check it before applying) and refuse to save when the result has violations that the input did not have (exit 2, message names them) unless `--allow-illegal` (then stamp `legal.ok: false` and the violations). `--dry-run` prints the legality result too.
- **`set_level` exp rewrite** (`surgery._set_level`): also write experience = `exp_for_level(growth, level)` (3 bytes, big-endian, at +14..+16) for the raised mon, so the result satisfies `party_exp`. `surgery.apply` gets a `growth` callable parameter next to `max_pp`/`base_stats` (`growth(species) -> str | None`); `set_level` raises `SurgeryError("set_level needs the growth rate (kb/rom_tables.json)")` without it; `tools/state_edit.py` builds it from `species_by_dex[..]["growth"]`. A level raise to the SAME level is a no-op on exp.

## 5. What NOT to do

- No event-flag writes; no new RAM addresses without evidence (every address used above is in the facts); `legality` and `envelope` never write a state or a sidecar (only `lineage.promote`, `tools/state_edit.py` and the CLI write sidecars).
- No changes to `ship_gate.py`, `planner.py`, `planner_east.py`, `planner_checkpoint.py`. No deletion of states or sidecars (this PR has no delete path).
- Do not derive or hard-code the map-view-pointer relation (it is unverified); do not turn any unverified check (gym flags, TM moves, S.S. Ticket flag, view pointer, evolution-pending) into a violation.
- No ROM, no emulator runs by Devin, and the only commands you run are `uv run pytest -q ...`; tests use `FakeEmulator` and small fixture tables. No new dependencies; each module under 300 lines; do not bump `statefp.VERSION`.

## 6. Verification

- `uv run pytest -q tests/test_legality.py tests/test_envelope.py tests/test_lineage.py tests/test_surgery.py`:
  1. **One fixture, one byte off per invariant.** Build a small `kb` dict (two species with `growth`, base stats, `moves1`, an `evolves` row, a `moves` table with `pp`, `dex_of_internal`, `name_of_internal`) and a `FakeEmulator` party (extend the `world()` helper of `tests/test_state_fingerprint.py` to two mons with DVs, stat exp, exp, PP, moves, and the pokedex bytes) that `check` passes (`ok`, `violations == []`, every invariant in `checked`).
     Then, for EACH of `party_structure`, `party_stats`, `party_exp`, `party_moves`, `party_pp`, `party_evolution`, `bag`, `money`, `key_items`, `world` (glitch map; respawn 11; out-of-bounds/unwalkable cell with a tiny fake walk grid injected), `pokedex`: change exactly one byte and assert `ok is False` and the violation string starts with that invariant's name and names the address.
  2. The stat band: stats computed with stat exp 0 pass, stats computed with the full stat exp pass, one point above/below the band fails (so an organic mon with lazily applied stat exp is legal).
  3. A move not provable by level-up/`moves1`/HM is a WARNING and `ok` stays True; a pre-form at its evolution level is a warning, the evolved form below the level is a violation.
  4. `check(emu, None)` does not raise, `ok` True, a no-kb warning; a `Bare` emulator whose reads raise yields a `read:` violation, not an exception.
  5. Envelope: `build` over a `tmp_path` with three organic sidecars (and one `synthetic`, which is ignored) gives the per-stage maxima; `within_envelope` passes at the max, passes within slack (+3 levels, +20% money), fails beyond with the reasons; an unknown stage returns `(True, [...])`.
  6. Lineage: `statefp.lineage` for no sidecar / `synthetic: true` / explicit `lineage`; `is_synthetic` is False for `promoted`; `edit_class` for `heal` (organic_equivalent), `give` with money deducted by at least the price (organic_equivalent) vs free `give` (shortcut), `set_level` (shortcut), `money` (shortcut), `respawn` to a seen town vs unseen.
  7. Promotion: organic_equivalent start + legal + in-envelope end -> `promoted` sidecar written; each failing condition (shortcut start, an illegal end, out of envelope) writes nothing and returns reasons.
  8. The gate: with a `promoted` start (sidecar written via `statefp.write`) `seg_ingest.record_attempt` leaves the doc unchanged and `seg_store.replayable` is False, while `seg_store.ckpt_valid` still accepts it as a start (it is not `is_synthetic`); with a `synthetic` start the existing refusals hold; organic is unchanged. Inheritance: `statefp.stamp(emu, path, inherit=<synthetic state>)` writes `lineage: synthetic`; `inherit=<organic state>` writes no lineage.
  9. `set_level`: the exp bytes at +14..+16 equal `exp_for_level(growth, level)` big-endian for the fixture (e.g. SLOW growth L20 -> 10000 = `00 27 10`); without `growth` it raises; the result passes `party_exp`. `tools/state_edit.py` `main([...])` with `make_emulator` replaced: an edit that produces an illegal result (e.g. `--give` of item id 0xFE... invalid id, or a respawn the checker rejects) exits 2 without `--allow-illegal` and saves with `legal.ok false` with it; an input that was already illegal does not block an unrelated legal edit.
  10. the `statescmd` handlers (`cmd_check` with legal=True, called as functions with parsed args, never as a process) on a `tmp_path` dir with one legal and one illegal fixture state (via an injected `make_emulator`): exit 1, the violation printed; `cmd_promote` happy path and refusal.
- Update, do not delete, existing assertions whose meaning changes (`is_synthetic` for promoted states; the `set_level` bytes in `tests/test_surgery.py` now include the exp rewrite). `uv run pytest -q` green; paste the before/after tails.
- **Controller validation (not run by Devin; ROM validation is the controller's job, you have no ROM or `kb/`):** run the legality check (the `states` check handler with legal on) over all live checkpoints (82 at the time of writing) and `runs/legs/states`; expect 0 violations on organic states. A violation on an organic state means the INVARIANT is wrong, not the state; the report must list which invariant so it can be fixed or downgraded. The controller also derives the view-pointer relation from a dozen organic states.

## 7. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation is rejected and ends the run. No installs, downloads or fetches.
  Never read outside the worktree.
- **Do not run the `pokeagent` entry point (the sandbox refuses it). Do not list the directory tree recursively; use `git ls-files`.
  Do not read outside the worktree. Create no scratch files; deleting is denied. If something expected is missing, stop and write that in the Status row.**
- Do not search, glob or hunt for a missing file or fact: stop and say so in the Status row.
- Test commands are exactly `uv run pytest -q` and `uv run pytest -q tests/<file>`. Never bare `python`.
- Work only on branch `directive/pokeagent-legal-state-verify-directive`. Never commit to `main`; never push; never deploy. Commit on the branch as you go.
- Create no scratch or debug files (deleting is denied and ends the run). If one is truly needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row; do not try another way around it.
- SOLID/SRP/KISS is a hard rule here: small new modules (under 300 lines), no new dependencies.

## 8. Completion criteria

- [ ] `legality.check` with the invariants named in 4.1 (each its own small function), warnings for every unverified check, never raises, never writes
- [ ] `envelope.build` / `within_envelope`; lineage keys, `statefp.lineage` / `is_organic`, `edit_class`, `inherit` on `statefp.stamp` and its callers, `lineage.promote`
- [ ] seg_ingest / seg_store gate refuses non-organic starts for bests and confirmations, still allows promoted starts for segment starts and drills
- [ ] `check --legal [--envelope]` and `promote` handlers in `statescmd.py`, `tools/state_edit.py` legality gate + `--allow-illegal`, `set_level` exp rewrite with `growth`
- [ ] The four test files pass; `uv run pytest -q` green (paste the tail); `git diff --stat main` pasted; no forbidden file changed
- [ ] Status row moved to Review with the branch name

## 9. Report

Findings first: test tails (before/after), `git diff --stat`, the module list with line counts, the final signatures of `check`, `promote`, `statefp.stamp`, which invariants are violations vs warnings and why, exactly where the gate changed in `seg_ingest` / `seg_store`,
the `edit_class` rules as implemented, and everything you could not verify without a ROM.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Review |
| Assigned to | devin |
| Branch | directive/pokeagent-legal-state-verify-directive |
| Base branch | - |
| Base commit | d5bd500e4176adc6445aae10dc299e311e5f331f |
| Head commit | 3ce9a7c3a07061bd68aa5bcbdb10d30bcb26878c |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-07 14:26 · robert-claude-laptop · none → Draft — Claude 2026-11-07: legality checker, envelope, lineage/promotion
- 2026-11-07 14:27 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; lint_override: dispatch-path-missing on new modules/tests and gitignored kb/ + runs/ evidence paths only
- 2026-11-07 14:30 · robert-claude-laptop · Queued → Draft — Claude 2026-11-07: reword for Devin allow list (pytest only); requeueing
- 2026-11-07 14:30 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07: pytest-only for Devin; CLI checks are controller validation. lint_override: dispatch-path-missing only
- 2026-11-07 14:31 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing on greenfield files (legality.py, envelope.py, three test files) and gitignored evidence (kb/*.json, runs/checkpoints/*.fp.json); known false positives. Entry-point steps reworded to pytest + controller validation.
- 2026-11-07 15:03 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-legal-state-verify-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6VSQ82HZE89YJQWNJ902CQ9
- 2026-11-07 15:07 · dispatcher · launched pid=6240; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-legal-state-verify-directive; provisioned: uv sync --frozen
- 2026-11-07 15:26 · devin · In progress → Review — Legal state verify implemented. Tests: before 1419 passed/18 skipped (directive baseline); after `uv run pytest -q`: 1557 passed, 36 skipped in 215s; the four files: 65 passed in 2.2s. git diff --stat main...HEAD: 23 files, +1230/-43 (legality.py split into legality.py + legality_party.py to stay under 300). Modules (lines): legality.py 195, legality_party.py 185, envelope.py 79, lineage.py 91, statefp.py 112, statescmd.py 208, surgery.py 240, tools/state_edit.py 209. Signatures: `legality.check(emu, kb, *, catalog=None, hm=None, rom=None) -> Legality` (ok, violations, warnings, checked); `lineage.promote(end_state, start_state, emu, kb, *, catalog=None, hm=None, rom=None, env=None, slack_levels=3, slack_money=0.20) -> (bool, [reasons])`; `statefp.stamp(emu, state, source_run=None, *, inherit=None) -> dict`. Violations: party_structure (count/list/terminator/level/box==level/HP<=max/maxHP>=1), party_stats (stat band [se=0, se]), party_exp (growth-band exp), party_moves (invalid ids, zero-gap), party_pp (PP>formula cap 61, empty-move PP!=0), party_evolution (evolved form below pre-form's level), bag (count/id/qty/dup/terminator), money (BCD<=999999), key_items (HM01 w/o 0xD803 bit0), world (glitch map, respawn>10, out-of-bounds/unwalkable cell), pokedex (owned not subset of seen; party species not owned). Warnings (unverified/unprovable): badges gym flags, TM-source moves, S.S. Ticket flag, view-pointer stub `expected_view_pointer()->None`, evolution pending, no-kb/no-catalog skips, no-rom walk check. Gate: seg_ingest._synthetic_start renamed `_non_organic_start` -> `not is_organic`; record_confirm + seg_store.replayable refuse non-organic starts; ckpt/ckpt_valid unchanged (refuse only is_synthetic -> promoted may start segments); statelog._kept now filters lineage_of=='synthetic'; stamp_states skips non-organic. edit_class: organic_equivalent iff every edit is heal / respawn-to-seen-town (envelope respawns_seen) / give-with-priced-items+money-drop>=cost / take / set_hp<=current; shortcut for set_level, position, money not purchase-paired, free give, set_hp-above-current, empty/unknown; non-organic parent forces shortcut unless parent was organic_equivalent. set_level now writes exp=exp_for_level(growth,level) at +14..16; same-level no-op on exp; raises without growth callable. CLI: `states check --legal [--envelope] [--rom]` (make_emulator seam, exit 1 on any violation) and `states promote END --from START`. state_edit runs check before+after, refuses NEW violations unless --allow-illegal; stamps lineage/edit_class/edit_context/legal. Unverified without ROM/kb (controller's job): all organic checkpoints under --legal should show 0 violations; a hit means the invariant is wrong (party_evolution is the least certain, party_stats band second); view-pointer relation to be derived by controller into expected_view_pointer. [origin] spent: devin 19 min est. n/a
<!-- queue:end -->
