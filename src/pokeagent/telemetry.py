"""Agent telemetry: optional shared-memory frame slots for live viewing.

Layer rule: agents PUBLISH (explore_demo, RL envs, swarm workers), viewers
SUBSCRIBE (tools/watch.py). "Headless" is a window choice, not a visibility
choice — any agent can publish, and one or many viewers may attach by slot
name without touching the emulator. No new dependencies (stdlib only).
"""
from __future__ import annotations

import time
from multiprocessing import shared_memory
from typing import Optional

FRAME_W, FRAME_H = 160, 144
HEADER = 16  # u64 seq | u16 w | u16 h | pad — seqlock: odd seq = write in progress


def slot_name(agent_id: int | str) -> str:
    return f"pokeagent_frames_{agent_id}"


class FramePublisher:
    """Writer side: renders the tick the agent was going to run anyway (no extra game frames)."""

    def __init__(self, agent_id: int | str, emu) -> None:
        self.emu = emu
        self.seq = 0
        self.shm = shared_memory.SharedMemory(name=slot_name(agent_id), create=True,
                                              size=HEADER + FRAME_W * FRAME_H * 3)
        self.shm.buf[8:10] = FRAME_W.to_bytes(2, "little")
        self.shm.buf[10:12] = FRAME_H.to_bytes(2, "little")

    def publish(self) -> None:
        self.emu.tick_rendered(1)
        data = self.emu.frame_rgb()
        self.seq += 1
        self.shm.buf[0:8] = (self.seq | 1).to_bytes(8, "little")
        self.shm.buf[16:16 + len(data)] = data
        self.seq += 1
        self.shm.buf[0:8] = self.seq.to_bytes(8, "little")

    def close(self) -> None:
        try:
            self.shm.close()
            self.shm.unlink()
        except Exception:
            pass


class FrameSubscriber:
    """Reader side: attach to one agent's slot; returns latest RGB frame bytes or None."""

    def __init__(self, agent_id: int | str) -> None:
        self.agent_id = agent_id
        self.shm: Optional[shared_memory.SharedMemory] = None
        self._tried = 0.0
        self.seq = 0

    def read(self) -> Optional[bytes]:
        if self.shm is None:
            now = time.time()
            if now - self._tried < 5.0:  # don't hammer a missing slot; retry every 5s
                return None
            self._tried = now
            try:
                self.shm = shared_memory.SharedMemory(name=slot_name(self.agent_id))
            except Exception:
                self.shm = None
            if self.shm is None:
                return None
        try:
            b = self.shm.buf
            s1 = int.from_bytes(b[0:8], "little")
            if s1 == 0 or s1 & 1:
                return None  # never written, or mid-write
            data = bytes(b[16:16 + FRAME_W * FRAME_H * 3])
            if int.from_bytes(b[0:8], "little") != s1:
                return None  # torn read; next tick gets a clean frame
            self.seq = s1
            return data
        except Exception:
            self.close()
            return None

    @property
    def attached(self) -> bool:
        return self.shm is not None

    def close(self) -> None:
        try:
            if self.shm is not None:
                self.shm.close()
        except Exception:
            pass
        self.shm = None
