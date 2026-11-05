from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import time
import uuid

from pokeagent.qmodels import atomic_json


def process_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == 'nt':
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            status = ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(status))) and status.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def registry_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + '.lock', 'a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        deadline = time.monotonic() + 5
        while True:
            stream.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Learner registry is locked')
                time.sleep(0.02)
        try:
            yield path
        finally:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def register_worker(path, port, info, max_workers=6):
    with registry_lock(path) as target:
        data = json.loads(target.read_text()) if target.exists() else {}
        previous = data.get(str(port))
        if previous and process_alive(previous.get('pid')):
            raise FileExistsError(f'Seat {port} already has a live owner')
        if sum(process_alive(entry.get('pid')) for entry in data.values()) >= max_workers:
            raise RuntimeError(f'Learner cap reached: {max_workers}')
        token = uuid.uuid4().hex
        data[str(port)] = dict(info, pid=os.getpid(), token=token, registered_ns=time.time_ns())
        atomic_json(target, data)
        return token


def unregister_worker(path, port, token):
    with registry_lock(path) as target:
        if not target.exists():
            return
        data = json.loads(target.read_text())
        if data.get(str(port), {}).get('token') == token:
            data.pop(str(port))
            atomic_json(target, data)
