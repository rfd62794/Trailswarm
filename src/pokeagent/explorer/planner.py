"""Goal-directed policy on top of exploration (moved unchanged from tools/explore_plan.py).

plan_step: Robert's targets in order: potion (PC), leave the house, first pokemon (Oak's trigger), win the
first battle (FIGHT), then the road to Pewter.
"""
from __future__ import annotations

from pokeagent.explorer.world import POKECENTER_MAPS, STARTERS, WorldGraph, interaction_spots


def plan_step(goals: dict, maps: dict, pos: tuple, facing: str) -> tuple[str, str] | None:
    """Next button toward the first unmet goal that the learned world already knows how to reach, else None."""
    g = WorldGraph(maps)
    hp, mx = goals.get("_hp", (0, 0))
    if goals.get("first_pokemon") and mx and hp / mx < 0.4 and pos[0] in (0x00, 0x25, 0x26, 0x0C) and not goals.get("_mom_failed"):
        # Weak and near home: Mom heals the party when talked to. She is the one static sprite downstairs
        # (learned in maps.json npcs; fallback (5,4)); stand below her facing UP and press A.
        mom = next((e for e in maps.get(str(0x25), {}).get("npcs", {}).values() if not e.get("moves") and e.get("last")), None)
        mx_, my_ = (mom["last"][0], mom["last"][1]) if mom else (5, 4)
        spot = (0x25, mx_, my_ + 1)
        if pos == spot:
            return ("A" if facing == "UP" else "UP"), f"HP {hp}/{mx}: at Mom, {'talking' if facing == 'UP' else 'facing her'} to heal"
        p = g.path(pos, lambda n: n == spot)
        if p:
            return p[0], f"HP {hp}/{mx}: going home to Mom to heal ({len(p)} steps)"
    # Top off (90%) while Viridian / Route 2's south end are close: 10 of 11 failed to_pewter runs (06:52-06:59) were Forest
    # blackouts, while every run that crossed without one needed only ~800 steps. Inside the gate / Forest the threshold
    # stays 50% (a trek back is long).
    # (the Pokecenter itself must use the same 90%: with 50% inside, an agent at 70% HP walked in at Viridian, walked
    # straight back out, and ping-ponged through the door for 220 presses - 07:14 round)
    heal_below = 0.9 if pos[0] in (0x01, 0x0D, 0x02, 0x36) + POKECENTER_MAPS else 0.5
    if (goals.get("deliver_parcel") and mx and hp / mx < heal_below and not goals.get("_mom_failed")
            and (pos[0] in (0x01, 0x0D, 0x0C, 0x32, 0x33, 0x02, 0x36) or pos[0] in POKECENTER_MAPS)):
        # Weak on the road north: the Viridian Pokecenter (map 41, door at Viridian (23,26)) heals for free. Inside,
        # every Pokecenter has the same shape: door (3,7), a clear column x=3 up to the counter, nurse at (3,1).
        if pos[0] in POKECENTER_MAPS:
            if pos[1] != 3:
                return ("RIGHT" if pos[1] < 3 else "LEFT"), f"HP {hp}/{mx}: crossing the Pokecenter to the counter"
            if pos[2] > 2:
                return "UP", f"HP {hp}/{mx}: walking up to the nurse"
            return ("A" if facing == "UP" else "UP"), f"HP {hp}/{mx}: at the nurse, {'talking' if facing == 'UP' else 'facing her'} to heal"
        p = g.path(pos, lambda n: n[0] in POKECENTER_MAPS)
        if p and len(p) <= 120:
            return p[0], f"HP {hp}/{mx}: to the Pokecenter to heal ({len(p)} steps)"
    if not goals.get("potion"):
        for (m, x, y, f) in interaction_spots(maps, "PC"):
            if pos == (m, x, y):
                return ("A" if facing == f else f), f"goal potion: at the PC, {'using it' if facing == f else 'facing it'}"
            p = g.path(pos, lambda n: n == (m, x, y))
            if p:  # [] cannot happen here (pos == spot handled above)
                return p[0], f"goal potion: {len(p)} steps to the PC at ({x},{y}) on map 0x{m:02X}"
    if not goals.get("left_house"):
        p = g.path(pos, lambda n: n[0] not in (0x25, 0x26))
        if p:
            return p[0], f"goal leave the house: {len(p)} steps to the door"
    if not goals.get("first_pokemon"):
        # In Oak's lab: go to the ball that offers the wanted starter (learned from earlier "Do you want X?" boxes).
        if pos[0] == 0x28:
            want = (goals.get("_starter") or "any").upper()

            def spot_text(m, x, y, f):
                e = maps.get(str(m), {}).get("interactions", {}).get(f"{x},{y},{f}", {})
                return ((e.get("text") or "") + " " + " ".join(e.get("choices", []) or [])).upper()

            # Balls = spots in the lab whose dialog named a starter. The wanted one may be an untried neighbour
            # on the same table row, so try those too. NEVER fall through to the Pallet Town OAK spot from here:
            # that is what walked the agent back out of the lab.
            # A ball spot is one whose dialog had the OFFER phrase ("So! You want the water POKeMON, SQUIRTLE?").
            # Plain "want" also matches the nickname question, which contaminated a spot where the agent merely
            # stood while that dialog ran (5,5,DOWN "received a BULBASAUR"); the offer phrase does not.
            OFFER = "YOU WANT THE"
            ELEMENT = {"FIRE": "CHARMANDER", "WATER": "SQUIRTLE", "PLANT": "BULBASAUR", "GRASS": "BULBASAUR"}

            def ball_species(s):
                """Which starter THIS ball offers, read from its own offer text ('You want the fire POKeMON, CHARMANDER?'),
                never from later dialog that may mention another starter (that contamination sent a Bulbasaur run to the
                Charmander ball forever)."""
                import re as _re
                m = _re.search(r"YOU WANT THE\W*(FIRE|WATER|PLANT|GRASS)\W*POK", spot_text(*s))
                return ELEMENT[m.group(1)] if m else None
            balls = [s for s in interaction_spots(maps, OFFER) if s[0] == 0x28 and ball_species(s)]
            declined = goals.get("_declined") or set()  # ball spots this run already said NO to
            balls = [s for s in balls if s not in declined]
            targets = [s for s in balls if want == "ANY" or ball_species(s) == want]
            if not targets:
                # The wanted ball is unknown: try an untried neighbour of every ball we have seen (including the declined
                # ones). A neighbour with recorded dialog text was already tried (NPC/sign), so skip it; empty captures do not count.
                seen = {(s[0], s[1], s[2], s[3]) for s in interaction_spots(maps, OFFER) if s[0] == 0x28 and ball_species(s)} | set(declined)
                lab_inter = {k: e for k, e in maps.get("40", {}).get("interactions", {}).items() if (e.get("text") or "").strip()}
                for (m, x, y, f) in seen:
                    for dx in (-1, 1):
                        nb = (m, x + dx, y, f)
                        if nb not in seen and f"{x + dx},{y},{f}" not in lab_inter and not any(n in spot_text(m, x + dx, y, f) for n in STARTERS if n != want):
                            targets.append(nb)
            for (m, x, y, f) in sorted(targets, key=lambda s: abs(s[1] - pos[1]) + abs(s[2] - pos[2])):
                if pos == (m, x, y):
                    return ("A" if facing == f else f), f"goal first pokemon: at a ball spot for {want}, {'taking it' if facing == f else 'facing it'}"
                p = g.path(pos, lambda n: n == (m, x, y))
                if p:
                    return p[0], f"goal first pokemon: {len(p)} steps to the ball spot ({x},{y}) for {want}"
            return None  # unknown table so far: explore the lab (the caller's exploration prefers untested walls)
        # Oak's trigger is the outdoor "Hey! Wait!" event in Pallet Town (map 0). Any spot whose text merely mentions OAK
        # also matched Mom's line "...Oak is looking for you", which sent every starter-segment agent into its own
        # house to talk to Mom for 1800 steps.
        for (m, x, y, f) in [s for s in interaction_spots(maps, "WAIT") if s[0] == 0x00]:
            if pos == (m, x, y):
                return f, f"goal first pokemon: standing where OAK appeared; stepping {f} to fire the event again"
            p = g.path(pos, lambda n: n == (m, x, y))
            if p:
                return p[0], f"goal first pokemon: {len(p)} steps to where OAK appeared ({x},{y}) on map 0x{m:02X}"
    if goals.get("first_pokemon") and not goals.get("won_battle") and pos[0] == 0x28:
        # The rival only challenges you when you try to leave the lab: head for the exit (a learned warp out of
        # 0x28 if we have one, else the lowest visited tile - the door is on the bottom edge).
        p = g.path(pos, lambda n: n[0] != 0x28)
        if p is not None and p:
            return p[0], f"goal first battle: walking to the lab exit so the rival challenges us ({len(p)} steps)"
        d = maps.get(str(0x28), {})
        tiles = [tuple(map(int, k.split(","))) for k in d.get("visited", {})]
        if tiles:
            tx, ty = max(tiles, key=lambda t: (t[1], -abs(t[0] - 4)))
            if (pos[1], pos[2]) != (tx, ty):
                p = g.path(pos, lambda n: n == (0x28, tx, ty))
                if p:
                    return p[0], f"goal first battle: heading to the bottom of the lab ({tx},{ty}) to find the door"
            return "DOWN", "goal first battle: at the lowest known tile, trying DOWN for the door"
    level = goals.get("_level", 0)
    carrying_parcel = goals.get("oaks_parcel") and not goals.get("deliver_parcel")
    # Past Viridian (Route 2, its gates, the Forest, Pewter) never turn back to grind: that yo-yo burned 600+ steps of
    # 1800 per run (2026-11-03 05:54 round: 6 of 8 runs ran out of steps in the Forest, 360-560 steps spent in Viridian/Route 1).
    beyond_viridian = bool(goals.get("deliver_parcel")) and pos[0] in (0x0D, 0x2F, 0x31, 0x32, 0x33, 0x34, 0x02, 0x36)
    if (goals.get("won_battle") and goals.get("to_route1") and 0 < level < goals.get("_train_level", 8) and mx and hp / mx >= 0.5
            and not carrying_parcel and not beyond_viridian):
        # (never while carrying Oak's parcel: delivering it came last in every deliver_parcel run because this branch
        #  sent the agent back to Route 1 to train - they spent 600+ presses there and never reached the lab)
        # Training: wander the Route 1 grass while healthy; wild battles are fought (FIGHT), fled when weak.
        if pos[0] != 0x0C:
            p = g.path(pos, lambda n: n[0] == 0x0C)
            if p:
                return p[0], f"goal train to L{goals.get('_train_level', 8)} (now L{level}, HP {hp}/{mx}): {len(p)} steps back to Route 1"
        return None  # on Route 1: let exploration roam (grass encounters happen on their own)
    if goals.get("to_viridian") and not goals.get("oaks_parcel"):
        # Already known from earlier agents: the spot where "got OAK PARCEL" was seen. Go there and talk (known facts first).
        known = [tuple(goals["_parcel_spot"])] if goals.get("_parcel_spot") else []  # (map, x, y, facing) from the item log
        for (m, x, y, f) in known + interaction_spots(maps, "OAK PARCEL") + interaction_spots(maps, "PARCEL"):
            if pos == (m, x, y):
                return ("A" if facing == f else f), f"goal parcel: at the mart clerk spot ({x},{y}), {'talking' if facing == f else 'facing him'}"
            p = g.path(pos, lambda n: n == (m, x, y))
            if p:
                return p[0], f"goal parcel: {len(p)} steps to the known mart clerk spot ({x},{y}) on map 0x{m:02X}"
        # The parcel is at the Viridian Mart: explore Viridian's buildings - take warps on map 0x01 never taken yet.
        if pos[0] == 0x01:
            d = maps.get("1", {})
            fresh = [k for k in d.get("warps", {}) if d.get("warp_taken", {}).get(k, 0) == 0]
            for k in fresh:
                wx, wy, wd = k.split(",")
                target = (0x01, int(wx), int(wy))
                if pos == target:
                    return wd, f"goal parcel: trying an unexplored door at ({wx},{wy})"
                p = g.path(pos, lambda n: n == target)
                if p:
                    return p[0], f"goal parcel: {len(p)} steps to an unexplored door at ({wx},{wy})"
        elif pos[0] not in (0x00, 0x0C, 0x25, 0x26, 0x28):
            return None  # inside a Viridian building: explore it (talk to the clerk - the parcel is a bag change)
        else:
            p = g.path(pos, lambda n: n[0] == 0x01)
            if p:
                return p[0], f"goal parcel: {len(p)} steps back to Viridian City"
    if goals.get("oaks_parcel") and not goals.get("deliver_parcel"):
        if pos[0] == 0x28:
            # Talk to PROF. OAK himself: the tile+facing where an interaction's text starts with his speaker tag
            # ("OAK BCN, raise your young POKeMON...") - NOT the aides or the rival. Oak stands static at (5,2).
            oak = [s for s in interaction_spots(maps, "RAISE YOUR") + interaction_spots(maps, "OAK B") if s[0] == 0x28]
            for (m, x, y, f) in oak:
                if pos == (m, x, y):
                    return ("A" if facing == f else f), f"goal deliver the parcel: at Oak's spot ({x},{y}), {'talking' if facing == f else 'facing him'}"
                p = g.path(pos, lambda n: n == (m, x, y))
                if p:
                    return p[0], f"goal deliver the parcel: {len(p)} steps to Oak at ({x},{y})"
            return None  # unknown yet: exploration talks to the NPCs
        p = g.path(pos, lambda n: n[0] == 0x28)
        if p:
            return p[0], f"goal deliver the parcel: {len(p)} steps to Oak's lab"
    after_parcel = goals.get("deliver_parcel") and not goals.get("beat_brock")
    if (goals.get("first_pokemon") and not goals.get("to_viridian")) or after_parcel:
        # The road north: Route 1 (0x0C), Viridian (0x01), then (parcel delivered, the old man steps aside) Route 2 (0x0D)
        # and Pewter City (0x02). Use known transitions if any; otherwise push to the northernmost explored tile of the
        # current outdoor map and keep going UP (map edges are connections).
        if after_parcel:
            target_map = (0x36 if goals.get("to_pewter") else 0x02) if goals.get("to_route2") else 0x0D
        else:
            target_map = 0x01 if goals.get("to_route1") else 0x0C
        p = g.path(pos, lambda n: n[0] == target_map)
        if p:
            return p[0], f"goal road north: {len(p)} steps to map 0x{target_map:02X}"
        if target_map == 0x36 and pos[0] != 0x36:
            # The gym door is not mapped yet: get to Pewter (a blackout respawns at the Viridian Pokecenter), then let
            # exploration find the gym - the 'northernmost tile' fallback below is for unmapped ROADS, not a city.
            p = g.path(pos, lambda n: n[0] == 0x02)
            if p:
                return p[0], f"goal gym: {len(p)} steps to Pewter City"
            if pos[0] == 0x02:
                return None
        outdoors = (0x00, 0x0C, 0x01, 0x0D, 0x02)
        passage = after_parcel and (0x2F <= pos[0] <= 0x34 or pos[0] == 0x36)  # Route 2 gates and Viridian Forest are on the road: do not leave them
        if passage:
            outdoors = outdoors + (pos[0],)
        if pos[0] not in outdoors:  # indoors (house, lab): get outside first - never probe house walls for a road
            p = g.path(pos, lambda n: n[0] in outdoors)
            if p:
                return p[0], f"goal road north: leaving map 0x{pos[0]:02X} for the outdoors ({len(p)} steps)"
            if pos[0] in POKECENTER_MAPS:  # exit warp never recorded ('seen once' gate): every center's door is straight down x=3
                if pos[1] != 3:
                    return ("RIGHT" if pos[1] < 3 else "LEFT"), "goal road north: crossing the Pokecenter to its door column"
                return "DOWN", "goal road north: walking out of the Pokecenter by its door"
            return None
        if pos[0] == 0x00:  # in Pallet Town: Route 1 is the known way north
            p = g.path(pos, lambda n: n[0] == 0x0C)
            if p:
                return p[0], f"goal road north: {len(p)} steps to Route 1"
        d = maps.get(str(pos[0]), {})
        blocked = set(d.get("blocked", []))
        # candidate frontier tiles: northernmost first, but never one whose UP is a confirmed wall (that was the
        # 'keeps pushing up into a wall' loop); a tile only counts if UP from it is still unknown
        tiles = [tuple(map(int, k.split(","))) for k in d.get("visited", {})]
        tiles = [t for t in tiles if f"{t[0]},{t[1]},UP" not in blocked and f"{t[0]},{t[1] - 1}" not in d.get("visited", {})]
        # northernmost first, but a tile this agent cannot reach (Route 2's far north half, known only from a
        # different entry) must not block the next one: that left agents in a ledge loop with no plan
        for tx, ty in sorted(tiles, key=lambda t: (t[1], abs(t[0] - pos[1])))[:8]:  # each try is a BFS: bound the cost
            if (pos[1], pos[2]) == (tx, ty):
                if (tx, ty - 1) in g.static_npc_tiles(pos[0]):  # a person blocks the way (Brock at the top of the gym): talk
                    return ("A" if facing == "UP" else "UP"), "goal road north: a person stands ahead - facing and talking to them"
                return "UP", "goal road north: at the northernmost open tile, pushing UP for the map edge"
            p = g.path(pos, lambda n, tx=tx, ty=ty: n == (pos[0], tx, ty))
            if p:
                return p[0], f"goal road north: {len(p)} steps to the northernmost known tile ({tx},{ty})"
    return None
