"""seed: copy a maps.json memory into a new document, optionally stripping run-specific state.

Every strip option is OFF by default: with no flag the seeded document equals the source. Unlike the
2026-11-08 scratch script this never drops encounters or loops unless asked.
"""
from __future__ import annotations

import copy


def seed_memory(data: dict, *, no_encounters: bool = False, no_loops: bool = False,
                no_demos: bool = False, no_playthrough_state: bool = False) -> tuple[dict, dict]:
    """A NEW document (``deepcopy``; the input is never mutated) plus the removal counts."""
    out = copy.deepcopy(data if data is not None else {})
    removed = {"encounters": 0, "loops": 0, "demos": 0,
               "playthrough_state": {"interaction_done": 0, "npc_results_done": 0}}
    for m in (out.get("maps") or {}).values():
        if not isinstance(m, dict):
            continue
        if no_encounters and m.pop("encounters", None) is not None:
            removed["encounters"] += 1
        if no_demos:
            demos = m.pop("demos", None)
            if isinstance(demos, (list, dict)):
                removed["demos"] += len(demos)
            elif demos:
                removed["demos"] += 1
        if no_playthrough_state:
            for entry in (m.get("interactions") or {}).values():
                if isinstance(entry, dict) and entry.pop("done", None) is not None:
                    removed["playthrough_state"]["interaction_done"] += 1
            for npc in (m.get("npcs") or {}).values():
                res = npc.get("results") if isinstance(npc, dict) else None
                if isinstance(res, dict) and res.pop("done", None) is not None:
                    removed["playthrough_state"]["npc_results_done"] += 1
    if no_loops:
        loops = out.pop("loops", None)
        if isinstance(loops, (dict, list)):
            removed["loops"] = len(loops)
        elif loops:
            removed["loops"] = 1
    return out, removed
