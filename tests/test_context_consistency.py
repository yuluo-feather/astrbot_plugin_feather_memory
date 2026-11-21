"""context 一致性：用 Event/Barrier 控制交错，不依赖 sleep。"""
from __future__ import annotations

import threading

from data.plugins.astrbot_plugin_feather_memory.core.identity import user_key_hash
from data.plugins.astrbot_plugin_feather_memory.core.timeutil import format_ts_precise


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
    assert service.user_state(user)["auto_history"] == 1


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
    original_drop = service._drop_context_guarded

    def saving_drop(user_key, now, guard):
        service.store.save_memory(user_key, "preference", "喜欢雨天", "喜欢雨天", now)
        return original_drop(user_key, now, guard)

    monkeypatch.setattr(service, "_drop_context_guarded", saving_drop)
    assert service.rebuild_context(user) == "superseded"
    assert service.user_state(user)["context_dirty"] == 1

    monkeypatch.setattr(service, "_drop_context_guarded", original_drop)
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


def test_empty_rebuild_restores_dirty_when_clear_condition_fails(
        service, feed, enabled_user, monkeypatch):
    user = enabled_user
    service.clear(user)
    service.enable(user)
    original = service.store.clear_dirty_if_revision
    calls = {"count": 0}

    def first_false(user_key, revision, now, *, require_enabled=True):
        calls["count"] += 1
        if calls["count"] == 1:
            return False
        return original(user_key, revision, now, require_enabled=require_enabled)

    monkeypatch.setattr(service.store, "clear_dirty_if_revision", first_false)
    assert service.rebuild_context(user) == "superseded"
    assert service.user_state(user)["context_dirty"] == 1


def test_transition_timestamp_taken_after_lock(service, feed, clock, enabled_user):
    user = enabled_user

    def advance():
        clock.advance(seconds=10)

    service._transition_hook = advance
    try:
        service.disable(user)
    finally:
        service._transition_hook = None
    row = service.user_state(user)
    assert row["disabled_at"] == format_ts_precise(clock.now())


def test_state_transition_waits_for_shared_state_lock(service, feed, enabled_user):
    user = enabled_user
    done = threading.Event()
    errors: list[BaseException] = []

    def disable():
        try:
            service.disable(user)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            done.set()

    with feed.state_lock():
        thread = threading.Thread(target=disable)
        thread.start()
        assert not done.wait(0.2)
    assert done.wait(5)
    thread.join(5)
    assert errors == []


def test_state_lock_blocks_second_transition(service, enabled_user):
    user = enabled_user
    first_inside = threading.Event()
    release_first = threading.Event()
    second_inside = threading.Event()
    calls = {"count": 0}

    def hook():
        calls["count"] += 1
        if calls["count"] == 1:
            first_inside.set()
            release_first.wait(5)
        else:
            second_inside.set()

    service._transition_hook = hook
    first = threading.Thread(target=service.disable, args=(user,))
    first.start()
    assert first_inside.wait(5)
    second = threading.Thread(target=service.enable, args=(user,))
    second.start()
    assert not second_inside.wait(0.2)
    release_first.set()
    first.join(5)
    second.join(5)
    service._transition_hook = None
    assert second_inside.is_set()
