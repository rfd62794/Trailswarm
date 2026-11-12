"""progress_export: the allow-list map progress export and its standalone CLI (synthetic data only)."""
import copy
import importlib.util
import json
import random
import sys
from pathlib import Path

import pytest

from pokeagent.share.progress_export import OUTPUT_MAP_FIELDS, export_progress

TOOLS = Path(__file__).resolve().parents[1] / "tools"
GAME = "pokemon-red"
TOP_KEYS = {"schema_version", "kind", "game", "maps", "totals"}


def _load(name):
    spec = importlib.util.spec_from_file_location(f"tool_{name}_pe", TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


cli = _load("export_progress")


def raw(out):
    return json.dumps(out, indent=1).encode("utf-8")


def small_doc():
    return {"maps": {
        "37": {"visited": {"3,7": 9, "3,6": 5}, "blocked": ["4,1,UP"], "warps": {"7,2,UP": [0, 5, 6]},
               "last_seen": 812},
        "0": {"visited": {"10,2": 1}, "blocked": ["2,2,RIGHT", "1,9,DOWN", "2,2,RIGHT"], "warps": {},
              "last_seen": 3},
    }, "updated": 1700000000}


def test_shape_and_values():
    out, st = export_progress(small_doc(), GAME)
    assert out == {
        "schema_version": 1, "kind": "trailswarm-progress-export", "game": "pokemon-red",
        "maps": {
            "0": {"walkable": [[10, 2]], "blocked": [[1, 9, "DOWN"], [2, 2, "RIGHT"]], "warps": [],
                  "stats": {"walkable_tiles": 1, "blocked_edges": 2, "warps": 0, "total_visits": 1}},
            "37": {"walkable": [[3, 6], [3, 7]], "blocked": [[4, 1, "UP"]],
                   "warps": [{"from": [7, 2, "UP"], "to": [0, 5, 6]}],
                   "stats": {"walkable_tiles": 2, "blocked_edges": 1, "warps": 1, "total_visits": 14}},
        },
        "totals": {"maps": 2, "walkable_tiles": 3, "blocked_edges": 3, "warps": 1},
    }
    assert list(out["maps"]) == ["0", "37"]
    assert (st.maps_kept, st.maps_dropped, st.tiles_dropped, st.blocked_dropped, st.warps_dropped) == \
        (2, 0, 0, 0, 0)


class Marks:
    def __init__(self):
        self.used = []

    def __call__(self, tag="A"):
        m = f"MARK_{tag}{len(self.used) + 1:02d}"
        self.used.append(m)
        return m


def marked_doc():
    k = Marks()

    def entry():
        return {
            "visited": {"3,6": 4, "3,7": 2, "3,6" + k("C"): 1, "5,5": k("D")},
            "blocked": ["4,1,UP", "4,1,UP" + k("E")],
            "warps": {"7,2,UP": [0, 5, 6], "8,2,UP": [k("F"), 1, 2], "9,2,UP" + k("F"): [1, 2, 3]},
            "last_seen": 99,
            "interactions": {"4,4,UP": {"count": 3, "text": k(), "presses": [k()], "effects": [k()],
                                        "menus": [k()], "choices": [k()], "outcomes": {k(): 1},
                                        "screens": {k(): 2}, "transitions": [k()], "npc": {"name": k()},
                                        "future_field_x": k()}},
            "npcs": {"slot1:pic" + k(): {"pic": 4, "slot": 1, "positions": {k(): 2}, "first_seen": 1,
                                         "text": k(), "talked": 1, "moves": True, "last": [1, 2],
                                         "results": {k(): k()}}},
            "items": {"6,6": {"pic": 61, "text": k(), "item": k(), "seen": 1, "picked": 0}},
            "demos": [{"at": [1, 2], "facing": k(), "screen": [k(), k()], "buttons": [k()], "achieved": [k()],
                       "source": k()}],
            "jumps": {"1,1,DOWN": [1, 3]},
            "future_field_x": {"nested": k(), k(): {"future_field_x": k()}},
        }

    doc = {
        "maps": {"37": entry(), "37" + k("B"): entry(), "12": [k()]},
        "updated": k(),
        "menus": {k(): [k()]}, "events": [k()], "items": {k(): k()}, "catches": [{"name": k()}],
        "trainers": {k(): {"text": k()}}, "battle_lessons": [k()], "procedures": {k(): [k()]},
        "future_field_x": k(), "another_new_top": {k(): [k()]},
    }
    return doc, k.used


def test_markers_in_every_text_and_unknown_field_never_reach_the_output_bytes(tmp_path):
    doc, marks = marked_doc()
    assert len(marks) == len(set(marks)) >= 40
    assert all(raw(doc).count(m.encode()) == 1 for m in marks)
    out, st = export_progress(doc, GAME)
    data = raw(out)
    assert out["totals"]["maps"] >= 1 and out["totals"]["walkable_tiles"] >= 1
    assert out["maps"]["37"]["warps"] == [{"from": [7, 2, "UP"], "to": [0, 5, 6]}]
    for m in marks:
        assert m.encode() not in data, m
    assert b"MARK" not in data
    src, dst = tmp_path / "maps.json", tmp_path / "export.json"
    src.write_text(json.dumps(doc), encoding="utf-8")
    assert cli.main([str(src), "--game", GAME, "--out", str(dst)]) == 0
    written = dst.read_bytes()
    assert json.loads(written)["totals"]["maps"] >= 1
    for m in marks:
        assert m.encode() not in written, m
    assert b"MARK" not in written


def test_unknown_future_field_is_dropped_by_default():
    doc = small_doc()
    doc["brand_new_stat"] = 5
    doc["maps"]["37"]["brand_new_stat"] = 5
    out, _ = export_progress(doc, GAME)
    assert b"brand_new_stat" not in raw(out)
    for entry in out["maps"].values():
        assert set(entry) == set(OUTPUT_MAP_FIELDS)


def test_output_field_names_are_pinned():
    assert OUTPUT_MAP_FIELDS == ("walkable", "blocked", "warps", "stats")
    out, _ = export_progress(small_doc(), GAME)
    assert set(out) == TOP_KEYS
    assert set(out["totals"]) == {"maps", "walkable_tiles", "blocked_edges", "warps"}
    assert set(out["maps"]["37"]["stats"]) == {"walkable_tiles", "blocked_edges", "warps", "total_visits"}


def test_rejects_unknown_game_and_bad_documents():
    with pytest.raises(ValueError):
        export_progress(small_doc(), "mario-land")
    with pytest.raises(ValueError):
        export_progress([small_doc()], GAME)
    with pytest.raises(ValueError):
        export_progress({"updated": 1}, GAME)
    with pytest.raises(ValueError):
        export_progress({"maps": [1, 2]}, GAME)


def test_malformed_entries_are_dropped_and_counted():
    doc = {"maps": {
        "1": {"visited": {"1,1": 2, "256,1": 1, "1,999": 1, "2,2": True, "3,3": -1, "4,4": 1.5},
              "blocked": ["1,1,UP", "1,256,UP", "1,1,NORTH", 7, "1,1,UP\n"],
              "warps": {"1,1,UP": [2, 3, 4], "2,2,UP": [2, 3], "3,3,UP": [2, 3, 256], "4,4,UP": [True, 1, 1],
                        "300,1,UP": [1, 1, 1]}},
        "256": {"visited": {"1,1": 1}},
        "-1": {"visited": {"1,1": 1}},
        "2": "not a dict",
        "3": None,
    }}
    out, st = export_progress(doc, GAME)
    assert list(out["maps"]) == ["1"]
    m = out["maps"]["1"]
    assert m["walkable"] == [[1, 1]] and m["stats"]["total_visits"] == 2
    assert m["blocked"] == [[1, 1, "UP"]]
    assert m["warps"] == [{"from": [1, 1, "UP"], "to": [2, 3, 4]}]
    assert (st.maps_kept, st.maps_dropped, st.tiles_dropped, st.blocked_dropped, st.warps_dropped) == \
        (1, 4, 5, 4, 4)


def test_deterministic_and_input_not_mutated():
    doc, _ = marked_doc()
    doc["maps"].update(small_doc()["maps"])
    before = copy.deepcopy(doc)
    first = raw(export_progress(doc, GAME)[0])
    assert doc == before

    def shuffled(v, rng):
        if isinstance(v, dict):
            items = list(v.items())
            rng.shuffle(items)
            return {k: shuffled(x, rng) for k, x in items}
        if isinstance(v, list):
            return [shuffled(x, rng) for x in v]
        return v

    for seed in range(5):
        rng = random.Random(seed)
        other = shuffled(doc, rng)
        other["maps"]["0"]["blocked"].reverse()
        assert raw(export_progress(other, GAME)[0]) == first
    assert doc == before


def test_cli_happy_path_and_bad_input(tmp_path, capsys):
    src, dst = tmp_path / "maps.json", tmp_path / "out.json"
    src.write_text(json.dumps(small_doc()), encoding="utf-8")
    assert cli.main([str(src), "--game", GAME, "--out", str(dst)]) == 0
    text = dst.read_text(encoding="utf-8")
    assert text == json.dumps(export_progress(small_doc(), GAME)[0], indent=1) + "\n"
    assert "kept maps=2 tiles=3 blocked=3 warps=1; dropped maps=0 tiles=0 blocked=0 warps=0" in \
        capsys.readouterr().err
    assert sorted(p.name for p in tmp_path.iterdir()) == ["maps.json", "out.json"]

    bad, nofile = tmp_path / "bad.json", tmp_path / "never.json"
    bad.write_text("{not json", encoding="utf-8")
    assert cli.main([str(bad), "--game", GAME, "--out", str(nofile)]) == 2
    assert not nofile.exists()
    assert cli.main([str(src), "--game", "mario-land", "--out", str(nofile)]) == 2
    assert not nofile.exists()
    nomaps = tmp_path / "nomaps.json"
    nomaps.write_text(json.dumps({"updated": 1}), encoding="utf-8")
    assert cli.main([str(nomaps), "--game", GAME, "--out", str(nofile)]) == 2
    assert cli.main([str(tmp_path / "missing.json"), "--game", GAME, "--out", str(nofile)]) == 2
    assert not nofile.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bad.json", "maps.json", "nomaps.json", "out.json"]


def test_cli_does_not_modify_the_input_file(tmp_path):
    doc, _ = marked_doc()
    src = tmp_path / "maps.json"
    src.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    before = src.read_bytes()
    assert cli.main([str(src), "--game", GAME, "--out", str(tmp_path / "out.json")]) == 0
    assert src.read_bytes() == before
    assert cli.main([str(src), "--game", GAME, "--out", str(src)]) == 2
    assert src.read_bytes() == before
