"""共享文件契约的读写：原子写入、租约归属、revision 串行化、清扫。"""
from __future__ import annotations

import json
import os
import threading
from datetime import timedelta

import pytest
from data.plugins.astrbot_plugin_feather_memory.adapters.file_lock import FileLock
from data.plugins.astrbot_plugin_feather_memory.adapters.memory_feed import (
    WRITE_STALE,
    WRITE_TIMEOUT,
    WRITE_WRITTEN,
)
from data.plugins.astrbot_plugin_feather_memory.core.contracts import (
    Auth,
    ContractError,
    Lease,
    MemoryContext,
    MemoryItem,
)
from data.plugins.astrbot_plugin_feather_memory.core.identity import user_key_hash
from data.plugins.astrbot_plugin_feather_memory.core.timeutil import format_ts


def _lease(clock, instance: str = "A", expires_in: int = 300) -> Lease:
    return Lease(
        instance_id=instance,
        started_at=format_ts(clock.now()),
        refreshed_at=format_ts(clock.now()),
        expires_at=format_ts(clock.now() + timedelta(seconds=expires_in)),
        source="feather_memory/0.1.0",
    )


def _auth(clock, user_key: str = "aiocqhttp:1", *, auto: bool = True) -> Auth:
    return Auth(
        user_key_hash=user_key_hash(user_key),
        generated_at=format_ts(clock.now()),
        expires_at=format_ts(clock.now() + timedelta(days=180)),
        auto_history=auto,
        store_topic=False,
        source="feather_memory/0.1.0",
    )


def _context(clock, revision: int, *, expires_in_days: int = 30) -> MemoryContext:
    return MemoryContext(
        revision=revision,
        generated_at=format_ts(clock.now()),
        expires_at=format_ts(clock.now() + timedelta(days=expires_in_days)),
        source="feather_memory/0.1.0",
        scope="private",
        items=(MemoryItem(kind="preference", text="喜欢温柔"),),
        text="这位用户喜欢温柔。",
    )


def test_lease_roundtrip_and_owner_check(feed, clock):
    digest = "A"
    feed.write_lease(_lease(clock, digest))
    assert feed.read_lease().instance_id == digest
    assert feed.delete_lease("B") is False
    assert feed.layout.lease_path.exists()
    assert feed.delete_lease("A") is True
    assert feed.read_lease() is None


def test_delete_lease_rechecks_instance_under_lock(feed, clock):
    feed.write_lease(_lease(clock, "A"))
    done = threading.Event()
    result = {"value": None}

    with FileLock(feed.layout.lease_lock_path, timeout_ms=1000):
        feed._write_json(feed.layout.lease_path,
                         _lease(clock, "B").to_dict(), 4 * 1024)

        def remover():
            result["value"] = feed.delete_lease("A")
            done.set()

        thread = threading.Thread(target=remover)
        thread.start()
        assert not done.wait(0.2)
    thread.join(5)
    assert result["value"] is False
    assert feed.read_lease().instance_id == "B"


def test_atomic_write_leaves_no_temp_files(feed, clock):
    feed.write_lease(_lease(clock))
    leftovers = list(feed.layout.root.rglob("*.tmp-*"))
    assert leftovers == []


def test_corrupt_lease_is_none(feed):
    feed.layout.lease_path.write_text("{not json", encoding="utf-8")
    assert feed.read_lease() is None


def test_oversized_event_rejected(feed):
    path = feed.layout.events_dir / "big.json"
    path.write_bytes(b"{" + b" " * (17 * 1024) + b"}")
    with pytest.raises(ContractError):
        feed.read_event(path)


def test_context_revision_guard(feed, clock):
    digest = user_key_hash("aiocqhttp:1")
    assert feed.write_context(digest, _context(clock, 5)) == WRITE_WRITTEN
    assert feed.write_context(digest, _context(clock, 3)) == WRITE_STALE
    assert feed.read_context(digest).revision == 5


def test_context_corrupt_is_ignored(feed):
    digest = user_key_hash("aiocqhttp:1")
    path = feed.context_path(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]", encoding="utf-8")
    assert feed.read_context(digest) is None


def test_context_guard_blocks_stale_write(feed, clock):
    digest = user_key_hash("aiocqhttp:1")
    assert feed.write_context(digest, _context(clock, 2),
                              guard=lambda: False) == WRITE_STALE
    assert feed.read_context(digest) is None


def test_delete_context_waits_for_lock(feed, clock):
    digest = user_key_hash("aiocqhttp:1")
    feed.write_context(digest, _context(clock, 1))
    lock_path = feed.layout.context_dir / f"{digest}.lock"
    with FileLock(lock_path, timeout_ms=1000):
        assert feed.delete_context(digest, timeout_ms=30) is False
    assert feed.read_context(digest) is not None
    assert feed.delete_context(digest) is True
    assert feed.read_context(digest) is None


def test_delete_context_if_skips_when_guard_false(feed, clock):
    digest = user_key_hash("aiocqhttp:1")
    feed.write_context(digest, _context(clock, 1))
    assert feed.delete_context_if(digest, lambda: False) == "skipped"
    assert feed.read_context(digest) is not None
    assert feed.delete_context_if(digest, lambda: True) == "deleted"
    assert feed.read_context(digest) is None


def test_expire_context_makes_it_unusable(feed, clock):
    digest = user_key_hash("aiocqhttp:1")
    feed.write_context(digest, _context(clock, 1))
    assert feed.expire_context(digest) is True
    context = feed.read_context(digest)
    assert context is not None
    assert context.is_usable(clock.now()) is False


def test_expire_context_missing_file_returns_false(feed):
    assert feed.expire_context(user_key_hash("aiocqhttp:none")) is False


def test_context_lock_timeout(feed, clock):
    digest = user_key_hash("aiocqhttp:1")
    lock_path = feed.layout.context_dir / f"{digest}.lock"
    with FileLock(lock_path, timeout_ms=1000):
        result = feed.write_context(digest, _context(clock, 1), timeout_ms=30)
    assert result == WRITE_TIMEOUT


def test_concurrent_context_writes_end_with_highest_revision(feed, clock):
    digest = user_key_hash("aiocqhttp:1")
    barrier = threading.Barrier(2)

    def worker(revision: int) -> None:
        barrier.wait()
        feed.write_context(digest, _context(clock, revision), timeout_ms=5000)

    threads = [threading.Thread(target=worker, args=(5,)),
               threading.Thread(target=worker, args=(3,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert feed.read_context(digest).revision == 5


def test_remove_events_for_user_only(feed, clock, make_event):
    feed.write_event(make_event("01JA", "aiocqhttp:1"))
    feed.write_event(make_event("01JB", "aiocqhttp:2"))
    assert feed.remove_events_for_user("aiocqhttp:1") == 1
    names = [path.name for path in feed.iter_events()]
    assert names == ["01JB.json"]


def test_cleanup_removes_expired_and_old(feed, clock, make_event):
    now = clock.now()
    old_event = feed.event_path("01JOLD")
    feed.write_event(make_event("01JOLD"))
    old_stamp = (now - timedelta(days=8)).timestamp()
    os.utime(old_event, (old_stamp, old_stamp))
    feed.write_event(make_event("01JNEW"))

    expired_auth = _auth(clock, "aiocqhttp:1")
    expired_auth = Auth(
        user_key_hash=expired_auth.user_key_hash,
        generated_at=expired_auth.generated_at,
        expires_at=format_ts(now - timedelta(days=1)),
        auto_history=True, store_topic=False, source=expired_auth.source)
    feed.write_auth(expired_auth)
    valid_auth = _auth(clock, "aiocqhttp:2")
    feed.write_auth(valid_auth)

    digest = user_key_hash("aiocqhttp:3")
    feed.write_context(digest, _context(clock, 1, expires_in_days=-1))

    feed.write_lease(_lease(clock, "A", expires_in=-2 * 86400))

    removed = feed.cleanup(now)
    assert removed == {"events": 1, "auth": 1, "context": 1, "lease": 1}
    assert [path.name for path in feed.iter_events()] == ["01JNEW.json"]
    assert feed.read_auth(valid_auth.user_key_hash) is not None
    assert feed.read_context(digest) is None
    assert feed.read_lease() is None


def test_cleanup_skips_locked_expired_context(feed, clock):
    digest = user_key_hash("aiocqhttp:1")
    feed.write_context(digest, _context(clock, 1, expires_in_days=-1))
    lock_path = feed.layout.context_dir / f"{digest}.lock"
    with FileLock(lock_path, timeout_ms=1000):
        feed.cleanup(clock.now())
    assert feed.read_context(digest) is not None
    feed.cleanup(clock.now())
    assert feed.read_context(digest) is None


def test_cleanup_skips_locked_expired_auth(feed, clock):
    auth = _auth(clock, "aiocqhttp:1")
    expired = Auth(
        user_key_hash=auth.user_key_hash,
        generated_at=auth.generated_at,
        expires_at=format_ts(clock.now() - timedelta(days=1)),
        auto_history=True, store_topic=False, source=auth.source)
    feed.write_auth(expired)
    with FileLock(feed.auth_lock_path(expired.user_key_hash), timeout_ms=1000):
        feed.cleanup(clock.now())
    assert feed.read_auth(expired.user_key_hash) is not None
    feed.cleanup(clock.now())
    assert feed.read_auth(expired.user_key_hash) is None


def test_cleanup_skips_locked_stale_lease(feed, clock):
    feed.write_lease(_lease(clock, "A", expires_in=-2 * 86400))
    with FileLock(feed.layout.lease_lock_path, timeout_ms=1000):
        feed.cleanup(clock.now())
    assert feed.read_lease() is not None
    feed.cleanup(clock.now())
    assert feed.read_lease() is None


def test_cleanup_rereads_fresh_context_after_lock(feed, clock):
    digest = user_key_hash("aiocqhttp:1")
    feed.write_context(digest, _context(clock, 1, expires_in_days=-1))
    lock_path = feed.layout.context_dir / f"{digest}.lock"
    with FileLock(lock_path, timeout_ms=1000):
        feed.cleanup(clock.now())
        feed._write_json(feed.context_path(digest),
                         _context(clock, 2, expires_in_days=30).to_dict(),
                         8 * 1024)
    feed.cleanup(clock.now())
    context = feed.read_context(digest)
    assert context is not None and context.revision == 2


def test_cleanup_rereads_fresh_auth_after_lock(feed, clock):
    auth = _auth(clock, "aiocqhttp:1")
    expired = Auth(
        user_key_hash=auth.user_key_hash,
        generated_at=auth.generated_at,
        expires_at=format_ts(clock.now() - timedelta(days=1)),
        auto_history=True, store_topic=False, source=auth.source)
    feed.write_auth(expired)
    with FileLock(feed.auth_lock_path(expired.user_key_hash), timeout_ms=1000):
        feed.cleanup(clock.now())
        feed._write_json(feed.auth_path(expired.user_key_hash),
                         _auth(clock, "aiocqhttp:1").to_dict(), 4 * 1024)
    feed.cleanup(clock.now())
    assert feed.read_auth(expired.user_key_hash) is not None


def test_write_event_is_valid_json(feed, make_event):
    event = make_event("01JJSON")
    feed.write_event(event)
    payload = json.loads(feed.event_path("01JJSON").read_text("utf-8"))
    assert payload["event_id"] == "01JJSON"
