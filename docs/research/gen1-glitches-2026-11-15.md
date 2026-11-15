# Generation I (Red/Blue) glitches and what they point to - PokeAgent research

Date 2026-11-15. Read-only research; nothing run, nothing edited in the repo.
Evidence labels: **[F]** = from a page I fetched this session (cited). **[K]** = from general background knowledge of the
Gen I glitch scene, NOT verified against a fetched source this session; re-check before relying on it. **[H]** = my
hypothesis/inference. Fetch summaries are paraphrases by a small model, so addresses should be re-verified at source
(pret/pokered `ram/wram.asm`) before being hard-coded.

## 1. Summary

- Most famous Gen I glitches reduce to a few engine weaknesses: (a) per-map "meta-map script" bytes and trainer-battle
  bookkeeping that can be desynced (trainer escape glitch, 0xF8FF, 0 ERROR walking lag); (b) unchecked table indices -
  item ids, move ids, quantities of stacked items (item underflow, 8F, glitch items, glitch moves); (c) stale RAM that the
  game assumes is refreshed on map load (Old Man / Missingno grass-slot reuse); (d) map coordinates/blocks read out of
  bounds (Glitch City, walk-through-walls, wrong warps); (e) path/movement buffers that overflow into flags
  (Brock through walls, $CCF9 -> $CD3B). Arbitrary code execution (ACE) is the far end of (a) and (b).
- Promising for an agent: the *observable* ones. Meta-map-script desync produces fast, detectable signatures (walking lag,
  repeated battles, Start menu error, 0xCD60/0xD730 flags). Stale-encounter-table and out-of-bounds map reads produce
  odd species/levels and odd map ids that the existing discovery detectors already flag. Item/bag corruption is already
  checked by `legality.py`.
- The agent can already see: raw RAM via PyBoy (`emu.read`), `Snapshot` features (map, flags, bag, PC, money, party, in_battle),
  `legality.check` (bag, money, map, coords, party, pokedex invariants), and `novelty/discoveries.py` detectors
  (glitch_map, new_map, flag_out_of_order, item_jump, money_jump, level_without_xp, species_unseen ...) logged to
  `runs/discoveries.jsonl` with save states in `runs/discoveries/` that no curriculum code reads.
- Biggest caution: several of these (ACE, SRAM glitch, item/box corruption, cloning) can corrupt SRAM/save data. Explore
  only from throwaway copies of save states, with SRAM writes disabled/redirected. Safety column in section 2.

## 2. Catalogue (about 25)

Route key: current route = Pallet -> Viridian City -> Viridian Forest -> Pewter -> Mt. Moon -> Cerulean -> Vermilion
(S.S. Anne). "Route?" = whether the trigger is reachable there without HMs from later (Fly/Surf/Strength not available
before Vermilion; Cut is on the S.S. Anne). Safety: H harmless, S can softlock, C can corrupt save, X can crash.

| # | Name | Mechanism (RAM / engine) | Trigger | Observable signature | Route? | Safety | Source |
|---|------|--------------------------|---------|----------------------|--------|--------|--------|
| 1 | Viridian Forest 0xF8FF glitch | Invalid meta-map script value 06 -> invalid predefined command 0xF4 makes the engine execute at 0xF8FF (echo RAM, inside enemy trainer mon 3 data) instead of 0xF808; falls through player name copies and play-time bytes into stored-mon data; can reach Hall of Fame script | Needs engineered name "mMna.♀tF", Trainer ID 61896 (F1C8), death-warp on last Bug Catcher, double fight, save, fight first Bug Catcher | Walking lag, interrupted A presses, immediate re-fight of same trainer; then ACE/Hall-of-Fame warp | Yes (Viridian Forest) but needs player name + ID that agent cannot set organically | X, C (ACE) | [F] https://glitchcity.wiki/wiki/Viridian_Forest_0xF8FF_glitch |
| 2 | Trainer escape glitch | Spotted trainer sets map's meta-map script 0->1, loads wEngagedTrainerClass/Set (0xCD2D/0xCD2E), sets 0xCD60 bit0 and 0xD730 bit0; leaving by Fly/Teleport/Dig/Escape Rope/Start-mid-step leaves state stale; on return the stored text box id runs and a battle starts | Escape a trainer mid-approach (see steps in source) | Start menu and NPC talk disabled; instant encounter on return; sightlines disabled; freeze if trainer never moves | Partly: Start-mid-step with long-range trainer, Escape Rope, Dig (Mt. Moon) are possible; Fly/Teleport not | S (0xD730 bit0 stuck), H otherwise (0xCD60 bit0 clears on save+reload) | [F] https://glitchcity.wiki/wiki/Trainer_escape_glitch, https://glitchcity.wiki/wiki/Trainer-fly_glitch |
| 3 | Death-warp | Wild encounter inside a trainer's line of sight then black out = trainer escape without an item | Grass/cave encounter while a trainer spots you, faint | Respawn at Pokemon Center with trainer state stale; instant encounter on return | Yes (Viridian Forest, Mt. Moon trainers with grass/cave) | S | [F] Trainer_escape_glitch page; used in the 0xF8FF steps |
| 4 | Meta-map script activation (walking lag / "0 ERROR") | Per-map meta-map script byte (WRAM, first Red/Blue entry D5F0 W_OAKSLABCURSCRIPT, last accessible D63A) pushed out of valid range (3, 4, ...) by trainer text box; persists across leave/save/reset | Trainer escape variants; dry underflow with stored PC items | Long pauses between steps, error code on Start menu, sound glitches, vanishing sprites, possible freezes | Yes in principle (Forest/Mt. Moon trainers) | S, C (value persists in save) | [F] https://glitchcity.wiki/wiki/Meta-map_script_activation |
| 5 | Trainer-fly / Mew trick | After trainer escape, the next encounter species is chosen by the stale last-Special stat in memory | Escape trainer, fly away, return, encounter | Unexpected species at a route; instant encounter | No (needs Fly; Mew is a non-organic species) | H | [F] Trainer-fly_glitch page |
| 6 | Old Man glitch / Missingno encounter | Demo changes player name at $D887 (grass encounter rate address), restores only that byte; stale grass list from $D888 remains if no map reload; shore tiles read it; name characters select species/level | Old man demo in Viridian, then Fly to Cinnabar/Fuchsia, surf a left-facing shore tile | Encounter with glitch species ids (Missingno., 'M) and glitch trainers; bag slot 6 += 128 on Missingno. | Setup half yes (Viridian old man is early), trigger half no (Fly + Surf needed) | C (Missingno. effects, item mutation), X possible | [F] https://glitchcity.wiki/wiki/Old_man_glitch |
| 7 | Brock through walls | Path copy at $CCF9 for unknown player coordinates talking to Pewter Youngster overflows into $CD3B (movement override flag); holding a button then walks through walls | Reach Youngster from the right, prime party-screen RAM setup (specific PP/level/moves), talk | Free movement through walls and NPCs | Needs Pewter Gym skip + exact party setup; not organic | S, C if combined with cloning | [F] https://glitchcity.wiki/wiki/Brock_through_walls |
| 8 | Pewter Youngster softlock | Same lookup: coordinates not found in table, game never exits path | Talk to Youngster from the right (not intended) | Game stops responding to input | Yes (Pewter) | S | [F] Brock_through_walls page |
| 9 | Walk through walls (family) | Overwrite movement/collision (Rival's effect, Select glitch, ledge, museum guy, F9 box set, map-size) | Various; see source | Player on wall/impassable tiles; coordinates over bounds | Partly (ledges on Route 22/other) | S | [F] https://glitchcity.wiki/wiki/Walk_through_walls (disambiguation only) |
| 10 | Glitch City / out-of-bounds maps | Map header/block source pointer (D35F/D360) or y-position beyond y-boundary reads tiles from wrong RAM; wrong warps (Safari exit etc.) | Many, see source | Map id outside normal list (e.g. 0xE7, 0xED..0xF4 in Yellow, 0xFE); garbled tiles | Not organic; detector exists | S, X | [F] https://glitchcity.wiki/wiki/Glitch_City_(Generation_I) |
| 11 | Item underflow (event method) | Gives away a stacked item and quantity wraps (0 -> 255); stack >99 | Give guard a drink / scientist a fossil | Bag qty 255 or >99, item stacks over 99 | No (guard/Cinnabar are later) | H/C | [F] https://glitchcity.wiki/wiki/Item_underflow (disambiguation) |
| 12 | Dry item underflow | Item stack merge oversight lets the quantity or slot be edited past bounds; item 50 edit overwrites meta-map script byte | Stack manipulation via PC/Bag | Qty out of 1..99, duplicate ids, overwritten script byte | Partly | C | [F] Meta-map_script_activation + Item_underflow pages |
| 13 | Expanded items pack | Bag read beyond its 20-slot capacity into adjacent RAM | Underflow setups | Item count > 20 or terminator missing (already checked in `legality._bag`) | Needs setup | C | [F] referenced from 0xF8FF page |
| 14 | 8F glitch item | Item id indexes a jump table out of bounds, jumps into the species list (usable as code entry) | Select/use glitch item | Item id past the catalog in bag | No (need item) | X, C | [F] https://glitchcity.wiki/wiki/Arbitrary_code_execution |
| 15 | Glitch moves ("-", TM42) | Move id out of the move table used for ACE entry | Learn/use glitch move | Move ids out of range in party | No | X, C | [F] Arbitrary_code_execution page |
| 16 | Arbitrary code execution (family) | Items, moves, map script pointer, invalid meta-map script, trainer-escape text boxes | See rows 1, 4, 14, 15 | Crashes, odd screens, unexpected RAM writes | Not for agent | X, C | [F] https://glitchcity.wiki/wiki/Arbitrary_code_execution |
| 17 | Cut glitch (Bulbapedia name) | Cutting a tree in certain maps swaps a block id in the live map buffer; in glitch maps with bad block source it rewrites RAM | Use Cut near tree on Glitch City | Block id change, odd RAM write | Cut available after S.S. Anne; not tried | S | [F] Glitch_City page mentions cutting a tree to modify RAM; [K] for details |
| 18 | Missingno. / 'M side effects | Species 00/glitch ids use odd base-stat/sprite pointers; bag slot 6 += 128 if < 128 | Via row 6 | Species id 0 or >190 in enemy mon | No | C, X | [F] Old_man_glitch page |
| 19 | Level 255 rare candy / leveling past 100 | One-byte level overflow (rare candy at L255 gives L0); stat recalculation | Cheat or glitch to get L100+ | Party level 0 or >100 (checked by party_stats) | No | C | [K] Bulbapedia (search snippet in section 6) |
| 20 | Safari Zone exit glitch | Wrong warp from Route 19/sea tiles into Safari zone map data | Surf at specific tiles | Glitch map or Safari map arrival | No (Surf, Safari later) | S | [F] Glitch_City page lists it as a trigger |
| 21 | Pokemon Center / PC SRAM glitch | Box switching writes to wrong SRAM bank, corrupting box data | Change box name/active box at a specific moment | Box data differs after reload | Not applicable (no PC use needed) | C | [F] mentioned in 0xF8FF and Trainer_escape pages as "SRAM glitch" |
| 22 | Select glitch (walk through walls trick) | Select press in a menu writes into a pointer | Press Select during specific menu | Walking through walls / odd menu | Unknown | S | [F] mentioned in Walk_through_walls page; [K] for mechanism |
| 23 | Cinnabar / step-count glitches | 500th step at Pokemon League -> "Glitch League" map; Cycling Road 500th step -> "Glitch Mountain" | Walk 500 steps | Glitch map id | No | S | [F] Glitch_City page |
| 24 | Ghost Marowak / Pokemon Tower | Not covered in fetched pages | - | - | No | - | [K] no source this session |
| 25 | Pikachu off-screen glitch (Yellow) | Super Glitch City | Yellow only | - | N/A | - | [F] Glitch_City page |

Rows 24-25 are placeholders (see section 6: Bulbapedia list was blocked, so the catalogue is built from glitchcity.wiki
pages and background knowledge; rows with [K] need verification).

## 3. Viridian Forest in depth

### 3.1 The 0xF8FF glitch (glitchcity.wiki) [F]

Source: https://glitchcity.wiki/wiki/Viridian_Forest_0xF8FF_glitch

- Core effect: arbitrary code execution at 0xF8FF in Echo RAM, in the middle of the opponent trainer's mon 3 data.
- Chain: beating the trainer twice sets the meta-map script to the glitch value 06, which causes walking lag and can
  interrupt A presses. Beating another trainer then executes F8FF. Copies of the player's name are run as code,
  falling through to play-time bytes (which must be "safe") and then stored Pokemon data. If exactly one specific mon with
  the right id is stored, the code can run the Hall of Fame script.
- Further research (TheZZAZZGlitch, as reported on the page): execution of F8FF comes from invalid predefined command
  0xF4; the game should run F808 but runs F8FF because of a VRAM-related detail.
- Setup: player name "mMna.♀tF", Trainer ID 61896 (F1C8), Charmander or Bulbasaur starter, a Spearow named "AAA" on
  Route 22, starter deposited in the PC, a death-warp on the last Bug Catcher (grass encounter in his line of sight, then
  faint), return without opening Start or any text box, fight him (win or lose, he re-fights you), which activates
  meta-map script 06; save south of the Forest (play time incl. frames matters); then fight the first Bug Catcher with A
  mashing; win; luck decides entry to the Hall of Fame.
- Caveats on the page: needs exact CPU timing and fails on some emulators (VisualBoyAdvance, Pokemon Stadium 2, maybe 3DS
  VC). The page says SRAM glitch is faster for completing English Red/Blue and Brock through walls makes it obsolete for
  that purpose.
- No wRAM symbols beyond those above are given on the page.

What it points to: (1) the trainer double-fight is the observable half; a trainer re-fights the player immediately after the
first fight, and walking lag appears. That is detectable without any exotic setup. (2) The code-execution half needs a
chosen player name and Trainer ID: out of reach for an organic agent and unnecessary to try.

### 3.2 The Reddit Viridian Forest report

Source 4 (reddit /r/PokemonGlitches/comments/1e05oe3/...) could NOT be fetched (WebFetch refuses reddit.com). I do not
know what that post describes and have not guessed. Source 2 (reddit "glitch ideas") likewise failed. Suggest Robert pastes
the posts if they matter; the agent-side detectors in section 5 are mechanism-agnostic.

Anything about the report beyond this is [H]: the Forest's trainers and its dense grass are exactly where the trainer
escape / death-warp mechanism applies, so odd behaviours there most likely involve the meta-map script byte or the
trainer bookkeeping flags (0xCD60, 0xD730, 0xCD2D/0xCD2E). Check those first.

## 4. Where known glitches point - mechanism families and safe hypotheses

For each: what to vary, what signature means "new". All tests on throwaway state copies, headless.

1. **Meta-map script / trainer bookkeeping desync.** Underlying: per-map script byte (D5F0..D63A range in Red/Blue [F]),
   0xCD2D/0xCD2E, 0xCD60 bit0, 0xD730 bit0.
   - Hypothesis: other maps on the route (Route 22, Route 2, Mt. Moon, Route 3, Route 24) show the same persistent
     walking-lag state after a death-warp from a trainer's line of sight, with different script byte values.
   - Vary: which trainer, which tile spotted on, time of faint, whether Start is pressed. Log the script byte range
     (D5F0..D63A) before/after.
   - New = a script byte outside the values seen on organic runs, or the same value on a different map.
2. **Unchecked item/move/species ids.** Underlying: tables indexed without range checks (jump tables for items, move
   table, species-to-dex table).
   - Hypothesis: the state space of plausible bag/party manipulation inside a throwaway copy is bounded and boring; the useful
     work is detection: when the party or bag has an id outside the catalog, flag it (already done by `legality`).
   - Do NOT inject ids; only observe ids that appear after other experiments.
3. **Stale RAM assumed refreshed on map load (Old Man / grass slot reuse).** Underlying: $D887 name overlay, $D888+ grass list,
   only refreshed by map load [F].
   - Hypothesis (safe, on route): other "temporary name" or temporary data overlays exist (rival name entry, nickname
     screens, the Pokedex rating, Oak's lab intro). Look for RAM regions rewritten at one event and not restored: compare
     the encounter table bytes ($D887 area) before and after each early-game scripted event, using Fly-free paths.
   - Vary: order of events and whether a map load (door, stairs) occurs in between.
   - New = encounter table bytes differing from the map header's table for the current map (a stale list).
4. **Out-of-bounds map reads.** Underlying: map y-boundary check, D35F/D360 block pointer, warp tables [F].
   - Hypothesis: map edge tiles where `legality._world` already notes coordinates outside map size or odd view pointer
     (warning "view pointer != expected"). Those are the first places a reader would see an out-of-bounds block read.
   - Vary: approach edges of routes in the "walk grid" along unconnected borders; log any frame where (x,y) exceeds the
     map's own bounds or the view pointer departs from `expected_view_pointer`.
   - New = a (map, x, y) outside bounds that the game still accepted; a map id not in `map_names.json`.
5. **Buffer overflows into flags (path/movement buffer).** Underlying: $CCF9 path copy overflowing into $CD3B [F].
   - Hypothesis: other NPC "movement path" tables copy to the same buffer; talk to NPCs from unusual sides. Pewter Youngster
     from the right is the known one [F]. Others unknown.
   - Vary: the tile from which each NPC is addressed. Log whether input is accepted after dialog (a lock-up) and whether
     $CD3B becomes nonzero.
   - New = $CD3B != 0, or input ignored while no text/menu is open.
6. **Menu/text-box state.** Underlying: text box id matching; Start press mid-step; map reload while menu open [F].
   - Hypothesis: Start/B/A input timing right around spotting, warp and door transitions can leave bits in 0xCD60 etc.
   - Vary: input frame offsets relative to a trainer spotting or a warp.
   - New = 0xCD60 bit0 or 0xD730 bit0 set while no trainer is engaged.
7. **Encounter/species selection from stale stats (Mew trick, Missingno.).** Underlying: encounter derived from last Special
   stat [F].
   - Hypothesis: the agent can record, per instant-encounter occurrence, the species and compare to the map's normal table;
     any species not in the map table is a signature.
   - New = enemy species not in the current map's table.
8. **Arbitrary code / 8F.** Underlying: jump through unchecked index, execution from data [F].
   - Hypothesis: none that is safe to test here. Treat as out of scope; detection only (unexpected RAM writes outside
     expected regions, code-like byte patterns in party data).

## 5. Exploration design notes

Fits the existing code:
- `novelty/discoveries.py` already flags: glitch map (`odd_map`), new map, flag out of order, item jump, money jump,
  level without xp, species unseen. Records go to `runs/discoveries.jsonl` with save states in `runs/discoveries/`;
  `is_discovery_state` is the guard that keeps these states away from checkpoint/segment/curriculum code
  (`checkpoint_goals.py:135`, `invariants/states.py:47` flags a discovery state in the checkpoint dirs as an ERROR).
- `legality.check` (read-only) already catches: bag count > capacity, missing 0xFF terminator, ids out of catalog, qty
  outside 1..99, duplicate ids, money not BCD, glitch map, respawn map not a town, (x,y) outside map or on a
  non-walkable tile, view pointer mismatch (warning), party invariants, pokedex consistency.
- `explorer/memory.py` line ~105 treats "fades/glitches" as the reason an earlier warp disproof can be stale.

Detectors to add (log only, never reward; all new):
1. Trainer bookkeeping: 0xCD60 bit0, 0xD730 bit0, 0xCD2D/0xCD2E nonzero while `in_battle` is false and no trainer is
   currently approaching.
2. Meta-map script bytes (D5F0..D63A): diff per step, flag values outside the set seen on organic runs.
3. Movement-lock: $CD3B != 0.
4. Encounter table ($D887.. area) differing from the current map's header table.
5. Enemy species not in the current map's table; enemy species id 0 or beyond the valid range.
6. (x,y) beyond map bounds (already `legality`), view pointer mismatch outside transitional frames.
7. Input-ignored detector: no screen/state change for N frames with no text box or menu.
8. Unexpected WRAM writes: hash a set of regions that normal play should not change during overworld walking, and log changes.

Rules:
- Run only from throwaway copies of save states, never `runs/checkpoints` or the curriculum segment states. Write
  discovery states only under `runs/discoveries/`. Keep SRAM writes redirected/disabled.
- Headless PyBoy only; no GUI input on Robert's screen.
- No ROM bytes or hex dumps of ROM in docs or logs; only RAM addresses and observed values. No ACE payloads, no
  Hall-of-Fame setup, no name/Trainer-ID engineering, no writes to SRAM/save files via glitches. Nothing published as ROM
  data; save states stay in gitignored `runs/`.
- Every discovery is evidence for Claude/Robert to review, not a starting point and not a reward.
- Zero-risk first: start with observation detectors on ordinary runs (cheap, no experiments), then single controlled
  variations (death-warp timing) from copies.

## 6. Sources and access status

| Source | Status |
|--------|--------|
| 1. https://glitchcity.wiki/wiki/Viridian_Forest_0xF8FF_glitch | LOADED |
| 2. reddit r/PokemonGlitches 13exxp4 (glitch ideas) | FAILED (WebFetch cannot fetch reddit.com) |
| 3. web.archive.org glitchcity.info namegen2 | FAILED (WebFetch cannot fetch web.archive.org) |
| 4. reddit r/PokemonGlitches 1e05oe3 (Viridian Forest weird glitch) | FAILED (reddit blocked) |
| 5. Bulbapedia List of glitches in Generation I | FAILED (HTTP 403; also retried the parenthesised URL once, 403) |
| One web search | Returned only Bulbapedia/Smogon/glitchcity.info URLs and snippets (rare candy overflow at L255, item underflow unterminated names, Mew glitch prerequisite); no extra fetching of mirrors |
| Followed links that loaded | glitchcity.wiki: Meta-map_script_activation, Trainer_escape_glitch, Trainer-fly_glitch, Old_man_glitch, Brock_through_walls, Arbitrary_code_execution (no Gen I detail on that page), Glitch_City_(Generation_I), Item_underflow and Walk_through_walls (disambiguation only) |
| Repo files | discoveries.py, novelty/__init__.py, legality.py, invariants/states.py (first 80 lines), explorer/memory.py (grep), docs/research/research_notes/RAM ROM tooling for game agents/pokemon_red_memory.md |

Gaps: no Bulbapedia list means rows 17, 19, 22, 24 and the generic "most relevant ~25" ranking rely on [K] knowledge; a
cleaner list would need Robert to paste the Bulbapedia page or allow another fetch route. Addresses in this doc are from
paraphrased pages (see section 0 caveat) and the repo notes already warn Data Crystal/wiki RAM maps contain errors.
