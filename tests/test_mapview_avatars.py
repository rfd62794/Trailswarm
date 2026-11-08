"""frame_crop avatars: keying, tinting, the in-memory cache (nothing ever hits disk)."""
from pathlib import Path
from unittest.mock import patch

import numpy as np

from pokeagent.mapview.avatars import AvatarCache, crop_avatar, tint
from pokeagent.mapview.live import LivePos
from pokeagent.mapview.presets import resolve


def frame():
    """160x144 flat background with a small dark sprite box at (30, 40) sized 8."""
    f = np.full((144, 160, 3), 200, np.uint8)
    f[44:50, 32:38] = (20, 30, 40)
    return f


def live(sx=30, sy=40):
    return LivePos("a", "r", "1-1", 0.0, 0.0, sx, sy, 0.0)


def test_crop_keys_out_the_background():
    out = crop_avatar(frame(), 30, 40, 12)
    assert out is not None and out.shape == (12, 12, 4)
    assert out[6, 6, 3] == 255 and list(out[6, 6, :3]) == [20, 30, 40]     # the sprite pixel
    assert out[0, 0, 3] == 0                                             # corner keyed out
    ring = crop_avatar(frame(), 30, 40, 12, key=(200, 200, 200))
    assert np.array_equal(ring[..., 3], out[..., 3])


def test_crop_returns_none_for_bad_boxes():
    assert crop_avatar(frame(), 500, 500, 12) is None                    # fully outside
    assert crop_avatar(frame(), 0, 0, 12, key=(0, 0, 0)) is None         # nothing keyed
    assert crop_avatar(frame(), 0, 0, 12) is None                        # all background: >90% keyed


def test_tint_blends_opaque_and_outlines():
    crop = crop_avatar(frame(), 30, 40, 12)
    t = tint(crop, (255, 0, 0))
    m = crop[..., 3] > 0
    assert (t[..., 3][m] == 255).all()                                   # alpha kept on the sprite
    px = t[..., :3][m][0]
    assert px[0] > crop[..., :3][m][0, 0]                                # red mixed in
    assert list(t[5, 1, :3]) == [255, 0, 0] and t[5, 1, 3] == 255        # 1 px outline ring
    assert t[0, 0, 3] == 0                                               # far pixel still transparent


def test_cache_offer_get_and_tinted_variants():
    c = AvatarCache()
    preset = resolve()
    assert c.get(preset, "RIGHT", (1, 2, 3)) is None                     # nothing offered yet
    c.offer(preset, "RIGHT", frame(), live())
    a = c.get(preset, "RIGHT", (1, 2, 3))
    b = c.get(preset, "RIGHT", (9, 9, 9))
    assert a is not None and b is not None and a is not b                # tinted per colour
    assert c.get(preset, "RIGHT", (1, 2, 3)) is a                        # same array from cache


def test_a_better_crop_replaces_a_worse_one():
    from types import SimpleNamespace
    c = AvatarCache()
    preset = SimpleNamespace(name="p", avatar_size=12)                     # 12 px box: crops qualify
    sparse = np.full((144, 160, 3), 200, np.uint8)
    sparse[44:48, 32:36] = (20, 30, 40)                                  # 4x4 sprite
    key = ("p", "RIGHT")
    c.offer(preset, "RIGHT", sparse, live())
    n1 = int((c._crops[key][..., 3] > 0).sum())
    c.offer(preset, "RIGHT", frame(), live())                            # 6x8 sprite: more opaque
    n2 = int((c._crops[key][..., 3] > 0).sum())
    assert n2 > n1
    c.offer(preset, "RIGHT", sparse, live())                             # a worse offer is kept out
    assert int((c._crops[key][..., 3] > 0).sum()) == n2


def test_nothing_is_written_to_disk(tmp_path):
    c = AvatarCache()
    preset = resolve()
    with patch("builtins.open", side_effect=AssertionError("disk")), \
         patch.object(Path, "write_bytes", side_effect=AssertionError("disk")), \
         patch("PIL.Image.Image.save", side_effect=AssertionError("disk")):
        c.offer(preset, "RIGHT", frame(), live())
        assert c.get(preset, "RIGHT", (5, 5, 5)) is not None
