"""Emulator seam: an Emulator protocol plus PyBoy and fake implementations."""

from __future__ import annotations

import json
from enum import StrEnum, auto
from pathlib import Path
from typing import Protocol, runtime_checkable

from PIL import Image
from pyboy import PyBoy

from pokeagent.game.pokemon_red import RED
from pokeagent.game.spec import GameSpec
from pokeagent.game.state_guard import check_state_game


class Button(StrEnum):
    """Buttons the agent may press. Values match PyBoy's lowercase names."""

    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()
    A = auto()
    B = auto()
    START = auto()
    SELECT = auto()
    NONE = auto()


@runtime_checkable
class Emulator(Protocol):
    """The seam the agent loop drives: FakeEmulator in tests, PyBoy in real runs."""

    def press(self, button: Button, hold_frames: int = 8, settle_frames: int = 16) -> None:
        """Hold a button then let the game settle; NONE only ticks."""
        ...

    def tick(self, frames: int) -> None:
        """Advance emulation by frames."""
        ...

    def read(self, addr: int) -> int:
        """Read one byte of RAM."""
        ...

    def read_range(self, start: int, length: int) -> bytes:
        """Read length bytes of RAM starting at start."""
        ...

    def write(self, addr: int, value: int) -> None:
        """Write one byte of RAM."""
        ...

    def screenshot(self) -> Image.Image:
        """Current screen as the game's RGB PIL image."""
        ...

    def tick_rendered(self, frames: int) -> None:
        """Advance emulation while updating the backend frame buffer."""
        ...

    def frame_rgb(self) -> bytes:
        """Return the latest rendered frame as RGB bytes."""
        ...

    def set_speed(self, speed: int) -> None:
        """Set backend emulation speed (backend-specific units)."""
        ...

    def save_state(self, path: Path) -> None: ...
    def load_state(self, path: Path) -> None: ...
    def close(self) -> None: ...


class PyBoyEmulator:
    """Real emulator driven through PyBoy; visible window unless headless."""

    def __init__(self, rom_path: Path, *, headless: bool = True, game: GameSpec | None = None) -> None:
        from pokeagent.game.gate import game_for_rom, require_playable
        rom_path = Path(rom_path)
        if not rom_path.is_file():
            raise FileNotFoundError(f"ROM not found: {rom_path}")
        # no explicit game: the ROM's hash picks it (Blue's ROM must never run under Red's state guard)
        self.game = require_playable(game or game_for_rom(rom_path) or RED)
        self._headless = headless
        self._pyboy = PyBoy(str(rom_path), window="null" if headless else "SDL2")
        self._pyboy.set_emulation_speed(0 if headless else 1)
        self._closed = False
        self._ram_rev = 0  # bumped by write/load_state: reads memoized per frame stay honest
        self.on_press = None  # optional (button, hold, settle) callback, fired before each press (replay traces)

    @property
    def frames(self) -> int:
        """Frames emulated since boot (monotonic; includes screenshot renders)."""
        return self._pyboy.frame_count

    @property
    def screen_size(self) -> tuple[int, int]:
        """The game's (width, height) in pixels."""
        return self.game.screen

    def press(self, button: Button, hold_frames: int = 8, settle_frames: int = 16) -> None:
        if button is not Button.NONE and button.value not in self.game.buttons:
            raise ValueError(f"{button.value!r} is not a button of {self.game.key}")
        if self.on_press is not None:
            self.on_press(button, hold_frames, settle_frames)
        if button is Button.NONE:
            self.tick(hold_frames + settle_frames)
            return
        self._pyboy.button(button.value, hold_frames)
        self.tick(settle_frames)

    def tick(self, frames: int) -> None:
        self._pyboy.tick(frames, not self._headless)

    def read(self, addr: int) -> int:
        return self._pyboy.memory[addr]

    def read_range(self, start: int, length: int) -> bytes:
        return bytes(self._pyboy.memory[start : start + length])

    def write(self, addr: int, value: int) -> None:
        self._pyboy.memory[addr] = value & 0xFF
        self._ram_rev += 1

    def screenshot(self) -> Image.Image:
        # Headless ticks never render, so the screen buffer would be stale/blank: render one frame first.
        self._pyboy.tick(1, True)
        return self._pyboy.screen.image.convert("RGB")

    def tick_rendered(self, frames: int) -> None:
        """Emulate `frames` and update the screen buffer even when headless.

        Used by frame publishing: render the tick the agent was going to run anyway
        instead of adding extra rendered ticks on top.
        """
        self._pyboy.tick(frames, True)

    def set_speed(self, speed: int) -> None:
        """PyBoy speed units: 0 unthrottled, 1 realtime."""
        self._pyboy.set_emulation_speed(speed)

    def gen1(self):
        """Optional PyBoy Pokemon Gen 1 wrapper for fixture/probe tooling."""
        return getattr(self._pyboy, 'game_wrapper', None)

    def frame_rgb(self) -> bytes:
        """Current screen as w*h*3 RGB bytes (valid right after a rendered tick)."""
        try:
            return self._pyboy.screen.ndarray[:, :, :3].tobytes()
        except Exception:
            return self._pyboy.screen.image.convert("RGB").tobytes()

    def save_state(self, path: Path) -> None:
        with Path(path).open("wb") as f:
            self._pyboy.save_state(f)

    def load_state(self, path: Path) -> None:
        check_state_game(path, self.game)
        with Path(path).open("rb") as f:
            self._pyboy.load_state(f)
        self._ram_rev += 1

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._pyboy.stop(save=False)


class _RamDict(dict):
    """FakeEmulator's memory: every write bumps the owner's ``_ram_rev`` so reads memoized per
    frame stay honest even when a test pokes ``emu.memory[addr]`` directly instead of ``.set``."""

    def __init__(self, *a, owner=None, **k):
        super().__init__(*a, **k)
        self._owner = owner

    def _bump(self, *_):
        if self._owner is not None:
            self._owner._ram_rev += 1

    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        self._bump()

    def __delitem__(self, k):
        super().__delitem__(k)
        self._bump()

    def update(self, *a, **k):
        super().update(*a, **k)
        self._bump()

    def clear(self):
        super().clear()
        self._bump()

    def pop(self, *a):
        r = super().pop(*a)
        self._bump()
        return r

    def popitem(self):
        r = super().popitem()
        self._bump()
        return r

    def setdefault(self, *a):
        r = super().setdefault(*a)
        self._bump()
        return r


class FakeEmulator:
    """In-memory emulator for tests; records presses and frame counts."""

    def __init__(self, memory: dict[int, int] | None = None, *, game: GameSpec = RED) -> None:
        self.game = game
        self.memory: dict[int, int] = _RamDict(memory or {}, owner=self)
        self.presses: list[Button] = []
        self.frames: int = 0
        self.closed: bool = False
        self._ram_rev: int = 0  # bumped by set/write/load_state (same contract as PyBoyEmulator)

    @property
    def screen_size(self) -> tuple[int, int]:
        """The game's (width, height) in pixels."""
        return self.game.screen

    def set(self, addr: int, value: int) -> None:
        self.memory[addr] = value
        self._ram_rev += 1

    def write(self, addr: int, value: int) -> None:
        self.set(addr, value)

    def press(self, button: Button, hold_frames: int = 8, settle_frames: int = 16) -> None:
        if button is not Button.NONE and button.value not in self.game.buttons:
            raise ValueError(f"{button.value!r} is not a button of {self.game.key}")
        if button is not Button.NONE:
            self.presses.append(button)
        self.frames += hold_frames + settle_frames

    def tick(self, frames: int) -> None:
        self.frames += frames

    def read(self, addr: int) -> int:
        return self.memory.get(addr, 0)

    def read_range(self, start: int, length: int) -> bytes:
        return bytes(self.memory.get(start + i, 0) for i in range(length))

    def screenshot(self) -> Image.Image:
        return Image.new("RGB", self.screen_size)

    def tick_rendered(self, frames: int) -> None:
        self.frames += frames

    def frame_rgb(self) -> bytes:
        w, h = self.screen_size
        return bytes(w * h * 3)

    def set_speed(self, speed: int) -> None:
        self.speed = speed

    def save_state(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.memory))

    def load_state(self, path: Path) -> None:
        check_state_game(path, self.game)
        self.memory = _RamDict({int(k): v for k, v in json.loads(Path(path).read_text()).items()}, owner=self)
        self._ram_rev += 1

    def close(self) -> None:
        self.closed = True
