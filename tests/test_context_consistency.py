"""context 一致性：用 Event/Barrier 控制交错，不依赖 sleep。"""
from __future__ import annotations

import threading

from data.plugins.astrbot_plugin_feather_memory.core.identity import user_key_hash


def _context(service, feed, user):
    return feed.read_context(user_key_hash(user))


def _write_blocking_context(feed, monkeypatch, started: threading.Event,
                            release: threading.Event):
    original = feed._write_json

    def blocking_write(path, payload, max_bytes):
        if path.parent == feed.layout.context_dir:
            started.set()
            release.wait(5)
        return original(path, payload, max_bytes)

    monkeypatch.setattr(feed, "_write_json", blocking_write)


def _transition_during_write(service, feed, monkeypatch, user, transition):
    started = threading.Event()
    release = threading.Event()
    reached_delete = threading.Event()
    errors: list[BaseException] = []

    _write_blocking_context(feed, monkeypatch, started, release)
    original_delete = feed.delete_context

    def marking_delete(digest, timeout_ms=1000):
        reached_delete.set()
        return original_delete(digest, timeout_ms)

    monkeypatch.setattr(feed, "delete_context", marking_delete)

    def writer():
        try:
            service.rebuild_context(user)
        except BaseException as exc:  # pragma: no cover - 失败时带回主线程
            errors.append(exc)

    def changer():
        try:
            transition()
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    writer_thread = threading.Thread(target=writer)
    change_thread = threading.Thread(target=changer)
    writer_thread.start()
    assert started.wait(5)
    change_thread.start()
    assert reached_delete.wait(5)
    release.set()
    writer_thread.join(5)
    change_thread.join(5)
    assert not writer_thread.is_alive()
    assert not change_thread.is_alive()
    assert errors == []


def test_revision_bump_after_guard_keeps_dirty(service, feed, enabled_user, monkeypatch):
    user = enabled_user
    service.remember(user, "喜欢温柔")
    original = feed.write_context

    def bumping_write(digest, ctx, timeout_ms=200, guard=None):
        def bumping_guard():
            ok = guard() if guard is not None else True
            if ok:
                service.store.bump_revision(user, service.clock())
            return ok

        return original(digest, ctx, timeout_ms=timeout_ms, guard=bumping_guard)

    monkeypatch.setattr(feed, "write_context", bumping_write)
    assert service.rebuild_context(user) == "superseded"
    assert service.user_state(user)["context_dirty"] == 1

    monkeypatch.setattr(feed, "write_context", original)
    service.rebuild_context(user)
    context = _context(service, feed, user)
    row = service.user_state(user)
    assert context is not None
    assert context.revision == row["context_revision"]
    assert row["context_dirty"] == 0


def test_clear_during_context_write_wins(service, feed, enabled_user, monkeypatch):
    user = enabled_user
    service.remember(user, "喜欢温柔")
    _transition_during_write(service, feed, monkeypatch, user,
                             lambda: service.clear(user))
    assert _context(service, feed, user) is None
    assert service.user_state(user)["enabled"] == 1
    assert service.user_state(user)["auto_history"] == 0


def test_disable_during_context_write_wins(service, feed, enabled_user, monkeypatch):
    user = enabled_user
    service.remember(user, "喜欢温柔")
    _transition_during_write(service, feed, monkeypatch, user,
                             lambda: service.disable(user))
    assert _context(service, feed, user) is None
    assert service.user_state(user)["enabled"] == 0


def test_disable_and_enable_concurrently_stay_consistent(service, feed, enabled_user):
    user = enabled_user
    service.remember(user, "喜欢温柔")
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def run(action):
        try:
            barrier.wait()
            action(user)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(service.disable,)),
               threading.Thread(target=run, args=(service.enable,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert errors == []
    row = service.user_state(user)
    context = _context(service, feed, user)
    if row["enabled"]:
        assert context is not None
        assert context.revision == row["context_revision"]
    else:
        assert context is None


def test_empty_rebuild_during_new_memory_keeps_dirty(
        service, feed, clock, enabled_user, monkeypatch):
    user = enabled_user
    service.clear(user)
    service.enable(user)
    assert _context(service, feed, user) is None
    original_drop = service._drop_context

    def saving_drop(user_key, now):
        service.store.save_memory(user_key, "preference", "喜欢雨天", "喜欢雨天", now)
        return original_drop(user_key, now)

    monkeypatch.setattr(service, "_drop_context", saving_drop)
    assert service.rebuild_context(user) == "superseded"
    assert service.user_state(user)["context_dirty"] == 1

    monkeypatch.setattr(service, "_drop_context", original_drop)
    service.rebuild_context(user)
    context = _context(service, feed, user)
    assert context is not None and "喜欢雨天" in context.text
    assert service.user_state(user)["context_dirty"] == 0


def test_two_rebuilds_keep_highest_revision(service, feed, enabled_user, monkeypatch):
    user = enabled_user
    service.remember(user, "喜欢温柔")
    started = threading.Event()
    release = threading.Event()
    newer_done = threading.Event()
    original = feed.write_context
    errors: list[BaseException] = []

    def ordered_write(digest, ctx, timeout_ms=200, guard=None):
        if ctx.revision == 1:
            started.set()
            release.wait(5)
        result = original(digest, ctx, timeout_ms=timeout_ms, guard=guard)
        if ctx.revision == 2:
            newer_done.set()
        return result

    monkeypatch.setattr(feed, "write_context", ordered_write)

    def older():
        try:
            service.rebuild_context(user)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    older_thread = threading.Thread(target=older)
    older_thread.start()
    assert started.wait(5)

    service.store.bump_revision(user, service.clock())
    newer_thread = threading.Thread(target=service.rebuild_context, args=(user,))
    newer_thread.start()
    assert newer_done.wait(5)
    release.set()
    older_thread.join(5)
    newer_thread.join(5)
    assert errors == []
    context = _context(service, feed, user)
    assert context is not None
    assert context.revision == service.user_state(user)["context_revision"]
