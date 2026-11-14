import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location('rl_env_terminal_test', Path(__file__).parents[1] / 'tools/rl_env.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Emulator:
    def __init__(self):
        self.frames = 0

    def press(self, *args, **kwargs):
        pass

    def tick(self, frames):
        self.frames += frames


class CountingEmulator:
    """Counts held vs released frame budgets; tick_rendered counts exactly like tick."""

    def __init__(self):
        self.frames = 0
        self.held = 0      # frames while the button is down
        self.released = 0  # frames after release, before the next action
        self.rendered = 0  # of those released frames, how many were rendered ticks

    def press(self, button, hold_frames=8, settle_frames=16):
        self.frames += hold_frames + settle_frames
        self.held += hold_frames
        self.released += settle_frames

    def tick(self, frames):
        self.frames += frames
        self.released += frames

    def tick_rendered(self, frames):
        self.frames += frames
        self.released += frames
        self.rendered += frames

    def read(self, addr):
        return 0

    def read_range(self, start, length):
        return bytes(length)

    def frame_rgb(self):
        return bytes(160 * 144 * 3)


class CountingPublisher:
    """Mirrors FramePublisher.publish: advance=True renders an extra tick."""

    def __init__(self, emu):
        self.emu = emu
        self.advances = []

    def publish(self, advance=True):
        self.advances.append(advance)
        if advance:
            self.emu.tick_rendered(1)
        self.emu.frame_rgb()


def counted_env(emu, **overrides):
    env = module.SegmentEnv.__new__(module.SegmentEnv)
    env.emu = emu
    env.hold = 8
    env.settle = 8
    env.publish_frames = False
    env.frame_pub = None
    env.render_interval = 1.0 / 15
    env._last_render = 0.0
    env.steps = 0
    env.max_steps = 100
    env.subgoals = ()
    env.goal_name = ''
    env.goal_fn = lambda emu: False
    env._goal_saved = True
    env.facing = 0
    env._obs = lambda: ()
    for key, value in overrides.items():
        setattr(env, key, value)
    return env


def test_stateful_goal_evaluated_once_per_step():
    env = module.SegmentEnv.__new__(module.SegmentEnv)
    env.emu = Emulator()
    env.hold = 8
    env.settle = 0
    env.publish_frames = False
    env.steps = 0
    env.max_steps = 10
    env.subgoals = ()
    env.goal_name = ''
    env._goal_saved = False
    env._obs = lambda: ()
    calls = []

    def goal(emu):
        calls.append(emu)
        return len(calls) == 1

    env.goal_fn = goal
    _, reward, done, info = env.step(4)
    assert len(calls) == 1
    assert done and env.goal_reached and info['goal_reached']
    assert not info['truncated']
    assert reward == 0.99


def test_timeout_is_not_a_win():
    env = module.SegmentEnv.__new__(module.SegmentEnv)
    env.emu = Emulator()
    env.hold = 8
    env.settle = 0
    env.publish_frames = False
    env.steps = 0
    env.max_steps = 1
    env.subgoals = ()
    env.goal_fn = lambda emu: False
    env._obs = lambda: ()
    _, _, done, info = env.step(4)
    assert done and info['truncated']
    assert not env.goal_reached


def test_step_spends_hold_then_release_window():
    emu = CountingEmulator()
    env = counted_env(emu, hold=8, settle=8)
    env.step(4)
    assert emu.held == 8              # the press itself holds the button for --hold frames
    assert emu.released == 8 + 8      # then the button is released for a hold+settle window
    assert emu.frames == 8 + (8 + 8)  # one action costs hold + (hold+settle) emulator frames


def test_render_and_publish_do_not_add_frames():
    actions = [4, 4, 0, 1, 2, 3, 5]
    plain = CountingEmulator()
    paced_emu, burst_emu = CountingEmulator(), CountingEmulator()
    paced = CountingPublisher(paced_emu)
    burst = CountingPublisher(burst_emu)
    envs = [counted_env(plain),
            counted_env(paced_emu, frame_pub=paced, render_interval=0.0),
            counted_env(burst_emu, frame_pub=burst, publish_frames=True)]
    for action in actions:
        for env in envs:
            env.step(action)
            env.publish()  # the wall-clock paced path must not advance the emulator either
    assert plain.frames == paced_emu.frames == burst_emu.frames == len(actions) * 24
    assert paced_emu.rendered == len(actions)            # render_due renders only the last budgeted frame
    assert burst_emu.rendered == len(actions) * 16       # publish_frames renders every budgeted frame
    assert paced.advances == [False] * len(actions)
    assert burst.advances == [False] * len(actions) * 17  # 16 in-step publishes + 1 wall-clock publish
