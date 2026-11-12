"""brain audit: one finding per class, counts and locations only, and the MEMORY_FACTS.md labels."""
import copy
import re
from pathlib import Path

from pokeagent.brain.audit import AREAS, TOP_LEVEL_AREAS, audit, summary

DOC = Path(__file__).resolve().parents[1] / "docs" / "MEMORY_FACTS.md"
FACT_TYPES = ("world fact (shareable)", "playthrough state (never shared)",
              "derived guess (shareable only with evidence)",
              "unclassified: treated as playthrough state (not shared)")
SECRET = "Zorbly the quokka hums"  # invented note text that must never reach the summary


def _doc():
    return {"maps": {"7": {
        "visited": {}, "blocked": [], "warps": {},
        "interactions": {
            "1,1,UP": "not a dict",
            "2,2,UP": {"count": 1, "text": ""},
            "3,3,UP": {"count": 2, "text": SECRET + " Wild RATTO fainted!"},
            "4,4,UP": {"count": 1, "text": "POKeDEX | something"},
            "5,5,UP": {"count": 1, "text": SECRET, "done": True},
            "6,6,UP": {"count": 140, "text": SECRET, "type": "pc"},
            "7,7,DOWN": {"count": 1, "text": "Someone turned on the PC."},
            "8,8,UP": {"count": 1, "text": SECRET, "type_votes": {"info": 1, "sign": 1}},
            "9,9,UP": {"count": 1, "text": "Same words"},
            "9,9,LEFT": {"count": 1, "text": "Same words"},
        },
        "npcs": {
            "slot1:pic1": {"pic": 1, "slot": 1, "last": [1, 2], "positions": {"1,2": 3, "1,3": 1},
                           "moves": False, "results": {"count": 1, "text": SECRET, "done": True}},
            "slot2:pic2": {"pic": 2, "slot": 2, "last": [2, 3], "positions": {"2,3": 1}, "moves": False,
                           "results": {"count": 1, "text": "", "pages": ["RATTO used TACKLE!"]}},
        },
        "demos": [{"at": [1, 1], "buttons": ["A"]}, {"at": [2, 2], "buttons": ["B"]}],
    }}, "beats": {"a": {}, "b": {}}, "bad_warps": ["7:1,1,UP"], "updated": "now", "zzz_new": 1}


def test_audit_counts_each_class():
    r = audit(_doc())
    c = r["counts"]
    assert c["interaction_not_a_dict"] == 1
    assert c["interaction_no_text"] == 1
    assert c["interaction_with_text"] == 8
    assert c["text_has_battle_lines"] == 1 and r["examples"]["text_has_battle_lines"] == "7:3,3,UP"
    assert c["text_has_menu_lines"] == 1 and r["examples"]["text_has_menu_lines"] == "7:4,4,UP"
    assert c["per_run_flag_done"] == 1 and r["examples"]["per_run_flag_done"] == "7:5,5,UP"
    assert c["type_pc_but_no_pc_in_text"] == 1
    assert c["pc_text_but_type_not_pc"] == 1 and r["examples"]["pc_text_but_type_not_pc"] == "7:7,7,DOWN"
    assert c["pressed_100_plus_times"] == 1
    assert c["conflicting_type_votes"] == 1
    assert c["same_text_on_several_facings_of_a_tile"] == 1
    assert r["examples"]["same_text_on_several_facings_of_a_tile"] == "7:9,9"
    assert c["npc_results_done"] == 1 and r["examples"]["npc_results_done"] == "7:slot1:pic1"
    assert c["npc_text_has_battle_lines"] == 1
    assert c["nonmoving_npc_many_positions"] == 1
    assert c["demos"] == 2
    assert r["top_level_sizes"] == {"bad_warps": 1, "beats": 2}
    assert r["top_level_keys"] == ["bad_warps", "beats", "maps", "updated", "zzz_new"]
    text = summary(r)
    assert SECRET not in text and "Zorbly" not in text and "Same words" not in text and "TACKLE" not in text
    assert "per_run_flag_done: 1 (first at 7:5,5,UP)" in text


def test_audit_does_not_mutate_input():
    doc = _doc()
    before = copy.deepcopy(doc)
    audit(doc)
    assert doc == before


def test_audit_reports_counts_per_area():
    r = audit(_doc())
    by = r["counts_by_area"]
    assert by["battle"] == {"npc_text_has_battle_lines": 1, "text_has_battle_lines": 1}
    assert by["progression"] == {"demos": 2, "npc_results_done": 1, "per_run_flag_done": 1}
    assert by["navigation"] == {"nonmoving_npc_many_positions": 1}
    assert sum(sum(v.values()) for v in by.values()) == sum(r["counts"].values())
    assert set(by) <= set(AREAS)
    sizes = r["top_level_sizes_by_area"]
    assert sizes["other"] == {"updated": 3, "zzz_new": None}  # an unknown key counts under other
    assert sizes["navigation"]["bad_warps"] == 1
    assert "battle: " in summary(r)


def _tables():
    """{section heading: [(field, fact type, area)]} from the markdown tables of MEMORY_FACTS.md."""
    out, section = {}, None
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if not line.startswith("|") or line.startswith("|---") or line.startswith("| Field "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        out.setdefault(section, []).append((cells[0].strip("`"), cells[1], cells[2]))
    return out


def test_every_documented_field_is_classified():
    tables = _tables()
    assert len(tables) == 5  # top level, map entry, interaction entry, NPC entry, demo
    for section, rows in tables.items():
        assert rows, section
        for field, fact_type, area in rows:
            assert fact_type in FACT_TYPES, (section, field)
            assert area in AREAS, (section, field)
            row_text = f"{fact_type} {area}"
            assert sum(1 for a in AREAS if re.search(rf"\b{a}\b", area)) == 1, (section, field, row_text)
    top = dict((f, a) for f, _, a in tables["Top-level keys"])
    for key in ("maps", "bad_warps", "beats", "catches", "events", "items", "trainers", "updated"):
        assert key in top
    inter = {f for f, _, _ in next(v for k, v in tables.items() if k.startswith("An interaction"))}
    assert {"done", "type", "type_votes", "type_conf", "type_why", "text", "pages"} <= inter


def test_audit_area_tables_match_the_document():
    top = {f: a for f, _, a in _tables()["Top-level keys"]}
    for key, area in TOP_LEVEL_AREAS.items():
        assert top.get(key) == area, key
    assert set(top) == set(TOP_LEVEL_AREAS)
