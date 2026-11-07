"""swarm.py shares frames by default (the viewer Tiles need them); --no-share-frames turns it off."""
import importlib.util
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location("tool_swarm_cli", TOOLS / "swarm.py")
swarm = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = swarm
spec.loader.exec_module(swarm)


def test_frame_sharing_is_the_default():
    assert swarm.build_parser().parse_args([]).share_frames is True


def test_share_frames_flag_still_accepted():
    assert swarm.build_parser().parse_args(["--share-frames"]).share_frames is True


def test_no_share_frames_turns_it_off():
    assert swarm.build_parser().parse_args(["--no-share-frames"]).share_frames is False
