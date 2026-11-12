"""The campaign ladder as data: src/pokeagent/data/campaign.json, plus generic detector evaluation and reachability.

Each goal is {id, name, after, detector, needs, note}. ``detector`` is one of
  {"map": [ids]}                  any of these maps was entered this run (sticky ``seen_maps``)
  {"badge": bit}                  wObtainedBadges (0xD356) bit set (bit0 Boulder ... bit7 Earth)
  {"item": id | [ids]}            the item is (or once was, this run) in the bag
  {"flag": {"addr", "bit"}}       an event-flag byte bit
  {"party": {"min_count": n}}     party size
  {"party_move": move_id}         any party member knows this move (pokered move id; 15 = CUT)
  {"map_and_badge": {"map": [ids], "badge": bit}}
  {"map_now_with_item": {"map": [ids], "item": id}}   standing on one of these maps NOW, holding (or once holding, this run) the item
  {"map_past_x": {"map": [ids], "x": n}}              standing on one of these maps NOW at wXCoord >= n (past a blocker)
  "unverified"                    no verified RAM detector; check_goals infers it from later goals, but only once its ``after``
                                  predecessor is reached too (never a segment target, never recorded)
The first 26 goals carry ``"special": true``: pokeagent.goals keeps their hand-coded detectors, byte for byte.
``needs`` are capability tags (cut, surf, strength, flash, poke_flute, silph_scope, bike, puzzle, safari, dex10) the
current agent behaviours may lack; see ``reachable`` / ``selectable``.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from pokeagent.ram_symbols import PARTY_COUNT, PARTY_MON1_MOVES, PARTY_MON_SIZE

CAMPAIGN_PATH = Path(__file__).with_name("data") / "campaign.json"
BADGES = 0xD356
UNVERIFIED = "unverified"


@lru_cache(maxsize=1)
def load_campaign() -> tuple[dict, ...]:
    return tuple(json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))["goals"])


def goal_ids() -> list[str]:
    return [g["id"] for g in load_campaign()]


def goal_spec(goal: str) -> dict | None:
    return next((g for g in load_campaign() if g["id"] == goal), None)


def agent_capabilities(emu=None, root: Path | None = None) -> frozenset[str]:
    """What the current agent behaviours can do: the POKEAGENT_CAPS=cut,surf env override (comma list, unchanged),
    capabilities read from RAM when an emulator is passed (pokeagent.unlocks), and the curriculum's own evidence:
    a run that reached ``cut_taught`` left ``runs/checkpoints/cut_taught.state`` (press_goals.record_goals writes it
    the moment the detector fires), which is what lets the segment picker - it has no emulator - see the capability."""
    caps = set(c.strip() for c in os.environ.get("POKEAGENT_CAPS", "").split(",") if c.strip())
    if emu is not None:
        from pokeagent import unlocks  # late import: unlocks needs this module's party_knows_move
        caps |= unlocks.capabilities(emu)
    base = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    if (base / "runs" / "checkpoints" / "cut_taught.state").exists():
        caps.add("cut")
    return frozenset(caps)


def reachable(goal: str, capabilities=None) -> bool:
    """False when the goal's own ``needs`` include a capability the agent lacks (unknown goals are unreachable)."""
    spec = goal_spec(goal)
    if spec is None:
        return False
    caps = agent_capabilities() if capabilities is None else set(capabilities)
    return set(spec.get("needs", ())) <= caps


def campaign_reachable(goal: str, capabilities=None) -> bool:
    """The goal AND every goal before it is reachable: the ladder is a chain, so a Surf goal walls off what follows."""
    caps = agent_capabilities() if capabilities is None else set(capabilities)
    for g in load_campaign():
        if not reachable(g["id"], caps):
            return False
        if g["id"] == goal:
            return True
    return False


def is_unverified(goal: str) -> bool:
    """No RAM detector of its own: its value is inferred from later goals, so it is never recorded as reached by a run."""
    spec = goal_spec(goal)
    return spec is not None and spec["detector"] == UNVERIFIED


def selectable(goal: str, capabilities=None) -> bool:
    """May the segment picker send an agent at this goal? Reachable through the chain and detectable in RAM."""
    spec = goal_spec(goal)
    return spec is not None and spec["detector"] != UNVERIFIED and campaign_reachable(goal, capabilities)


def _flag(emu, flag: dict) -> bool:
    addr = int(flag["addr"], 16) if isinstance(flag["addr"], str) else int(flag["addr"])
    return bool(emu.read(addr) >> int(flag["bit"]) & 1)


def party_knows_move(emu, move_id: int) -> bool:
    """Any of the (up to 6) party members has ``move_id`` in one of its four move slots."""
    n = min(emu.read(PARTY_COUNT), 6)
    return any(emu.read(PARTY_MON1_MOVES + PARTY_MON_SIZE * i + s) == move_id for i in range(n) for s in range(4))


def evaluate(det, emu, st: dict, seen: set, bag: dict) -> bool | None:
    """One generic detector against the emulator and run state; None for a detector this module does not evaluate."""
    if not isinstance(det, dict):
        return None
    if "map" in det and len(det) == 1:
        return any(m in seen for m in det["map"])
    if "badge" in det:
        return bool(emu.read(BADGES) >> int(det["badge"]) & 1)
    if "item" in det:
        ids = det["item"] if isinstance(det["item"], list) else [det["item"]]
        had = st.setdefault("had_items", set())
        had.update(i for i in ids if i in bag)
        return any(i in had for i in ids)
    if "flag" in det:
        return _flag(emu, det["flag"])
    if "party" in det:
        return emu.read(PARTY_COUNT) >= int(det["party"].get("min_count", 1))
    if "party_move" in det:
        return party_knows_move(emu, int(det["party_move"]))
    if "map_and_badge" in det:
        mb = det["map_and_badge"]
        return any(m in seen for m in mb["map"]) and bool(emu.read(BADGES) >> int(mb["badge"]) & 1)
    if "map_now_with_item" in det:
        mi = det["map_now_with_item"]
        had = st.setdefault("had_items", set())
        if mi["item"] in bag:
            had.add(mi["item"])
        return emu.read(0xD35E) in mi["map"] and mi["item"] in had
    if "map_past_x" in det:
        mx = det["map_past_x"]
        return emu.read(0xD35E) in mx["map"] and emu.read(0xD362) >= int(mx["x"])
    return None


def campaign_goals(emu, st: dict, seen: set, bag: dict) -> dict[str, bool]:
    """Generic detectors for every non-special goal (unverified ones are filled in by ``infer_unverified``)."""
    out: dict[str, bool] = {}
    for g in load_campaign():
        if g.get("special"):
            continue
        r = evaluate(g["detector"], emu, st, seen, bag)
        out[g["id"]] = bool(r)
    return out


def infer_unverified(g: dict[str, bool]) -> None:
    """An unverified goal counts as reached once a later goal has AND its ``after`` predecessor has: the ladder is a chain,
    so it cannot stall, but a goal reached out of order (the Cerulean bike shop) must not drag earlier ones with it."""
    later_true: dict[str, bool] = {}
    later = False
    for spec in reversed(load_campaign()):
        later_true[spec["id"]] = later
        later = later or bool(g.get(spec["id"]))
    for spec in load_campaign():  # forward, so a chain of unverified goals needs each predecessor in turn
        k = spec["id"]
        if spec["detector"] == UNVERIFIED:
            pred = spec.get("after")
            g[k] = later_true[k] and (pred is None or bool(g.get(pred)))


def brief(goals: dict, order: list[str], ahead: int = 6) -> str:
    """Short goal line for logs: 'done/total' then the next few unmet goals (the full ladder is too long to print)."""
    done = sum(1 for k in order if goals.get(k))
    nxt = [k for k in order if not goals.get(k)][:ahead]
    return f"{done}/{len(order)} done; next: " + " ".join(f"{k}-" for k in nxt) if nxt else f"{done}/{len(order)} done"
