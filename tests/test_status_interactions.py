import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from status import interaction_lines  # noqa: E402


def test_interaction_metrics_lines():
    maps = {"interaction_stats": {"by_type": {"info": {"talks": 4, "presses": 20}, "healer": {"talks": 1, "presses": 9}},
                                  "retalks": 0, "retalks_avoided": 7, "heal_visits": 1},
            "text_press_stats": {"presses": 50, "pages": 40, "dropped": 1, "frames": 2600}, "text_speed": {"byte": 1}}
    lines = interaction_lines(maps)
    assert "info 4x 5.0" in lines[0] and "healer 1x 9.0" in lines[0]
    assert "re-talks avoided: 7" in lines[1] and "heal visits: 1" in lines[1]
    assert "65.0 frames/page" in lines[2] and "1.25 presses/page" in lines[2]
    assert interaction_lines({}) == []
