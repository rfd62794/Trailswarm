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
    if ok:
        ctx.proc_done.add("text_speed_ok")
        if ctx.proc and ctx.proc.get("step0") is not None:
            ctx.setup_steps += ctx.step - ctx.proc["step0"]  # one-time setup: its presses do not count as run steps,
            ctx.step = ctx.proc["step0"]  # so the milestone step counts stay comparable with a run that skipped it
    ctx.log(f"[text speed: wOptions 0x{byte:02X} -> {'FAST (verified)' if ok else 'NOT fast'}]", "res")
    return ok


MAX_ATTEMPTS = 2  # the procedure runs once and is retried once if the option byte is still not FAST


def seed_text_speed(ctx) -> None:
    """Queue ``set_text_speed_fast`` first thing, at most MAX_ATTEMPTS times per run; once the byte reads FAST that is cached in
    ``ctx.proc_done`` (run-local: a saved maps.json must never claim a fresh game is already fast). A new attempt starts only
    when the previous one is finished (not queued, not running)."""
    if "text_speed_ok" in ctx.proc_done or "set_text_speed_fast" in ctx.proc_due:
        return
    if ctx.proc is not None and ctx.proc.get("name") == "set_text_speed_fast":
        return
    if ctx.emu.read(OPTIONS_ADDR) & SPEED_MASK == FAST:
        ctx.proc_done.add("text_speed_ok")
        return
    tries = sum(1 for k in ctx.proc_done if str(k).startswith("text_speed_try"))
    if tries >= MAX_ATTEMPTS:
        return
    ctx.proc_done.add(f"text_speed_try{tries + 1}")
    ctx.proc_due.insert(0, "set_text_speed_fast")
