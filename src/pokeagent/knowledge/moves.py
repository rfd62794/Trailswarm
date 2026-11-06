"""What every move DOES, keyed by the ROM's own effect byte (kb/rom_tables.json 'effect'), plus a one-line describe().

Chances follow Gen 1: LOW = 26/256 (~10%), HIGH = 77/256 (~30%). Effect ids are the ROM's (see the table in
docs/directives/Game_Knowledge_Directive.md); the move lists in each comment are the Red/Blue moves using it.
"""
from __future__ import annotations

from dataclasses import dataclass

LOW, HIGH = 0.1, 0.3


@dataclass(frozen=True)
class Effect:
    kind: str                 # damage | status | stat | setup | special
    target: str = "foe"       # self | foe
    stat: str = ""            # attack defense speed special accuracy evasion (stat moves)
    stages: int = 0           # stat stages (+ own, - foe)
    chance: float = 0.0       # side-effect chance of a damaging move (LOW / HIGH)
    status: str = ""          # poison burn paralyse sleep freeze confuse flinch leech-seed
    hits: float = 1.0         # expected hits per use
    charge: bool = False      # two-turn: charge first
    recharge: bool = False
    fixed: str = ""           # "level" | "half" | "20" | "40" - damage that ignores stats
    heal: float = 0.0         # fraction of damage (drain) or of max HP (recover) healed
    ohko: bool = False
    ends_wild: bool = False
    trap: bool = False
    recoil: bool = False
    faints: bool = False
    text: str = ""            # the one-line meaning


def _dmg(text="", **kw): return Effect("damage", text=text, **kw)
def _stat(stat, stages, who="foe", text=""): return Effect("stat" if who == "foe" else "setup", who, stat, stages, text=text)
def _side(stat, stages, chance): return Effect("damage", stat=stat, stages=stages, chance=chance, text=f"may lower the foe's {stat}")
def _st(status, **kw): return Effect("status", status=status, **kw)


EFFECTS: dict[int, Effect] = {
    0x00: _dmg("plain damage"),
    0x02: _dmg("damage + poison chance", chance=LOW, status="poison"), 0x21: _dmg("damage + poison chance", chance=HIGH, status="poison"),
    0x03: _dmg("damage, heals half of it", heal=0.5),
    0x04: _dmg("damage + burn chance", chance=LOW, status="burn"), 0x22: _dmg("damage + burn chance", chance=HIGH, status="burn"),
    0x05: _dmg("damage + freeze chance", chance=LOW, status="freeze"),
    0x06: _dmg("damage + paralyse chance", chance=LOW, status="paralyse"), 0x24: _dmg("damage + paralyse chance", chance=HIGH, status="paralyse"),
    0x07: _dmg("user faints", faints=True),
    0x08: _dmg("only hits a sleeping foe, heals half", heal=0.5),
    0x09: Effect("special", text="copies the foe's last move"), 0x53: Effect("special", text="random move"),
    0x52: Effect("special", text="copies a foe move"), 0x39: Effect("special", text="becomes the foe"),
    0x0A: _stat("attack", 1, "self"), 0x0B: _stat("defense", 1, "self"), 0x0D: _stat("special", 1, "self"), 0x0F: _stat("evasion", 1, "self"),
    0x32: _stat("attack", 2, "self"), 0x33: _stat("defense", 2, "self"), 0x34: _stat("speed", 2, "self"), 0x35: _stat("special", 2, "self"),
    0x12: _stat("attack", -1), 0x13: _stat("defense", -1), 0x14: _stat("speed", -1), 0x16: _stat("accuracy", -1), 0x3B: _stat("defense", -2),
    0x44: _side("attack", -1, LOW), 0x45: _side("defense", -1, LOW), 0x46: _side("speed", -1, LOW), 0x47: _side("special", -1, 0.33),
    0x10: _dmg("damage + money"), 0x11: _dmg("never misses"),
    0x18: Effect("special", "self", text="changes own type"), 0x19: Effect("special", text="removes all stat changes"),
    0x1A: Effect("special", "self", text="stores damage for 2-3 turns, then returns double"),
    0x1B: _dmg("2-3 turns, then confuses the user", hits=2.5),
    0x1C: Effect("special", text="ends a wild battle", ends_wild=True),
    0x1D: _dmg("2-5 hits", hits=3.0), 0x2C: _dmg("2 hits", hits=2.0), 0x4D: _dmg("2 hits + poison chance", hits=2.0, chance=HIGH, status="poison"),
    0x1F: _dmg("damage + flinch chance", chance=LOW, status="flinch"), 0x25: _dmg("damage + flinch chance", chance=HIGH, status="flinch"),
    0x20: _st("sleep", text="puts the foe to sleep"),
    0x26: _dmg("one-hit KO (fails on a faster foe)", ohko=True),
    0x27: _dmg("charges a turn, then hits", charge=True), 0x2B: _dmg("flies up a turn, then hits", charge=True),
    0x28: Effect("damage", fixed="half", text="takes half the foe's HP"),
    0x29: Effect("damage", fixed="level", text="fixed damage"),
    0x2A: _dmg("traps the foe 2-5 turns", trap=True),
    0x2D: _dmg("hurts the user if it misses", recoil=True),
    0x30: _dmg("recoil damage to the user", recoil=True),
    0x2E: Effect("setup", "self", text="stops stat drops"), 0x2F: Effect("setup", "self", text="raises crit rate"),
    0x40: Effect("setup", "self", text="halves special damage"), 0x41: Effect("setup", "self", text="halves physical damage"),
    0x4F: Effect("setup", "self", text="decoy costs 1/4 HP"),
    0x31: _st("confuse", text="confuses the foe"), 0x4C: _dmg("damage + confuse chance", chance=LOW, status="confuse"),
    0x38: Effect("setup", "self", heal=0.5, text="heals half of max HP"),
    0x42: _st("poison", text="poisons the foe"), 0x43: _st("paralyse", text="paralyses the foe"),
    0x50: _dmg("must recharge next turn", recharge=True),
    0x51: _dmg("damage grows while hit"), 0x54: _st("leech-seed", text="drains the foe each turn"),
    0x55: Effect("special", "self", text="does nothing"), 0x56: Effect("special", text="blocks one foe move"),
}

IMMUNE = {"THUNDER WAVE": "GROUND", "LEECH SEED": "GRASS", "POISONPOWDER": "POISON", "TOXIC": "POISON", "POISON GAS": "POISON",
          "DREAM EATER": "needs a sleeping foe"}
FIXED_DAMAGE = {"SONICBOOM": "20", "DRAGON RAGE": "40", "SEISMIC TOSS": "level", "NIGHT SHADE": "level", "PSYWAVE": "level"}


def effect_of(move: dict | None) -> Effect | None:
    return EFFECTS.get(int(move.get("effect", 0))) if move else None


def fixed_of(move: dict) -> str:
    """'level' / 'half' / '20' / '40' for fixed-damage moves, else ''."""
    e = effect_of(move)
    return FIXED_DAMAGE.get(move.get("name", ""), e.fixed) if e else ""


def describe(move: dict) -> str:
    """One line: 'THUNDER WAVE: ELECTRIC status - paralyses the foe; fails on GROUND'."""
    e = effect_of(move)
    name, typ = move.get("name", "?"), move.get("type", "?")
    if e is None:
        return f"{name}: {typ} (effect 0x{int(move.get('effect', 0)):02X} unknown)"
    power = int(move.get("power", 0))
    parts = [f"{name}: {typ} {e.kind}" + (f" power {power}" if power > 1 else "") + f" - {e.text or e.kind}"]
    if e.chance and e.status:
        parts.append(f"{round(e.chance * 100)}% {e.status}")
    if e.stat and e.stages:
        parts.append(f"{e.stat} {e.stages:+d}" + (f" ({round(e.chance * 100)}%)" if e.chance else ""))
    for flag in ("charge", "recharge", "recoil", "ohko", "faints", "trap"):
        if getattr(e, flag) and flag not in e.text:
            parts.append(flag)
    if fixed_of(move):
        parts.append({"level": "= user level", "half": "half the foe's HP", "20": "20 HP", "40": "40 HP"}[fixed_of(move)])
    imm = IMMUNE.get(name)
    if imm:
        parts.append(f"fails on {imm}" if imm.isupper() else imm)
    return "; ".join(parts)
