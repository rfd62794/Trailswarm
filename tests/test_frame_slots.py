import os
from unittest import mock

import pytest

from pokeagent import telemetry
from pokeagent.agent_registry import register
from pokeagent.telemetry import FramePublisher, FrameSubscriber, slot_name
from pokeagent.viewer.sources import HttpShmSource


class Emu:
    def tick_rendered(self, n): pass
    def frame_rgb(self): return bytes([7]) * (160 * 144 * 3)


def test_slot_name_unique_per_pid():
    assert slot_name(8801, 10) == "pokeagent_frames_8801_10"
    assert slot_name(8801, 10) != slot_name(8801, 11)
    assert slot_name(8801) == f"pokeagent_frames_8801_{os.getpid()}"


def test_live_slot_second_publisher_raises():
    a = FramePublisher("t1", Emu())
    try:
        with pytest.raises(FileExistsError):
            FramePublisher("t1", Emu())
        a.publish()  # first publisher still healthy
    finally:
        a.close()


def test_stale_slot_replaced():
    a = FramePublisher("t2", Emu())
    a.shm.buf[12:16] = (2**31).to_bytes(4, "little")  # owner pid that is not alive
    if os.name == "nt":  # Windows frees a dead owner's slot once its handles close
        a.shm.close()
    try:
        b = FramePublisher("t2", Emu())
        assert b.shm.buf[12:16] == os.getpid().to_bytes(4, "little")
        b.close()
    finally:
        a.close()


def test_subscriber_reads_full_name_and_pid():
    p = FramePublisher("t3", Emu())
    try:
        p.publish()
        s = FrameSubscriber(p.name)
        data, w, h = s.read()
        assert (w, h, data[0]) == (160, 144, 7) and s.owner_pid == os.getpid()
        s.close()
    finally:
        p.close()


def test_subscriber_port_resolves_via_registry(tmp_path):
    p = FramePublisher("8855", Emu())
    try:
        p.publish()
        register(tmp_path, "x", "rl", 1, p.name)
        s = FrameSubscriber(8855, root=tmp_path)
        assert s.read() is not None
        s.close()
    finally:
        p.close()


def test_viewer_rejects_stranger_pid():
    p = FramePublisher("t4", Emu())
    try:
        p.publish()
        good = HttpShmSource({"id": "g", "port": 1, "frame_slot": p.name, "pid": os.getpid()})
        bad = HttpShmSource({"id": "b", "port": 1, "frame_slot": p.name, "pid": os.getpid() + 1})
        assert good.frame() is not None
        assert bad.frame() is None
    finally:
        p.close()
