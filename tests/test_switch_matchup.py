"""SwitchOut.matchup_pick: the matchup switch in a trainer battle (synthetic ctx, no ROM/emulator).
"""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.explorer.behaviours import switch_out as so_mod
from pokeagent.explorer.stats import stat_value
from pokeagent.knowledge import team_plan
from pokeagent.knowledge.party import Combatant

SYN = {
    "moves": {"1": {"name": "EMBER", "type": "FIRE", "power": 40, "accuracy": 1.0, "effect": 0, "pp": 25},
              "2": {"name": "VINE WHIP", "type": "GRASS", "power": 45, "accuracy": 1.0, "effect": 0, "pp": 25},
              "3": {"name": "WATER GUN", "type": "WATER", "power": 40, "accuracy": 1.0, "effect": 0, "pp": 25},
              "4": {"name": "TACKLE", "type": "NORMAL", "power": 35, "accuracy": 1.0, "effect": 0, "pp": 35}},
    "type_chart": [["WATER", "FIRE", 2.0], ["GRASS", "WATER", 2.0], ["FIRE", "WATER", 0.5],
                   ["WATER", "GRASS", 0.5]],
    "species_by_dex": {
        "1": {"name": "CHARMELEON", "type1": "FIRE", "type2": "FIRE", "hp": 58, "atk": 64, "def": 58,
              "spd": 80, "spc": 65, "moves1": ["EMBER"]},
        "2": {"name": "ODDISH", "type1": "GRASS", "type2": "POISON", "hp": 45, "atk": 50, "def": 55,
              "spd": 30, "spc": 75, "moves1": ["VINE WHIP"]},
        "3": {"name": "STARMIE", "type1": "WATER", "type2": "PSYCHIC", "hp": 60, "atk": 75, "def": 85,
              "spd": 115, "spc": 100, "moves1": ["WATER GUN"]},
        "4": {"name": "WEEDLE", "type1": "BUG", "type2": "POISON", "hp": 40, "atk": 35, "def": 30,
              "spd": 50, "spc": 20, "moves1": ["TACKLE"]},
    },
    "learnsets": {},
}


def _mon(name, level):
    row = next(r for r in SYN["species_by_dex"].values() if r["name"] == name)
    hp = stat_value(row["hp"], 8, 0, level, hp=True)
    st = tuple(stat_value(row[k], 8, 0, level) for k in ("atk", "def", "spd", "spc"))
    return Combatant(name, level, tuple(dict.fromkeys((row["type1"], row["type2"]))), hp, st,
                     tuple(row["moves1"]), (8,) * 5, (0,) * 5)


def _ctx(team, kind=2, switches=0, active_hp=None):
    emu = SimpleNamespace()  # every emu-touching helper is patched below
    return SimpleNamespace(bv=SimpleNamespace(kind=kind), battle_log={"matchup_switches": switches},
                           battles=3, train_member=None, emu=emu, switch_gave_up=None,
                           _team=team, _active_hp=active_hp)


def _patch(monkeypatch, ctx):
    team = ctx._team
    monkeypatch.setattr(team_plan, "table", lambda kb, k: SYN.get(k, {}))
    monkeypatch.setattr(so_mod, "our_party", lambda emu: team)
    monkeypatch.setattr(so_mod, "_foe", lambda c: _mon("STARMIE", 21))
    monkeypatch.setattr(so_mod, "active_slot", lambda emu: 0)
    hp = [c.hp for c in team]
    if ctx._active_hp is not None:
        hp[0] = ctx._active_hp
    monkeypatch.setattr(so_mod, "read_party", lambda emu: [SimpleNamespace(hp=h) for h in hp])
    monkeypatch.setattr(so_mod, "trainee_slot_for", lambda emu, named: None)


def test_matchup_pick_fires_in_a_trainer_battle(monkeypatch):
    team = [_mon("CHARMELEON", 15), _mon("ODDISH", 16)]
    ctx = _ctx(team)
    _patch(monkeypatch, ctx)
    pick = so_mod.matchup_pick(ctx)
    assert pick is not None and pick[0] == 1          # the Grass answer to Starmie
    assert "thin" in pick[1] or "weak" in pick[1]


def test_matchup_pick_never_in_a_wild_battle(monkeypatch):
    ctx = _ctx([_mon("CHARMELEON", 15), _mon("ODDISH", 16)], kind=1)
    _patch(monkeypatch, ctx)
    assert so_mod.matchup_pick(ctx) is None


def test_matchup_pick_respects_the_per_battle_cap(monkeypatch):
    ctx = _ctx([_mon("CHARMELEON", 15), _mon("ODDISH", 16)], switches=2)
    _patch(monkeypatch, ctx)
    assert so_mod.matchup_pick(ctx) is None  # the third switch is never picked


def test_matchup_pick_none_when_nobody_is_better(monkeypatch):
    ctx = _ctx([_mon("CHARMELEON", 15), _mon("WEEDLE", 9)])
    _patch(monkeypatch, ctx)
    assert so_mod.matchup_pick(ctx) is None


def test_matchup_pick_is_computed_once_per_step(monkeypatch):
    calls = []
    ctx = _ctx([_mon("CHARMELEON", 15), _mon("ODDISH", 16)])
    _patch(monkeypatch, ctx)
    ctx.step = 7
    monkeypatch.setattr(team_plan, "switch_choice", lambda *a, **k: calls.append(1) or 1)
    assert so_mod.matchup_pick(ctx)[0] == 1
    assert so_mod.matchup_pick(ctx)[0] == 1 and calls == [1]   # applies() + step() share the one sim
    ctx.step = 8
    so_mod.matchup_pick(ctx)
    assert calls == [1, 1]                                     # a new step asks again


# --- _matchup_step: the PKMN -> member -> SWITCH press flow, its cap and the battle-record count --------------------

def _step_ctx(tmp_path, monkeypatch):
    """A trainer-battle ctx SwitchOut._matchup_step can walk a menu on (draw_framed battle menu)."""
    from pokeagent.emulator import FakeEmulator
    from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
    from pokeagent.explorer.memory import MapMemory
    from test_magikarp import party_mem
    emu = FakeEmulator({0xD35E: 0x28, 0xD362: 5, 0xD361: 6, 0xD057: 2, 0xD014: 0xB1, 0xCC2F: 0,
                        **party_mem([(0xB1, 18, 51, 51), (0x85, 5, 17, 17)])})   # two members, slot 1 is the target
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(),
                          run_dir=tmp_path, battles=3, stable_frames=10)
    ctx.refresh()
    ctx.battle_log = {"kind": 2}
    monkeypatch.setattr(so_mod, "trainee_slot_for", lambda *a: None)
    monkeypatch.setattr(so_mod, "matchup_pick", lambda c: (1, "thin: foe hits 30x2 vs 20 HP"))
    return ctx


def test_matchup_step_press_flow_cap_and_landed_count(tmp_path, monkeypatch):
    from test_magikarp import draw_framed
    ctx = _step_ctx(tmp_path, monkeypatch)
    draw_framed(ctx.emu, [">FIGHT PKMN", "ITEM RUN"])
    st = team_plan.of(ctx)
    for _ in range(so_mod.MAX_PRESSES):
        d = so_mod.SwitchOut()._matchup_step(ctx)
        assert d.button == "RIGHT" and d.rule.startswith("switch_matchup:")
        assert d.why.endswith(f"(press {st['matchup']['presses']})")
    d = so_mod.SwitchOut()._matchup_step(ctx)                  # one too many: the menus are not what we think
    assert (d.button, d.rule) == ("B", "switch_matchup_failed")
    assert ctx.switch_gave_up == ctx.battles and "matchup" not in st


def test_matchup_step_counts_the_landed_switch_on_the_battle_record(tmp_path, monkeypatch):
    from test_magikarp import draw_framed
    ctx = _step_ctx(tmp_path, monkeypatch)
    draw_framed(ctx.emu, [">FIGHT PKMN", "ITEM RUN"])
    d = so_mod.SwitchOut()._matchup_step(ctx)                  # press 1: RIGHT toward PKMN
    assert d.button == "RIGHT"
    ctx.emu.set(0xD014, 0x85); ctx.emu.set(0xCC2F, 1)          # the swap landed: slot 1 is out now
    assert so_mod.SwitchOut()._matchup_step(ctx) is None
    assert ctx.battle_log["matchup_switches"] == 1
    assert "matchup" not in team_plan.of(ctx)


def test_active_pos_ignores_the_stale_battle_struct_party_byte(tmp_path, monkeypatch):
    """Pewter Gym 2026-11-12: Rattata fainted, the forced switch sent Charmander out, but wBattleMon's party byte stayed 0
    (the fainted Rattata), so the matchup 'switched' Rattata -> Charmander, i.e. into the mon already out, for ~3,000 steps."""
    ctx = _step_ctx(tmp_path, monkeypatch)
    ctx.emu.set(0xD014, 0x85); ctx.emu.set(0xCC2F, 1); ctx.emu.set(0xD017, 0)   # Charmander out, stale byte says slot 0
    assert so_mod.active_pos(ctx) == 1
    team_plan.of(ctx)["matchup"] = {"battle": ctx.battles, "target": 1, "presses": 2, "why": "x", "rule": "switch_matchup: x"}
    assert so_mod.SwitchOut()._matchup_step(ctx) is None        # target already fighting: done, no menu presses
    assert ctx.battle_log["matchup_switches"] == 1


def test_matchup_pick_none_when_the_fighter_has_fainted(monkeypatch):
    ctx = _ctx([_mon("CHARMELEON", 15), _mon("ODDISH", 16)], active_hp=0)
    _patch(monkeypatch, ctx)
    assert so_mod.matchup_pick(ctx) is None                     # the forced list belongs to bring_out
