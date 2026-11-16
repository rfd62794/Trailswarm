# Generation I (Red/Blue) glitches and what they point to - PokeAgent research

Date 2026-11-15 (updated same day with Robert's pastes). Research only; nothing run, nothing edited outside this doc.
Evidence labels: **[F]** = from a page fetched this session, or text Robert pasted 2026-11-15 (Bulbapedia "List of glitches in
Generation I" = "Bulbapedia list"; Glitch City wiki 0xF8FF page; Reddit "Pokemon Red Glitch Ideas" = "Reddit ideas", community
pointers only, no mechanisms), cited. **[K]** = from general background knowledge of the
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
| 5 | Trainer-fly / Mew trick | After trainer escape, the next encounter species is chosen by the stale last-Special stat in memory | Escape trainer, fly away, return, encounter | Unexpected species at a route; instant encounter | No (needs Fly; Mew is a non-organic species) | H | [F] Trainer-fly_glitch page; [F] Reddit ideas, pasted by Robert 2026-11-15: lists the Mew glitch as a recommended early trick (pointer only) |
| 6 | Old Man glitch / Missingno encounter | Demo changes player name at $D887 (grass encounter rate address), restores only that byte; stale grass list from $D888 remains if no map reload; shore tiles read it; name characters select species/level | Old man demo in Viridian, then Fly to Cinnabar/Fuchsia, surf a left-facing shore tile | Encounter with glitch species ids (Missingno., 'M) and glitch trainers; bag slot 6 += 128 on Missingno. | Setup half yes (Viridian old man is early), trigger half no (Fly + Surf needed) | C (Missingno. effects, item mutation), X possible | [F] https://glitchcity.wiki/wiki/Old_man_glitch; [F] Reddit ideas: the player name decides which species/Missingno/glitch trainers the Old Man trick yields; the Glitch City Old Man Name Generator (namegen2) helps pick a name (pointer only; the agent cannot choose its name organically) |
| 7 | Brock through walls | Path copy at $CCF9 for unknown player coordinates talking to Pewter Youngster overflows into $CD3B (movement override flag); holding a button then walks through walls | Reach Youngster from the right, prime party-screen RAM setup (specific PP/level/moves), talk | Free movement through walls and NPCs | Needs Pewter Gym skip + exact party setup; not organic | S, C if combined with cloning | [F] https://glitchcity.wiki/wiki/Brock_through_walls; [F] Reddit ideas: also works with a Route 22 Nidoran-female and a L8 Bulbasaur 'and other things', Coin Case then Abra to Teleport back (pointer only). Route 22 is on route, so a Nidoran-female catch there is organic |
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
| 19 | Leveling past 100 | A mon obtained above L100 can be Rare-Candied up to L255; Rare Candy at L255 wraps level to 0 (one-byte overflow); a mon above L100 that levels from experience resets to L100 | Needs a >L100 mon (glitch/cheat) | Party level 0 or >100 (checked by party_stats) | No | C | [F] Bulbapedia list, pasted by Robert 2026-11-15; stat recalculation | Cheat or glitch to get L100+ | Party level 0 or >100 (checked by party_stats) | No | C | [K] Bulbapedia (search snippet in section 6); [F] Reddit ideas: 'Lv 100 before Brock' named as a known early trick (pointer only, no mechanism) |
| 20 | Safari Zone exit glitch | Wrong warp from Route 19/sea tiles into Safari zone map data | Surf at specific tiles | Glitch map or Safari map arrival | No (Surf, Safari later) | S | [F] Glitch_City page lists it as a trigger |
| 21 | Pokemon Center / PC SRAM glitch | Box switching writes to wrong SRAM bank, corrupting box data | Change box name/active box at a specific moment | Box data differs after reload | Not applicable (no PC use needed) | C | [F] mentioned in 0xF8FF and Trainer_escape pages as "SRAM glitch" |
| 22 | Select glitch (walk through walls trick) | Select press in a menu writes into a pointer | Press Select during specific menu | Walking through walls / odd menu | Unknown | S | [F] mentioned in Walk_through_walls page; [K] for mechanism |
| 23 | Cinnabar / step-count glitches | 500th step at Pokemon League -> "Glitch League" map; Cycling Road 500th step -> "Glitch Mountain" | Walk 500 steps | Glitch map id | No | S | [F] Glitch_City page |
| 24 | Instant Text trick (English R/B) | Entering the Cerulean City Bike Shop without a bike voucher and cancelling out of the shop menu never resets a text flag; all text then prints instantly. Buying the bike later resets it | Walk into the Cerulean bike shop, back out of the menu | Dialog/battle text appears with no delay; text-wait frame counts collapse | Yes, out of order: the agent does wander into the Cerulean shop; the voucher comes from Vermilion's Fan Club, so the flag likely stays set through the S.S. Anne leg | H (timing only) | [F] Bulbapedia list, pasted by Robert 2026-11-15 |
| 25 | Storage System healthy-party deposit | Every non-fainted mon can be deposited; blackout only after four steps in the same session (saving before 4 steps resets the count to 4 on reset in R/B). Entering a battle with only fainted mons blacks out at once | Deposit all healthy mons at a PC | Party of only fainted mons or empty party; blackout after 4 steps | Only if the agent uses the PC | S | [F] Bulbapedia list, pasted by Robert 2026-11-15 |
| 26 | Experience PC withdrawing softlock | Withdrawing an L1 Medium Slow mon softlocks; also Medium Fast at L255, Fast at L255, Slow at L237. Medium Slow at L245-255 returns as L59-125, Slow at L238-255 as L39-146, stats recalculated, HP may exceed max | Withdraw such a mon from a box | Input dead after withdraw; HP > max HP; level jump | Only via PC use with an L1 Medium Slow mon | S | [F] Bulbapedia list, pasted by Robert 2026-11-15 |
| 27 | Save corruption (power-off timing) | With no save file, saving and cutting power about 20 frames after A at the Yes/No box yields a 255-mon party next load; slots past the sixth are other memory read as mon data, and healing/swapping them edits memory | Power-off in that frame window | Party count 255, stats 65535, nickname of repeating 9s, slot species changing as you walk | Not reachable without emulator reset tricks. Checkpoint-safety note: never kill or reset the emulator mid-save | C | [F] Bulbapedia list, pasted by Robert 2026-11-15 |
| 28 | Hall of Fame corruption | If glitch mons have been seen on the save file, the sprite decompression buffer (kept in SRAM) overflows into save-data memory when a glitch mon's sprite is decompressed | Seeing a glitch mon (rows 6, 18) | Hall of Fame data garbled after reload | Only downstream of rows 6/18; not reachable | C | [F] Bulbapedia list, pasted by Robert 2026-11-15 |
| 29 | Save data carryover | New game saved over an old file, reset about 2 frames after the Yes/No box keeps the old party in the new file (too early corrupts the old file, too late overwrites) | Frame-exact reset during save | Old party/inventory after starting a new game | Not reachable organically | C | [F] Bulbapedia list, pasted by Robert 2026-11-15; Reddit ideas: the 'three starters glitch' pointer (no mechanism) |

Out of scope (one line each, per the Bulbapedia list pasted by Robert): JP Red/Green only - Empty Pokemon List, Full Box
glitch, Select glitches, Dokokashira door glitch, Second type glitch. Yellow only - Friendship item effect, Pikachu
off-screen / Super Glitch City, Pikachu-related ACEs. Blue only - Purple Jigglypuff intro oversight. Cross-gen - Time
Capsule glitches, Trade Evolution learnset oversight, Poke Transporter/Bank FF glitch. Cosmetic/audio - new-game Nidorino
cry, Menu glitch (hold A while saving), title-screen transparent pixels, Town Map cursor, Trade menu palette. Item
duplication, Pokemon merging, Rhydon glitch, cloning: main articles not pasted, so not catalogued.

Remaining [K] rows after the pastes: 17 (Cut glitch details) and 22 (Select glitch mechanism; the Bulbapedia list files
Select glitches under JP-only, so the English-version claim is unverified).

## 3. Viridian Forest in depth

### 3.1 The 0xF8FF glitch [F]

Sources: https://glitchcity.wiki/wiki/Viridian_Forest_0xF8FF_glitch (full page text pasted by Robert 2026-11-15, last edited
26 June 2026; documented by gifvex) and the Bulbapedia list.

- Core effect: arbitrary code execution (ACE) at 0xF8FF in Echo RAM, in the middle of the opponent trainer's Pokemon 3
  data, started by a special glitch meta-map script activation. It can run the Hall of Fame script; needs a specific
  Trainer ID, player name, stored Pokemon data, luck and a "good" play time down to the frame. Fastest English R/B
  completion other than the SRAM glitch; makes Brock through walls obsolete for that purpose.
- Full steps (as on the page): (1) name the player mMna.female-sign-tF; (2) manipulate Trainer ID 61896 (F1C8); a Charmander
  or Bulbasaur starter takes that ID; (3) continue to Viridian City, catch a Spearow on Route 22, nickname it "AAA";
  (4) deposit the starter in the PC; (5) death-warp on the last Bug Catcher of Viridian Forest (grass encounter inside his
  line of sight, then faint and black out; this leaves an instant encounter set up); (6) do not open Start or any text
  box, return to the Forest, fight that Bug Catcher (win or lose), then immediately fight him again (win or lose); this
  sets glitch meta-map script 06 (walking lag, interrupted A presses); (7) save outside the Forest to the south (play
  time including frames matters); (8) go to the first Bug Catcher you can fight, mash A until his text appears, win; if
  lucky, the Hall of Fame is entered.
- No-luck variant: reach ID 61896 by swapping quantity 241 into item 30 and HM05 into item 31 (expanded items pack), get an
  L6 Charmander via the Trainer escape glitch and trade it into the new game to deposit.
- Technical detail: instant trainer encounters run through meta-map scripts. Winning the trainer fight twice sets the script
  to the invalid value 06, which causes walking lag. The next trainer win then executes F8FF (Echo RAM, the mirror of wRAM,
  which holds enemy Pokemon 3's data). Copies of the player's name run as code, fall through to the play-time bytes (the
  frame count must be "safe"), then into stored Pokemon data; exactly one stored mon with the right id reaches the Hall of
  Fame script. Per TheZZAZZGlitch: the engine executes F8FF because of an invalid predefined command function 0xF4; it
  should have run F808 but ends at F8FF through a VRAM-inaccessibility detail.
- Emulator caveat: the page says it abuses CPU timing and may fail on VisualBoyAdvance, Pokemon Stadium 2 and possibly 3DS
  VC. PyBoy fidelity is unknown [H]; do not rely on either outcome.
- Related ACE family listed on the page (names only): 99 item stack glitch, Arbitrary Pokedex data, CC57 ACE, custom PCM /
  sprite / text boxes / tilesets, Facing direction ACE, Ingame save reload glitch, 8F bootstrap, Map script ACE, Quantity
  only ACE, Trainer escape glitch text box, Unexpected coordinate NPC interaction (Brock through walls).

Reachable by the agent organically vs not:
- Reachable: death-warp (wild encounter in a trainer's sight, faint) plus the double fight, which leaves meta-map script 06
  and the walking lag in Viridian Forest. Plausible by accident on the current route.
- Not reachable: the ACE payload. It needs a chosen player name, a chosen Trainer ID, a particular stored mon and a
  frame-tuned play time. The agent must not try, and nothing in this repo should engineer them.
- What the agent should detect: the Viridian Forest meta-map script byte out of its valid range, a trainer re-fighting
  immediately, and walking lag (steps taking long, input ignored). Log only.
- Save risk: the invalid script byte persists across leave/save/reset, so a checkpoint or leg state saved in that condition
  carries a corrupted world into curriculum runs. Guard in section 5.

### 3.2 The Reddit Viridian Forest report

Source 4 (reddit /r/PokemonGlitches/comments/1e05oe3/...) is still not available (not fetched, not pasted). I do not
know what that post describes and have not guessed. Source 2 ("glitch ideas", 13exxp4) is now pasted: it holds only
community pointers (Old Man name choice via namegen2, Mew glitch, Lv 100 before Brock, Brock through walls incl. with a
Route 22 Nidoran-female, three starters / save carryover), no mechanisms or addresses. Suggest Robert pastes the Forest post if it matters; the agent-side detectors in section 5 are mechanism-agnostic.

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

9. **Text-speed / dialog-timing flag (Instant Text trick).** Underlying: a text flag the Cerulean Bike Shop menu cancel never
   clears [F, behaviour]; the paste does not name the wRAM bit [H: possibly a no-text-delay bit among the 0xD730 flags;
   verify in pret/pokered symbols before hard-coding].
   - Effect on the agent: all dialog and battle text prints instantly, so A-press/wait-for-text frame budgets, "input ignored
     for N frames" detectors and timing-based replays shorten versus a normal run; runs with and without the flag are not
     comparable. Buying the bike (needs the Vermilion Fan Club voucher) resets it, so it will usually persist through the
     S.S. Anne leg.
   - Vary: visit the shop with and without the voucher; compare text-wait frame counts for the same dialog.
   - New = text-wait duration far below the normal run's for the same dialog.

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

Checkpoint/leg-state write guard (new, from Robert's paste):
- Never write a checkpoint or leg state while any meta-map script byte is outside its valid range for its map (for example
  the Viridian Forest byte left at 06 after the double fight). The invalid value persists through save/reset, so such a state
  poisons every run that loads it. On detection, log a discovery record under `runs/discoveries/` instead and keep the last
  clean checkpoint.
- Also refuse the write, or record it in the state's fingerprint, when the instant-text flag set by the Cerulean bike-shop
  trick differs from the normal value, so runs with different dialog timing stay comparable.
- Never kill or reset the emulator mid-save (row 27): finish or discard the save before any stop/restart.
- Every wRAM address cited in this doc (D5F0..D63A script range, D730, CD60, CD2D/CD2E, CD3B, D887, D35F/D360) comes from
  paraphrased or pasted wiki text and must be verified against pret/pokered symbols (`ram/wram.asm`) before hard-coding.

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
| 1. https://glitchcity.wiki/wiki/Viridian_Forest_0xF8FF_glitch | LOADED; full page text also pasted by Robert 2026-11-15 |
| 2. reddit r/PokemonGlitches 13exxp4 ("Pokemon Red Glitch Ideas") | Now available: pasted by Robert 2026-11-15 (community pointers only) |
| 3. web.archive.org glitchcity.info namegen2 | Still not available (not fetched, not pasted) |
| 4. reddit r/PokemonGlitches 1e05oe3 (Viridian Forest weird glitch) | Still not available |
| 5. Bulbapedia "List of glitches in Generation I" | Pasted by Robert 2026-11-15 (page last edited 18 May 2026); main articles for battle/overworld glitches, item duplication/underflow, merging, cloning and Rhydon not included |
| Followed links that loaded | glitchcity.wiki: Meta-map_script_activation, Trainer_escape_glitch, Trainer-fly_glitch, Old_man_glitch, Brock_through_walls, Arbitrary_code_execution (no Gen I detail on that page), Glitch_City_(Generation_I), Item_underflow and Walk_through_walls (disambiguation only) |
| Repo files | discoveries.py, novelty/__init__.py, legality.py, invariants/states.py (first 80 lines), explorer/memory.py (grep), docs/research/research_notes/RAM ROM tooling for game agents/pokemon_red_memory.md |

Gaps: rows 17 and 22 remain [K]. The namegen2 archive and the Viridian Forest Reddit post are still missing. Addresses in this
doc are from paraphrased or pasted wiki text and the repo notes already warn Data Crystal/wiki RAM maps contain errors;
verify against pret/pokered before hard-coding.
