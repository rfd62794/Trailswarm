"""party_view: one typed read of party/battle RAM - the active slot is verified against wBattleMon,
stale blocks (species 0) are never exposed, and the enemy party is trainer-only."""
from __future__ import annotations

from pokeagent.emulator import FakeEmulator
from pokeagent.magikarp import MAGIKARP, fighter
from pokeagent.explorer.perceive import heal_gate_hp, lead_level, party_hp, party_needs_heal
from pokeagent.party_view import PartyView, read_battle_view, read_party_view

# mons: (species, level, hp, max_hp) or (species, level, hp, max_hp, status)
SP1, SP2 = 0x99, 0x9A


def mem(mons, *, in_battle=0, battle=None, player_mon=0, gain=0, fought=0, enemy=None,
        enemy_party=(), enemy_pos=None) -> dict:
    m = {0xD163: len(mons), 0xD057: in_battle, 0xCC2F: player_mon, 0xD058: gain, 0xCCF5: fought}
    for i, mon in enumerate(mons):
        sp, lvl, hp, mx, status = (*mon, 0)[:5] if len(mon) == 4 else mon
        b = 0xD16B + 44 * i
        m[0xD164 + i] = sp
        m.update({b: sp, b + 1: hp >> 8, b + 2: hp & 255, b + 4: status,
                  b + 33: lvl, b + 34: mx >> 8, b + 35: mx & 255})
    if battle is not None:  # (species, level, hp, max_hp) on wBattleMon
        sp, lvl, hp, mx = battle
        m.update({0xD014: sp, 0xD015: hp >> 8, 0xD016: hp & 255, 0xD022: lvl,
                  0xD023: mx >> 8, 0xD024: mx & 255})
    if enemy is not None:  # (species, level, hp, max_hp) on wEnemyMon
        sp, lvl, hp, mx = enemy
        m.update({0xCFE5: sp, 0xCFE6: hp >> 8, 0xCFE7: hp & 255, 0xCFF3: lvl,
                  0xCFF4: mx >> 8, 0xCFF5: mx & 255})
    if enemy_pos is not None:
        m[0xCFE8] = enemy_pos
    if enemy_party:
        m[0xD89C] = len(enemy_party)
        for i, (sp, lvl, hp, mx) in enumerate(enemy_party):
            m[0xD89D + i] = sp
            b = 0xD8A4 + 44 * i
            m.update({b + 1: hp >> 8, b + 2: hp & 255, b + 33: lvl, b + 34: mx >> 8, b + 35: mx & 255})
    return m


def test_fainted_lead_falls_through_to_the_first_living_slot():
    emu = FakeEmulator(mem([(SP1, 18, 0, 35), (SP2, 14, 25, 32)]))
    view = read_party_view(emu)
    assert view.lead.index == 1 and view.count == 2 and not view.in_battle
    assert view.fainted_slots == (0,) and view.any_fainted
    assert party_hp(emu) == (25, 32) and lead_level(emu) == 14
    assert fighter(emu) == (SP2, 14, 25, 32)
    assert party_needs_heal(emu, 0.5) and heal_gate_hp(emu) == (0, 32)


def test_all_fainted_reports_slot_zero_with_zero_hp():
    emu = FakeEmulator(mem([(SP1, 18, 0, 35), (SP2, 14, 0, 32)]))
    assert read_party_view(emu).lead.index == 0 and party_hp(emu) == (0, 35)


def test_healthy_lead_behaviour_is_unchanged():
    emu = FakeEmulator(mem([(SP1, 7, 21, 35), (SP2, 5, 0, 10)]))
    view = read_party_view(emu)
    assert view.lead.index == 0 and party_hp(emu) == (21, 35) and lead_level(emu) == 7
    assert fighter(emu) == (SP1, 7, 21, 35)
    assert party_needs_heal(emu, 0.5) and heal_gate_hp(emu) == (0, 35)   # the hurt bench mon still gates
    healthy = FakeEmulator(mem([(SP1, 7, 21, 35), (SP2, 5, 9, 10)]))
    assert party_hp(healthy) == (21, 35) and not party_needs_heal(healthy, 0.5)
    assert heal_gate_hp(healthy) == (21, 35)


def test_empty_party_reports_zeroes():
    emu = FakeEmulator({})
    view = read_party_view(emu)
    assert view.slots == () and view.count == 0 and view.lead is None and view.fighter() is None
    assert view.fainted_slots == () and not view.any_fainted
    assert party_hp(emu) == (0, 0) and heal_gate_hp(emu) == (0, 0) and fighter(emu) == (0, 0, 0, 0)
    assert not party_needs_heal(emu, 0.5) and lead_level(emu) == 0


def test_stale_battle_mon_exposes_nothing_and_the_party_data_wins():
    """wBattleMon is stale RAM here: species 0 with a leftover HP/level/max it never earned."""
    emu = FakeEmulator(mem([(SP1, 18, 21, 35)], in_battle=1, battle=(0, 6, 15, 21)))
    view = read_party_view(emu)
    assert view.active_slot is None and view.lead.index == 0
    bv = read_battle_view(emu)
    assert bv.kind == 1 and bv.battle_mon is None and bv.enemy_party == ()
    assert party_hp(emu) == (21, 35) and fighter(emu) == (SP1, 18, 21, 35)


def test_a_verified_active_slot_wins_in_battle_and_uses_battle_numbers():
    """Slot 0 down, slot 1 out: party_hp is the battle's live HP, not any party-slot byte."""
    emu = FakeEmulator(mem([(SP1, 18, 0, 35), (SP2, 14, 30, 32)], in_battle=1,
                           battle=(SP2, 14, 25, 32), player_mon=1))
    view = read_party_view(emu)
    assert view.active_slot == 1 and view.lead.index == 1 and view.any_fainted
    bv = read_battle_view(emu)
    assert bv.battle_mon.species == SP2 and bv.battle_mon.hp == 25 and bv.battle_mon.max_hp == 32
    assert bv.battle_mon.level == 14
    assert party_hp(emu) == (25, 32) and fighter(emu) == (SP2, 14, 25, 32)


def test_active_slot_falls_back_on_a_unique_species_match_only():
    emu = FakeEmulator(mem([(SP1, 5, 9, 10), (SP2, 14, 25, 32)], in_battle=1,
                           battle=(SP2, 14, 25, 32), player_mon=5))  # stale player_mon
    assert read_party_view(emu).active_slot == 1
    dup = FakeEmulator(mem([(SP2, 5, 9, 10), (SP2, 14, 25, 32)], in_battle=1,
                           battle=(SP2, 14, 25, 32), player_mon=5))  # ambiguous: no slot named
    assert read_party_view(dup).active_slot is None
    bad = FakeEmulator(mem([(SP1, 5, 9, 10), (SP2, 14, 25, 32)], in_battle=1,
                           battle=(0x01, 9, 9, 10), player_mon=5))    # battle species in no slot
    assert read_party_view(bad).active_slot is None


def test_magikarp_trainee_in_battle_fights_the_active_battle_mon():
    """A Magikarp in the party + a verified non-Magikarp active mon: the fighter is the battler."""
    emu = FakeEmulator(mem([(MAGIKARP, 5, 9, 9), (SP1, 18, 30, 51)], in_battle=2,
                           battle=(SP1, 18, 30, 51), player_mon=1))
    assert fighter(emu) == (SP1, 18, 30, 51)


def test_magikarp_trainee_out_of_battle_fights_the_strongest_other_member():
    emu = FakeEmulator(mem([(MAGIKARP, 5, 9, 9), (SP1, 18, 30, 51), (SP2, 9, 9, 40)]))
    view = read_party_view(emu)
    assert view.fighter().species == SP1
    assert fighter(emu) == (SP1, 18, 30, 51)
    hurt = FakeEmulator(mem([(MAGIKARP, 5, 9, 9), (SP1, 18, 0, 51), (SP2, 9, 9, 40)]))
    assert fighter(hurt) == (SP2, 9, 9, 40)   # strongest LIVING non-Magikarp wins


def test_wild_battle_ignores_the_stale_enemy_party_block():
    """In a wild fight wEnemyMons is leftover trainer data: never exposed, never read."""
    ep = [(0x55, 12, 30, 30), (0x56, 11, 28, 28)]
    emu = FakeEmulator(mem([(SP1, 18, 30, 51)], in_battle=1, battle=(SP1, 18, 30, 51),
                           enemy=(0x33, 7, 15, 15), enemy_party=ep, enemy_pos=1))
    bv = read_battle_view(emu)
    assert bv.kind == 1 and bv.enemy_party == () and bv.enemy_party_pos is None
    assert bv.enemy_mon.species == 0x33


def test_trainer_battle_decodes_the_enemy_party():
    ep = [(0x55, 12, 30, 30), (0x56, 11, 28, 28), (0x57, 10, 0, 24)]
    emu = FakeEmulator(mem([(SP1, 18, 30, 51)], in_battle=2, battle=(SP1, 18, 30, 51),
                           enemy=(0x56, 11, 28, 28), enemy_party=ep, enemy_pos=1))
    bv = read_battle_view(emu)
    assert bv.kind == 2 and bv.enemy_party_pos == 1
    assert [(m.species, m.level, m.hp, m.max_hp) for m in bv.enemy_party] == ep


def test_participants_is_the_or_of_the_flag_bytes_masked_to_the_party():
    emu = FakeEmulator(mem([(SP1, 5, 9, 10), (SP2, 6, 12, 12)], in_battle=1,
                           battle=(SP1, 5, 9, 10), gain=0b0001, fought=0b0110))
    assert read_battle_view(emu).participants == frozenset({0, 1})   # bit 2 sits at/above the count
    over = FakeEmulator(mem([(SP1, 5, 9, 10)], in_battle=1, battle=(SP1, 5, 9, 10), gain=0b101))
    assert read_battle_view(over).participants == frozenset({0})   # bits at/above the count ignored


def test_unknown_battle_kinds_expose_no_battle_data():
    for kind in (0, 3, 0xFF):
        emu = FakeEmulator(mem([(SP1, 5, 9, 10)], in_battle=kind, battle=(SP1, 5, 9, 10),
                               enemy=(0x33, 7, 15, 15), enemy_party=[(0x55, 12, 30, 30)], gain=1))
        bv = read_battle_view(emu)
        assert bv.kind == 0 and bv.battle_mon is None and bv.enemy_mon is None
        assert bv.enemy_party == () and bv.participants == frozenset() and bv.enemy_party_pos is None
        assert read_party_view(emu).active_slot is None and read_party_view(emu).lead.index == 0


def test_one_ram_read_per_frame_and_invalidation():
    emu = FakeEmulator(mem([(SP1, 5, 9, 10)]))
    calls = []
    orig = emu.read_range
    emu.read_range = lambda a, n: calls.append((a, n)) or orig(a, n)
    read_party_view(emu)
    n1 = len(calls)
    read_party_view(emu), read_party_view(emu)
    assert len(calls) == n1                      # one read total, memoized per frame
    emu.tick(1)
    read_party_view(emu)
    assert len(calls) > n1                       # a new frame re-reads
    emu.set(0xD163, 0)
    assert read_party_view(emu).count == 0       # a RAM write invalidates at once


def test_status_care_still_sees_a_poisoned_slot_behind_a_fainted_lead(tmp_path, monkeypatch):
    """The emergency trigger: slot 0 down + slot 1 poisoned -> the same care a one-mon party gets."""
    from pokeagent.explorer.behaviours import status_care as sc_beh
    from pokeagent.explorer.behaviours.status_care import StatusCare
    from pokeagent.explorer.economy import outside_use
    from pokeagent.explorer.status_care import MonStatus, decide
    from test_status_care_behaviour import _road_to_center, make_ctx, put_mon
    m = {}
    put_mon(m, 0, SP1, 18, 0, 35, status=0)          # fainted lead
    put_mon(m, 1, SP2, 14, 5, 40, status=0x08)       # poisoned and low behind it
    ctx = make_ctx(tmp_path, m)
    monkeypatch.setattr(outside_use, "walk_to_center", lambda c, get=None: (16 * 100, 0, 0x40))
    _road_to_center(ctx)
    b = StatusCare()
    assert b.applies(ctx)
    d = b.step(ctx)
    assert d.button == "DOWN" and d.rule == "heal_walk"
    rows = sc_beh._rows(ctx.emu)
    assert rows[1].kinds == frozenset({"poison"})
    assert decide(rows, {}, 50) == decide([rows[1]], {}, 50)   # the fainted lead changes nothing
    quiet = decide([MonStatus(0, 0, 35, frozenset())], {}, 50)
    assert quiet.action == "none" and "no poisoned" in quiet.why


def test_party_view_imports_only_ram_symbols_ramstructs_and_stdlib():
    """party_view is a leaf: ramstructs + ram_symbols + stdlib only (never magikarp/perceive)."""
    import ast
    import inspect
    import pokeagent.party_view as pv
    tree = ast.parse(inspect.getsource(pv))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    assert {m for m in mods if m.startswith("pokeagent")} <= {"pokeagent", "pokeagent.ramstructs",
                                                             "pokeagent.ram_symbols"}


def test_party_view_reimports_cleanly_without_cycles():
    """A fresh import in this interpreter state must not hit a circular import."""
    import importlib
    import sys
    sys.modules.pop("pokeagent.party_view", None)
    mod = importlib.import_module("pokeagent.party_view")
    assert callable(mod.read_party_view) and callable(mod.read_battle_view)


def test_party_view_fields():
    view = PartyView((), 0, 0, None)
    assert view.count == 0 and view.in_battle == 0 and view.lead is None
