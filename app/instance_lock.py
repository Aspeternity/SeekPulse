"""Linux single-database owner lock shared by legacy and opt-in V1.1 runners.

This protects upgraded instances only; older deployed images do not acquire
it, so a later production handoff still requires explicit operator proof.
"""

from __future__ import annotations

import fcntl
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def database_owner_lock(path: Path) -> Iterator[None]:
    db = Path(os.path.realpath(os.fspath(path)))
    lock = db.with_name(db.name + ".owner.lock")
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RuntimeError("unsafe_instance_lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("seekpulse_instance_already_running") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
