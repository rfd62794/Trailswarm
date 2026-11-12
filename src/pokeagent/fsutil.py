"""Windows-safe atomic file replace shared by every writer that another process may be reading.

os.replace raises PermissionError (winerror 5/32/33) while a reader or sibling run holds the target open,
and a shared ``<name>.tmp`` raced between two runs raises FileNotFoundError. Use unique temp names and
retry briefly; a persistent failure still surfaces to the caller.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

ATTEMPTS = 8
BASE_DELAY = 0.01  # 10ms doubling, capped: ~1.3s worst case


def unique_tmp(path) -> Path:
    path = Path(path)
    return path.with_name(f"{path.name}.{os.getpid()}.tmp")


def replace_retry(src, dst, attempts: int = ATTEMPTS, base_delay: float = BASE_DELAY) -> None:
    """os.replace(src, dst) retried on PermissionError; the last error is re-raised."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(min(base_delay * 2 ** i, 0.25))


def atomic_write_text(path, text: str, encoding: str = "utf-8", **kw) -> None:
    """Write via a per-process temp sibling then replace_retry; the temp is removed on failure."""
    path = Path(path)
    tmp = unique_tmp(path)
    try:
        tmp.write_text(text, encoding=encoding)
        replace_retry(tmp, path, **kw)
    finally:
        tmp.unlink(missing_ok=True)


def where(exc: BaseException) -> str:
    """One-line ' @ file:line in func [file=...]' for a swallowed exception, so a bare PermissionError is diagnosable."""
    tb = exc.__traceback__
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    out = ""
    if tb is not None:
        out = f" @ {Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno} in {tb.tb_frame.f_code.co_name}"
    fn = getattr(exc, "filename", None)
    if fn:
        out += f" [file={fn}" + (f" -> {exc.filename2}" if getattr(exc, "filename2", None) else "") + "]"
    return out
