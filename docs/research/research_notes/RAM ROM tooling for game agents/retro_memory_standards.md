# Retro-game RAM standards for AI/RL agents and game tooling (beyond Pokemon)

Research date: 2026-11-06. Method: WebFetch of primary docs plus WebSearch snippets. Where a claim comes from a search snippet only (page not opened), it is marked "(snippet)".

## 1. Gym Retro / stable-retro: data.json, scenario.json, integration UI, Game Boy

### Takeaway
stable-retro (Farama) is the maintained successor to OpenAI gym-retro and defines the de facto RL standard for naming RAM variables: `data.json` (name, address, struct-like type string) plus `scenario.json` (reward/done as functions of those variables). Game Boy/Color is supported (gambatte core). A new toolkit should emit/consume `data.json` and `scenario.json` as an export target rather than invent a format.

### Cited Findings
- A game is integrated by defining a starting state, a reward function and a done condition; afterwards it is a Gymnasium env. — [stable-retro integration docs](https://stable-retro.farama.org/integration/)
- `data.json` holds variables under an `info` section; each has a name, `address` (RAM position of first byte) and `type`. — [stable-retro integration docs](https://stable-retro.farama.org/integration/)
- `type` has three parts in order: endianness (`<` little, `>` big, `|` don't care, single-byte only), format (`i` signed, `u` unsigned, `d` BCD, `n` low-nybble BCD), byte count. Examples: `|u1`, `>u2`, `>d2` (BCD 1234 stored as 0x12 0x34). — [stable-retro integration docs](https://stable-retro.farama.org/integration/)
- `scenario.json`: reward per variable computed from `op`, `measurement` (default `delta`) and `reference`, multiplied by `reward` (if positive) or `penalty` (if negative), summed per step; optional per-step time reward/penalty. Done: top-level `condition` is `any` (default) or `all`; done variables default to `absolute` measurement. Loaded by default from `scenario.json` or passed to the `RetroEnv` constructor. — [stable-retro integration docs](https://stable-retro.farama.org/integration/)
- Integration UI: helps find variables and see reward behaviour; workflow is load ROM, name game, reach first playable moment, pause, save a state; verify reward against the `Cumulative` value in the Scenario Information pane. — [stable-retro integration docs](https://stable-retro.farama.org/integration/)
- ROM extension identifies system: `.gb` Game Boy, `.gbc` Game Boy Color, `.gba` GBA, `.nes`, `.sfc`, `.md`, `.a26`, `.gg`, `.pce`, `.sms`. Custom game folders follow a `Name-System` pattern, e.g. `AeroStar-GameBoy`. — [stable-retro integration docs](https://stable-retro.farama.org/integration/)
- stable-retro lists "Gameboy/Color" and "Gameboy Advance" as supported on Linux, Windows and Apple, MIT-licensed, ~621 commits on main; README says gym-retro is in maintenance so new games/features should be PRed to stable-retro. No release/version/date was visible on the fetched page. — [stable-retro GitHub](https://github.com/Farama-Foundation/stable-retro)
- openai/retro: README status "Maintenance (expect bug fixes and minor updates)"; repository archived by owner on May 29, 2026, now read-only; Game Boy/GBC via gambatte, GBA via mGBA, Atari 2600 via Stella, etc. — [openai/retro GitHub](https://github.com/openai/retro)

### Inferences
- Because the `type` string is struct-like (endianness + signedness/BCD + width), it already covers Game Boy's little-endian 16-bit values and BCD money/score fields; a toolkit's own variable schema can map 1:1 onto it.
- openai/retro being archived (2026-05-29) means stable-retro is the only live upstream for this format.

### Gaps
- Did not verify stable-retro's latest release tag or last-commit date (page did not show them).
- Did not open a concrete Game Boy `data.json` example (e.g. an existing Pokemon or Tetris integration) to confirm RAM address conventions (WRAM $C000 base vs offset).

## 2. Arcade Learning Environment: RAM observations and AtariARI

### Takeaway
ALE exposes the 128-byte Atari 2600 RAM as a raw observation (`obs_type="ram"`, `Box(0,255,(128,),uint8)`), and AtariARI is the reference for adding semantic labels to RAM bytes via a per-game annotation table. Neither provides a shareable file format; labels live in Python code.

### Cited Findings
- Gymnasium's ALE env: `obs_type="ram"` returns the console RAM, observation space `Box(0, 255, (128), np.uint8)`; v5 env ids keep a `-ram` suffix in the `ALE` namespace. — [Gymnasium Atari docs](https://gymnasium.farama.org/environments/atari/)
- AtariARI is a Gym wrapper (`AtariARIWrapper`); each `step` returns `info["labels"]` with semantic variables (player/enemy position, score, lives, etc.). Labels are defined by mapping RAM addresses to variables in `atariari/benchmark/ram_annotations.py`; labels are intended for full 210x160 observations. — [AtariARI GitHub](https://github.com/mila-iqia/atari-representation-learning)
- Reference paper: Anand, Racah, Ozair, Bengio, Cote, Hjelm, "Unsupervised State Representation Learning in Atari", arXiv:1906.08226 (2019). — [AtariARI GitHub](https://github.com/mila-iqia/atari-representation-learning)
- AtariARI repo: 579 commits, 259 stars, MIT; no maintenance statement on page. — [AtariARI GitHub](https://github.com/mila-iqia/atari-representation-learning)

### Inferences
- The AtariARI pattern (wrapper that adds a `labels` dict to `info`, driven by a per-game address table) is a clean template for a Game Boy equivalent, but the table should be data (JSON/YAML) rather than Python.

### Gaps
- No survey of RAM-vs-pixel agent papers was done beyond AtariARI (budget). Not verified: ALE's own docs on RAM, the AtariARI maintenance status, or papers comparing RAM and pixel agents.

## 3. RetroAchievements

### Takeaway
RetroAchievements is the largest crowd-sourced memory-map ecosystem: per-game code notes attached to addresses, a typed condition language, and Rich Presence scripts, all authored in a built-in memory inspector. Its size/format model (8/16/24/32-bit, bits, upper/lower nibble, little-endian) is a recognised vocabulary.

### Cited Findings
- Memory Inspector: searches scoped to All / System RAM / Cartridge RAM / custom range; filters (`!= Last Value`, Constant, Last Value Plus/Minus, Initial Value); bookmarks (renamable, resizable, freezable); notes shown blue, bookmarks green. — [RA Memory Inspector](https://docs.retroachievements.org/developer-docs/memory-inspector.html)
- Code notes: short, clear text descriptions attached to addresses, saved to the server on Save Note; browsable/searchable in a Code Notes dialog. — [RA Memory Inspector](https://docs.retroachievements.org/developer-docs/memory-inspector.html)
- Size types: 8-bit (default), 16/32-bit (little-endian), single bits (flags), Upper4/Lower4 nibbles. — [RA Memory Inspector](https://docs.retroachievements.org/developer-docs/memory-inspector.html)
- Rich Presence is a script with `Lookup:` (value-to-text, ranges/lists, `*` fallback), `Format:` (SCORE, VALUE, SECS, FRAMES, FIXED1-3, FLOAT1-6), and `Display:` with `@Name(value)` macros and optional `?condition?` lines; output limited to 255 bytes. Memory is referenced like `0xh0756` (8-bit at hex address). — [RA Rich Presence](https://docs.retroachievements.org/developer-docs/rich-presence.html)
- Game Boy specifics (snippet): cartridge RAM 0xA000-0xBFFF is save data (cheatable via edited saves); work RAM at 0xC000; echo RAM addresses starting with E should be rewritten to C; GBC banked WRAM beyond bank 1 is exposed at $10000-$15FFF in the libretro memory map. — [RA Console Specific Tips](https://docs.retroachievements.org/Console-Specific-Tips/), [libretro core support](https://docs.retroachievements.org/libretro-core-support/)
- rcheevos PR #329 discusses cartridge RAM only exposing the first 8 KB page of up to 128 KB; merge status unconfirmed. — [rcheevos PR 329](https://github.com/RetroAchievements/rcheevos/pull/329)

### Inferences
- RA's `0xh` style size prefix and nibble/bit sizes are worth supporting as an import/export notation for note-to-variable conversion.
- RA's remapping of GBC banked WRAM into a flat address space shows the need for a toolkit address model that includes bank (`bank:address`).

### Gaps
- The achievement condition-syntax page (guessed URLs `achievement-logic-syntax.html`, `achievement-syntax.html`) returned 404, so the condition operator/flag syntax is not documented here. Correct URL not located.
- No metadata on RA code-note file export formats or API for fetching notes (RA does have an API; not verified).

## 4. Cheat formats, RAM watch files, TASVideos, BizHawk

### Takeaway
Game Boy GameShark codes are the simplest portable "write byte to RAM" format; BizHawk `.wch` is a plain-text RAM watch list that TASVideos uses as the community standard for sharing addresses (replacing wiki address lists); RetroArch `.cht` is a key/value text format. None is typed or documented as richly as stable-retro data.json.

### Cited Findings
- Game Shark (RAM patches): eight hex digits holding SRAM bank, new value, address; example `010238CD` selects SRAM bank $01 and writes $02 to $CD38 (address bytes swapped). Game Genie (ROM patches): `ABC-DEF-GHI`, address XOR $F000, old data XOR $BA rotated, ROM range $0000-7FFF only. — [Pan Docs: Shark Cheats](https://gbdev.io/pandocs/Shark_Cheats.html)
- PyBoy implements GameShark type 01 (write one byte) only (snippet). — [PyBoy gameshark API](https://docs.pyboy.dk/api/gameshark.html)
- pret/pokecrystal documents discovering GameShark codes against the disassembly (title seen in search results; page not opened). — [pokecrystal wiki](https://github.com/pret/pokecrystal/wiki/Discovering-GameShark-cheat-codes)
- BizHawk Lua `memory` library: memory domains are named regions per core; default is system bus; `memory.usememorydomain`, `getmemorydomainlist`; reads `read_u8/s8`, `u16/s16/u24/u32` with `_le`/`_be`; bulk reads as array/string/dict; `hash_region`. — [TASVideos BizHawk Lua functions](https://tasvideos.org/BizHawk/LuaFunctions)
- RAM Watch `.wch`: saves the address list and order; TASVideos moved address lists into `.wch` files hosted as user files linked from game pages. Example lines resemble "03 b u 1 Main RAM Y Position of Bobby" (snippet; field order is my inference, not stated). — [TASVideos RAM Watch](https://tasvideos.org/EmulatorResources/RamWatch), [example file](https://tasvideos.org/UserFiles/Info/637936906481244621)
- BizHawk `.cht`: display column stores u/s/h/b; one cheat per address; cheat files named by game title; no official spec for the column layout found. — [BizHawk Cheats forum thread](https://tasvideos.org/Forum/Topics/22217), [TASVideos cheat guide](https://tasvideos.org/Bizhawk/Cheat)
- RetroArch `.cht`: numbered keys `cheatN_address`, `_value`, `_code`, `_desc`, `_enable`, `_memory_search_size`, all quoted strings, preceded by `cheats = N`; no official spec found (snippet from a user-posted file). — [libretro forum](https://forums.libretro.com/t/mupen64plus-next-widescreen-cheats/26613)
- LiveSplit autosplitters (ASL): `state("process","version") { type name : "module", offsets...; }` pointer-path variables with `current`/`old`; actions `startup`, `init`, `update`, `start`, `split`, `reset`, `isLoading`, `gameTime`; WebAssembly autosplitters are sandboxed, Rust best supported; shared via pull request to the Auto Splitters XML. — [LiveSplit.AutoSplitters](https://github.com/LiveSplit/LiveSplit.AutoSplitters)

### Inferences
- `.wch` and GameShark are low-fidelity (no types/semantics in GameShark; free-text notes in .wch) so they work best as export targets for a toolkit's named-variable file.
- Autosplitter state descriptors are the closest "typed variable list" analogue in speedrunning; emulator autosplitters usually need the emulator process base plus a WRAM offset, which varies by emulator.

### Gaps
- Cheat Engine table (.CT) format was not researched.
- BizHawk `.wch` header/field layout not confirmed from an authoritative spec; the `.cht` spec is also unconfirmed.
- Did not verify how LiveSplit autosplitters for Game Boy emulators locate WRAM (signature scan vs fixed offset).

## 5. Symbol-file standards

### Takeaway
RGBDS `.sym` is the de facto standard for exposing labels from a GB disassembly project to emulators and debuggers: one `bank:address name` per line, hex without prefixes. It is loosely specified but has an official page. Map files are linker-specific and not standardised.

### Cited Findings
- rgblink `-n/--sym` writes visible labels and exported numeric constants (labels as bank+address, constants as value); format follows the spec at rgbds.gbdev.io/sym; "Several external programs can use this information, for example to help debugging ROMs." `-m/--map` lists how sections and symbols were assigned; `-M` omits symbols from the map. Map layout not documented on that page. — [rgblink(1)](https://rgbds.gbdev.io/docs/master/rgblink.1)
- Sym spec: each line has location then name; location is `<bank>:<address>` in hex without prefixes, or `BOOT:<addr>`, or a bank-less address; `;` starts a comment; a name with exactly one period is a local symbol attached to a preceding global. The spec says the format "was always loosely defined, leading to subtle incompatibilities" and has existed "since at least the early 2000's". — [RGBDS sym format](https://rgbds.gbdev.io/sym)
- Sym files generally omit hardware registers ($FF00-FF7F, $FFFF) (snippet), and the no$gmb emulator supported sym files historically. — [RGBDS sym format](https://rgbds.gbdev.io/sym)
- pret/pokered builds produce a `.sym` beside the ROM listing all labels with bank and address; `make DEBUG=1` passes `-E` to rgbasm to export all symbols (third-party docs page, not official pret). — [mintlify pokered debugging](https://www.mintlify.com/pret/pokered/development/debugging)
- Data Crystal (TCRF) hosts community "RAM map" and "ROM map" wiki pages per game (e.g. Pokemon Red RAM map) and notes the pret disassembly has far more addresses. — [Data Crystal Pokemon Red RAM map](https://datacrystal.tcrf.net/wiki/Pokemon_Red:RAM_map)
- Related tooling seen: issotm/gb-sym-file (sym utilities) and mgbdis (disassembler) — [gb-sym-file](https://github.com/issotm/gb-sym-file), [mgbdis](https://github.com/mattcurrie/mgbdis) (titles only; not opened).

### Inferences
- A toolkit following the standard should import/export RGBDS `.sym` (bank:addr name) for labels, and treat typed variables as a separate layer (sym has no size or type).
- Because `.sym` has no type/size information, pairing it with data.json-style typing is a gap the toolkit can fill.

### Gaps
- BGB's own sym handling (loading rules, extensions) not confirmed from BGB docs.
- Constants in `.sym` format are not described on the spec page.

## 6. Common use cases

### Takeaway
The same address table drives RL reward/done, state detection, trackers, speedrun autosplitters, rich presence and bots; the ecosystems above each cover one slice with an incompatible format.

### Cited Findings
- RL reward/done from RAM: stable-retro `scenario.json` — [stable-retro](https://stable-retro.farama.org/integration/)
- Representation-learning probing with labelled RAM: AtariARI — [AtariARI](https://github.com/mila-iqia/atari-representation-learning)
- Achievement triggers and presence strings from RAM: RetroAchievements — [Rich Presence](https://docs.retroachievements.org/developer-docs/rich-presence.html)
- Speedrun timers/auto-splitting from RAM: LiveSplit ASL — [LiveSplit.AutoSplitters](https://github.com/LiveSplit/LiveSplit.AutoSplitters)
- Scripted bots/TAS tooling reading RAM: BizHawk Lua — [BizHawk Lua](https://tasvideos.org/BizHawk/LuaFunctions)

### Inferences
- Randomizer/tracker overlays, stream overlays and accessibility mods were not researched; they most likely reuse the same bank/address plus size vocabulary but this is unverified.

### Gaps
- No sources gathered for randomizer trackers (e.g. auto-trackers), stream overlays or accessibility mods.

## Overall recommendation (inference)
Adopt: RGBDS `.sym` for labels; stable-retro `data.json` type strings (`|u1`, `>u2`, `>d2`) for typed variables; scenario.json for reward/done; export adapters to RA-style notes, BizHawk `.wch`, and GameShark. Add an explicit bank field because stable-retro and `.sym` differ in how they handle banked memory.
