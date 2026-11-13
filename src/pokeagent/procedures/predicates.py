"""The precondition / effect vocabulary for goal procedures: pure checks over a small State snapshot.

``read_state(ctx)`` is the only reader: it fills ``{map, x, y, hp, hp_max, party, badges, flags, beaten, bag}``
from RAM and the run's own records. ``flags`` is a callable ``addr -> byte`` so a ``flag`` predicate may read
any address lazily; tests pass a plain dict instead (both are handled). Every predicate is a dict:
``{"map": 35}``, ``{"at": [m,x,y]}``, ``{"region": [m,x0,y0,x1,y1]}``, ``{"hp_frac_min": f}``,
``{"hp_frac_max": f}``, ``{"flag": [addr, bit]}``, ``{"badge": n}``, ``{"has_item": id}``,
``{"trainer_beaten": [m,x,y]}`` (or ``[m]``: any beaten placement on the map), ``{"party_size_min": n}``,
and the combinators ``all`` / ``any`` / ``not``.
An unknown key makes the predicate FALSE and is logged once - never raised, never treated as true.
"""
from __future__ import annotations

from pokeagent.goals import bag_contents
from pokeagent.magikarp import fighter, trainee_slot
from pokeagent.party_view import read_party_view
from pokeagent.ramstructs import read_party

BADGES = 0xD356  # wObtainedBadges (verified)
_warned: set = set()  # unknown predicate keys already logged once


def check(pred, state: dict, log=None) -> bool:
    """Does ``pred`` hold on this State snapshot? An empty dict is vacuously true; a non-dict is false."""
    if not isinstance(pred, dict):
        return False
    parts = []
    for key, val in pred.items():
        if key == "all":
            parts.append(isinstance(val, list) and all(check(p, state, log) for p in val))
        elif key == "any":
            parts.append(isinstance(val, list) and any(check(p, state, log) for p in val))
        elif key == "not":
            parts.append(not check(val, state, log))
        else:
            parts.append(_one(key, val, state, log))
    return all(parts)


def _one(key: str, val, st: dict, log) -> bool:
    try:
        if key == "map":
            return st["map"] == int(val)
        if key == "at":
            return (st["map"], st["x"], st["y"]) == tuple(val)
        if key == "region":
            m, x0, y0, x1, y1 = val
            return st["map"] == m and x0 <= st["x"] <= x1 and y0 <= st["y"] <= y1
        if key == "hp_frac_min":
            return st["hp_max"] > 0 and st["hp"] / st["hp_max"] >= float(val)
        if key == "hp_frac_max":
            return st["hp_max"] > 0 and st["hp"] / st["hp_max"] <= float(val)
        if key == "flag":
            addr, bit = val
            flags = st.get("flags")
            byte = flags(int(addr)) if callable(flags) else (flags or {}).get(int(addr), 0)
            return bool(byte >> int(bit) & 1)
        if key == "badge":
            return bool(int(st.get("badges", 0)) >> int(val) & 1)
        if key == "has_item":
            bag = st.get("bag") or {}
            return bool(bag.get(val, bag.get(int(val) if str(val).lstrip("0x").isalnum() else val, 0)))
        if key == "trainer_beaten":
            v, beaten = tuple(val), st.get("beaten", set())
            return v in beaten if len(v) > 1 else any(t[:1] == v for t in beaten)
        if key == "party_size_min":
            return len(st.get("party") or ()) >= int(val)
    except (TypeError, ValueError, KeyError, IndexError):
        return False
    if key not in _warned:
        _warned.add(key)
        if log:
            log(f"[procedure predicate: unknown key {key!r} - treating as false]", "res")
    return False


def _party_hp(emu) -> tuple[int, int]:
    """(hp, max) the hp_frac predicates see: the fighter's numbers while a Magikarp trainee is out; else slot 0's, as
    before; but a fainted slot 0 reads (0, fighter max) so a dead lead still routes to a heal even though the fighter is
    another member. A fainted BENCH member changes nothing."""
    view = read_party_view(emu)
    if not view.slots:
        return 0, 0
    _, _, hp, mx = fighter(emu)
    if trainee_slot(emu) is not None:
        return hp, mx
    s0 = view.slots[0]
    return (0, mx) if s0.fainted else (s0.hp, s0.max_hp)


def beaten_trainers(ctx) -> set:
    """{(map, x, y)} of trainers beaten IN THIS RUN - the trainer ledger's ROM-placement records (PR #158),
    the one beaten-trainers source. A walked-up trainer still counts: the ledger matches a placement to every
    tile the NPC was seen on, not the battle tile alone."""
    from pokeagent.explorer import trainer_hooks
    return trainer_hooks.beaten_trainers(ctx)


def read_state(ctx) -> dict:
    """Fill the State snapshot from RAM and the run's records (the only emulator reads the package does)."""
    emu = ctx.emu
    hp, mx = _party_hp(emu)
    return {"map": ctx.view.m, "x": ctx.view.x, "y": ctx.view.y, "hp": hp, "hp_max": mx,
            "party": read_party(emu), "badges": emu.read(BADGES), "flags": emu.read,
            "beaten": beaten_trainers(ctx), "bag": bag_contents(emu)}


def proc_maps(proc) -> set:
    """Every map id a procedure touches (action targets and every predicate's coordinates)."""
    out = set()

    def scan(pred):
        if not isinstance(pred, dict):
            return
        for k, v in pred.items():
            if k in ("all", "any"):
                for p in (v or []):
                    scan(p)
            elif k == "not":
                scan(v)
            elif k == "map":
                out.add(v)
            elif k in ("at", "region", "trainer_beaten") and isinstance(v, (list, tuple)) and v:
                out.add(v[0])

    for s in proc.steps:
        a = s.action or {}
        if isinstance(a.get("map"), int):
            out.add(a["map"])
        if isinstance(a.get("at"), (list, tuple)) and a["at"]:
            out.add(a["at"][0])
        scan(s.pre)
        scan(s.effect)
    return out
