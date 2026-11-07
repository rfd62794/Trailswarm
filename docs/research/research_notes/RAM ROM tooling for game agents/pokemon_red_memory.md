# Pokemon Red/Blue memory (RAM/ROM) knowledge and agent tooling

Research date 2026-11-06. About 20 tool calls; several pages returned partial or no data (flagged in Gaps). Fetch tool summaries are paraphrases by a small model, so exact figures (addresses, stars) should be re-verified at the source before being hard-coded.

## 1. pret/pokered disassembly: what it provides, licence, how it is consumed

### Takeaway
pret/pokered is the canonical, buildable disassembly (about 5k stars, 2,836 commits) and the authoritative source of WRAM labels and data tables. It is the better source of truth than the wiki RAM maps. Its licence and the exact .sym workflow were not confirmed in this pass.

### Cited Findings
- pret/pokered is "a disassembly of Pokemon Red and Blue"; about 5.0k stars, 1.4k forks, 2,836 commits on master, 18 open issues, 4 open PRs at fetch time. Top-level folders: engine, maps, scripts, text, audio, gfx, constants, data, tools, ram. — [GitHub pret/pokered](https://github.com/pret/pokered)
- It builds bit-identical Red and Blue ROMs (checksummed), plus a BLUEMONS.GB debug build and two patch targets (dmgapae0.e69, dmgapee0.e68). — [GitHub pret/pokered](https://github.com/pret/pokered)
- The README points to a separate "Symbols" branch for symbol files; .sym files are not in the master tree. — [GitHub pret/pokered](https://github.com/pret/pokered)
- WRAM labels live in `ram/wram.asm` (older commits: root `wram.asm`). — [wram.asm mirror](https://cocalc.com/github/pret/pokered/blob/master/ram/wram.asm)
- Sprite state: `wSpriteStateData1` at $C100 and `wSpriteStateData2` at $C200, 16 sprites x $10 bytes each, player is always sprite 0. Data1 offset 0 picture ID, 1 movement status, 2 image index, 7 grass flag, 8 delay counter. Data2 offset 0 walk animation counter, 4 Y position, 5 X position (in 2x2-tile steps), 6 movement byte 1, 9 original facing, $D second picture ID, $E image base offset. A 2024 commit renamed offsets to named constants such as SPRITESTATEDATA1_PICTUREID, so field names differ across versions. — [wram.asm mirror (forgejo)](https://v10.next.forgejo.org/foster/pokered/src/branch/master/ram/wram.asm), [cocalc copy](https://cocalc.com/github/pret/pokered/blob/master/ram/wram.asm)
- Trainer party ROM data: `engine/battle/read_trainer_party.asm` reads `TrainerDataPointers` (one pointer per trainer class); party data in `data/trainers/parties.asm`. A leading $FF byte means each mon has its own level (gym leaders, E4, rival); otherwise the first byte is a shared level. — [read_trainer_party.asm mirror](https://v10.next.forgejo.org/foster/pokered/src/branch/master/engine/battle/read_trainer_party.asm), [Mintlify pokered docs: trainers](https://mintlify.com/pret/pokered/game-systems/trainers)
- Third-party generated docs of pokered exist (memory layout, data structures) — [Mintlify memory layout](https://www.mintlify.com/pret/pokered/architecture/memory-layout), [Mintlify data structures](https://www.mintlify.com/pret/pokered/reference/data-structures). These are derived docs; treat as secondary.
- Consumption by agent projects: PokemonRedExperiments and pokemonred_puffer hard-code addresses by hand (see section 3); PWhiddy's code comments cite a RAM-map reference, not .sym loading. — [red_gym_env.py](https://raw.githubusercontent.com/PWhiddy/PokemonRedExperiments/master/baselines/red_gym_env.py)

### Inferences
- A Trailswarm address module should be generated from the pokered `Symbols` branch (or built `.sym`) rather than hand-typed, and pinned to a commit.
- The pokered mirrors cited here are non-canonical; confirm offsets against github.com/pret/pokered at a pinned commit.

### Gaps
- Licence text of pret/pokered: the GitHub page and LICENSE raw URL (404 on /master/LICENSE) did not yield it. Check the repo directly (pret projects are commonly permissive, but this was not verified). Note ROM data/assets are Nintendo/Game Freak IP regardless of the code licence.
- Last-commit date / current activity not visible.
- Exact format of the Symbols branch not inspected. Whether PyBoy loads `.sym` natively was not confirmed (see section 3).
- No sourced description of map/NPC/object ROM tables (`data/maps/objects`, `maps/*.asm` object events) or base-stat/move tables beyond folder names; not fetched.

## 2. RAM maps: Data Crystal, Bulbapedia, others

### Takeaway
Data Crystal's Red/Blue RAM map is broad but explicitly incomplete and contains known typos and overlapping ranges; use it for orientation and cross-check against pokered wram.asm. Bulbapedia's Gen I data structure pages were not retrievable (HTTP 403) in this pass.

### Cited Findings
- Data Crystal key ranges: party count D163, six 44-byte party structs from D16B, trainer names D273-D2AA, nicknames D2B5-D2F6; enemy trainer party D89C to about D9ED; battle: player mon D009-D030, enemy battle data CFB3-D008, status flags D062-D072, stat modifiers CD1A-CD33; sprites C100-C1FF / C200-C2FF, OAM buffer C300-C39F; map number D35E, player coords D361-D364, map header D367-D39C; bag D31D-D346, money D347-D349, badges D356; missable-object flags D5A6-D5C5; event flags about D5AB-D803; PC boxes D4B9-D59F; SRAM boxes in banks 2 and 3. — [Data Crystal Pokemon Red/Blue RAM map](https://datacrystal.tcrf.net/wiki/Pok%C3%A9mon_Red_and_Blue/RAM_map)
- Completeness and errors on that page: flagged "To do"; many "unused?" entries; overlapping box ranges (DABF-DAC2 vs DAC2-DAC4); typos "DC65-CC66" and "DA81-CA94"; 12th nickname range runs into the 13th; CC47, CCDC, CFD3 listed with two meanings; mixed JPN/INT tables; some "Level" bytes are not the real level. Points readers to pret/pokered for more. Content under GNU FDL 1.2. — [Data Crystal RAM map](https://datacrystal.tcrf.net/wiki/Pok%C3%A9mon_Red_and_Blue/RAM_map)
- Event flag bit range used in practice by RL projects: 0xD747-0xD886, museum ticket at 0xD754 bit 0. — [memory_addresses.py](https://raw.githubusercontent.com/PWhiddy/PokemonRedExperiments/master/baselines/memory_addresses.py)
- Cross-check: PokemonRedExperiments uses the same core addresses as Data Crystal (party size 0xD163, map 0xD35E, badges 0xD356, money 0xD347-9). Y at 0xD361 and X at 0xD362. — [memory_addresses.py](https://raw.githubusercontent.com/PWhiddy/PokemonRedExperiments/master/baselines/memory_addresses.py)
- Bulbapedia's "Pokemon data structure (Generation I)" page exists and Data Crystal-adjacent search results show the party structure starting at 0xD163 for Red/Blue (en). — [Bulbapedia](https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_data_structure_(Generation_I)) (page body not read)
- Related: a blog on RAM-writing / ACE in Pokemon Red/Green/Blue — [flag3 blog](https://flag3.github.io/blog/posts/ram-writer-in-pokemon-red-green-blue-en) (not read).

### Inferences
- Treat Data Crystal as a lookup index and pokered wram.asm as ground truth; a swarm project should unit-test its address table against a known save state.

### Gaps
- Bulbapedia party/box/trainer structure pages (403): offsets, species index vs Pokedex order, and any listed errata unverified. Glitch City wiki not consulted. Bulbapedia licence (CC BY-NC-SA) not verified here.

## 3. AI agents in Pokemon Red/Blue and what memory they read

### Takeaway
RL projects read a small set of addresses (position, map, party HP/levels, badges, event-flag bitfield) from PyBoy. LLM harnesses (Claude Plays Pokemon, Gemini Plays Pokemon) additionally decode RAM into text/map/walkability overlays. The NeurIPS 2025 PokeAgent Challenge speedrun track used Pokemon Emerald, not Red.

### Cited Findings
**PokemonRedExperiments (PWhiddy)**
- MIT licence; 278 commits, 67 open issues, 17 open PRs; V2 uses coordinate-based exploration reward; last visible dated update 10-19-24; follow-ups: 2025 arXiv paper and PokeGym. — [GitHub](https://github.com/PWhiddy/PokemonRedExperiments)
- Addresses: PARTY_SIZE 0xD163; species 0xD164-0xD169; HP 0xD16C, 0xD198, 0xD1C4, 0xD1F0, 0xD21C, 0xD248 (2 bytes big-endian); level 0xD18C, 0xD1B8, 0xD1E4, 0xD210, 0xD23C, 0xD268; max HP 0xD18D...; opponent party levels 0xD8C5, 0xD8F1, 0xD91D, 0xD949, 0xD975, 0xD9A1; map 0xD35E; X 0xD362; Y 0xD361; badges 0xD356; money 0xD347-0xD349; event flags 0xD747-0xD886. — [memory_addresses.py](https://raw.githubusercontent.com/PWhiddy/PokemonRedExperiments/master/baselines/memory_addresses.py)
- Reward components: event-flag count, level sum (diminishing above 22), healing (x4 weight), opponent max level minus 5 times 0.2, death -0.1, badge +5, exploration (KNN on screen novelty, or coordinate count); step reward = change in total times 0.1. — [red_gym_env.py](https://raw.githubusercontent.com/PWhiddy/PokemonRedExperiments/master/baselines/red_gym_env.py)

**drubinstein/pokemonred_puffer**
- 809 commits, 214 stars, 33 forks, 13 open issues; no LICENSE file visible and no licence shown (licence unknown, do not assume reuse is allowed); README warns some commands untested recently; multinode sweeps "in progress". — [GitHub](https://github.com/drubinstein/pokemonred_puffer)
- `data/events.py` maps event-flag memory starting at 0xD747 (320 bytes) to named bit fields via ctypes (e.g. EVENT_GOT_STARTER, EVENT_BEAT_BROCK, EVENT_BEAT_MOLTRES) and imports PyBoy; this is a reusable named-event table. — [events.py](https://raw.githubusercontent.com/drubinstein/pokemonred_puffer/main/pokemonred_puffer/data/events.py)

**PyBoy**
- Memory access via `pyboy.memory[0xC345]`; screen via `pyboy.screen.image`; active repo (1,194 commits, 6 open issues, 12 PRs, Discord); install `pip install pyboy`. — [GitHub Baekalfen/PyBoy](https://github.com/Baekalfen/PyBoy) (API docs at docs.pyboy.dk; the memory-API URL guessed returned 404)

**Claude Plays Pokemon**
- A BGR article says the harness has a memory reader to help the model avoid misreading the screen. — [BGR](https://bgr.com/entertainment/claude-ai-playing-pokemon-red-might-be-your-next-twitch-obsession/)
- A community blog says tool results return a new screenshot plus an overlay of critical information parsed from game memory (author notes it is outdated). — [michaelyliu6 blog](https://michaelyliu6.github.io/posts/claude-plays-pokemon)
- A May 2026 Reddit snapshot (secondary) describes a lean harness: button-press tool, pathfinding navigator, knowledge base, RAM-built walkability overlay, second LLM critiquing notes. — [Reddit snapshot](https://reddit.sentinel-team.org/posts/1t5y7ac/snapshots/2026-05-07T08%3A28%3A48.951918Z)

**Gemini Plays Pokemon**
- Harness: system prompt, screenshots with grid overlay, game state extracted from RAM, planning/text tool, textual minimap, sub-agents (e.g. BFS maze solving). — [About (archived rentry)](https://rentry.org/gpp-about-20250612), [LessWrong/GreaterWrong comparison](https://www.greaterwrong.com/posts/7mqp8uRnnPdbBzJZE/is-gemini-now-better-than-claude-at-pokemon), [dbreunig](https://www.dbreunig.com/2025/06/17/an-agentic-case-study-playing-pok%C3%A9mon-with-gemini.html)
- Text had to be pulled out of RAM and inserted into context so the model did not rely on pixels. — [dbreunig](https://www.dbreunig.com/2025/06/17/an-agentic-case-study-playing-pok%C3%A9mon-with-gemini.html)

**PokeAgent Challenge / Continual Harness**
- NeurIPS 2025 competition: Battling Track (20M+ battle trajectories) and Speedrunning Track; speedrun track is Pokemon Emerald (15 milestones); 100+ teams; live leaderboard at pokeagentchallenge.com. — [arXiv 2603.15563](https://arxiv.org/abs/2603.15563), [UT RPL page](https://rpl.cs.utexas.edu/publications/2025/04/01/karten-neurips25-pokeagent/)
- Continual Harness (arXiv 2605.09998, CC BY-NC-SA 4.0) evaluates Pokemon Red and Emerald. The PokeAgent emulator memory reader exposes party, inventory, party HP, map ID, dialogue text, battle status. Minimal conditions see it through an ASCII text map (walkable, walls, interactables, NPCs, ledges, player position/facing) and get_party_hp; the expert harness uses the reader for A* pathfinding, type chart, damage calculator. Tools: press_buttons, get_game_state, define_agent, run_code, process_memory; 8 buttons; 120 frames per step. No RAM addresses or repo link given. — [arXiv HTML](https://arxiv.org/html/2605.09998v1)

### Inferences
- The proven minimal agent state set (map, x, y, party, HP, badges, events, opponent levels) is cheap and stable; Trailswarm should start from it and add NPC sprites (Data1/Data2) and battle structs.
- The PokeAgent harness is Emerald-centric; its memory reader is not directly reusable for Red (Gen 3 vs Gen 1 layouts).

### Gaps
- PokeAgent repo URL, Emerald-specific details, and observation schema not found. pokemonred_puffer licence and its RAM-map module not located. Claude Plays Pokemon official harness source and exact RAM addresses not public in what I found. PokeGym and the 2025 PWhiddy arXiv paper not read. Any 2026 papers beyond Continual Harness not searched.

## 4. Battle memory and opponent-team modification, damage calculation

### Takeaway
Battle state is in WRAM structs (wBattleMon / wEnemyMon, 44-byte-like party structure layout) and enemy party is built from ROM trainer tables at battle start. Direct sourced recipes for injecting an opponent team (RAM writes, Gameshark, ROM hack) were not found; the viable route is editing pokered trainer party data or writing the enemy party RAM before battle.

### Cited Findings
- wEnemyMon is the opponent's active battler with the same structure as wBattleMon; enemy trainer party RAM begins about D89C per Data Crystal (D89C-D9ED); PokemonRedExperiments reads opponent levels at 0xD8C5 etc. — [Data Crystal](https://datacrystal.tcrf.net/wiki/Pok%C3%A9mon_Red_and_Blue/RAM_map), [memory_addresses.py](https://raw.githubusercontent.com/PWhiddy/PokemonRedExperiments/master/baselines/memory_addresses.py), [search summary of Mintlify pokered docs](https://www.mintlify.com/pret/pokered/reference/data-structures)
- ROM-side modification point: `TrainerDataPointers` and `data/trainers/parties.asm` in pokered (see section 1).
- Gen 1 damage mechanics: crit chance is Speed-based, base Speed x 100 / 512 (high-crit moves x8, capped about 99.6% by a glitch; Focus Energy bug reduces crit rate by 4x); crits ignore stat stages. — [Smogon RBY critical hits](https://smogon.com/rb/articles/critical_hits), [Showdown gen1 mod README](https://cdn.jsdelivr.net/npm/@wcyat/pokemon-showdown@0.11.9/data/mods/gen1/README.md)
- Official calculator source: smogon/damage-calc — [GitHub](https://www.github.com/smogon/damage-calc). Gen 1 mod lives under Pokemon Showdown `data/mods/gen1` (README mirrored above; mirror is an old npm fork, verify against smogon/pokemon-showdown).

### Inferences
- For a swarm needing scripted opponents, the lowest-risk approach is a patched ROM built from pokered with modified trainer tables, rather than runtime RAM writes (inference; not sourced).
- Showdown's gen1 mod can be a reference oracle for damage/crit verification against PyBoy runs (inference).

### Gaps
- No source found for Gameshark codes or RAM-write recipes to alter trainer parties; D89C not independently confirmed beyond Data Crystal. Exact wBattleMon/wEnemyMon field offsets not captured. Showdown gen1 code path not confirmed.

## 5. NPC/object reading and map rendering tools

### Takeaway
Runtime NPCs are readable from the sprite state tables at $C100/$C200; static object placement is in pokered map object data. No dedicated map-with-NPC renderer was identified in this pass beyond agent harness ASCII/walkability maps.

### Cited Findings
- Runtime sprite tables and their offsets: see section 1 ([wram.asm mirror](https://v10.next.forgejo.org/foster/pokered/src/branch/master/ram/wram.asm)). Data Crystal confirms the same ranges and OAM buffer at C300-C39F ([Data Crystal](https://datacrystal.tcrf.net/wiki/Pok%C3%A9mon_Red_and_Blue/RAM_map)).
- Missable-object (show/hide) flags at D5A6-D5C5 control NPC presence ([Data Crystal](https://datacrystal.tcrf.net/wiki/Pok%C3%A9mon_Red_and_Blue/RAM_map)).
- Harness examples render RAM-derived maps with NPCs: Continual Harness ASCII map ([arXiv](https://arxiv.org/html/2605.09998v1)); Claude's RAM walkability overlay ([Reddit snapshot](https://reddit.sentinel-team.org/posts/1t5y7ac/snapshots/2026-05-07T08%3A28%3A48.951918Z)).

### Inferences
- Combining map header/tile data (D367+, ROM blocksets) with sprite tables yields the ASCII map with NPCs; source code for such a builder was not found to reuse.

### Gaps
- No ROM-side object table format documented here; no dedicated third-party map-viewer tool (e.g. with NPC render) found; Gen 2 tooling (pokecrystal) not covered.
