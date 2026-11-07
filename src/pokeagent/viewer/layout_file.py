"""Layout file bookkeeping (pure file I/O, no Dear PyGui): the committed default and the live ini.

The viewer persists top-level window positions/sizes to ``runs/viewer/layout.ini`` via Dear PyGui's
``init_file``. On start the committed read-only default is copied in when the live file is missing;
the default itself is never written.
"""
from __future__ import annotations

import shutil
from pathlib import Path

DEFAULT = Path(__file__).with_name("default_layout.ini")


def ensure_layout(default: Path, target: Path) -> Path:
    """Copy ``default`` to ``target`` when missing (never overwrites, never raises).

    A read-only or otherwise unwritable target still returns ``target`` - the app simply runs
    without a persisted layout."""
    try:
        target = Path(target)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(default), target)
    except OSError:
        pass
    return target


def reset_layout(default: Path, target: Path) -> Path:
    """Overwrite ``target`` with ``default`` (applies on next start). Never raises."""
    try:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(default), target)
    except OSError:
        pass
    return target
