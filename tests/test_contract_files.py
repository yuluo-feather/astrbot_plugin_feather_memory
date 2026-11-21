"""契约文件级自测：真实路径、文件名、JSON 字段集合与读写往返。

与 golden JSON 对账：写入后文件的顶层字段集合必须与 golden 完全一致，
多一个少一个都算违约；未知字段只在“读”时忽略。
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from data.plugins.astrbot_plugin_feather_memory.adapters.memory_feed import (
    WRITE_TOO_LARGE,
)
from data.plugins.astrbot_plugin_feather_memory.core.contracts import (
    Auth,
    Card,
    Lease,
    MemoryContext,
    MemoryItem,
    ReadingEvent,
)
from data.plugins.astrbot_plugin_feather_memory.core.identity import user_key_hash
from data.plugins.astrbot_plugin_feather_memory.core.timeutil import format_ts

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
USER = "aiocqhttp:123456"
DIGEST = user_key_hash(USER)


def _golden(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text("utf-8"))


def _lease(clock) -> Lease:
    return Lease(
        instance_id="01JLEASETEST00000000000000",
        started_at=format_ts(clock.now()),
        refreshed_at=format_ts(clock.now()),
        expires_at=format_ts(clock.now() + timedelta(minutes=5)),
        source="feather_memory/0.1.0",
    )


def _auth(clock) -> Auth:
    return Auth(
        user_key_hash=DIGEST,
        generated_at=format_ts(clock.now()),
        expires_at=format_ts(clock.now() + timedelta(days=180)),
        auto_history=True,
        store_topic=False,
        source="feather_memory/0.1.0",
    )


def _event(clock) -> ReadingEvent:
    return ReadingEvent(
        event_id="01JEVENTTEST00000000000001",
        created_at=format_ts(clock.now()),
        source_version="0.11.0",
        platform_id="aiocqhttp",
        user_key=USER,
        conversation_scope="private",
        kind="spread",
        spread="羽时三刻",
        cards=(Card(id="swords_03", upright=True),),
        topic_key="工作",
        spirit_line_present=True,
    )


def _context(clock, revision: int = 1) -> MemoryContext:
    return MemoryContext(
        revision=revision,
        generated_at=format_ts(clock.now()),
        expires_at=format_ts(clock.now() + timedelta(days=30)),
        source="feather_memory/0.1.0",
        scope="private",
        items=(MemoryItem(kind="preference", text="喜欢温柔"),),
        text="这位用户喜欢温柔。",
    )


def test_shared_root_is_plugin_data_relative(tmp_path):
    from data.plugins.astrbot_plugin_feather_memory.adapters.memory_feed import (
        FeedLayout,
    )

    plugin_data = tmp_path / "plugin_data" / "feather_memory"
    layout = FeedLayout.from_plugin_data_dir(plugin_data)
    assert layout.root == tmp_path / "plugin_data" / "_shared" / "feather_memory" / "v1"
    layout.ensure()
    for directory in (layout.root, layout.auth_dir, layout.events_dir, layout.context_dir):
        assert directory.is_dir()


def test_lease_file_path_and_fields(feed, clock):
    feed.write_lease(_lease(clock))
    path = feed.layout.root / "lease.json"
    assert path.is_file()
    payload = json.loads(path.read_text("utf-8"))
    assert set(payload) == set(_golden("lease.json"))
    assert feed.read_lease() == _lease(clock)


def test_lease_without_auto_enroll_parses_false():
    payload = _golden("lease.json")
    payload.pop("auto_enroll", None)
    assert Lease.parse(payload).auto_enroll is False


def test_auth_file_path_and_fields(feed, clock):
    feed.write_auth(_auth(clock))
    path = feed.layout.auth_dir / f"{DIGEST}.json"
    assert path.is_file()
    payload = json.loads(path.read_text("utf-8"))
    assert set(payload) == set(_golden("auth.json"))
    assert payload["user_key_hash"] == DIGEST
    assert feed.read_auth(DIGEST) == _auth(clock)


def test_event_file_path_and_fields(feed, clock):
    feed.write_event(_event(clock))
    path = feed.layout.events_dir / "01JEVENTTEST00000000000001.json"
    assert path.is_file()
    payload = json.loads(path.read_text("utf-8"))
    assert set(payload) == set(_golden("event.json"))
    assert payload["cards"] == [{"id": "swords_03", "upright": True}]
    assert feed.read_event(path) == _event(clock)


def test_context_file_path_fields_and_lock(feed, clock):
    assert feed.write_context(DIGEST, _context(clock)) == "written"
    path = feed.layout.context_dir / f"{DIGEST}.json"
    assert path.is_file()
    payload = json.loads(path.read_text("utf-8"))
    assert set(payload) == set(_golden("context.json"))
    assert (feed.layout.context_dir / f"{DIGEST}.lock").exists()
    assert feed.read_context(DIGEST) == _context(clock)


def test_golden_payloads_read_through_feed(feed):
    (feed.layout.root / "lease.json").write_text(
        json.dumps(_golden("lease.json")), encoding="utf-8")
    (feed.layout.auth_dir / f"{DIGEST}.json").write_text(
        json.dumps(_golden("auth.json")), encoding="utf-8")
    event_path = feed.layout.events_dir / "01J00000000000000000000001.json"
    event_path.write_text(json.dumps(_golden("event.json")), encoding="utf-8")
    (feed.layout.context_dir / f"{DIGEST}.json").write_text(
        json.dumps(_golden("context.json")), encoding="utf-8")

    assert feed.read_lease().instance_id == "01J00000000000000000000000"
    assert feed.read_auth(DIGEST).auto_history is True
    assert feed.read_event(event_path).topic_key == "工作"
    assert feed.read_context(DIGEST).revision == 12


def test_context_over_size_cap_is_rejected(feed, clock):
    oversized = MemoryContext(
        revision=1,
        generated_at=format_ts(clock.now()),
        expires_at=format_ts(clock.now() + timedelta(days=30)),
        source="feather_memory/0.1.0",
        scope="private",
        items=(MemoryItem(kind="preference", text="长" * 9000),),
        text="长" * 9000,
    )
    assert feed.write_context(DIGEST, oversized) == WRITE_TOO_LARGE
    assert not feed.context_path(DIGEST).exists()
