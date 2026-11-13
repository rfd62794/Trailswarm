"""Named constants for every WRAM symbol the party/battle views read.

One constant per symbol: modules outside this file never spell a hex address for
these symbols again, so a reader of party_hp or fighter can trust the memory it
names. Layout notes are the working notes the decoders were written against."""

# party block (wPartyMons): count byte, species list, then six 44-byte structs
PARTY_COUNT = 0xD163          # wPartyCount
PARTY_SPECIES = 0xD164        # wPartySpecies: list of species bytes (0-terminated)
PARTY_MON1 = 0xD16B           # wPartyMon1: first 44-byte party struct
PARTY_MON1_HP = 0xD16C        # wPartyMon1HP (2 bytes, big-endian)
PARTY_MON1_MOVES = 0xD173     # wPartyMon1Moves: 4 move ids
PARTY_MON1_LEVEL = 0xD18C     # wPartyMon1Level
PARTY_MON1_MAX_HP = 0xD18D    # wPartyMon1MaxHP (2 bytes, big-endian)
PARTY_MON_SIZE = 44           # sizeof(party_struct)
MAX_PARTY = 6
PARTY_MON_OT = 0xD273         # wPartyMonOT: 11 chars per slot
PARTY_MON_NICKS = 0xD2B5      # wPartyMonNicks: 11 bytes per slot
NAME_SIZE = 11

# battle structs (wBattleMon / wEnemyMon), 29 bytes each
BATTLE_MON = 0xD014           # wBattleMon (the player's active mon)
ENEMY_MON = 0xCFE5            # wEnemyMon
BATTLE_STRUCT_SIZE = 29
BATTLE_MON_HP = 0xD015        # wBattleMonHP (2 bytes, big-endian)
BATTLE_MON_MOVES = 0xD01C     # wBattleMonMoves: 4 move ids
BATTLE_MON_LEVEL = 0xD022     # wBattleMonLevel
BATTLE_MON_MAX_HP = 0xD023    # wBattleMonMaxHP (2 bytes, big-endian)
BATTLE_MON_PP = 0xD02D        # wBattleMonPP: 4 bytes, move PP
ENEMY_MON_PP = 0xCFFE         # wEnemyMonPP

# battle state / flags
IS_IN_BATTLE = 0xD057         # wIsInBattle: 0 overworld, 1 wild, 2 trainer
CUR_OPPONENT = 0xD059         # wCurOpponent: 0 none, species id (wild) or 200 + trainer class; set while the battle intro still fades
PLAYER_MON_NUMBER = 0xCC2F    # wPlayerMonNumber: party slot currently out
ENEMY_MON_PARTY_POS = 0xCFE8  # wEnemyMonPartyPos: enemy party slot out (trainer fights)
PARTY_GAIN_EXP_FLAGS = 0xD058 # wPartyGainExpFlags: bit i = party slot i fought this enemy
PARTY_FOUGHT_ENEMY_FLAGS = 0xCCF5  # wPartyFoughtCurrentEnemyFlags: bit i = slot i fought this enemy

# enemy trainer's party (wEnemyPartyCount .. wEnemyMons): stale outside trainer fights
ENEMY_PARTY_COUNT = 0xD89C    # wEnemyPartyCount
ENEMY_PARTY_SPECIES = 0xD89D  # wEnemyPartySpecies
ENEMY_MONS = 0xD8A4           # wEnemyMons: 44-byte structs
ENEMY_MON_SIZE = 44

# Pokemon storage box (current box in RAM)
BOX_COUNT_ADDR = 0xDA80       # wBoxCount
BOX_SPECIES = 0xDA81          # wBoxSpecies
BOX_MONS = 0xDA96             # wBoxMonN
BOX_MON_SIZE = 33             # box_struct (no stat block)
BOX_MON_OT = 0xDD2A           # wBoxMonOT
BOX_MON_NICKS = 0xDE06        # wBoxMonNicks

# misc state
MENU_ITEM = 0xCC26            # wCurrentMenuItem
TRAINER_CLASS = 0xD031        # wTrainerClass
TRAINER_NO = 0xD05D           # wTrainerNo
SPECIES_MAGIKARP = 133        # internal species id used by the trainee rule
