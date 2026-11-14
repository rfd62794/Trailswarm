# Legal notes and project policy

This page states what this project does and does not include. It is not legal advice.

## What the licence covers

The [MIT License](../LICENSE) applies only to the original code and documentation written for this project.
It grants no rights in any game, character, trademark, or other third-party work.

## Ownership and affiliation

This project is unaffiliated with and not endorsed by any game publisher or developer. Every game named in this
repository belongs to its respective owners. Pokemon belongs to Nintendo, Game Freak, Creatures Inc. and The Pokemon
Company. Names are used only to identify which game the software was tested with.

The project's public name is Trailswarm. The Python package name `pokeagent` is descriptive and carries no claim
of association.

## What is not in this repository

- ROM images or any other copy of game software
- Boot ROMs, firmware, or decryption keys
- Extracted game graphics, audio, or text as data files, other than the one documentation image described below
- Links to, or instructions for obtaining, copies of game software

`roms/`, `baselines/` and `runs/` are gitignored, along with the three files generated from a local ROM under `kb/`:
`rom_tables.json`, `hm_compat.json` and `items.json`. Crops, thumbnails, datasets and trained model
weights derived from a game are local only and stay gitignored.

Earlier commits briefly included tables generated from a local ROM: moves, the type chart, species names, items and
HM compatibility (`kb/rom_tables.json`, `kb/items.json`, `src/pokeagent/data/hm_compat.json`). They hold game facts, numbers
and names, with no images, audio or ROM bytes. They are not in the current tree but remain in the git history. A rights
holder who wants them removed from the history can open an issue.

## What is in this repository

Original source code, tests and documentation, plus memory addresses, labels and goal names that describe how a game
behaves.

One documentation image, `docs/media/world.gif`, shows real agent runs moving across a map rendered from the game's
own graphics. It is included only to illustrate what the software does, and it will be removed on request from the
rights holder.

Emulator save states may be included where they help demonstrate or test the software, as is common among similar
projects. A save state is a snapshot of a running session and cannot be played without the game itself.

RAM labels in `src/pokeagent/data/ram_map.json` are derived from pret/pokered's `pokered.sym`. That repository
publishes no licence file, so the symbol file itself is not redistributed here.

## Using this software

You must supply your own copy of any game, and you are responsible for having the legal right to use it. The
project does not provide, locate or recommend sources for game software.

## Videos and streams

This is the project's policy for any footage it publishes:

- It comes only from lawfully held copies of a game.
- It adds real commentary or analysis rather than plain gameplay.
- It follows the publisher's current rules for that specific game, checked before publishing. For Nintendo titles
  these are the [Game Content Guidelines](https://www.nintendo.co.jp/networkservice_guideline/en/index.html).
  Square Enix publishes rules per title rather than one policy.

## Third-party software

| Package | Licence | How it is used |
|---|---|---|
| [PyBoy](https://github.com/Baekalfen/PyBoy) | LGPL-3.0 | Unmodified dependency, installed separately, not vendored |

Other dependencies are listed in `pyproject.toml` and carry their own licences. Any future dependency under the GPL,
such as an NES emulator library, would be an optional extra that is installed separately and never bundled here.

## Rights holders

If you represent a rights holder and believe something here should not be, please open an issue on this repository.
It will be reviewed and removed promptly where appropriate.
