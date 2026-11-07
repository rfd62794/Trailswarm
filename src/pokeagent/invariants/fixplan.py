"""The safe remediation for each finding, as text. Never executes anything; never writes runs/ itself."""
from __future__ import annotations

import shlex

from pokeagent.invariants.findings import Finding

BRAIN = "uv run python tools/brain.py"


def plan_for(f: Finding) -> str | None:
    d = f.data
    if f.kind == "phantom_warp":
        if d.get("tombstoned"):
            return (f"# {d['map']}:{d['key']} is tombstoned but still in maps.json: fold the journal\n"
                    f"{BRAIN} apply --backup")
        note = shlex.quote(f"phantom: no ROM warp tile or map edge (taken {d['warp_taken']}, disproved {d['warp_disproof']})")
        return (f"{BRAIN} edit warp_remove {d['map']} {shlex.quote(d['key'])} --note {note} --by invariants\n"
                f"{BRAIN} apply --backup   # journaled, tombstones it; never hand-edit runs/maps.json")
    if f.kind == "impossible_milestone":
        return ("uv run python tools/milestones_clean.py --apply   # writes runs/milestones.cleaned.json, a COPY; "
                "review it, then swap it in while the swarm is stopped")
    if f.kind == "respawn_behind":
        return (f"# {d['file']}: a blackout from this state lands behind Vermilion. Do not ship or start from it; leave the file\n"
                f"# for the swarm to supersede (a new best re-saves it with the sidecar's respawn), or move it out of runs/ by hand")
    if f.kind == "discovery_as_checkpoint":
        return f"# {d['file']}: move it back to the discoveries directory under runs (evidence only), then let a run re-save the real checkpoint"
    if f.kind in ("label_map_mismatch", "sidecar_respawn_mismatch", "state_unloadable"):
        return f"# {d['file']}: label/sidecar and saved RAM disagree. Quarantine it (move out of runs/checkpoints), then let a run re-save it"
    if f.kind == "bad_cut":
        return (f"# segments.json splits[{d['goal']}] holds cut {d['cut']} (0x{d['cut']:02X}) off the route. With the swarm stopped: "
                f"uv run python -c \"import sys; sys.path.insert(0,'tools'); import seg_store, seg_split; "
                f"from pathlib import Path; r=Path('runs'); doc=seg_store.load(r); seg_split.reset(doc, ['{d['goal']}']); seg_store.save(r, doc)\"")
    if f.kind in ("unparsable", "nan", "negative_count", "duplicate_merged", "not_object"):
        return (f"# {d['file']}: restore the last good copy (runs/ backups) or rebuild it with its tool "
                f"(bandit/novelty: tools/novelty.py, tools/seg_ingest.py); stop the swarm first - it rewrites these")
    return None


def fix_plan(findings: list[Finding]) -> str:
    lines = []
    for f in findings:
        if f.level == "INFO":
            continue
        p = plan_for(f)
        if p:
            lines.append(f"[{f.level}] {f.message}\n{p}\n")
    return "\n".join(lines) or "nothing to fix"
