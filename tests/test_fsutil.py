import os

import pytest

from pokeagent import fsutil


def _flaky(monkeypatch, n):
    real, calls = os.replace, {"n": 0}

    def fake(src, dst):
        calls["n"] += 1
        if calls["n"] <= n:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(src, dst)
    monkeypatch.setattr(fsutil.os, "replace", fake)
    monkeypatch.setattr(fsutil.time, "sleep", lambda s: None)
    return calls


def test_retry_then_success(tmp_path, monkeypatch):
    calls = _flaky(monkeypatch, 3)
    dst = tmp_path / "maps.json"
    fsutil.atomic_write_text(dst, "{}")
    assert dst.read_text() == "{}" and calls["n"] == 4
    assert list(tmp_path.iterdir()) == [dst]


def test_failure_surfaces_after_bound(tmp_path, monkeypatch):
    calls = _flaky(monkeypatch, 99)
    with pytest.raises(PermissionError):
        fsutil.atomic_write_text(tmp_path / "m.json", "{}", attempts=4)
    assert calls["n"] == 4
    assert list(tmp_path.iterdir()) == []  # temp cleaned up


def test_unique_tmp_per_process(tmp_path):
    assert str(os.getpid()) in fsutil.unique_tmp(tmp_path / "a.json").name


def test_where_names_frame_and_file(tmp_path):
    try:
        open(tmp_path / "missing" / "x", "rb")
    except OSError as e:
        w = fsutil.where(e)
    assert "test_fsutil.py" in w and "test_where_names_frame_and_file" in w and "x" in w
