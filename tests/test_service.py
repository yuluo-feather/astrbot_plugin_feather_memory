"""业务编排：租约、授权、事件消费、context 重建与开关状态表。"""
from __future__ import annotations

import os
import sqlite3
from datetime import timedelta

from data.plugins.astrbot_plugin_feather_memory.adapters.file_lock import FileLock
from data.plugins.astrbot_plugin_feather_memory.adapters.memory_feed import (
    WRITE_TIMEOUT,
)
from data.plugins.astrbot_plugin_feather_memory.app.service import (
    MemoryService,
    has_meaningful_text,
    normalize_content,
)
from data.plugins.astrbot_plugin_feather_memory.core.contracts import Auth
from data.plugins.astrbot_plugin_feather_memory.core.identity import user_key_hash
from data.plugins.astrbot_plugin_feather_memory.core.timeutil import format_ts, parse_ts


def _activate(service, user_key="aiocqhttp:123456"):
    service.startup()
    service.enable(user_key)
    assert service.enable_auto(user_key) == "ok"


def test_startup_writes_lease_and_shutdown_removes_own(service, feed):
    service.startup()
    lease = feed.read_lease()
    assert lease is not None
    assert lease.instance_id == service.instance_id
    service.shutdown()
    assert feed.read_lease() is None


def test_refresh_after_shutdown_does_not_rewrite_lease(service, feed, clock):
    service.startup()
    service.shutdown()
    service._refresh_lease(clock.now())
    assert feed.read_lease() is None


def test_shutdown_keeps_other_instance_lease(service, feed, clock):
    service.startup()
    other = MemoryService(service.store, feed, global_enabled=True, version="0.1.0",
                          clock=clock.now, instance_id="01JOTHER000000000000000000")
    other._refresh_lease(clock.now())
    service.shutdown()
    assert feed.read_lease().instance_id == other.instance_id


def test_enable_opens_all_and_writes_auth_once(service, feed, monkeypatch):
    user = "aiocqhttp:1"
    service.startup()
    calls = {"count": 0}
    original = feed.write_auth

    def counting(auth):
        calls["count"] += 1
        return original(auth)

    monkeypatch.setattr(feed, "write_auth", counting)
    service.enable(user)
    row = service.user_state(user)
    assert (row["enabled"], row["auto_history"], row["store_topic"]) == (1, 1, 1)
    auth = feed.read_auth(user_key_hash(user))
    assert auth is not None
    assert auth.auto_history is True and auth.store_topic is True
    assert calls["count"] == 1


def test_enable_auto_requires_total_switch(service):
    service.startup()
    assert service.enable_auto("aiocqhttp:1") == "not_enabled"
    service.enable("aiocqhttp:1")
    assert service.enable_auto("aiocqhttp:1") == "ok"


def test_enable_topic_requires_auto(service, clock):
    user = "aiocqhttp:1"
    service.startup()
    service.store.ensure_user(user, clock.now())
    service.store.set_user_flags(user, clock.now(), enabled=1)
    service.refresh_auth(user, clock.now())
    assert service.enable_topic(user) == "auto_required"
    assert service.enable_auto(user) == "ok"
    assert service.enable_topic(user) == "ok"


def test_disable_auto_only_changes_auto(service, feed):
    user = "aiocqhttp:1"
    service.startup()
    service.enable(user)
    assert service.disable_auto(user) == "ok"
    row = service.user_state(user)
    assert (row["enabled"], row["auto_history"], row["store_topic"]) == (1, 0, 1)
    auth = feed.read_auth(user_key_hash(user))
    assert auth is not None
    assert auth.auto_history is False and auth.store_topic is True


def test_disable_topic_only_changes_topic(service, feed):
    user = "aiocqhttp:1"
    service.startup()
    service.enable(user)
    assert service.disable_topic(user) == "ok"
    row = service.user_state(user)
    assert (row["enabled"], row["auto_history"], row["store_topic"]) == (1, 1, 0)
    auth = feed.read_auth(user_key_hash(user))
    assert auth is not None
    assert auth.auto_history is True and auth.store_topic is False


def test_disable_subcommands_missing_user(service):
    service.startup()
    assert service.disable_auto("aiocqhttp:none") == "missing"
    assert service.disable_topic("aiocqhttp:none") == "missing"


def test_consume_success_writes_context_and_deletes_file(
        service, feed, store, clock, make_event, enabled_user):
    event = make_event("01J1")
    feed.write_event(event)
    assert service.consume_pending(clock.now()) == 1
    assert not feed.event_path("01J1").exists()
    context = feed.read_context(user_key_hash(enabled_user))
    assert context is not None
    assert context.revision == 1
    assert "工作（最近 1 次）" in context.text
    assert context.scope == "private"


def test_duplicate_event_not_counted_twice(
        service, feed, clock, make_event, enabled_user):
    event = make_event("01J1")
    feed.write_event(event)
    assert service.consume_pending(clock.now()) == 1
    feed.write_event(event)
    assert service.consume_pending(clock.now()) == 0
    assert not feed.event_path("01J1").exists()
    stats = service.store.topic_stats(enabled_user, clock.now())
    assert [(item.topic_key, item.count) for item in stats] == [("工作", 1)]


def test_first_event_enrolls_new_user(service, feed, clock, make_event):
    service.startup()
    user = "aiocqhttp:999"
    feed.write_event(make_event("01J1", user))
    assert service.consume_pending(clock.now()) == 1
    row = service.user_state(user)
    assert row is not None
    assert (row["enabled"], row["auto_history"], row["store_topic"]) == (1, 1, 1)
    auth = feed.read_auth(user_key_hash(user))
    assert auth is not None
    assert auth.auto_history is True and auth.store_topic is True
    stats = service.store.topic_stats(user, clock.now())
    assert [(item.topic_key, item.count) for item in stats] == [("工作", 1)]
    assert feed.read_context(user_key_hash(user)) is not None


def test_event_for_unknown_user_dropped_when_auto_enroll_off(
        store, feed, clock, make_event):
    service = MemoryService(store, feed, global_enabled=True, version="0.1.0",
                            clock=clock.now, auto_enroll=False)
    service.startup()
    user = "aiocqhttp:999"
    feed.write_event(make_event("01J1", user))
    assert service.consume_pending(clock.now()) == 0
    assert not feed.event_path("01J1").exists()
    assert service.user_state(user) is None
    assert feed.read_auth(user_key_hash(user)) is None


def test_expired_auth_event_dropped(service, feed, clock, make_event, enabled_user):
    clock.advance(days=181)
    feed.write_event(make_event("01J1", enabled_user))
    service.tick()
    assert not feed.event_path("01J1").exists()
    assert service.store.topic_stats(enabled_user, clock.now()) == []


def test_group_event_dropped(service, feed, clock, make_event, enabled_user):
    feed.write_event(make_event("01J1", enabled_user, scope="group"))
    assert service.consume_pending(clock.now()) == 0
    assert not feed.event_path("01J1").exists()


def test_daily_kind_dropped(service, feed, clock, make_event, enabled_user):
    feed.write_event(make_event("01J1", enabled_user, kind="daily"))
    assert service.consume_pending(clock.now()) == 0
    assert not feed.event_path("01J1").exists()


def test_store_topic_off_clears_topic(service, feed, clock, make_event):
    user = "aiocqhttp:777"
    service.startup()
    service.enable(user)
    assert service.disable_topic(user) == "ok"
    feed.write_event(make_event("01J1", user, topic_key="工作"))
    assert service.consume_pending(clock.now()) == 1
    assert service.store.topic_stats(user, clock.now()) == []
    assert feed.read_context(user_key_hash(user)) is None


def test_expired_lease_blocks_consumption(service, feed, clock, make_event, enabled_user):
    clock.advance(minutes=6)
    event_path = feed.event_path("01J1")
    feed.write_event(make_event("01J1", enabled_user))
    assert service.consume_pending(clock.now()) == 0
    assert event_path.exists()
    service.tick()
    assert not event_path.exists()


def test_disable_writes_tombstone_and_clears_context_events(
        service, feed, clock, make_event, enabled_user):
    feed.write_event(make_event("01J1", enabled_user))
    service.consume_pending(clock.now())
    service.remember(enabled_user, "喜欢温柔")
    service.disable(enabled_user)
    digest = user_key_hash(enabled_user)
    auth = feed.read_auth(digest)
    assert auth is not None
    assert auth.user_key_hash == digest
    assert auth.auto_history is False and auth.store_topic is False
    row = service.user_state(enabled_user)
    assert auth.context_valid_after == format_ts(parse_ts(row["disabled_at"]))
    assert feed.read_context(digest) is None
    assert feed.iter_events() == []
    assert (row["enabled"], row["auto_history"], row["store_topic"]) == (0, 0, 0)
    assert service.store.count_memories(enabled_user) == 1


def test_clear_sets_cleared_at_and_blocks_old_events(
        service, feed, clock, make_event, enabled_user):
    feed.write_event(make_event("01J1", enabled_user))
    service.consume_pending(clock.now())
    service.remember(enabled_user, "喜欢温柔")
    clock.advance(minutes=1)
    service.clear(enabled_user)
    digest = user_key_hash(enabled_user)
    assert service.store.count_memories(enabled_user) == 0
    assert service.store.topic_stats(enabled_user, clock.now()) == []
    auth = feed.read_auth(digest)
    assert auth is not None and auth.auto_history is True
    assert service.user_state(enabled_user)["enabled"] == 1

    feed.write_auth(Auth(
        user_key_hash=digest,
        generated_at=clock.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        expires_at=(clock.now() + timedelta(days=180)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        auto_history=True, store_topic=False, source="feather_memory/0.1.0"))
    old = (clock.now() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    feed.write_event(make_event("01JOLD", enabled_user, created_at=old))
    assert service.consume_pending(clock.now()) == 0
    assert not feed.event_path("01JOLD").exists()


def test_remember_autoenables_and_forget_removes_context(
        service, feed, clock, enabled_user):
    service.disable(enabled_user)
    memory_id, truncated = service.remember(enabled_user, "偏好 温柔一点")
    assert memory_id > 0 and truncated is False
    row = service.user_state(enabled_user)
    assert row["enabled"] == 1
    auth = feed.read_auth(user_key_hash(enabled_user))
    assert auth is not None and auth.auto_history is False
    context = feed.read_context(user_key_hash(enabled_user))
    assert context is not None and "温柔一点" in context.text

    assert service.forget(enabled_user, memory_id) is True
    assert feed.read_context(user_key_hash(enabled_user)) is None
    assert service.forget(enabled_user, memory_id) is False


def test_remember_truncates_to_160_chars(service, enabled_user):
    memory_id, truncated = service.remember(enabled_user, "长" * 200)
    assert memory_id > 0 and truncated is True
    memories, _ = service.list_display(enabled_user)
    assert memories[0].content == "长" * 160


def test_identity_isolation(service, feed, clock, make_event):
    service.startup()
    users = {"aiocqhttp:1": ("工作", "01JA"),
             "aiocqhttp:2": ("感情", "01JB"),
             "telegram:1": ("学业", "01JC")}
    for user, (topic, event_id) in users.items():
        service.enable(user)
        service.enable_auto(user)
        service.enable_topic(user)
        feed.write_event(make_event(event_id, user, topic_key=topic))
    assert service.consume_pending(clock.now()) == 3
    for user, (topic, _) in users.items():
        context = feed.read_context(user_key_hash(user))
        assert topic in context.text
        for other, (other_topic, _) in users.items():
            if other != user:
                assert other_topic not in context.text


def test_startup_renews_context_ttl(service, feed, clock, enabled_user):
    service.remember(enabled_user, "喜欢温柔")
    digest = user_key_hash(enabled_user)
    before = feed.read_context(digest).expires_at
    clock.advance(days=20)
    fresh = MemoryService(service.store, feed, global_enabled=True, version="0.1.0",
                          clock=clock.now, instance_id="01JNEW00000000000000000000")
    fresh.startup()
    after = feed.read_context(digest).expires_at
    assert after > before


def test_dirty_user_rebuilt_on_startup(service, feed, clock, enabled_user):
    service.remember(enabled_user, "喜欢温柔")
    digest = user_key_hash(enabled_user)
    service.store.set_context_dirty(enabled_user, True, clock.now())
    feed.delete_context(digest)
    fresh = MemoryService(service.store, feed, global_enabled=True, version="0.1.0",
                          clock=clock.now, instance_id="01JNEW00000000000000000000")
    fresh.startup()
    assert feed.read_context(digest) is not None
    assert service.store.get_user(enabled_user)["context_dirty"] == 0


def test_context_timeout_marks_dirty_then_recovers(
        service, feed, clock, enabled_user):
    digest = user_key_hash(enabled_user)
    lock_path = feed.layout.context_dir / f"{digest}.lock"
    with FileLock(lock_path, timeout_ms=1000):
        service.remember(enabled_user, "喜欢温柔")
    assert service.store.get_user(enabled_user)["context_dirty"] == 1
    assert feed.read_context(digest) is None
    service.rebuild_all_contexts(clock.now())
    assert service.store.get_user(enabled_user)["context_dirty"] == 0
    assert feed.read_context(digest) is not None


def test_event_delete_failure_retried_without_duplicate(
        service, feed, clock, make_event, enabled_user, monkeypatch):
    feed.write_event(make_event("01J1", enabled_user))
    original = feed.delete_event
    calls = {"count": 0}

    def flaky(path):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("disk full")
        return original(path)

    monkeypatch.setattr(feed, "delete_event", flaky)
    assert service.consume_pending(clock.now()) == 1
    assert feed.event_path("01J1").exists()

    monkeypatch.setattr(feed, "delete_event", original)
    assert service.consume_pending(clock.now()) == 0
    assert not feed.event_path("01J1").exists()
    stats = service.store.topic_stats(enabled_user, clock.now())
    assert [(item.topic_key, item.count) for item in stats] == [("工作", 1)]


def test_clear_boundary_with_fractional_events(
        service, feed, clock, make_event, enabled_user):
    clock.moment = clock.moment.replace(microsecond=600000)
    service.clear(enabled_user)
    service.enable(enabled_user)
    feed.write_event(make_event(
        "01JBEFORE", enabled_user, topic_key="工作",
        created_at="2026-11-21T12:00:00.300000Z"))
    feed.write_event(make_event(
        "01JAFTER", enabled_user, topic_key="感情",
        created_at="2026-11-21T12:00:00.900000Z"))
    assert service.consume_pending(clock.now()) == 1
    assert not feed.event_path("01JBEFORE").exists()
    assert not feed.event_path("01JAFTER").exists()
    stats = service.store.topic_stats(enabled_user, clock.now())
    assert [(item.topic_key, item.count) for item in stats] == [("感情", 1)]


def test_auth_without_auto_history_drops_event(service, feed, clock, make_event):
    user = "aiocqhttp:556"
    service.startup()
    service.enable(user)
    assert service.disable_auto(user) == "ok"
    feed.write_event(make_event("01J1", user))
    assert service.consume_pending(clock.now()) == 0
    assert not feed.event_path("01J1").exists()


def test_missing_lease_keeps_events(service, feed, clock, make_event, enabled_user):
    feed.layout.lease_path.unlink()
    feed.write_event(make_event("01J1", enabled_user))
    assert service.consume_pending(clock.now()) == 0
    assert feed.event_path("01J1").exists()


def test_cleanup_prunes_disabled_user_readings(
        service, feed, clock, make_event, enabled_user):
    feed.write_event(make_event("01J1", enabled_user))
    assert service.consume_pending(clock.now()) == 1
    service.disable(enabled_user)
    clock.advance(days=181)
    service.cleanup(clock.now())
    with sqlite3.connect(service.store.path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM readings WHERE user_key = ?", (enabled_user,)
        ).fetchone()[0]
    assert count == 0


def test_global_disabled_still_sweeps_shared_files(store, feed, clock):
    service = MemoryService(store, feed, global_enabled=False, version="0.1.0",
                            clock=clock.now, instance_id="01JOFF0000000000000000000")
    digest = user_key_hash("aiocqhttp:1")
    feed.write_auth(Auth(
        user_key_hash=digest,
        generated_at=format_ts(clock.now() - timedelta(days=181)),
        expires_at=format_ts(clock.now() - timedelta(days=1)),
        auto_history=True, store_topic=False, source="feather_memory/0.1.0"))
    service.startup()
    assert feed.read_lease() is None
    assert feed.read_auth(digest) is None


def test_enable_reports_auth_write_failure(service, feed, monkeypatch):
    service.startup()

    def boom(auth):
        raise OSError("disk full")

    monkeypatch.setattr(feed, "write_auth", boom)
    result = service.enable("aiocqhttp:1")
    assert result["auth_ok"] is False
    assert service.enable_auto("aiocqhttp:1") == "auth_failed"
    assert service.disable_auto("aiocqhttp:1") == "auth_failed"


def test_disabled_at_blocks_old_events_after_reenable(
        service, feed, clock, make_event):
    user = "aiocqhttp:1"
    service.startup()
    service.enable(user)
    before_disable = format_ts(clock.now() - timedelta(seconds=1))
    service.disable(user)
    clock.advance(seconds=5)
    service.enable(user)
    feed.write_event(make_event("01JOLD", user, created_at=before_disable))
    feed.write_event(make_event("01JNEW", user))
    assert service.consume_pending(clock.now()) == 1
    assert not feed.event_path("01JOLD").exists()
    assert not feed.event_path("01JNEW").exists()
    stats = service.store.topic_stats(user, clock.now())
    assert [(item.topic_key, item.count) for item in stats] == [("工作", 1)]


def test_update_memory_preserves_id_and_category(service, feed, clock, enabled_user):
    memory_id, _ = service.remember(enabled_user, "偏好 温柔")
    revision = service.user_state(enabled_user)["context_revision"]
    code, truncated = service.update_memory(enabled_user, memory_id, "更温柔")
    assert (code, truncated) == ("ok", False)
    memories, _ = service.list_display(enabled_user)
    assert [(item.memory_id, item.category, item.content) for item in memories] == [
        (memory_id, "preference", "更温柔")]
    assert service.user_state(enabled_user)["context_revision"] == revision + 1
    context = feed.read_context(user_key_hash(enabled_user))
    assert context is not None and "更温柔" in context.text


def test_update_memory_can_change_category(service, enabled_user):
    memory_id, _ = service.remember(enabled_user, "偏好 温柔")
    assert service.update_memory(enabled_user, memory_id, "背景 学生") == ("ok", False)
    memories, _ = service.list_display(enabled_user)
    assert memories[0].category == "background"


def test_update_memory_missing_and_duplicate(service, enabled_user):
    first, _ = service.remember(enabled_user, "喜欢温柔")
    service.remember(enabled_user, "喜欢雨天")
    assert service.update_memory(enabled_user, first, "喜欢雨天")[0] == "duplicate"
    memories, _ = service.list_display(enabled_user)
    assert any(item.content == "喜欢温柔" for item in memories)
    assert service.update_memory(enabled_user, 99999, "随便")[0] == "missing"


def test_update_memory_truncates(service, enabled_user):
    memory_id, _ = service.remember(enabled_user, "喜欢温柔")
    code, truncated = service.update_memory(enabled_user, memory_id, "长" * 200)
    assert (code, truncated) == ("ok", True)
    memories, _ = service.list_display(enabled_user)
    assert memories[0].content == "长" * 160


def test_disable_collects_failures_and_retries(
        service, feed, monkeypatch, enabled_user, make_event):
    feed.write_event(make_event("01J1", enabled_user))
    calls = {"auth": 0, "context": 0}

    def fail_auth(auth):
        calls["auth"] += 1
        raise OSError("disk full")

    def fail_context(digest, timeout_ms=1000):
        calls["context"] += 1
        return False

    monkeypatch.setattr(feed, "write_auth", fail_auth)
    monkeypatch.setattr(feed, "delete_context", fail_context)
    removed, failures = service.disable(enabled_user)
    assert removed == 1
    assert failures == ["context", "auth"]
    assert calls == {"auth": 1, "context": 2}
    assert feed.iter_events() == []
    assert service.user_state(enabled_user)["context_dirty"] == 1


def test_clear_collects_context_failure(service, feed, monkeypatch, enabled_user):
    service.remember(enabled_user, "喜欢温柔")
    monkeypatch.setattr(feed, "delete_context",
                        lambda digest, timeout_ms=1000: False)
    monkeypatch.setattr(feed, "expire_context",
                        lambda digest, timeout_ms=1000: False)
    removed, failures = service.clear(enabled_user)
    assert removed == 0
    assert failures == ["context"]
    assert service.store.count_memories(enabled_user) == 0


def test_prefix_requires_separator(service, enabled_user):
    for text in ("背景知识很重要", "目标导向思维", "偏好关系分析"):
        memory_id, _ = service.remember(enabled_user, text)
        memories, _ = service.list_display(enabled_user)
        entry = next(item for item in memories if item.memory_id == memory_id)
        assert entry.category == "preference"
        assert entry.content == text
    memory_id, _ = service.remember(enabled_user, "背景：学生")
    memories, _ = service.list_display(enabled_user)
    entry = next(item for item in memories if item.memory_id == memory_id)
    assert (entry.category, entry.content) == ("background", "学生")
    assert service.update_memory(enabled_user, memory_id, "背景知识很重要") == ("ok", False)
    memories, _ = service.list_display(enabled_user)
    entry = next(item for item in memories if item.memory_id == memory_id)
    assert (entry.category, entry.content) == ("background", "背景知识很重要")


def test_stats_is_read_only_counts(service, feed, make_event, enabled_user):
    service.remember(enabled_user, "喜欢温柔")
    feed.write_event(make_event("01JSTAT", enabled_user))
    stats = service.stats()
    assert stats["users"] == 1
    assert stats["enabled"] == 1
    assert stats["memories"] == 1
    assert stats["readings"] == 0
    assert stats["files_events"] == 1
    assert stats["files_lease"] is True


def test_status_counts_pending_events(service, feed, make_event, enabled_user):
    feed.write_event(make_event("01J1", enabled_user))
    info = service.status(enabled_user)
    assert info["pending_events"] == 1
    assert info["lease_valid"] is True


def test_context_write_timeout_constant_is_exposed():
    assert WRITE_TIMEOUT == "timeout"
    assert os.name in ("nt", "posix")


def test_lease_carries_auto_enroll_config(service, feed):
    service.startup()
    lease = feed.read_lease()
    assert lease is not None and lease.auto_enroll is True


def test_lease_auto_enroll_can_be_disabled(store, feed, clock):
    service = MemoryService(store, feed, global_enabled=True, version="0.1.0",
                            clock=clock.now, auto_enroll=False)
    service.startup()
    lease = feed.read_lease()
    assert lease is not None and lease.auto_enroll is False


def test_startup_reconciles_missing_auth(service, feed, clock, enabled_user):
    disabled = "aiocqhttp:777"
    service.enable(disabled)
    service.disable(disabled)
    digest_enabled = user_key_hash(enabled_user)
    digest_disabled = user_key_hash(disabled)
    feed.delete_auth(digest_enabled)
    feed.delete_auth(digest_disabled)

    service.startup()

    enabled_auth = feed.read_auth(digest_enabled)
    disabled_auth = feed.read_auth(digest_disabled)
    assert enabled_auth is not None and enabled_auth.auto_history is True
    assert disabled_auth is not None
    assert disabled_auth.auto_history is False
    assert disabled_auth.store_topic is False


def test_cleanup_restores_missing_tombstone(service, feed, clock):
    user = "aiocqhttp:777"
    service.enable(user)
    service.disable(user)
    digest = user_key_hash(user)
    feed.delete_auth(digest)

    service.cleanup(clock.now())

    auth = feed.read_auth(digest)
    assert auth is not None and auth.auto_history is False


def test_normalize_content_matches_render_cleaning():
    assert normalize_content(" 喜欢  猫。 ") == "喜欢 猫"
    assert normalize_content("喜欢猫；") == "喜欢猫"
    assert has_meaningful_text("喜欢猫")
    assert not has_meaningful_text("！！！")
    assert not has_meaningful_text("。。。")


def test_remember_dedupes_trailing_punctuation(service):
    service.startup()
    first, _ = service.remember("aiocqhttp:1", "喜欢猫")
    second, _ = service.remember("aiocqhttp:1", "喜欢猫。")
    assert first == second
    assert service.store.count_memories("aiocqhttp:1") == 1
    memories, _ = service.list_display("aiocqhttp:1")
    assert [entry.content for entry in memories] == ["喜欢猫。"]


def test_remember_rejects_punctuation_only(service):
    service.startup()
    assert service.remember("aiocqhttp:1", "！！！") == (0, False)
    assert service.remember("aiocqhttp:1", "。。。") == (0, False)
    assert service.store.count_memories("aiocqhttp:1") == 0


def test_update_rejects_punctuation_only(service):
    service.startup()
    service.enable("aiocqhttp:1")
    memory_id, _ = service.remember("aiocqhttp:1", "喜欢猫")
    assert service.update_memory("aiocqhttp:1", memory_id, "？？！")[0] == "empty"
    assert service.store.get_memory("aiocqhttp:1", memory_id)["content"] == "喜欢猫"


def test_update_to_punctuated_duplicate_is_rejected(service):
    service.startup()
    service.enable("aiocqhttp:1")
    first, _ = service.remember("aiocqhttp:1", "喜欢猫")
    second, _ = service.remember("aiocqhttp:1", "喜欢狗")
    assert service.update_memory("aiocqhttp:1", second, "喜欢猫。")[0] == "duplicate"
    assert service.store.get_memory("aiocqhttp:1", second)["content"] == "喜欢狗"
    assert service.store.count_memories("aiocqhttp:1") == 2


def test_event_for_disabled_user_is_dropped_and_keeps_tombstone(
        service, feed, clock, make_event):
    user = "aiocqhttp:777"
    service.startup()
    service.enable(user)
    service.disable(user)
    digest = user_key_hash(user)
    feed.delete_auth(digest)
    feed.write_event(make_event("01J1", user))

    assert service.consume_pending(clock.now()) == 0

    assert service.user_state(user)["enabled"] == 0
    auth = feed.read_auth(digest)
    assert auth is not None and auth.auto_history is False
    assert not feed.event_path("01J1").exists()


def test_duplicate_event_does_not_reenable_disabled_user(
        service, feed, clock, make_event):
    user = "aiocqhttp:777"
    service.startup()
    service.enable(user)
    service.disable(user)
    event = make_event("01J1", user)
    feed.write_event(event)
    service.consume_pending(clock.now())
    feed.write_event(event)

    assert service.consume_pending(clock.now()) == 0
    assert service.user_state(user)["enabled"] == 0
    assert not feed.event_path("01J1").exists()


def test_clear_keeps_switches_and_writes_cutoff(service, feed, clock, enabled_user):
    before = feed.read_auth(user_key_hash(enabled_user))
    service.remember(enabled_user, "喜欢温柔")

    service.clear(enabled_user)

    after = feed.read_auth(user_key_hash(enabled_user))
    row = service.user_state(enabled_user)
    assert before is not None and after is not None
    assert after.user_key_hash == before.user_key_hash
    assert after.auto_history is True and after.store_topic is True
    assert after.context_valid_after == format_ts(parse_ts(row["cleared_at"]))
    assert (row["enabled"], row["auto_history"], row["store_topic"]) == (1, 1, 1)
    assert service.store.count_memories(enabled_user) == 0


def test_reenabled_context_is_after_cutoff(service, feed, clock, enabled_user):
    service.disable(enabled_user)
    clock.advance(seconds=1)
    service.enable(enabled_user)
    service.remember(enabled_user, "喜欢温柔")

    auth = feed.read_auth(user_key_hash(enabled_user))
    context = feed.read_context(user_key_hash(enabled_user))
    assert auth is not None and auth.context_valid_after
    assert context is not None
    assert parse_ts(context.generated_at) > parse_ts(auth.context_valid_after)


def test_clear_disabled_user_keeps_tombstone(service, feed, clock):
    user = "aiocqhttp:777"
    service.startup()
    service.enable(user)
    service.disable(user)

    service.clear(user)

    row = service.user_state(user)
    assert (row["enabled"], row["auto_history"], row["store_topic"]) == (0, 0, 0)
    auth = feed.read_auth(user_key_hash(user))
    assert auth is not None
    assert auth.auto_history is False and auth.store_topic is False


def test_clear_unknown_user_writes_tombstone(service, feed, clock):
    user = "aiocqhttp:404"

    service.clear(user)

    row = service.user_state(user)
    assert row is not None
    assert (row["enabled"], row["auto_history"], row["store_topic"]) == (0, 0, 0)
    auth = feed.read_auth(user_key_hash(user))
    assert auth is not None
    assert auth.auto_history is False and auth.store_topic is False


def test_disable_expires_context_when_delete_fails(
        service, feed, clock, enabled_user, monkeypatch):
    service.remember(enabled_user, "喜欢温柔")
    digest = user_key_hash(enabled_user)
    assert feed.read_context(digest) is not None
    monkeypatch.setattr(feed, "delete_context",
                        lambda digest, timeout_ms=1000: False)

    _, failures = service.disable(enabled_user)

    assert "context" not in failures
    context = feed.read_context(digest)
    assert context is not None
    assert context.is_usable(clock.now()) is False


def test_clear_expires_context_when_delete_fails(
        service, feed, clock, enabled_user, monkeypatch):
    service.remember(enabled_user, "喜欢温柔")
    digest = user_key_hash(enabled_user)
    monkeypatch.setattr(feed, "delete_context",
                        lambda digest, timeout_ms=1000: False)

    _, failures = service.clear(enabled_user)

    assert "context" not in failures
    context = feed.read_context(digest)
    assert context is not None
    assert context.is_usable(clock.now()) is False


def test_disabled_event_does_not_rewrite_valid_tombstone(
        service, feed, clock, make_event, monkeypatch):
    user = "aiocqhttp:777"
    service.startup()
    service.enable(user)
    service.disable(user)
    calls = []
    monkeypatch.setattr(feed, "write_auth", lambda auth: calls.append(auth))

    feed.write_event(make_event("01J1", user))

    assert service.consume_pending(clock.now()) == 0
    assert calls == []


def test_enroll_failure_keeps_event_for_retry(
        service, feed, clock, make_event, monkeypatch):
    service.startup()
    feed.write_event(make_event("01J1", "aiocqhttp:777"))

    def boom(user_key, now):
        raise RuntimeError("database down")

    monkeypatch.setattr(service.store, "enroll_user", boom)

    assert service.consume_pending(clock.now()) == 0
    assert feed.event_path("01J1").exists()
