import argparse
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokeagent import cli, statescmd
from pokeagent.atlas import collision, ladders, rom_maps, walkgrid
from pokeagent.knowledge import hm_compat, items_catalog
from pokeagent.world import export

RED_ROM = "roms/Pokemon Red.gb"
SIG_DEFAULTS = [
    (collision.rom_tile_pairs, "rom_path"),
    (collision.rom_walkable_ids, "rom_path"),
    (ladders.rom_ladders, "rom_path"),
    (rom_maps.load, "rom"),
    (rom_maps.valid_map_ids, "rom"),
    (walkgrid.rom_planner, "rom_path"),
    (walkgrid.rom_cave_planner, "rom_path"),
    (export.load_world, "rom_path"),
    (export.load_for_view, "rom_path"),
]


def test_cli_default_rom_is_the_spec_path():
    assert cli.DEFAULT_ROM == Path(RED_ROM)


def test_statescmd_default_rom_is_the_spec_path():
    assert statescmd.DEFAULT_ROM == statescmd.ROOT / "roms" / "Pokemon Red.gb"


def test_knowledge_rom_paths_are_the_spec_path():
    assert hm_compat.ROM_PATH == hm_compat.ROOT / "roms" / "Pokemon Red.gb"
    assert items_catalog.ROM_PATH == items_catalog.ROOT / "roms" / "Pokemon Red.gb"


@pytest.mark.parametrize("fn,param", SIG_DEFAULTS, ids=[f"{fn.__module__}.{fn.__name__}" for fn, _ in SIG_DEFAULTS])
def test_signature_default_is_the_red_rom_string(fn, param):
    assert inspect.signature(fn).parameters[param].default == RED_ROM


def test_world_argparse_rom_default():
    from pokeagent.world.app import add_parser
    sub = argparse.ArgumentParser().add_subparsers()
    add_parser(sub)
    args = sub.choices["world"].parse_args([])
    assert args.rom == RED_ROM


def test_rom_path_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv("POKEAGENT_ROM", raising=False)
    monkeypatch.delenv("POKEAGENT_GAME", raising=False)
    args = SimpleNamespace(rom=None)
    assert cli._rom_path(args) == Path(RED_ROM)
    monkeypatch.setenv("POKEAGENT_ROM", "env.gb")
    assert cli._rom_path(args) == Path("env.gb")
    args.rom = "cli.gb"
    assert cli._rom_path(args) == Path("cli.gb")
