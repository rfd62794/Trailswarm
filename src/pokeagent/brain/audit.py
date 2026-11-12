"""Memory audit: how dirty is a maps.json document? Counts and first locations only, never note text.

Pure: ``audit(doc)`` reads a loaded maps.json ``data`` dict (normally the effective data, journal
applied) and never mutates it; ``summary(report)`` renders the report as plain text. The field
labels behind the area tables are documented in ``docs/MEMORY_FACTS.md``.
"""
from __future__ import annotations

import re
from collections import defaultdict

from pokeagent.explorer.note_filter import BATTLE, MENU, text_of

AREAS = ("navigation", "interaction", "battle", "team_capture", "economy_items", "progression", "other")
SIZED_KEYS = ("bad_warps", "beats", "catches", "trainers", "training", "procedures", "loops", "events")

CLASS_AREAS = {
    "interaction_not_a_dict": "interaction", "interaction_no_text": "interaction",
    "interaction_with_text": "interaction", "text_has_battle_lines": "battle",
    "text_has_menu_lines": "interaction", "per_run_flag_done": "progression",
    "type_pc_but_no_pc_in_text": "interaction", "pc_text_but_type_not_pc": "interaction",
    "pressed_100_plus_times": "interaction", "conflicting_type_votes": "interaction",
    "same_text_on_several_facings_of_a_tile": "interaction", "npc_results_done": "progression",
    "npc_text_has_battle_lines": "battle", "nonmoving_npc_many_positions": "navigation",
    "demos": "progression",
}

TOP_LEVEL_AREAS = {
    "maps": "navigation", "bad_warps": "navigation", "beats": "interaction", "catches": "team_capture",
    "events": "progression", "items": "economy_items", "grass_ids": "navigation", "tile_types": "navigation",
    "interaction_stats": "interaction", "text_press_stats": "interaction", "text_pace": "interaction",
    "mash_skill": "interaction", "menus": "interaction", "move_damage": "battle", "enemy_damage": "battle",
    "damage_dealt": "battle", "damage_taken": "battle", "damage_by_type": "battle",
    "item_heal": "economy_items", "battle_lessons": "battle", "procedures": "interaction",
    "training": "team_capture", "threat_by_species": "battle", "type_effect": "battle",
    "chart_disagreements": "battle", "dv_records": "team_capture", "trainers": "battle",
    "grind_points": "team_capture", "loops": "navigation", "team_best_level": "team_capture",
    "blackout_tax": "battle", "updated": "other",
}

_PC_WORD = re.compile(r"\bpc\b")


def _map_order(maps: dict) -> list:
    return sorted(maps, key=lambda m: (0, int(m)) if str(m).lstrip("-").isdigit() else (1, str(m)))


class _Tally:
    def __init__(self):
        self.counts: dict = defaultdict(int)
        self.examples: dict = {}

    def hit(self, cls: str, where: str, n: int = 1) -> None:
        self.counts[cls] += n
        self.examples.setdefault(cls, where)


def _audit_interactions(t: _Tally, mid, inters: dict) -> None:
    by_tile: dict = defaultdict(list)
    for key in sorted(inters):
        e, where = inters[key], f"{mid}:{key}"
        if not isinstance(e, dict):
            t.hit("interaction_not_a_dict", where)
            continue
        text = text_of(e)
        low = text.lower()
        if text.strip():
            t.hit("interaction_with_text", where)
            by_tile[",".join(str(key).split(",")[:2])].append(text)
        else:
            t.hit("interaction_no_text", where)
        if BATTLE.search(text):
            t.hit("text_has_battle_lines", where)
        if MENU.search(text):
            t.hit("text_has_menu_lines", where)
        if e.get("done"):
            t.hit("per_run_flag_done", where)
        if e.get("type") == "pc" and not _PC_WORD.search(low):
            t.hit("type_pc_but_no_pc_in_text", where)
        if "turned on" in low and "the pc" in low and e.get("type") != "pc":
            t.hit("pc_text_but_type_not_pc", where)
        count = e.get("count") or 0
        if isinstance(count, (int, float)) and count >= 100:
            t.hit("pressed_100_plus_times", where)
        if len(e.get("type_votes") or {}) > 1:
            t.hit("conflicting_type_votes", where)
    for tile in sorted(by_tile):
        texts = by_tile[tile]
        if len(texts) >= 2 and len(set(texts)) < len(texts):
            t.hit("same_text_on_several_facings_of_a_tile", f"{mid}:{tile}")


def _audit_npcs(t: _Tally, mid, npcs: dict) -> None:
    for sid in sorted(npcs):
        n, where = npcs[sid], f"{mid}:{sid}"
        if not isinstance(n, dict):
            continue
        r = n.get("results") or {}
        if isinstance(r, dict):
            if r.get("done"):
                t.hit("npc_results_done", where)
            if BATTLE.search(text_of(r)):
                t.hit("npc_text_has_battle_lines", where)
        if not n.get("moves") and len(n.get("positions") or {}) > 1:
            t.hit("nonmoving_npc_many_positions", where)


def _size(v) -> int | None:
    return len(v) if isinstance(v, (dict, list, str)) else None


def audit(doc: dict) -> dict:
    """``{"counts", "examples", "counts_by_area", "top_level_keys", "top_level_sizes",
    "top_level_sizes_by_area"}`` for one maps.json document."""
    t = _Tally()
    maps = doc.get("maps") if isinstance(doc.get("maps"), dict) else {}
    for mid in _map_order(maps):
        m = maps[mid]
        if not isinstance(m, dict):
            continue
        inters = m.get("interactions")
        if isinstance(inters, dict):
            _audit_interactions(t, mid, inters)
        npcs = m.get("npcs")
        if isinstance(npcs, dict):
            _audit_npcs(t, mid, npcs)
        demos = m.get("demos")
        n_demos = _size(demos) if isinstance(demos, (list, dict)) else 0
        if n_demos:
            t.hit("demos", f"{mid}:demos", n_demos)
    counts = dict(sorted(t.counts.items()))
    by_area: dict = defaultdict(dict)
    for cls, n in counts.items():
        by_area[CLASS_AREAS.get(cls, "other")][cls] = n
    sizes = {k: _size(doc[k]) for k in SIZED_KEYS if k in doc}
    sizes_by_area: dict = defaultdict(dict)
    for k in sorted(doc):
        sizes_by_area[TOP_LEVEL_AREAS.get(k, "other")][k] = _size(doc[k])
    return {"counts": counts, "examples": dict(sorted(t.examples.items())),
            "counts_by_area": {a: by_area[a] for a in AREAS if a in by_area},
            "top_level_keys": sorted(doc), "top_level_sizes": sizes,
            "top_level_sizes_by_area": {a: sizes_by_area[a] for a in AREAS if a in sizes_by_area}}


def summary(report: dict) -> str:
    """Plain multi-line text: counts and locations only."""
    lines = ["memory audit"]
    counts, examples = report.get("counts") or {}, report.get("examples") or {}
    if not counts:
        lines.append("  no findings")
    for cls, n in counts.items():
        lines.append(f"  {cls}: {n} (first at {examples.get(cls, '-')})")
    lines.append("by area")
    for area, cls_counts in (report.get("counts_by_area") or {}).items():
        lines.append(f"  {area}: " + ", ".join(f"{c}={n}" for c, n in cls_counts.items()))
    lines.append("top-level keys: " + ", ".join(report.get("top_level_keys") or []))
    for area, sizes in (report.get("top_level_sizes_by_area") or {}).items():
        lines.append(f"  {area}: " + ", ".join(f"{k}={'-' if v is None else v}" for k, v in sizes.items()))
    return "\n".join(lines)
