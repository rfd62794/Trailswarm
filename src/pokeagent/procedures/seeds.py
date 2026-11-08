"""The committed seeds as code: seed_gauntlet builds a trainer gauntlet from ROM placement rows, so the JSON
under seeds/ is produced by a test-covered function, never retyped numbers (tests/test_procedures.py asserts
the committed files match these helpers' output for the directive's fixture tables).

Walking order is an ASSUMPTION (directive section 2): Route 24's main line is taken south to north by y
descending with the Rocket last; the off-line Jr.Trainer at (5,20) is an optional step.
"""
from __future__ import annotations

from pokeagent.procedures.schema import FIGHT_MAX_FRAMES, FIGHT_MAX_PRESSES, GOTO_MAX_FRAMES, GOTO_MAX_PRESSES

TRAINER_APPROACH = 3     # tiles before the trainer along the direction of travel (north: y + 3); untuned, unverified
ENTRY_REGION_DEPTH = 5   # the entry region reaches this many tiles behind the first approach tile (untuned)
ENTRY_REGION_PAD = 2     # and this many tiles to either side (untuned)

# S.S. Anne ROOM trainers (directive section 2): class, party #, map, x, y - optional gauntlet steps the seed
# lists but never blocks on. The 1F/2F corridors hold no ROM trainer besides the suspect RIVAL1 row, which the
# seed deliberately does NOT use (the rival comes from trainers.boss_party("rival_ss_anne")).
SHIP_ROOM_TRAINERS = [
    ("SAILOR", 1, 99, 4, 4), ("SAILOR", 2, 99, 10, 8),
    ("GENTLEMAN", 1, 102, 2, 3), ("GENTLEMAN", 2, 102, 11, 4), ("YOUNGSTER", 8, 102, 11, 14), ("LASS", 11, 102, 13, 11),
    ("GENTLEMAN", 3, 103, 10, 2), ("FISHERMAN", 1, 103, 13, 4), ("GENTLEMAN", 5, 103, 0, 14), ("LASS", 12, 103, 2, 11),
    ("SAILOR", 3, 104, 0, 13), ("SAILOR", 4, 104, 2, 11), ("SAILOR", 5, 104, 12, 3), ("SAILOR", 6, 104, 22, 2),
    ("SAILOR", 7, 104, 0, 2), ("FISHERMAN", 2, 104, 0, 4),
]
RIVAL_AT = [96, 36, 4]   # the 2F east end: the rival intercepts on the walk to the captain's door (ROM warp -> 0x65)


def _fight_step(sid: str, map_id: int, x: int, y: int, *, optional: bool = False, **action_extra) -> dict:
    beaten = {"trainer_beaten": [map_id, x, y]}
    return {"id": sid, "optional": optional,
            "pre": {"all": [{"map": map_id}, {"not": beaten}]},
            "action": {"kind": "behaviour", "name": "fight_trainer", "at": [map_id, x, y], **action_extra},
            "effect": {"all": [beaten]},
            "ok": 0, "fail": 0, "max_presses": FIGHT_MAX_PRESSES, "max_frames": FIGHT_MAX_FRAMES}


def seed_gauntlet(map_id: int, trainers: list, order=None, optional=()) -> list:
    """A gauntlet procedure's steps from placement rows ({class, party, x, y} like trainers_on() output).

    Per trainer, in walking order: a ``goto`` to its approach tile (TRAINER_APPROACH tiles before it along the
    direction of travel; the walk itself is the learned WorldGraph) then a ``fight_trainer`` step with effect
    ``trainer_beaten``. The first goto also carries the entry region and ``hp_frac_min 0.5``. ``order`` is a
    sort key on the row (default: south to north by y descending); rows in ``optional`` (a set of (x, y)) are
    appended last as ``optional: true`` steps off the main line.
    """
    order = order or (lambda t: -t["y"])
    opt = {(p[0], p[1]) for p in optional}
    main = sorted((t for t in trainers if (t["x"], t["y"]) not in opt), key=order)
    side = sorted((t for t in trainers if (t["x"], t["y"]) in opt), key=order)
    steps = []
    for t in main + side:
        is_opt = (t["x"], t["y"]) in opt
        ax, ay = t["x"], t["y"] + TRAINER_APPROACH
        if not steps:  # the entry goto: bridge south end, healthy enough to start the gauntlet
            pre = {"all": [{"map": map_id},
                           {"region": [map_id, ax - ENTRY_REGION_PAD, ay - ENTRY_REGION_DEPTH,
                                       ax + ENTRY_REGION_PAD, ay - 1]},
                           {"hp_frac_min": 0.5}]}
        else:
            pre = {"all": [{"map": map_id}, {"not": {"trainer_beaten": [map_id, t["x"], t["y"]]}}]}
        steps.append({"id": f"s{len(steps) + 1}", "optional": is_opt, "pre": pre,
                      "action": {"kind": "goto", "map": map_id, "x": ax, "y": ay},
                      "effect": {"all": [{"at": [map_id, ax, ay]}]},
                      "ok": 0, "fail": 0, "max_presses": GOTO_MAX_PRESSES, "max_frames": GOTO_MAX_FRAMES})
        steps.append(_fight_step(f"s{len(steps) + 1}", map_id, t["x"], t["y"], optional=is_opt))
    return steps


def seed_ss_anne() -> list:
    """The S.S. Anne corridor/boss-path seed: waypoint steps through maps 95 -> 96 (x/y null: the learned maps
    supply the warps at run time; a null tile is satisfied by arriving on the map), the rival boss fight at the
    corridor's east end (party from trainers.boss_party("rival_ss_anne"), NOT the suspect RIVAL1 row), then the
    room trainers of 99/102/103/104 as optional steps."""
    steps = []
    for m, came in ((95, 94), (96, 95)):
        steps.append({"id": f"s{len(steps) + 1}", "optional": False,
                      "pre": {"all": [{"map": came}]},
                      "action": {"kind": "goto", "map": m, "x": None, "y": None},
                      "effect": {"all": [{"map": m}]},
                      "ok": 0, "fail": 0, "max_presses": GOTO_MAX_PRESSES, "max_frames": GOTO_MAX_FRAMES})
    steps.append(_fight_step(f"s{len(steps) + 1}", 96, RIVAL_AT[1], RIVAL_AT[2], boss="rival_ss_anne"))
    for cls, pno, m, x, y in SHIP_ROOM_TRAINERS:
        steps.append(_fight_step(f"s{len(steps) + 1}", m, x, y, optional=True))
    return steps
