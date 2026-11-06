# Ground truth about Pokemon Red (UE) as seen through PokeAgent

For tests and humans. NOT fed to the agent; the agent is supposed to learn these itself. Every line here
was observed on the real ROM on the date given, with the tool named. Directives extend this file; they do
not re-create it.

## RAM (work RAM, 0xC000-0xDFFF)

| addr | name (pret/pokered) | meaning | evidence |
|---|---|---|---|
| 0xC3A0..0xC507 | wTileMap | the visible 20x18 screen tiles, row-major | 2026-11-02 START menu text decoded from it |
| 0xD31D | wNumBagItems | items in the bag | 2026-11-02 probe_pc: 0->1 after withdrawing the POTION |
| 0xD31E.. | wBagItems | pairs (item id, qty), 0xFF terminator | probe_pc: D31E FF->14 (POTION), D31F 00->01, D320 00->FF |
| 0xD347 (3 bytes) | wPlayerMoney | BCD, 3000 at a new game | make_baseline |
| 0xD35E | wCurMap | 0x26 = REDS_HOUSE_2F, 0x25 = REDS_HOUSE_1F, 0x00 = PALLET_TOWN | make_baseline + explore_demo warps |
| 0xD361 / 0xD362 | wYCoord / wXCoord | player tile position | make_baseline (RIGHT changed X 4->5) |
| 0xD53A | wNumBoxItems | items stored in the PC | probe_pc: 1->0 |
| 0xD53B.. | wBoxItems | pairs (item id, qty), 0xFF terminator | probe_pc: D53B 14->FF |
| 0xD019 / 0xD01A | wBattleMonType1 / wBattleMonType2 | OUR battler's types in a fight (the STAB source; party slot 1's 0xD170/0xD171 is not the Pokemon in play) | from pokered wBattleMon layout, consistent with the moves at 0xD01C and PP at 0xD02D already in use; controller verifies on the ROM |

Item id 0x14 = POTION (the one item in the PC at a new game). Still UNVERIFIED: 0xD163 party count
(the START menu showed POKéMON while it read 0), 0xD356 badges, 0xD057 in-battle.

## Screen text

- Charmap: 0x7F space, 0x80-0x99 A-Z, 0xA0-0xB9 a-z, 0xF6-0xFF 0-9, 0xBA é, 0xED the ▶ menu cursor,
  0x50 string end. Verified by decoding "POKéMON ITEM SAVE OPTION EXIT" and "BCN turned on the PC."
- Frame (text box / menu) border tiles: 0x79 top-left, 0x7A top/bottom edge, 0x7B top-right, 0x7C left/right
  edge, 0x7D bottom-left, 0x7E bottom-right. Detect a frame as the two bytes 0x79 0x7A, never a lone 0x79.
- A dialog box is rows 12-17 full width; the START menu is a frame on the right, rows 0-13; the PC menu is a
  frame on the left with the cursor on WITHDRAW ITEM.

## World

- New game: the player stands in the upstairs bedroom (map 0x26). The baseline state `baselines/bedroom.state`
  is at (4,6). The player's name in that state is "BCN" (the intro masher typed it).
- Upstairs staircase: (7,2) pressing UP -> map 0x25 (Robert: "upper-right corner"; explore_demo confirmed).
- Downstairs front door: (3,7) pressing DOWN -> map 0x00 Pallet Town (Robert; explore_demo confirmed).
- The PC: stand at (0,2) upstairs facing UP, press A -> "BCN turned on the PC." Menu: WITHDRAW ITEM /
  DEPOSIT ITEM / TOSS ITEM / LOG OFF. WITHDRAW ITEM -> list "POTION x1 / CANCEL" -> A -> "How many?" -> A.
  Sequence that worked: A (turn on), A (WITHDRAW), A (POTION), A (quantity), A... then B until closed.

## Viridian City (found by headless swarm agents, 2026-11-03)

- Viridian City is map 0x01 (reached from Route 1 0x0C). Map 0x2A (42) is the Poke Mart: stand at (2,5) in front of the
  clerk and press A: "BCN got OAK PARCEL!" adds item 0x46 (bag count 0xD31D goes up). Door tile from Viridian: (29,20) DOWN
  warps out; the mart warp lands inside at (3,7) facing the counter. VERIFIED in two agent runs.
- A free POTION lies on the ground in Viridian at (13,4): "BCN found POTION!" (VERIFIED).
- Map 0x2B (43) is a small house with one NPC ("Whew! I..."); map 0x2C (44) is a house where a child talks about nicknames.
- Map 0x21 (33) is Route 22, west of Viridian (its east edge warps to Viridian (0,15)/(0,16)).
- Viridian has one-way ledges (a press that moves two tiles); the plaza around (18-19, 26-28) loops if ledges are treated as two-way.

## East of Pewter: Mt Moon to the S.S. Ticket (ROM-verified 2026-11-05)

Verified with `uv run python tools/rom_maps.py <ids>`: it reads MapHeaderPointers (0x01AE, 248 entries) and MapHeaderBanks
(0xC23D), both located by search and cross-checked (pointer 0 = 10x9 Pallet, pointer 1 = 20x18 Viridian; 224/248 entries decode
to sane headers), then follows each header's connections and warp list. Warps are (x, y) tiles; the player lands ON the warp tile.

| id | what | how verified |
|---|---|---|
| 0x0E / 0x0F | Route 3 (35x9), Route 4 (45x9) | Route 3 connects N to 0x0F and W to Pewter 0x02; Route 4 connects S to 0x0E and E to Cerulean 0x03 |
| 0x3B | Mt Moon 1F | Route 4 warp (18,5) -> 0x3B; 1F exits at (14,35),(15,35) back to that warp; cavern tileset 17, 20x18 |
| 0x3C | Mt Moon B1F | Route 4 warp (24,5) is B1F warp 7 (27,3); 1F stairs (5,5),(17,11),(25,15) lead to it; 14x14 |
| 0x3D | Mt Moon B2F | B1F warps lead to it; four warps back up to B1F; 20x18 |
| x >= 24 on 0x0F | east of the cave exit | the exit warp lands at Route 4 (24,5); west side holds entrance (18,5) and the Pokecenter door (11,5) |
| 0x44 | Mt Moon (Route 4) Pokecenter | Route 4 warp (11,5) -> 0x44; Pokecenter tileset 6, 7x4; confirmed live 2026-11-05: its NPC sells MAGIKARP ("for just 500") |
| 0x03 | Cerulean City | N conn 0x23, S conn 0x10 (Route 5), W conn 0x0F, E conn 0x14 (Route 9) |
| 0x40 | Cerulean Pokecenter | Cerulean warp 2 (19,17) -> 0x40, whose exit points back at warp index 2; tileset 6, 7x4 |
| 0x41 | Cerulean Gym | Cerulean warp 3 (30,19) -> 0x41, exit points back at index 3; gym tileset 7, 5x7, same shape as Pewter Gym 0x36 |
| 0x23 | Route 24 | Cerulean's N connection; its S conn is 0x03, E conn is 0x24; no warps |
| 0x24 | Route 25 | Route 24's E connection; one warp (45,3) -> 0x58 |
| 0x58 | Bill's house | the only warp of Route 25; 4x4 house, exit back to warp 0 (name from pret's map list; position confirms it) |
| 0xD356 bit1 | CASCADEBADGE | `21 56 D3 CB CE` (ld hl,wObtainedBadges; set 1,[hl]) occurs once, at ROM 0x5C736 (bank 17, the gym-leader bank); the Brock twin `CB C6` is at 0x5C408 |
| item 0x3F | S.S.TICKET | item-name table starts at 0x472B ("MASTER BALL" = id 1); entry 0x3F decodes "S.S.TICKET"; entries 0x14 "POTION" and 0x46 "OAK PARCEL" match the ids already in use |

Not verified on the ROM: the name "Bill's house" for 0x58 (it is the only warp of Route 25, a 4x4 house; the name is from pret's map list),
and the in-game route through Mt Moon (left to exploration). Seen live 2026-11-05 (seed 7, beat_brock state): a level-8 Ivysaur team
blacks out in Mt Moon B1F/B2F trainers and respawns in the Pewter Pokecenter.

## Full RAM map (2026-11-05)

- `src/pokeagent/data/ram_map.json`: every WRAM/HRAM label from pret/pokered `pokered.sym` (symbols branch), generated by
  `tools/build_ram_map.py <pokered.sym> --wram wram.asm`; corrections in `data/ram_overrides.json`. pret/pokered has no
  LICENSE file (GitHub reports none), so the raw `.sym` is NOT committed; only the derived JSON of label names and addresses is.
- `tools/verify_ram.py` proves addresses on the ROM against checkpoints and writes `verified` + `evidence` back (never downgrades).
  Note `first_pokemon.state` is captured mid-give: the party struct is still zero until the text is dismissed (the verifier presses B).
- `tools/ram_query.py <name|0xADDR|region> [--state f]` looks labels up, optionally reading live values.
- Decoders: `ramstructs.py` (party/battle mons, item lists), `ramworld.py` (badges, dex, map header, menu, event flags);
  stats awareness in `explorer/stats.py` and `explorer/stat_records.py` (DVs, stat exp, formula; catch keep-best and per-map stat-exp are report-only).
- Gen 1 quirk: party stats are only recomputed at level-up, so they ignore stat exp earned since.

## Magikarp: buy, reorder, switch-train (ROM-verified headless 2026-11-05)

- Internal species ids (kb `name_of_internal`): 133 = MAGIKARP, 22 = GYARADOS. Party count 0xD163, species list 0xD164, mon structs 0xD16B stride 44.
  A bought Magikarp arrives at level 5 with 17-18 HP. Money is BCD at 0xD347 (500 = 500 off the total).
- The salesman is a wanderer in the Mt Moon Pokemon Center (0x44), pic id 10, pacing the row y=6 between x=8 and x=11. Stand on y=5 above him
  facing DOWN and press A. His pitch runs ~17 presses before the YES/NO appears (the old "menu open for 12 presses -> B" guard answered NO for us
  until `AdvanceDialog` exempted the MAGIKARP offer). Texts: "MAN Hello, there! Have I got a deal just for you! I'll let you have a swell MAGIKARP
  for just 500! What do you say?" -> YES/NO box (with the money window "3553" above it) -> "BCN got MAGIKARP!" -> "Do you want to give a nickname to
  MAGIKARP?" (YES/NO, we answer NO). Saying NO: "No? I only | doing this as a favor to you!". Afterwards he says "Well, I don't give refunds!".
- Party screens (all unframed full-screen lists, so `frame_lines` is blind to them; `explorer/party_menu.py` decodes the whole tile map):
  START menu is a frame "POKeDEX / POKeMON / ITEM / <name> / SAVE / OPTION / EXIT" (cursor remembered between opens; wCurrentMenuItem 0xCC26 = row);
  A on POKeMON opens the list with the prompt "Choose a POKeMON."; wCurrentMenuItem is the party slot under the cursor; A on a member opens
  "STATS / SWITCH / CANCEL" (outside a fight; STATS is row 0, SWITCH row 1); A on SWITCH prints "Move POKeMON where?" and the cursor starts on the
  chosen member; moving it to another slot and pressing A swaps the two (RAM order changes at once); B closes the list, B again the START menu.
- In a fight: battle menu is a frame ">FIGHT PKMN / ITEM RUN" (PKMN is RIGHT of FIGHT); A on PKMN opens the same "Choose a POKeMON." list; A on a
  member opens ">SWITCH / STATS / CANCEL" (SWITCH is the FIRST row in a fight); A on SWITCH prints "MAGIKARP enough! Come back!" then "Go! WARTORTLE!".
  Gen 1 does not reorder the party on an in-battle switch. The enemy then acts (turn one is spent). Seen: "MAGIKARP gained 30 EXP. Points!" and
  "WARTORTLE gained 30 EXP. Points!" after the Zubat fainted - the switched-out Magikarp shares the experience.
- No healthy member to send in (all fainted or under 25% HP): a Magikarp only knows SPLASH, so a wild fight is left with RUN (rule
  `switch_train_run`); a trainer fight cannot be left and carries on. Headless runs from to_route3.state (seeds 7/11/23, 4,000 steps): Magikarp
  reached L6-L7 and shared 4-9 battles; level 20 needs a few hundred shared fights (about 30 EXP each at these levels), so it is far off.
- Engine notes: the buy_magikarp goal is settled (so the ladder never blocks) when a MAGIKARP/GYARADOS is owned, money < 500, the party is full, or
  Mt Moon 1F has been entered. `gyarados` is in `SIDE_GOALS` (reported by check_goals and tools/status.py, never the planner's next goal).
  With a Magikarp in the party, `party_hp`, the training level and the BattleView read the fighter (the battle's active mon, else the strongest
  non-Magikarp), not party slot 0.

## Game knowledge drain (ROM-verified 2026-11-05)

`uv run python tools/rom_tables.py` writes `kb/rom_tables.json` (gitignored) ONLY if every check below passes. Offsets are from
pret/pokered `pokered.sym` (symbols branch), file offset = bank*0x4000 + (addr - 0x4000). Query with `tools/knowledge.py`
(moves / catch / train / trainer / map / ready) and `pokeagent.knowledge.*`.

| table | symbol (bank:addr) | layout | check that passed |
|---|---|---|---|
| species base data | BaseStats 0e:43de | 28 B per dex no.; level-1 moves @15..18, growth rate @19 | CHARMANDER HP 39 FIRE; PIDGEY NORMAL/FLYING; GEODUDE and ONIX ROCK/GROUND |
| learnsets + evolutions | EvosMovesPointerTable 0e:705c | 190 pointers by INTERNAL id; evolutions (1 level / 2 item+min level / 3 trade, species), 0, then (level, move) pairs, 0 | CHARMANDER EMBER at 9, evolves at 16; BULBASAUR VINE WHIP at 13 |
| wild encounters | WildDataPointers 03:4eeb | pointer per MAP id; grass rate, 10 x (level, species), water rate, 10 x (level, species) | Route 1 (0x0C): PIDGEY and RATTATA, levels 2-5 |
| trainer parties | TrainerDataPointers 0e:5d3b, TrainerNames 0e:59ff | 47 pointers; a class's parties back to back: `level, species..., 0` or `0xFF, (level, species)..., 0`; class ends at the next higher pointer (TrainerAI 0e:652e ends the last) | BROCK = GEODUDE L12, ONIX L14; MISTY = STARYU L18, STARMIE L21 |
| trainer placement | map object data (rom_maps.py) | object text id bit 6 set -> 2 extra bytes (200 + class, party no.) | Pewter Gym 0x36 holds BROCK party 1 and a JR.TRAINER(M); Mt Moon 1F/B2F list their trainers |
| items | ItemPrices 01:4608, ItemNames 01:472b | 3-byte BCD price; names 0x50-terminated, item ids 1..83 | POTION 300 (id 0x14) |

Mt Moon (0x3B/0x3C/0x3D) trainers, from the ROM: 1F has HIKER, YOUNGSTER, 2 LASS, SUPER NERD, 2 BUG CATCHER; B1F none; B2F SUPER NERD and 4 ROCKET.
Move meaning: `knowledge/moves.py` maps each ROM effect byte to an `Effect`; every effect id in the drained moves is covered (test-guarded).
Party readiness (`knowledge/readiness.py`) replaces the fixed training-level table: it simulates our party (RAM stats, known moves) against the boss
party (ROM base stats, DV 8, learnset moves) and `TRAIN_LEVEL_BY_GOAL` is only the fallback when the data or the party is missing.
