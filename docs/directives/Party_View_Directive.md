# Trailswarm: one typed party/battle view and one constant per RAM symbol, so a fainted lead or a stale wBattleMon can no longer feed the agent wrong HP and level

**Size:** M. **Assignee:** devin.

**Depends on:** none.

**Follow-up:** `Party_View_Migration_Constants_Directive.md` (single constants, species gating) and then `Party_View_Migration_Lead_Directive.md` (lead/fighter readers) move the remaining direct RAM readers onto this view. Both depend on this one; do not start them here.

## 1. Why this exists

A read-only audit of the party and battle RAM reads on 2026-11-12, re-verified against `origin/main` (3f73696) before this was written. Every address below matches `pokered.sym`. The problems are about trust and structure, not addresses.

**(a) `wPlayerMonNumber` 0xCC2F is stale outside a fight.** `src/pokeagent/data/ram_map.json` has it `"verified": false`. `ramstructs.active_slot` already cross-checks it against wBattleMon's species, and `item_use.py:84` reads it raw (migration directive).

**(b) `wBattleMon` is half-filled at battle start.** Measured on a wild-battle state (`wIsInBattle` = 1, one Squirtle-line party member L6 21/21): `wBattleMonSpecies` = 0 while `wBattleMonHP` = 15, level = 6, max = 21. The species is the field that says "loaded"; HP and level are left over from earlier. Readers that take HP or level without checking species: `bring_out.py:24` (`BATTLER_HP = 0xD015`, read at `forced_faint_prompt`), `already_out.py:41`, `perceive.py:118` (`battle_view`), `press.py:58,65`, `adapters/event_feed.py:72-76`, `observations.py:62`. (Audit correction: `battle_moves.py` does not read our HP; it reads wBattleMonPP at 0xD02D and enemy HP at 0xCFE6. The PP read is stale at battle start in the same way.)

**(c) The enemy trainer party block is never read.** `wEnemyPartyCount` 0xD89C, `wEnemyPartySpecies` 0xD89D, `wEnemyMons` 0xD8A4 hold the previous trainer's data in a wild fight (measured: wild-battle state shows count 1, species [153, 255]). No `src/` or `tools/` file reads them. Audit correction: trainer-battle (`wIsInBattle` = 2) states DO exist, untracked under `runs/discoveries/`; none are tracked by git, so this directive stays synthetic and the ROM check is `Party_RAM_State_Tests_Directive.md`.

**(d) Slot 0 is assumed to be the lead everywhere.** When the lead has fainted and the second mon is alive (measured on a Brock-win state: slot 0 Squirtle-line 0/35, slot 1 25/32, `wIsInBattle` 0), `perceive.party_hp` returns (0, 35) and every heal, run and top-up rule acts on a dead lead:

```python
# src/pokeagent/explorer/perceive.py (current)
def party_hp(emu) -> tuple[int, int]:
    if trainee_slot(emu) is not None:  # a Magikarp in training lives in the party: the fighter is not the lead
        _, _, hp, mx = fighter(emu)
        return hp, mx
    hp = (emu.read(0xD16C) << 8) | emu.read(0xD16D)
    mx = (emu.read(0xD18D) << 8) | emu.read(0xD18E)
    return hp, mx
```

```python
# src/pokeagent/magikarp.py (current)
def fighter(emu) -> tuple[int, int, int, int]:
    """(species, level, hp, max_hp) of whoever is doing the fighting: the party lead normally; while a Magikarp is
    in the party, the battle's active mon in a fight, or else the strongest non-Magikarp member."""
    party = read_party(emu)
    if not party:
        return 0, 0, 0, 0
    if not any(p.species == MAGIKARP for p in party):
        p = party[0]
        return p.species, p.level, p.hp, p.max_hp
    if emu.read(IN_BATTLE):
        b = read_battle_mon(emu)
        if b.species:
            return b.species, b.level, b.hp, b.max_hp
    others = [p for p in party if p.species != MAGIKARP] or party
    p = max(others, key=lambda q: (q.hp > 0, q.level, q.hp))
    return p.species, p.level, p.hp, p.max_hp
```

`perceive.lead_level` / `true_lead_level` read 0xD18C (slot 0's level) directly. Callers of party_hp/lead_level/fighter: bandit (hook, points), battle, battle_run, cave_escape, cave_topup, frontier, grind_drill, heal, menu, party_order, plan_goal, team_hunt, par_follow, party_log, item_policies, press_track.

**(e)** `item_use.py:84` reads raw `PLAYER_MON`. **(f) Duplicate constants** (measured with `git grep` on `src tools`, excluding `src/pokeagent/data`): `PARTY_COUNT` 0xD163 is defined in `ramstructs.py:14`, `campaign.py:96`, `bring_out.py:12`, `interaction_types.py:12` (as `A_PARTY_N`), `ram_event_kinds.py:15`, `tools/make_state.py:30`, plus literals in `battle.py`, `party_order.py:35`, `press.py:138`, `goals.py:52`, `ram.py:11`; `MENU_ITEM` 0xCC26 in `bring_out.py`, `item_use.py:21`, `party_menu.py:13`, `ramworld.py:19`; `wIsInBattle` 0xD057 as `IN_BATTLE` / `BATTLE_FLAG` / `A_BATTLE` in `adapters/event_feed.py:12`, `explorer/interaction_gate.py:12`, `explorer/interaction_types.py:12`, `explorer/ram_event_kinds.py:15`, `legs/states.py:18`, `magikarp.py:21`, `explorer/perceive.py:15`, `ram.py:12`, plus literals in about 20 more files; `PLAYER_MON` 0xCC2F in `ramstructs.py:176` and `item_use.py:21`.

**(g) Never read by any code:** `wPartyGainExpFlags` 0xD058, `wPartyFoughtCurrentEnemyFlags` 0xCCF5, `wBoxCount` 0xDA80 / `wBoxMons` 0xDA96 / `wBoxMonOT` 0xDD2A / `wBoxMonNicks` 0xDE06, `wWhichPokemon` 0xCF92, `wPartyMenuTypeOrMessageID` 0xD07D, `wEnemyMonPartyPos` 0xCFE8. `ram_map.json` has 2,792 entries, 107 verified.

The fix is one typed, gated view read once per frame, and one constant per symbol.

### Ground-truth symbols (pasted: `.devin-scratch/pokered.sym` is gitignored and not in your worktree)

Format `bank:addr name` (WRAM bank 00, so the address is the 16-bit value):

```
00:cc26 wCurrentMenuItem
00:cc2f wPlayerMonNumber
00:ccf5 wPartyFoughtCurrentEnemyFlags
00:cf92 wWhichPokemon
00:cfe5 wEnemyMon
00:cfe5 wEnemyMonSpecies
00:cfe6 wEnemyMonHP
00:cfe8 wEnemyMonPartyPos
00:cfe9 wEnemyMonStatus
00:cfed wEnemyMonMoves
00:cff1 wEnemyMonDVs
00:cff3 wEnemyMonLevel
00:cff4 wEnemyMonMaxHP
00:cffe wEnemyMonPP
00:d014 wBattleMon
00:d014 wBattleMonSpecies
00:d015 wBattleMonHP
00:d018 wBattleMonStatus
00:d01c wBattleMonMoves
00:d020 wBattleMonDVs
00:d022 wBattleMonLevel
00:d023 wBattleMonMaxHP
00:d02d wBattleMonPP
00:d031 wTrainerClass
00:d057 wIsInBattle
00:d058 wPartyGainExpFlags
00:d05d wTrainerNo
00:d163 wPartyCount
00:d164 wPartySpecies
00:d16b wPartyMon1
00:d16b wPartyMon1Species
00:d16c wPartyMon1HP
00:d16f wPartyMon1Status
00:d173 wPartyMon1Moves
00:d177 wPartyMon1OTID
00:d186 wPartyMon1DVs
00:d188 wPartyMon1PP
00:d18c wPartyMon1Level
00:d18d wPartyMon1MaxHP
00:d273 wPartyMonOT
00:d2b5 wPartyMonNicks
00:d89c wEnemyPartyCount
00:d89d wEnemyPartySpecies
00:d8a4 wEnemyMons
00:d8a5 wEnemyMon1HP
00:d8c5 wEnemyMon1Level
00:d8c6 wEnemyMon1MaxHP
00:d8d0 wEnemyMon2
00:da80 wBoxCount
00:da81 wBoxSpecies
00:da96 wBoxMons
00:dd2a wBoxMonOT
00:de06 wBoxMonNicks
```

Struct strides (from the sym and `ramstructs.py`): party struct 44 bytes (`wPartyMon1` 0xD16B, next 0xD197), enemy-party struct 44 (`wEnemyMon2` - `wEnemyMons` = 0x2C), box struct 33 (0xDAB7 - 0xDA96 = 0x21), names 11 bytes, `wBattleMon`/`wEnemyMon` 29 bytes. In a wild fight a byte-0 species of an `wEnemyMons` slot is not reliable (measured 0 in some stale blocks); trust `wEnemyPartySpecies` for species and `wEnemyPartyCount` for the count.

Gen 1 facts the code relies on: wIsInBattle is 0 overworld, 1 wild, 2 trainer (-1 = lost link; treat anything not in {0,1,2} as 0). Internal species id 133 = MAGIKARP, 0 = empty. Multi-byte values are big-endian. wPartyGainExpFlags and wPartyFoughtCurrentEnemyFlags are bitmasks, bit n = party slot n.

### How the existing per-frame memo works (pasted from `src/pokeagent/ramstructs.py`; reuse it, do not write a second one)

```python
_PARTY_MEMO: dict = {}  # id(emu) -> (emu, key, {"count": int, "party": [PartyMon]})
_PARTY_MEMO_CAP = 8     # a live run shares one emulator; the test suite makes thousands - bound it

def _party_key(emu) -> tuple | None:
    """(frames, write-revision) a party read stays valid for: a press ticks frames forward and a
    RAM write or state load bumps ``_ram_rev``, so either change forces a re-read. An emulator with
    no frames counter (a stub or mock) bypasses the memo entirely."""
    try:
        return (int(emu.frames), int(getattr(emu, "_ram_rev", 0)))
    except (TypeError, ValueError, AttributeError):
        return None

def _memoized(emu, kind: str, read):
    key = _party_key(emu)
    if key is None:
        return read()
    ent = _PARTY_MEMO.get(id(emu))
    if ent is None or ent[0] is not emu or ent[1] != key:
        if len(_PARTY_MEMO) >= _PARTY_MEMO_CAP:
            _PARTY_MEMO.clear()
        ent = _PARTY_MEMO[id(emu)] = (emu, key, {})
    vals = ent[2]
    if kind not in vals:
        vals[kind] = read()
    return vals[kind]
```

`FakeEmulator` (in `src/pokeagent/emulator.py`) has `memory` (a dict addr -> byte; missing reads 0), `frames`, `_ram_rev`, `set(addr, value)`, `read`, `read_range`. A test builds one as `FakeEmulator({0xD163: 2, ...})`. Writing through `emu.set(...)` bumps `_ram_rev`, which invalidates the memo. The existing helper in `tests/test_magikarp.py` shows the byte layout (party mon i at `0xD16B + 44*i`: species +0, HP +1/+2, level +33, max HP +34/+35; species list at `0xD164 + i`).

## 2. Scope (one PR, in order)

1. `src/pokeagent/ram_symbols.py` <!-- new: src/pokeagent/ram_symbols.py --> : one constant per symbol above, defined once.
2. `src/pokeagent/party_view.py` <!-- new: src/pokeagent/party_view.py --> : `PartySlot`, `PartyView`, `BattleView`, `read_party_view(emu)`, `read_battle_view(emu)`.
3. Hub rewires (small edits): `ramstructs.py` imports its constants from `ram_symbols` (names stay importable from `ramstructs`); `magikarp.fighter`, `perceive.party_hp`, `perceive.lead_level`, `perceive.true_lead_level` become thin wrappers over `party_view`.
3b. Emergency routing (section 3.3b): `perceive.party_needs_heal` and `perceive.heal_gate_hp` plus explicit edits to the heal/restock/planning callers of `party_hp`, so that changing `party_hp` to the fighter's HP loses no "a member fainted" trigger.
4. Tests (synthetic, no ROM): `tests/test_party_view.py` <!-- new: tests/test_party_view.py -->, `tests/test_ram_symbols.py` <!-- new: tests/test_ram_symbols.py -->.

Size rules: both new modules stay under 250 lines; no file you touch crosses 600.

## 3. The work

### 3.1 `ram_symbols.py`

Plain module constants, no logic, each with a one-line comment naming the symbol. Names: `PARTY_COUNT`, `PARTY_SPECIES`, `PARTY_MON1`, `PARTY_MON_SIZE`, `MAX_PARTY`, `PARTY_MON_OT`, `PARTY_MON_NICKS`, `NAME_SIZE`, `BATTLE_MON`, `ENEMY_MON`, `BATTLE_STRUCT_SIZE`, `BATTLE_MON_PP`, `ENEMY_MON_PP`, `IS_IN_BATTLE`, `PLAYER_MON_NUMBER`, `ENEMY_MON_PARTY_POS`, `PARTY_GAIN_EXP_FLAGS`, `PARTY_FOUGHT_ENEMY_FLAGS`, `ENEMY_PARTY_COUNT`, `ENEMY_PARTY_SPECIES`, `ENEMY_MONS`, `ENEMY_MON_SIZE` (44), `BOX_COUNT_ADDR`, `BOX_SPECIES`, `BOX_MONS`, `BOX_MON_SIZE` (33), `BOX_MON_OT`, `BOX_MON_NICKS`, `MENU_ITEM` (wCurrentMenuItem), `TRAINER_CLASS`, `TRAINER_NO`, `SPECIES_MAGIKARP = 133`. Do NOT touch `BAG_COUNT, BOX_COUNT = 0xD31D, 0xD53A` in `ramstructs.py`: that `BOX_COUNT` is the PC item list, a different thing from wBoxCount; keep the name `BOX_COUNT_ADDR` for 0xDA80 so the two never collide.

`ramstructs.py` keeps exporting `PARTY_MON1`, `PARTY_COUNT`, `PARTY_MON_SIZE`, `MAX_PARTY`, `BATTLE_MON`, `ENEMY_MON`, `BATTLE_STRUCT_SIZE`, `PLAYER_MON` (as an alias of `PLAYER_MON_NUMBER`) by importing them from `ram_symbols`, so no importer elsewhere changes. `magikarp.py` sets `MAGIKARP = SPECIES_MAGIKARP` and `IN_BATTLE = IS_IN_BATTLE` the same way.

`tests/test_ram_symbols.py`: every constant equals the pasted hex above (a table of name -> expected address, comparing against the pasted values, not recomputed); each module-level name in `ram_symbols` is unique in value only where the symbol is unique (do not assert uniqueness across symbols: `wPartyMon1` and `wPartyMon1Species` legitimately share 0xD16B); `PARTY_MON_SIZE`, `ENEMY_MON_SIZE`, `BOX_MON_SIZE` are 44, 44, 33.

### 3.2 `party_view.py`

```python
@dataclass(frozen=True)
class PartySlot:
    index: int
    species: int
    level: int
    hp: int
    max_hp: int
    status: int
    moves: tuple[int, int, int, int]
    pp: tuple[int, int, int, int]
    ot_id: int
    dv_word: int           # raw 2-byte DVs, as ramstructs.PartyMon.dv_word
    nickname: bytes        # 11 raw bytes from wPartyMonNicks + 11*index
    @property
    def fainted(self) -> bool: ...   # hp <= 0 (an empty slot, species 0, is also fainted)

@dataclass(frozen=True)
class PartyView:
    slots: tuple[PartySlot, ...]
    count: int                         # min(wPartyCount, 6)
    in_battle: int                     # 0, 1 or 2 (normalised)
    active_slot: int | None            # VERIFIED; None when unverifiable
    @property
    def lead(self) -> PartySlot | None
    def fighter(self) -> PartySlot | None
    @property
    def fainted_slots(self) -> tuple[int, ...]   # indexes of OCCUPIED slots (species != 0) with hp <= 0
    @property
    def any_fainted(self) -> bool                # bool(fainted_slots)
```

Build `slots` from `ramstructs.read_party(emu)` (that read is already memoized per frame) plus one `emu.read_range` for the nicknames, memoized under a new kind through `ramstructs._memoized`. Do not add a second memo dict. Do not decode party bytes a second way.

**`active_slot` (verified).** `None` unless `in_battle` is 1 or 2 AND `wBattleMonSpecies` is non-zero. Otherwise: `slot = wPlayerMonNumber`; return `slot` if `slot < count` and that slot's species equals `wBattleMonSpecies`; else if exactly one party slot has that species return its index; else `None`. This is the existing `ramstructs.active_slot` rule plus the `in_battle` gate; leave `ramstructs.active_slot` itself unchanged (intervene code and its tests depend on it).

**`lead`.** Out of battle (`in_battle == 0`): the first slot with `not fainted`; if every slot is fainted, slot 0; `None` for an empty party. In battle: the verified active slot when there is one, else the same first-non-fainted rule.

**`fighter()`.** Whoever is doing the fighting, honouring the Magikarp-trainee rule exactly as `magikarp.fighter` does today, with the lead rule replacing `party[0]`:

1. Empty party: `None`.
2. No slot has species `SPECIES_MAGIKARP`: `lead`.
3. A Magikarp is in the party and `in_battle` is non-zero and the battle mon is loaded (`wBattleMonSpecies` != 0): the slot that is `active_slot` (the live battle values are used by `magikarp.fighter` below).
4. Otherwise: of the non-Magikarp slots (or all slots if there are none), the max by `(hp > 0, level, hp)`.

```python
@dataclass(frozen=True)
class BattleMonView:     # a gated wBattleMon
    species: int; hp: int; max_hp: int; level: int; status: int
    moves: tuple[int, int, int, int]; pp: tuple[int, int, int, int]

@dataclass(frozen=True)
class EnemyMonView:      # wEnemyMon
    species: int; hp: int; max_hp: int; level: int; status: int
    moves: tuple[int, int, int, int]; pp: tuple[int, int, int, int]

@dataclass(frozen=True)
class EnemyPartyMon:
    species: int; hp: int; max_hp: int; level: int

@dataclass(frozen=True)
class BattleView:
    kind: int                                  # 0 none, 1 wild, 2 trainer (anything else -> 0)
    battle_mon: BattleMonView | None           # None unless kind != 0 AND wBattleMonSpecies != 0
    enemy_mon: EnemyMonView | None             # None when kind == 0 or wEnemyMonSpecies == 0
    enemy_party_pos: int | None                # wEnemyMonPartyPos, only when kind == 2
    participants: frozenset[int]               # party slots in wPartyGainExpFlags | wPartyFoughtCurrentEnemyFlags, only slots < count; empty when kind == 0
    enemy_party: tuple[EnemyPartyMon, ...]     # ONLY when kind == 2; () otherwise. Count = min(wEnemyPartyCount, 6); species from wEnemyPartySpecies; hp/max_hp/level from the 44-byte struct at wEnemyMons + 44*i
```

Rules that must hold, each with a test: `battle_mon` is `None` while `wBattleMonSpecies` is 0 even when wBattleMonHP/Level are non-zero (the stale half-filled case); `enemy_party` is `()` in a wild fight even when `wEnemyPartyCount` is non-zero (stale); `participants` ignores bits at or above `count`; `kind` 3 or 0xFF reads as 0.

Reads: `read_party_view(emu)` and `read_battle_view(emu)` are each memoized per frame through `ramstructs._memoized` (new kinds `"party_view"` and `"battle_view"`), so several calls inside one frame do one RAM read. A FakeEmulator with no `frames` attribute bypasses the memo, as today.

### 3.3 Hub rewires

Each of these is a few lines; behaviour for non-fainted-lead parties must not change.

- `magikarp.fighter(emu) -> (species, level, hp, max_hp)`: build from `read_party_view`/`read_battle_view`. Empty party returns `(0, 0, 0, 0)`. Case 3 above returns the live `battle_mon` values (species, level, hp, max_hp), exactly as today; every other case returns the chosen slot's values. Keep the signature and the `IN_BATTLE` name.
- `perceive.party_hp(emu) -> (hp, max_hp)`: the fighter's HP. Delete the hard-coded 0xD16C/0xD18D reads and the `trainee_slot` branch; `fighter()` already covers the trainee case. `(0, 0)` for an empty party.
- `perceive.true_lead_level(emu)`: `fighter(emu)[1]`.
- `perceive.lead_level(emu)`: unchanged logic (trainee-band cap using `magikarp_stats` and `TEAM_GAP`), but the no-trainee branch returns the fighter's level (the lead by the new rule) instead of `emu.read(0xD18C)`.

The fix this buys: a fainted lead with a live second mon now reports the second mon's HP and level to every caller of those four functions.

### 3.3b No emergency may be lost (controller requirement, 2026-11-12)

Before this change a fainted lead made `party_hp` return `(0, max)`, and several callers read that as "go heal / do not fight / do not start something". With the fighter's HP, a healthy second mon hides that. Every such caller must keep its trigger through an explicit signal. Measured list of `party_hp(...)` callers on origin/main (`git grep -n "party_hp(" -- src`), each with what to do:

Out-of-battle heal, restock, field-use and planning decisions: the old trigger was "lead HP low or zero". New trigger: `party_needs_heal(emu, below)` = `view.any_fainted or (fighter max_hp > 0 and fighter hp / max_hp < below)` (define it in `perceive.py`, built on `read_party_view`; `below` is the fraction the caller already uses). Callers:
- `behaviours/restock.py:31` (`hp / mx < 0.5`, "heal first").
- `behaviours/frontier.py:111,140` (`< 0.4`: the `weak` flag and the explore-burst gate).
- `behaviours/menu.py:68` (PC heal option, `hp < mx`): use `any_fainted or hp < mx`.
- `behaviours/plan_goal.py:35`: `hp_now, mx_now` feed `train_route.step` and `_grind_step`, which need numbers, so keep passing the fighter's numbers; where plan_goal only asks "are we hurt" use `party_needs_heal(emu, 1.0)`.
- `behaviours/team_hunt.py:66` (`hp / mx >= TEAM_HUNT_MIN_HP` gate): not ok when `any_fainted`.
- `explorer/grind_episode.py:230` (`hp / mx < MIN_HP_FRACTION` with no potion): add `or any_fainted`.
- `explorer/economy/outside_use.py:77` (field potion): the existing `0 < hp < mx * FIELD_BELOW` already excludes a fainted fighter; keep it on the fighter's HP and add no potion case for a fainted bench mon.
- `behaviours/grind_drill.py:68` (`_episode_step`): `hp, mx` go to `train_route.step(...)`, which decides whether to route toward a heal. This is the real gap: with the fighter's HP a fainted slot 0 no longer sends the episode to heal. Pass numbers that preserve the trigger: when `view.any_fainted`, pass `hp = 0` with the fighter's `mx` (the old fainted-lead values), else the fighter's `hp, mx`. Put that as one helper in `perceive.py` (`heal_gate_hp(emu) -> (hp, mx)`) and use it here and in `plan_goal.py:35`/`frontier.py` wherever the numbers are fed to `train_route.step` / `_grind_step`.
- `behaviours/heal.py:16` (the Mom-heal success check): it must verify that EVERY slot was healed, not that the fighter's HP rose. New rule: success when no occupied slot is below its max HP (`all(s.hp == s.max_hp for s in slots if s.species)`); failure (the existing "Mom did not heal us" branch and `mom_failed_until`) when the old condition holds on the fighter (`hp_now <= ctx.mom_talk_hp and hp_now / mx_now < 0.4`) OR `view.any_fainted` is still True after the 6-step wait.
- `behaviours/cave_topup.py:39,57,64-71` (`wants_topup`, the sequence's `hp0` / `mx0`, the log lines and the `led.use(..., hp0, party_hp(...)[0])` before/after): SAFE and left on `party_hp` = the fighter's HP. A top-up potion goes to `fighter_slot` (the same mon whose HP is read), and `wants_topup` needs `0 < hp`, which already excludes a fainted fighter. Listed so nobody changes it.

In-battle decisions: the fighter's HP IS the right signal (the verified active slot, or the lead); a fainted bench mon must not make a healthy fighter look weak. Callers: `behaviours/battle.py:157` (`weak = hp / mx < 0.4`), `behaviours/battle.py:267` (HP at battle end), `behaviours/battle_run.py:33` (`hp / mx >= CATCH_MIN_HP`), `bandit/hook.py:30` (shield `hp / mx < FIGHT_FLOOR`), `bandit/hook.py:70` (context key). All stay on `party_hp` (now the fighter's HP); no edit beyond the hub rewire. When the lead fainted and the second mon is fighting this is the intended correction: they judge the mon that is actually fighting.

Overworld dungeon check, not in battle: `behaviours/cave_escape.py:25` (`0 < hp <= mx * CRITICAL_HP`, rope escape). Harmless (`hp > 0` already excludes a fainted fighter); stays on `party_hp`.

Log-only: `behaviours/procedures.py:72` (a log line). No change.

`status_care` (`behaviours/status_care.py`, `explorer/status_care.py`) does NOT call `party_hp`: it builds one `MonStatus` per party slot from `read_party` (`_rows`), and `decide` considers `living = [m for m in party if m.hp > 0]` and every sick slot, so a fainted slot 0 already reaches it. Do not change it; pin it with a test (below) so it stays that way.

If you find another reader of `party_hp` / lead HP / `fighter()` that compares it with 0 or uses it for a heal, run, blackout or status decision and is not listed (re-run `git grep -n -E "party_hp\(|fighter\(" -- src`), route it by the same rule and list it in the PR description. The direct 0xD16C readers (`goals.py`, `legs/states.py`, `procedures/predicates.py`) belong to `Party_View_Migration_Lead_Directive.md`, which must keep this rule.

### 3.4 Unit tests, `tests/test_party_view.py`

All with `FakeEmulator`; build memory with a helper `mem(mons, *, in_battle=0, battle=None, ...)` that writes the exact byte layout pasted in section 1. At least:

- fainted lead + live second out of battle: `lead.index == 1`; `perceive.party_hp(emu) == (hp1, max1)`; `perceive.lead_level(emu) == level1`; `magikarp.fighter(emu)` reports slot 1.
- every slot fainted: `lead.index == 0`; `party_hp` is `(0, max0)`.
- healthy lead: `lead.index == 0`; `party_hp` equals the old formula (compare against a literal).
- stale `wBattleMon` (species 0, HP 15, level 6, max 21, `wIsInBattle` 1): `read_battle_view(emu).battle_mon is None`; `read_party_view(emu).active_slot is None`; `party_hp` and `fighter` take HP and level from the party, not from 0xD015/0xD022 (set party HP to 21 and assert 21, not 15).
- verified active slot: two-mon party, `wIsInBattle` 1, `wBattleMonSpecies` = slot 1's species, `wPlayerMonNumber` = 1 gives `active_slot == 1`; `wPlayerMonNumber` stale 0 but exactly one slot has the species gives that slot; two slots share the species and the number is wrong gives `None`; `wIsInBattle` 0 with a loaded wBattleMon gives `None` (the out-of-battle gate).
- Magikarp rule: party `[MAGIKARP, mon]` out of battle: `fighter()` is the non-Magikarp mon; in battle with a loaded battle mon: `magikarp.fighter` returns the battle mon's live values; a fainted non-Magikarp with a live one: the live one.
- `BattleView`: kind 2 with `wEnemyPartyCount` 3 and three structs gives three `EnemyPartyMon`; kind 1 with the same bytes gives `enemy_party == ()`; `participants` from both flag bytes; bit above `count` ignored; kind 3 reads 0.
- emergencies kept (3.3b), each with slot 0 fainted (HP 0, max 35) and a healthy slot 1 (HP 32/32): `party_needs_heal(emu, 0.5)` is True and `party_hp` is (32, 32); `PartyView.fainted_slots == (0,)` and `any_fainted` is True; a party with an empty slot or no fainted member gives `any_fainted` False; a healthy party leaves all of them False. Named tests (add each, same FakeEmulator style as the neighbours): `tests/test_economy.py::test_restock_heals_first_when_slot_zero_fainted` (build with the file's `Restock().step` helper near line 135: slot 0 HP 0, slot 1 full, empty-intent state -> `step` returns None and sets no intent, the `hp / mx < 0.5` guard); `tests/test_explorer_behaviours.py::test_frontier_weak_when_slot_zero_fainted` (next to `test_planner_and_frontier_always_apply_and_frontier_presses`: with `explore_burst` > 0 the burst is dropped, and `weak` is True, when slot 0 has fainted); `tests/test_grind_episode.py::test_episode_ends_hurt_with_slot_zero_fainted_and_no_potion` (next to `test_episode_ends_hurt_with_no_potion`: slot 0 fainted, slot 1 full, no potion -> reason `"hurt with no potion"`); `tests/test_grind_episode.py::test_grind_drill_episode_step_gets_heal_gate_hp_when_slot_zero_fainted` (monkeypatch `train_route.step` to record its `hp` argument: 0 with a fainted slot 0, the fighter's HP otherwise); `tests/test_explorer_behaviours.py::test_heal_needs_every_slot_healed` (next to the `mom_talk_step` test at line 138: slot 0 still fainted after the wait -> `mom_failed_until` set; every slot full -> the `healed at Mom` path).
- status_care still triggers: with slot 0 fainted and slot 1 poisoned and low (status byte 0x08), `behaviours.status_care.StatusCare().applies(ctx)` is True and `explorer.status_care.decide(rows, bag, steps_to_heal)` (rows built as `_rows(emu)` does) returns the same `CareDecision` as for a party made of only the poisoned mon; a fainted slot 0 alone still yields the decision `decide` gave before the change (call `decide` directly on hand-built `MonStatus` rows). Model it on `tests/test_status_care_behaviour.py`.
- in-battle: with slot 0 fainted and slot 1 the verified active slot at 25/32, `party_hp` is (25, 32), so `battle.py`'s `weak` stays False; a fainted bench mon with a healthy active fighter does not make `party_hp` zero.
- per-frame memo: count `FakeEmulator.read_range` calls (wrap it) across three `read_party_view` calls with no tick or write: the RAM read count of the first call equals the count after the third; after `emu.tick(1)` the next call reads again.
- `ramstructs.PARTY_COUNT`, `PARTY_MON1`, `PLAYER_MON` and `magikarp.MAGIKARP` are still importable and equal the pasted values.
- circular import guard: `import pokeagent.party_view` in a fresh interpreter-state test (`importlib.import_module` after popping it from `sys.modules`) succeeds; `party_view` imports only `ram_symbols`, `ramstructs` and the standard library.

## 4. What NOT to do

- Do not migrate any caller other than the four hub functions in 3.3, the emergency routing in 3.3b, and the `ramstructs` / `magikarp` constant imports. `bring_out`, `cave_topup.fighter_slot`, `item_policies/view.fighter_slot_of`, `ram_event_kinds`, `interaction_types`, `xitems_battle`, `item_policies/policy.py`, `menu.py`, `item_use.py` and the duplicate-literal sweep are the next directive's.
- Do not change `ramstructs.active_slot` or any existing test's expected value to make something pass; if an existing test fails, stop and say which one in the PR description.
- Do not touch `src/pokeagent/data/ram_map.json` or `ram_names.json` (verification flags are earned by ROM tests, not by this PR).
- Do not run a ROM, an emulator or `tools/`; do not search or glob for a ROM or states; none exist in this worktree.
- Do not touch protected repos (TeleseroAdminSuite2026, DialerListPulse), `agentflow.toml`, or `src/pokeagent/explorer/retalk_veto.py` / `loop_veto.py`.
- Do not add dependencies. Do not add a second memoization mechanism.
- Do not add features beyond section 3: no box reader, no `PartyView` consumers.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x` (3.12.12 on the laptop).

```
uv run pytest -q -p no:cacheprovider tests/test_party_view.py tests/test_ram_symbols.py
```
Expected: all pass, none skipped.

```
uv run pytest -q -p no:cacheprovider tests/test_ramstructs.py tests/test_magikarp.py tests/test_bandit.py tests/test_cave_topup.py tests/test_item_policies.py tests/test_ram_map.py tests/test_anomalies.py tests/test_intervene_macros.py tests/test_switch_matchup.py tests/test_intervene_lease.py
```
Baseline on `origin/main` (measured 2026-11-12): `280 passed, 1 warning in 5.78s`. Expected after your change: 280 passed (these files are unchanged), none failing.

```
uv run pytest -q -p no:cacheprovider
```
Baseline on `origin/main` (measured 2026-11-12): `2499 passed, 41 skipped, 1 warning in 186.93s (0:03:06)`. Expected: the same plus your new tests passed, zero failed, the same 41 skipped. This takes about three minutes; run it once at the end.

```
git grep -n -E "^(PARTY_COUNT|MENU_ITEM|IS_IN_BATTLE|PLAYER_MON_NUMBER|PARTY_GAIN_EXP_FLAGS|ENEMY_PARTY_COUNT|BOX_COUNT_ADDR)\b" -- src
```
Expected: every one of those names defined in `src/pokeagent/ram_symbols.py` and nowhere else (lines in `ramstructs.py` / `magikarp.py` that read `X = Y` aliasing an imported name are fine; a numeric `= 0x...` assignment of these addresses outside `ram_symbols.py` is not, inside the files you touched).

```
git grep -n -E "0xD16C|0xD18C|0xD18D" -- src/pokeagent/explorer/perceive.py src/pokeagent/magikarp.py src/pokeagent/ramstructs.py
```
Expected: no output.

```
git status --short
```
Expected: only the files named in section 2.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here; if something expected is missing, stop and write that in the PR description.
- Use `uv run` and Python 3.12 only. Do not use bare `python`.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file, and do not write a `## Queue` block.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- Free models only where the work touches model configuration (it should not).
- If a tool call is genuinely blocked, stop and write why in the PR description.

## 7. Completion criteria

- [ ] `ram_symbols.py` defines each symbol in section 3.1 once, each equal to the pasted address. <!-- test: tests/test_ram_symbols.py -->
- [ ] A fainted lead with a live second mon reports the second mon's HP, level and fighter slot through `party_hp`, `lead_level` and `fighter`. <!-- test: tests/test_party_view.py -->
- [ ] Every heal/restock/planning caller of `party_hp` in 3.3b still triggers when slot 0 has fainted and slot 1 is healthy, and `status_care` still applies for a fainted slot 0 with a poisoned slot 1. <!-- test: tests/test_party_view.py -->
- [ ] A stale `wBattleMon` (species 0) never feeds `BattleView.battle_mon`, `PartyView.active_slot`, `party_hp` or `fighter`. <!-- test: tests/test_party_view.py -->
- [ ] `BattleView.enemy_party` is populated only when `kind == 2`; participants come from 0xD058 and 0xCCF5. <!-- test: tests/test_party_view.py -->
- [ ] One RAM read per frame for each view (memo test). <!-- test: tests/test_party_view.py -->
- [ ] Full suite: zero failures, same 41 skips as the baseline.
- [ ] Nothing outside section 2 changed; no new file over 250 lines, no touched file over 600.

## 8. Report

Findings first: the 3.3b list (each `party_hp` caller: routed to `party_needs_heal`, or left on the fighter's HP, and why), any deviation from section 3, any existing test that needed attention (should be none), and whether any `fighter()` / `party_hp` behaviour changed for a healthy lead (it must not). Then the tails of the three pytest commands and the output of the two greps. State plainly that no ROM was available and the real-state check is `Party_RAM_State_Tests_Directive.md`, run by the controller. Name the callers left for the two migration directives.

## Required from User

Nothing for the build. After merge, Claude confirms on the laptop that `PartyView` / `BattleView` agree with the field values in `tests/rom/test_party_states.py` (that directive's states) and records the result; Devin has no ROM and does not run that.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(src/pokeagent/ramstructs.py)
- Read(src/pokeagent/magikarp.py)
- Read(src/pokeagent/explorer/perceive.py)
- Read(src/pokeagent/emulator.py)
- Read(tests/test_magikarp.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git grep)
- Exec(git status)
