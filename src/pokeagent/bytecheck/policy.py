"""Verdicts. All thresholds are UNTUNED first guesses; revisit with real data.

LEAK    longest run >= leak_run bytes, or coverage >= leak_cov.
SUSPECT longest run >= suspect_run bytes, or coverage >= suspect_cov.
CLEAN   otherwise.

Profiles, by artifact kind:
  state   PyBoy save states hold WRAM/VRAM/OAM/cart RAM, not ROM banks, but VRAM legitimately
          holds copied ROM tile data (several KB contiguous) and WRAM can hold ROM-derived tables.
          So only a multi-KB run or several percent coverage counts. (Whether states hold ROM
          bytes beyond that is what the ROM-gated test measures on the laptop.)
  media   screenshots/video: a rendered frame should never carry 256 raw ROM bytes.
  export  map exports / atlases: rendered from the ROM, so default strictness.
  commit  anything going into git: strictest; a few dozen raw ROM bytes in source is a smell.
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.bytecheck.scan import ScanResult

CLEAN, SUSPECT, LEAK = "CLEAN", "SUSPECT", "LEAK"


@dataclass(frozen=True)
class Profile:
    leak_run: int
    leak_cov: float
    suspect_run: int
    suspect_cov: float


PROFILES = {
    "state": Profile(16384, 0.05, 2048, 0.01),
    "media": Profile(256, 0.01, 64, 0.001),
    "export": Profile(256, 0.01, 64, 0.001),
    "commit": Profile(128, 0.005, 48, 0.0005),
}
DEFAULT_PROFILE = "media"


def verdict(res: ScanResult, profile: str = DEFAULT_PROFILE) -> str:
    p = PROFILES[profile]
    if res.longest_run >= p.leak_run or res.coverage >= p.leak_cov:
        return LEAK
    if res.longest_run >= p.suspect_run or res.coverage >= p.suspect_cov:
        return SUSPECT
    return CLEAN
