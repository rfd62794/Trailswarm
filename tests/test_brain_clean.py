"""brain clean: the planner rules, the journal it writes, undo, and the CLI's dry-run/--write guards."""
import copy
import json

from pokeagent import cli_brain
from pokeagent.brain import fileops
from pokeagent.brain.cleanplan import plan_clean, unreachable_npcs
from pokeagent.explorer import edits


def _doc():
    return {"maps": {"5": {
        "visited": {"1,1": 1}, "blocked": [], "warps": {},
        "interactions": {
            "1,1,UP": {"count": 2, "text": "A sign about trees", "done": True},
            "2,2,UP": {"count": 1, "text": "Hello there",
                       "pages": ["Hello there", "Wild FOXLY fainted!", "Now saving the game"]},
            "3,3,UP": {"count": 4, "text": "Someone turned on the PC.", "type": "pc"},
            "3,3,LEFT": {"count": 1, "text": "Someone turned on the PC.", "done": True},
            "4,4,UP": {"count": 1, "text": "Plain words", "type": "info", "type_votes": {"info": 2, "sign": 1},
                       "type_conf": 0.67, "type_why": "no effect"},
            "6,6,UP": {"count": 1, "text": "Quiet"},
        },
        "npcs": {
            "slot1:pic1": {"pic": 1, "slot": 1, "last": [7, 7], "results": {"count": 1, "text": "Take it", "done": True}},
            "slot2:pic2": {"pic": 2, "slot": 2, "last": [7, 7],
                           "results": {"count": 1, "text": "Bye", "done": False, "pages": ["Bye", "BUGGO used BITE!"]}},
            "slot3:pic3": {"pic": 3, "slot": 3, "results": {"count": 1, "text": "lost", "done": True}},
        },
    }}}


def _ops(plan, key):
    return sorted((p["op"], p["value"], p["note"]) for p in plan if p["key"] == key)


def _apply(doc, plan):
    recs = []
    for i, p in enumerate(plan):
        mid, key, value = edits.prepare(p["op"], p["map"], p["key"], p["value"])
        recs.append({"id": f"e{i}", "op": p["op"], "map": mid, "key": key, "value": value, "note": p["note"]})
    return edits.apply(copy.deepcopy(doc), recs)


def _write_maps(tmp_path, doc=None):
    path = tmp_path / "maps.json"
    path.write_text(json.dumps(doc or _doc()), encoding="utf-8")
    return path


def _journal(path):
    jp = fileops.journal_for(path)
    return [json.loads(line) for line in jp.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_interaction_done_flag_is_cleared():
    plan = plan_clean(_doc())
    assert _ops(plan, "1,1,UP") == [("interaction_state_clear", "done", "playthrough_state_done")]
    assert "done" not in _apply(_doc(), plan)["maps"]["5"]["interactions"]["1,1,UP"]


def test_npc_results_done_flag_is_cleared():
    plan = plan_clean(_doc())
    assert ("npc_state_clear", "done", "playthrough_state_done") in _ops(plan, "7,7")
    npcs = _apply(_doc(), plan)["maps"]["5"]["npcs"]
    assert "done" not in npcs["slot1:pic1"]["results"] and "done" not in npcs["slot2:pic2"]["results"]
    assert npcs["slot3:pic3"]["results"]["done"] is True  # no last tile: unreachable


def test_battle_and_menu_pages_pruned_ordinary_page_stays():
    plan = plan_clean(_doc())
    assert _ops(plan, "2,2,UP") == [("interaction_prune", "battle_menu", "battle_text")]
    e = _apply(_doc(), plan)["maps"]["5"]["interactions"]["2,2,UP"]
    assert e["pages"] == ["Hello there"] and e["text"] == "Hello there"


def test_untyped_bogus_facing_cleared_beside_typed_pc():
    plan = plan_clean(_doc())
    assert _ops(plan, "3,3,LEFT") == [("interaction_clear", None, "contradicts_typed_pc")]  # no other edit
    assert _ops(plan, "3,3,UP") == []
    inters = _apply(_doc(), plan)["maps"]["5"]["interactions"]
    assert "3,3,LEFT" not in inters and inters["3,3,UP"]["type"] == "pc"


def test_conflicting_type_votes_clear_type():
    plan = plan_clean(_doc())
    assert _ops(plan, "4,4,UP") == [("interaction_state_clear", "type", "conflicting_type_votes")]
    e = _apply(_doc(), plan)["maps"]["5"]["interactions"]["4,4,UP"]
    assert not {"type", "type_conf", "type_why"} & set(e) and e["type_votes"] == {"info": 2, "sign": 1}


def test_conflicting_votes_without_type_plans_nothing():
    doc = {"maps": {"5": {"interactions": {"4,4,UP": {"count": 1, "text": "x", "type_votes": {"a": 1, "b": 1}}}}}}
    assert plan_clean(doc) == []


def test_npc_edits_are_deduped_per_tile():
    doc = _doc()
    doc["maps"]["5"]["npcs"]["slot2:pic2"]["results"]["done"] = True
    plan = plan_clean(doc)
    assert [p["op"] for p in plan if p["key"] == "7,7"].count("npc_state_clear") == 1
    assert not [p for p in plan if p["key"] is None]
    assert unreachable_npcs(doc) == 1


def test_clear_and_prune_on_one_npc_tile_both_apply():
    plan = plan_clean(_doc())
    assert _ops(plan, "7,7") == [("npc_prune", "battle_menu", "battle_text"),
                                 ("npc_state_clear", "done", "playthrough_state_done")]
    r = _apply(_doc(), plan)["maps"]["5"]["npcs"]["slot2:pic2"]["results"]
    assert r["pages"] == ["Bye"] and "done" not in r


def test_prune_undo_deletes_keys_the_entry_never_had():
    doc = {"maps": {"5": {"interactions": {"1,1,UP": {"count": 1, "text": "Wild RATTO fainted!"}}}}}
    prior = edits.prior_state(copy.deepcopy(doc), "interaction_prune", 5, "1,1,UP", "battle_menu")
    rec = {"id": "p", "op": "interaction_prune", "map": 5, "key": "1,1,UP", "value": "battle_menu", "prior": prior}
    pruned = edits.apply(copy.deepcopy(doc), [rec])
    assert pruned["maps"]["5"]["interactions"]["1,1,UP"] == {"count": 1, "text": ""}
    undone = edits.apply(copy.deepcopy(doc), [rec, {"id": "u", "op": "undo", "map": 5, "key": "1,1,UP", "value": "p"}])
    assert "pages" not in undone["maps"]["5"]["interactions"]["1,1,UP"]
    assert undone == doc


def test_dry_run_writes_nothing(tmp_path, capsys):
    path = _write_maps(tmp_path)
    before = path.read_bytes()
    assert cli_brain.main(["clean", "--maps", str(path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["planned"] == len(plan_clean(_doc()))
    assert "Hello there" not in json.dumps(out) and "Take it" not in json.dumps(out)
    assert not fileops.journal_for(path).exists() and path.read_bytes() == before


def test_write_appends_journal_with_prior_and_never_touches_maps_json(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(fileops, "live_agents", lambda _p: [])
    path = _write_maps(tmp_path)
    before = path.read_bytes()
    assert cli_brain.main(["clean", "--write", "--maps", str(path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "fold" in out["reminder"] and "before any agent starts" in out["reminder"]
    recs = _journal(path)
    assert recs and path.read_bytes() == before
    assert all(r["prior"] is not None and r["by"] == "brain-clean" and r["note"] for r in recs)


def test_write_refuses_while_an_agent_is_alive(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(fileops, "live_agents", lambda _p: ["agent-1"])
    path = _write_maps(tmp_path)
    assert cli_brain.main(["clean", "--write", "--maps", str(path)]) == 1
    assert "agent-1" in capsys.readouterr().out
    assert not fileops.journal_for(path).exists()


def _leaves(obj, prefix=()):
    if isinstance(obj, dict) and obj:
        for k, v in obj.items():
            yield from _leaves(v, prefix + (k,))
    else:
        yield prefix, json.dumps(obj, sort_keys=True)


def test_every_planned_item_is_in_the_journal(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(fileops, "live_agents", lambda _p: [])
    path = _write_maps(tmp_path)
    plan = plan_clean(_doc())
    assert cli_brain.main(["clean", "--write", "--maps", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["skipped_noop"] == 0
    recs = _journal(path)
    assert len(recs) == len(plan)
    assert [(r["op"], r["map"], r["key"], r["value"], r["note"]) for r in recs] == \
        [(p["op"], p["map"], p["key"], p["value"], p["note"]) for p in plan]
    cleaned = edits.apply(_doc(), recs)
    before, after = dict(_leaves(_doc())), dict(_leaves(cleaned))
    changed = {p for p in set(before) | set(after) if before.get(p) != after.get(p)}
    planned = {(str(p["map"]), p["key"]) for p in plan}
    tile_of = {nid: f"{n['last'][0]},{n['last'][1]}" for nid, n in _doc()["maps"]["5"]["npcs"].items() if "last" in n}
    touched = set()
    for p in changed:
        assert p[0] == "maps"
        key = p[3] if p[2] == "interactions" else tile_of[p[3]]
        assert (p[1], key) in planned, p
        touched.add((p[1], key))
    assert touched == planned  # every planned item removed something, nothing else changed


def test_clean_then_undo_all_restores_the_original(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(fileops, "live_agents", lambda _p: [])
    path = _write_maps(tmp_path)
    assert cli_brain.main(["clean", "--write", "--maps", str(path)]) == 0
    recs = _journal(path)
    undos = [{"id": f"u{i}", "op": "undo", "map": r["map"], "key": r["key"], "value": r["id"]}
             for i, r in enumerate(reversed(recs))]
    assert edits.apply(_doc(), recs + undos) == _doc()


def test_second_clean_has_an_empty_plan(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(fileops, "live_agents", lambda _p: [])
    path = _write_maps(tmp_path)
    assert cli_brain.main(["clean", "--write", "--maps", str(path)]) == 0
    capsys.readouterr()
    assert plan_clean(fileops.effective_data(path)[0]) == []
    assert cli_brain.main(["clean", "--maps", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["planned"] == 0
