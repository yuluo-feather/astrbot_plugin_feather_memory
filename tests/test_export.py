"""用户导出、状态可见性与上下文质量门槛。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from data.plugins.astrbot_plugin_feather_memory.app.chat import handle_command
from data.plugins.astrbot_plugin_feather_memory.app.service import MemoryService
from data.plugins.astrbot_plugin_feather_memory.core.identity import user_key_hash

USER = "aiocqhttp:123456"


def _export_path(reply: str) -> Path:
    match = re.search(r"文件：(.+\.json)", reply)
    assert match is not None, reply
    return Path(match.group(1).strip())


def test_export_writes_required_fields_without_identifiers(service):
    service.startup()
    service.enable(USER)
    service.remember(USER, "偏好 温柔一点")
    reply = handle_command(service, USER, True, "导出")
    assert "1 条主动保存" in reply

    path = _export_path(reply)
    assert path.exists()
    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert payload["data_type"] == "feather_memory.user_export"
    assert payload["data_version"] == 1
    assert payload["exported_at"].endswith("Z")
    assert payload["switches"] == {
        "enabled": True, "auto_history": True, "store_topic": True}
    assert payload["memories"][0]["category"] == "preference"
    assert payload["memories"][0]["category_label"] == "偏好"
    assert payload["memories"][0]["content"] == "温柔一点"

    assert USER not in raw
    assert "aiocqhttp" not in raw
    assert user_key_hash(USER) not in raw


def test_export_lists_topics_and_switches(service, feed, clock, make_event):
    service.startup()
    service.enable(USER)
    feed.write_event(make_event("01J1", USER, topic_key="工作"))
    service.consume_pending(clock.now())

    reply = handle_command(service, USER, True, "导出")
    payload = json.loads(_export_path(reply).read_text(encoding="utf-8"))
    assert payload["recent_topics"] == [
        {"topic": "工作", "count": 1, "last_at": payload["recent_topics"][0]["last_at"]}]


def test_export_contains_only_own_data(service):
    service.startup()
    service.enable(USER)
    service.enable("aiocqhttp:999")
    service.remember(USER, "偏好 温柔")
    service.remember("aiocqhttp:999", "偏好 别人的秘密")

    reply = handle_command(service, USER, True, "导出")
    raw = _export_path(reply).read_text(encoding="utf-8")
    assert "温柔" in raw
    assert "别人的秘密" not in raw


def test_export_unknown_user(service):
    service.startup()
    assert "还没有羽忆记录" in handle_command(service, USER, True, "导出")


def test_export_group_chat_refused(service):
    service.startup()
    service.enable(USER)
    assert handle_command(service, USER, False, "导出") != ""
    assert "私聊" in handle_command(service, USER, False, "导出")


def test_export_allowed_when_global_switch_off(store, feed, clock):
    service = MemoryService(store, feed, global_enabled=False, version="0.1.0",
                            clock=clock.now)
    service.store.ensure_user(USER, clock.now())
    service.store.save_memory(USER, "preference", "温柔", "温柔", clock.now())
    service.store.set_user_flags(USER, clock.now(), enabled=1)
    reply = handle_command(service, USER, True, "导出")
    assert "1 条主动保存" in reply
    assert _export_path(reply).exists()


def test_status_shows_context_details_and_last_consumption(
        service, feed, clock, make_event, enabled_user):
    feed.write_event(make_event("01J1", enabled_user))
    service.consume_pending(clock.now())
    context = feed.read_context(user_key_hash(enabled_user))
    assert context is not None

    text = handle_command(service, enabled_user, True, "状态")
    assert f"revision {context.revision}" in text
    assert f"{len(context.items)} 条 / {len(context.text)} 字" in text
    assert "生成于 2026-11-21" in text
    assert "最近消费：2026-11-21" in text


def test_status_without_context_says_none(service, enabled_user):
    text = handle_command(service, enabled_user, True, "状态")
    assert "记忆上下文：无" in text
    assert "最近消费：还没有" in text


def test_explicit_limit_is_five(service):
    service.startup()
    service.enable(USER)
    for index in range(1, 6):
        service.remember(USER, f"偏好{index}")
    context = service.feed.read_context(user_key_hash(USER))
    assert context is not None
    assert len(context.items) == 5
    assert all(item.kind == "preference" for item in context.items)
    assert "偏好5" in context.text


def test_five_explicit_leave_no_room_for_topics(service, feed, clock, make_event):
    service.startup()
    service.enable(USER)
    for index in range(1, 6):
        service.remember(USER, f"偏好{index}")
    feed.write_event(make_event("01J1", USER, topic_key="工作"))
    service.consume_pending(clock.now())

    context = service.feed.read_context(user_key_hash(USER))
    assert context is not None
    assert len(context.items) == 5
    assert all(item.kind == "preference" for item in context.items)
    assert "最近关注" not in context.text


def test_three_explicit_leave_room_for_topics(service, feed, clock, make_event):
    service.startup()
    service.enable(USER)
    for index in range(1, 4):
        service.remember(USER, f"偏好{index}")
    feed.write_event(make_event("01J1", USER, topic_key="工作"))
    service.consume_pending(clock.now())

    context = service.feed.read_context(user_key_hash(USER))
    assert context is not None
    assert [item.kind for item in context.items] == [
        "preference", "preference", "preference", "recent_topic"]


def test_min_topic_count_filters_context_but_keeps_stats(
        tmp_path, feed, clock, make_event):
    from data.plugins.astrbot_plugin_feather_memory.adapters.sqlite_store import (
        SqliteStore,
    )
    store = SqliteStore(tmp_path / "feather_memory.sqlite3")
    store.initialize()
    service = MemoryService(store, feed, global_enabled=True, version="0.1.0",
                            clock=clock.now, min_topic_count=2)
    service.startup()
    user = "aiocqhttp:1"
    service.enable(user)
    feed.write_event(make_event("01J1", user, topic_key="工作"))
    feed.write_event(make_event("01J2", user, topic_key="感情"))
    clock.advance(minutes=1)
    feed.write_event(make_event("01J3", user, topic_key="感情"))
    service.consume_pending(clock.now())

    context = feed.read_context(user_key_hash(user))
    assert context is not None
    assert [item.text for item in context.items] == ["感情（最近 2 次）"]
    stats = {(item.topic_key, item.count) for item in store.topic_stats(user, clock.now())}
    assert stats == {("工作", 1), ("感情", 2)}
