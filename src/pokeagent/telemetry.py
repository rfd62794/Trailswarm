"""Agent telemetry: optional shared-memory frame slots for live viewing.

Layer rule: agents PUBLISH (explore_demo, RL envs, swarm workers), viewers
SUBSCRIBE (tools/watch.py). "Headless" is a window choice, not a visibility
choice — any agent can publish, and one or many viewers may attach by slot
name without touching the emulator. No new dependencies (stdlib only).
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from multiprocessing import shared_memory
from typing import Optional

FRAME_W, FRAME_H = 160, 144
HEADER = 16  # u64 seq | u16 w | u16 h | u32 owner pid (seqlock: odd seq = write in progress)
SLOT_PREFIX = "pokeagent_frames_"


def slot_name(agent_id: int | str, pid: int | None = None) -> str:
    """Unique per process (shared-memory names are machine-global): pokeagent_frames_<id>_<pid>."""
    return f"{SLOT_PREFIX}{agent_id}_{os.getpid() if pid is None else pid}"


def slot_owner(buf) -> int:
    return int.from_bytes(buf[12:16], "little")


def _stale_slot_removed(name: str) -> bool:
    """True if an existing slot's recorded owner is dead and the slot was unlinked (or vanished)."""
    from pokeagent.registry import process_alive
    try:
        old = shared_memory.SharedMemory(name=name)
    except Exception:
        return True  # vanished meanwhile (Windows frees a dead owner's slot)
    try:
        if process_alive(slot_owner(old.buf)):
            return False
        old.unlink()
    except Exception:
        return False
    finally:
        old.close()
    return True


class FramePublisher:
    """Writer side: renders the tick the agent was going to run anyway (no extra game frames).

    half_res=True publishes 80x72 frames (every other pixel): ~4x cheaper render
    + transport, and the viewer upscales on display anyway."""

    def __init__(self, agent_id: int | str, emu, half_res: bool = False) -> None:
        self.emu = emu
        self.half_res = half_res
        self.seq = 0
        self.name = slot_name(agent_id)
        size = HEADER + FRAME_W * FRAME_H * 3
        try:
            self.shm = shared_memory.SharedMemory(name=self.name, create=True, size=size)
        except FileExistsError:  # never attach to a live slot: two writers make a viewer card flip games
            if not _stale_slot_removed(self.name):
                raise FileExistsError(f"frame slot {self.name} is owned by a live publisher") from None
            try:
                self.shm = shared_memory.SharedMemory(name=self.name, create=True, size=size)
            except FileExistsError:  # dead owner but handles still open (Windows): cannot reclaim
                raise FileExistsError(f"frame slot {self.name} is held by a dead publisher's open handles") from None
        self.shm.buf[12:16] = os.getpid().to_bytes(4, "little")
        w, h = self.dims()
        self.shm.buf[8:10] = w.to_bytes(2, "little")
        self.shm.buf[10:12] = h.to_bytes(2, "little")

    def dims(self) -> tuple[int, int]:
        return (80, 72) if self.half_res else (FRAME_W, FRAME_H)

    def publish(self, advance: bool = True) -> None:
        if advance:
            self.emu.tick_rendered(1)
        data = self.emu.frame_rgb()
        if self.half_res:  # decimate: every other pixel, every other row (~4x cheaper)
            out = bytearray()
            for y in range(0, FRAME_H, 2):
                row = data[y * FRAME_W * 3:(y + 1) * FRAME_W * 3]
                for x in range(0, FRAME_W, 2):
                    out += row[x * 3:x * 3 + 3]
            data = bytes(out)
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
    """Reader side: attach to one agent's slot; returns latest RGB frame bytes or None.

    ``agent_id`` is a full slot name (pokeagent_frames_<id>_<pid>) or, for tools that scan ports, a bare
    port: the slot is then looked up in the agent registry under ``root`` (prefix pokeagent_frames_<port>_)."""

    def __init__(self, agent_id: int | str, root: Path | str = ".") -> None:
        self.agent_id = agent_id
        self.root = Path(root)
        self.owner_pid = 0
        self.shm: Optional[shared_memory.SharedMemory] = None
        self._tried = 0.0
        self.seq = 0

    def _slot(self) -> Optional[str]:
        sid = str(self.agent_id)
        if sid.startswith(SLOT_PREFIX):
            return sid
        from pokeagent.agent_registry import list_agents
        for e in list_agents(self.root):
            slot = str(e.get("frame_slot") or "")
            if slot.startswith(f"{SLOT_PREFIX}{sid}_"):
                return slot
        return None

    def read(self) -> Optional[bytes]:
        if self.shm is None:
            now = time.time()
            if now - self._tried < 5.0:  # don't hammer a missing slot; retry every 5s
                return None
            self._tried = now
            try:
                name = self._slot()
                self.shm = shared_memory.SharedMemory(name=name) if name else None
            except Exception:
                self.shm = None
            if self.shm is None:
                return None
        try:
            b = self.shm.buf
            s1 = int.from_bytes(b[0:8], "little")
            if s1 == 0 or s1 & 1:
                return None  # never written, or mid-write
            w = int.from_bytes(b[8:10], "little") or FRAME_W
            h = int.from_bytes(b[10:12], "little") or FRAME_H
            data = bytes(b[16:16 + w * h * 3])
            if int.from_bytes(b[0:8], "little") != s1:
                return None  # torn read; next tick gets a clean frame
            self.seq = s1
            self.owner_pid = slot_owner(b)
            return (data, w, h)
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
