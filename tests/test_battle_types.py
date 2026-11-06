"""Battle types: STAB from the active battler, effect parsing, the type-effect ledger,
generalised damage lessons, enemy threat, and the move rule string."""
from __future__ import annotations

import pytest

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import battle as kbattle
from pokeagent.explorer.behaviours import battle_moves as bms
from pokeagent.explorer.battle_text import battle_events, parse_effect
from pokeagent.explorer.behaviours.battle import BattleView, scan_battle_text
from pokeagent.explorer.behaviours.battle_moves import BattleMoves
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.perceive import battle_view

TM = 0xC3A0
MAP, PX, PY, BATTLE = 0xD35E, 0xD362, 0xD361, 0xD057

# A small cartridge stand-in: ids are the Gen 1 RAM type bytes, keys are ROM move indexes.
FAKE_KB = {
    "moves": {
        "1": {"name": "TACKLE", "power": 35, "type": "NORMAL", "accuracy": 0.95, "pp": 35},
        "4": {"name": "EMBER", "power": 40, "type": "FIRE", "accuracy": 0.9, "pp": 25},
        "7": {"name": "WATER GUN", "power": 40, "type": "WATER", "accuracy": 1.0, "pp": 25},
        "45": {"name": "GROWL", "power": 0, "type": "NORMAL", "accuracy": 1.0, "pp": 40, "effect": 18},
        "82": {"name": "DRAGON RAGE", "power": 1, "type": "DRAGON", "accuracy": 1.0, "pp": 10, "effect": 41},
        "162": {"name": "SUPER FANG", "power": 1, "type": "NORMAL", "accuracy": 0.9, "pp": 10, "effect": 40},
        "13": {"name": "QUICK ATTACK", "power": 40, "type": "NORMAL", "accuracy": 1.0, "pp": 30},
    },
    "type_chart": [
        ["FIRE", "GRASS", 2.0], ["FIRE", "BUG", 2.0], ["FIRE", "ICE", 2.0],
        ["WATER", "FIRE", 2.0], ["WATER", "GROUND", 2.0], ["ELECTRIC", "WATER", 2.0],
        ["NORMAL", "ROCK", 0.5], ["FIGHTING", "NORMAL", 2.0],
    ],
    "name_of_internal": {"25": "PIDGEY", "4": "CHARMANDER"},
    "dex_of_internal": {},
}

GLYPH = {**{c: 0x80 + i for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")},
         **{c: 0xA0 + i for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")},
         **{str(i): 0xF6 + i for i in range(10)},
         ">": 0xED, "/": 0xF3, "-": 0xE3, " ": 0x7F}


def make_ctx(tmp_path, memory=None, **fields) -> ExplorerContext:
    emu = FakeEmulator({MAP: 0x28, PX: 5, PY: 6, **(memory or {})})
    mem = MapMemory(tmp_path / "maps.json")
    return ExplorerContext(emu=emu, mem=mem, opts=ExplorerOptions(), run_dir=tmp_path, stable_frames=10, **fields)


def put_box(ctx, text_rows) -> None:
    """Draw a frame in the tile map with the rows given (full CHARMAP, unlike the tests' A-Z helper)."""
    emu = ctx.emu
    emu.set(TM + 20 * 10, 0x79)
    emu.set(TM + 20 * 10 + 1, 0x7A)
    for r, text in enumerate(text_rows, start=11):
        emu.set(TM + 20 * r, 0x7C)
        emu.set(TM + 20 * r + 19, 0x7C)
        for i, ch in enumerate(text):
            emu.set(TM + 20 * r + 1 + i, GLYPH.get(ch.upper(), 0x7F) if ch != ">" else 0xED)


def test_stab_uses_active_battler_types_not_party_slot(monkeypatch):
    """0xD019/0xD01A (wBattleMon) drive STAB; party slot 1's 0xD170/0xD171 must be ignored."""
    monkeypatch.setattr(kbattle, "ROM_KB", FAKE_KB)
    emu = FakeEmulator({
        0xCFEA: 22, 0xCFEB: 3,          # enemy GRASS/POISON
        0xD019: 20, 0xD01A: 25,         # OUR battler FIRE/ICE
        0xD170: 21, 0xD171: 21,         # party slot 1 WATER/WATER (the old, wrong source)
        0xD01C: 4, 0xD01D: 7, 0xD01E: 1, 0xD01F: 13,   # EMBER, WATER GUN, TACKLE, QUICK ATTACK
        0xD02D: 25, 0xD02E: 25, 0xD02F: 25, 0xD030: 25,
    })
    scores = kbattle.move_scores(emu)
    # EMBER (FIRE): STAB via 0xD019 even though party slot 1 is WATER; FIRE>GRASS 2x, FIRE>POISON 1x
    assert scores["EMBER"][1] == "EMBER x2 FIRE>GRASS/POISON STAB"
    assert scores["EMBER"][0] == pytest.approx(40 * 2 * 1.5 * 0.9)
    # WATER GUN (WATER): party slot says WATER but the battler is FIRE/ICE -> NO STAB; no chart row -> x1
    assert scores["WATER GUN"][1] == "WATER GUN x1 WATER>GRASS/POISON"
    assert scores["WATER GUN"][0] == pytest.approx(40.0)
    assert "STAB" not in scores["TACKLE"][1] and "STAB" not in scores["QUICK ATTACK"][1]


@pytest.mark.parametrize("text,effect,crit", [
    ("It's super effective!", "super", False),
    ("It's not very effective...", "weak", False),
    ("IT'S NOT VERY EFFECTIVE!", "weak", False),
    ("It doesn't affect ENEMY RATTATA!", "none", False),
    ("It doesn?t affect PIDGEY!", "none", False),   # '?' = the unmapped apostrophe byte
    ("It does not affect BULBASAUR...", "none", False),
    ("Critical hit!", None, True),
    ("Enemy RATTATA used QUICK ATTACK!", None, False),
    ("", None, False),
])
def test_parse_effect(text, effect, crit):
    assert parse_effect(text) == {"effect": effect, "crit": crit}


def test_battle_events_orders_sides_and_effects():
    evs = battle_events(
        "A wild RATTATA appeared! Enemy RATTATA used QUICK ATTACK! It's super effective! "
        "CHARMANDER used EMBER! Critical hit! It's not very effective... Enemy RATTATA used TAIL WHIP!")
    assert evs == [
        ("used", "enemy", "QUICK ATTACK"),
        ("effect", "super"),
        ("used", "ours", "EMBER"),
        ("crit",),
        ("effect", "weak"),
        ("used", "enemy", "TAIL WHIP"),
    ]


def test_battle_events_survive_row_wraps_and_ellipses():
    # the text box wraps ~18 chars/row and rows were rejoined with spaces; '...' ends a sentence too
    evs = battle_events("Enemy RATTATA used QUICK ATTACK! It s supereffec tive... Enemy RATTATA used TACKLE!")
    assert evs == [("used", "enemy", "QUICK ATTACK"), ("effect", "super"), ("used", "enemy", "TACKLE")]


def test_type_effect_ledger_counts_and_flags_chart_disagreements(monkeypatch):
    monkeypatch.setattr(kbattle, "ROM_KB", FAKE_KB)
    data = {}
    # FIRE vs GRASS/POISON: chart says FIRE>GRASS 2x, FIRE>POISON unlisted -> x2 -> 'super' agrees
    kbattle.record_type_effect(data, "FIRE", ["GRASS", "POISON"], "super", step=1)
    rec = data["type_effect"]["FIRE>>GRASS/POISON"]
    assert rec["super"] == 1 and rec["n"] == 1 and kbattle.learned_effect(rec) == "super"
    assert "chart_disagreements" not in data
    # an observation the chart did not predict is logged (the drained-table check)
    kbattle.record_type_effect(data, "FIRE", ["GRASS", "POISON"], "weak", step=2)
    assert data["chart_disagreements"] == [
        {"key": "FIRE>>GRASS/POISON", "expected": "super", "observed": "weak", "step": 2}]
    # a chart-agreeing neutral adds no disagreement
    kbattle.record_type_effect(data, "WATER", ["GRASS", "POISON"], "neutral", step=3)
    assert len(data["chart_disagreements"]) == 1
    # unkeyable observations are ignored: no move type, '?' defender, bogus observed value
    kbattle.record_type_effect(data, None, ["GRASS"], "super")
    kbattle.record_type_effect(data, "FIRE", ["?"], "super")
    kbattle.record_type_effect(data, "FIRE", ["GRASS"], "bogus")
    assert data["type_effect"]["FIRE>>GRASS/POISON"]["n"] == 2


def test_observed_damage_species_first_then_type():
    data = {"move_damage": {"7:TACKLE": [8, 12]},
            "damage_by_type": {"TACKLE|GRASS/POISON": [0.25, 0.35]}}
    # the species key wins while it exists
    assert kbattle.observed_damage(data, 7, "TACKLE", "GRASS/POISON", 40) == (1, 10.0)
    # a different species with the same defender types falls back to the type lesson (mean frac x max HP)
    assert kbattle.observed_damage(data, 8, "TACKLE", "GRASS/POISON", 40) == (1, 12.0)
    # nothing known -> untried
    assert kbattle.observed_damage(data, 8, "WATER GUN", "GRASS/POISON", 40) == (0, 0.0)


def test_threat_score_and_record(monkeypatch):
    monkeypatch.setattr(kbattle, "ROM_KB", FAKE_KB)
    emu = FakeEmulator({0xD019: 22, 0xD01A: 22,   # our battler GRASS/GRASS
                         0xCFEA: 20, 0xCFEB: 20})  # enemy FIRE/FIRE
    # enemy EMBER (FIRE, power 40): 2x vs GRASS, enemy STAB (FIRE in its own types) -> 40*2*1.5
    assert kbattle.threat_score(emu, "EMBER") == pytest.approx(120.0)
    # WATER GUN vs GRASS: no chart row -> x1, no STAB -> 40
    assert kbattle.threat_score(emu, "WATER GUN") == pytest.approx(40.0)
    assert kbattle.threat_score(emu, "SPLASH") is None      # unknown move
    monkeypatch.setattr(kbattle, "ROM_KB", None)
    assert kbattle.threat_score(emu, "EMBER") is None       # no cartridge tables at all
    monkeypatch.setattr(kbattle, "ROM_KB", FAKE_KB)
    data = {}
    kbattle.record_threat(data, emu, 25, "EMBER", step=1)
    kbattle.record_threat(data, emu, 25, "QUICK ATTACK", step=2)   # 40 < 120: the worst is kept
    rec = data["threat_by_species"]["25"]
    assert rec["n"] == 2 and rec["move"] == "EMBER" and rec["type"] == "FIRE"
    assert rec["score"] == pytest.approx(120.0)


def test_move_rule_string(monkeypatch):
    monkeypatch.setattr(kbattle, "ROM_KB", FAKE_KB)
    emu = FakeEmulator({0xCFEA: 22, 0xCFEB: 3, 0xD019: 20, 0xD01A: 20})
    assert kbattle.move_rule(emu, "EMBER") == "EMBER x2 FIRE>GRASS/POISON STAB"
    assert kbattle.move_rule(emu, "WATER GUN") == "WATER GUN x1 WATER>GRASS/POISON"
    monkeypatch.setattr(kbattle, "ROM_KB", None)
    assert kbattle.move_rule(emu, "EMBER") == "EMBER"  # no tables: the bare name


def test_scan_battle_text_records_effects_and_threat(tmp_path, monkeypatch):
    monkeypatch.setattr(kbattle, "ROM_KB", FAKE_KB)
    ctx = make_ctx(tmp_path, memory={0xCFE5: 25, 0xCFEA: 22, 0xCFEB: 3, 0xD019: 20, 0xD01A: 20})
    ctx.dialog = ["CHARMANDER used EMBER!", "It's super effective!",
                  "Enemy PIDGEY used QUICK ATTACK!", "It's not very effective..."]
    scan_battle_text(ctx)
    rec = ctx.mem.data["type_effect"]["FIRE>>GRASS/POISON"]
    assert rec["super"] == 1 and rec["n"] == 1 and kbattle.learned_effect(rec) == "super"
    th = ctx.mem.data["threat_by_species"]["25"]
    assert th["move"] == "QUICK ATTACK" and th["type"] == "NORMAL" and th["n"] == 1
    assert th["score"] == pytest.approx(40.0)  # NORMAL 40 vs our FIRE: x1, no enemy STAB
    # the 'not very effective' belonged to the enemy's attack: it is not our ledger's business
    assert set(ctx.mem.data["type_effect"]) == {"FIRE>>GRASS/POISON"}
    # a second scan of the same dialog adds nothing (the mark cursor consumed it)
    scan_battle_text(ctx)
    assert ctx.mem.data["type_effect"]["FIRE>>GRASS/POISON"]["n"] == 1


def test_pending_effect_neutral_and_real_effect_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(kbattle, "ROM_KB", FAKE_KB)
    ctx = make_ctx(tmp_path, memory={0xCFE5: 25, 0xCFEA: 22, 0xCFEB: 3, 0xD019: 20, 0xD01A: 20})
    # a landed hit whose result text never appeared -> neutral when the enemy's next attack starts
    ctx.pending_effect = {"move": "TACKLE", "move_type": "NORMAL", "def_types": ["GRASS", "POISON"], "step": ctx.step}
    ctx.dialog = ["Enemy PIDGEY used QUICK ATTACK!"]
    scan_battle_text(ctx)
    assert ctx.pending_effect is None
    rec = ctx.mem.data["type_effect"]["NORMAL>>GRASS/POISON"]
    assert rec["neutral"] == 1 and rec["n"] == 1
    # a real message for the pending move records it instead of the neutral default
    # (the 'used' line is consumed before the attack resolves; only the result text is new)
    ctx.dialog = ["CHARMANDER used EMBER!"]
    scan_battle_text(ctx)
    ctx.pending_effect = {"move": "EMBER", "move_type": "FIRE", "def_types": ["GRASS", "POISON"], "step": ctx.step}
    ctx.dialog.append("It's super effective!")
    scan_battle_text(ctx)
    rec = ctx.mem.data["type_effect"]["FIRE>>GRASS/POISON"]
    assert rec["super"] == 1 and rec["neutral"] == 0 and ctx.pending_effect is None


def test_battle_view_shows_move_rule_line():
    emu = FakeEmulator({BATTLE: 1})
    assert not any(r.startswith("move") for r in battle_view(emu))
    rows = battle_view(emu, "EMBER x2 FIRE>GRASS/POISON STAB")
    i = rows.index("move  EMBER x2")           # wrapped at spaces to fit the 22-col Sees grid
    assert rows[i + 1].strip().startswith("FIRE>GRASS/POISON") and "STAB" in " ".join(rows[i:i + 3])


def test_move_choose_decision_carries_the_rule_string(tmp_path, monkeypatch):
    monkeypatch.setattr(kbattle, "ROM_KB", FAKE_KB)
    monkeypatch.setattr(bms, "ROM_KB", FAKE_KB)  # battle_moves binds kb.ROM_KB itself for the name lookup
    ctx = make_ctx(tmp_path, memory={
        BATTLE: 1, 0xCFE5: 25, 0xCFE6: 0, 0xCFE7: 20, 0xCFF3: 3, 0xCFF4: 0, 0xCFF5: 30,
        0xCFEA: 22, 0xCFEB: 3, 0xD019: 20, 0xD01A: 20,
        0xD01C: 4, 0xD01D: 7, 0xD01E: 1, 0xD01F: 13,
        0xD02D: 25, 0xD02E: 25, 0xD02F: 25, 0xD030: 25})
    put_box(ctx, ("FIGHT", "TYPE/", "NORMAL", "29/30", "TACKLE", "QUICK ATTACK", ">EMBER", "WATER GUN"))
    ctx.bv = BattleView(kind=1, hp=10, mx=20, species=25, my_sp=4, my_lvl=5, e_lvl=3, cur=">FIGHT")
    ctx.refresh()
    d = BattleMoves().step(ctx)
    assert d.button == "A"
    assert d.rule == "EMBER x2 FIRE>GRASS/POISON STAB"
    assert "PIDGEY" in d.why and "first try" in d.why
    assert ctx.move_tag == "EMBER x2 FIRE>GRASS/POISON STAB"
    pm = ctx.pending_move
    assert pm["move"] == "EMBER" and pm["move_type"] == "FIRE"
    assert pm["def_types"] == ["GRASS", "POISON"] and pm["def_key"] == "GRASS/POISON"
    assert pm["enemy_max"] == 30 and pm["enemy_hp"] == 20


def _hp_drop(ctx, move, **pm):
    ctx.pending_move = {"species": 25, "move": move, "enemy_hp": 20, "enemy_max": 30, "def_key": "GRASS/POISON",
                        "def_types": ["GRASS", "POISON"], "move_type": (kbattle.move_by_name(move) or {}).get("type"),
                        "step": ctx.step, "typed": kbattle.is_typed_attack(move), **pm}
    ctx.emu.set(0xCFE7, 15)  # enemy HP fell 20 -> 15 (poison tick or a hit)
    put_box(ctx, ("FIGHT", "TYPE/", "NORMAL", "29/30", "TACKLE", ">GROWL"))
    ctx.bv = BattleView(kind=1, hp=10, mx=20, species=25, my_sp=4, my_lvl=5, e_lvl=3, cur=">FIGHT")
    ctx.refresh()
    BattleMoves().step(ctx)


@pytest.mark.parametrize("move", ["GROWL", "DRAGON RAGE", "SUPER FANG"])
def test_status_and_fixed_damage_moves_do_not_feed_type_ledgers(tmp_path, monkeypatch, move):
    monkeypatch.setattr(kbattle, "ROM_KB", FAKE_KB)
    monkeypatch.setattr(bms, "ROM_KB", FAKE_KB)
    ctx = make_ctx(tmp_path, memory={BATTLE: 1, 0xCFE5: 25, 0xCFE6: 0, 0xCFF4: 0, 0xCFF5: 30,
                                     0xCFEA: 22, 0xCFEB: 3, 0xD019: 20, 0xD01A: 20,
                                     0xD01C: 45, 0xD01D: 82, 0xD01E: 162, 0xD01F: 1, 0xD02D: 9, 0xD02E: 9, 0xD02F: 9, 0xD030: 9})
    _hp_drop(ctx, move)
    assert ctx.pending_effect is None
    assert "damage_by_type" not in ctx.mem.data


def test_typed_damage_move_still_feeds_ledgers(tmp_path, monkeypatch):
    monkeypatch.setattr(kbattle, "ROM_KB", FAKE_KB)
    monkeypatch.setattr(bms, "ROM_KB", FAKE_KB)
    ctx = make_ctx(tmp_path, memory={BATTLE: 1, 0xCFE5: 25, 0xCFE6: 0, 0xCFF4: 0, 0xCFF5: 30,
                                     0xCFEA: 22, 0xCFEB: 3, 0xD019: 20, 0xD01A: 20,
                                     0xD01C: 4, 0xD01D: 45, 0xD01E: 82, 0xD01F: 1, 0xD02D: 9, 0xD02E: 9, 0xD02F: 9, 0xD030: 9})
    _hp_drop(ctx, "EMBER")
    assert ctx.pending_effect["move"] == "EMBER"
    assert "EMBER|GRASS/POISON" in ctx.mem.data["damage_by_type"]


def test_new_hit_finalizes_unfinished_pending_effect_first(tmp_path, monkeypatch):
    monkeypatch.setattr(kbattle, "ROM_KB", FAKE_KB)
    monkeypatch.setattr(bms, "ROM_KB", FAKE_KB)
    ctx = make_ctx(tmp_path, memory={BATTLE: 1, 0xCFE5: 25, 0xCFE6: 0, 0xCFF4: 0, 0xCFF5: 30,
                                     0xCFEA: 22, 0xCFEB: 3, 0xD019: 20, 0xD01A: 20,
                                     0xD01C: 4, 0xD01D: 45, 0xD01E: 82, 0xD01F: 1, 0xD02D: 9, 0xD02E: 9, 0xD02F: 9, 0xD030: 9})
    ctx.pending_effect = {"move": "TACKLE", "move_type": "NORMAL", "def_types": ["GRASS", "POISON"], "step": 0}
    _hp_drop(ctx, "EMBER")
    assert ctx.mem.data["type_effect"]["NORMAL>>GRASS/POISON"]["neutral"] == 1
    assert ctx.pending_effect["move"] == "EMBER"


def test_repeated_identical_line_after_box_close_is_scanned_again(tmp_path, monkeypatch):
    monkeypatch.setattr(kbattle, "ROM_KB", FAKE_KB)
    ctx = make_ctx(tmp_path, memory={0xCFE5: 25, 0xCFEA: 22, 0xCFEB: 3, 0xD019: 20, 0xD01A: 20})
    ctx.dialog = ["Enemy PIDGEY used QUICK ATTACK!"]
    scan_battle_text(ctx)
    ctx.dialog = ["Enemy PIDGEY used QUICK ATTACK!"]  # press.py replaced the list when the box reopened
    scan_battle_text(ctx)
    assert ctx.mem.data["threat_by_species"]["25"]["n"] == 2


def test_rotated_capped_dialog_is_not_rescanned(tmp_path, monkeypatch):
    monkeypatch.setattr(kbattle, "ROM_KB", FAKE_KB)
    ctx = make_ctx(tmp_path, memory={0xCFE5: 25, 0xCFEA: 22, 0xCFEB: 3, 0xD019: 20, 0xD01A: 20})
    ctx.dialog = ["Enemy PIDGEY used QUICK ATTACK!"] + [f"line {i}" for i in range(11)]
    scan_battle_text(ctx)
    assert ctx.mem.data["threat_by_species"]["25"]["n"] == 1
    ctx.dialog.append("more"); del ctx.dialog[:-12]  # the first entry rotated off, as press.py caps at 12
    scan_battle_text(ctx)
    assert ctx.mem.data["threat_by_species"]["25"]["n"] == 1
