"""跨进程本地文件锁：POSIX `fcntl.flock` / Windows `msvcrt.locking`。

锁是 advisory 的，进程崩溃时由操作系统释放，不依赖手工删锁文件。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import IO

if sys.platform == "win32":  # pragma: no cover - 平台分支由两端分别覆盖
    import msvcrt
else:  # pragma: no cover
    import fcntl


class LockTimeout(TimeoutError):
    """在超时内没有拿到锁；调用方按「本次放弃写入」处理。"""


class FileLock:
    def __init__(self, path: Path, timeout_ms: int = 200, poll_ms: int = 10):
        self._path = Path(path)
        self._timeout = max(0, timeout_ms) / 1000.0
        self._poll = max(1, poll_ms) / 1000.0
        self._fh: IO[bytes] | None = None

    def __enter__(self) -> "FileLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self._path, "a+b")
        if sys.platform == "win32":
            fh.seek(0, 2)
            if fh.tell() == 0:
                fh.write(b"\0")
                fh.flush()
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                self._lock(fh)
                self._fh = fh
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    fh.close()
                    raise LockTimeout(
                        f"could not lock {self._path} within {int(self._timeout * 1000)}ms")
                time.sleep(self._poll)

    def __exit__(self, exc_type, exc, tb) -> None:
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            self._unlock(fh)
        finally:
            fh.close()

    @staticmethod
    def _lock(fh: IO[bytes]) -> None:
        if sys.platform == "win32":
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock(fh: IO[bytes]) -> None:
        if sys.platform == "win32":
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
