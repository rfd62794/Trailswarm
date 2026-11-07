"""File-level operations for brain surgery: load maps.json + journal, check live agents,
fold the journal into maps.json with a backup, and write Q-tables only behind a backup.

Shared by ``pokeagent brain`` (cli_brain) and kept pure of argparse so the rules live in
one place: maps.json is NEVER written while a registered agent is alive, and a Q-table is
never written without a timestamped backup copy first.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from pokeagent.explorer import edits as edit_journal
from pokeagent.qmodels import save_model
from pokeagent.registry import process_alive


def load_maps(path) -> dict:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"maps": {}}


def journal_for(maps_path) -> Path:
    return edit_journal.journal_path_for(maps_path)


def effective_data(maps_path) -> tuple[dict, Path]:
    """maps.json with the journal folded in (what an agent sees after apply_edits)."""
    jpath = journal_for(maps_path)
    data = edit_journal.apply(load_maps(maps_path), edit_journal.read_journal(jpath))
    return data, jpath


def live_agents(maps_path) -> list:
    """Live entries in ``<maps dir>/agents/*.json`` (agent_registry schema, pid-checked)."""
    adir = Path(maps_path).parent / "agents"
    out = []
    if adir.is_dir():
        for p in sorted(adir.glob("*.json")):
            try:
                entry = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(entry, dict) and process_alive(entry.get("pid")):
                out.append(entry.get("id", p.stem))
    return out


def fold_journal(maps_path, *, dry_run: bool = False) -> dict:
    """Fold the journal into maps.json. Dry-run reports what would happen; a real fold
    backs maps.json up to ``<dir>/backups/`` first and refuses while agents are live."""
    maps_path = Path(maps_path)
    jpath = journal_for(maps_path)
    journal = edit_journal.read_journal(jpath)
    live = live_agents(maps_path)
    if dry_run:
        return {"ok": True, "dry_run": True, "pending_edits": len(journal), "live_agents": live,
                "maps": str(maps_path), "journal": str(jpath),
                "note": "run with --backup to fold the journal into maps.json"}
    if live:
        raise RuntimeError(f"refusing to fold while agents are alive: {live} "
                           f"(stop them or wait; maps.json is rewritten by every agent save)")
    if not journal:
        return {"ok": True, "applied": 0, "note": "journal empty - nothing to fold"}
    if not maps_path.is_file():
        raise FileNotFoundError(f"maps file not found: {maps_path}")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = maps_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"maps-{stamp}.json"
    shutil.copy2(maps_path, backup)
    data = edit_journal.apply(load_maps(maps_path), journal)
    tmp = maps_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, maps_path)
    journal_backup = None
    if jpath.exists():
        journal_backup = backup_dir / f"memory_edits-{stamp}.jsonl"
        os.replace(jpath, journal_backup)
    return {"ok": True, "applied": len(journal), "backup": str(backup),
            "journal_backup": str(journal_backup) if journal_backup else None}


def backup_q(path) -> Path:
    """Timestamped sibling copy of a Q-table; call before ANY write to it."""
    path = Path(path)
    bak = path.with_name(path.name + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path, bak)
    return bak


def write_q_with_backup(path, table: dict, schema, n_actions: int) -> Path:
    """Back up then atomically save a Q-table; returns the backup path."""
    path = Path(path)
    bak = backup_q(path)
    save_model(path, {repr(k): list(v) for k, v in table.items()}, schema, n_actions)
    return bak
