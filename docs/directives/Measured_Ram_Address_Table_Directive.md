# Trailswarm: a tool that turns RAM observations into a per-game measured address table and a stable-retro variable file

**Size:** M. **Assignee:** devin.

## 1. Why this exists

Every address in `src/pokeagent/data/ram_map.json` comes from pret/pokered labels. The file has 2792 entries and 107 carry `"verified": true` (counted 2026-11-08). That flag is one bit with no game attached. Nothing records whether an address was seen to change in Red, in Blue, or in neither. "Red and Blue use the same addresses" is a belief.

The research report (`docs/research/reports/RAM ROM tooling for game agents.md`) says no existing JSON or YAML schema for Pokemon Red RAM, and no tool that checks an address table against evidence, was found, so this fills a gap. It recommends exporting stable-retro `data.json`. The report's text on the format, pasted because you cannot read it from here:

> stable-retro ... defines the RL convention: `data.json` with name, `address` and a struct-like `type` string (endianness, then `i`/`u`/`d`/`n` for signed, unsigned, BCD, nibble-BCD, then byte count, e.g. `|u1`, `>u2`, `>d2`), plus `scenario.json` for reward and done conditions. Game Boy is supported there.

The report does not show the outer wrapper of `data.json`. stable-retro's integration docs use `{"info": {"<name>": {"address": <decimal int>, "type": "<type string>"}}}`. That wrapper is from the maintainers' docs, not from the report, and nobody has loaded the output in stable-retro yet. Write the wrapper as given here, and state in the module docstring that it is unverified against a real stable-retro install.

This directive builds the tool, the schema and the tests. It does not produce the real table. The real observation run needs a ROM and an emulator, and Claude does it after this merges (see "Required from User").

## 2. Scope

New files only. Each is a small single-purpose module; no file over 600 lines (aim far lower).

1. `src/pokeagent/ramlab/observations.py` <!-- new: src/pokeagent/ramlab/observations.py --> - load and validate observation files. Under 120 lines.
2. `src/pokeagent/ramlab/address_table.py` <!-- new: src/pokeagent/ramlab/address_table.py --> - fold observations and map entries into the table dict. Pure, no file I/O. Under 150 lines.
3. `src/pokeagent/ramlab/retro_vars.py` <!-- new: src/pokeagent/ramlab/retro_vars.py --> - type strings and the stable-retro `data.json` dict. Pure. Under 90 lines.
4. `tools/ram_address_table.py` <!-- new: tools/ram_address_table.py --> - standalone CLI. Does not touch `src/pokeagent/cli.py`. Under 100 lines.
5. `docs/data/gen1_ram_addresses.schema.json` <!-- new: docs/data/gen1_ram_addresses.schema.json --> - hand-written JSON Schema describing the output (documentation; no schema library is installed, so do not import one).
6. `tests/test_ramlab_address_table.py` <!-- new: tests/test_ramlab_address_table.py --> - observations, table and CLI tests.
7. `tests/test_ramlab_retro_vars.py` <!-- new: tests/test_ramlab_retro_vars.py --> - type string and `data.json` tests.

Do NOT create the table data file `docs/data/gen1_ram_addresses.json` (it must stay missing) or any `data.json`. See section 4.

## 3. The work

### Facts you need (pasted; do not go looking)

`ramlab` already exists as a package with 12 modules (`findings.py`, `verify.py`, `mine.py`, ...). Leave them alone. Existing code you reuse, `src/pokeagent/ram_lookup.py`:

```python
@dataclass(frozen=True)
class MapEntry:
    name: str
    addr: int          # parsed from the "0xD35E" string
    size: int
    region: str
    encoding: str = "bytes"
    verified: bool = False
    evidence: str = ""
    note: str = ""
    def covers(self, addr: int) -> bool:
        return self.addr <= addr < self.addr + self.size

def load_map() -> list[MapEntry]: ...        # reads the packaged ram_map.json
def query(entries: list[MapEntry], what: str) -> list[MapEntry]: ...
# an address string such as "0xD35E" returns every entry whose range covers it, tightest first (size, then name)
```

Two real lines of `src/pokeagent/data/ram_map.json` (a JSON array of objects, one per line):

```
{"name": "wCurMap", "addr": "0xD35E", "size": 1, "encoding": "u8", "region": "map", "verified": true, "source": "pokered.sym (pret/pokered, symbols branch)", "sym": "wCurMap", "evidence": "make_baseline 2026-11-02"},
{"name": "wPlayerMoney", "addr": "0xD347", "size": 3, "encoding": "bcd", "region": "items", "verified": true, "source": "pokered.sym (pret/pokered, symbols branch)", "sym": "wPlayerMoney", "evidence": "make_baseline 2026-11-02"},
```

Measured counts of `(encoding, size)` in that file: `u8,1` 1921; `bytes,*` about 840 across many sizes; `bitmask,1` 12; `bitmask,19` 2; `u16be,2` 7; `bcd,3` 1; `text,11` 2; `text,360` 1; `u8,256` 1.

Key names present in entries: `name, addr, size, encoding, region, verified, source, sym`, and sometimes `evidence, note, alias`. Your output must NOT copy `source`, `sym`, `evidence`, `note` or `alias`. Labels and addresses only (docs/LEGAL.md: the `.sym` file itself is not redistributed; labels derived from it are credited in LEGAL.md).

### Game keys

Exactly two: `pokemon-red`, `pokemon-blue`. Put them in one constant `GAMES = ("pokemon-red", "pokemon-blue")` in `observations.py`. Any other key is an error.

### Observation file format (the input)

```json
{
  "version": 1,
  "game": "pokemon-red",
  "samples": [
    {"addr": "0xD35E", "value": 12, "context": "walk-route1"},
    {"addr": "0xD35E", "value": 0,  "context": "pallet-town-start"}
  ]
}
```

Rules, enforced in `observations.py::load_observation_file(path) -> Observation` (a frozen dataclass with `game: str` and `samples: tuple[Sample, ...]`, `Sample` has `addr: int`, `value: int`, `context: str`):

- `version` must be `1`; `game` must be in `GAMES`; `samples` a list (may be empty).
- `addr` is a hex string `0x` plus 4 hex digits, parsed to int, in `0xC000..0xDFFF` or `0xFF80..0xFFFE`.
- `value` is an int 0..255 (one byte per sample).
- `context` matches `^[a-z0-9][a-z0-9._:-]{0,63}$`. This is deliberate: it stops free text, and anything read from the game screen, from entering the table.
- Any violation raises `ObservationError(ValueError)` whose message names the file, the sample index and the rule. Never skip a bad sample silently.
- Unknown extra keys on a sample or at the top level are an error too (an allow-list, so a future field cannot slip through).

`load_observations(paths) -> dict[str, list[Sample]]` merges several files by game (concatenate; same game from two files is fine).

### Table rules (`address_table.py::build_table(entries, samples_by_game) -> dict`)

A sample credits exactly one entry: the tightest entry covering its address (smallest `size`, then `name`, the same order `ram_lookup.query` uses). Samples that no entry covers go into `unmapped`.

For each entry and each game in `GAMES`, with that game's samples credited to the entry:

- `not-exercised`: no samples.
- `believed`: at least one sample, but fewer than 2 distinct values, or fewer than 2 distinct contexts.
- `measured`: at least 2 distinct values AND at least 2 distinct contexts.

Per game record: `status`, `samples` (count), `distinct_values` (count, NOT the values themselves), `exercised_by` (sorted unique contexts, at most 8). The output must never contain a raw observed value. Put the three rules in a `STATUS_RULES` dict constant that is also written into the output, so a reader sees them.

Output shape (`schema_version` 1), sorted by `(addr, name)`, deterministic (no timestamp):

```json
{
  "schema_version": 1,
  "games": ["pokemon-red", "pokemon-blue"],
  "source_map": "src/pokeagent/data/ram_map.json",
  "status_rules": {"not-exercised": "...", "believed": "...", "measured": "..."},
  "entries": [
    {"addr": "0xD35E", "label": "wCurMap", "width": 1, "type": "u8", "region": "map",
     "ram_map_verified": true,
     "games": {
       "pokemon-red":  {"status": "measured", "samples": 4, "distinct_values": 3, "exercised_by": ["pallet-town-start", "walk-route1"]},
       "pokemon-blue": {"status": "not-exercised", "samples": 0, "distinct_values": 0, "exercised_by": []}
     }}
  ],
  "unmapped": [{"addr": "0xC0FF", "samples": {"pokemon-red": 2, "pokemon-blue": 0}}]
}
```

`type` is the entry's `encoding`. `ram_map_verified` is the existing flag copied as-is; the schema description must say it is a single-game claim of unknown game and says nothing about Red versus Blue.

### stable-retro variable file (`retro_vars.py`)

- `retro_type(entry) -> str | None`: `u8` size 1 and `bitmask` size 1 give `"|u1"`; `u16be` size 2 gives `">u2"`; `bcd` size 1..4 gives `">d{size}"`; anything else (`bytes`, `text`, wide `bitmask`, wide `u8`) gives `None` because there is no honest scalar type for it. Those entries are skipped from `data.json` and counted.
- `build_retro_data(table, game, include=("measured",)) -> dict`: returns `{"info": {label: {"address": <decimal int>, "type": "<type string>"}}}` for entries whose status for `game` is in `include` and whose type is not `None`. `address` is the CPU address from the map, decimal. Whether stable-retro's Game Boy integration uses the same address base is unverified; say so in the docstring.
- With no measured entries the result is `{"info": {}}`, not an error.

### CLI (`tools/ram_address_table.py`)

```
uv run python tools/ram_address_table.py OBS.json [OBS2.json ...] [--out docs/data/gen1_ram_addresses.json] [--retro-dir DIR] [--retro-include measured|believed]
```

- `main(argv: list[str] | None = None) -> int` so tests call it directly.
- Writes `--out` (default `docs/data/gen1_ram_addresses.json`), creating parent dirs, with `json.dumps(..., indent=1, sort_keys=False)` plus a trailing newline.
- With `--retro-dir`, also writes `<dir>/<game>/data.json` for each game. `--retro-include believed` means measured and believed.
- Prints one summary line per game: `pokemon-red: measured=N believed=N not-exercised=N`, plus `unmapped=N` and `retro-skipped-untyped=N`.
- Exit 0 on success, 2 on `ObservationError` (message to stderr, no output files written).
- Uses `pokeagent.ram_lookup.load_map()`. No `--map` override.

### Tests to write (names are the contract)

In `tests/test_ramlab_address_table.py`, using small hand-written `MapEntry` lists and synthetic observation JSON written under `tmp_path`:

- `test_loader_rejects_bad_game_addr_value_context_and_unknown_keys`: one parametrized case per rule in the list above, each raises `ObservationError`.
- `test_sample_credits_only_the_tightest_covering_entry`: a 44-byte struct and a 2-byte field inside it; a sample inside the field credits the field, not the struct.
- `test_status_boundaries`: 0 samples is `not-exercised`; 3 samples all value 5 is `believed`; two values but one context is `believed`; two values and two contexts is `measured`.
- `test_games_are_independent`: Red measured, Blue untouched gives `not-exercised` for Blue on the same entry.
- `test_output_contains_no_raw_values_and_no_sym_text`: plant the unusual value 237 and the strings `pokered.sym` and a `note` text on the input entry, assert none appear in the serialized output (check for `237` as a JSON number token by asserting `"value"` never appears as a key and `distinct_values` is a count).
- `test_unmapped_samples_are_listed`.
- `test_output_is_deterministic`: build twice from shuffled input order, byte-identical.
- `test_cli_writes_table_and_exits_2_on_bad_input`: via `main([...])`; on a bad file, no output file exists.
- `test_cli_on_the_packaged_map_with_one_synthetic_file`: real `load_map()` (tracked in git, available), a synthetic file sampling `0xD35E` twice with different values and contexts for `pokemon-red`; the `wCurMap` entry is `measured` for Red and `not-exercised` for Blue.
- `test_schema_file_is_valid_json_and_lists_the_same_statuses`: load `docs/data/gen1_ram_addresses.schema.json` and compare its status enum to `STATUS_RULES` keys.

In `tests/test_ramlab_retro_vars.py`:

- `test_retro_type_table`: `("u8",1)->"|u1"`, `("bitmask",1)->"|u1"`, `("u16be",2)->">u2"`, `("bcd",3)->">d3"`, `("bytes",44)`, `("text",11)`, `("bitmask",19)`, `("u8",256)` all `None`.
- `test_data_json_has_only_measured_typed_entries_by_default`.
- `test_include_believed_adds_believed`.
- `test_data_json_shape_and_decimal_address`: `{"info": {"wCurMap": {"address": 54110, "type": "|u1"}}}` (0xD35E is 54110).
- `test_empty_gives_empty_info`.

## 4. What NOT to do

- No ROM, no emulator, no PyBoy import, no `Emulator`/`FakeEmulator`. Tests use synthetic data only. No network, no downloads, no installs, nothing read outside the worktree.
- Do not read, copy or commit `roms/`, `kb/`, `baselines/` or `runs/` (gitignored, absent here, and that is correct).
- Do NOT commit `docs/data/gen1_ram_addresses.json`, any `data.json`, or any placeholder or synthetic version of them. The only file in `docs/data/` is the schema. The real table is generated from a real run later; a fake one committed now would read as evidence it is not.
- Do not change `src/pokeagent/ram.py`, `src/pokeagent/ram_lookup.py`, `src/pokeagent/data/ram_map.json`, any existing `ramlab` module, `src/pokeagent/cli.py`, `src/pokeagent/game/`, the emulator or the explorer. A separate Devin run is changing `game/` and `cli.py`.
- Do not copy `pokered.sym` contents, any label that is not already in `ram_map.json`, or any game text, bytes or art into the repo. Do not say where any game copy came from, in code, docs or the report.
- Do not add a dependency (no `jsonschema`, no `pyyaml`).
- Do not add a skip, `xfail` or a `needs_rom` marker. Every new test must run everywhere.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

```
uv run pytest -q -p no:cacheprovider tests/test_ramlab_address_table.py tests/test_ramlab_retro_vars.py
```
Expected: all pass, 0 skipped.

```
uv run pytest -q -p no:cacheprovider tests/test_ram_map.py tests/test_ramlab_flags.py tests/test_ramlab_mine.py tests/test_ramlab_verify.py
```
Expected: same result as on your base commit (`tests/test_ram_map.py` printed `8 passed` on 2026-11-08). Report any failure that predates your change separately.

```
uv run python -c "import pathlib; [print(p, len(p.read_text().splitlines())) for p in map(pathlib.Path, ['src/pokeagent/ramlab/observations.py','src/pokeagent/ramlab/address_table.py','src/pokeagent/ramlab/retro_vars.py','tools/ram_address_table.py'])]"
```
Expected: each under 600 lines (targets are in section 2).

```
git diff --stat main -- src/pokeagent/cli.py src/pokeagent/game src/pokeagent/ram.py src/pokeagent/ram_lookup.py src/pokeagent/data
```
Expected: no output.

```
git ls-files docs/data
```
Expected: exactly `docs/data/gen1_ram_addresses.schema.json`.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here. If something expected is missing, stop and write that in the PR description.
- Use `uv run` and Python 3.12 only.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- Hard rules: no file over 600 lines; one purpose per module.
- If a tool call is genuinely blocked, stop and write why in the PR description.

## 7. Completion criteria

- [ ] A malformed observation file (bad game, address, value, context, or unknown key) is rejected with a message naming the rule. <!-- test: tests/test_ramlab_address_table.py -->
- [ ] A sample credits only the tightest covering entry. <!-- test: tests/test_ramlab_address_table.py -->
- [ ] `not-exercised`, `believed` and `measured` follow the stated boundaries, per game, independently. <!-- test: tests/test_ramlab_address_table.py -->
- [ ] The output has no raw observed values and none of `source`, `sym`, `evidence`, `note`. <!-- test: tests/test_ramlab_address_table.py -->
- [ ] The CLI writes the table, exits 2 on bad input without writing, and works against the packaged `ram_map.json`. <!-- test: tests/test_ramlab_address_table.py -->
- [ ] Type strings and the `data.json` shape match section 3, and untyped entries are skipped. <!-- test: tests/test_ramlab_retro_vars.py -->
- [ ] `docs/data/` holds only the schema file; no generated data file is committed.
- [ ] Nothing under the paths listed in section 4 changed, and no new file is over 600 lines.

## 8. Report

Findings first: any rule you had to interpret, anything in the `data.json` wrapper you could not confirm (expected: it stays unverified), and the count of untyped entries the tool skips against the packaged map. Then the command tails from section 5.

## Required from User

The real observation run needs a game copy and an emulator, which a dispatch does not have. Claude does it after this merges: run a scripted session per game key, write observation files in the format above, run the table tool from the CLI section above, review the result, then commit `docs/data/gen1_ram_addresses.json`. Until Claude does that, the table does not exist, and nothing in the repo should say Red and Blue addresses are measured.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(src/pokeagent/ram_lookup.py)
- Read(src/pokeagent/data/ram_map.json)
- Write(src/pokeagent/ramlab)
- Write(tools/ram_address_table.py)
- Write(docs/data)
- Write(tests)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git diff)
- Exec(git ls-files)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Approved |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-08 17:18 · robert-claude-laptop · none → Queued — Drafted by Claude at Robert's request 2026-11-08: tool and schema for a measured Red/Blue address table; the real ROM run is Claude's after merge
- 2026-11-12 16:37 · devin-laptop-overseer (delegated) · Queued → Approved — devin-laptop-overseer: Robert permanent PokeAgent approval + 2026-11-12 all-personal-repos approval; cloud drain; under delegate.band-normal, delegate.rate-limit
<!-- queue:end -->
