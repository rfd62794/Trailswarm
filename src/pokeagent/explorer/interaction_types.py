"""interaction_types: what KIND of interaction was it? Classified from observed effects, never from who the NPC is.

An interaction is the span from the first A press to the box closing. ``EffectWindow`` holds the RAM bytes around it
(the same 0xD000.. window the explorer already snapshots); ``classify`` is a pure function of the before/after
windows plus the screens seen. The type is stored with a vote count so one odd reading cannot flip a memorised entry.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BASE = 0xD000  # EFFECT_WINDOW start in explorer.perceive (kept here so the module stays dependency-free)
A_BATTLE, A_PARTY_N, A_PARTY, A_MAP, A_BAG_N, A_BAG, A_MONEY, A_FLAGS = 0xD057, 0xD163, 0xD16B, 0xD35E, 0xD31D, 0xD31E, 0xD347, 0xD747
PARTY_STRIDE, A_HP, A_MAXHP, FLAG_BYTES = 44, 0xD16C, 0xD18D, 320
TRAINER_BATTLE = 2  # wIsInBattle: 1 wild, 2 trainer

HEALER, SHOP, PC, GIVER, VENDOR, TRAINER, STORY, BLOCKER, SIGN, INFO = (
    "healer", "shop", "pc", "giver", "vendor", "trainer", "story", "blocker", "sign", "info")
TYPES = (HEALER, SHOP, PC, GIVER, VENDOR, TRAINER, STORY, BLOCKER, SIGN, INFO)
GIVE_WORDS = ("received", "got ", "obtained", "found")


@dataclass
class Effects:
    """Everything classification needs, read from two window snapshots (bytes starting at BASE)."""
    money: int = 0  # after - before
    bag_gain: bool = False
    party_gain: bool = False
    healed: bool = False  # some mon was hurt before and every mon is at full HP after
    battle: int = 0  # wIsInBattle after (0 if none)
    map_changed: bool = False
    flags_changed: bool = False
    moved: bool = False  # the player ended on another tile (pushed back / forced walk)
    texts: list = field(default_factory=list)
    menus: list = field(default_factory=list)
    npc: bool = True  # an NPC sprite was in front (False: a solid tile, e.g. a sign or bookshelf)
    repeat_same: bool = False  # this spot already gave the same text before


def _at(win: bytes, addr: int, n: int = 1) -> bytes:
    return win[addr - BASE:addr - BASE + n]


def _bcd(raw: bytes) -> int:
    return int("".join(f"{b:02x}" for b in raw))


def _party_hp(win: bytes) -> list[tuple[int, int]]:
    n = min(_at(win, A_PARTY_N)[0], 6)
    out = []
    for i in range(n):
        hp = _at(win, A_HP + PARTY_STRIDE * i, 2)
        mx = _at(win, A_MAXHP + PARTY_STRIDE * i, 2)
        out.append(((hp[0] << 8) | hp[1], (mx[0] << 8) | mx[1]))
    return out


def _bag(win: bytes) -> dict[int, int]:
    n = _at(win, A_BAG_N)[0]
    if not 0 < n < 21:
        return {}
    raw = _at(win, A_BAG, 2 * n)
    return {raw[i]: raw[i + 1] for i in range(0, len(raw), 2)}


def _flag_bits(win: bytes) -> int:
    return sum(bin(b).count("1") for b in _at(win, A_FLAGS, FLAG_BYTES))


def read_effects(before: bytes, after: bytes, *, texts=(), menus=(), npc: bool = True, repeat_same: bool = False,
                 pos_before: tuple = (0, 0), pos_after: tuple = (0, 0)) -> Effects:
    """Compare the two window snapshots. Short windows (a test fixture without a field) read as unchanged."""
    try:
        hp_b, hp_a = _party_hp(before), _party_hp(after)
        bag_b, bag_a = _bag(before), _bag(after)
        money = _bcd(_at(after, A_MONEY, 3)) - _bcd(_at(before, A_MONEY, 3))
        bag_gain = any(q > bag_b.get(i, 0) for i, q in bag_a.items())
        party_gain = _at(after, A_PARTY_N)[0] > _at(before, A_PARTY_N)[0]
        healed = bool(hp_b) and any(h < m for h, m in hp_b) and len(hp_a) >= len(hp_b) and all(h == m for h, m in hp_a)
        return Effects(money, bag_gain, party_gain, healed, _at(after, A_BATTLE)[0],
                       _at(before, A_MAP)[0] != _at(after, A_MAP)[0], _flag_bits(before) != _flag_bits(after),
                       pos_before != pos_after, list(texts), list(menus), npc, repeat_same)
    except (IndexError, ValueError):
        return Effects(texts=list(texts), menus=list(menus), npc=npc, repeat_same=repeat_same)


def classify(fx: Effects) -> tuple[str, str]:
    """(type, why). First match wins; the order is the table in the directive, strongest evidence first."""
    said = " ".join(fx.texts).lower()
    menus = " ".join(fx.menus).upper()
    if fx.battle == TRAINER_BATTLE:
        return TRAINER, "a trainer battle started right after the text"
    if "BUY" in menus and ("SELL" in menus or "QUIT" in menus):
        return SHOP, "the BUY/SELL menu appeared"
    if "turned on the pc" in said or "WITHDRAW" in menus:
        return PC, "the PC menu appeared"
    if fx.healed:
        return HEALER, "party HP restored to full"
    if fx.money < 0:
        return VENDOR, f"money fell by {-fx.money} after a choice"
    if fx.bag_gain or fx.party_gain or any(w in said for w in GIVE_WORDS):
        return GIVER, "the bag or party gained something"
    if fx.map_changed or fx.flags_changed:
        return STORY, "the text changed the map or flipped an event flag"
    if fx.repeat_same and fx.moved:
        return BLOCKER, "the same text came back and the player was pushed back"
    if not fx.npc:
        return SIGN, "a solid non-NPC tile showed text"
    return INFO, "plain text with no effect"


def record_type(entry: dict, fx: Effects) -> str:
    """Store the type on an interaction entry as votes; the winner is ``entry['type']``, share is ``type_conf``."""
    kind, why = classify(fx)
    votes = entry.setdefault("type_votes", {})
    votes[kind] = votes.get(kind, 0) + 1
    top = max(votes, key=lambda k: (votes[k], k == kind))
    entry["type"], entry["type_conf"], entry["type_why"] = top, round(votes[top] / sum(votes.values()), 2), why
    return top
