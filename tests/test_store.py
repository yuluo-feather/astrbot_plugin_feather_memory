"""SQLite 存储：去重、主题统计、保留窗口、清空。"""
from __future__ import annotations

import sqlite3
import threading
from datetime import timedelta

import pytest
from data.plugins.astrbot_plugin_feather_memory.core.timeutil import (
    format_ts,
    format_ts_precise,
)


def _count(store, table: str) -> int:
    with sqlite3.connect(store.path) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_initialize_sets_user_version_and_is_idempotent(store):
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    store.initialize()


def test_migrates_v1_users_table(tmp_path):
    from data.plugins.astrbot_plugin_feather_memory.adapters.sqlite_store import (
        SqliteStore,
    )

    path = tmp_path / "v1.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE users (user_key TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,"
            " auto_history INTEGER NOT NULL DEFAULT 0, store_topic INTEGER NOT NULL DEFAULT 0,"
            " context_revision INTEGER NOT NULL DEFAULT 0, context_dirty INTEGER NOT NULL DEFAULT 0,"
            " cleared_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,"
            " updated_at TEXT NOT NULL)")
        conn.execute("PRAGMA user_version = 1")
    SqliteStore(path).initialize()
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        assert "disabled_at" in columns
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3


def test_unsupported_user_version_rejected(tmp_path):
    from data.plugins.astrbot_plugin_feather_memory.adapters.sqlite_store import (
        SqliteStore,
    )

    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 4")
    with pytest.raises(RuntimeError):
        SqliteStore(path).initialize()


def test_migrates_v2_adds_exports_table(tmp_path):
    from data.plugins.astrbot_plugin_feather_memory.adapters.sqlite_store import (
        SqliteStore,
    )

    path = tmp_path / "v2.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 2")
    SqliteStore(path).initialize()
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "exports" in tables
        columns = {row[1] for row in conn.execute("PRAGMA table_info(exports)")}
        assert {"id", "user_key", "filename", "created_at"} <= columns


def test_concurrent_inserts_do_not_lose_committed(store, clock, make_event):
    user = "aiocqhttp:1"
    store.ensure_user(user, clock.now())
    errors = []

    def worker(worker_id: int) -> None:
        try:
            for index in range(10):
                store.insert_reading(
                    make_event(f"01JC{worker_id:02d}{index:02d}", user), clock.now())
        except Exception as exc:  # pragma: no cover - 失败时把原因带回主线程
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert _count(store, "readings") == 80


def test_upsert_memory_dedupes_same_normalized(store, clock):
    first = store.upsert_memory("u:1", "preference", "喜欢温柔", "喜欢温柔", clock.now())
    second = store.upsert_memory("u:1", "preference", "喜欢温柔 ", "喜欢温柔", clock.now())
    assert first == second
    assert _count(store, "memories") == 1


def test_insert_reading_guarded_states(store, clock, make_event):
    user = "aiocqhttp:1"
    store.ensure_user(user, clock.now())
    store.set_user_flags(user, clock.now(), enabled=1, auto_history=1)
    event = make_event("01JGUARD", user)
    assert store.insert_reading_guarded(event, clock.now()) == "inserted"
    assert store.insert_reading_guarded(event, clock.now()) == "duplicate"
    store.disable_user(user, clock.now())
    assert store.insert_reading_guarded(
        make_event("01JGUARD2", user), clock.now()) == "stale"
    with sqlite3.connect(store.path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM readings WHERE event_id = ?", ("01JGUARD2",)
        ).fetchone()[0] == 0


def test_insert_reading_guarded_requires_auto_history(store, clock, make_event):
    user = "aiocqhttp:1"
    store.ensure_user(user, clock.now())
    store.set_user_flags(user, clock.now(), enabled=1, auto_history=0)
    assert store.insert_reading_guarded(
        make_event("01JAUTO", user), clock.now()) == "stale"


def test_insert_reading_guarded_clears_topic_when_store_topic_off(store, clock, make_event):
    user = "aiocqhttp:1"
    store.ensure_user(user, clock.now())
    store.set_user_flags(user, clock.now(), enabled=1, auto_history=1, store_topic=0)
    assert store.insert_reading_guarded(
        make_event("01JTOPIC", user, topic_key="工作"), clock.now()) == "inserted"
    with sqlite3.connect(store.path) as conn:
        row = conn.execute(
            "SELECT topic_key FROM readings WHERE event_id = ?", ("01JTOPIC",)
        ).fetchone()
    assert row[0] == ""


def test_insert_reading_guarded_respects_disabled_at(store, clock, make_event):
    user = "aiocqhttp:1"
    store.ensure_user(user, clock.now())
    store.set_user_flags(user, clock.now(), enabled=1, auto_history=1, store_topic=1)
    store.disable_user(user, clock.now())
    disabled_at = store.get_user(user)["disabled_at"]
    store.set_user_flags(user, clock.now(), enabled=1, auto_history=1, store_topic=1)
    before = format_ts(clock.now() - timedelta(seconds=1))
    after = format_ts(clock.now() + timedelta(seconds=1))
    assert store.insert_reading_guarded(
        make_event("01JDIS", user, created_at=before), clock.now()) == "stale"
    assert store.insert_reading_guarded(
        make_event("01JDIS2", user, created_at=after), clock.now()) == "inserted"
    assert disabled_at


def test_insert_reading_guarded_respects_cleared_at(store, clock, make_event):
    user = "aiocqhttp:1"
    store.ensure_user(user, clock.now())
    store.set_user_flags(user, clock.now(), enabled=1, auto_history=1, store_topic=1)
    store.clear_user_data(user, clock.now())
    store.set_user_flags(user, clock.now(), auto_history=1, store_topic=1)
    before = format_ts(clock.now() - timedelta(seconds=1))
    after = format_ts(clock.now() + timedelta(seconds=1))
    assert store.insert_reading_guarded(
        make_event("01JOLD", user, created_at=before), clock.now()) == "stale"
    assert store.insert_reading_guarded(
        make_event("01JNEW", user, created_at=after), clock.now()) == "inserted"


def test_set_flag_if_enabled(store, clock):
    user = "aiocqhttp:1"
    store.ensure_user(user, clock.now())
    store.set_user_flags(user, clock.now(), enabled=1)
    assert store.set_flag_if_enabled(user, clock.now(), auto_history=1) == "ok"
    assert store.get_user(user)["auto_history"] == 1
    assert store.set_flag_if_enabled(
        user, clock.now(), store_topic=1, require_auto=True) == "ok"
    assert store.get_user(user)["store_topic"] == 1
    store.set_user_flags(user, clock.now(), auto_history=0)
    assert store.set_flag_if_enabled(
        user, clock.now(), store_topic=1, require_auto=True) == "auto_required"
    store.disable_user(user, clock.now())
    assert store.set_flag_if_enabled(user, clock.now(), auto_history=1) == "not_enabled"


def test_insert_reading_dedupes_event_id(store, clock, make_event):
    event = make_event("01JDUP")
    assert store.insert_reading(event, clock.now()) is True
    assert store.insert_reading(event, clock.now()) is False
    assert _count(store, "readings") == 1


def test_topic_stats_window_and_order(store, clock, make_event):
    store.ensure_user("aiocqhttp:1", clock.now())
    store.insert_reading(make_event("01JA", "aiocqhttp:1", topic_key="工作",
                                    created_at="2026-11-20T10:00:00Z"), clock.now())
    store.insert_reading(make_event("01JB", "aiocqhttp:1", topic_key="感情",
                                    created_at="2026-11-20T11:00:00Z"), clock.now())
    store.insert_reading(make_event("01JC", "aiocqhttp:1", topic_key="工作",
                                    created_at="2026-11-20T12:00:00Z"), clock.now())
    store.insert_reading(make_event("01JD", "aiocqhttp:1", topic_key="",
                                    created_at="2026-11-20T13:00:00Z"), clock.now())
    store.insert_reading(make_event("01JE", "aiocqhttp:1", topic_key="工作",
                                    created_at="2025-01-01T00:00:00Z"), clock.now())
    stats = store.topic_stats("aiocqhttp:1", clock.now())
    assert [(item.topic_key, item.count) for item in stats] == [("工作", 2), ("感情", 1)]


def test_topic_stats_ignores_items_beyond_retention_days(store, clock, make_event):
    store.ensure_user("aiocqhttp:1", clock.now())
    old = format_ts(clock.now() - timedelta(days=181))
    store.insert_reading(make_event("01JOLD", "aiocqhttp:1", topic_key="工作",
                                    created_at=old), clock.now())
    assert store.topic_stats("aiocqhttp:1", clock.now()) == []


def test_purge_readings_keeps_latest_200(store, clock, make_event):
    store.ensure_user("aiocqhttp:1", clock.now())
    base = clock.now()
    for index in range(205):
        created = format_ts(base + timedelta(seconds=index))
        store.insert_reading(make_event(f"01JP{index:04d}", "aiocqhttp:1",
                                        topic_key="工作", created_at=created), clock.now())
    store.purge_readings("aiocqhttp:1", clock.now())
    assert _count(store, "readings") == 200


def test_clear_user_data_removes_all_and_sets_cleared_at(store, clock, make_event):
    user = "aiocqhttp:1"
    store.ensure_user(user, clock.now())
    store.set_user_flags(user, clock.now(), enabled=1, auto_history=1, store_topic=1)
    store.upsert_memory(user, "preference", "喜欢温柔", "喜欢温柔", clock.now())
    store.insert_reading(make_event("01JCLR", user), clock.now())
    before = store.get_user(user)["context_revision"]
    store.clear_user_data(user, clock.now())
    row = store.get_user(user)
    assert _count(store, "memories") == 0
    assert _count(store, "readings") == 0
    assert row["auto_history"] == 0
    assert row["store_topic"] == 0
    assert row["cleared_at"] == format_ts_precise(clock.now())
    assert row["context_revision"] == before + 1
    assert row["context_dirty"] == 1


def test_insert_reading_normalizes_timestamp_precision(store, clock, make_event):
    user = "aiocqhttp:1"
    store.ensure_user(user, clock.now())
    store.insert_reading(
        make_event("01JPREC", user, created_at="2026-11-21T12:00:00.987654Z"),
        clock.now())
    with sqlite3.connect(store.path) as conn:
        stored = conn.execute("SELECT created_at FROM readings").fetchone()[0]
    assert stored == "2026-11-21T12:00:00Z"


def test_save_memory_bumps_revision_in_same_transaction(store, clock):
    user = "aiocqhttp:1"
    store.ensure_user(user, clock.now())
    store.save_memory(user, "preference", "喜欢温柔", "喜欢温柔", clock.now())
    row = store.get_user(user)
    assert (row["context_revision"], row["context_dirty"]) == (1, 1)
    store.save_memory(user, "preference", "喜欢温柔", "喜欢温柔", clock.now())
    assert store.get_user(user)["context_revision"] == 2
    assert _count(store, "memories") == 1


def test_remove_memory_only_bumps_when_removed(store, clock):
    user = "aiocqhttp:1"
    store.ensure_user(user, clock.now())
    memory_id = store.save_memory(user, "preference", "喜欢温柔", "喜欢温柔", clock.now())
    assert store.remove_memory(user, memory_id + 100, clock.now()) is False
    assert store.get_user(user)["context_revision"] == 1
    assert store.remove_memory(user, memory_id, clock.now()) is True
    assert store.get_user(user)["context_revision"] == 2


def test_disable_user_bumps_revision(store, clock):
    user = "aiocqhttp:1"
    store.ensure_user(user, clock.now())
    store.set_user_flags(user, clock.now(), enabled=1, auto_history=1, store_topic=1)
    before = store.get_user(user)["context_revision"]
    store.disable_user(user, clock.now())
    row = store.get_user(user)
    assert (row["enabled"], row["auto_history"], row["store_topic"]) == (0, 0, 0)
    assert row["context_revision"] == before + 1


def test_bump_revision_marks_dirty(store, clock):
    user = "aiocqhttp:1"
    store.ensure_user(user, clock.now())
    assert store.bump_revision(user, clock.now()) == 1
    row = store.get_user(user)
    assert row["context_revision"] == 1
    assert row["context_dirty"] == 1
    store.set_context_dirty(user, False, clock.now())
    assert store.get_user(user)["context_dirty"] == 0
