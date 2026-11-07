"""Lineage: where a save state came from - ``organic`` (a run wrote it), ``synthetic`` (state surgery edited it) or
``promoted`` (a legal, in-envelope descendant of an organic-equivalent edit).

``edit_class`` decides whether the edits a synthetic state carries could have happened in the real game
(``organic_equivalent``) or skipped progress (``shortcut``). ``promote`` upgrades a synthetic start's descendant to
``promoted`` when the start was an organic-equivalent edit AND the end state is legal AND inside the organic
envelope. A promoted state may seed drills, A/B runs and segment starts, but never a chain best or confirmation;
a ``shortcut`` lineage stays synthetic forever.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pokeagent import envelope, legality, statefp

ORGANIC, SYNTHETIC, PROMOTED = "organic", "synthetic", "promoted"


def edit_class(edited: dict, edit_context: dict, catalog: dict | None, envelope_info) -> str:
    """``organic_equivalent`` only when EVERY edit could happen in the real game; else ``shortcut``.

    organic_equivalent edits: ``heal``; ``respawn`` to a town organic states carry (``envelope_info``: the set of
    respawn ids seen, e.g. envelope.respawns_seen(env)); ``give`` where every item has a price AND the money drop
    covers the cost; ``take``; ``set_hp`` at or below the mon's current HP (damage). ``shortcut``: ``set_level``,
    a money increase or a money edit not paired with a purchase, a free ``give``, ``set_hp`` above current,
    ``position``, or anything empty/unknown."""
    if not isinstance(edited, dict) or not edited:
        return "shortcut"
    ctx = edit_context or {}
    money_before, hp_now = ctx.get("money_before"), ctx.get("hp") or []
    respawns = set(envelope_info or ())
    items = (catalog or {}).get("items") or {}
    cost = 0
    for name, spec in edited.items():
        if name == "heal":
            ok = spec is True
        elif name == "respawn":
            ok = isinstance(spec, int) and spec in respawns
        elif name == "give":
            ok = bool(spec) and all(int((items.get(str(i)) or {}).get("price") or 0) > 0 for i, _q in spec)
            cost += sum(int(items[str(i)]["price"]) * q for i, q in spec) if ok else 0
        elif name == "take":
            ok = bool(spec)
        elif name == "set_hp":
            ok = isinstance(spec, dict) and bool(hp_now) and \
                all(isinstance(s, int) and 0 <= s < len(hp_now) and 0 <= v <= hp_now[s] for s, v in spec.items())
        elif name == "money":
            ok = True   # decided below against the give cost
        else:
            return "shortcut"  # set_level, position, anything unknown
        if not ok:
            return "shortcut"
    if "money" in edited:
        new_money = edited["money"]
        if (not isinstance(new_money, int) or isinstance(new_money, bool) or money_before is None
                or new_money >= money_before or not cost or money_before - new_money < cost):
            return "shortcut"  # a money increase, or a drop no purchase explains
    elif "give" in edited:
        return "shortcut"  # items appeared with no money deducted: a free give
    return "organic_equivalent"


MAX_DEPTH = 8


def _descends_from(end_state: Path, start_name: str) -> bool:
    """Walk END's ``parent`` sidecar chain (same directory) up to MAX_DEPTH hops looking for ``start_name``."""
    cur = end_state
    for _ in range(MAX_DEPTH):
        parent = (statefp.read(cur) or {}).get("parent")
        if not isinstance(parent, str) or not parent:
            return False
        if parent == start_name:
            return True
        cur = end_state.parent / parent
    return False


def promote(end_state, start_state, emu, kb, *, catalog: dict | None = None, hm: dict | None = None,
            rom: bytes | None = None, env: dict | None = None, slack_levels: int = 3,
            slack_money: float = 0.20) -> tuple[bool, list[str]]:
    """Upgrade END state's lineage to ``promoted``: START must be a synthetic state whose edit_class is
    ``organic_equivalent``, END must pass ``legality.check`` on ``emu`` (already loaded with it) and sit inside the
    organic envelope for its stage.
    END must also be ``synthetic`` and descend from START via the ``parent`` sidecar chain (<= MAX_DEPTH hops, same dir). On success the END sidecar gets ``lineage: promoted``, the ``legal`` record,
    ``parent`` and ``promoted_from``; on failure nothing is written and the reasons are returned."""
    start_state, end_state = Path(start_state), Path(end_state)
    reasons = []
    if statefp.lineage(end_state) != SYNTHETIC:
        reasons.append(f"promote: end {end_state.name} is {statefp.lineage(end_state)} (needs synthetic)")
    elif not _descends_from(end_state, start_state.name):
        reasons.append(f"promote: end {end_state.name} does not descend from {start_state.name} "
                       f"(parent chain must reach it within {MAX_DEPTH} hops)")
    sfp = statefp.read(start_state) or {}
    if statefp.lineage(start_state) != SYNTHETIC or sfp.get("edit_class") != "organic_equivalent":
        reasons.append(f"promote: start {start_state.name} is {statefp.lineage(start_state)}/"
                       f"{sfp.get('edit_class') or 'unclassified'} (needs synthetic/organic_equivalent)")
    res = legality.check(emu, kb, catalog=catalog, hm=hm, rom=rom)
    reasons += res.violations
    efp = statefp.read(end_state) or {"v": statefp.VERSION}
    inside, why = envelope.within_envelope(efp, envelope.stage_key(end_state.name, efp), env or {},
                                           slack_levels=slack_levels, slack_money=slack_money)
    if not inside:
        reasons += why
    if reasons:
        return False, reasons
    efp.pop("synthetic", None)
    efp.update(lineage=PROMOTED, parent=start_state.name, promoted_from=start_state.name,
               legal={"ok": res.ok, "violations": res.violations,
                      "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    statefp.write(end_state, efp)
    return True, []
