"""The mapview package stays game-agnostic: no game words, each file under its line limit.

``presets.py`` is the one exemption: it is the data table that names games."""
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "src" / "pokeagent" / "mapview"
BANNED = ("mario", "pokemon", "kanto", "lives", "score", "map_id")
EXEMPT = {"presets.py"}
LIMITS = {"__init__.py": 40, "areas.py": 150, "layout.py": 120, "ghosts.py": 150,
          "playback.py": 200, "overlay.py": 200, "best.py": 60, "view.py": 280, "app.py": 150,
          "texcache.py": 80, "compose.py": 60, "live.py": 130, "presets.py": 120, "edges.py": 90,
          "avatars.py": 150, "avatar_rom.py": 70, "walk.py": 70, "controls.py": 120,
          "ghost_avatars.py": 60, "live_schema.py": 40, "smooth.py": 40, "holder.py": 60, "fast_live.py": 60}


def test_no_game_words_in_the_package():
    for py in sorted(PKG.glob("*.py")):
        if py.name in EXEMPT:
            continue
        text = py.read_text(encoding="utf-8").lower()
        body = text.replace("livestore", "")                        # the store class: not a game word
        for word in BANNED:
            assert word not in body, f"{word} in {py.name}"
        body = body.replace('"levels"', "") if py.name == "areas.py" else body
        assert "level" not in body, f"level in {py.name}"           # areas.py keeps the one alias key


def test_files_stay_under_their_line_limits():
    for name, limit in LIMITS.items():
        n = len((PKG / name).read_text(encoding="utf-8").splitlines())
        assert n <= limit, f"{name}: {n} > {limit}"
