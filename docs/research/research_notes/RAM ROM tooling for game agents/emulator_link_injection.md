# Emulator APIs, link-cable play, and opponent injection for Pokemon Red agent-vs-agent battles

## Q1. PyBoy (2.x) API surface and serial/link support

### Takeaway
PyBoy 2.9.0 has everything needed for memory/hook/state control and, notably, ships an experimental two-instance serial link (shared-memory cable) that is demonstrated for Pokemon Gen 1 trading only, not battling. Save states are incompatible with serial-linked instances.

### Cited Findings
- PyBoy v2.9.0 constructor includes `symbols=None`, `serial_shared_memory=None`, `serial_interrupt_based=False`, `fast_mode`, `no_input`, `gameshark`; methods include `tick(count, render, sound)`, `button(input, delay)`, `save_state(file_like)`, `load_state(file_like)`, `symbol_lookup(symbol)`, `hook_register(bank, addr, callback, context)`, `hook_deregister(bank, addr)`, `set_emulation_speed(target_speed)`; properties include `memory`, `register_file`, `memory_scanner`, `tilemap_window`, `game_wrapper` — [PyBoy API docs](https://docs.pyboy.dk/api/pyboy.html)
- Memory is read/written by indexing, e.g. `pyboy.memory[0xC345]` — [PyBoy docs home](https://docs.pyboy.dk/index.html)
- The null window starts at unlimited speed (headless speed); `fast_mode` runs without serial — [PyBoy API docs](https://docs.pyboy.dk/api/pyboy.html)
- A Pokemon Gen 1 game wrapper exists among plugins/game wrappers — [PyBoy docs home](https://docs.pyboy.dk/index.html)
- Official experimental example `extras/examples/gamewrapper_pokemon_link_trade.py` links two PyBoy instances via a "shared-memory Game Boy serial cable" with interrupt-based serial transport; requires compatible Red/Blue ROMs; shared buffer is process-safe and intended only for two connected emulators; `--headless` supported — [PyBoy link trade docs](https://docs.pyboy.dk/wiki/examples/pokemon-link-trade.html)
- Script internals: one `SerialSharedMemoryBuffer()` created in `main()`; Player 1 runs in a `multiprocessing.Process`, Player 2 in the main process; each built with `serial_shared_memory=shared_memory, serial_interrupt_based=True`; setup uses `pokemon.add_pokemon(...)`, `pokemon.set_event_flag("got_pokedex")`, `pokemon.warp("viridian_pokecenter")`, then walks to the Cable Club NPC via `pyboy.button`; a `PyBoyInvalidOperationException` is ignored because "serial connections don't support save states"; it drives the Trade Center menu by reading `tilemap_window` text — [raw example script](https://raw.githubusercontent.com/Baekalfen/PyBoy/master/extras/examples/gamewrapper_pokemon_link_trade.py) (summary via fetch tool, not read verbatim)
- The script covers trade only; no battle flow in it — [raw example script](https://raw.githubusercontent.com/Baekalfen/PyBoy/master/extras/examples/gamewrapper_pokemon_link_trade.py)
- Older issue #29 requested link cable support (good-first-issue, stale; mentions preference for two-computer linking) — [goodfirstissue listing](https://www.goodfirstissue.org/Baekalfen/PyBoy/issues/29); README credited a contributor for "Link Cable" per search snippet — [search snippet only, unverified](https://github.com/kaff3/PyBoy)

### Inferences
- Since the Cable Club trade works, the Colosseum (battle) path uses the same serial layer, so a battle script is plausibly a small extension (drive menus to "Colosseum"), but nobody I found has published it. Needs a test.
- No save/load state while linked means rollback/search-by-state-cloning is unavailable for a linked pair; use the injection approach (Q4) for search-heavy agents.

### Gaps
- Which PyBoy release first shipped serial support, and whether Colosseum works, not confirmed (docs page and script give no version/battle info).
- Hook/symbol-file semantics (symbol file format, `bank` argument for ROM-bank-resident functions) were listed only as signatures; docs prose not read.

## Q2. Other emulators with scriptable link

### Takeaway
SameBoy has a callback-level serial API and a working 2-instance libretro "subsystem" link; BizHawk reportedly has a GB link feature; mGBA has local link but no documented Python-driven two-instance link. PyBoy is the only one with a documented, Python-scripted, headless two-instance example.

### Cited Findings
- SameBoy exposes `GB_set_serial_transfer_start_callback`, `GB_set_serial_transfer_end_callback`, `GB_serial_get_data`, `GB_serial_set_data`; libretro core 2-player subsystem link implemented (Aug 2020 comment); network play had not reached mainline as of 2022; issue still open — [SameBoy issue #18](https://github.com/LIJI32/SameBoy/issues/18)
- RetroBat docs: SameBoy libretro core simulates a link cable between two cartridges via an .m3u playlist — [RetroBat Game Boy 2 players](https://wiki.retrobat.org/systems-and-emulators/supported-game-systems/portable-game-consoles/nintendo-portable-game-consoles/game-boy-2-players)
- BizHawk: forum posters report a GB link feature tested with Pokemon Red/Blue and link toggle controls; no Lua link API documentation found — [TASVideos post](https://tasvideos.org/Forum/Posts/419959), [TASVideos post](https://tasvideos.org/Forum/Posts/487761); another poster asked whether GB/GBC linking exists at all, unanswered in result — [TASVideos post](https://tasvideos.org/Forum/Posts/419775)
- mGBA: Lua scripting and local-only link; Python bindings (libmgba-py, PyGBA) need building from source; no source found showing two linked instances driven from Python — [libmgba-py](https://github.com/hanzi/libmgba-py), [PyGBA](https://pypi.org/project/pygba); old forum note that mGBA multiplayer was local only — [mGBA forum](https://forums.mgba.io/showthread.php?tid=424)
- BGB: link fuzzer tool for Pokemon Red/Blue connects to a BGB instance over BGB's network link (two BGB instances linked) — [bgb-link-fuzzer](https://github.com/Quantaly/bgb-link-fuzzer)

### Inferences
- A BGB network-link protocol client could let a custom program act as the second Game Boy (emulating the link partner without a second emulator), but BGB is closed-source Windows and not headless.

### Gaps
- BizHawk Lua/API details, VBA-M, Gambatte link: not found.
- mGBA GB-link two-process options: not confirmed.

## Q3. Automated Cable Club battles/trades and the Gen 1 link protocol

### Takeaway
I found no published bot that automates Gen 1 Colosseum battles between two emulated agents; only the PyBoy trade demo and a BGB fuzzer. Protocol knowledge exists in pret disassemblies and Smogon writeups.

### Cited Findings
- Gen 1 serial: bulk transfer via `Serial_ExchangeBytes()` with preamble byte `$FD` marking block start; code in `home/serial.asm`, `engine/link/cable_club.asm`, `engine/link/cable_club_npc.asm` — [DeepWiki pret/pokeyellow link cable system](https://deepwiki.com/pret/pokeyellow/6.1-link-cable-system) (secondary; page was only seen via search snippet because fetch returned HTTP 429)
- `Serial_SyncAndExchangeNybble` is used to exchange a nybble (e.g. version check) — [PokeCommunity thread](https://www.pokecommunity.com/threads/implementing-version-control-in-pokered-for-the-cable-club.441564/latest)
- Link battle RNG: one Game Boy generates an array of random values (10 generated, 9 used; values >=253 rejected because 253/$FD is the preamble) shared once at battle start; each use takes the next value; after the array is exhausted every value gets `x*5+1 mod 256` — [Smogon: RNG in RBY Link Battles](https://www.smogon.com/forums/threads/rng-in-rby-link-battles.3746779). Thread does not describe master/slave roles or per-turn exchange.
- `wLinkState` gates link-battle behavior in battle-end code — [pokered fork snippet](https://github.com/TheFakeMateo/RedPlusPlus/blob/5b2068ad14d051ca983fde68456539ce705c826b/engine/battle/4_2.asm) (fork, not canonical)
- Hackaday: a Red ROM hack extended the Cable Club over the internet; trades worked, battles reported untested — [Hackaday tag page](https://hackaday.com/tag/tcpoke)
- Generic Gen 1 link description (~8 kbit/s, lockstep, only decisions/results synced): [finalboss.io](https://finalboss.io/pokemons-tiny-game-boy-link-cable-quietly-rewired) (low-quality secondary source)

### Inferences
- A Gen 1 link battle needs both sides to run the real battle code in lockstep; the shared RNG array means both emulations are deterministic given the same inputs, which suits a two-PyBoy approach.

### Gaps
- Exact master/slave handshake bytes, party block layout on the wire, and TPP-style link battle tools: not found. Read `home/serial.asm` in pret/pokered directly.
- No evidence of any PyBoy battle automation.

## Q4. Opponent injection and Gen 1 simulators

### Takeaway
Injection into one emulator is feasible but undocumented as a recipe: you must write enemy party data after the game's trainer-load routine runs (RAMdomizer demonstrates the technique). For fast agent research, pkmn/engine (Gen 1, Zig) is a purpose-built, Showdown-compatible, ~1000x-faster simulator.

### Cited Findings
- `read_trainer_party.asm` zeroes the enemy party count then reads the trainer table, so injected data must be written after it runs or it will be overwritten — [pret read_trainer_party mirror](https://v10.next.forgejo.org/foster/pokered/src/branch/master/engine/battle/read_trainer_party.asm)
- PokemonRedBlue-RAMdomizer overwrites enemy trainer data in WRAM before battle by running code every frame via an arbitrary-code-execution exploit, detecting load and substituting data — [RAMdomizer](https://github.com/NPO-197/PokemonRedBlue-RAMdomizer)
- pret wiki: a RAM flag distinguishes trainer vs wild battle — [Trainers are not Pokemon](https://github.com/pret/pokered/wiki/Trainers-are-not-Pokemon)
- WRAM layout reference — [pokered memory layout (mintlify)](https://www.mintlify.com/pret/pokered/architecture/memory-layout)
- pkmn/engine: Stage 1 covers Gen I and II; claims frame-accurate, bug-for-bug compatibility with original game code and Showdown; >1000x faster than patched Showdown; C API (`pkmn.h`), `@pkmn/engine` JS/WASM with `Battle.create/restore/update/choices`, Zig package with `FixedRNG`; community C++/Python bindings (unendorsed); main branch breaking, wait for v0.1; AI named as target use; ~349 stars, last push ~May 2026 — [pkmn/engine](https://github.com/pkmn/engine), [gittrend snapshot](https://gittrend.io/repo/pkmn/engine)
- AI research: PokeChamp (LLM minimax; projected Elo 1300-1500) — [arXiv 2503.04094](https://arxiv.org/pdf/2503.04094); Metamon (offline RL transformers on human Showdown games; notes LLM agents uncompetitive in long-horizon early gens) — [arXiv 2504.04395](https://arxiv.org/html/2504.04395v2); PokeLLMon is the LLM baseline — [PokeChamp ICML page](https://icml.cc/virtual/2025/poster/45207); search summaries say RL/search methods dominate LLM agents on the PokeAgent Challenge — [search summary, unverified source](https://sites.google.com/view/pokechamp-llm)

### Inferences
- Hybrid plan: use pkmn/engine for training/search (fast, deterministic, FixedRNG) and PyBoy only for the real-cartridge demonstration, with either the link trade-style two-instance setup (try Colosseum) or enemy-party injection for a single instance.
- Single-instance injection yields a scripted AI opponent in-game, not a second agent's decisions, unless the agent's move choices are fed into the enemy side by patching the enemy move selection routine via `hook_register`.

### Gaps
- No existing project found injecting an arbitrary party via PyBoy; wEnemyParty address not retrieved (use pret `pokered.sym`, loadable through PyBoy `symbols=`).
- pkmn/engine Gen 1 accuracy vs cartridge not independently verified.
- Whether Metamon/PokeAgent Challenge cover Gen 1 specifically: not confirmed.
