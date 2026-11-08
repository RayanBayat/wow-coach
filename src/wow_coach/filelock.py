"""A tiny lock file, so two wow-coach programs never rewrite the same file at once.

The coach window, ``wow-coach ask`` and the background importer can all touch the same file in
the data folder. ``locked(path)`` holds ``<file>.lock`` while the ``with`` block runs.
"""

import contextlib
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final

LOCK_WAIT_SECONDS: Final = 2.0
LOCK_STALE_SECONDS: Final = 30.0
LOCK_POLL_SECONDS: Final = 0.05


def _lock_is_stale(lock: Path) -> bool:
    try:
        return time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS
    except OSError:
        return False


@contextlib.contextmanager
def locked(path: Path) -> Iterator[None]:
    """Hold ``<file>.lock`` (made with O_EXCL, so only one program gets it) while running.

    Waits about 2 seconds, takes over a lock older than 30 seconds (a crashed program), and
    always removes its own lock. If the lock can't be had in time we go on without it: a
    rare lost update of a small list is better than blocking the coach.
    """
    lock = path.with_name(path.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    held = False
    while not held:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
            held = True
        except FileExistsError:
            if _lock_is_stale(lock):
                with contextlib.suppress(OSError):
                    lock.unlink()
            elif time.monotonic() > deadline:
                break
            else:
                time.sleep(LOCK_POLL_SECONDS)
    try:
        yield
    finally:
        if held:
            with contextlib.suppress(OSError):
                lock.unlink()
