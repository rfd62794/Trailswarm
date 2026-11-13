"""PROPOSED pass/fail thresholds for the compat check (the owner may change them) and the verdict function."""
from __future__ import annotations

PROPOSED = {
    "min_shared_maps": 10, "min_candidate_tiles": 500, "tile_overlap_min": 0.95, "warps_common_min": 10,
    "warps_different_max": 0, "npc_min": 20, "npc_match_min": 0.95, "wall_unexplained_max": 0.02,
    "verified_addr_different_max": 0, "verified_present_min": 0.95,
}


def _ratio(num: int, den: int):
    return round(num / den, 4) if den else None


def evaluate(memory: dict, addresses: dict | None, overrides: dict | None = None) -> tuple[list[dict], str]:
    """Per-rule table and the verdict: fail > insufficient > pass (skipped addresses never block a pass)."""
    t = {**PROPOSED, **(overrides or {})}
    tot = memory.get("totals") or {}
    g = lambda k: tot.get(k, 0)  # noqa: E731
    rules: list[dict] = []

    def add(rule, value, threshold, ok_fn, enough=True, minimum=False):
        """``minimum`` rules are evidence floors: below them the verdict is insufficient, never fail."""
        if not enough or value is None or (minimum and not ok_fn(value)):
            status = "insufficient"
        else:
            status = "pass" if ok_fn(value) else "fail"
        rules.append({"rule": rule, "value": value, "threshold": threshold, "status": status})

    add("shared_maps", memory.get("shared_maps", 0), t["min_shared_maps"], lambda v: v >= t["min_shared_maps"], minimum=True)
    add("candidate_tiles", g("tiles"), t["min_candidate_tiles"], lambda v: v >= t["min_candidate_tiles"], minimum=True)
    add("tile_overlap", _ratio(g("overlap"), g("tiles")), t["tile_overlap_min"], lambda v: v >= t["tile_overlap_min"])
    add("warps_common", g("warps_common"), t["warps_common_min"], lambda v: v >= t["warps_common_min"], minimum=True)
    add("warps_different", g("warps_different"), t["warps_different_max"], lambda v: v <= t["warps_different_max"],
        enough=g("warps_common") >= t["warps_common_min"])
    add("npc_match", _ratio(g("npc_match"), g("npc_candidate")), t["npc_match_min"], lambda v: v >= t["npc_match_min"],
        enough=g("npc_candidate") >= t["npc_min"])
    add("wall_unexplained (ledge_row is a heuristic)", _ratio(g("unexplained"), g("baseline_walls")),
        t["wall_unexplained_max"], lambda v: v <= t["wall_unexplained_max"])
    if addresses is None:
        for r in ("verified_addr_different", "verified_present"):
            rules.append({"rule": r, "value": None, "threshold": None, "status": "skipped"})
    else:
        a = addresses
        add("verified_addr_different", a["verified_addr_different"], t["verified_addr_different_max"],
            lambda v: v <= t["verified_addr_different_max"])
        add("verified_present", _ratio(a["verified_present"], a["verified_in_baseline"]), t["verified_present_min"],
            lambda v: v >= t["verified_present_min"])
    st = {r["status"] for r in rules}
    return rules, "fail" if "fail" in st else ("insufficient" if "insufficient" in st else "pass")
