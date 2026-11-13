"""Address-table comparison (two ``ram_map.json``-shaped lists matched by name)."""
from __future__ import annotations


def compare_addresses(baseline: list, candidate: list) -> dict:
    b = {e["name"]: e for e in baseline}
    c = {e["name"]: e for e in candidate}
    both = sorted(set(b) & set(c))
    diff = [{"name": n, "baseline": b[n]["addr"], "candidate": c[n]["addr"]} for n in both if b[n]["addr"] != c[n]["addr"]]
    ver = [n for n, e in b.items() if e.get("verified")]
    ver_present = [n for n in ver if n in c]
    return {"names_baseline": len(b), "names_candidate": len(c), "in_both": len(both),
            "only_baseline": len(set(b) - set(c)), "only_baseline_first": sorted(set(b) - set(c))[:20],
            "only_candidate": len(set(c) - set(b)), "only_candidate_first": sorted(set(c) - set(b))[:20],
            "addr_different": len(diff), "addr_different_first": diff[:20],
            "verified_in_baseline": len(ver), "verified_present": len(ver_present),
            "verified_addr_different": sum(1 for n in ver_present if b[n]["addr"] != c[n]["addr"])}
