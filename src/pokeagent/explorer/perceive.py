"""Pure readers of the screen and RAM: what the explorer sees (moved unchanged from tools/explore_demo.py)."""
from __future__ import annotations

from pokeagent.explorer import items, legend, tilekind
from pokeagent.hexmap import diff as ram_diff
from pokeagent.knowledge.readiness import TEAM_GAP
from pokeagent.magikarp import fighter, magikarp_stats, trainee_slot
from pokeagent.names import load_registry
from pokeagent.party_view import read_battle_view, read_party_view
from pokeagent.ram_symbols import IS_IN_BATTLE
from pokeagent.screentext import CHARMAP

DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}
TILEMAP, TILEMAP_LEN, BORDER_TL = 0xC3A0, 360, 0x79
TILEMAP_ADDR, BATTLE_FLAG = TILEMAP, IS_IN_BATTLE  # the names the old explorer module used
# Screen-tile offsets of the 2x2 map tile in front of the player (player sprite sits at rows 8-9, cols 8-9).
AHEAD = {"UP": [(6, 8), (6, 9), (7, 8), (7, 9)], "DOWN": [(10, 8), (10, 9), (11, 8), (11, 9)],
         "LEFT": [(8, 6), (8, 7), (9, 6), (9, 7)], "RIGHT": [(8, 10), (8, 11), (9, 10), (9, 11)]}
EFFECT_WINDOW = (0xD000, 0x900)  # bag, money, map, party, event flags: diffed around every interaction
REGISTRY = load_registry()


def party_hp(emu) -> tuple[int, int]:
    """The fighter's HP and max HP: the lead normally, the verified active mon while a Magikarp trainee
    is out (party_view). (0, 0) for an empty party."""
    _, _, hp, mx = fighter(emu)
    return hp, mx


def party_needs_heal(emu, below: float) -> bool:
    """Out-of-battle "are we hurt" for heal/restock/planning callers: the fighter's HP fraction is under
    ``below``, or any occupied slot is fainted (a healthy second mon must not hide a dead lead)."""
    _, _, hp, mx = fighter(emu)
    return read_party_view(emu).any_fainted or (mx > 0 and hp / mx < below)


def heal_gate_hp(emu) -> tuple[int, int]:
    """(hp, max) the route/grind heal gates should see: the fighter's numbers normally; (0, fighter max)
    while any member is fainted, so a dead lead still routes to a heal like the old slot-0 read did."""
    _, _, hp, mx = fighter(emu)
    return (0, mx) if read_party_view(emu).any_fainted else (hp, mx)


def true_lead_level(emu) -> int:
    """The fighter's real level (party lead, or the strongest non-Magikarp while a trainee is out): bandit features and
    atlas priors are keyed by this, not by the trainee-band level the training gate sees."""
    return fighter(emu)[1]


def lead_level(emu) -> int:
    """Level the training gate sees: the fighter's (the party lead, or the strongest non-Magikarp while a Magikarp is
    in training). While a Magikarp trainee is in the party it is min(fighter level, trainee level + TEAM_GAP):
    the gate stays open (grass-seeking continues) until the trainee is within TEAM_GAP of the level the stage
    needs. Once it has evolved the function behaves exactly as before."""
    if trainee_slot(emu) is None:
        return fighter(emu)[1]
    stats = magikarp_stats(emu)
    return min(fighter(emu)[1], stats["level"] + TEAM_GAP) if stats else fighter(emu)[1]


def ahead_tiles(tilemap: bytes, direction: str) -> list[int]:
    return [tilemap[r * 20 + c] for r, c in AHEAD[direction]]


def stand_tile(tilemap: bytes) -> int:
    """The tile id under the player: bottom-left of the 2x2 at screen rows 8-9, columns 8-9 (the game's wTilePlayerStandingOn)."""
    return tilemap[9 * 20 + 8]


def sprite_snapshot(emu) -> list[list[int]]:
    """[picture id, map y, map x] for NPC sprite slots 1-15 (wSpriteStateData, UNVERIFIED addresses)."""
    out = []
    for i in range(1, 16):
        pic = emu.read(0xC100 + 16 * i)
        if pic:
            out.append([pic, emu.read(0xC204 + 16 * i), emu.read(0xC205 + 16 * i)])
    return out


def npc_positions(emu) -> set:
    return {(emu.read(0xC205 + 16 * i) - 4, emu.read(0xC204 + 16 * i) - 4) for i in range(1, 16) if emu.read(0xC100 + 16 * i)}


def ascii_vision(emu, mem, tileset: int) -> legend.Rendered:
    """Cheap vision: the visible 10x9 map tiles as one character each, from RAM, no image model.
    Kinds and glyphs come from the world legend (explorer.legend + explorer.tilekind); text boxes are
    NOT part of the map: the dialog pane shows them."""
    tm = emu.read_range(TILEMAP, TILEMAP_LEN)
    m, px, py = emu.read(0xD35E), emu.read(0xD362), emu.read(0xD361)
    d = mem.m(m)
    npcs = {(emu.read(0xC205 + 16 * i) - 4, emu.read(0xC204 + 16 * i) - 4) for i in range(1, 16) if emu.read(0xC100 + 16 * i)}
    trainers = tilekind.trainer_tiles(d)
    item_pos = {(x, y) for _slot, x, y in items.item_balls(emu)}  # live: a picked-up ball is gone, not '*'
    tile_types = mem.data.get("tile_types", {})
    grass_ids = mem.data.get("grass_ids", {})
    kinds = set()
    rows = []
    for r in range(9):
        line = ""
        for c in range(10):
            mx, my = px + (c - 4), py + (r - 4)
            block = [tm[(2 * r) * 20 + 2 * c], tm[(2 * r) * 20 + 2 * c + 1], tm[(2 * r + 1) * 20 + 2 * c], tm[(2 * r + 1) * 20 + 2 * c + 1]]
            kind = "you" if (c, r) == (4, 4) else tilekind.classify(
                d, tile_types, grass_ids, tileset, mx, my, block, npcs, trainers, items=item_pos, strict=False)
            kinds.add(kind)
            line += legend.glyph(kind, tilekind.ledge_dir(d, mx, my) if kind == "ledge" else None)
        rows.append(line)
    return legend.Rendered(rows, legend.line(kinds))


def wrap_move(move: str, width: int = 22, prefix: str = "move  ") -> list[str]:
    """The move rule wrapped at spaces to fit ``width`` columns (continuations indented); never cuts a word."""
    if not move:
        return []
    import textwrap
    parts = textwrap.wrap(move, width, initial_indent=prefix, subsequent_indent="  ",
                          break_long_words=False, break_on_hyphens=False)
    return parts or [prefix + move]


def battle_view(emu, move: str = "") -> list[str]:
    """What the agent 'sees' in a battle: not a map. HP/level from RAM (pret/pokered addresses, UNVERIFIED until
    we watch them move: wBattleMonHP, wBattleMonMaxHP, wBattleMonLevel via read_battle_view,
    wEnemyMonHP 0xCFE6/E7, wEnemyMonMaxHP 0xCFF4/F5, wEnemyMonLevel 0xCFF3) plus the on-screen text and menu.
    `move` adds the chosen move's rule string ('EMBER x2 FIRE>GRASS/POISON STAB') when supplied."""
    def u16(a): return (emu.read(a) << 8) | emu.read(a + 1)
    tm = emu.read_range(TILEMAP, TILEMAP_LEN)
    lines = frame_lines(tm)
    bm = read_battle_view(emu).battle_mon  # None while wBattleMon is stale (species 0): no leftover numbers
    rows = [f"BATTLE kind=0x{emu.read(IS_IN_BATTLE):02X}",
            f"you   L{bm.level:<3} HP {bm.hp:>3}/{bm.max_hp:<3}" if bm is not None else "you  (not loaded)",
            f"enemy L{emu.read(0xCFF3):<3} HP {u16(0xCFE6):>3}/{u16(0xCFF4):<3}",
            "(hp addrs unverified)"]
    rows += wrap_move(move)
    rows += ["", "MENU/TEXT:"]
    menu = [ln for ln in lines if ">" in ln or ln.isupper()]
    rows += [ln[:20] for ln in (menu or lines)[:6]]
    return rows


def effects(before: bytes, after: bytes) -> tuple[list[list[int]], str]:
    """RAM deltas around an interaction, capped, plus a one-line human summary using the registry's names."""
    changes = ram_diff(before, after, base=EFFECT_WINDOW[0])[:64]
    raw = [[c.addr, c.old, c.new] for c in changes]
    named = []
    for c in changes:
        e = REGISTRY.by_addr(c.addr)
        if e:
            named.append(f"{e.name} {c.old}->{c.new}")
    summary = ", ".join(named[:6]) if named else (f"{len(raw)} unnamed bytes changed" if raw else "no RAM change")
    return raw, summary


def box_open(tilemap: bytes) -> bool:
    """A frame is open when a top-left corner tile is immediately followed by a top-edge tile."""
    i = tilemap.find(bytes([BORDER_TL, 0x7A]))
    return i >= 0


def frame_lines(tilemap: bytes) -> list[str]:
    """Readable text lines anywhere on screen (dialog rows, menus, lists); '>' marks the menu cursor."""
    out = []
    for r in range(18):
        row = tilemap[r * 20:(r + 1) * 20]
        if row.count(0x7C) < 2:  # only rows inside a frame (left and right edge tiles present)
            continue
        inner = row[row.index(0x7C) + 1:len(row) - row[::-1].index(0x7C) - 1]
        line = "".join(ch if ch.isprintable() else " " for ch in (CHARMAP.get(b, " ") or " " for b in inner)).strip()
        if any(ch.isalnum() for ch in line):
            out.append(" ".join(line.split()))
    return out


def box_text(tilemap: bytes) -> str:
    return " | ".join(frame_lines(tilemap))


def is_menu(tilemap: bytes) -> bool:
    return 0xED in tilemap  # the ▶ cursor tile (verified)
