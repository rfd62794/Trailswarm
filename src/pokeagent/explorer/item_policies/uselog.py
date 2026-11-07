"""Every item use goes through the economy ledger: item, category, reason, before / after, so outcomes can be learned later."""
from __future__ import annotations

from pokeagent.explorer.economy import ledger
from pokeagent.explorer.item_policies import ids
from pokeagent.explorer.item_policies.view import read_mons

CATEGORIES = ("key_item", "rare_candy", "vitamin", "stone", "hm", "tm", "repel", "x_item")


def snapshot(emu, slot: int | None, item: int) -> dict:
    """What a use can change, read now: the target's species/level/HP/moves/stat exp, the bag count, riding and repel RAM."""
    from pokeagent.goals import bag_contents
    snap = {"bag": bag_contents(emu).get(item, 0), "ride": emu.read(0xD700), "repel": emu.read(0xD0DB)}
    mons = read_mons(emu)
    if slot is not None and slot < len(mons):
        m = mons[slot]
        snap.update(slot=slot, species=m.species, level=m.level, hp=m.hp, max_hp=m.max_hp, moves=list(m.moves), stat_exp=list(m.stat_exp))
    return snap


def record(ctx, item: int, category: str, reason: str, before: dict, after: dict, behaviour: str = "use_items", battle: bool = False) -> None:
    ledger.of(ctx).item_use(ctx, item, category, reason, behaviour, before, after, battle)
    ctx.log(f"[item use: {ids.name_of(item)} ({category}) - {reason}; before {_brief(before)} -> after {_brief(after)}]", "res")


def _brief(s: dict) -> str:
    keys = ("species", "level", "hp", "moves", "bag", "ride", "repel")
    return "{" + ", ".join(f"{k}={s[k]}" for k in keys if k in s) + "}"
