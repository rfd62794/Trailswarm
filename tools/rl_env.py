"""Tiny gym-style env over PyBoyEmulator for segment RL (exploration lane).

Observation = (map_id, x, y, box_open, facing, in_battle, hp_bucket, bag_n) —
compact enough for tabular methods, rich enough to distinguish movement,
menus, battles and carrying items. Actions = the 6 direction/A/B buttons.
Reward = +1 on the goal detector, -0.01 per step.
"""
from __future__ import annotations

from pathlib import Path
import time

from pokeagent.emulator import Button, PyBoyEmulator
from pokeagent.ram import read_state
from pokeagent.telemetry import FramePublisher

ACTIONS = [Button.UP, Button.DOWN, Button.LEFT, Button.RIGHT, Button.A, Button.B]


def goal_left_house(emu) -> bool:
    """Bedroom baseline -> outside: house interior maps are 0x25/0x26."""
    return read_state(emu).map_id == 0x00


def goal_potion(emu) -> bool:
    """Withdraw the POTION from the PC: bag item count 0xD31D > 0."""
    from pokeagent.goals import bag_contents
    return bag_contents(emu).get(0x14, 0) > 0


def sub_box_open(emu) -> bool:
    """Any menu/dialog box is open: reaching the PC and opening it reads as progress."""
    return emu.read_range(0xC3A0, 360).find(bytes([0x79, 0x7A])) >= 0


def _u16(emu, addr: int) -> int:
    return (emu.read(addr) << 8) | emu.read(addr + 1)


def sub_enemy_hurt(emu) -> bool:
    """Enemy HP dropped to <=75%: first hit landed (battle-segment shaping)."""
    if emu.read(0xD057) == 0:
        return False
    e_max, e_hp = _u16(emu, 0xCFF4), _u16(emu, 0xCFE6)
    return bool(e_max) and e_hp * 4 <= e_max * 3


def battle_obs_extra(emu):
    """Battle-only observation fields: enemy HP quarter-bucket + level bucket +
    battle kind (0xD057: 1=wild/random, 2=trainer/set). Appended to the base obs
    ONLY for the battle segment, so nav Q-tables stay valid."""
    kind = emu.read(0xD057)
    if kind == 0:
        return (0, 0, 0)
    e_max, e_hp = _u16(emu, 0xCFF4), _u16(emu, 0xCFE6)
    return (min(3, e_hp * 4 // e_max) if e_max else 0, emu.read(0xCFF3) // 10, kind)


def make_battle_goal():
    """Win a wild battle: enemy HP hits 0 and we end up back on the fight tile.
    A blackout warps the player home instead, so the position match separates
    a win from a loss; running away never sets `fainted`, so it doesn't count."""
    st = {"pos": None, "fainted": False}

    def goal(emu) -> bool:
        s = read_state(emu)
        if emu.read(0xD057) != 0:
            st["pos"] = (s.map_id, s.x, s.y)
            if _u16(emu, 0xCFE6) == 0 and _u16(emu, 0xCFF4):
                st["fainted"] = True
            return False
        pos, fainted = st.get("pos"), st.get("fainted", False)
        st["pos"], st["fainted"] = None, False
        return bool(pos and fainted and (s.map_id, s.x, s.y) == pos)

    def reset() -> None:
        st["pos"], st["fainted"] = None, False

    goal.reset = reset
    return goal


def make_grind_goal(wins_needed: int = 3):
    """Win N wild battles: the training loop is walk->encounter->fight->resume.
    Only kind-1 (wild/random) KOs count; trainer/set battles (kind 2) don't.
    A blackout doesn't end the episode -- it's a setback, not a terminal."""
    st = {"pos": None, "fainted": False, "kind": 0, "wins": 0}

    def goal(emu) -> bool:
        if st["wins"] >= wins_needed:
            return True
        s = read_state(emu)
        kind = emu.read(0xD057)
        if kind != 0:
            st["pos"] = (s.map_id, s.x, s.y)
            st["kind"] = kind
            if _u16(emu, 0xCFE6) == 0 and _u16(emu, 0xCFF4):
                st["fainted"] = True
            return False
        pos, fainted, k = st.get("pos"), st.get("fainted", False), st.get("kind", 0)
        st["pos"], st["fainted"], st["kind"] = None, False, 0
        if pos and fainted and k == 1 and (s.map_id, s.x, s.y) == pos:
            st["wins"] += 1
            return st["wins"] >= wins_needed
        return False

    def reset() -> None:
        st.update({"pos": None, "fainted": False, "kind": 0, "wins": 0})

    goal.reset = reset
    return goal


def goal_potion_run(emu) -> bool:
    """The full errand: POTION in the bag AND out of the house."""
    return goal_left_house(emu) and goal_potion(emu)


def goal_reach_pc(emu) -> bool:
    """Standing at the PC with its menu open: a box is open while still inside the house."""
    from pokeagent.screencontext import MenuKind, classify_screen
    context = classify_screen(emu.read_range(0xC3A0, 360), emu.read(0xD057))
    return read_state(emu).map_id == 0x26 and context.menu == MenuKind.PC


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


def goal_menu_start(emu):
    from pokeagent.screencontext import MenuKind, ScreenType, classify_screen
    context = classify_screen(emu.read_range(0xC3A0, 360), emu.read(0xD057))
    return context.screen == ScreenType.MENU and context.menu == MenuKind.START


def goal_map(map_id: int):
    """Reach a campaign map: the RL ladder beyond the house is pure map_id goals."""
    def f(emu) -> bool:
        return read_state(emu).map_id == map_id
    return f


GOAL_FNS = {"menu_start": goal_menu_start, "left_house": goal_left_house, "potion": goal_potion, "potion_run": goal_potion_run,
            "reach_pc": goal_reach_pc, "exit_potion": goal_potion_run,
            "to_viridian": goal_map(0x01), "to_route2": goal_map(0x0D),
            "to_pewter": goal_map(0x02), "to_gym": goal_map(0x36),
            "battle": make_battle_goal(), "grind": make_grind_goal(3)}
def make_goal(segment):
    if segment == 'battle':
        return make_battle_goal()
    if segment == 'grind':
        return make_grind_goal(3)
    return GOAL_FNS[segment]


# per-segment extra observation fields (appended to the base 8-tuple)
EXTRA_OBS = {"battle": battle_obs_extra, "grind": battle_obs_extra}
# checkpoints per segment, tried in order: a downstream stage starts from the previous
# stage's saved milestone (auto-written by the first agent to reach it)
SEGMENT_STATES = {"menu_start": ["baselines/bedroom.state"], "left_house": ["baselines/bedroom.state"],
                  "reach_pc": ["baselines/bedroom.state"],
                  "potion": ["runs/checkpoints/rl_reach_pc.state", "baselines/bedroom.state"],
                  "exit_potion": ["runs/checkpoints/rl_potion.state", "baselines/bedroom.state"],
                  "potion_run": ["baselines/bedroom.state"],
                  "to_viridian": ["runs/checkpoints/rl_exit_potion.state",
                                  "runs/checkpoints/to_route1.state",
                                  "runs/checkpoints/rl_potion.state", "baselines/bedroom.state"],
                  "to_route2": ["runs/checkpoints/deliver_parcel_closed.state",
                                "runs/checkpoints/deliver_parcel.state",
                                "runs/checkpoints/rl_deliver_parcel.state",
                                "runs/checkpoints/rl_to_viridian.state",
                                "runs/checkpoints/to_viridian.state",
                                "runs/checkpoints/rl_exit_potion.state",
                                "runs/checkpoints/to_route1.state", "baselines/bedroom.state"],
                  "to_pewter": ["runs/checkpoints/rl_to_route2.state",
                                "runs/checkpoints/to_route2.state",
                                "runs/checkpoints/rl_to_viridian.state",
                                "runs/checkpoints/to_viridian.state", "baselines/bedroom.state"],
                  "to_gym": ["runs/checkpoints/rl_to_pewter.state",
                             "runs/checkpoints/to_pewter.state",
                             "runs/checkpoints/rl_to_route2.state",
                             "runs/checkpoints/to_route2.state", "baselines/bedroom.state"],
                  "battle": ["baselines/battle.state",
                             "runs/checkpoints/to_route1.state",
                             "runs/checkpoints/to_viridian.state", "baselines/bedroom.state"],
                  "grind": ["runs/checkpoints/rl_grind.state",
                            "runs/checkpoints/to_viridian.state",
                            "runs/checkpoints/to_route1.state",
                            "runs/checkpoints/rl_exit_potion.state", "baselines/bedroom.state"]}
# shaped sub-goals per segment: first-time detectors each worth a small bonus
SEGMENT_SUBGOALS = {"potion": [sub_box_open],
                    "potion_run": [sub_box_open, goal_potion],
                    "to_route2": [goal_map(0x00), goal_map(0x0C), goal_map(0x01)],
                    "battle": [sub_enemy_hurt]}


class SegmentEnv:
    def __init__(self, rom: str | Path, state: str | Path, goal_fn, goal_name: str = "",
                 subgoals: tuple = (), sub_bonus: float = 0.4,
                 max_steps: int = 300, hold: int = 8, settle: int = 8, publish_frames: bool = False,
                 windowed: bool = False, speed: int = 1, frame_port: int | None = None,
                 half_res: bool = True, obs_extra=None, screen_context: bool = False) -> None:
        self.emu = PyBoyEmulator(Path(rom), headless=not windowed)
        if windowed and speed != 1:
            self.emu.set_speed(speed)  # 0 = unthrottled, 1 = realtime
        self.state = Path(state)
        self.actions = tuple(ACTIONS)
        self.screen_context = screen_context
        self.spatial_observer = None
        self.combat_context = False
        self.goal_fn = goal_fn
        self.goal_name = goal_name
        from pokeagent.learning import BattleTracker
        self.battle_tracker = BattleTracker()
        self.battle_learning = False
        self.travel_priority = False
        self.battle_outcomes = {}
        self._goal_saved = False
        self.subgoals = subgoals
        self.sub_bonus = sub_bonus
        self._claimed: set = set()
        self.max_steps = max_steps
        self.hold, self.settle = hold, settle  # ~8 frames/action: lean but still a real press
        self.steps = 0
        self.render_interval = 1.0 / 15
        self._last_render = 0.0
        self.publish_frames = publish_frames  # True: render+publish every settle frame (showcase agents)
        self.facing = 0  # tracked like the explorer does: last direction pressed (0=D,1=U,2=L,3=R)
        self.frame_pub = FramePublisher(frame_port, self.emu, half_res=half_res) if frame_port is not None else None
        self.obs_extra = obs_extra  # segment-specific fields appended to the base obs

    def allowed_actions(self):
        from pokeagent.learning import retreat_allowed
        from pokeagent.screentext import CHARMAP
        if not self.battle_learning or self.emu.read(0xD057) != 1:
            return list(range(len(self.actions)))
        if retreat_allowed(_u16(self.emu, 0xD015), _u16(self.emu, 0xD023), self.travel_priority):
            return list(range(len(self.actions)))
        tm = self.emu.read_range(0xC3A0, 360)
        for i, tile in enumerate(tm):
            if tile == 0xED:
                label = ''.join(CHARMAP.get(b, ' ') for b in tm[i + 1:(i // 20 + 1) * 20]).strip()
                if label.startswith('RUN'):
                    return [i for i in range(len(self.actions)) if self.actions[i] != Button.A]
        return list(range(len(self.actions)))

    def battle_sample(self):
        from pokeagent.learning import BattleSample
        s = read_state(self.emu)
        party_hp = sum(_u16(self.emu, 0xD16C + i * 44)
                       for i in range(min(6, self.emu.read(0xD163))))
        return BattleSample(self.emu.read(0xD057), (s.map_id, s.x, s.y),
                            _u16(self.emu, 0xCFE6), _u16(self.emu, 0xCFF4), party_hp)

    def battle_snapshot(self):
        try:
            kind = self.emu.read(0xD057)
        except AttributeError:
            return {'kind': 0}
        if not kind:
            return {'kind': 0}
        return {'kind': kind, 'enemy_species': self.emu.read(0xCFE5),
                'enemy_level': self.emu.read(0xCFF3), 'own_level': self.emu.read(0xD022),
                'own_hp': _u16(self.emu, 0xD015), 'own_max': _u16(self.emu, 0xD023),
                'enemy_hp': _u16(self.emu, 0xCFE6), 'enemy_max': _u16(self.emu, 0xCFF4),
                'moves': [self.emu.read(0xD01C + i) for i in range(4)],
                'pp': [self.emu.read(0xD02D + i) & 0x3F for i in range(4)]}

    def _capture_battle(self):
        snap = self.battle_snapshot()
        if snap.get('kind'):
            if not getattr(self, '_battle_start', None):
                self._battle_start = snap
            self._battle_end = snap

    def battle_summary(self):
        start = getattr(self, '_battle_start', None)
        end = getattr(self, '_battle_end', None)
        if not start:
            return {}
        moves = {}
        for i, move in enumerate(start.get('moves', [])):
            if not move:
                continue
            used = max(0, start['pp'][i] - end.get('pp', start['pp'])[i])
            if used:
                moves[str(i)] = {'move': move, 'pp_used': used}
        return {'start': start, 'end': end, 'moves_used': moves,
                'outcomes': dict(self.battle_outcomes)}

    def publish(self) -> None:
        """Render the current frame into the shared-memory slot for tools/watch.py."""
        if self.frame_pub is not None:
            self.frame_pub.publish(advance=False)

    def reset(self):
        if self.state.exists():
            self.emu.load_state(self.state)
        reset_fn = getattr(self.goal_fn, "reset", None)
        if reset_fn:
            reset_fn()  # stateful goals (battle/grind) clear per-episode counters
        self.emu.tick(60)
        self.steps = 0
        self.goal_reached = False
        if self.goal_name and self.goal_name not in ('battle', 'grind') and self.goal_fn(self.emu):
            raise ValueError(f'Start checkpoint already satisfies {self.goal_name}; refusing a trivial success')
        self.battle_tracker.reset()
        self.battle_tracker.update(self.battle_sample())
        self._battle_start = self._battle_end = None
        self._capture_battle()
        self.battle_outcomes = {}
        self._claimed = set()
        return self._obs()

    def step(self, action: int):
        if action < 4:
            self.facing = action  # facing = last direction pressed, same accounting as the explorer
        self.emu.press(getattr(self, 'actions', ACTIONS)[action], hold_frames=self.hold, settle_frames=0)
        for frame in range(self.hold + self.settle):  # settle frames ticked one at a time: a showcase agent publishes each one
            publisher = getattr(self, 'frame_pub', None)
            render_due = (publisher is not None and frame == self.hold + self.settle - 1
                          and time.monotonic() - self._last_render >= self.render_interval)
            if self.publish_frames or render_due:
                self.emu.tick_rendered(1)
                self._last_render = time.monotonic()
            else:
                self.emu.tick(1)
            if self.publish_frames and publisher is not None:
                publisher.publish(advance=False)
        self.steps += 1
        rew = -0.01
        for i, sg in enumerate(self.subgoals):
            if i not in self._claimed and sg(self.emu):  # first time this episode: milestone bonus
                self._claimed.add(i)
                rew += self.sub_bonus
        from pokeagent.learning import BattleOutcome, battle_reward
        tracker = getattr(self, 'battle_tracker', None)
        outcome = tracker.update(self.battle_sample()) if tracker else BattleOutcome.NONE
        self._capture_battle()
        if tracker and outcome != BattleOutcome.NONE:
            self.battle_outcomes[outcome.value] = self.battle_outcomes.get(outcome.value, 0) + 1
        if tracker and self.goal_name in ('battle', 'grind'):
            self.goal_reached = tracker.wild_wins >= 3 if self.goal_name == 'grind' else tracker.wild_wins + tracker.trainer_wins >= 1
        else:
            self.goal_reached = bool(self.goal_fn(self.emu))
        if getattr(self, 'battle_learning', False):
            rew += battle_reward(outcome, safe_to_fight=True, travel_priority=self.travel_priority)
        if self.goal_reached:
            rew += 1.0
            if not self._goal_saved and self.goal_name:  # milestone checkpoint: downstream stages start here
                try:
                    from pokeagent.statemeta import write_state
                    write_state(self.emu, Path(f"runs/checkpoints/rl_{self.goal_name}.state"),
                                source=self.state, segment=self.goal_name,
                                note='RL milestone checkpoint')
                    self._goal_saved = True
                except Exception:
                    pass
        failed = outcome == BattleOutcome.BLACKOUT
        done = self.goal_reached or failed or self.steps >= self.max_steps
        return self._obs(), rew, done, {"goal_reached": self.goal_reached,
                                       "terminated": self.goal_reached or failed,
                                       "outcome": outcome.value,
                                       "truncated": not (self.goal_reached or failed) and self.steps >= self.max_steps,
                                       "battle": self.battle_summary()}

    def _obs(self):
        s = read_state(self.emu)
        tm = self.emu.read_range(0xC3A0, 360)  # verified: a box is open when corner+edge tiles appear
        box = tm.find(bytes([0x79, 0x7A])) >= 0
        in_battle = self.emu.read(0xD057) != 0  # wIsInBattle (verified)
        hp = (self.emu.read(0xD16C) << 8) | self.emu.read(0xD16D)
        mx = (self.emu.read(0xD18D) << 8) | self.emu.read(0xD18E)
        hp_bucket = min(3, int(hp * 4 / mx)) if mx else 0  # quarter-tanks, keeps the table small
        bag_n = min(9, self.emu.read(0xD31D))  # item count, bounded
        base = (s.map_id, s.x, s.y, box, self.facing, in_battle, hp_bucket, bag_n)
        if self.screen_context:
            from pokeagent.screencontext import classify_screen
            base += classify_screen(tm, self.emu.read(0xD057)).observation()
        if self.spatial_observer:
            base += self.spatial_observer.observe(tm, s.map_id, s.x, s.y, self.emu.read(0xD367),
                                                  obscured=box or in_battle)
        if self.combat_context:
            from pokeagent.observations import combat_observation
            base += combat_observation(self.emu)
        return base + tuple(self.obs_extra(self.emu)) if self.obs_extra else base

    def close(self) -> None:
        if self.frame_pub is not None:
            self.frame_pub.close()
        self.emu.close()
