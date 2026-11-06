"""ROM check of effect-aware move scoring: crafts a battle in RAM on a headless emulator and prints move_scores
(status moves only when catching, never when a hit ends the fight, fixed / two-turn / multi-hit / drain adjustments).

    uv run python tools/score_check.py        # needs roms/Pokemon Red.gb, runs/checkpoints/rl_battle.state, kb/rom_tables.json
"""
import sys
sys.path.insert(0, "src")
from pathlib import Path
from pokeagent.emulator import PyBoyEmulator
from pokeagent.explorer import battle as B
from pokeagent.explorer.kb import ROM_KB
ids = {m["name"]: int(i) for i, m in ROM_KB["moves"].items()}
emu = PyBoyEmulator(Path("roms/Pokemon Red.gb"), headless=True)
emu.load_state(Path("runs/checkpoints/rl_battle.state"))
print("in battle flag", emu._pyboy.memory[0xD057], "enemy", ROM_KB["name_of_internal"].get(str(emu.read(0xCFE5))), "L", emu.read(0xCFF3))
M = emu._pyboy.memory
def w16(a, v): M[a] = v >> 8; M[a + 1] = v & 255
def setup(foe_hp, foe_max, foe_def=20):
    w16(0xCFE6, foe_hp); w16(0xCFF4, foe_max); M[0xCFF3] = 8; M[0xCFE9] = 0; M[0xCFEA] = 0; M[0xCFEB] = 0
    for a, v in ((0xCFF6, 15), (0xCFF8, foe_def), (0xCFFA, 15), (0xCFFC, 15)): w16(a, v)
    M[0xD022] = 10; w16(0xD015, 30); w16(0xD023, 30)
    for a, v in ((0xD025, 20), (0xD027, 20), (0xD029, 20), (0xD02B, 20)): w16(a, v)
    M[0xD019] = 0; M[0xD01A] = 0
def setmoves(names):
    for i, n in enumerate(names):
        emu._pyboy.memory[0xD01C + i] = ids[n]; emu._pyboy.memory[0xD02D + i] = 20
    for i in range(len(names), 4):
        emu._pyboy.memory[0xD01C + i] = 0
def show(label, names, catching, enemy_hp=None):
    setmoves(names); setup(enemy_hp, 80)
    sc = B.move_scores(emu, catching=catching)
    best = max(sc, key=lambda k: sc[k][0])
    print(f"{label} catching={catching} enemyHP={emu.read(0xCFE6)*256+emu.read(0xCFE7)}:")
    for k, v in sc.items(): print(f"   {k:14s} {v[0]:7.1f}  {v[1]}")
    print("   -> highest:", best)
mine = ["SLEEP POWDER", "GROWL", "TACKLE", "SEISMIC TOSS"]
show("fight, foe 80/80 HP (long fight)", mine, False, 80)
show("fight, enemy nearly dead", mine, False, enemy_hp=6)
show("catch attempt, foe 40/80", mine, True, 40)
show("misc effects, foe 80/80", ["SOLARBEAM", "HYPER BEAM", "DOUBLE KICK", "ABSORB"], False, 80)
emu.close()
