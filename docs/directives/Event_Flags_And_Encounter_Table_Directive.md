# Trailswarm: goals prefer the game's own story-progress flags, and the current map's wild-encounter table is read live

**Size:** M. **Assignee:** devin.

**Depends on:** `Party_View_Migration_Constants_Directive.md` (In progress) AND `Party_View_Migration_Lead_Directive.md` (Queued) merged first. They edit `src/pokeagent/goals.py`, `campaign.py`, `press_track.py`, `ram_event_kinds.py` and `ram_symbols.py`, and this directive edits `goals.py` and adds constants to `ram_symbols.py`; build on top of both. For the encounter hook, `Level_Banded_Grind_Directive.md` (Queued, not built) lands FIRST: it creates `src/pokeagent/grind/solo_viable.py` with `encounter_mix(kb, map_id)`, and this directive only adds one optional parameter to it (4.3). If `grind/solo_viable.py` is missing from your worktree, build Part A and the live reader of Part B, SKIP the hook, say so in the PR description, and do not create `solo_viable.py` or `encounter_mix` yourself (that is the double-build to avoid). `RAM_Trust_Tiers_And_Discovery_Directive.md` (sibling) owns every edit to `ram_map.json`, including the `wGrassRate`/`wGrassMons` caveat rows; this directive does not touch `ram_map.json` and does not wait for it.

**Read first (all in the worktree; if one is missing, stop and say so in the PR description; do not search):** `src/pokeagent/goals.py` (136 lines), `src/pokeagent/campaign.py` (lines 89-130), `src/pokeagent/ramworld.py` (lines 20-30, 112-130), `src/pokeagent/knowledge/encounters.py`, `src/pokeagent/magikarp.py` (`magikarp_goal_settled`), `src/pokeagent/ram_symbols.py`, `tests/test_campaign.py`, `tests/rom/rom_helpers.py`, `tests/rom/conftest.py`.

## 1. Why this exists

Robert, 2026-11-12: auto-assume the known pokered addresses; he approved adopting the story-progress flags (`wEventFlags`) and the wild-encounter table (`wGrassRate`/`wGrassMons`). Both addresses are already in `ram_map.json` as verified rows:

```
{"name": "wEventFlags", "addr": "0xD747", "size": 320, "encoding": "bitmask", "region": "event_flags", "verified": true, ..., "note": "story flags d747-d886; one-time triggers flip bits here", "evidence": "event bits grow with progress: first_pokemon 4 < to_route1 6 < beat_brock 15"}
{"name": "wGrassRate", "addr": "0xD887", "size": 1, ..., "evidence": "Route 1: rate 25, 10 slots of ['PIDGEY', 'RATTATA'] L2-5"}
{"name": "wGrassMons", "addr": "0xD888", "size": 20, "encoding": "bytes", "region": "map", ..., "note": "level,species x10"}
```

pokered.sym (the sym file is gitignored and not in your worktree; these are the real lines, pasted):

```
00:d72a wBeatGymFlags
00:d747 wEventFlags
00:d887 wGrassRate
00:d888 wGrassMons
00:d8a4 wWaterRate        (alias: wEnemyMon1 at 0xD8A4; the water table shares memory with the enemy party, so it is clobbered by trainer battles: OUT OF SCOPE here)
```

`wEventFlags` is 0xD747-0xD886 (320 bytes, 2,560 bits). Bit convention in this repo (`ramworld.event_flag`): event index `n` is bit `n % 8` (LSB first) of byte `0xD747 + n // 8`. Pokered names each bit with an `EVENT_*` constant (an enum in pokered's `constants/event_constants.asm`); **that file is not in this worktree and not in the sym**, so no bit index below comes from it. What the repo does have is MINED bits (`src/pokeagent/data/ram_findings.json`, `flags` section: which bit flipped, in how many runs, and the on-screen text at that moment) and two hand-confirmed ones in `src/pokeagent/data/campaign.json` (`ss_anne_captain` = 0xD803 bit 1, `hm01_cut` = 0xD803 bit 0; both are already `{"flag": {...}}` detectors).

**What already exists (do not rebuild it).** `ramworld.py:20,114-127` has `EVENT_FLAGS = 0xD747`, `EVENT_FLAG_BYTES = 320`, `read_event_flags(emu)`, `event_flag(flags, index)`, `named_event_labels()`. `campaign.py:91-93` `_flag(emu, flag)` and the `"flag"` detector. `explorer/press_track.py:36-44` and `explorer/trainer_ledger.py:29` read the same block (duplicates of the address; leave them). `knowledge/encounters.py` `species_on(map_id, kb)` / `slot_chances()` already serve the encounter table, but from the ROM-drained static table `kb/rom_tables.json` (`wild_by_map`; gitignored, absent in a worktree). What is missing: (a) the goals do not use the flags, (b) there is no live read of the current map's grass table.

**What the goals infer today (the problem).** `goals.py` `check_goals`:

```python
has_parcel = 0x46 in bag_contents(emu)
if has_parcel:
    st["had_parcel"] = True
g = {..., "oaks_parcel": has_parcel or st.get("had_parcel", False),
         "deliver_parcel": st.get("had_parcel", False) and not has_parcel,
         "beat_brock": bool(emu.read(0xD356) & 1),   # wObtainedBadges bit0
         "buy_magikarp": magikarp_goal_settled(emu, st, seen), ...
         "beat_misty": bool(emu.read(0xD356) & 2), ...}
```

`oaks_parcel` and `deliver_parcel` are inferred from the BAG plus a sticky in-memory `had_parcel`: a run started from a state AFTER the parcel (bag empty, `had_parcel` never set) reads `oaks_parcel` False and `deliver_parcel` False until the ladder's `initial_goals` patch-up. `buy_magikarp` is settled by `magikarp_goal_settled` (owned, or no longer possible, or Mt Moon 1F entered). `beat_brock`/`beat_misty` already read `wObtainedBadges` (0xD356, verified) and need nothing.

## 2. Scope (two parts; one PR, in order)

**Part A, story flags.**
1. `src/pokeagent/data/event_flags.json` <!-- new: src/pokeagent/data/event_flags.json -->: the named bits (4.1).
2. `src/pokeagent/knowledge/event_flags.py` <!-- new: src/pokeagent/knowledge/event_flags.py --> (under 250 lines): load the table, `flags_readable(emu)`, `flag_set(emu, name)`, `flag_goals(emu)`.
3. `src/pokeagent/goals.py` (136; at most +12): merge `flag_goals` into `check_goals`.
4. `src/pokeagent/ram_symbols.py`: add the constants in 4.1 only if absent.

**Part B, encounter table.**
5. `src/pokeagent/knowledge/live_encounters.py` <!-- new: src/pokeagent/knowledge/live_encounters.py --> (under 200 lines): `read_grass(emu)`, `compare_to_table(live, kb, map_id)`.
6. `src/pokeagent/grind/solo_viable.py`: ONLY if it exists: one optional keyword on `encounter_mix` (4.3), at most +10 lines. Do not create it.

**Tests.** `tests/test_event_flags.py` <!-- new: tests/test_event_flags.py -->, `tests/test_live_encounters.py` <!-- new: tests/test_live_encounters.py -->, `tests/rom/test_event_flags_rom.py` <!-- new: tests/rom/test_event_flags_rom.py -->, `tests/rom/test_live_encounters_rom.py` <!-- new: tests/rom/test_live_encounters_rom.py -->, plus additions to `tests/test_campaign.py` or a new `tests/test_goals_event_flags.py` <!-- new: tests/test_goals_event_flags.py -->.

## 3. Facts probed on the real ROM (2026-11-12; pasted; Devin has no ROM)

The controller loaded each committed state in `tests/fixtures/rom_states/` (`PyBoyEmulator`, `load_state`, `tick(1)`) and read these. They are the values the ROM tests assert.

```
state                         map   party badges D72A  D74E     D7C6     D74B     wEventFlags set bits   wGrassRate  wWaterRate
bedroom                       0x26  0     0      0     00000000 00000000 00000000 0                      0           0
wild_stale_battle             0x0C  1     0      0     00000000 00000000 10001111 6                      25          0
fainted_lead_overworld        0x36  2     1      1     00000011 00000000 10101111 13                     0           0
trainer_single_mon            0x0E  1     1      1     00000011 00000000 10101111 14                     20          123
six_mons_with_box             0x41  6     1      1     00000011 10000000 10101111 39                     0           0
trainer_second_slot_active    0x03  2     3      3     00000011 10000000 10101111 36                     0           150
```

(D74E, D7C6, D74B are the bytes at those addresses, bit 7 on the left.) `wBeatGymFlags` (0xD72A) equals `wObtainedBadges` (0xD356) in all six states. `wGrassMons` (20 bytes = 10 slots of `level, species-internal-id`) in the two states where `wGrassRate != 0`:

```
wild_stale_battle (Route 1, map 0x0C), rate 25:
  [3,36, 3,165, 3,165, 2,165, 2,36, 3,36, 3,36, 4,165, 4,36, 5,36]       36 = PIDGEY, 165 = RATTATA
trainer_single_mon (Route 3, map 0x0E), rate 20:
  [6,36, 5,5, 7,36, 6,5, 7,5, 8,36, 8,5, 3,100, 5,100, 7,100]            36 = PIDGEY, 5 = SPEAROW, 100 = JIGGLYPUFF
```

In the four states with `wGrassRate == 0` `wGrassMons` still holds the previous map's slots (stale), e.g. `fainted_lead_overworld` (Pewter Gym): `[3,165, 3,36, 4,36, 4,165, 5,36, 3,112, 2,165, 5,165, 4,112, 5,112]`. **A zero rate means "this map has no grass": ignore the slots.** `wWaterRate` reads nonzero (123, 150) in states with no water: stale, and the table is clobbered by trainer battles: do not use water.

Mined candidate bits (from `ram_findings.json` `flags`; "runs" = distinct explorer runs that saw the bit flip; text is what was on screen at the flip):

```
0xD74E bit 1  set   34 runs   [item/gift] Viridian Mart (2,5): "BCN got OAK PARCEL!"
0xD7C6 bit 7  set    3 runs   Mt Moon Pokecenter (10,5): garbled price text (the mined text is "?5671"; the place is where the Magikarp salesman stands)
0xD803 bit 0  set    (campaign.json hm01_cut: hand-confirmed)       "got HM01"
0xD803 bit 1  set    (campaign.json ss_anne_captain: hand-confirmed)
```

The state probe agrees with both candidates: `D74E` bit 1 is clear in `bedroom` and `wild_stale_battle` (Route 1, before the Viridian Mart) and set in the four later states; `D7C6` bit 7 is clear in `bedroom`, `wild_stale_battle`, `fainted_lead_overworld` (Pewter), `trainer_single_mon` (Route 3, before Mt Moon) and set in `six_mons_with_box` and `trainer_second_slot_active` (Cerulean; past Mt Moon). That is consistent with "got Oak's parcel" and "bought the Magikarp", not proof; the table (4.1) records exactly that status.

## 4. The work

### 4.1 Event table and reader (Part A)

`data/event_flags.json`, an object keyed by a short name; every entry has `addr` (hex string), `bit` (0-7, LSB first), `goal` (a goal id from `data/campaign.json`, or `null`), `status`, `evidence`:

```json
{
  "version": 1,
  "flags": {
    "got_oaks_parcel": {"addr": "0xD74E", "bit": 1, "goal": "oaks_parcel", "status": "mined",
      "evidence": "ram_findings.json flags: 34 runs, 'got OAK PARCEL!' at Viridian Mart (2,5); ROM states 2026-11-12: clear in bedroom and wild_stale_battle, set in the other four"},
    "bought_magikarp": {"addr": "0xD7C6", "bit": 7, "goal": "buy_magikarp", "status": "mined", "needs": "magikarp_evidence",
      "evidence": "ram_findings.json flags: 3 runs at Mt Moon Pokecenter (10,5); ROM states 2026-11-12: set in six_mons_with_box and trainer_second_slot_active, clear in the other four"},
    "got_hm01": {"addr": "0xD803", "bit": 0, "goal": null, "status": "confirmed", "evidence": "campaign.json hm01_cut (mined and replay-verified 2026-11-07)"},
    "rubbed_captains_back": {"addr": "0xD803", "bit": 1, "goal": null, "status": "confirmed", "evidence": "campaign.json ss_anne_captain (mined and replay-verified 2026-11-07)"}
  }
}
```

`status` is `mined` (a bit seen to flip at the right moment; used by default, per Robert's "assume, verify over time") or `confirmed` (a ROM test or replay asserts it). The two `confirmed` rows have `goal: null` because the campaign detectors already own them; they are listed so the ROM test pins them. Do not add other rows: a row needs mined evidence or a ROM probe pasted here. Do NOT invent bit indices from memory of `event_constants.asm`.

`knowledge/event_flags.py`:

```python
def flags_readable(emu) -> bool:
    """True when the 320-byte block reads as 320 bytes and is not a blank block in a game that clearly has progress."""
def flag_set(emu, name: str) -> bool | None:
    """True/False for a table entry; None when the block is unreadable or the name is unknown."""
def flag_goals(emu) -> dict[str, bool]:
    """{goal_id: True} for every table entry that has a goal and whose bit is SET. Never contains False."""
```

`flags_readable`: `emu.read_range(0xD747, 320)` returns exactly 320 bytes without raising, and NOT (`wPartyCount` (0xD163) > 0 and all 320 bytes are zero), because a started game with a party always has the starter-flow bits set (`D74B` is `10001111` or more in every state with a party, section 3), so an all-zero block next to a party means the memory is not really there (a blank fake, a bad state). `bedroom` has no party and zero flags and IS readable. Use the constants from `ram_symbols` (`EVENT_FLAGS = 0xD747`, `EVENT_FLAGS_SIZE = 320`, plus `PARTY_COUNT`, which exists); add `EVENT_FLAGS`, `EVENT_FLAGS_SIZE`, `GRASS_RATE = 0xD887`, `GRASS_MONS = 0xD888`, `GRASS_SLOTS = 10` to `ram_symbols.py` if absent, each with its `# wName` comment (one constant per symbol; do not touch the existing duplicates in `ramworld.py`, `press_track.py`, `trainer_ledger.py`, `novelty/features.py`, `ramlab/flags.py`).

**Sticky-goal guard (mined bits).** Achieved goals are sticky (`goals.py` "stays achieved" loop), so one wrong bit could never be undone. Therefore: (a) log goal provenance when a flag sets a goal, as `flag(mined)` or `flag(verified)` by the row's `status` (`confirmed` logs `flag(verified)`), through the same `st` run-state dict check_goals already receives (e.g. `st.setdefault("goal_source", {})[goal] = "flag(mined)"`; no new logging system); (b) `got_oaks_parcel` (34 runs) may set `oaks_parcel` on its own; (c) `bought_magikarp` (0xD7C6 bit 7, only 3 runs) sets `buy_magikarp` only when the bit is set AND existing evidence agrees: a Magikarp species (internal id 133, `ram_symbols.SPECIES_MAGIKARP`) in the party, or the player is on map 0x44 (Mt Moon Pokecenter). Once its row is promoted to `confirmed` the bit alone suffices. Put the corroboration in a per-row field `"needs": "magikarp_evidence"` honoured by `flag_goals(emu)`; rows without it stand alone.

**The rule (stated once, tested).** A SET flag sets its goal True. A CLEAR flag never sets it False: when the bit is clear, or the block is unreadable, or the name is unknown, the goal keeps the value the old inference gave. Reason: a clear bit is exactly what a wrong bit index looks like, so a clear must never override evidence from the bag or the map; and a set bit is the game's own record that cannot be unset. (`oaks_parcel` therefore becomes True for a run started after the parcel, which is the real gap today.)

`goals.check_goals`: after the dict `g` is built and before the "once achieved, stays achieved" loop, `for k, v in event_flags.flag_goals(emu).items(): g[k] = g.get(k, False) or v`. Layering: `goals.py` imports `knowledge` already (`from pokeagent.knowledge import kb as _kbmod`), so no allow-list change; do NOT import `event_flags` from `src/pokeagent/explorer/` (the explorer allow-list in `tests/test_explorer_behaviours.py:263` contains `knowledge` as a package, so a `pokeagent.knowledge.event_flags` import would be legal, but there is no need).

Goals with no flag in the table keep today's inference exactly. The list of goals the controller still has to find a bit for is in section 8 (open questions); do not guess them.

### 4.2 Live encounter table (Part B)

`knowledge/live_encounters.py`:

```python
@dataclass(frozen=True)
class LiveGrass:
    rate: int                          # wGrassRate, 1..255
    slots: tuple[tuple[int, int], ...] # 10 x (level, internal species id), slot order = wGrassMons order

def read_grass(emu) -> LiveGrass | None: ...
def mix(live: LiveGrass, names: dict | None = None) -> list[tuple[str, int, float]]: ...   # [(species name, level, weight)], weights sum to 1
def compare_to_table(live: LiveGrass, kb: dict | None, map_id: int) -> list[str]: ...      # [] when they agree, else one human line per difference
```

`read_grass`: reads `wGrassRate` and the 20 bytes at `wGrassMons`. Returns **None** when the rate is 0 (the stale case above), when any slot has level 0 or > 100 or species 0 or > 190, or when the read raises. It never returns a guess and never falls back to the previous slots. `mix`: weights are `knowledge.encounters.slot_chances()[i]` (51,51,39,25,25,25,13,13,11,3 of 256; slot i's own level, no min/max splitting; rows for the same species and level summed); species names come from `(ROM_KB or {}).get("name_of_internal", {}).get(str(id), f"#{id}")` (the pattern in `adapters/party_panel.py:13`; import `ROM_KB` the way `explorer/behaviours/battle.py` does). `compare_to_table`: `kb` None or no `wild_by_map` row for the map returns `[]` (unknown is not a mismatch); otherwise it compares the live (level, species) slot list with `table(kb, "wild_by_map")[str(map_id)]["grass"]` (rows `[level, "SPECIES"]`) and the live rate with `["grass_rate"]`, and returns one line per differing slot or rate.

### 4.3 The one hook (Part B, only if `grind/solo_viable.py` exists)

`encounter_mix(kb, map_id)` (Level_Banded 4.1) builds the mix from the static `wild_by_map` slots. Add ONE keyword-only parameter `live=None` (a `LiveGrass` or None) and `current_map=None`: when both are given and `map_id == current_map`, the mix comes from the live slots (`live_encounters.mix` logic, same weights and level handling, so the weights still sum to 1); in every other case the function is exactly as the Level_Banded directive wrote it. A map other than the current one can never use the live table (it only describes the map the player stands on); say that in the docstring. If the live read is None (rate 0 or invalid) the static table is used, never an empty mix. Do not change `solo_verdict`, `choose` or the grind call sites; the live value is plumbed in by the grind directive's caller later (note it in the report, do not do it). `grind_episode._try_start` is NOT edited here.

### 4.4 ROM-backed tests (skip without the ROM)

Use the `rom_emu` fixture and `load(emu, name)` from `tests/rom/rom_helpers.py`; a missing state or ROM skips, never fails. Assert the section 3 values:
- `test_event_flags_rom.py`: for each of the six states the `D74E` bit 1 and `D7C6` bit 7 values in the table above through `flag_set(emu, "got_oaks_parcel")` / `flag_set(emu, "bought_magikarp")`; `flag_set(emu, "got_hm01")` is False in all six; `flags_readable` is True in all six; `flag_goals` of `bedroom` is `{}`, of `trainer_second_slot_active` contains `oaks_parcel` and `buy_magikarp`; `wBeatGymFlags` (0xD72A) equals `wObtainedBadges` (0xD356) in all six.
- `test_live_encounters_rom.py`: `read_grass` is None in `bedroom`, `fainted_lead_overworld`, `six_mons_with_box` and `trainer_second_slot_active` (rate 0); in `wild_stale_battle` it equals rate 25 and the Route 1 slot list above; in `trainer_single_mon` rate 20 and the Route 3 list; `mix` weights sum to 1 (to 1e-9) in both; when `kb/rom_tables.json` loads (the gitignored table; skip that assertion if it does not) `compare_to_table` is `[]` for both maps.

### 4.5 Other tests (no ROM; `FakeEmulator`)

`FakeEmulator.press` is a no-op, so any test that needs bytes to flip on a press must subclass a scripted fake (override `press` to write the scripted bytes); do not expect the stock fake to change memory.

`tests/test_event_flags.py`: the table loads and every entry validates (`addr` hex, `bit` 0-7, `status` in `mined`/`confirmed`, non-empty `evidence`, a `goal` that exists in `campaign.goal_ids()` or is null); `flag_set` on a hand-built block (set `0xD74E` to `0b10`, `PARTY_COUNT` to 1) is True, with the bit clear False, unknown name None; an unreadable emulator (a stub whose `read_range` raises) gives `flags_readable` False and `flag_set` None; the blank-block-with-party case is unreadable; `flag_goals` never contains a False value.

`tests/test_goals_event_flags.py`: with the parcel bit set and an empty bag and no `had_parcel`, `check_goals(...)["oaks_parcel"]` is True (the new behaviour); with the bit clear and the parcel in the bag it is still True (inference kept); with the bit clear and nothing else it is False; with the block unreadable the result equals today's. `buy_magikarp`: bit set AND a Magikarp in the party (or map 0x44) gives True even when `magikarp_goal_settled` says False; bit set with neither stays at the inferred value; the provenance string is `flag(mined)`. `deliver_parcel`, `beat_brock`, `beat_misty` are unchanged for every case above (a regression assertion). The existing tests (`tests/test_campaign.py`, `tests/test_goal_order.py`, `tests/test_false_goal_detectors.py`, `tests/test_goals_cerulean.py`, `tests/test_inferred_goals_not_recorded.py`) pass UNMODIFIED (expected: their `FakeEmulator`s set no flag bytes, so a flag is never set and the blank-block rule routes any with a party to inference; if one fails, stop and name it).

`tests/test_live_encounters.py`: rate 0 with stale slots -> None; a slot with level 0 -> None; species 0 -> None; a valid Route 1 table -> the exact slot list and rate; `mix` weights sum to 1 and a repeated (species, level) pair is summed; `compare_to_table` with a matching synthetic `wild_by_map` row is `[]`, with one level changed returns exactly one line, with `kb=None` returns `[]`. If `solo_viable.py` exists: `encounter_mix(kb, 0x0C, live=LiveGrass(...), current_map=0x0C)` uses the live slots, with `current_map=0x0D` it uses the static row, with the live read None it uses the static row.

## 5. What NOT to do

- **Never publish ROMs. No ROM bytes, no large dumps in the repo.** The section 3 values are the only data copied from the probe; commit no state, save-state dump or table export. `kb/rom_tables.json` is gitignored: never commit it or paste more of it than a synthetic row in a test.
- No network, no installs, no downloads. Do not look for the pokered repo, `event_constants.asm` or the sym file; they are not here and fetching them is a confirmation that kills the run.
- Do not guess a bit index. A goal with no mined or probed bit in section 3 gets NO table row and keeps its inference (section 8 lists them).
- Do not let a clear bit set a goal False; do not remove the old inference; do not change `deliver_parcel`, `beat_brock`, `beat_misty`, `magikarp_goal_settled`, `campaign.json` or any `{"flag": ...}` detector.
- Do not edit `ram_map.json` (the Trust Tiers directive owns it), `ram_overrides.json`, `explorer/press_track.py`, `explorer/trainer_ledger.py`, `ramworld.py`, `ramlab/`, the grind modules other than the one optional parameter in 4.3, or `grind_episode.py`.
- Do not use the water table; do not read `wGrassMons` when `wGrassRate` is 0; do not create `grind/solo_viable.py`, `encounter_mix` or any xp/viability logic (Level_Banded owns it).
- Keep modules small: new modules under 250 lines; no existing file over 600; `goals.py` at most +12 lines.
- Keep the layering allow-list rule: `tests/test_layers.py` and `tests/test_explorer_behaviours.py::test_explorer_package_layering_and_size` stay green; do not add to the explorer allow-list; new code goes under `knowledge/`.
- Use `uv run` only; never bare `python`. Python is 3.12.
- Do not run the emulator or look for a ROM: none exists here; the ROM-backed tests must SKIP cleanly.
- No scratch or debug files outside `.devin-scratch/`; deleting is denied in the sandbox. Do not change a test's expected value to make it pass; stop and say which test.

## 6. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x` (confirmed `Python 3.12.12` on this branch, 2026-11-12).

Baseline on origin/main 7bda1a9, real output (2026-11-12), before any change:

```
uv run pytest -q -p no:cacheprovider tests/test_campaign.py tests/test_goal_order.py tests/test_false_goal_detectors.py tests/test_goals_cerulean.py tests/test_inferred_goals_not_recorded.py tests/test_trainer_ledger.py tests/test_layers.py tests/test_explorer_behaviours.py tests/test_grind_points.py tests/test_grind_episode.py tests/test_ram_map.py tests/rom
122 passed, 8 skipped, 1 warning in 2.21s
```

Re-measured by the controller on the current origin/main (after more merges): `126 passed, 8 skipped`. Use that as the baseline figure; still re-measure on your own base.

```
```

Re-measure it on your base commit first (the two Migration directives and Level_Banded add tests), then after the work run the same command with `tests/test_event_flags.py tests/test_goals_event_flags.py tests/test_live_encounters.py` appended (and `tests/test_solo_viable.py` if it exists). Expected: baseline plus the new tests passed, zero failed, the 8 baseline skips plus the new ROM-test skips and nothing else.

Use the built-in Grep tool (not a shell command) for the regex `0xD747|0xD887|0xD888` over `src/`, ignoring `src/pokeagent/data`.
Expected: the existing hits (`ramworld.py`, `press_track.py`, `trainer_ledger.py`, `novelty/features.py`, `ramlab/flags.py`, comments) plus `ram_symbols.py` only; no new literal in `goals.py`, `event_flags.py` or `live_encounters.py` (they import the constants).

```
git status --short
```
Expected: only the files named in section 2 (and `ram_symbols.py` if a constant was missing).

## 7. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here; if something expected is missing, stop and write that in the PR description.
- Use `uv run` and Python 3.12 only. Do not use bare `python`.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file, and do not write a `## Queue` block.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- If a tool call is genuinely blocked, stop and write why in the PR description rather than trying another way around it.

**Completion criteria** (checkable):
- [ ] A set `got_oaks_parcel` bit makes `oaks_parcel` True with an empty bag and no `had_parcel`; a clear bit, an unreadable block and a blank block next to a party all leave today's value. <!-- test: tests/test_goals_event_flags.py -->
- [ ] A set `bought_magikarp` bit makes `buy_magikarp` True. <!-- test: tests/test_goals_event_flags.py -->
- [ ] `deliver_parcel`, `beat_brock`, `beat_misty` and every existing goal test unchanged. <!-- test: tests/test_campaign.py -->
- [ ] `read_grass` returns None at rate 0 and on invalid slots; exact slots otherwise; `mix` sums to 1. <!-- test: tests/test_live_encounters.py -->
- [ ] The hook exists only if `grind/solo_viable.py` exists, adds one keyword, and falls back to the static table. <!-- test: tests/test_live_encounters.py -->
- [ ] ROM tests exist, assert the section 3 values, and skip cleanly. <!-- test: tests/rom/test_event_flags_rom.py -->
- [ ] No ROM data, no `ram_map.json` edit, layering and size tests green, `goals.py` +12 lines at most.

## 8. Report

Findings first: which goals now read a flag, the new tests, whether the hook was built or skipped (and why), the re-measured baseline, then the tails of the before/after pytest commands, `git status --short`, line counts of `goals.py` and the new modules. State plainly that no ROM was available and which tests skipped.

**Open questions for the controller (do not answer them by guessing; each needs a bit probe on the laptop with the ROM, using `tools/ram_discover.py` mining or a state diff, then a new row in `event_flags.json`):**
1. `deliver_parcel`: the bit set when Oak receives the parcel (pokered `EVENT_OAK_GOT_PARCEL`). No mined bit exists; `deliver_parcel` stays inferred, and still breaks for a run started after delivery.
2. Pokedex received from Oak (the step after delivery); no goal uses it yet.
3. Brock and Misty beaten as event bits (`EVENT_BEAT_BROCK`, `EVENT_BEAT_MISTY`): `wObtainedBadges` already answers both and `wBeatGymFlags` (0xD72A) equals it in all six states, so no row is added; confirm whether any goal needs the event bit instead.
4. Whether the two `mined` rows should be promoted to `confirmed`: needs a replay-verified flip (`tools/ram_discover.py verify`) or a state taken just before and just after the Viridian Mart pickup and the Mt Moon purchase.
5. The Trust Tiers directive's `caveat` rows for `wGrassRate`/`wGrassMons` are the same fact as the zero-rate rule here; confirm they landed.

## Required from User

Nothing for the build. After merge, Claude runs `tests/rom/test_event_flags_rom.py` and `tests/rom/test_live_encounters_rom.py` on the laptop with the ROM, then works the open questions.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.
- Never publish, commit or print a ROM or ROM-derived dump.

## Sandbox needs

- Read(src/pokeagent/data/ram_findings.json)
- Read(src/pokeagent/data/campaign.json)
- Read(src/pokeagent/ram_symbols.py)
- Read(tests/rom/rom_helpers.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git status)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-12 15:56 · robert-claude-laptop · none → Queued — Approve after Party_View_Migration_Constants (#213), _Lead and Level_Banded_Grind merge
<!-- queue:end -->
