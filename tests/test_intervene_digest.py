"""Situation digest and stuck signals: pure, from recorded snapshot-shaped fixtures (no ROM)."""
from pokeagent.intervene.digest import digest_agent, format_block, format_table, rank, stage_of
from pokeagent.intervene.names import item_id, map_id, map_name, pretty
from pokeagent.intervene.stuck import stuck_signals
from pokeagent.goals import GOALS, SIDE_GOALS

LADDER = [g for g in GOALS if g not in SIDE_GOALS]


def goals(done: int) -> list[dict]:
    return [{"id": g, "name": g, "status": "done" if i < done else ("current" if i == done else "ahead")}
            for i, g in enumerate(LADDER)]


def dec(rule="frontier", btn="UP", out="moved", x=1, y=1, bx=False, bt=False, d="agent", s=0):
    return {"s": s, "r": rule, "b": btn, "m": 59, "x": x, "y": y, "o": out, "bx": bx, "bt": bt, "d": d}


def snap(aid="explore-1", done=3, step=100, extra=None, **kw):
    base = {"agent_id": aid, "state": "running", "step": step, "goals": goals(done), "human_hold": False, "claude_hold_s": 0,
            "screen": {"box_text": "", "in_battle": False, "money": 1234,
                       "party": [{"species": "WARTORTLE", "level": 24, "hp": 11, "max_hp": 57}]},
            "sees": {"rows": [], "mode": "overworld"},
            "extra": {"map": 59, "x": 12, "y": 34, "mode": "overworld", "battle": None, "bag": {"POTION": 0, "POKé BALL": 5},
                      "decisions": [], "box_hist": []}}
    base.update(kw)
    if extra:
        base["extra"].update(extra)
    return base


BATTLE = {"kind": "wild", "you": {"species": "WARTORTLE", "level": 24, "hp": 11, "max": 57},
          "enemy": {"species": "RATTATA", "level": 12, "hp": 8, "max": 20}}


def test_names():
    assert pretty("MT_MOON_B2F") == "Mt Moon B2F" and pretty("ROUTE_1") == "Route 1" and pretty("PALLET_TOWN") == "Pallet Town"
    assert map_name(0) == "Pallet Town" and map_name(9999) == "map 9999"
    assert map_id("Pallet Town") == 0 and map_id("0x0C") == 12 and map_id("ROUTE_1") == 12 and map_id("nowhere") is None
    assert item_id("nope") is None


def test_stage_and_overworld_digest():
    assert stage_of(goals(0)) == (LADDER[0], 0) and stage_of(goals(3)) == (LADDER[3], 3)
    d = digest_agent(snap(done=18))
    assert d["id"] == "explore-1" and (d["x"], d["y"]) == (12, 34) and d["mode"] == "overworld"
    assert d["stage"] == LADDER[18] and d["done"] == 18 and d["money"] == 1234
    assert d["party"] == ["WARTORTLE L24 11/57"] and d["bag"] == {"POTION": 0, "POKé BALL": 5} and d["potions"] is False
    assert d["stuck"] == [] and d["battle_text"] == ""
    assert "Pallet Town (12,34)" not in format_block(d)  # map 59 is not Pallet; a real name or "map N" appears
    assert "NO POTION" in format_block(d)


def test_battle_digest_and_last_8_decisions():
    decs = [dec(rule=f"r{i}", btn="A", s=i) for i in range(12)] + [dec(rule="remote_press", btn="B", d="claude")]
    d = digest_agent(snap(extra={"mode": "battle", "battle": BATTLE, "decisions": decs}))
    assert d["mode"] == "battle" and d["battle_text"] == "wild: WARTORTLE L24 11/57 vs RATTATA L12 8/20"
    assert len(d["decisions"]) == 8 and d["decisions"][-1] == "remote_press:B*claude" and d["decisions"][0] == "r5:A"
    assert "battle: wild: WARTORTLE" in format_block(d)


def test_item_loop_is_a_stuck_reason():
    s = snap(screen={"box_text": "It won't have any effect.", "in_battle": True, "money": 1, "party": []},
             extra={"mode": "battle", "battle": BATTLE, "decisions": [dec(rule="item_open", btn="A", out="box", bx=True, bt=True)] * 3})
    kinds = {x["kind"] for x in stuck_signals(s)}
    assert "item_loop" in kinds
    d = digest_agent(s)
    assert "item_loop" in format_table([d]) and "won't have any effect" in format_block(d)
    # the apostrophe glyph is lost on screen: "won t" / "wont" still match
    s2 = snap(extra={"box_hist": ["It won t have any effect.", "", "It won t have any effect."]})
    assert [x["kind"] for x in stuck_signals(s2)] == ["item_loop"]


def test_rule_repeat_needs_no_progress():
    stuck = snap(extra={"decisions": [dec(rule="bump", btn="UP", out="blocked", x=5, y=5)] * 12})
    assert [x["kind"] for x in stuck_signals(stuck)][0] == "rule_repeat"
    walking = snap(extra={"decisions": [dec(rule="frontier", out="moved", x=i, y=0) for i in range(12)]})
    assert stuck_signals(walking) == []
    claude = snap(extra={"decisions": [dec(rule="bump", out="blocked", d="claude")] * 12})
    assert stuck_signals(claude) == []  # Claude's own presses are never the agent's loop


def test_no_new_tile_box_repeat_and_stall_guard():
    pacing = snap(extra={"decisions": [dec(rule=f"r{i % 5}", out="none", x=i % 2, y=3) for i in range(30)]})
    assert any(s["kind"] == "no_new_tile" for s in stuck_signals(pacing))
    fighting = snap(extra={"decisions": [dec(rule=f"r{i % 5}", out="box", bt=True) for i in range(30)]})
    assert not any(s["kind"] == "no_new_tile" for s in stuck_signals(fighting))  # standing still in a fight is normal
    boxes = snap(extra={"box_hist": ["Welcome to the shop", "Welcome to the shop", "Welcome to the shop", "Welcome to the shop"]})
    assert any(s["kind"] == "box_repeat" for s in stuck_signals(boxes))
    esc = snap(extra={"decisions": [dec(rule="frontier")] * 3 + [dec(rule="stall_escalate", btn="START", out="none")]})
    assert any(s["kind"] == "stall_guard" for s in stuck_signals(esc))
    menu = snap(extra={"box_hist": [">FIGHT PKMN | ITEM RUN"] * 6})
    assert stuck_signals(menu) == []  # the battle menu between turns is not a repeated box
    assert stuck_signals({**pacing, "state": "paused"}) == [] and stuck_signals({**pacing, "human_hold": True}) == []
    assert stuck_signals({**pacing, "claude_hold_s": 30.0}) == []


def test_ranking_closest_first_and_table():
    ds = [digest_agent(snap("a", done=3, step=500)), digest_agent(snap("b", done=18, step=100)),
          digest_agent(snap("c", done=18, step=900, claude_hold_s=42.0))]
    assert [d["id"] for d in rank(ds)] == ["c", "b", "a"]
    table = format_table(ds + [{"id": "dead", "error": "connection refused"}])
    rows = table.splitlines()
    assert rows[0].startswith("c") and "HELD:claude 42s" in rows[0] and rows[1].startswith("b") and rows[3].startswith("dead")
    assert "unreachable: connection refused" in rows[3]
    assert format_table([]) == "no agents registered"
