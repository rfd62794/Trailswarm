"""Tiny gym-style env over PyBoyEmulator for segment RL (exploration lane).

Observation = (map_id, x, y, box_open, facing, in_battle, hp_bucket, bag_n) —
compact enough for tabular methods, rich enough to distinguish movement,
menus, battles and carrying items. Actions = the 6 direction/A/B buttons.
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


def sub_box_open(emu) -> bool:
    """Any menu/dialog box is open: reaching the PC and opening it reads as progress."""
    return emu.read_range(0xC3A0, 360).find(bytes([0x79, 0x7A])) >= 0


def goal_potion_run(emu) -> bool:
    """The full errand: POTION in the bag AND out of the house."""
    return goal_left_house(emu) and emu.read(0xD31D) > 0


def goal_reach_pc(emu) -> bool:
    """Standing at the PC with its menu open: a box is open while still inside the house."""
    return read_state(emu).map_id in (0x25, 0x26) and sub_box_open(emu)


def waypoint_fn(wp):
    """A mined (map,x,y) milestone becomes a first-time sub-goal detector."""
    def f(emu) -> bool:
        s = read_state(emu)
        return (s.map_id, s.x, s.y) == tuple(wp)
    return f


def curriculum_subgoals(segment: str):
    """Mined/hand-corrected milestones for this segment. Entries are {pos:[m,x,y],
    label?, quality?:silver|gold}; bare [m,x,y] lists still accepted."""
    try:
        import json
        entries = json.loads(Path("runs/rl_curriculum.json").read_text()).get(segment, [])
        return [waypoint_fn(e["pos"] if isinstance(e, dict) else e) for e in entries]
    except Exception:
        return []


GOAL_FNS = {"left_house": goal_left_house, "potion": goal_potion, "potion_run": goal_potion_run,
            "reach_pc": goal_reach_pc, "exit_potion": goal_left_house}
# checkpoints per segment, tried in order: a downstream stage starts from the previous
# stage's saved milestone (auto-written by the first agent to reach it)
SEGMENT_STATES = {"left_house": ["baselines/bedroom.state"],
                  "reach_pc": ["baselines/bedroom.state"],
                  "potion": ["runs/checkpoints/rl_reach_pc.state", "baselines/bedroom.state"],
                  "exit_potion": ["runs/checkpoints/rl_potion.state", "baselines/bedroom.state"],
                  "potion_run": ["baselines/bedroom.state"]}
# shaped sub-goals per segment: first-time detectors each worth a small bonus
SEGMENT_SUBGOALS = {"potion": [sub_box_open],
                    "potion_run": [sub_box_open, goal_potion]}


class SegmentEnv:
    def __init__(self, rom: str | Path, state: str | Path, goal_fn, goal_name: str = "",
                 subgoals: tuple = (), sub_bonus: float = 0.4,
                 max_steps: int = 300, hold: int = 8, settle: int = 8, publish_frames: bool = False,
                 windowed: bool = False, speed: int = 1, frame_port: int | None = None) -> None:
        self.emu = PyBoyEmulator(Path(rom), headless=not windowed)
        if windowed and speed != 1:
            self.emu._pyboy.set_emulation_speed(speed)  # 0 = unthrottled, 1 = realtime
        self.state = Path(state)
        self.goal_fn = goal_fn
        self.goal_name = goal_name
        self._goal_saved = False
        self.subgoals = subgoals
        self.sub_bonus = sub_bonus
        self._claimed: set = set()
        self.max_steps = max_steps
        self.hold, self.settle = hold, settle  # ~8 frames/action: lean but still a real press
        self.steps = 0
        self.publish_frames = publish_frames  # True: render+publish every settle frame (showcase agents)
        self.facing = 0  # tracked like the explorer does: last direction pressed (0=D,1=U,2=L,3=R)
        self.frame_pub = FramePublisher(frame_port, self.emu, half_res=True) if frame_port is not None else None

    def publish(self) -> None:
        """Render the current frame into the shared-memory slot for tools/watch.py."""
        if self.frame_pub is not None:
            self.frame_pub.publish()

    def reset(self):
        if self.state.exists():
            self.emu.load_state(self.state)
        self.emu.tick(60)
        self.steps = 0
        self._claimed = set()
        return self._obs()

    def step(self, action: int):
        if action < 4:
            self.facing = action  # facing = last direction pressed, same accounting as the explorer
        self.emu.press(ACTIONS[action], hold_frames=self.hold, settle_frames=0)
        for _ in range(self.settle):  # settle frames ticked one at a time: a showcase agent publishes each one
            self.emu.tick_rendered(1) if self.publish_frames else self.emu.tick(1)
            if self.publish_frames and self.frame_pub is not None:
                self.frame_pub.publish()
        self.steps += 1
        rew = -0.01
        for i, sg in enumerate(self.subgoals):
            if i not in self._claimed and sg(self.emu):  # first time this episode: milestone bonus
                self._claimed.add(i)
                rew += self.sub_bonus
        if self.goal_fn(self.emu):
            rew += 1.0
            if not self._goal_saved and self.goal_name:  # milestone checkpoint: downstream stages start here
                try:
                    self.emu.save_state(Path(f"runs/checkpoints/rl_{self.goal_name}.state"))
                    self._goal_saved = True
                except Exception:
                    pass
        done = self.goal_fn(self.emu) or self.steps >= self.max_steps
        return self._obs(), rew, done, {}

    def _obs(self):
        s = read_state(self.emu)
        tm = self.emu.read_range(0xC3A0, 360)  # verified: a box is open when corner+edge tiles appear
        box = tm.find(bytes([0x79, 0x7A])) >= 0
        in_battle = self.emu.read(0xD057) != 0  # wIsInBattle (verified)
        hp = (self.emu.read(0xD16C) << 8) | self.emu.read(0xD16D)
        mx = (self.emu.read(0xD18D) << 8) | self.emu.read(0xD18E)
        hp_bucket = min(3, int(hp * 4 / mx)) if mx else 0  # quarter-tanks, keeps the table small
        bag_n = min(9, self.emu.read(0xD31D))  # item count, bounded
        return (s.map_id, s.x, s.y, box, self.facing, in_battle, hp_bucket, bag_n)

    def close(self) -> None:
        if self.frame_pub is not None:
            self.frame_pub.close()
        self.emu.close()
