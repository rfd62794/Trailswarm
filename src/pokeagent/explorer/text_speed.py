"""text_speed: the one-time START -> OPTION -> TEXT SPEED FAST procedure, verified on the option byte.

wOptions (0xD355, pret) low 3 bits are the text speed: 1 FAST, 3 MEDIUM, 5 SLOW (ROM-verified 2026-11-05: a new game reads 3,
LEFT on the TEXT SPEED row of the OPTION screen changes it to 1 at once). The START menu lists
POKeMON, ITEM, <name>, SAVE, OPTION, EXIT even in the bedroom with no party (wMaxMenuItem 6), so OPTION is always the 5th line."""
from __future__ import annotations

OPTIONS_ADDR, SPEED_MASK, FAST = 0xD355, 7, 1
OPTION_ROW = 4  # POKeMON, ITEM, <name>, SAVE, OPTION, EXIT -> OPTION is index 4


def text_speed_steps(ctx) -> list:
    """Button steps with the screen text each must produce (see procedures.py for the format)."""
    downs = OPTION_ROW  # the START menu has 6 lines from the first moment (POKeMON is listed even before a party; verified)
    return ([("START", r"OPTION")] + [("DOWN", None)] * (downs - 1) + [("DOWN", r">OPTION")]
            + [("A", r"TEXT SPEED"), ("LEFT", r">FAST"), ("B", r"OPTION"), ("B", None), ("CHECK_OPT", None)])


def check_text_speed(ctx) -> bool:
    """Verify the option byte after the procedure and record it in maps.json (``text_speed``)."""
    byte = ctx.emu.read(OPTIONS_ADDR)
    ok = byte & SPEED_MASK == FAST
    ctx.mem.data["text_speed"] = {"byte": byte, "fast": ok}
    ctx.log(f"[text speed: wOptions 0x{byte:02X} -> {'FAST (verified)' if ok else 'NOT fast'}]", "res")
    return ok
