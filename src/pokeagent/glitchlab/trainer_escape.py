"""Trainer-escape ("Mew trick") probe: the hypothesis of docs/research/gen1-glitches-2026-11-15.md
rows 2, 3 and 5 as a scripted recipe, a per-step RAM probe and a pure verdict over the trace.

The recipe observes and records: H1 is "Start pressed before the '!' resolves, then escape,
leaves trainer bookkeeping stuck"; H2 is "a later fight's Special stat seeds the species of the
instant battle on return". Nothing here is confirmed - the verdict is data for the controller,
never a claim. Read-only: buttons and RAM reads only.
"""
from __future__ import annotations

from pokeagent.explorer.party_menu import is_start_menu, screen_lines
from pokeagent.explorer.perceive import TILEMAP, TILEMAP_LEN
from pokeagent.glitch_signals import MISC_SEEN_BY_TRAINER, active_reasons, engaged_now, read_signals
from pokeagent.glitchlab.script import Step, load_script, run_script
from pokeagent.ram import RAM_MAP
from pokeagent.ram_symbols import CUR_OPPONENT, ENEMY_MON, TRAINER_CLASS

ENEMY_LEVEL = 0xCFF3       # wEnemyMonLevel (ram_map.json, verified)
ENEMY_SPECIAL = 0xCFFC     # wEnemyMonSpecial, 2 bytes big-endian (ram_map.json, verified)
CUR_ENEMY_LEVEL = 0xD127   # wCurEnemyLevel (SYM): UNVERIFIED "other stale stat" candidate - log only
UNMOD_SPECIAL = 0xCD2C     # wEnemyMonUnmodifiedSpecial (SYM): UNVERIFIED candidate - log only
UNMOD_LEVEL = 0xCD23       # wEnemyMonUnmodifiedLevel (SYM): UNVERIFIED candidate - log only

# The steps in order. Cursor/walk presses depend on the save state, so those steps are
# placeholders: the controller fills them in a --script JSON before the probe runs.
RECIPE: list[dict] = [
    {"id": "before_spot", "mark": True},
    {"id": "walk_to_sight", "press": [], "placeholder": True},
    {"id": "at_exclaim", "mark": True},
    {"id": "start_menu", "press": ["START"]},
    {"id": "escape", "press": [], "placeholder": True},
    {"id": "after_escape", "mark": True},
    {"id": "special_fight", "press": [], "placeholder": True},
    {"id": "return_walk", "press": [], "placeholder": True},
    {"id": "on_return", "mark": True},
]


def default_menu_probe(emu) -> bool:
    """True when the on-screen text is the Start menu (tile map -> screen_lines -> is_start_menu)."""
    return is_start_menu(" | ".join(screen_lines(emu.read_range(TILEMAP, TILEMAP_LEN))))


def read_probe(emu, menu_probe=None) -> dict:
    """The RAM bytes each recipe step dumps: the slice-1 signals plus reasons, map/position,
    the enemy block (including the 2-byte Special) and the log-only stale-stat candidates.
    ``menu_probe`` overrides the tile-map Start-menu read; a raising probe yields
    ``start_menu_open`` None, never an error."""
    sig = read_signals(emu)
    spec = emu.read_range(ENEMY_SPECIAL, 2)
    try:
        start_open = (menu_probe or default_menu_probe)(emu)
    except Exception:  # noqa: BLE001  the menu read must never kill a probe run
        start_open = None
    return {
        "misc_flags": sig.misc_flags, "status5": sig.status5,
        "seen_by_trainer": bool(sig.misc_flags & MISC_SEEN_BY_TRAINER), "engaged": engaged_now(sig),
        "engaged_class": sig.engaged_class, "engaged_set": sig.engaged_set,   # stale bytes: log only
        "in_battle": sig.in_battle, "reasons": active_reasons(sig),
        "map": emu.read(RAM_MAP["map_id"]), "y": emu.read(RAM_MAP["player_y"]),
        "x": emu.read(RAM_MAP["player_x"]),
        "enemy_species": emu.read(ENEMY_MON), "enemy_level": emu.read(ENEMY_LEVEL),
        "special_u16": (spec[0] << 8) | spec[1], "special_lo": spec[1],
        "cur_opponent": emu.read(CUR_OPPONENT), "trainer_class": emu.read(TRAINER_CLASS),
        "cur_enemy_level": emu.read(CUR_ENEMY_LEVEL),
        "unmod_special": emu.read(UNMOD_SPECIAL), "unmod_level": emu.read(UNMOD_LEVEL),
        "start_menu_open": start_open,
    }


def _row(rows, rid) -> dict | None:
    return next((r for r in rows if r.get("id") == rid), None)


def _ram(row, key, default=None):
    return (row or {}).get("ram", {}).get(key, default)


def verdict(rows) -> dict:
    """Pure summary of a repro trace: did the Start menu open before engagement, is the trainer
    state stuck after the escape, what Special did the wild fight leave, and did an instant
    battle fire on return (species/level/map). Raw bytes ride along in ``notes`` so the
    controller judges - the bit meanings are UNVERIFIED."""
    notes = ["bit meanings UNVERIFIED"]
    before, exclaim = _row(rows, "before_spot"), _row(rows, "at_exclaim")
    start, after = _row(rows, "start_menu"), _row(rows, "after_escape")
    fight, back, ret = _row(rows, "special_fight"), _row(rows, "return_walk"), _row(rows, "on_return")

    opened = _ram(start, "start_menu_open")
    start_opened = None if opened is None else bool(opened)
    seen_at_exclaim = _ram(exclaim, "seen_by_trainer")
    notes.append(f"at_exclaim engaged_class={_ram(exclaim, 'engaged_class')} (stale byte, log only)")
    notes.append(f"at_exclaim seen_by_trainer={seen_at_exclaim}")

    stuck = None
    if after is not None and before is not None:
        notes.append(f"after_escape misc_flags={_ram(after, 'misc_flags')} "
                     f"status5={_ram(after, 'status5')} in_battle={_ram(after, 'in_battle')} "
                     f"map={_ram(after, 'map')}")
        stuck = (not _ram(after, "in_battle")
                 and bool((_ram(after, "misc_flags", 0) or 0) & 1 or (_ram(after, "status5", 0) or 0) & 1)
                 and _ram(after, "map") != _ram(before, "map"))

    enemy_special = None
    if fight is not None:
        enemy_special = {"special_u16": _ram(fight, "special_u16"), "special_lo": _ram(fight, "special_lo")}

    instant = None
    if ret is not None and back is not None and _ram(ret, "in_battle") and not _ram(back, "in_battle"):
        instant = {"species": _ram(ret, "enemy_species"), "level": _ram(ret, "enemy_level"),
                   "map": _ram(ret, "map")}
        notes.append(f"on_return cur_enemy_level={_ram(ret, 'cur_enemy_level')} "
                     f"unmod_level={_ram(ret, 'unmod_level')} unmod_special={_ram(ret, 'unmod_special')}")

    matches = None
    if instant is not None and enemy_special is not None and enemy_special["special_lo"] is not None:
        matches = instant["species"] == enemy_special["special_lo"]

    return {"start_opened_before_engagement": start_opened, "trainer_state_stuck": stuck,
            "enemy_special": enemy_special, "instant_encounter": instant,
            "species_matches_special": matches, "seen_at_exclaim": seen_at_exclaim, "notes": notes}


def run_recipe(emu, steps=None, *, allow_placeholder=False, probes=read_probe, record=None) -> list:
    """Run the recipe on an emulator already booted from a scratch state; returns the trace
    rows. ``steps`` defaults to RECIPE (the CLI passes a parsed --script instead). ValueError
    while any placeholder step remains, unless ``allow_placeholder`` - the cursor and walking
    presses are save-dependent and only the controller can supply them."""
    steps = load_script(RECIPE) if steps is None else steps
    left = [s.id for s in steps if s.placeholder]
    if left and not allow_placeholder:
        raise ValueError(f"placeholder steps need controller edits: {left} (or pass --allow-placeholder)")
    return run_script(emu, steps, probes, record=record)


__all__ = ["RECIPE", "read_probe", "verdict", "run_recipe", "default_menu_probe", "Step"]
