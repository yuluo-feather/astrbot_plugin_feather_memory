"""SQLite 存储：WAL、`PRAGMA user_version` 迁移、短事务；只依赖标准库。"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from ..core.contracts import (
    READING_RETENTION_COUNT,
    READING_RETENTION_DAYS,
    ReadingEvent,
)
from ..core.merge import ExplicitEntry, TopicStat
from ..core.timeutil import add_days, format_ts, format_ts_precise, parse_ts

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
  user_key TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL DEFAULT 0,
  auto_history INTEGER NOT NULL DEFAULT 0,
  store_topic INTEGER NOT NULL DEFAULT 0,
  context_revision INTEGER NOT NULL DEFAULT 0,
  context_dirty INTEGER NOT NULL DEFAULT 0,
  cleared_at TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_key TEXT NOT NULL,
  category TEXT NOT NULL,
  content TEXT NOT NULL,
  normalized_content TEXT NOT NULL,
  visibility TEXT NOT NULL DEFAULT 'private',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  expires_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_memories_dedupe
ON memories(user_key, category, normalized_content);

CREATE INDEX IF NOT EXISTS idx_memories_owner
ON memories(user_key, updated_at DESC);

CREATE TABLE IF NOT EXISTS readings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  user_key TEXT NOT NULL,
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  spread TEXT NOT NULL,
  cards_json TEXT NOT NULL,
  topic_key TEXT NOT NULL DEFAULT '',
  conversation_scope TEXT NOT NULL DEFAULT 'private'
);

CREATE INDEX IF NOT EXISTS idx_readings_user_time
ON readings(user_key, created_at DESC);

CREATE TABLE IF NOT EXISTS suppressed_topics (
  user_key TEXT NOT NULL,
  topic_key TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_key, topic_key)
);
"""

_USER_FIELDS = ("enabled", "auto_history", "store_topic", "context_dirty")


class SqliteStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self._connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                conn.executescript(SCHEMA_V1)
                conn.execute("PRAGMA user_version = 1")
            elif version != 1:
                raise RuntimeError(f"unsupported feather_memory schema version {version}")

    # ---- users ---------------------------------------------------------

    def ensure_user(self, user_key: str, now: datetime) -> dict:
        stamp = format_ts(now)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users(user_key, created_at, updated_at) VALUES(?,?,?)",
                (user_key, stamp, stamp),
            )
        user = self.get_user(user_key)
        if user is None:  # pragma: no cover - 插入后必然存在
            raise RuntimeError("user row vanished after insert")
        return user

    def get_user(self, user_key: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_key = ?", (user_key,)
            ).fetchone()
        return dict(row) if row else None

    def set_user_flags(self, user_key: str, now: datetime, **flags: int) -> None:
        unknown = set(flags) - set(_USER_FIELDS)
        if unknown:
            raise ValueError(f"unknown user flags: {sorted(unknown)}")
        if not flags:
            return
        assignments = ", ".join(f"{name} = ?" for name in flags)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE users SET {assignments}, updated_at = ? WHERE user_key = ?",
                (*[int(value) for value in flags.values()], format_ts(now), user_key),
            )

    def all_users(self, *, enabled_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM users"
        if enabled_only:
            sql += " WHERE enabled = 1"
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql)]

    def dirty_users(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM users WHERE context_dirty = 1"
            ).fetchall()
        return [dict(row) for row in rows]

    def set_context_dirty(self, user_key: str, dirty: bool, now: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET context_dirty = ?, updated_at = ? WHERE user_key = ?",
                (1 if dirty else 0, format_ts(now), user_key),
            )

    def bump_revision(self, user_key: str, now: datetime) -> int:
        stamp = format_ts(now)
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET context_revision = context_revision + 1,"
                " context_dirty = 1, updated_at = ? WHERE user_key = ?",
                (stamp, user_key),
            )
            row = conn.execute(
                "SELECT context_revision FROM users WHERE user_key = ?", (user_key,)
            ).fetchone()
        return int(row["context_revision"]) if row else 0

    def save_memory(self, user_key: str, category: str, content: str,
                    normalized: str, now: datetime) -> int:
        """写入 / 去重一条显式记忆，并在同一事务里递增 revision。"""
        stamp = format_ts(now)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO memories(user_key, category, content, normalized_content,"
                " created_at, updated_at) VALUES(?,?,?,?,?,?)"
                " ON CONFLICT(user_key, category, normalized_content)"
                " DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at",
                (user_key, category, content, normalized, stamp, stamp),
            )
            conn.execute(
                "UPDATE users SET context_revision = context_revision + 1,"
                " context_dirty = 1, updated_at = ? WHERE user_key = ?",
                (stamp, user_key),
            )
            row = conn.execute(
                "SELECT id FROM memories WHERE user_key = ? AND category = ?"
                " AND normalized_content = ?",
                (user_key, category, normalized),
            ).fetchone()
        return int(row["id"])

    def remove_memory(self, user_key: str, memory_id: int, now: datetime) -> bool:
        """删除一条显式记忆；只有真的删到才在同一事务里递增 revision。"""
        stamp = format_ts(now)
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM memories WHERE user_key = ? AND id = ?", (user_key, memory_id)
            )
            removed = cursor.rowcount > 0
            if removed:
                conn.execute(
                    "UPDATE users SET context_revision = context_revision + 1,"
                    " context_dirty = 1, updated_at = ? WHERE user_key = ?",
                    (stamp, user_key),
                )
        return removed

    def disable_user(self, user_key: str, now: datetime) -> None:
        """关闭总开关：清三枚开关并递增 revision，挡住并发中的旧 context 重建。"""
        stamp = format_ts(now)
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET enabled = 0, auto_history = 0, store_topic = 0,"
                " context_revision = context_revision + 1, context_dirty = 0,"
                " updated_at = ? WHERE user_key = ?",
                (stamp, user_key),
            )

    # ---- explicit memories --------------------------------------------

    def upsert_memory(self, user_key: str, category: str, content: str,
                      normalized: str, now: datetime) -> int:
        stamp = format_ts(now)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO memories(user_key, category, content, normalized_content,"
                " created_at, updated_at) VALUES(?,?,?,?,?,?)"
                " ON CONFLICT(user_key, category, normalized_content)"
                " DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at",
                (user_key, category, content, normalized, stamp, stamp),
            )
            row = conn.execute(
                "SELECT id FROM memories WHERE user_key = ? AND category = ?"
                " AND normalized_content = ?",
                (user_key, category, normalized),
            ).fetchone()
        return int(row["id"])

    def list_memories(self, user_key: str, now: datetime, limit: int = 200) -> list[ExplicitEntry]:
        stamp = format_ts(now)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, category, content FROM memories"
                " WHERE user_key = ? AND (expires_at IS NULL OR expires_at = '' OR expires_at > ?)"
                " ORDER BY updated_at DESC, id DESC LIMIT ?",
                (user_key, stamp, limit),
            ).fetchall()
        return [ExplicitEntry(memory_id=int(row["id"]), category=row["category"],
                              content=row["content"]) for row in rows]

    def delete_memory(self, user_key: str, memory_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM memories WHERE user_key = ? AND id = ?", (user_key, memory_id)
            )
        return cursor.rowcount > 0

    def count_memories(self, user_key: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM memories WHERE user_key = ?", (user_key,)
            ).fetchone()
        return int(row["n"])

    # ---- readings ------------------------------------------------------

    def insert_reading(self, event: ReadingEvent, now: datetime) -> bool:
        cards_json = json.dumps([card.to_dict() for card in event.cards],
                                ensure_ascii=False, separators=(",", ":"))
        # 统一入库为秒精度：核心写的事件允许带微秒，混用两种精度会让字符串
        # 比较（cleared_at / 保留窗口 / 排序）在“同一秒”内判错。
        created_at = format_ts(parse_ts(event.created_at))
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO readings(event_id, user_key, created_at, kind, spread,"
                " cards_json, topic_key, conversation_scope) VALUES(?,?,?,?,?,?,?,?)",
                (event.event_id, event.user_key, created_at, event.kind, event.spread,
                 cards_json, event.topic_key, event.conversation_scope),
            )
            inserted = cursor.rowcount > 0
            if inserted:
                conn.execute(
                    "UPDATE users SET context_revision = context_revision + 1,"
                    " context_dirty = 1, updated_at = ? WHERE user_key = ?",
                    (format_ts(now), event.user_key),
                )
        return inserted

    def topic_stats(self, user_key: str, now: datetime,
                    max_events: int = READING_RETENTION_COUNT,
                    limit: int = 8) -> list[TopicStat]:
        since = format_ts(add_days(now, -READING_RETENTION_DAYS))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT topic_key, COUNT(*) AS count, MAX(created_at) AS last_at FROM ("
                "  SELECT topic_key, created_at FROM readings"
                "  WHERE user_key = ? AND topic_key <> ''"
                "  ORDER BY created_at DESC, id DESC LIMIT ?"
                ") WHERE created_at >= ?"
                " GROUP BY topic_key ORDER BY last_at DESC, topic_key ASC LIMIT ?",
                (user_key, max_events, since, limit),
            ).fetchall()
        return [TopicStat(topic_key=row["topic_key"], count=int(row["count"]),
                          last_at=row["last_at"]) for row in rows]

    def purge_readings(self, user_key: str, now: datetime,
                       keep: int = READING_RETENTION_COUNT) -> int:
        since = format_ts(add_days(now, -READING_RETENTION_DAYS))
        with self._connect() as conn:
            removed = conn.execute(
                "DELETE FROM readings WHERE user_key = ? AND id NOT IN ("
                "  SELECT id FROM readings WHERE user_key = ?"
                "  ORDER BY created_at DESC, id DESC LIMIT ?)",
                (user_key, user_key, keep),
            ).rowcount
            removed += conn.execute(
                "DELETE FROM readings WHERE user_key = ? AND created_at < ?",
                (user_key, since),
            ).rowcount
        return max(0, removed)

    def suppressed_topics(self, user_key: str) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT topic_key FROM suppressed_topics WHERE user_key = ?", (user_key,)
            ).fetchall()
        return {row["topic_key"] for row in rows}

    # ---- clear ---------------------------------------------------------

    def clear_user_data(self, user_key: str, now: datetime) -> None:
        stamp = format_ts(now)
        cleared = format_ts_precise(now)
        with self._connect() as conn:
            conn.execute("DELETE FROM memories WHERE user_key = ?", (user_key,))
            conn.execute("DELETE FROM readings WHERE user_key = ?", (user_key,))
            conn.execute("DELETE FROM suppressed_topics WHERE user_key = ?", (user_key,))
            conn.execute(
                "UPDATE users SET auto_history = 0, store_topic = 0, cleared_at = ?,"
                " context_revision = context_revision + 1, context_dirty = 1,"
                " updated_at = ? WHERE user_key = ?",
                (cleared, stamp, user_key),
            )
