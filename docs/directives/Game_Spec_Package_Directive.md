# PokeAgent: game spec package - a GameSpec per game, a GAMES table, --game and POKEAGENT_GAME, and the Red ROM hash moved behind it (plan phase 2)

## Why this exists

`docs/plans/Multi_Game_Framework_Plan.md` (on branch `feat/watch-mario-land`, PR #169; if it is not on main when this runs, the facts below are all you need) settles the route to more games: extend this repo, one directive per phase, Pokemon Red byte-identical by default. This directive is phase 2: the first game seam. Today there is no game abstraction at all.

Measured on main 2026-11-08:

- `src/pokeagent/cli.py:31` `EXPECTED_SHA1 = "EA9BCAE617FDF159B045185467AE58B2E4A48B9A"` and `:32` `DEFAULT_ROM = Path("roms/Pokemon Red.gb")` are module constants; `_rom_path(args)` (:38-45) resolves `--rom`, then `$POKEAGENT_ROM`, then `DEFAULT_ROM`; `_cmd_check_rom` (:92-110) hashes the ROM and compares to `EXPECTED_SHA1`, then boots it through `_build_emulator`.
- The subcommands that take `--rom` are `run`, `check-rom`, `state`, `mcp` (cli.py `_build_parser`, :155-190). `world`, `states` and the `hex` group register their own parsers and are NOT in this phase.
- `tests/test_cli.py` pins the behaviour: `test_check_rom_missing_file`, `test_check_rom_mismatch_still_boots`, `test_check_rom_match_returns_zero` (line 86 does `monkeypatch.setattr(cli, "EXPECTED_SHA1", ...)`), `test_rom_path_precedence` (:119-126).
- `registry.py` is a worker-process registry and `adapters/` are viewer snapshot adapters, so neither can carry this. A new package is needed.

The governing rule, verbatim from the plan: "Pokemon Red behaviour stays byte-identical by default. `--game` defaults to `pokemon-red`, and Red's paths resolve to where they are today." This phase ends in a stop point: Red only, no behaviour change.

Read first: `src/pokeagent/cli.py` (whole file, about 230 lines), `tests/test_cli.py`, `src/pokeagent/emulator.py` lines 1-40 (only to see that it is unchanged by this phase).

## Scope (in this order)

1. `src/pokeagent/game/__init__.py` <!-- new: src/pokeagent/game/__init__.py --> - re-exports `GameSpec`, `GAMES`, `DEFAULT_GAME`, `resolve_game`, `add_game_argument`.
2. `src/pokeagent/game/spec.py` <!-- new: src/pokeagent/game/spec.py --> - the `GameSpec` dataclass only. Under 60 lines.
3. `src/pokeagent/game/pokemon_red.py` <!-- new: src/pokeagent/game/pokemon_red.py --> - the one spec instance for Red. Under 40 lines.
4. `src/pokeagent/game/registry.py` <!-- new: src/pokeagent/game/registry.py --> - `GAMES`, `DEFAULT_GAME`, `get_game`. Under 50 lines.
5. `src/pokeagent/game/select.py` <!-- new: src/pokeagent/game/select.py --> - `resolve_game(arg)` and `add_game_argument(parser)`. Under 70 lines.
6. `src/pokeagent/cli.py` - read the expected hash from the selected spec, add `--game` to the four subparsers that take `--rom`. Net change small; no other behaviour edits.
7. `tests/test_cli.py` - the minimum edit to keep its existing cases valid (see the work), plus the new test files listed in the completion criteria.
8. `docs/KNOWLEDGE.md` - a short paragraph: what a GameSpec is, how a game is selected.

## The work

### spec.py

```
@dataclass(frozen=True)
class GameSpec:
    key: str                       # "pokemon-red": the stable name used by --game, POKEAGENT_GAME and later by store paths
    title: str                     # "Pokemon Red"
    rom_sha1: tuple[str, ...]      # accepted ROM hashes, uppercase hex, at least one
```

Validate in `__post_init__`: `key` matches `^[a-z0-9]+(-[a-z0-9]+)*$`, `rom_sha1` is non-empty and every entry is 40 uppercase hex characters; raise `ValueError` otherwise. Nothing else goes on the spec in this phase: later phases add ROM default, screen size and button set (phase 3) and store namespaces (phase 4); do not add them now and do not add placeholders for them.

### pokemon_red.py

`RED = GameSpec(key="pokemon-red", title="Pokemon Red", rom_sha1=("EA9BCAE617FDF159B045185467AE58B2E4A48B9A",))`. This is the SAME hash string that `cli.py` holds today; copy it exactly and delete the literal from `cli.py` (a grep criterion checks that).

### registry.py

`GAMES: dict[str, GameSpec] = {RED.key: RED}`, `DEFAULT_GAME = "pokemon-red"`, `get_game(key) -> GameSpec` (raises `KeyError` with the list of known keys in the message). Registration is by editing this dict; no plugin discovery, no entry points, no import magic.

### select.py

- `resolve_game(arg: str | None, env: Mapping[str, str] | None = None) -> GameSpec`: the `--game` argument if given, else `$POKEAGENT_GAME` if set and non-empty, else `DEFAULT_GAME`. An unknown key raises `UnknownGame(ValueError)` whose message lists the known keys. Takes `env` as a parameter (default `os.environ`) so tests do not touch the real environment.
- `add_game_argument(parser)`: adds `--game KEY` with `default=None`, `metavar="KEY"`, help text naming the default and `POKEAGENT_GAME`. The default is `None` so `resolve_game` can tell "not given" from "given"; do not put `pokemon-red` as the argparse default.

### cli.py

- Delete the `EXPECTED_SHA1` literal. Keep the module attribute name `EXPECTED_SHA1` ONLY if a test needs it; prefer removing it (see below).
- `_cmd_check_rom` resolves the game with `resolve_game(args.game)` (catching `UnknownGame`: print `error: <message>` and return exit code 2, the same code the argparse errors use) and compares the ROM hash against `spec.rom_sha1`. Output text is byte-identical for Red: the same three lines `size: ...`, `sha1: ...`, then `match` or `mismatch (expected <hash>)` where `<hash>` is `spec.rom_sha1[0]`.
- `_rom_path(args)` is unchanged in this phase (the ROM default moves in phase 3). `_build_emulator`, `_cmd_run`, `_cmd_state`, `_cmd_mcp`: resolve the game the same way at the top of the command so an unknown `--game` or `POKEAGENT_GAME` fails early with exit code 2; the resolved spec is not otherwise used yet. A non-default game key that is registered cannot exist yet (only Red is registered), so no branch on the key is needed.
- `--game` is added through `add_game_argument` to `run`, `check-rom`, `state` and `mcp` only.

### tests/test_cli.py

`test_check_rom_match_returns_zero` patches `cli.EXPECTED_SHA1`. That name no longer exists. Change that one test to patch the registry instead, with the least change: `monkeypatch.setitem(GAMES, "pokemon-red", dataclasses.replace(RED, rom_sha1=(hashlib.sha1(data).hexdigest().upper(),)))`. Change nothing else in the existing assertions; all other existing tests in the file must pass without edits. Report exactly which test lines you changed.

## What NOT to do

- Do not touch `roms/`, `baselines/`, or any ROM data, and do not state where any game copy came from, anywhere.
- Do not change the ROM default path, the emulator, screen size, button handling, `statemeta`, any `runs/` or `kb/` path, or any explorer, knowledge, viewer or world code. Those are phases 3 and 4.
- Do not add `--game` to `world`, `states`, `hex`, `view` or any tool in `tools/`.
- Do not register a second game, a Blue or Mario spec, or a stub for one.
- Do not rename the package, `pokeagent` the CLI, or anything in `src/pokeagent/registry.py` or `src/pokeagent/adapters/`.
- Do not add dependencies. No scratch or debug files outside `.devin-scratch/`.
- Every new file stays under its stated line limit; keep each module single-purpose.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run python --version
uv run pytest -q tests/test_cli.py tests/test_game_spec.py tests/test_game_registry.py tests/test_game_select.py tests/test_cli_game_flag.py
```
Expected: all pass.

```
git grep -n "EA9BCAE617FDF159B045185467AE58B2E4A48B9A" -- src tests tools
```
Expected: exactly one hit, in `src/pokeagent/game/pokemon_red.py` (a test that needs the value reads it from `RED`, not a second literal).

```
uv run pytest -q
```
Expected: no new failures against main's tail; ROM-gated tests skip in this worktree (no ROM is present, none is needed).

## What the Claude verify lane must run afterwards, with the ROM

A Devin worktree has no ROM and no baselines (`roms/` and `baselines/` are gitignored), so every ROM-gated test skips there and a green Devin run proves nothing about real emulation. After the PR is up, Claude runs in the main checkout (which has both), on the PR head sha in a fresh worktree with `roms/` and `baselines/` made available by junction:

1. `uv run pytest -q tests/test_golden_red.py` (the Red golden guard; a changed hash means this phase changed Red's behaviour and the PR is rejected). It skips in a dispatch worktree because the ROM and baselines are absent; report it as NOT run, not as passed. Claude's ROM-present check runs it before merge. The recorded hash must not change (a deliberate change re-records it from a base-commit run in the same PR).
2. `uv run pokeagent check-rom` with the real Red ROM. Expected: output identical to the base commit's output (`size:`, `sha1:`, `match`, and the boot line).
3. `uv run pokeagent check-rom --game pokemon-red` equals (2); `POKEAGENT_GAME=nonsense uv run pokeagent check-rom` exits 2 with the known-keys message.
4. The ROM-gated tests: `uv run pytest -q` in the main checkout; compare the passed and skipped counts with base.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Branch only (`directive/pokeagent-game-spec-package-directive`); commit as you go; never commit to or push main; never merge.
- Tests are headless and need no ROM; use `FakeEmulator` or the existing `_build_emulator` patch the CLI tests already use. Nothing may open a window.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat, test tails and the changed test lines in the Report.

## Completion criteria

- [ ] `GameSpec` rejects a bad key, an empty hash tuple and a lowercase or short hash, and accepts RED. <!-- test: tests/test_game_spec.py --> <!-- new: tests/test_game_spec.py -->
- [ ] `GAMES` holds exactly `pokemon-red`, `DEFAULT_GAME` is `pokemon-red`, and `get_game("nope")` raises `KeyError` naming the known keys. <!-- test: tests/test_game_registry.py --> <!-- new: tests/test_game_registry.py -->
- [ ] `resolve_game` precedence is `--game`, then `POKEAGENT_GAME`, then the default; an empty env value is ignored; an unknown key raises `UnknownGame` listing the keys. <!-- test: tests/test_game_select.py --> <!-- new: tests/test_game_select.py -->
- [ ] `run`, `check-rom`, `state` and `mcp` accept `--game pokemon-red` and reject `--game nope` with exit code 2; `world`, `states` and `view` do not gain the flag; `check-rom` output for a Red ROM-shaped file is byte-identical to the output captured before the change (the test pins the three lines using a temporary file whose hash is injected through the registry). <!-- test: tests/test_cli_game_flag.py --> <!-- new: tests/test_cli_game_flag.py -->
- [ ] All pre-existing `tests/test_cli.py` cases pass; only `test_check_rom_match_returns_zero` was edited. <!-- test: tests/test_cli.py -->
- [ ] The git grep above shows exactly one hit for the hash.
- [ ] Every new `src/pokeagent/game/*.py` is under its line limit and `git diff --stat main` touches only the files in Scope.
- [ ] Status row set to `Review` with the evidence above and the "Claude verify lane" section copied into the Status note so the reviewer sees what a ROM-less run did not prove.

## Report

Diff stat, test tails, the exact test lines changed in `tests/test_cli.py`, the line count of each new file, and a plain statement that `tests/test_golden_red.py` (skipped) and the real `check-rom` were NOT run (no ROM in the worktree) and are owed by the Claude verify lane.

## Forbidden Actions

- Do not touch `roms/`, `baselines/` or any ROM data, and do not state where a game copy came from.
- Do not run any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor; do not edit another directive's queue block.
- Do not edit `src/pokeagent/emulator.py`, `statemeta.py`, `telemetry.py`, `world/`, `viewer/`, `explorer/`, `knowledge/` or `tools/`.
- Do not commit to or push main, merge, deploy, or open a window.

## Required from User

- None for the run. The ROM-gated `tests/test_golden_red.py` check after the run is Claude's verify lane, not Robert's.
- Sequencing: this is the first of three game-framework directives; `Game_Spec_Rom_Screen_Buttons_Directive.md` must not be approved until this one is merged.

## Sandbox needs

- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git grep)
- Exec(git diff)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Approved |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-08 12:16 · robert-claude-laptop · none → Queued — Drafted by Claude: plan phase 2; golden trace owed by Claude verify with ROM
- 2026-11-08 16:50 · robert-claude-laptop · Queued → Approved
<!-- queue:end -->
