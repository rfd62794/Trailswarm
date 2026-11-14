"""The legal boundary: gitignore entries, the LEGAL.md sentence, and no derived artifact in the diff."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES = (".pt", ".pth", ".npz", ".png", ".gif", ".jpg", ".jpeg")


def test_gitignore_covers_the_vision_outputs():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for entry in ("runs/vision/", "runs/vision_models/", "*.pt", "*.pth", "*.npz"):
        assert entry in text


def test_legal_notes_the_local_only_rule():
    assert "derived from a game are local only" in (ROOT / "docs" / "LEGAL.md").read_text(encoding="utf-8")


def _git(*args) -> list[str]:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
    return [ln for ln in out.stdout.splitlines() if ln]


def test_diff_and_worktree_carry_no_derived_artifact():
    names = set(_git("diff", "--name-only", "main"))
    names |= {ln[3:] for ln in _git("status", "--porcelain")}
    for name in names:
        assert not name.startswith("runs/vision"), name
        assert not name.endswith(FORBIDDEN_SUFFIXES), name
