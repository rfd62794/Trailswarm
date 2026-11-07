# Live-state viewers and ROM data extractors for Game Boy / Pokemon (trackers, map/NPC viewers, save editors, multi-agent maps)

Note on method: page fetches were summarised by a small model; where the summary said a page did not cover something, that is recorded as a gap rather than guessed.

## 1. Pokemon live trackers (Ironmon Tracker, BizHawk Lua overlays, stream widgets)

### Takeaway
The main live tracker (Ironmon Tracker) is Gen 3 only and is a Lua script inside BizHawk/mGBA, split into Memory / GameSettings (per-version address tables) / Program / Drawing modules with an extension API. For Gen 1, the closest found is a small BizHawk Lua "memory reader" that exposes party data as JSON over local HTTP, which is the memory-reader-to-presentation split a World view would want.

### Cited Findings
- Ironmon Tracker is "a collection of lua scripts" for BizHawk (2.8+) or mGBA (0.10+); supports Ruby, Sapphire, Emerald, FireRed, LeafGreen (non-English: FireRed only). Code must run on Lua 5.1 and 5.4. — [besteon/Ironmon-Tracker](https://github.com/besteon/Ironmon-Tracker)
- mGBA has no drawing functionality, so the tracker is text-only there; BizHawk renders images. — [besteon/Ironmon-Tracker](https://github.com/besteon/Ironmon-Tracker)
- Module layout of `ironmon_tracker/`: Drawing.lua, GameSettings.lua, Memory.lua, Program.lua, Inifile.lua. — [ironmon_tracker folder](https://github.com/besteon/Ironmon-Tracker/tree/main/ironmon_tracker) (as reported by search result)
- Since v9.0.0 all GameSettings addresses are stored as JSON files, one per game version; a lightweight TrackerAPI exists for extensions. — [Version Changelog](https://github.com/besteon/Ironmon-Tracker/wiki/Version-Changelog) (search-result summary; changelog page not fetched in full)
- Extensions (since v7.3.0) live outside the main code and survive upgrades; they hook events via `EventHandler.addNewGameEvent`/`triggerEvent` and must remove them on unload. A CodeExtensionTemplate.lua.txt is provided. — [Tracker Add ons wiki](https://github.com/besteon/Ironmon-Tracker/wiki/Tracker-Add-ons), [Stream Connect Guide](https://github.com/besteon/Ironmon-Tracker/wiki/Stream-Connect-Guide)
- Pokemon Memory Reader: BizHawk Lua script (load `main.lua`) for Pokemon Red/Blue/Yellow that serves party data/stats as JSON from a local HTTP endpoint for external overlays. — [NathanTBeene/pokemon-memory-reader (mirror)](https://gh.r-mj.com/NathanTBeene/pokemon-memory-reader)
- yPokeStats (ylingstats.lua) is a read-only Gen 1-5 stats overlay script for emulators; in-game overlays would need a ROM patch. — [r/pokemonrng thread](https://redlib.ssps.io/r/pokemonrng/comments/nm6omh/my_lua_script_gen_15/gzrlc2c/?context=3)
- A third party (Planton361 workspace) claims a pinned v9.3.1 load order of extension beforeGameDataLoad -> GameSettings.initialize -> other modules -> extension startup. — [issue #688](https://github.com/Planton361/firered-gen9-randomizer-workspace/issues/688) (third-party, unverified)

### Inferences
- Ironmon's per-version JSON address files plus a Memory module are a proven template for "versioned address table + reader" separation; Gen 1 would use the same idea with RBY revisions (and the Japanese variants).
- The HTTP-JSON bridge in pokemon-memory-reader shows the viewer can be a separate process from the emulator, which suits multi-agent use.

### Gaps
- Ironmon's actual GameSettings JSON schema and Gen 3 address layout were not read (wiki page not surfaced).
- No Twitch Plays Pokemon-specific overlay source found; no Gen 1 tracker comparable to Ironmon found beyond the small tools above.
- Maintenance status of pokemon-memory-reader unknown (accessed via a mirror).

## 2. Map and NPC extraction/rendering from ROM (pret, Porymap, Polished Map, full-world maps)

### Takeaway
pokered already contains everything needed as plain text: per-map headers with connections, per-map object files (warps, signs, NPCs with sprite/movement/text), and sprite PNGs. A full Kanto world map has been built purely from these by walking connections and matching warps; Polished Map is the editor for Gen 1/2 map blocks; Porymap is Gen 3 only.

### Cited Findings
- pokered object files use three macros: `warp_event x, y, DEST_MAP, dest_warp_id`; `bg_event x, y, TEXT_...`; `object_event x, y, SPRITE_..., STAY|WALK, direction, TEXT_...` (example Oak: `object_event 8, 5, SPRITE_OAK, STAY, NONE, TEXT_PALLETTOWN_OAK`). — [pokered PalletTown.asm](https://raw.githubusercontent.com/pret/pokered/master/data/maps/objects/PalletTown.asm)
- Map headers (e.g. `data/maps/headers/PalletTown.asm`) list connections to neighbouring maps. — [Vjeux write-up](https://blog.vjeux.com/2023/project/pokemon-red-blue-map.html)
- Vjeux built a Red/Blue world map (final 7200x7200 per search snippet) by recursive traversal of connections from Pallet Town, placing interiors by overlaying warp doors on mats and searching outward for a free spot (stepping by 4 tiles = one block), then manual adjustment. — [Vjeux](https://blog.vjeux.com/2023/project/pokemon-red-blue-map.html), [Vjeux blog index](https://blog.vjeux.com/?p=5407)
- pokered lists sprites per map and ships them as PNG; the PNGs have white as background (needs transparency), only left-facing frames are stored (right is a flip). — [Vjeux](https://blog.vjeux.com/2023/project/pokemon-red-blue-map.html)
- Polished Map is a map/tileset editor for pokecrystal, pokegold, pokeyellow, pokered and hacks; its example project includes stitched overworld `.blk` files (Kanto.180x135.kanto.blk); Events Mode edits events and follows warps. — [Rangi42/polished-map](https://github.com/Rangi42/polished-map)
- Porymap is a map editor for Gen 3 decomp projects (pokeruby, pokeemerald, pokefirered) only; Qt/C++. — [huderlem/porymap](https://github.com/huderlem/porymap)
- pokered repo layout: `maps/`, `data/`, `constants/`, `gfx/`, `ram/`, `Makefile`, plus a `symbols` branch. — [pret/pokered](https://github.com/pret/pokered)
- pokered has `wram.asm`-derived memory layout docs (mirror). — [Mintlify pokered memory layout](https://www.mintlify.com/pret/pokered/architecture/memory-layout)

### Inferences
- A viewer can generate a build-time asset bundle (map blocks, tileset PNGs, object lists, sprite sheets) by parsing pokered `.asm`; no ROM binary parsing is needed for Red/Blue.
- Interior-map global placement is a heuristic (not in the game data), so a hand-corrected `map_id -> (x, y)` offset table is the realistic approach (this is what pokerl-map-viz uses, see section 4).

### Gaps
- Did not find a ready-made stitched full-world PNG with licence; only Vjeux's site and the community map used by pokerl-map-viz (credited to Death Strike Gaming).
- Block (`.blk`) and tileset binary formats not described by fetched pages.
- Peter Hajas's map parsing write-up referenced by Vjeux was not fetched.

## 3. Save-file parsers and editors (PKHeX Gen 1, pokered save format, Python libraries)

### Takeaway
PKHeX supports Gen 1 saves in a UI-independent core library, but saves only update on in-game save, so they are not a live source. Python options are thin: one archived Codeberg library and old gists; RAM reading via the pret symbol file is the better live route.

### Cited Findings
- PKHeX has a `PKHeX.Core` library separate from WinForms/Drawing projects; transfers/converts across generations. — [kwsch/PKHeX](https://github.com/kwsch/PKHeX)
- A docs mirror lists PKHeX's SAV1 class covering Red/Blue/Yellow with a Japanese flag (box counts 8 JP / 12 INT). — [Mintlify PKHeX Gen 1/2 docs](https://mintlify.com/kwsch/PKHeX/api/saves/generation-1-2) (third-party mirror)
- Release notes mention improved Yellow detection for saves without a chosen starter; a forum thread reports a Red/Blue load bug around 25.8.30 attributed to an event flag block change. — [Project Pokemon release](https://projectpokemon.org/home/index/news/pkhex-250830-r185/), [thread](https://projectpokemon.org/home/forums/topic/67143-pkhex-250830/)
- `emberquill/pkmn-gen1` (Python, Codeberg) parses Gen 1 saves (trainer, dex, bag, party, PC, money, badges, checksums); archived 2026-02-05; successor `emberquill/pkmn` last visible commit April 2025. — [pkmn-gen1](https://codeberg.org/emberquill/pkmn-gen1), [pkmn](https://codeberg.org/emberquill/pkmn)
- Older references: mplewis gist (Python 2 style byte offsets), Miss-Inputs gist (unfinished lister with text/item tables), PikaExplorer (JS), arktosmos-pkmn-sav-editor (TS, Gen 1-3). — [mplewis](https://gist.github.com/mplewis/9383518), [Miss-Inputs](https://gist.github.com/Miss-Inputs/b838b0114eee220fe5adffb1e8b9fd27), [pkgstats](https://www.pkgstats.com/pkg:arktosmos-pkmn-sav-editor)
- A walkthrough of the Red save layout exists. — [LiveOverflow, Dissecting Pokemon Red Savegame](https://rosetta.to/u/liveoverflow/dissecting-pokemon-red-savegame)

### Inferences
- Gen 1 SRAM and WRAM party structures are largely the same layout, so a save parser's struct definitions (party mon, box mon, checksums) can be reused to decode WRAM live.

### Gaps
- PKHeX SAV1 offsets not verified against source; the mirror's offsets were not relied on.
- No maintained GitHub Python Gen 1 save library found.

## 4. Multi-agent visualisations (PokemonRedExperiments, puffer, shared maps)

### Takeaway
pokerl-map-viz is the directly relevant design: agents broadcast small JSON messages (path of [x, y, mapId] plus metadata) and a PixiJS client converts them to global coordinates via a `map_data.json` offset table and draws per-user sprites on a big Kanto image.

### Cited Findings
- PokemonRedExperiments streams to a shared global map through `baselines/stream_agent_wrapper.py` (metadata: username, env_id, color, extra); viewer lives in the separate `pokerl-map-viz` repo; V2 streams by default. — [PWhiddy/PokemonRedExperiments](https://github.com/PWhiddy/PokemonRedExperiments)
- pokerl-map-viz repo: `ws-server/`, `large-scale-viz/`, `old_static_visualizer/`, `visualizer_live.js`, `pixi.js`, MIT; the "complete map" is credited to Death Strike Gaming; optional `sprite_id` 0-50. — [PWhiddy/pokerl-map-viz](https://github.com/PWhiddy/pokerl-map-viz)
- Wire format: JSON from a WebSocket; position message has `coords` (array of `[x, y, mapId]`) and `metadata` {`user` required, `env_id`, `extra`, `color`, `sprite_id`}; sprite key is `user-env_id`; stats message has `viewers` and `envs`. — [visualizer_live.js](https://raw.githubusercontent.com/PWhiddy/pokerl-map-viz/main/visualizer_live.js)
- Conversion: `assets/map_data.json` has `regions[]` with `id` and `coordinates [mapX, mapY]`; global = `[x + mapX - 217.5, y + mapY - 221.5]`, times 16 px; unknown map id logs a warning and goes to [0,0]. — [visualizer_live.js](https://raw.githubusercontent.com/PWhiddy/pokerl-map-viz/main/visualizer_live.js)
- Rendering: sprite sheet `characters_transparent.png` with 16x16 frames at (9+17x, 34+17y); direction columns down=1, up=4, left=6, right=8; interpolation over an EMA of update intervals (min 1 s); stale sprites removed after 2 min; regex label filter; background `kanto_big_done1.png` crossfaded smooth/sharp by zoom. — [visualizer_live.js](https://raw.githubusercontent.com/PWhiddy/pokerl-map-viz/main/visualizer_live.js)
- pokemonred_puffer has wrappers incl. logging to the map visualiser, `eval.py` for training visualisations, and `kanto_map_dsv.png` (high-res Kanto map). — [drubinstein/pokemonred_puffer](https://github.com/drubinstein/pokemonred_puffer)

### Inferences
- The `[x, y, mapId]` + offset table design means agents need only report local coordinates and map id; NPC and agent drawing share one coordinate transform.
- The same `map_data.json` can probably be reused or regenerated; its licence/contents were not inspected (file not fetched).

### Gaps
- `map_data.json` contents, ws-server code, and `large-scale-viz/` not read.
- puffer's own RAM map module (`ram_map`) not found in fetched page; not confirmed.

## 5. Architectural patterns (memory adapters, schema-driven maps, versioned tables, disassembly verification)

### Takeaway
Common pattern: take addresses from pret's symbol file (`pokered.sym`), keep them in per-version data files, read with an emulator API (PyBoy `memory[...]`, BizHawk/mGBA Lua), and keep presentation separate behind a JSON bridge.

### Cited Findings
- `pokered.sym` lines look like `bank:addr label` (e.g. `00:d16c wPartyMon1HP`); labels pointing into ROM cannot be read as RAM and need a hook at the nearest label (example: CUT detection). — [pokerl: Reading RAM](https://drubinstein.github.io/pokerl/docs/chapter-3/reading-asm)
- The symbols file is on pokered's `symbols` branch; the page does not say which revision it matches, so check against your ROM. — [pokerl: Reading RAM](https://drubinstein.github.io/pokerl/docs/chapter-3/reading-asm), [pret/pokered](https://github.com/pret/pokered)
- Data Crystal Red/Blue RAM map: map id `D35E`, player Y `D361`, X `D362`, block Y/X `D363/D364`, party count `D163`, badges `D356`; sprite state tables `C100-C1FF` (picture id, movement status, image index, screen Y/X pixels, facing 0/4/8/$C) and `C200-C2FF` (grid Y/X, movement byte, delay); has JPN and INT columns for some entries. — [Data Crystal RAM map](https://datacrystal.tcrf.net/wiki/Pok%C3%A9mon_Red_and_Blue/RAM_map)
- Data Crystal warns the "Level" byte in the party struct at the first offset is not the actual level (real level at `D18C` for mon 1). — [Data Crystal RAM map](https://datacrystal.tcrf.net/wiki/Pok%C3%A9mon_Red_and_Blue/RAM_map)
- An unmerged PyBoy PR (#176) added a Pokemon Red helper plugin for multi-byte ints and text. — [PyBoy PR 176](https://www.github.com/Baekalfen/PyBoy/pull/176)
- Ironmon: per-game-version JSON address files (see section 1).

### Inferences
- Suggested design: generate `ram_map_<rom_revision>.json` (name, address, size, type) from `pokered.sym` at build time, assert the ROM hash/revision on load, and treat Data Crystal as a cross-check since it is a wiki (can lag the disassembly).
- NPCs for the shared map: static NPC placement from pokered object files (section 2) plus live movement from the sprite tables in `C1xx/C2xx` (current map only, 16 slots) means only NPCs on each agent's current map are observable live.

### Gaps
- No existing standard JSON/YAML schema for Pokemon Red RAM found.
- No public tool found that verifies an address table automatically against the disassembly.
- Gen 2 (pokecrystal) specifics not researched.
