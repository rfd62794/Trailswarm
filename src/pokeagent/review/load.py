"""Tolerant readers for one run directory plus the shared runs/ files it touches.

A missing file yields an empty list, a corrupt line is skipped and counted in
``skipped_rows`` - never a traceback. ``RunData`` is what every review tool consumes.
Read-only: nothing here writes, moves or deletes anything under ``runs/``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

RUN_NAME = re.compile(r"^explore-(\d{8})-(\d{6})-(\d+)")


def jsonl(path: Path, skipped: dict | None = None) -> list[dict]:
    """Every valid JSON-object line of ``path``; corrupt lines are counted in ``skipped[path.name]``."""
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    obj = None
                if isinstance(obj, dict):
                    rows.append(obj)
                elif skipped is not None:
                    skipped[path.name] = skipped.get(path.name, 0) + 1
    except OSError:
        pass
    return rows


def load_json(path: Path) -> dict:
    """One JSON object file; {} when missing or malformed."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def run_start(name: str, run_dir: Path | None = None) -> datetime | None:
    """Run start time from the ``explore-YYYYMMDD-HHMMSS-pid`` dir name (local time), else meta.json mtime."""
    m = RUN_NAME.match(name)
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        except ValueError:
            pass
    if run_dir is not None:
        try:
            return datetime.fromtimestamp((run_dir / "meta.json").stat().st_mtime)
        except OSError:
            pass
    return None


@dataclass
class RunData:
    """One run's own files plus the shared runs/ rows that belong to it (battles, dossier, milestones)."""

    run_dir: Path
    name: str
    runs_dir: Path
    meta: dict = field(default_factory=dict)
    decisions: list[dict] = field(default_factory=list)      # press rows only ("event" extras excluded)
    event_rows: list[dict] = field(default_factory=list)     # decisions.jsonl rows carrying an "event" key
    transitions: list[dict] = field(default_factory=list)
    levels: list[dict] = field(default_factory=list)
    goal_frames: list[dict] = field(default_factory=list)
    battles: list[dict] = field(default_factory=list)        # runs/battles.jsonl rows for this run
    dossier: dict | None = None                              # runs/stalls/<run>.json when present
    milestones: dict = field(default_factory=dict)           # runs/milestones.json (older runs' goal firsts)
    after_victory: list[dict] = field(default_factory=list)  # runs/after_victory.jsonl rows for this run
    skipped_rows: dict = field(default_factory=dict)
    start_time: datetime | None = None
    crashed: bool = False                                    # error.txt / crash.json seam files present


def resolve_run_dir(run: str, runs_dir: Path) -> Path | None:
    """``run`` is a path or a bare run name under ``runs_dir``."""
    p = Path(run)
    if p.is_dir():
        return p
    cand = Path(runs_dir) / run
    return cand if cand.is_dir() else None


def load_run(run_dir: Path) -> RunData:
    """Load one run directory; shared files come from its parent (the runs/ dir)."""
    run_dir = Path(run_dir)
    runs_dir = run_dir.parent
    skipped: dict = {}
    raw_decisions = jsonl(run_dir / "decisions.jsonl", skipped)
    return RunData(
        run_dir=run_dir,
        name=run_dir.name,
        runs_dir=runs_dir,
        meta=load_json(run_dir / "meta.json"),
        decisions=[r for r in raw_decisions if "event" not in r],
        event_rows=[r for r in raw_decisions if "event" in r],
        transitions=jsonl(run_dir / "transitions.jsonl", skipped),
        levels=jsonl(run_dir / "levels.jsonl", skipped),
        goal_frames=jsonl(run_dir / "goal_frames.jsonl", skipped),
        battles=[r for r in jsonl(runs_dir / "battles.jsonl", skipped) if r.get("run") == run_dir.name],
        dossier=load_json(runs_dir / "stalls" / f"{run_dir.name}.json") or None,
        milestones=load_json(runs_dir / "milestones.json"),
        after_victory=[r for r in jsonl(runs_dir / "after_victory.jsonl", skipped)
                       if r.get("run") == run_dir.name],
        skipped_rows=skipped,
        start_time=run_start(run_dir.name, run_dir),
        crashed=(run_dir / "error.txt").exists() or (run_dir / "crash.json").exists(),
    )
