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
