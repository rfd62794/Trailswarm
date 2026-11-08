"""The mapview package stays game-agnostic: no game words, each file under its line limit."""
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "src" / "pokeagent" / "mapview"
BANNED = ("mario", "pokemon", "kanto", "lives", "score", "map_id")
LIMITS = {"__init__.py": 40, "areas.py": 150, "layout.py": 120, "ghosts.py": 150,
          "playback.py": 200, "overlay.py": 200, "best.py": 60, "view.py": 280, "app.py": 150,
          "texcache.py": 80, "compose.py": 60}


def test_no_game_words_in_the_package():
    for py in sorted(PKG.glob("*.py")):
        text = py.read_text(encoding="utf-8").lower()
        for word in BANNED:
            assert word not in text, f"{word} in {py.name}"
        body = text.replace('"levels"', "") if py.name == "areas.py" else text
        assert "level" not in body, f"level in {py.name}"           # areas.py keeps the one alias key


def test_files_stay_under_their_line_limits():
    for name, limit in LIMITS.items():
        n = len((PKG / name).read_text(encoding="utf-8").splitlines())
        assert n <= limit, f"{name}: {n} > {limit}"
