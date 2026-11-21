"""羽忆业务编排：服务租约、事件消费、context 重建、开关状态转换。

所有方法都是同步的，由宿主侧用 `asyncio.to_thread` 调用；
`core/` 与 `app/` 都不 import astrbot。
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..adapters.file_lock import LockTimeout
from ..adapters.memory_feed import (
    WRITE_ERROR,
    WRITE_TIMEOUT,
    WRITE_TOO_LARGE,
    WRITE_WRITTEN,
    MemoryFeed,
)
from ..adapters.sqlite_store import SqliteStore
from ..core.contracts import (
    ALLOWED_EVENT_KINDS,
    AUTH_TTL_DAYS,
    CONTEXT_TTL_DAYS,
    LEASE_REFRESH_SECONDS,
    LEASE_TTL_SECONDS,
    SOURCE,
    Auth,
    ContractError,
    Lease,
    MemoryContext,
    MemoryItem,
    ReadingEvent,
)
from ..core.export import build_export
from ..core.identity import user_key_hash
from ..core.ids import new_ulid
from ..core.merge import EXPLICIT_LIMIT, ExplicitEntry, TopicStat, compose_context
from ..core.timeutil import add_days, add_seconds, format_ts, now_utc, parse_ts

MAX_MEMORY_CHARS = 160
CLEAR_CONFIRM_SECONDS = 60
CLEANUP_INTERVAL_SECONDS = 3600
AUTH_REFRESH_INTERVAL_SECONDS = 86400
EXPORT_KEEP_COUNT = 5

_CATEGORY_PREFIXES = (
    ("偏好", "preference"),
    ("背景", "background"),
    ("目标", "goal"),
)
_PREFIX_SEPARATORS = " ：:，,"


def _split_category_prefix(text: str) -> tuple[str | None, str]:
    """只有前缀后紧跟分隔符才算分类；否则整段都是内容。"""
    for prefix, category in _CATEGORY_PREFIXES:
        if not text.startswith(prefix) or len(text) == len(prefix):
            continue
        if text[len(prefix)] not in _PREFIX_SEPARATORS:
            continue
        rest = text[len(prefix) + 1:].lstrip(" ：:，,")
        return category, rest
    return None, text


def parse_memory_input(raw: str) -> tuple[str, str]:
    text = " ".join((raw or "").split())
    if not text:
        return "preference", ""
    category, content = _split_category_prefix(text)
    return (category or "preference"), content


def normalize_content(content: str) -> str:
    return " ".join(content.split())


class MemoryService:
    def __init__(self, store: SqliteStore, feed: MemoryFeed, *,
                 global_enabled: bool, version: str,
                 clock: Callable[[], datetime] = now_utc,
                 log: logging.Logger | None = None,
                 instance_id: str | None = None,
                 min_topic_count: int = 1):
        self.store = store
        self.feed = feed
        self.global_enabled = global_enabled
        self.version = version
        self.min_topic_count = 2 if int(min_topic_count) >= 2 else 1
        self.clock = clock
        self.log = log or logging.getLogger("feather_memory")
        self.instance_id = instance_id or new_ulid(clock())
        self.started_at = format_ts(clock())
        self._state = "new"
        self._lifecycle_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._transition_hook: Callable[[], None] | None = None
        self._last_lease: datetime | None = None
        self._last_cleanup: datetime | None = None
        self._last_auth_refresh: datetime | None = None
        self._clear_pending: dict[str, datetime] = {}

    @property
    def source(self) -> str:
        return f"{SOURCE}/{self.version}"

    @staticmethod
    def _tag(user_key: str) -> str:
        """日志只留身份摘要前 8 位，不打完整 uid。"""
        return user_key_hash(user_key)[:8]

    @contextmanager
    def _state_transition(self):
        """进程内 RLock + 跨进程 state.lock；锁序 state → context。"""
        with self._state_lock:
            with self.feed.state_lock():
                if self._transition_hook is not None:
                    self._transition_hook()
                yield

    # ---- lifecycle -----------------------------------------------------

    def startup(self) -> None:
        self.store.initialize()
        now = self.clock()
        if self.global_enabled:
            self._refresh_lease(now)
            self.consume_pending(now)
            self.rebuild_all_contexts(now)
            self.refresh_auth_all(now)
        self.cleanup(now)
        self._state = "started"
        self.log.info(
            "启动完成：全局=%s，用户=%d，待处理事件=%d，租约=%s，实例=%s",
            "开" if self.global_enabled else "关",
            len(self.store.all_users()),
            len(self.feed.iter_events()),
            "有效" if self.global_enabled and self._lease_ok(now) else "无",
            self.instance_id[:8],
        )

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            self._state = "stopped"
            try:
                self.feed.delete_lease(self.instance_id)
            except (OSError, LockTimeout) as exc:
                self.log.warning("租约删除失败：%s", exc)

    def tick(self) -> None:
        if self._state != "started":
            return
        now = self.clock()
        if self.global_enabled:
            if (self._last_lease is None
                    or (now - self._last_lease).total_seconds() >= LEASE_REFRESH_SECONDS):
                self._refresh_lease(now)
            self.consume_pending(now)
            if (self._last_auth_refresh is None
                    or (now - self._last_auth_refresh).total_seconds()
                    >= AUTH_REFRESH_INTERVAL_SECONDS):
                self.refresh_auth_all(now)
        if (self._last_cleanup is None
                or (now - self._last_cleanup).total_seconds() >= CLEANUP_INTERVAL_SECONDS):
            self.cleanup(now)

    # ---- lease ---------------------------------------------------------

    def _refresh_lease(self, now: datetime) -> None:
        lease = Lease(
            instance_id=self.instance_id,
            started_at=self.started_at,
            refreshed_at=format_ts(now),
            expires_at=format_ts(add_seconds(now, LEASE_TTL_SECONDS)),
            source=self.source,
        )
        with self._lifecycle_lock:
            # 关闭与刷新互斥：已经进入线程池的 tick 不得在 shutdown 删租约后写回。
            if self._state == "stopped":
                return
            try:
                self.feed.write_lease(lease)
            except (OSError, ContractError, LockTimeout) as exc:
                self.log.warning("羽忆租约写入失败：%s", exc)
                return
        self._last_lease = now

    def _lease_ok(self, now: datetime) -> bool:
        lease = self.feed.read_lease()
        return lease is not None and lease.is_valid(now)

    # ---- event consumption --------------------------------------------

    def consume_pending(self, now: datetime | None = None) -> int:
        now = now or self.clock()
        if not self._lease_ok(now):
            return 0
        affected: set[str] = set()
        consumed = 0
        for path in self.feed.iter_events():
            try:
                event = self.feed.read_event(path)
            except ContractError as exc:
                self.log.warning("丢弃损坏事件 %s：%s", path.name, exc)
                self._delete_event(path)
                continue
            except OSError as exc:
                self.log.warning("读取事件 %s 失败：%s", path.name, exc)
                continue

            event = self._check_event(event, now)
            if event is None:
                self._delete_event(path)
                continue

            try:
                result = self.store.insert_reading_guarded(event, now)
            except Exception as exc:  # SQLite 故障：保留文件，下次重试
                self.log.error("写入事件 %s 失败：%s", event.event_id, exc)
                continue

            if result == "stale":
                self.log.info("丢弃事件 %s：用户已关闭或在清空之前", event.event_id)
                self._delete_event(path)
                continue
            if result == "inserted":
                consumed += 1
                affected.add(event.user_key)
                try:
                    self.store.purge_readings(event.user_key, now)
                except Exception as exc:
                    self.log.warning("清理旧占卜记录失败：%s", exc)
            else:
                self.log.info("重复事件 %s：已入库，直接删除文件", event.event_id)
            self._delete_event(path)

        if consumed:
            self.log.info("消费事件 %d 条，涉及用户 %d 个", consumed, len(affected))
        for user_key in sorted(affected):
            self.rebuild_context(user_key, now)
        return consumed

    def _check_event(self, event: ReadingEvent, now: datetime) -> ReadingEvent | None:
        if event.conversation_scope != "private":
            self.log.info("丢弃非私聊事件 %s", event.event_id)
            return None
        if event.kind not in ALLOWED_EVENT_KINDS:
            self.log.info("丢弃不支持的事件类型 %s：%s", event.event_id, event.kind)
            return None
        user = self.store.get_user(event.user_key)
        if user is None:
            self.log.info("丢弃事件 %s：用户无记录", event.event_id)
            return None
        if not user["enabled"]:
            self.log.info("丢弃事件 %s：用户总开关关闭", event.event_id)
            return None
        if not user["auto_history"]:
            self.log.info("丢弃事件 %s：自动历史关闭（数据库）", event.event_id)
            return None
        digest = user_key_hash(event.user_key)
        auth = self.feed.read_auth(digest)
        if auth is None:
            self.log.info("丢弃事件 %s：授权缺失或损坏", event.event_id)
            return None
        if not auth.is_valid(now):
            self.log.info("丢弃事件 %s：授权已过期", event.event_id)
            return None
        if not auth.auto_history:
            self.log.info("丢弃事件 %s：自动历史关闭（授权）", event.event_id)
            return None
        if auth.user_key_hash != digest:
            self.log.info("丢弃事件 %s：授权身份不匹配", event.event_id)
            return None
        for cutoff in (user.get("cleared_at") or "", user.get("disabled_at") or ""):
            if not cutoff:
                continue
            try:
                if parse_ts(event.created_at) <= parse_ts(cutoff):
                    self.log.info("丢弃事件 %s：早于清空或停用时间", event.event_id)
                    return None
            except ValueError:
                self.log.info("丢弃事件 %s：清空/停用时间不可解析", event.event_id)
                return None
        if not user["store_topic"] and event.topic_key:
            return replace(event, topic_key="")
        return event

    def _delete_event(self, path) -> None:
        try:
            self.feed.delete_event(path)
        except OSError as exc:
            self.log.warning("删除事件文件 %s 失败：%s", path.name, exc)

    # ---- context -------------------------------------------------------

    def _drop_context(self, user_key: str, now: datetime) -> bool:
        """删除 context；删不掉就置 dirty，交给下一次重建 / 启动重试。"""
        if self.feed.delete_context(user_key_hash(user_key)):
            return True
        self.store.set_context_dirty(user_key, True, now)
        self.log.warning("context 删除失败（已置 dirty）：user=%s", user_key)
        return False

    def _drop_context_guarded(self, user_key: str, now: datetime,
                              guard: Callable[[], bool]) -> str:
        """锁内复查 guard 后再删；guard 失败时不动新 context。"""
        status = self.feed.delete_context_if(user_key_hash(user_key), guard)
        if status in ("deleted", "skipped"):
            return status
        self.store.set_context_dirty(user_key, True, now)
        self.log.warning("context 删除失败（已置 dirty）：user=%s", user_key)
        return "error"

    def rebuild_context(self, user_key: str, now: datetime | None = None) -> str:
        now = now or self.clock()
        digest = user_key_hash(user_key)
        user = self.store.get_user(user_key)
        if user is None:
            return "missing"
        snapshot = int(user["context_revision"])
        if not user["enabled"]:
            def still_disabled() -> bool:
                fresh = self.store.get_user(user_key)
                return bool(fresh and not fresh["enabled"]
                            and int(fresh["context_revision"]) == snapshot)

            status = self._drop_context_guarded(user_key, now, still_disabled)
            if status == "skipped":
                return "superseded"
            if status == "deleted":
                if not self.store.clear_dirty_if_revision(
                        user_key, snapshot, now, require_enabled=False):
                    self.store.set_context_dirty(user_key, True, now)
                    return "superseded"
            return "disabled"

        explicit = self.store.list_memories(user_key, now, limit=EXPLICIT_LIMIT)
        stats = self.store.topic_stats(user_key, now)
        suppressed = self.store.suppressed_topics(user_key)
        stats = [topic for topic in stats if topic.topic_key not in suppressed
                 and topic.count >= self.min_topic_count]
        items, text = compose_context(explicit, stats)

        if not items:
            def still_empty() -> bool:
                fresh = self.store.get_user(user_key)
                return bool(fresh and fresh["enabled"]
                            and int(fresh["context_revision"]) == snapshot)

            status = self._drop_context_guarded(user_key, now, still_empty)
            if status == "skipped":
                return "superseded"
            if status == "deleted":
                if not self.store.clear_dirty_if_revision(user_key, snapshot, now):
                    self.store.set_context_dirty(user_key, True, now)
                    return "superseded"
            return "empty"

        context = MemoryContext(
            revision=int(user["context_revision"]),
            generated_at=format_ts(now),
            expires_at=format_ts(add_days(now, CONTEXT_TTL_DAYS)),
            source=self.source,
            scope="private",
            items=tuple(MemoryItem(kind=item.kind, text=item.text) for item in items),
            text=text,
        )

        def still_current() -> bool:
            # 锁内复查：关闭 / 清空 / 新数据变更后，旧快照不得把 context 写回来。
            fresh = self.store.get_user(user_key)
            return bool(fresh and fresh["enabled"]
                        and int(fresh["context_revision"]) == context.revision)

        try:
            result = self.feed.write_context(digest, context, guard=still_current)
        except OSError as exc:
            self.log.warning("context 写入异常：%s", exc)
            result = WRITE_ERROR
        if result == WRITE_WRITTEN:
            if self.store.clear_dirty_if_revision(user_key, context.revision, now):
                if user.get("context_dirty"):
                    self.log.info("重建 dirty context(%s) revision=%d",
                                  self._tag(user_key), context.revision)
            else:
                result = "superseded"
                self.log.info("context 写入被新 revision 超越(%s) revision=%d",
                              self._tag(user_key), context.revision)
        elif result in (WRITE_TIMEOUT, WRITE_ERROR, WRITE_TOO_LARGE):
            self.store.set_context_dirty(user_key, True, now)
            self.log.warning("context 写入失败（%s）：user=%s", result, user_key)
        return result

    def rebuild_all_contexts(self, now: datetime | None = None) -> None:
        now = now or self.clock()
        seen: set[str] = set()
        for user in self.store.all_users(enabled_only=True) + self.store.dirty_users():
            user_key = user["user_key"]
            if user_key in seen:
                continue
            seen.add(user_key)
            self.rebuild_context(user_key, now)

    # ---- auth ----------------------------------------------------------

    def refresh_auth(self, user_key: str, now: datetime | None = None) -> bool:
        with self._state_transition():
            return self._refresh_auth_impl(user_key, now or self.clock())

    def _refresh_auth_impl(self, user_key: str, now: datetime) -> bool:
        # 调用方必须已持有状态转换锁。
        digest = user_key_hash(user_key)
        user = self.store.get_user(user_key)
        if user is None:
            return False
        if not user["enabled"]:
            self.feed.delete_auth(digest)
            return False
        auth = Auth(
            user_key_hash=digest,
            generated_at=format_ts(now),
            expires_at=format_ts(add_days(now, AUTH_TTL_DAYS)),
            auto_history=bool(user["auto_history"]),
            store_topic=bool(user["store_topic"]),
            source=self.source,
        )
        try:
            self.feed.write_auth(auth)
        except (OSError, ContractError, LockTimeout) as exc:
            self.log.warning("授权文件写入失败：%s", exc)
            return False
        return True

    def refresh_auth_all(self, now: datetime | None = None) -> None:
        now = now or self.clock()
        for user in self.store.all_users(enabled_only=True):
            self.refresh_auth(user["user_key"], now)
        self._last_auth_refresh = now

    # ---- cleanup -------------------------------------------------------

    def cleanup(self, now: datetime | None = None) -> None:
        now = now or self.clock()
        try:
            removed = self.feed.cleanup(now)
            if any(removed.values()):
                self.log.info("清扫：%s", removed)
        except Exception as exc:
            self.log.warning("共享目录清扫失败：%s", exc)
        for user in self.store.all_users():
            try:
                self.store.purge_readings(user["user_key"], now)
            except Exception as exc:
                self.log.warning("清理占卜记录失败：%s", exc)
            if not user["enabled"]:
                # 关闭时的共享文件清理若失败，由每小时维护重试。
                try:
                    if not self.feed.delete_auth(user_key_hash(user["user_key"])):
                        self.log.warning("重试删除授权失败：user=%s",
                                         self._tag(user["user_key"]))
                except OSError as exc:
                    self.log.warning("重试删除授权失败：%s", exc)
                try:
                    self.feed.remove_events_for_user(user["user_key"])
                except OSError as exc:
                    self.log.warning("重试清理事件失败：%s", exc)
        if self.global_enabled:
            for user in self.store.dirty_users():
                self.rebuild_context(user["user_key"], now)
        self._last_cleanup = now
        self.log.info("统计：%s", self.stats())

    def stats(self) -> dict:
        """只读统计，不设上限、不影响行为。"""
        users = self.store.all_users()
        return {
            "users": len(users),
            "enabled": sum(1 for user in users if user["enabled"]),
            "dirty": len(self.store.dirty_users()),
            "memories": self.store.count_memories_all(),
            "readings": self.store.count_readings_all(),
            **{f"files_{key}": value for key, value in self.feed.counts().items()},
        }

    # ---- state transitions --------------------------------------------

    def user_state(self, user_key: str) -> dict | None:
        return self.store.get_user(user_key)

    def enable(self, user_key: str) -> dict:
        """一键开启：总开关 + 自动历史 + 主题记录，只写一次授权。"""
        with self._state_transition():
            now = self.clock()
            user = self.store.ensure_user(user_key, now)
            self.store.set_user_flags(
                user_key, now, enabled=1, auto_history=1, store_topic=1)
            auth_ok = self._refresh_auth_impl(user_key, now)
            self.rebuild_context(user_key, now)
            self.log.info("开关：enable-all(%s)", self._tag(user_key))
            result = dict(self.store.get_user(user_key) or user)
            result["auth_ok"] = auth_ok
            return result

    def enable_auto(self, user_key: str) -> str:
        with self._state_transition():
            now = self.clock()
            code = self.store.set_flag_if_enabled(user_key, now, auto_history=1)
            if code != "ok":
                return code
            if not self._refresh_auth_impl(user_key, now):
                return "auth_failed"
            self.rebuild_context(user_key, now)
            self.log.info("开关：auto(%s)=1", self._tag(user_key))
            return "ok"

    def enable_topic(self, user_key: str) -> str:
        with self._state_transition():
            now = self.clock()
            code = self.store.set_flag_if_enabled(
                user_key, now, store_topic=1, require_auto=True)
            if code != "ok":
                return code
            if not self._refresh_auth_impl(user_key, now):
                return "auth_failed"
            self.rebuild_context(user_key, now)
            self.log.info("开关：topic(%s)=1", self._tag(user_key))
            return "ok"

    def disable_auto(self, user_key: str) -> str:
        """只关自动历史；主题记录与已存数据不动。"""
        with self._state_transition():
            now = self.clock()
            user = self.store.get_user(user_key)
            if user is None:
                return "missing"
            self.store.set_user_flags(user_key, now, auto_history=0)
            auth_ok = True
            if user["enabled"]:
                auth_ok = self._refresh_auth_impl(user_key, now)
            self.log.info("开关：auto(%s)=0", self._tag(user_key))
            return "ok" if auth_ok else "auth_failed"

    def disable_topic(self, user_key: str) -> str:
        """只关主题记录；自动历史与已存数据不动。"""
        with self._state_transition():
            now = self.clock()
            user = self.store.get_user(user_key)
            if user is None:
                return "missing"
            self.store.set_user_flags(user_key, now, store_topic=0)
            auth_ok = True
            if user["enabled"]:
                auth_ok = self._refresh_auth_impl(user_key, now)
            self.log.info("开关：topic(%s)=0", self._tag(user_key))
            return "ok" if auth_ok else "auth_failed"

    def _cleanup_user_files(self, user_key: str,
                            now: datetime) -> tuple[int, list[str]]:
        """删除 auth / context / 事件；每步独立失败，返回未完成项。"""
        failures: list[str] = []
        digest = user_key_hash(user_key)
        auth_ok = False
        for _ in range(2):
            try:
                if self.feed.delete_auth(digest):
                    auth_ok = True
                    break
            except OSError as exc:
                self.log.warning("删除授权失败：%s", exc)
        if not auth_ok:
            failures.append("auth")

        context_ok = False
        for _ in range(2):
            if self._drop_context(user_key, now):
                context_ok = True
                break
        if not context_ok:
            failures.append("context")

        removed = 0
        try:
            removed = self.feed.remove_events_for_user(user_key)
        except OSError as exc:
            self.log.warning("清理待处理事件失败：%s", exc)
            failures.append("events")

        if failures:
            self.log.warning("共享文件清理未完成：%s user=%s",
                             failures, self._tag(user_key))
        return removed, failures

    def _remove_export_row(self, user_key: str, name: str) -> None:
        try:
            self.store.remove_export(user_key, name)
        except Exception as exc:
            self.log.warning("删除导出索引失败：%s", exc)

    def _delete_export_file(self, directory: Path, name: str) -> bool:
        """删文件成功或本就不存在返回 True；IO 失败返回 False 并保留索引行。"""
        if Path(name).name != name:
            return True
        try:
            (directory / name).unlink()
        except FileNotFoundError:
            return True
        except OSError as exc:
            self.log.warning("删除导出文件失败：%s", exc)
            return False
        return True

    def _cleanup_exports(self, user_key: str, failures: list[str]) -> None:
        """清空时一并删除该用户导出到 exports/ 的副本。"""
        try:
            names = self.store.list_exports(user_key)
        except Exception as exc:
            self.log.warning("导出索引读取失败：%s", exc)
            failures.append("exports")
            return
        directory = self.store.path.parent / "exports"
        failed = False
        for name in names:
            if self._delete_export_file(directory, name):
                self._remove_export_row(user_key, name)
            else:
                failed = True
        if failed:
            failures.append("exports")

    def disable(self, user_key: str) -> tuple[int, list[str]]:
        with self._state_transition():
            now = self.clock()
            self.store.ensure_user(user_key, now)
            self.store.disable_user(user_key, now)
            removed, failures = self._cleanup_user_files(user_key, now)
            self.log.info("开关：disable(%s)，清理事件 %d 条",
                          self._tag(user_key), removed)
            return removed, failures

    def clear(self, user_key: str) -> tuple[int, list[str]]:
        with self._state_transition():
            now = self.clock()
            self.store.ensure_user(user_key, now)
            self.store.clear_user_data(user_key, now)
            removed, failures = self._cleanup_user_files(user_key, now)
            self._cleanup_exports(user_key, failures)
            self._clear_pending.pop(user_key, None)
            self.log.info("开关：clear(%s)，清理事件 %d 条",
                          self._tag(user_key), removed)
            return removed, failures

    def request_clear(self, user_key: str) -> None:
        self._clear_pending[user_key] = self.clock()

    def confirm_clear(self, user_key: str) -> list[str] | None:
        started = self._clear_pending.pop(user_key, None)
        if started is None:
            return None
        if (self.clock() - started).total_seconds() > CLEAR_CONFIRM_SECONDS:
            return None
        _, failures = self.clear(user_key)
        return failures

    def remember(self, user_key: str, raw: str) -> tuple[int, bool]:
        category, content = parse_memory_input(raw)
        if not content:
            return 0, False
        truncated = len(content) > MAX_MEMORY_CHARS
        content = content[:MAX_MEMORY_CHARS]
        with self._state_transition():
            now = self.clock()
            user = self.store.ensure_user(user_key, now)
            if not user["enabled"]:
                self.store.set_user_flags(user_key, now, enabled=1)
            self._refresh_auth_impl(user_key, now)
            memory_id = self.store.save_memory(
                user_key, category, content, normalize_content(content), now)
            self.rebuild_context(user_key, now)
            self.log.info("记忆：save(%s) #%d", self._tag(user_key), memory_id)
            return memory_id, truncated

    def forget(self, user_key: str, memory_id: int) -> bool:
        with self._state_transition():
            now = self.clock()
            if not self.store.remove_memory(user_key, memory_id, now):
                return False
            self._refresh_auth_impl(user_key, now)
            self._drop_context(user_key, now)
            self.rebuild_context(user_key, now)
            self.log.info("记忆：forget(%s) #%d", self._tag(user_key), memory_id)
            return True

    def update_memory(self, user_key: str, memory_id: int,
                      raw: str) -> tuple[str, bool]:
        text = " ".join((raw or "").split())
        category_hint, text = _split_category_prefix(text)
        if not text:
            return "empty", False
        truncated = len(text) > MAX_MEMORY_CHARS
        text = text[:MAX_MEMORY_CHARS]
        with self._state_transition():
            now = self.clock()
            old = self.store.get_memory(user_key, memory_id)
            if old is None:
                return "missing", False
            category = category_hint or old["category"]
            code = self.store.update_memory(
                user_key, memory_id, category, text,
                normalize_content(text), now)
            if code != "ok":
                return code, False
            self._drop_context(user_key, now)
            self.rebuild_context(user_key, now)
            self.log.info("记忆：update(%s) #%d", self._tag(user_key), memory_id)
            return "ok", truncated

    # ---- read models ---------------------------------------------------

    def list_display(self, user_key: str) -> tuple[list[ExplicitEntry], list[TopicStat]]:
        now = self.clock()
        if self.store.get_user(user_key) is None:
            return [], []
        memories = self.store.list_memories(user_key, now, limit=10)
        stats = self.store.topic_stats(user_key, now)
        suppressed = self.store.suppressed_topics(user_key)
        return memories, [topic for topic in stats if topic.topic_key not in suppressed]

    def export_data(self, user_key: str) -> tuple[Path, dict] | None:
        """把本人数据写到 plugin_data/feather_memory/exports/；无记录返回 None。"""
        now = self.clock()
        with self._state_transition():
            user = self.store.get_user(user_key)
            if user is None:
                return None
            memories = self.store.list_memories(user_key, now, limit=None)
            suppressed = self.store.suppressed_topics(user_key)
            topics = [topic for topic in self.store.topic_stats(user_key, now)
                      if topic.topic_key not in suppressed]
            payload = build_export(
                exported_at=format_ts(now),
                plugin_version=self.version,
                enabled=bool(user["enabled"]),
                auto_history=bool(user["auto_history"]),
                store_topic=bool(user["store_topic"]),
                memories=memories,
                topics=topics,
            )
            directory = self.store.path.parent / "exports"
            directory.mkdir(parents=True, exist_ok=True)
            filename = f"{secrets.token_hex(6)}-{now.strftime('%Y%m%dT%H%M%SZ')}.json"
            path = directory / filename
            data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
            try:
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, path)
                self.store.add_export(user_key, filename, now)
            except Exception:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
            self._trim_exports(user_key, directory)
        self.log.info("导出：user=%s 记忆=%d 主题=%d",
                      self._tag(user_key), len(memories), len(topics))
        return path, payload

    def _trim_exports(self, user_key: str, directory: Path) -> None:
        """每个用户只保留最近 EXPORT_KEEP_COUNT 份导出；失败的行留待下次重试。"""
        try:
            stale = self.store.stale_exports(user_key, EXPORT_KEEP_COUNT)
        except Exception as exc:
            self.log.warning("导出轮转失败：%s", exc)
            return
        for name in stale:
            if self._delete_export_file(directory, name):
                self._remove_export_row(user_key, name)

    def status(self, user_key: str) -> dict:
        now = self.clock()
        digest = user_key_hash(user_key)
        lease = self.feed.read_lease()
        user = self.store.get_user(user_key)
        auth = self.feed.read_auth(digest) if user else None
        return {
            "global_enabled": self.global_enabled,
            "lease": lease,
            "lease_valid": lease is not None and lease.is_valid(now),
            "user": user,
            "auth": auth,
            "auth_valid": auth is not None and auth.is_valid(now),
            "context": self.feed.read_context(digest),
            "last_reading_at": self.store.last_reading_at(user_key),
            "pending_events": self.feed.count_events_for_user(user_key),
        }
