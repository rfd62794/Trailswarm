"""Screenshots of the viewer window: where they go and how they are named (pure path logic + one dpg call)."""
from __future__ import annotations

import time
from pathlib import Path

DIR = Path("runs") / "screenshots"


def screenshot_path(root: Path | str | None, now: float | None = None, label: str = "viewer") -> Path:
    """``<root>/runs/screenshots/<label>-YYYYmmdd-HHMMSS.png`` (local time)."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() if now is None else now))
    return Path(root or ".") / DIR / f"{label}-{stamp}.png"


def save(dpg, root: Path | str | None, label: str = "viewer") -> Path:
    """Write the window (the whole viewport framebuffer) to runs/screenshots/; the file lands a frame or two later."""
    path = screenshot_path(root, label=label)
    path.parent.mkdir(parents=True, exist_ok=True)
    dpg.output_frame_buffer(str(path))
    return path
