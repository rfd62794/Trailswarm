"""Key items: never sold, tossed or deposited; BICYCLE use; marked campaign hooks for the rest.

The catalog's ``key_item`` is a heuristic (price 0 and not consumable: the ROM's KeyItemFlags table was not found), so the
shield is the UNION of the catalog flag and the fixed id list below (pokered item ids), and HMs always count.
"""
from __future__ import annotations

from pokeagent.explorer.item_policies import ids
from pokeagent.knowledge import items_catalog

KEY_IDS = frozenset({0x05, 0x06, 0x07, 0x09, 0x1F, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x30, 0x3F, 0x40, 0x45, 0x46, 0x47, 0x48, 0x49,
                     0x4A, 0x4B, 0x4C, 0x4D, 0x4E})  # TOWN MAP, BICYCLE ... fossils, keys, tickets, flute, scope, rods
DISPOSALS = ("sell", "toss", "deposit")
WALK, BIKE, SURF = 0, 1, 2
WALK_BIKE_SURF_STATE = 0xD700
CUR_TILESET, TILESET_OVERWORLD = 0xD367, 0
BIKE_MIN_LEG = 12   # tiles: a shorter leg is not worth the START-menu round trip (None = leg length unknown: ride)


def is_key_item(item_id: int, cat: dict | None = None) -> bool:
    if item_id in KEY_IDS or ids.is_hm(item_id):
        return True
    cat = cat if cat is not None else items_catalog.load()
    row = items_catalog.item(cat, item_id) if cat else None
    return bool(row and row["key_item"])


def may_dispose(item_id: int, action: str, cat: dict | None = None) -> bool:
    """False for any key item (or HM) and any of sell / toss / deposit."""
    if action not in DISPOSALS:
        raise ValueError(f"unknown disposal {action!r}")
    return not is_key_item(item_id, cat)


def bicycle_decision(*, owned: bool, state: int, outdoor: bool, battle: bool, leg_tiles: int | None,
                     on_cooldown: bool = False) -> tuple[int, None, str] | None:
    """Mount the BICYCLE (selecting it from the bag toggles riding, so only ever when we are walking) for a long outdoor leg."""
    if not owned or battle or on_cooldown or state != WALK or not outdoor:
        return None
    if leg_tiles is not None and leg_tiles < BIKE_MIN_LEG:
        return None
    return ids.BICYCLE, None, f"long overworld leg ({'?' if leg_tiles is None else leg_tiles} tiles): riding the BICYCLE"


# --- campaign hooks: decision functions only (no menu driver yet); map ids are pokered's, not yet verified on this ROM ---
POKEMON_TOWER_MAPS = frozenset(range(0x8E, 0x95))                                        # 1F-7F (unverified)
SILPH_CO_MAPS = frozenset({0xB5, 0xCF, 0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xE9, 0xEA, 0xEB})  # 1F-11F (unverified)


def flute_decision(*, owned: bool, snorlax_ahead: bool, battle: bool) -> tuple[int, None, str] | None:
    """CAMPAIGN HOOK: the POKe FLUTE when a sleeping SNORLAX blocks the way. Not wired to a menu driver."""
    if owned and snorlax_ahead and not battle:
        return ids.POKE_FLUTE, None, "SNORLAX blocks the road: playing the POKe FLUTE"
    return None


def silph_scope_decision(*, owned: bool, map_id: int, battle: bool) -> tuple[int, None, str] | None:
    """CAMPAIGN HOOK: the SILPH SCOPE is carried, not used from the bag; Pokemon Tower ghosts need it to be seen."""
    if owned and map_id in POKEMON_TOWER_MAPS and not battle:
        return ids.SILPH_SCOPE, None, "in Pokemon Tower with the SILPH SCOPE (carry, never dispose)"
    return None


def card_key_decision(*, owned: bool, map_id: int, facing_locked_door: bool, battle: bool) -> tuple[int, None, str] | None:
    """CAMPAIGN HOOK: the CARD KEY opens Silph Co doors by walking into them; this only decides it is the key to carry."""
    if owned and map_id in SILPH_CO_MAPS and facing_locked_door and not battle:
        return ids.CARD_KEY, None, "locked Silph Co door: the CARD KEY opens it"
    return None
