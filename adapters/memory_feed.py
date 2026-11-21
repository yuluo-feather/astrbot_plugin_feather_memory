"""共享文件契约的读写：租约 / 授权 / 事件 / 上下文 + TTL 清扫。

所有写入都是「临时文件 + os.replace」；context 写入在跨进程文件锁内做
「读 revision → 写临时文件 → replace」。
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from ..core.contracts import (
    AUTH_MAX_BYTES,
    CONTEXT_MAX_BYTES,
    EVENT_MAX_BYTES,
    EVENT_RETENTION_DAYS,
    LEASE_MAX_BYTES,
    Auth,
    ContractError,
    Lease,
    MemoryContext,
    ReadingEvent,
)
from ..core.timeutil import parse_ts
from .file_lock import FileLock, LockTimeout

WRITE_WRITTEN = "written"
WRITE_STALE = "stale"
WRITE_TIMEOUT = "timeout"
WRITE_TOO_LARGE = "too_large"
WRITE_ERROR = "error"


def _expired(parsed, now: datetime) -> bool:
    try:
        return now >= parse_ts(parsed.expires_at)
    except ValueError:
        return True


@dataclass(frozen=True, slots=True)
class FeedLayout:
    root: Path

    @classmethod
    def from_plugin_data_dir(cls, data_dir: Path) -> "FeedLayout":
        plugin_data = Path(data_dir).parent
        return cls(plugin_data / "_shared" / "feather_memory" / "v1")

    @property
    def lease_path(self) -> Path:
        return self.root / "lease.json"

    @property
    def state_lock_path(self) -> Path:
        return self.root / "state.lock"

    @property
    def auth_dir(self) -> Path:
        return self.root / "auth"

    @property
    def events_dir(self) -> Path:
        return self.root / "events"

    @property
    def context_dir(self) -> Path:
        return self.root / "context"

    def ensure(self) -> None:
        for directory in (self.root, self.auth_dir, self.events_dir, self.context_dir):
            directory.mkdir(parents=True, exist_ok=True)


class MemoryFeed:
    def __init__(self, layout: FeedLayout):
        self.layout = layout
        self.layout.ensure()

    # ---- generic io ----------------------------------------------------

    @staticmethod
    def _read_json(path: Path, max_bytes: int) -> dict:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            raise
        if size > max_bytes:
            raise ContractError(f"{path.name}: size {size} exceeds {max_bytes} bytes")
        raw = path.read_bytes()
        if not raw:
            raise ContractError(f"{path.name}: empty file")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError(f"{path.name}: invalid json: {exc}") from None
        if not isinstance(payload, dict):
            raise ContractError(f"{path.name}: payload must be an object")
        return payload

    @staticmethod
    def _write_json(path: Path, payload: dict, max_bytes: int) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        if len(data) > max_bytes:
            raise ContractError(f"{path.name}: payload {len(data)} bytes exceeds {max_bytes}")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
        try:
            with open(tmp, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    # ---- lease ---------------------------------------------------------

    def read_lease(self) -> Lease | None:
        try:
            return Lease.parse(self._read_json(self.layout.lease_path, LEASE_MAX_BYTES))
        except (OSError, ContractError):
            return None

    def write_lease(self, lease: Lease) -> None:
        self._write_json(self.layout.lease_path, lease.to_dict(), LEASE_MAX_BYTES)

    def delete_lease(self, instance_id: str) -> bool:
        lease = self.read_lease()
        if lease is None or lease.instance_id != instance_id:
            return False
        try:
            self.layout.lease_path.unlink()
        except FileNotFoundError:
            return False
        return True

    # ---- auth ----------------------------------------------------------

    def auth_path(self, user_key_hash: str) -> Path:
        return self.layout.auth_dir / f"{user_key_hash}.json"

    def read_auth(self, user_key_hash: str) -> Auth | None:
        try:
            return Auth.parse(self._read_json(self.auth_path(user_key_hash), AUTH_MAX_BYTES))
        except (OSError, ContractError):
            return None

    def write_auth(self, auth: Auth) -> None:
        self._write_json(self.auth_path(auth.user_key_hash), auth.to_dict(), AUTH_MAX_BYTES)

    def delete_auth(self, user_key_hash: str) -> bool:
        try:
            self.auth_path(user_key_hash).unlink()
        except FileNotFoundError:
            return False
        return True

    # ---- events --------------------------------------------------------

    def event_path(self, event_id: str) -> Path:
        return self.layout.events_dir / f"{event_id}.json"

    def iter_events(self) -> list[Path]:
        return sorted(path for path in self.layout.events_dir.iterdir()
                      if path.is_file() and path.suffix == ".json")

    def read_event(self, path: Path) -> ReadingEvent:
        return ReadingEvent.parse(self._read_json(path, EVENT_MAX_BYTES))

    def write_event(self, event: ReadingEvent) -> None:
        self._write_json(self.event_path(event.event_id), event.to_dict(), EVENT_MAX_BYTES)

    def delete_event(self, path: Path) -> bool:
        try:
            Path(path).unlink()
        except FileNotFoundError:
            return False
        return True

    def remove_events_for_user(self, user_key: str) -> int:
        removed = 0
        for path in self.iter_events():
            try:
                event = self.read_event(path)
            except (OSError, ContractError):
                continue
            if event.user_key == user_key and self.delete_event(path):
                removed += 1
        return removed

    def count_events_for_user(self, user_key: str) -> int:
        count = 0
        for path in self.iter_events():
            try:
                event = self.read_event(path)
            except (OSError, ContractError):
                continue
            if event.user_key == user_key:
                count += 1
        return count

    # ---- context -------------------------------------------------------

    def context_path(self, user_key_hash: str) -> Path:
        return self.layout.context_dir / f"{user_key_hash}.json"

    def read_context(self, user_key_hash: str) -> MemoryContext | None:
        try:
            return MemoryContext.parse(
                self._read_json(self.context_path(user_key_hash), CONTEXT_MAX_BYTES))
        except (OSError, ContractError):
            return None

    def delete_context(self, user_key_hash: str, timeout_ms: int = 1000) -> bool:
        """在 context 锁内删除，避免与并发重建交错后把旧内容写回来。

        返回 True 表示「删除后文件不存在」（原本就不存在也算成功）。
        """
        path = self.context_path(user_key_hash)
        lock_path = self.layout.context_dir / f"{user_key_hash}.lock"
        try:
            with FileLock(lock_path, timeout_ms=timeout_ms):
                try:
                    path.unlink()
                except FileNotFoundError:
                    return True
                except OSError:
                    return False
                return True
        except (LockTimeout, OSError):
            return False

    def delete_context_if(self, user_key_hash: str,
                          guard: Callable[[], bool],
                          timeout_ms: int = 1000) -> str:
        """锁内复查 guard 后再删；guard 失败返回 skipped，不碰文件。"""
        path = self.context_path(user_key_hash)
        lock_path = self.layout.context_dir / f"{user_key_hash}.lock"
        try:
            with FileLock(lock_path, timeout_ms=timeout_ms):
                if not guard():
                    return "skipped"
                try:
                    path.unlink()
                except FileNotFoundError:
                    return "deleted"
                except OSError:
                    return "error"
                return "deleted"
        except (LockTimeout, OSError):
            return "error"

    def state_lock(self, timeout_ms: int = 2000) -> FileLock:
        """跨进程状态转换锁；锁序固定 state.lock → context.lock。"""
        return FileLock(self.layout.state_lock_path, timeout_ms=timeout_ms)

    def write_context(self, user_key_hash: str, context: MemoryContext,
                      timeout_ms: int = 200,
                      guard: Callable[[], bool] | None = None) -> str:
        target = self.context_path(user_key_hash)
        lock_path = self.layout.context_dir / f"{user_key_hash}.lock"
        try:
            with FileLock(lock_path, timeout_ms=timeout_ms):
                try:
                    existing = MemoryContext.parse(
                        self._read_json(target, CONTEXT_MAX_BYTES))
                except (OSError, ContractError):
                    existing = None
                if existing is not None and existing.revision > context.revision:
                    return WRITE_STALE
                if guard is not None and not guard():
                    return WRITE_STALE
                try:
                    self._write_json(target, context.to_dict(), CONTEXT_MAX_BYTES)
                except ContractError:
                    return WRITE_TOO_LARGE
                except OSError:
                    return WRITE_ERROR
                return WRITE_WRITTEN
        except LockTimeout:
            return WRITE_TIMEOUT
        except OSError:
            return WRITE_ERROR

    # ---- cleanup -------------------------------------------------------

    def cleanup(self, now: datetime) -> dict[str, int]:
        removed = {"events": 0, "auth": 0, "context": 0, "lease": 0}
        event_cutoff = (now - timedelta(days=EVENT_RETENTION_DAYS)).timestamp()
        for path in self.iter_events():
            try:
                if path.stat().st_mtime < event_cutoff:
                    path.unlink()
                    removed["events"] += 1
            except OSError:
                continue
        for directory, parser, key in (
            (self.layout.auth_dir, Auth.parse, "auth"),
            (self.layout.context_dir, MemoryContext.parse, "context"),
        ):
            for path in directory.glob("*.json"):
                try:
                    before = path.stat()
                    payload = self._read_json(
                        path, AUTH_MAX_BYTES if key == "auth" else CONTEXT_MAX_BYTES)
                    parsed = parser(payload)
                except (OSError, ContractError):
                    continue
                if not _expired(parsed, now):
                    continue
                try:
                    after = path.stat()
                except OSError:
                    continue
                if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                    continue  # 读取后被新文件替换：不删新文件
                try:
                    path.unlink()
                    removed[key] += 1
                except OSError:
                    continue
        lease_path = self.layout.lease_path
        try:
            before = lease_path.stat()
            lease = self.read_lease()
            stale_after = None
            if lease is not None:
                try:
                    stale_after = parse_ts(lease.expires_at) + timedelta(days=1)
                except ValueError:
                    stale_after = None
            after = lease_path.stat()
            if (stale_after is not None and now > stale_after
                    and (before.st_mtime_ns, before.st_size)
                    == (after.st_mtime_ns, after.st_size)):
                lease_path.unlink()
                removed["lease"] += 1
        except (OSError, ValueError):
            pass
        return removed
