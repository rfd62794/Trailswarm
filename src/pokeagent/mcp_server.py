"""MCP server: the emulator as tools, so a Claude/Devin session plays directly.

A stdio MCP server owns stdout, so nothing on this path may ``print()`` to
stdout - errors go to stderr only. Every tool runs through the
:class:`EmulatorThread`, so the emulator (and its SDL2 window) is only ever
touched from its own thread.
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Image, MCPServer
from PIL import Image as PILImage

from pokeagent.emulator import Button, Emulator, PyBoyEmulator
from pokeagent.emu_thread import EmulatorThread
from pokeagent.explorer import Explorer
from pokeagent.ram import RAM_MAP, read_state

WRAM_START, WRAM_LEN = 0xC000, 0x2000  # WRAM 0xC000-0xDFFF
RUNS_DIR = Path("runs/mcp")
MAPS_PATH = Path("runs/maps.json")
SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")
NAME_AT = {addr: name for name, addr in RAM_MAP.items()}
BOOT_FRAMES = 60


def _state_dict(emu: Emulator) -> dict[str, Any]:
    s = read_state(emu)
    return {**s.as_dict(), "summary": s.summary()}


def _safe(name: str) -> str:
    return SAFE_NAME.sub("_", name).strip("_") or "state"


class _Tools:
    """Tool implementations over one EmulatorThread; build_server registers these."""

    def __init__(
        self,
        thread: EmulatorThread,
        runs_dir: Path = RUNS_DIR,
        maps_path: Path = MAPS_PATH,
    ) -> None:
        self.thread = thread
        self.runs_dir = Path(runs_dir)
        self.snapshots: dict[str, bytes] = {}
        self.explorer = Explorer(maps_path)

    def press(
        self, button: str, repeat: int = 1, hold_frames: int = 8, settle_frames: int = 16
    ) -> dict[str, Any]:
        """Press a Game Boy button (UP DOWN LEFT RIGHT A B START SELECT NONE), then return the new game state."""
        name = button.upper()
        if name not in Button.__members__:
            return {"error": f"unknown button {button!r}; use {sorted(Button.__members__)}"}
        b = Button[name]

        def go(emu: Emulator) -> dict[str, Any]:
            for _ in range(max(1, repeat)):
                emu.press(b, hold_frames, settle_frames)
            return _state_dict(emu)

        return self.thread.call(go)

    def wait(self, frames: int = 60) -> dict[str, Any]:
        """Let the game run for `frames` frames, then return the new state."""
        def go(emu: Emulator) -> dict[str, Any]:
            emu.tick(max(0, frames))
            return _state_dict(emu)

        return self.thread.call(go)

    def state(self) -> dict[str, Any]:
        """Current game state: map, position, party, badges, battle flag, money."""
        return self.thread.call(_state_dict)

    def screenshot(self, scale: int = 1) -> Image:
        """Current screen as a PNG (160x144, nearest-neighbour scaled by `scale`)."""
        def go(emu: Emulator) -> bytes:
            img = emu.screenshot()
            if scale > 1:
                img = img.resize(
                    (img.width * scale, img.height * scale), PILImage.NEAREST
                )
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

        return Image(data=self.thread.call(go), format="png")

    def peek(self, addr: int, length: int = 1) -> dict[str, Any]:
        """Read `length` bytes of RAM at `addr` (max 4096)."""
        if not 1 <= length <= 4096:
            return {"error": f"length must be 1..4096, got {length}"}
        data = self.thread.call(lambda emu: emu.read_range(addr, length))
        return {"addr": f"0x{addr:04X}", "hex": data.hex(), "bytes": list(data)}

    def snapshot(self, name: str) -> dict[str, Any]:
        """Store WRAM 0xC000-0xDFFF under `name` in memory, for later diff()."""
        self.snapshots[name] = self.thread.call(
            lambda emu: emu.read_range(WRAM_START, WRAM_LEN)
        )
        return {"name": name, "bytes": len(self.snapshots[name])}

    def diff(self, a: str, b: str, limit: int = 200) -> list[dict[str, Any]] | dict[str, Any]:
        """Bytes that changed between snapshots `a` and `b`, with RAM_MAP names where known."""
        missing = [n for n in (a, b) if n not in self.snapshots]
        if missing:
            return {"error": f"unknown snapshot(s) {missing}; take one with snapshot()"}
        out = []
        for i, (old, new) in enumerate(zip(self.snapshots[a], self.snapshots[b])):
            if old == new:
                continue
            entry = {"addr": f"0x{WRAM_START + i:04X}", "old": old, "new": new}
            if WRAM_START + i in NAME_AT:
                entry["name"] = NAME_AT[WRAM_START + i]
            out.append(entry)
            if len(out) >= limit:
                break
        return out

    def save_state(self, name: str) -> dict[str, Any]:
        """Write an emulator save-state to runs/mcp/<name>.state (name sanitised)."""
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        path = self.runs_dir / f"{_safe(name)}.state"
        self.thread.call(lambda emu: emu.save_state(path))
        return {"path": str(path)}

    def load_state(self, name_or_path: str) -> dict[str, Any]:
        """Load a save-state: runs/mcp/<name>.state, or an existing path under the repo."""
        candidate = self.runs_dir / f"{_safe(name_or_path)}.state"
        if candidate.is_file():
            path = candidate
        else:
            path = Path(name_or_path)
            if not path.is_file():
                return {
                    "error": f"no saved state {name_or_path!r} in {self.runs_dir} or as a path"
                }
            try:
                path.resolve().relative_to(Path.cwd().resolve())
            except ValueError:
                return {"error": f"refusing to load a state outside the repo: {name_or_path}"}
        self.thread.call(lambda emu: emu.load_state(path))
        return {"path": str(path)}

    def pause(self) -> dict[str, Any]:
        """Stop idle ticking; the game only advances inside tool calls."""
        self.thread.paused = True
        return {"paused": True}

    def resume(self) -> dict[str, Any]:
        """Resume idle ticking."""
        self.thread.paused = False
        return {"paused": False}

    def note(self, text: str) -> dict[str, Any]:
        """Append a line to runs/mcp/notes.txt (the agent's memory); returns the last 20 lines."""
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        path = self.runs_dir / "notes.txt"
        with path.open("a", encoding="utf-8") as f:
            f.write(str(text).rstrip("\n") + "\n")
        return {"lines": path.read_text(encoding="utf-8").splitlines()[-20:]}

    def explore(self, steps: int = 20) -> dict[str, Any]:
        """Hand control to the rule-based explorer for `steps` presses; returns the map-memory summary."""
        return self.thread.call(
            lambda emu: self.explorer.run(emu, steps), timeout=max(30.0, steps * 3.0)
        )


def build_server(
    thread: EmulatorThread, *, runs_dir: Path = RUNS_DIR, maps_path: Path = MAPS_PATH
) -> MCPServer:
    """MCP tools over one EmulatorThread; plain sync functions (the SDK wraps them)."""
    tools = _Tools(thread, runs_dir, maps_path)
    server = MCPServer("pokeagent")
    for fn in (
        tools.press, tools.wait, tools.state, tools.screenshot, tools.peek,
        tools.snapshot, tools.diff, tools.save_state, tools.load_state,
        tools.pause, tools.resume, tools.note, tools.explore,
    ):
        server.tool()(fn)
    from pokeagent.intervene.mcp_tools import register as register_agent_tools  # live-agent digest + nudge tools
    register_agent_tools(server)

    @server.resource("pokeagent://state", mime_type="application/json")
    def current_state() -> dict[str, Any]:
        """Live game state, same shape as the state tool returns."""
        return tools.state()

    return server


def serve(rom: Path, state: Path | None, headless: bool, idle_fps: int) -> int:
    """Build the emulator on its own thread and serve MCP over stdio until EOF."""
    if state is not None and not Path(state).is_file():
        print(f"error: state file not found: {state}", file=sys.stderr)
        return 2

    def factory() -> Emulator:
        emu = PyBoyEmulator(Path(rom), headless=headless)
        emu.tick(BOOT_FRAMES)
        if state is not None:
            emu.load_state(Path(state))
        return emu

    thread = EmulatorThread(factory, idle_fps=idle_fps)
    try:
        thread.start()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        build_server(thread).run(transport="stdio")
    finally:
        thread.stop()
    return 0
