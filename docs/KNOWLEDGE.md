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
| 0xD719 | wLastBlackoutMap | map id of the town a blackout returns to (the last Pokecenter healed at); 5 = Vermilion | 2026-11-07: 2026-11-07: read from 229 save states with one headless emulator: all 49 leg states on Vermilion and ship maps read 5 (Vermilion) after the Pokecenter heal; ship checkpoints saved before the heal read 3 (Cerulean); values seen 0,1,2,3,5,15. Spec docs/superpowers/specs/2026-11-07-save-state-ledger.md. |
| 0xD361 / 0xD362 | wYCoord / wXCoord | player tile position | make_baseline (RIGHT changed X 4->5) |
| 0xD53A | wNumBoxItems | items stored in the PC | probe_pc: 1->0 |
| 0xD53B.. | wBoxItems | pairs (item id, qty), 0xFF terminator | probe_pc: D53B 14->FF |
| 0xD019 / 0xD01A | wBattleMonType1 / wBattleMonType2 | OUR battler's types in a fight (the STAB source; party slot 1's 0xD170/0xD171 is not the Pokemon in play) | from pokered wBattleMon layout, consistent with the moves at 0xD01C and PP at 0xD02D already in use; controller verifies on the ROM |

- **Position RAM is not safe to edit alone (ROM-observed 2026-11-07):** writing only wYCoord/wXCoord (0xD361/0xD362) leaves the map-view pointer (0xD35F..0xD360) and scroll unshifted, so the rendered map is one tile off from the coordinates; collision and warps use the new coordinates while the screen does not move (a RIGHT from the edited x did nothing where the original walked onto the next map). Any position edit must shift the view pointer too; `surgery.py` refuses position edits unless `unsafe_pos` is set.

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
  Mt Moon 1F has been entered. `gyarados` is a LADDER goal since 2026-11-07 (right after `nugget_bridge`): it settles
  without blocking when a GYARADOS is owned, when no Magikarp was ever owned, or once the stage's step cap is spent.
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

## Poke Mart, text speed, text prompt (ROM-verified 2026-11-05)

Probed headless in the Viridian Mart (map 42, 0x2A) from `oaks_parcel.state` (player at the clerk, (2,5)), with `shop.buy()` driving it.

- **The clerk only opens the shop after the parcel is delivered.** Before that every A repeats "Okay! Say hi to PROF.OAK for me!". Found by
  setting bits: **EVENT_OAK_GOT_PARCEL = 0xD74E bit 0** (the clerk handing it over is bit 1, event index 57). Setting it makes the menu appear.
- **Menu texts, in order** (screen text; `$` is the yen tile 0xF0): `BUY $3175 | SELL | QUIT` + "Hi there! May I help you?" (wTextBoxID 14, 3 items)
  -> BUY -> "Take your time." with the item list (wTextBoxID 13): `POKe BALL $200 | ANTIDOTE $100 | PARLYZ HEAL $200 | BURN HEAL $250 | CANCEL`
  -> item -> quantity box `x01 $200` (UP/DOWN +-1 and it wraps 99 <-> 1; LEFT/RIGHT do nothing) -> A -> "POKe BALL? That will be $1000. OK?" with `>YES / NO`
  -> A -> "Here you are! Thank you!" -> list again -> B -> "Is there anything else I can do?" with BUY/SELL/QUIT -> B -> "Thank you!" -> closed.
- The confirm text does not finish by itself: it waits for a press after "That will be" (the down-arrow prompt tile shows). The screen is "ready"
  when `>YES` is on it, not when a frame count has passed. The YES/NO box id is not constant, so `buy()` reads it from the screen.
- **Stock** is `wItemList` 0xCF7B = [count, item ids..., 0xFF]; Viridian: `04 0B 0F 0C` = POKe BALL, ANTIDOTE, PARLYZ HEAL, BURN HEAL. The cursor's list
  index is `wListScrollOffset` 0xCC36 + `wCurrentMenuItem` 0xCC26.
- **Money** is BCD at 0xD347..0xD349 (`ramworld.read_money`). **Result:** 5 POKe BALLs (item 0x04): money 3175 -> 2175, bag {0x46:1} -> {0x46:1, 0x04:5}.
  Also bought 12 ANTIDOTE (idx 1: 3175 -> 1975) and 95 ANTIDOTE (down-wrap path, 99900 -> 90400); 99 POKe BALLs with 3175 money is refused up front.
- **Text speed byte** `wOptions` 0xD355, low 3 bits: 1 FAST, 3 MEDIUM, 5 SLOW (a new game reads 3). START menu: `POKeMON, ITEM, <name>, SAVE, OPTION, EXIT`
  (even in the bedroom with no party, wMaxMenuItem 6), so OPTION is 4 DOWNs from the top. The OPTION screen: `TEXT SPEED / FAST >MEDIUM SLOW / BATTLE ANIMATION
  / ON OFF / BATTLE STYLE / SHIFT SET`, the cursor on the current speed; one LEFT sets 0xD355 to 0x01 at once, B leaves. Procedure `set_text_speed_fast`.
- **Text prompt**: the blinking down-arrow tile is **0xEE at screen row 16, column 18** (tilemap 0xC3A0 + 16*20 + 18), alternating with 0x7F; the last page of a
  text has no arrow and simply waits for A. `text_pace.prompt_waiting`.
- **Press cost**: `Presser` used to spend ~48 frames per A in a text box (hold 8 + settle 16 + 24 stillness). 3,000-step headless run from `baselines/bedroom.state`
  (`tools/explore_headless.py`): 2.21 -> 1.87 presses per text page, 119.5 -> 65.7 frames per page (text FAST + learned pace).

## False-positive goals (found 2026-11-06 from runs/milestones.json)
- **bike_shop / rival_ss_anne / hm01_cut at step 49-400 of Cerulean runs.** `bike_shop` was `{"map": [66]}`: the swarm walks through the shop door at Cerulean (13,26) without the Bike Voucher. The two unverified goals were then *inferred* from it, because `infer_unverified` marked every unverified goal before any reached goal. Fixes: `bike_shop` is now `map_now_with_item` (map 66 and the Bike Voucher, item 45, held); `infer_unverified` also requires the goal's `after` predecessor. (The old run code also wrote inferred goals to goal_frames/milestones; `press_goals.record_goals` skips unverified goals now.)
- **to_route9 at step 1710 of a Route 5 run.** The detector was right about the map: Cerulean east edge (39,17) leads to Route 9 (map 20) x=0, y=9, and the run (human-driven) entered it. The assumption was wrong, not the map id: Route 9's west end is open, and the Cut tree stands at x=4 (ahead tiles 64,65,80,81 at x=3). The goal means "past the tree", so it is now `map_past_x` (map 20 and wXCoord >= 5). Route 9 is also reachable from Route 10 (east end), which lands far past x=5 and is real progress.
- **Still unverified** (no flag/address checked against the ROM): HM01 item id (pokered HM_01 = 0xC4, candidate in campaign.json), HM05 (0xC8), any "beat the S.S. Anne rival" event flag, the Route 9 tree x=4 (read from one run's ahead_tiles, not from the map blocks). rival_ss_anne and hm01_cut stay `unverified`: they now fire only when a later goal is reached AND their `after` goal is reached.
- `tools/milestones_clean.py` lists milestone entries that cannot be real (report mode; `--apply` writes `runs/milestones.cleaned.json`, never the live file). Its other hits (buy_magikarp without to_route4 in-run, mt_moon floors in a run from `potion`) need a human look; they may be real order-skips, not detector bugs.

## Battle and level logs

XP and leveling data, written by `src/pokeagent/explorer/party_log.py`. Records only ever gain fields; old readers still parse.
Species are the game's internal ids (the same as `enemy_species`); `kb/rom_tables.json` `dex_of_internal` maps them to dex numbers.

**`runs/battles.jsonl`** (one line per battle, written by `behaviours/battle.py`). The original fields (`start`, `kind`
1 wild / 2 trainer, `you`, `enemy`, `enemy_species`, `end`, `won`, `run`, `map`, `presses`, `hp_end`, `fled`, `turns`)
are unchanged. New, snapshotted at battle start and at battle end (verified RAM: party struct exp + level):

| field | shape |
|---|---|
| `party_before`, `party_after` | one row per member: `[species, level, exp, hp, max_hp]` |
| `exp_gained` | per member, after minus before (aligned with `party_after`; a mon caught mid-fight is 0) |
| `level_ups` | `[{slot, species, from, to}]` |
| `evolved` | `[{slot, from, to}]` species ids |
| `moves_learned` | `[{slot, species, moves: [move ids]}]` for moves present after but not before |

Gen 1 evolves a mon after the battle returns to the overworld, so an evolution usually lands in `levels.jsonl`
(`cause: out_of_battle`, `evolved`) rather than in the battle record.
Atlas consumers: key on `map`, `kind`, `enemy` (species, level) and sum `exp_gained`; `sum(exp_gained)` is the exp for that fight
(lead only unless Exp. All or the fight was shared). Records written before this change have none of these fields; treat them as
missing, or use `runs/xp_estimates.jsonl`.

2026-11-07: the record also carries `outcome` (`"won" | "lost" | "fled" | "blackout"`), `battle_map` (the map the fight started
on), `end_map` (where the run stands after the battle: the respawn town for a blackout), `stage` (the training stage goal, e.g.
`"rival_ss_anne"`), `trainer` (`{"map","x","y","pic"}` of the pinned trainer NPC, or `null`), and `party_error` (only when the
party snapshot failed; `party_before`/`party_after` are now on every record). From this date `map` = `battle_map` and `fled`
means a real wild flee: records before it have `fled: true` on blackouts and the respawn town in `map`; readers that need
history should prefer `outcome` when present. `party_after` is read after the warp, so for a blackout it shows the healed
party (the HP at the moment of loss is the last `turns[-1].hp_you`). A ship fight won is the record
`{"outcome": "won", "stage": "rival_ss_anne", "trainer": {...}}`: that is the battle-won flag until a ROM-verified event flag
exists (`rival_ss_anne` stays `unverified`).

**`runs/explore-*/levels.jsonl`** (per run): `{step, frame, map, cause, party, [level_ups, evolved, moves_learned]}`, with `cause`
`start` (baseline), `battle_end` (every battle), or `out_of_battle` (any level/exp/species change outside a fight: rare candy, daycare,
evolution). `party` rows are as above.

**`runs/explore-*/meta.json` `xp_summary`** (at run exit, via `record_trainee`): `exp_gained`, `levels_gained_by_slot`, `battles`,
`battles_won`, `blackouts` (lost fights that were not flees), and step counts `steps_grinding` (lead level below
`ctx.train_need`, the training gate plan_goal sets and frontier's grass-seeking reads), `steps_travelling`, `steps_in_battle`.

**`runs/xp_estimates.jsonl`** (`uv run python tools/xp_backfill.py`, read-only on runs): per past battle, `exp_estimate` =
base_exp x enemy level / 7 (x1.5 trainer), 0 for a lost or fled fight, `"estimated": true`; `exp_measured` appears when the record
has real `exp_gained`. Needs the ROM-extracted `kb/rom_tables.json` (gitignored). Shared fights are over-estimated.
Caveats: `won` in battle records means we survived, so a fled wild fight counts as won (estimate over-counts it); a trainer battle
record holds only the last enemy mon, so a multi-mon trainer is under-counted. Prefer `exp_gained` when present.

- Trainer "Will <name> change POKeMON?" (YES/NO, after our kill, before their next mon): YES opens "Bring out which POKeMON?" with the cursor on slot 0 = the mon already fighting, and A there answers "<name> is already out!" (2026-11-07: 1,564 of 1,566 such loops in runs 11-06/11-07 began at this prompt). Always answer NO (dialog.YESNO_RULES). wPlayerMonNumber (0xCC2F) is read via intervene.screen.active_slot, which cross-checks it against wBattleMon species.

**Gen 1 money and Mart stock (measured 2026-11-07, `runs/battles.jsonl` records with `money_before`/`money_after`).** Of 406
money-bearing trainer records, 220 were wins and 218 of those paid (the other 2 paid 0); no run was paid twice by the same
map + lead-enemy pair (0 repeats), so trainer prizes are one-time. Wild fights do not pay (3 of 322 changed money, all other
causes). Blackouts could not be measured: the 8 lost-fight records in the file predate the money fields and 0 of the 713
money-bearing records is a blackout; the halving rule (`budget.blackout_cost`, pokered `ResetStatusAndHalveMoneyOnBlackout`) is
unverified in our data until `runs/economy.json` `blackouts.yen` fills. Mart stock read live (`stock_seen`): Pewter 56 and Cerulean
67 sell Potion (0x14); Viridian 42 and Vermilion 91 do not (Vermilion: Poke Ball, Super Potion, Ice Heal, Awakening, Parlyz Heal,
Repel); the battle and field item policies only ever use Potion, never Super Potion.

**HM01 Cut and the S.S. Anne captain (measured 2026-11-07, headless from `runs/checkpoints/ss_anne_captain.state`).** Item 0xC4 is HM01 on this
ROM: talking to the captain at (4,2) of map 0x65 from (4,3) facing UP ("Rub-rub...", "feel much better!", "BCN got HM01!") is the only bag change and adds
`(196, 1)`; the same states in `runs/legs/states` and `runs/checkpoints` that hold 0xC4 (6 of 329, all later than the cabin) all have both flags set, the 323
without it have neither. Event flags in `wEventFlags` (0xD747+): `0xD803` bit 1 flips when the back-rubbing starts (A press 14 of the dialog), bit 0 flips with
the item (press 27); the replay from the pre-talk state is deterministic and no other byte of 0xD747-0xD87B changes. They are pokered `EVENT_RUBBED_CAPTAINS_BACK`
(bit 1) and `EVENT_GOT_HM01` (bit 0). Entering the cabin sets neither, so "map 0x65 entered" was never a talked-to detector. kb/hm_compat.json: the Squirtle line
cannot learn CUT (Bulbasaur, Charmander and Oddish lines, Paras, Bellsprout, Sandshrew can), so a Wartortle + Magikarp party holds HM01 with nobody to teach.
Item-list rows read "x10" for a stack of ten, which `toss_guard` used to mistake for the TOSS quantity box (vetoing every A of the HM teach flow).


Route 24 beaten trainer (2026-11-07): the Bug Catcher at (11,31), first on Nugget Bridge, stands still after his fight. `choose_local`'s reason text starts "at (x,y) ...", not "frontier", so
`press_interact` did not treat the press as exploring and never temp-blocked his tile; memory_purge had also healed the learned wall, so 1,500 UP presses went into him. The press now carries
the deciding rule (`ctx.deciding_rule`), `blocked_cap` temp-blocks any tile+direction after 20 consecutive blocked presses (routing only, never saved), a person's tile is no longer a frontier side,
and `train_route` walks to Route 24's known grass and keeps frontier from leaving for Cerulean.

## Viewer (pull model, 2026-11-07)

- The poll thread pulls on a per-source cadence instead of polling everything every frame: snapshots
  at `SNAPSHOT_HZ_IDLE = 2` Hz for unfocused agents / `SNAPSHOT_HZ_FOCUS = 10` Hz for the focused one;
  world `/events` at `POLL_S_FOCUS = 0.2` s focused / `POLL_S_IDLE = 1.0` s for others; frames only for
  the on-screen set the views declare via `visible_frame_set` (grid cards `CARD_FRAME_HZ = 10`, the
  focus card `FOCUS_FRAME_HZ = 30`, Stadium slots `1/FRAME_S`). The render loop reads cached state
  only. An in-flight source is skipped, never queued; a dead agent (`DEAD_AFTER = 5` failed
  snapshots) retries at `DEAD_RETRY_S = 2` s and reads no frames. The old app.py `_Throttle` is gone:
  cadences live in `ViewerModel`/`WorldModel`, demand in `set_wants`/`set_focus` (written by the UI
  thread each tick).
- Frame slot header is layout v2 (`telemetry.LAYOUT = 2`, 32-byte header: v1 fields + u32 layout +
  u32 `SLOT_MAGIC` at offset 20 + f64 `reader_ts` at offset 24). Every shared-memory read stamps
  the reader heartbeat — the field Agent_Footprint item 2 reads to render frames only while
  watched; v1 slots are still read correctly (size is only a secondary guard — shared memory is
  page-rounded on the attaching side, so v2 needs the layout AND magic u32s, not pixel bytes that
  merely spell 2). An OLD viewer reading a NEW v2 publisher reads frames 16 bytes late: upgrade
  viewers before agents, or restart the World view after this merge.
- The Swarm page (View menu checkbox, top-level `SWARM_PAGE` window persisted by init_file) shows
  one row per agent/slot: live/lost/dead, current segment + curriculum grade (the scorecard's
  flag words, computed live via `segment_grades.grade_all`), next segment in the curriculum chain, steps/s + RSS from
  `runs/swarm/agent_stats.jsonl` when the Agent_Footprint sampler writes it (blank otherwise), the
  health state + reason, and the last goal landed. A row click focuses the agent. Rows assemble at
  1 Hz on the poll thread (`viewer/swarm_rows.py`, pure); `ui/swarm_page.py` renders them.
