# PokeAgent: state surgery v1 - edit a save state (heal, money, respawn, items, HP/level) and mark it synthetic

**Read first:** `docs/superpowers/specs/2026-11-07-save-state-ledger.md` (the fingerprint sidecar and why states need metadata),
`src/pokeagent/emulator.py` (the `Emulator` protocol, `PyBoyEmulator`, `FakeEmulator`), `src/pokeagent/statefp.py`,
`src/pokeagent/ramstructs.py`, `src/pokeagent/ramworld.py` (`read_money`, `MONEY`), `src/pokeagent/explorer/stats.py`
(`dvs`, `stat_value`, `base_stats_of`, `computed_stats`), `tools/stamp_states.py` (the pattern for a ROM-loading tool),
`tools/seg_ingest.py` (`record_attempt`, `record_confirm`, `_job_record`), `tools/seg_store.py` (`replayable`, `ckpt`, `ckpt_valid`),
`tests/test_state_fingerprint.py`. If any of these is missing, stop and write that in the Status row.
**Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-07): "are we making progress toward Save State Editing?" The pieces exist (a fingerprint that reads the RAM
facts of a state, a loader, an A/B harness) but no tool WRITES them. Two things this unlocks:

1. Counterfactual questions answered in minutes instead of by play. The S.S. Anne rival question took 300+ runs to answer by
   playing (every loss started with the lead at 6/79 HP and 0 potions; see the spec's "Rival / captain note"). With an edited state
   (same tile, party healed; same tile, +1 Super Potion) `tools/ab.py --state <edited>` answers "was it the HP or the level?" directly.
2. Bad checkpoints can be repaired instead of remade: `runs/checkpoints/ss_anne_captain@63.state` was a good tile with respawn 3 (Cerulean);
   setting respawn 5 and healing would have been a valid drill start.

An edited state is a SYNTHETIC state: never a chain checkpoint, never a personal best. It may be used for drills and A/B only.

## 2. Facts (verified on the live checkout 2026-11-07; pasted because you cannot look outside the worktree)

- **Memory write seam.** The `Emulator` protocol (`src/pokeagent/emulator.py`) has `read` and `read_range` but NO write. `PyBoyEmulator.read` is
  `self._pyboy.memory[addr]`; PyBoy 2.x memory views accept assignment, and the repo already writes that way in two tools
  (`tools/explore_headless.py` line 52: `emu._pyboy.memory[0xD16C], emu._pyboy.memory[0xD16D] = 0, args.hurt`; `tools/score_check.py`).
  `FakeEmulator` has `set(addr, value)` (writes its `.memory` dict). You add `write(addr: int, value: int) -> None` to the protocol,
  to `PyBoyEmulator` (`self._pyboy.memory[addr] = value & 0xFF`) and to `FakeEmulator` (calls `set`). Do not use `_pyboy` outside `emulator.py`.
- **Fingerprint sidecar** `<state>.fp.json` (`statefp.py`; real file `runs/checkpoints/to_vermilion.state.fp.json`; keys sorted, `v` 1):

```json
{"badges": 2, "bag_slots": 11, "frames": 0, "heal_items": 0, "map": 5, "money": 11258, "party": [[133, 12, 0, 27], [179, 29, 6, 79]], "respawn": 3, "v": 1, "x": 18, "y": 31}
```

  `statefp.stamp(emu, state, source_run)` fingerprints the RAM and writes it; `statefp.write(state, fp)` / `statefp.read(state)` store and load a dict.
- **`src/pokeagent/data/ram_map.json`**: 2,792 entries, 107 `verified: true` (`tools/verify_ram.py` writes `verified` plus `evidence`; it needs the ROM).
  Addresses this directive writes, with their layout (from `ramstructs.py` / `ramworld.py` / `statefp.py`):

| addr | field | encoding |
|---|---|---|
| 0xD719 | wLastBlackoutMap (respawn town) | u8; verified 2026-11-07; 0 Pallet, 1 Viridian, 2 Pewter, 3 Cerulean, 4 Lavender, 5 Vermilion, 6 Celadon, 7 Fuchsia, 8 Cinnabar, 9 Indigo, 10 Saffron |
| 0xD35E | wCurMap | u8 |
| 0xD361 / 0xD362 | y / x tile | u8 each |
| 0xD347..0xD349 | money | 3 bytes BCD, big-endian (11,258 yen = `01 12 58`) |
| 0xD163 | party count | u8 (max 6) |
| 0xD16B + 44*slot | party mon struct (`PARTY_MON1`, `PARTY_MON_SIZE` 44) | species +0; HP +1 (hi) +2 (lo), big-endian; box level +3; status +4; moves +8..+11; exp +14..+16; stat exp +17..+26; DVs +27..+28; PP +29..+32 (low 6 bits = PP, top 2 bits = PP Ups); level +33; max HP +34 (hi) +35 (lo); attack/defense/speed/special +36..+43 (u16 big-endian each) |
| 0xD31D | bag: count byte, then (item id, qty) pairs, then 0xFF terminator | `BAG_COUNT`, capacity `BAG_CAPACITY` = 20 slots; qty 1..99 per slot |
| 0xD356 | badges bitmask | read only here (no badge edits in v1) |

  Item ids in this repo: 0x14 POTION, 0x13 SUPER POTION, 0x12 HYPER POTION, 0x11 MAX POTION (`explorer/behaviours/cave_escape.py`, `item_use.py`).
- `tools/make_state.py` (usage docstring): "Build reusable emulator checkpoints from an existing savestate", with flags `--src SRC --out OUT --clear-dialog` and `--goto MAP:X:Y --press BUTTON`.
  It walks and presses buttons; it does not write RAM. `tools/state_info.py <glob>` prints the `statemeta` sidecars (not `.fp.json`).
  `tools/ab.py --state S --goal G --seeds 1-4 --steps N --a "" --b "--flag"` runs two explorer variants headless from state `S`.
- **Where a personal best is recorded (read from `tools/`):** `tools/seg_ingest.py::record_attempt` (updates attempt stats, may copy the run's `end.state`
  over `runs/checkpoints/<end>.state`, and sets `st["best"]`); `record_confirm` (accepts a candidate best after a replay);
  `tools/seg_store.py::replayable` (a best can be confirmed only if its kept start state is still there and unchanged); `tools/seg_store.py::ckpt` /
  `ckpt_valid` (which checkpoint starts a segment); `tools/seg_sched.py::_job` / `_confirm` (the job's `start`). The job's start-state
  copy is recorded by `seg_ingest._job_record(root, tag)` as `{"start", "start_sha"}`.

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

1. `src/pokeagent/emulator.py`: `write(addr, value)` on the protocol, `PyBoyEmulator` and `FakeEmulator`.
2. New pure module `src/pokeagent/surgery.py` (the whitelist and the RAM writes; no I/O, no file access, no ROM).
3. `src/pokeagent/statefp.py`: one helper `is_synthetic(state: Path) -> bool` (True when `read(state)` has `synthetic` true; False on missing/unreadable). Nothing else in that file changes.
4. New `tools/state_edit.py` (the CLI: load, apply, save, re-stamp).
5. The synthetic gate in `tools/seg_ingest.py` and `tools/seg_store.py` (functions named in section 4.4).
6. Tests: `tests/test_surgery.py`.

## 4. The work

### 4.1 `surgery.py`

```python
class SurgeryError(ValueError): ...      # unknown field, out-of-range value, capacity, a refused edit

WHITELIST = ("heal", "set_hp", "set_level", "money", "respawn", "give", "take", "position")

def apply(emu, edits: dict, *, max_pp=None, base_stats=None) -> list[tuple[int, int, int]]:
    """Validate EVERY edit first (raise SurgeryError before the first write), then write.
    Returns the writes applied as [(addr, old_byte, new_byte)] in order (only bytes whose value changed)."""
```

`edits` keys (anything else raises `SurgeryError("unknown field: <name>")`; an edit dict that is empty raises too):

- `"heal": True` - for each party slot (count at 0xD163, capped at 6): HP = max HP (+1/+2 from +34/+35), status (+4) = 0, and PP: when `max_pp`
  (a callable `move_id -> base PP or None`) is given, each non-zero move's PP low 6 bits = `base + ups * (base // 5)` (ups = top 2 bits, kept),
  capped at 63; without `max_pp` PP is left untouched (the CLI passes it from `kb/rom_tables.json`).
- `"set_hp": {slot: hp}` - slot 0..count-1; `0 <= hp <= max HP` of that mon (read from the struct), written big-endian at +1/+2.
- `"set_level": {slot: level}` - RAISE only (`level >= current`, `<= 100`); writes box level (+3) and level (+33), then recomputes max HP (+34/+35) and the
  four stats (+36..+43) with `pokeagent.explorer.stats` (`dvs`, `stat_exp`, `stat_value`; base stats from the injected `base_stats(species) -> dict | None`,
  default `explorer.stats.base_stats_of`); HP is raised by the same amount max HP rose (never above max). Exp and species and moves are NOT touched.
  If base stats are unavailable, raise `SurgeryError("set_level needs base stats (kb/rom_tables.json)")`. Lowering a level raises too.
- `"money": N` - `0 <= N <= 999999`, written as 3 BCD bytes at 0xD347..0xD349.
- `"respawn": M` - one of the town ids 0..10 (table above); anything else raises (15 has been observed but is not understood, so it is not allowed).
- `"give": [(item_id, qty), ...]` / `"take": [(item_id, qty), ...]` - on the bag list at 0xD31D: `give` adds to an existing stack of the same id (max 99 per slot;
  overflow goes to a new slot) or appends a slot; it raises if the 20-slot capacity would be exceeded. `take` removes qty (raises when the bag holds less); a slot reaching 0
  is removed and the later slots shift up. After either, rewrite the count byte, the pairs, and the 0xFF terminator right after the last pair (zero the unused tail is NOT
  needed; the terminator is what the game reads). `item_id` 1..0xFF excluding 0xFF; `qty` 1..99.
- `"position": {"map": m, "x": x, "y": y, "warp_safe": True}` - refused unless `warp_safe` is literally `True` AND `m` equals the current map (0xD35E): v1 does NOT
  change maps (a map id write without a warp leaves the loaded tile data wrong). Writes y (0xD361) and x (0xD362) only. Document in the docstring that the player sprite
  position is not rewritten and that the controller validates the result on the ROM.

Everything is validated before any write; `apply` is all-or-nothing from the caller's view. Keep each edit in its own small function (SRP); the module stays under 300 lines.

### 4.2 `tools/state_edit.py`

```
uv run python tools/state_edit.py IN.state --out OUT.state [--rom ROM] [--heal] [--money N] [--respawn M]
    [--give ID:QTY ...] [--take ID:QTY ...] [--set-hp SLOT:HP ...] [--set-level SLOT:LEVEL ...] [--pos MAP:X:Y --warp-safe] [--dry-run]
```

Numbers accept decimal or `0x` hex (`--give 0x13:1`, `--respawn 0x05`). Flow: build the edits dict; load `IN` into a `PyBoyEmulator(ROM, headless=True)` (default ROM
`roms/Pokemon Red.gb` under the repo root; build the emulator through a module function `make_emulator(rom)` so tests can replace it); `surgery.apply`; `emu.save_state(OUT)`;
`fp = statefp.stamp(emu, OUT, source_run=f"edit:{IN.name}")`; add to `fp`: `"synthetic": true`, `"edited": {...}` (the edits dict as JSON, ids and numbers only) and
`"parent": IN.name`; `statefp.write(OUT, fp)`. Print the writes as `0xADDR old -> new`. `--dry-run` loads and applies in memory, prints the writes, saves nothing.
Refusals (exit 2 with a message): `OUT` equal to `IN`; `OUT` under `runs/checkpoints/` or `runs/segments/` (default OUT directory is `runs/edited/`, created on demand);
`OUT` already exists unless `--force`. Do NOT copy the goals sidecar (`checkpoint_goals.sidecar`) to `OUT`: it holds an old `respawn` that `read_respawn` prefers over the fingerprint.
`max_pp` is built from the `moves` table (`pokeagent.knowledge.kb.table(None, "moves")`, rows have `"pp"`) when available, else `None`.

### 4.3 What the stamp means

`synthetic: true` means "RAM was written by a tool, not reached by play". `edited` lists exactly what was written. A re-stamp of an edited state later by `tools/stamp_states.py`
would drop these keys; add a one-line guard there: skip a state whose existing fingerprint has `synthetic` true unless `--force`. (`tools/stamp_states.py` is the only other file
that writes fingerprints in place.)

### 4.4 The synthetic gate (a solve from an edited state never counts)

Use `statefp.is_synthetic`. Exact places:
- `tools/seg_ingest.py::record_attempt`: at the top, resolve the job's start state with `_job_record(root, tag)["start"]` (when `tag` is set) and, if that file `is_synthetic`,
  return before ANY mutation: no attempt appended, no `n`/`solves` increment, no checkpoint copy, no `st["best"]`. Also treat an attempt whose run `meta.json` names a `start`
  path that is synthetic the same way (read `run / "meta.json"` defensively; a missing or odd meta means "not synthetic").
- `tools/seg_ingest.py::record_confirm`: if the candidate's `b["start"]` is synthetic, mark the best rejected (`rejected = True`) instead of confirming.
- `tools/seg_store.py::replayable`: return False when `b["start"]` is synthetic.
- `tools/seg_store.py::ckpt` and `ckpt_valid`: a synthetic state is never returned / never valid as a segment start (it lives outside `runs/checkpoints/`, so this is a guard).
- If `src/pokeagent/statelog.py` exists in your worktree, its `select` must skip entries whose fingerprint has `synthetic` true unless the `Want` asks for them; if the file does not
  exist, do nothing about it (do not create it).
`tools/ab.py` and the drills keep working from an edited state; do not gate them.

## 5. What NOT to do

- No event-flag writes (0xD747 range) and no script/cutscene state; no species, move, DV, exp, or badge edits; nothing outside `WHITELIST`; no map change.
- Do not modify `ship_gate.py`, `planner.py`, `planner_east.py`, `planner_checkpoint.py`.
- Do not write to `runs/`, `baselines/`, or any `.state` that exists in the repo; the tests use `tmp_path` only.
- Do not run any emulator. There is no ROM in your worktree; `PyBoyEmulator` is never instantiated in tests. Do not run `uv run pokeagent ...` or `tools/state_edit.py` against a real state.
- No new dependencies; each new module under 300 lines.

## 6. Verification

- `uv run pytest -q tests/test_surgery.py` - new tests, `FakeEmulator` + `tmp_path` (a party fixture like `tests/test_state_fingerprint.py::world()`, extended to two party mons):
  1. `heal`: HP bytes (+1/+2) equal max HP (+34/+35) for each slot, status 0, PP restored with a stub `max_pp` and Ups bits kept; without `max_pp` PP bytes are unchanged.
  2. `set_hp` writes hi/lo big-endian exactly (e.g. 300 -> `01 2C`); above max HP or a bad slot raises and writes nothing.
  3. `set_level` raises level + box level and recomputes max HP and stats with a stub `base_stats`; lowering raises; no base stats raises.
  4. `money`: 1,234 -> `00 12 34`; 999999 -> `99 99 99`; 1,000,000 raises; negative raises.
  5. `respawn`: 5 writes 0xD719; 15 and 300 raise.
  6. Bag: `give` merges into an existing stack, splits past 99, appends a slot, writes the count and the 0xFF terminator in the right place; capacity 20 overflow raises; `take` removes a middle
     slot and shifts the later ones up; taking more than held raises and writes nothing.
  7. `position`: refused without `warp_safe=True`; refused when `map` differs from the current map; with both, only 0xD361/0xD362 change.
  8. Unknown field raises `SurgeryError`; an empty dict raises; `apply` returns `(addr, old, new)` tuples only for changed bytes; a failing edit anywhere leaves memory untouched.
  9. `tools/state_edit.py` `main([...])` with `make_emulator` monkeypatched to a `FakeEmulator` (use `save_state` to make the input; `FakeEmulator.load_state` reads JSON): the output
     fingerprint has `synthetic` true, `edited` listing the edits, `parent`; refuses `--out` under `runs/checkpoints/`, `--out` equal to the input, and an existing `--out` without `--force`; `--dry-run` saves nothing.
  10. Gate: with a synthetic start-state file (stamped via `statefp.write`), `seg_ingest.record_attempt` leaves the doc unchanged (no attempts, no `best`) and `seg_store.replayable` is False;
      with a non-synthetic start the existing behaviour is unchanged (build the minimal `doc`/`seg`/`att` the way the existing seg_ingest tests do; find them with `git grep -ln record_attempt -- tests`).
- `uv run pytest -q` green; paste the before/after tails.
- **ROM validation is the controller's job, on the laptop (you have no ROM):** load an edited state in `PyBoyEmulator`, read the bytes back, run a few hundred frames, confirm the game is not corrupted
  (party screen shows the edit, no crash, the player can still walk), then `tools/ab.py` from it. Do not attempt this.

## 7. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation is rejected and ends the run. No installs, downloads or fetches.
  Never read outside the worktree.
- **Do not run the `pokeagent` entry point (the sandbox refuses it). Do not list the directory tree recursively; use `git ls-files`.
  Do not read outside the worktree. Create no scratch files; deleting is denied. If something expected is missing, stop and write that in the Status row.**
- Do not search, glob or hunt for a missing file or fact: stop and say so in the Status row.
- Test commands are exactly `uv run pytest -q` and `uv run pytest -q tests/<file>`. Never bare `python`.
- Work only on branch `directive/pokeagent-state-surgery-directive`. Never commit to `main`; never push; never deploy. Commit on the branch as you go.
- Create no scratch or debug files (deleting is denied and ends the run). If one is truly needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row; do not try another way around it.
- SOLID/SRP/KISS is a hard rule here: small new modules (under 300 lines), no new dependencies.

## 8. Completion criteria

- [ ] `Emulator.write` on the protocol, `PyBoyEmulator` and `FakeEmulator`; `surgery.py` with `apply`, `WHITELIST`, `SurgeryError`; `statefp.is_synthetic`
- [ ] `tools/state_edit.py` with the flags above, the three refusals, the `synthetic` / `edited` / `parent` stamp; `tools/stamp_states.py` skips synthetic states without `--force`
- [ ] The synthetic gate in `seg_ingest.record_attempt`, `record_confirm`, `seg_store.replayable`, `ckpt`, `ckpt_valid`
- [ ] `tests/test_surgery.py` passes (the ten cases); `uv run pytest -q` green (paste the tail); `git diff --stat main` pasted; no forbidden file changed
- [ ] Status row moved to Review with the branch name

## 9. Report

Findings first: test tails (before/after), `git diff --stat`, the final signature of `surgery.apply`, the list of writes a heal produces on the test fixture, exactly where the gate sits in each
function, what you could not do without a ROM, and anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-state-surgery-directive |
| Base branch | - |
| Base commit | 4e9d4ba6cf138ed5cbb25548ce6221a5911ad65b |

**Status log**
- 2026-11-07 12:56 · robert-claude-laptop · none → Draft — Claude 2026-11-07: save-state editing v1 (surgery.py + state_edit CLI + synthetic gate)
- 2026-11-07 12:57 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; lint_override candidate: dispatch-path-missing on new surgery.py/test_surgery.py and gitignored kb/ + runs/ evidence paths (greenfield); statelog.py cited conditionally
- 2026-11-07 13:03 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing on greenfield files (src/pokeagent/surgery.py, tests/test_surgery.py, src/pokeagent/statelog.py from the sibling directive) and gitignored evidence paths (kb/rom_tables.json, runs/checkpoints/*.fp.json); known false positive
- 2026-11-07 13:03 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-state-surgery-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6VJWPNNBEW8JP4PNY8DARJ1
<!-- queue:end -->
