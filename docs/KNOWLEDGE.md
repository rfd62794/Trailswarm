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
