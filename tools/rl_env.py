"""Tiny gym-style env over PyBoyEmulator for segment RL (exploration lane).

Observation = (map_id, x, y, box_open) — compact enough for tabular methods,
now includes whether a dialog/menu box is open (distinguishes A-to-confirm
states from free movement). Actions = the 6 direction/A/B buttons.
Reward = +1 on the goal detector, -0.01 per step.
"""
from __future__ import annotations

from pathlib import Path

from pokeagent.emulator import Button, PyBoyEmulator
from pokeagent.ram import read_state
from pokeagent.telemetry import FramePublisher

ACTIONS = [Button.UP, Button.DOWN, Button.LEFT, Button.RIGHT, Button.A, Button.B]


def goal_left_house(emu) -> bool:
    """Bedroom baseline -> outside: house interior maps are 0x25/0x26."""
    return read_state(emu).map_id not in (0x25, 0x26)


def goal_potion(emu) -> bool:
    """Withdraw the POTION from the PC: bag item count 0xD31D > 0."""
    return emu.read(0xD31D) > 0


GOAL_FNS = {"left_house": goal_left_house, "potion": goal_potion}
# which checkpoint each segment resets to (previous goal in the campaign chain)
SEGMENT_STATES = {"left_house": "baselines/bedroom.state", "potion": "baselines/bedroom.state"}


class SegmentEnv:
    def __init__(self, rom: str | Path, state: str | Path, goal_fn,
                 max_steps: int = 300, hold: int = 8, settle: int = 8,
                 windowed: bool = False, speed: int = 1, frame_port: int | None = None) -> None:
        self.emu = PyBoyEmulator(Path(rom), headless=not windowed)
        if windowed and speed != 1:
            self.emu._pyboy.set_emulation_speed(speed)  # 0 = unthrottled, 1 = realtime
        self.state = Path(state)
        self.goal_fn = goal_fn
        self.max_steps = max_steps
        self.hold, self.settle = hold, settle  # ~8 frames/action: lean but still a real press
        self.steps = 0
        self.frame_pub = FramePublisher(frame_port, self.emu) if frame_port is not None else None

    def publish(self) -> None:
        """Render the current frame into the shared-memory slot for tools/watch.py."""
        if self.frame_pub is not None:
            self.frame_pub.publish()

    def reset(self):
        if self.state.exists():
            self.emu.load_state(self.state)
        self.emu.tick(60)
        self.steps = 0
        return self._obs()

    def step(self, action: int):
        self.emu.press(ACTIONS[action], hold_frames=self.hold, settle_frames=self.settle)
        self.steps += 1
        done = self.goal_fn(self.emu) or self.steps >= self.max_steps
        return self._obs(), (1.0 if self.goal_fn(self.emu) else -0.01), done, {}

    def _obs(self):
        s = read_state(self.emu)
        tm = self.emu.read_range(0xC3A0, 360)  # verified: a box is open when corner+edge tiles appear
        box = tm.find(bytes([0x79, 0x7A])) >= 0
        return (s.map_id, s.x, s.y, box)

    def close(self) -> None:
        if self.frame_pub is not None:
            self.frame_pub.close()
        self.emu.close()
