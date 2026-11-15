"""Measured xp/min by trainee level bucket (synthetic ledgers): the 4th episode element and the
bucket-aware measured value choose() prefers."""
from __future__ import annotations

from pokeagent.grind import points as gp
from pokeagent.grind import xp_buckets as xb


def pt(map_id, band=(1, 99), prior=100.0, **kw):
    return gp.GrindPoint(map_id, name=f"MAP{map_id}", level_band=band, xp_per_min_prior=prior, **kw)


def test_bucket_of_and_measured_for():
    assert xb.bucket_of(9) == 5 and xb.bucket_of(10) == 10 and xb.bucket_of(5) == 5
    assert xb.bucket_of(4) == 0 and xb.bucket_of(None) is None
    p = pt(35)
    gp.episode_result(p, 10, 50, 0, ep_id="a", trainee_level=12)   # bucket 10, 45/min
    gp.episode_result(p, 20, 50, 0, ep_id="b", trainee_level=14)   # bucket 10, 90/min
    gp.episode_result(p, 30, 50, 0, ep_id="c")                     # untagged: the default bucket, 135/min
    assert p.episodes["a"] == [45.0, 0, "organic", 10]             # the bucket rides along as element 4
    assert xb.measured_for(p, 14) == (67.5, 2)                     # the trainee's bucket wins
    assert xb.measured_for(p, 4) == (135.0, 1)                     # bucket 0 empty: the default bucket
    assert xb.measured_for(p, None) == (135.0, 1)
    assert xb.measured_for(pt(36), 10) is None


def test_choose_uses_the_trainee_bucket_when_it_has_min_measured():
    a = pt(35, prior=0.0)
    gp.episode_result(a, 20, 50, 0, ep_id="a", trainee_level=12)   # 90/min bucket 10
    gp.episode_result(a, 20, 50, 0, ep_id="b", trainee_level=13)   # 90/min bucket 10
    gp.episode_result(a, 2, 50, 0, ep_id="c")                      # 9/min default bucket: all-mean 63
    b = pt(36, prior=75.0, blackout_rate=0.0)                     # even blackout terms: only xp differs
    led = gp.GrindLedger({35: a, 36: b})
    assert gp.choose(led, [12], 20, None).map_id == 35   # L12 -> bucket-10 mean 90 beats the 75 prior
    assert gp.choose(led, [20], 30, None).map_id == 36   # L20 -> default 1 ep < MIN_MEASURED -> all-mean 63 loses
    assert gp.choose(led, [12], 20, None, rank=None).map_id == 35  # same answer through the new kwarg
