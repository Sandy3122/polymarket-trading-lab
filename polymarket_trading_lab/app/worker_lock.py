"""Single-worker guard.

Two paper workers on one database both react to the same book and each
fills/sells the same position, producing double sales and a wrong balance.
An exclusive, non-blocking file lock makes the second worker refuse to start.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows: no guard available
    fcntl = None  # type: ignore[assignment]


class WorkerAlreadyRunning(RuntimeError):
    pass


class WorkerLock:
    def __init__(self, database_url: str) -> None:
        digest = hashlib.sha1(database_url.encode()).hexdigest()[:10]
        self.path = Path(tempfile.gettempdir()) / f"polymarket_paper_worker_{digest}.lock"
        self._fd: int | None = None

    def acquire(self) -> None:
        if fcntl is None:
            return
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            owner = os.read(fd, 32).decode(errors="ignore").strip() or "unknown"
            os.close(fd)
            raise WorkerAlreadyRunning(
                f"another paper worker is already running (pid {owner}). Stop it first "
                "(e.g. Ctrl+C the `polymarket-lab paper-worker` terminal), or use only the dashboard's Start button."
            ) from None
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        self._fd = fd

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)  # closing the descriptor drops the flock
            self._fd = None
