"""Warp-disproof learning: forgetting warps that presses disproved.

Mixed into MapMemory (moved unchanged from memory.py).
"""
from __future__ import annotations


class WarpsMixin:
    def forget_warp(self, map_id: int, key: str, *, tombstone: bool = False):
        """Drop a learned warp that presses disproved. Without `tombstone` it is recoverable: learn() re-adds it after
        two real sightings. With it, bad_warps keeps learn() and the swarm merge from ever bringing it back."""
        d = self.m(map_id)
        d["warps"].pop(key, None)
        d.get("warp_cand", {}).pop(key, None)
        d.get("warp_taken", {}).pop(key, None)
        d.get("warp_disproof", {}).pop(key, None)  # a new cycle: without this the count stays past 2 and a re-learned phantom is immortal
        if tombstone:
            bad = self.data.setdefault("bad_warps", [])
            if f"{map_id}:{key}" not in bad:
                bad.append(f"{map_id}:{key}")

    def _note_warp_disproof(self, m0: int, key: str):
        """A learned warp's press moved us exactly one tile in the pressed direction inside the same map (after the
        settle wait): the door is not there. 2 disproofs in a cycle pop it (recoverable); once it was
        re-learned and 2 more come (4 in all, `warp_disproof_total`) it is tombstoned. A push-back (guard, locked gym) moves us the other way: no evidence."""
        d = self.m(m0)
        counts = d.setdefault("warp_disproof", {})      # this cycle: reset when the key really warps
        totals = d.setdefault("warp_disproof_total", {})  # lifetime: never reset, so a re-learned warp is remembered
        counts[key] = counts.get(key, 0) + 1
        totals[key] = totals.get(key, 0) + 1
        if counts[key] >= 2:  # >=, not ==: a merged-in count already far past 2 must still fire
            self.forget_warp(m0, key, tombstone=totals[key] >= 4)
