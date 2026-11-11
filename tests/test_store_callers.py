"""Every store call site resolves to Red's literal path, and each site's scope matches the classification.

Checkpoint sites are game-scope; every other site is family-scope. Namespaced behaviour itself is
tested in test_game_stores.py through the fake specs, not through POKEAGENT_GAME (a process runs one
game, and these sites bind the path once at import/def time).
"""
import ast
import inspect
from pathlib import Path

import pytest

from pokeagent import cli_brain, mcp_server, navigation, observations, statemeta, statescmd
from pokeagent.explorer import legacy
from pokeagent.explorer.context import ExplorerOptions
from pokeagent.knowledge import hm_compat, items_catalog
from pokeagent.knowledge import kb as kbmod


def test_explorer_context_defaults():
    opts = ExplorerOptions()
    assert opts.maps_path == "runs/maps.json"
    assert opts.bandit_path == "runs/bandit.json"
    assert opts.novelty_path == "runs/novelty.json"


def test_legacy_explorer_default():
    assert inspect.signature(legacy.Explorer.__init__).parameters["maps_path"].default \
        == Path("runs/maps.json")


def test_cli_brain_maps_default():
    assert cli_brain.MAPS_DEFAULT == "runs/maps.json"


def test_mcp_server_maps_path():
    assert mcp_server.MAPS_PATH == Path("runs/maps.json")


def test_navigation_load_memory_default():
    assert inspect.signature(navigation.load_memory).parameters["path"].default == "runs/maps.json"


def test_observations_spatial_observer_default():
    assert inspect.signature(observations.SpatialObserver.__init__).parameters["path"].default \
        == "runs/maps.json"


def test_statemeta_tile_snapshot_resolves_the_family_store():
    assert inspect.signature(statemeta.tile_snapshot).parameters["maps_path"].default is None


def test_statescmd_default_dirs():
    assert statescmd.DEFAULT_DIRS == (Path("runs/checkpoints"), Path("runs/legs/states"))


def test_knowledge_kb_paths():
    assert hm_compat.KB_PATH == hm_compat.ROOT / "kb" / "hm_compat.json"
    assert items_catalog.KB_PATH == items_catalog.ROOT / "kb" / "items.json"
    root = Path(kbmod.__file__).resolve().parents[3]
    assert kbmod._KB == root / "kb" / "rom_tables.json"


def _store_scopes(mod) -> set[str]:
    """The scope kwarg used by every store_path(...) call in the module's source ('family' when absent)."""
    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    scopes = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if (isinstance(fn, ast.Name) and fn.id == "store_path") \
                or (isinstance(fn, ast.Attribute) and fn.attr == "store_path"):
            scope = "family"
            for kw in node.keywords:
                if kw.arg == "scope" and isinstance(kw.value, ast.Constant):
                    scope = kw.value.value
            scopes.add(scope)
    return scopes


# file -> the scope(s) its store_path sites must use (from the directive's classification table):
# checkpoints are game-scope (ROM-bound); every other store is family-scope.
_SCOPES = [
    ("pokeagent.explorer.context", {"family"}),
    ("pokeagent.explorer.legacy", {"family"}),
    ("pokeagent.explorer.press_goals", {"game"}),
    ("pokeagent.explorer.press_track", {"game"}),
    ("pokeagent.cli_brain", {"family"}),
    ("pokeagent.mcp_server", {"family"}),
    ("pokeagent.navigation", {"family"}),
    ("pokeagent.observations", {"family"}),
    ("pokeagent.statemeta", {"family"}),
    ("pokeagent.statescmd", {"family", "game"}),  # DEFAULT_DIRS checkpoint + _kb_json tables
    ("pokeagent.knowledge.hm_compat", {"family"}),
    ("pokeagent.knowledge.items_catalog", {"family"}),
    ("pokeagent.knowledge.kb", {"family"}),
    ("pokeagent.review.swarm", {"family"}),
]


@pytest.mark.parametrize("modname,want", _SCOPES, ids=[m.rsplit(".", 1)[-1] for m, _ in _SCOPES])
def test_each_site_uses_the_classified_scope(modname, want):
    import importlib
    mod = importlib.import_module(modname)
    assert _store_scopes(mod) == want
