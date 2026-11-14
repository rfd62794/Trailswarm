"""Save and load model weights plus the class table under a local runs/ directory.

The weights and tables are ROM-derived like the dataset they came from: gitignored,
local only, and never written outside a ``runs`` directory under the cwd.
"""
from __future__ import annotations

import json
from pathlib import Path


def _in_runs(out: Path, cwd: Path) -> bool:
    """``out`` must resolve inside a ``runs`` directory under the cwd."""
    try:
        rel = out.resolve().relative_to(cwd.resolve())
    except ValueError:
        return False
    return rel.parts[:1] == ("runs",) or "runs" in rel.parts[:-1]


def save(model, class_table: dict, out_dir) -> Path:
    """Write ``weights.pt`` and ``classes.json`` under ``out_dir``; refuses any path
    that is not inside a ``runs`` directory under the current working directory."""
    import torch

    out = Path(out_dir)
    if not _in_runs(out, Path.cwd()):
        raise ValueError(f"refusing to write outside runs/: {out}")
    out.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out / "weights.pt")
    keys = sorted(class_table, key=class_table.get)
    doc = {"classes": [[k, b, l] for (k, b, l) in keys]}
    (out / "classes.json").write_text(json.dumps(doc, indent=1) + "\n",
                                      encoding="utf-8")
    return out


def load(out_dir):
    """Rebuild ``(model, class_table)`` from a directory written by ``save``."""
    import torch

    from pokeagent.vision_model.net import TinyNet

    out = Path(out_dir)
    doc = json.loads((out / "classes.json").read_text(encoding="utf-8"))
    table = {tuple(k): i for i, k in enumerate(doc["classes"])}
    model = TinyNet(len(table))
    state = torch.load(out / "weights.pt", map_location="cpu", weights_only=True)
    model.load_state_dict(state)
    model.eval()
    return model, table
