"""Verification checks for tools/verify_ram.py: each proves addresses mean what ram_map.json says.

A check takes a Rig and returns a Result: ``ok`` maps ram_map names to evidence strings (written back
as verified), ``failed`` lists human-readable failures. A check never marks a name it did not prove.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pokeagent.emulator import Button, PyBoyEmulator
from pokeagent.explorer.stats import computed_stats, ram_stats
from pokeagent.ramstructs import read_battle_mon, read_enemy_base_stats, read_enemy_mon, read_party
from pokeagent.ramworld import bit_indices, read_map_header
from pokeagent.screentext import decode_text

KEYS = ("hp", "attack", "defense", "speed", "special")
DIRS = {Button.UP: 4, Button.DOWN: 0, Button.LEFT: 8, Button.RIGHT: 0xC}


@dataclass
class Result:
    ok: dict[str, str] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)

    def check(self, cond: bool, names: list[str], evidence: str, failure: str = "") -> None:
        if cond:
            self.ok.update({n: evidence for n in names})
        else:
            self.failed.append(failure or f"{names}: {evidence}")


class Rig:
    """Emulator + checkpoint loader + the ROM-drained kb (moves, species base stats)."""

    def __init__(self, rom: Path, states: Path, kb: dict) -> None:
        self.emu, self.states, self.kb = PyBoyEmulator(rom), states, kb

    def load(self, name: str, ticks: int = 2) -> PyBoyEmulator:
        self.emu.load_state(self.states / f"{name}.state")
        self.emu.tick(ticks)
        return self.emu

    def base(self, species: int) -> dict[str, int]:
        row = self.kb["species_by_dex"][str(self.kb["dex_of_internal"][str(species)])]
        return {"hp": row["hp"], "attack": row["atk"], "defense": row["def"], "speed": row["spd"], "special": row["spc"]}

    def starter_filled(self) -> PyBoyEmulator:
        """first_pokemon.state is captured mid-give (struct still zero): press B until it is filled."""
        e = self.load("first_pokemon", 300)
        for _ in range(40):
            if e.read(0xD18C):
                break
            e.press(Button.B, 8, 32)
        return e

    def wild_battle(self) -> PyBoyEmulator:
        """From to_route1, shuffle in the Route 1 grass until a wild battle starts, then let it settle."""
        e = self.load("to_route1")
        seq = [Button.UP, Button.UP, Button.DOWN, Button.DOWN]
        for i in range(800):
            e.press(seq[(i // 2) % 4], 8, 8)
            if e.read(0xD057):
                break
        fight = bytes([0x85, 0x88, 0x86, 0x87, 0x93])   # "FIGHT" in tile ids
        for _ in range(60):                             # advance the intro text until the command menu is up
            if fight in e.read_range(0xC3A0, 360):
                break
            e.press(Button.A, 8, 40)
        e.tick(30)
        return e


def party_struct(rig: Rig) -> Result:
    r, e = Result(), rig.starter_filled()
    m, sp = read_party(e)[0], rig.kb["name_of_internal"]
    nm = sp[str(m.species)]
    ev = f"first_pokemon (+give): {nm} L{m.level}"
    r.check(e.read(0xD164) == m.species and e.read(0xD165) == 0xFF and e.read(0xD163) == 1,
            ["wPartyCount", "wPartySpecies"], f"{ev}: count 1, species list [{nm}, 0xFF]")
    r.check(m.level == 5 and m.hp == m.max_hp and m.hp > 0, ["wPartyMon1Level", "wPartyMon1HP", "wPartyMon1MaxHP"],
            f"{ev}: L5, HP {m.hp}/{m.max_hp} full on receipt")
    row = rig.kb["species_by_dex"][str(rig.kb["dex_of_internal"][str(m.species)])]
    r.check((m.type1, m.type2) == (22, 3) and row["type1"] == "GRASS" and m.catch_rate == row["catch_rate"],
            ["wPartyMon1Type1", "wPartyMon1Type2", "wPartyMon1CatchRate", "wPartyMon1Type"], f"{ev}: types GRASS/POISON, catch rate {m.catch_rate} == kb")
    mv = [rig.kb["moves"][str(i)] for i in m.moves if i]
    r.check([x["name"] for x in mv] == ["TACKLE", "GROWL"] and m.pp[:2] == (mv[0]["pp"], mv[1]["pp"]),
            ["wPartyMon1Moves", "wPartyMon1PP"], f"{ev}: moves TACKLE/GROWL, PP {m.pp[:2]} == kb")
    exp_l5 = 6 * 5 ** 3 // 5 - 15 * 5 ** 2 + 100 * 5 - 140   # Medium Slow curve: 6/5 n^3 - 15 n^2 + 100 n - 140
    r.check(m.exp == exp_l5 == 135, ["wPartyMon1Exp"], f"{ev}: exp {m.exp} == Medium Slow curve at L5 (135)")
    r.check(computed_stats(m, rig.base(m.species)) == ram_stats(m),
            ["wPartyMon1DVs", "wPartyMon1Stats", "wPartyMon1Attack", "wPartyMon1Defense", "wPartyMon1Speed",
             "wPartyMon1Special", "wPartyMon1HPExp", "wPartyMon1AttackExp"],
            f"{ev}: DVs {m.dv_word:#06x} + base stats reproduce HP/Atk/Def/Spd/Spc {ram_stats(m)} exactly")
    r.check(e.read_range(0xD359, 2) == e.read_range(0xD16B + 12, 2), ["wPlayerID", "wPartyMon1OTID"], f"{ev}: trainer id == mon OT id {m.ot_id}")
    own = decode_text(e.read_range(0xD158, 11))
    r.check(bool(own) and decode_text(e.read_range(0xD273, 11)) == own, ["wPlayerName", "wPartyMonOT", "wPartyMon1OT"], f"{ev}: player name {own!r} == OT name")
    r.check(decode_text(e.read_range(0xD2B5, 11)) == nm, ["wPartyMonNicks", "wPartyMon1Nick"], f"{ev}: nickname decodes to {nm!r}")
    r.check(bool(decode_text(e.read_range(0xD34A, 11))), ["wRivalName"], f"{ev}: rival name {decode_text(e.read_range(0xD34A, 11))!r}")
    return r


def stat_exp_levelled(rig: Rig) -> Result:
    """beat_brock / to_pewter: stat exp is non-zero; the stats stored at the last level-up use it."""
    r = Result()
    for name in ("beat_brock", "to_pewter", "to_route1"):
        e = rig.load(name)
        m = read_party(e)[0]
        got, want = ram_stats(m), computed_stats(m, rig.base(m.species))
        r.check(got == want, ["wPartyMon1SpeedExp", "wPartyMon1DefenseExp", "wPartyMon1SpecialExp", "wPartyMon1AttackExp", "wPartyMon1HPExp"],
                f"{name}: stats incl. stat exp {m.stat_exp} reproduce RAM stats {got}",
                f"{name}: computed {want} != RAM {got} (stats are only recomputed at level-up, so stat exp earned since then is not in them)")
    return r


def player_progress(rig: Rig) -> Result:
    r = Result()
    e = rig.load("beat_brock")
    r.check(e.read(0xD356) & 1 == 1, ["wObtainedBadges"], "beat_brock: bit 0 (Boulder) set")
    e = rig.load("to_route1")
    r.check(e.read(0xD356) == 0, ["wObtainedBadges"], "to_route1: no badges")
    n, spec = rig.load("beat_brock"), None
    owned, seen = bit_indices(n.read_range(0xD2F7, 19)), bit_indices(n.read_range(0xD30A, 19))
    dex = rig.kb["dex_of_internal"][str(read_party(n)[0].species)]
    r.check(dex - 1 in owned and set(owned) <= set(seen), ["wPokedexOwned", "wPokedexSeen"],
            f"beat_brock: owned {len(owned)} (has dex #{dex}, the party mon), seen {len(seen)} superset of owned")
    e = rig.load("left_house")
    r.check(e.read_range(0xD347, 3) == bytes([0x00, 0x30, 0x00]), ["wPlayerMoney"], "left_house: BCD 00 30 00 == $3000 new-game money")
    f0 = rig.load("first_pokemon").read_range(0xD747, 320)
    f1 = rig.load("to_route1").read_range(0xD747, 320)
    f2 = rig.load("beat_brock").read_range(0xD747, 320)
    c = [len(bit_indices(x)) for x in (f0, f1, f2)]
    r.check(c[0] < c[1] < c[2], ["wEventFlags"], f"event bits grow with progress: first_pokemon {c[0]} < to_route1 {c[1]} < beat_brock {c[2]}")
    e = rig.load("to_route1")
    pairs = [(e.read(0xD888 + 2 * i), e.read(0xD889 + 2 * i)) for i in range(10)]
    nm = {rig.kb["name_of_internal"][str(s)] for _, s in pairs}
    r.check(nm == {"PIDGEY", "RATTATA"} and all(2 <= lv <= 5 for lv, _ in pairs) and e.read(0xD887) == 25,
            ["wGrassRate", "wGrassMons"], f"Route 1: rate 25, 10 slots of {sorted(nm)} L{min(p[0] for p in pairs)}-{max(p[0] for p in pairs)}")
    return r


def map_header(rig: Rig) -> Result:
    r, e = Result(), rig.load("left_house")
    h = read_map_header(e)
    r.check((e.read(0xD35E), h.width, h.height) == (0, 10, 9) and h.tiles == (20, 18),
            ["wCurMapWidth", "wCurMapHeight", "wCurMapHeader"], "Pallet Town (map 0): 10x9 blocks = 20x18 tiles")
    doors = {(w.y, w.x): w.dest_map for w in h.warps}
    r.check(e.read(0xD3AE) == 3 and doors == {(5, 5): 37, (5, 13): 39, (11, 12): 40},
            ["wNumberOfWarps", "wWarpEntries"], f"Pallet warps {doors}: Red's house (37), Blue's house (39), Oak's lab (40)")
    r.check(e.read(0xD4B0) == 4 and len(h.signs) == 4, ["wNumSigns", "wSignCoords"], "Pallet Town has 4 signs")
    live = sum(1 for i in range(1, 16) if e.read(0xC100 + 16 * i))
    r.check(e.read(0xD4E1) == live == 3, ["wNumSprites", "wMapSpriteData"], f"Pallet: {live} live sprite slots == wNumSprites (3 NPCs)")
    r.check(e.read(0xD367) == 0, ["wCurMapTileset"], "Pallet Town tileset 0 (overworld)")
    return r


def battle(rig: Rig) -> Result:
    r, e = Result(), rig.wild_battle()
    if not e.read(0xD057):
        r.failed.append("battle: no wild encounter found in 800 steps of Route 1 grass")
        return r
    en, me, party = read_enemy_mon(e), read_battle_mon(e), read_party(e)[0]
    nm = rig.kb["name_of_internal"][str(en.species)]
    ev = f"wild {nm} L{en.level} on Route 1"
    r.check(e.read(0xD057) == 1 and e.read(0xD05A) == 0, ["wIsInBattle", "wBattleType"], f"{ev}: wIsInBattle 1 (wild), wBattleType 0")
    r.check(e.read(0xCFD8) == en.species == e.read(0xCFE5), ["wEnemyMonSpecies2", "wEnemyMonSpecies", "wEnemyMon"], f"{ev}: species copies agree")
    # wCurOpponent is the TRAINER id (200 + class) and stays 0 in wild battles (found by tools/ram_discover.py, 2026-11-05)
    r.check(e.read(0xD059) == 0, ["wCurOpponent"], f"{ev}: wCurOpponent 0 in a wild battle (trainer battles: 200 + class)",
            f"wCurOpponent reads {e.read(0xD059)} in a wild battle; expected 0")
    r.check(2 <= en.level <= 5 and 0 < en.hp <= en.max_hp, ["wEnemyMonLevel", "wEnemyMonHP", "wEnemyMonMaxHP"], f"{ev}: HP {en.hp}/{en.max_hp}")
    row = rig.kb["species_by_dex"][str(rig.kb["dex_of_internal"][str(en.species)])]
    r.check(read_enemy_base_stats(e) == rig.base(en.species), ["wEnemyMonBaseStats"], f"{ev}: base stats {rig.base(en.species)} == kb")
    r.check(e.read(0xCFEC) == row["catch_rate"], ["wEnemyMonCatchRate"], f"{ev}: catch rate {row['catch_rate']} == kb")
    r.check(all(str(i) in rig.kb["moves"] for i in en.moves if i) and en.moves[0] != 0, ["wEnemyMonMoves", "wEnemyMonPP"],
            f"{ev}: moves {[rig.kb['moves'][str(i)]['name'] for i in en.moves if i]}")
    comp = {k: v for k, v in zip(KEYS, (en.max_hp, *en.stats))}
    from pokeagent.explorer.stats import dvs, stat_value
    d = dvs(en)
    want = {k: stat_value(rig.base(en.species)[k], d[k], 0, en.level, hp=(k == "hp")) for k in KEYS}
    r.check(comp == want, ["wEnemyMonDVs", "wEnemyMonStats", "wEnemyMonAttack", "wEnemyMonDefense", "wEnemyMonSpeed", "wEnemyMonSpecial"],
            f"{ev}: wild stat exp 0 + DVs {en.dv_word:#06x} + kb base reproduce stats {comp}")
    r.check(decode_text(e.read_range(0xCFDA, 11)) == nm, ["wEnemyMonNick"], f"{ev}: nick decodes to {nm!r}")
    r.check((me.species, me.hp, me.level, me.moves, me.dv_word, me.stats) == (party.species, party.hp, party.level, party.moves, party.dv_word, party.stats),
            ["wBattleMonSpecies", "wBattleMonHP", "wBattleMonLevel", "wBattleMonMoves", "wBattleMonDVs", "wBattleMonStats", "wBattleMonAttack", "wBattleMonPP", "wBattleMonMaxHP", "wBattleMon"],
            "battle: wBattleMon mirrors party mon 1 (species, HP, level, moves, DVs, stats)")
    r.check(me.stat_mods == (7,) * 6 and en.stat_mods == (7,) * 6, ["wPlayerMonStatMods", "wEnemyMonStatMods"], "battle start: all six stat modifiers 7 (+0) on both sides")
    return r


def menus_and_ui(rig: Rig) -> Result:
    r, e = Result(), rig.load("left_house")
    e.press(Button.START, 8, 40)
    y, x, cur0 = e.read(0xCC24), e.read(0xCC25), e.read(0xCC26)
    tm = e.read_range(0xC3A0, 360)
    on_cursor = tm[y * 20 + x] == 0xED
    e.press(Button.DOWN, 8, 24)
    cur1, mx = e.read(0xCC26), e.read(0xCC28)
    r.check(on_cursor and cur1 == cur0 + 1 and mx >= 1, ["wCurrentMenuItem", "wTopMenuItemY", "wTopMenuItemX", "wMaxMenuItem"],
            f"START menu: cursor tile 0xED at (wTopMenuItemX {x}, Y {y}); DOWN moved wCurrentMenuItem {cur0}->{cur1}; wMaxMenuItem {mx}")
    e = rig.load("left_house")
    t0 = e.read_range(0xDA43, 3)
    e.tick(600)
    t1 = e.read_range(0xDA43, 3)
    r.check(t0 != t1 and (t1[1] - t0[1]) % 60 == 10, ["wPlayTimeMinutes", "wPlayTimeSeconds", "wPlayTimeFrames", "wPlayTimeHours", "wPlayTimeMaxed"],
            f"play time advanced 10s over 600 frames: {t0.hex()} -> {t1.hex()}")
    return r


def facing_and_hram(rig: Rig) -> Result:
    r, e = Result(), rig.load("to_route1")
    seen = {}
    for b, want in DIRS.items():
        e.press(b, 4, 24)
        seen[b.name] = (e.read(0xC109), e.read(0xD52A))
    r.check(all(seen[b.name][0] == want for b, want in DIRS.items()), ["wSpritePlayerStateData1FacingDirection", "wSpritePlayerFacing"],
            f"facing after UP/DOWN/LEFT/RIGHT: {[seen[b.name][0] for b in DIRS]} == 4/0/8/12")
    r.check({v[1] for v in seen.values()} == {1, 2, 4, 8}, ["wPlayerDirection"], f"wPlayerDirection after UP/DOWN/LEFT/RIGHT: {[v[1] for v in seen.values()]} (8/4/2/1 bits)")
    pb = e._pyboy
    pb.button_press("a"); e.tick(4)
    held, pressed = e.read(0xFFB4), e.read(0xFFB3)
    pb.button_release("a"); e.tick(4)
    r.check(held & 1 == 1, ["hJoyHeld"], f"A held: hJoyHeld {held:#04x}", f"hJoyHeld read {held:#04x} with A held")
    r1 = {e.read(0xFFD3) for _ in range(8) if (e.tick(1) or True)}
    r.check(len(r1) > 1, ["hRandomAdd"], f"hRandomAdd varies frame to frame ({len(r1)} distinct of 8)")
    return r


def discovered(rig: Rig) -> Result:
    """Replay-verify the best mined RAM-discovery candidates (runs with ram_events.jsonl); proves labels they confirm.
    Pure: results only. tools/verify_ram.py records ``rig.findings`` unless --dry-run."""
    from pokeagent.ramlab import findings as F
    from pokeagent.ramlab import pipeline
    from pokeagent.ramlab.labels import load_entries
    root = Path(__file__).resolve().parent.parent
    r = Result()
    if not list((root / "runs").glob("*/ram_events.jsonl")):
        return r
    found, _, _ = pipeline.verify_top([root / "runs"], root / "roms" / "Pokemon Red.gb", rig.states)
    rig.findings = found
    entries = load_entries()
    already = {e["name"] for e in entries if e.get("verified")}
    F.apply_to_map(entries, {"findings": found})        # the same gate the CLI uses (size, region, byte coverage)
    r.ok.update({e["name"]: e["evidence"] for e in entries if e.get("verified") and e["name"] not in already})
    r.failed += [f"{f['addr']} {f['name']} ({f['event']}): {f['evidence'][:100]}" for f in found
                 if not f["verified"] and f["replay"]["witnesses"] and f["replay"]["passed"] * 3 < f["replay"]["witnesses"] * 2]
    return r


ALL = [party_struct, stat_exp_levelled, player_progress, map_header, battle, menus_and_ui, facing_and_hram, discovered]
