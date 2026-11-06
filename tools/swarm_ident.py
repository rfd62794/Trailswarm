"""Process identity for adopted agents: a pid alone can be reused by an unrelated process, so adoption records the
process creation time and the command line (must contain explore_demo). Stdlib only; None = could not be read."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

SIGNATURE = "explore_demo"


class Ident:
    def created(self, pid: int):
        """An opaque, stable per-process start stamp (same process -> same value), or None."""
        try:
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes
                k = ctypes.WinDLL("kernel32", use_last_error=True)
                k.OpenProcess.restype = wintypes.HANDLE
                k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                k.CloseHandle.argtypes = [wintypes.HANDLE]
                k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
                h = k.OpenProcess(0x1000, False, pid)
                if not h:
                    return None
                try:
                    t = [wintypes.FILETIME() for _ in range(4)]
                    if not k.GetProcessTimes(h, *[ctypes.byref(x) for x in t]):
                        return None
                    return (t[0].dwHighDateTime << 32) | t[0].dwLowDateTime
                finally:
                    k.CloseHandle(h)
            return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19])
        except (OSError, ValueError, IndexError):
            return None

    def cmdline(self, pid: int):
        try:
            if os.name == "nt":
                q = f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"
                r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", q],
                                   capture_output=True, text=True, timeout=20)
                return r.stdout.strip() or None
            return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace") or None
        except (OSError, subprocess.SubprocessError):
            return None
