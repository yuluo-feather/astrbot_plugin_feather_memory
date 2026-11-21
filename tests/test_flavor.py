"""回复尾巴：成功加「本羽」，失败与用法保持中性。"""
from __future__ import annotations

import re

import pytest
from data.plugins.astrbot_plugin_feather_memory.app import chat
from data.plugins.astrbot_plugin_feather_memory.app.chat import (
    FLAVOR_POOLS,
    GLOBAL_OFF_TEXT,
    PRIVATE_ONLY_TEXT,
    handle_command,
)
from data.plugins.astrbot_plugin_feather_memory.app.service import MemoryService

USER = "aiocqhttp:123456"


@pytest.fixture(autouse=True)
def _reset_flavor():
    chat._last_flavor.clear()
    yield
    chat._last_flavor.clear()


def _has_flavor(text: str) -> bool:
    for pool in FLAVOR_POOLS.values():
        for line in pool:
            pattern = re.escape(line).replace(r"\{id\}", r"\d+")
            if re.search(pattern, text):
                return True
    return False


def test_success_replies_add_one_flavor(service):
    service.startup()
    replies = [
        handle_command(service, USER, True, "开启"),
        handle_command(service, USER, True, "记住 偏好 温柔"),
        handle_command(service, USER, True, "修改 1 更温柔"),
        handle_command(service, USER, True, "忘记 1"),
        handle_command(service, USER, True, "关闭 自动"),
        handle_command(service, USER, True, "开启 自动"),
        handle_command(service, USER, True, "关闭 主题"),
        handle_command(service, USER, True, "开启 主题"),
        handle_command(service, USER, True, "关闭"),
    ]
    for reply in replies:
        assert _has_flavor(reply), reply


def test_view_and_status_add_generic_flavor(service):
    service.startup()
    service.enable(USER)
    assert _has_flavor(handle_command(service, USER, True, ""))
    assert _has_flavor(handle_command(service, USER, True, "查看"))
    assert _has_flavor(handle_command(service, USER, True, "状态"))


def test_flavor_replaces_memory_id(service):
    service.startup()
    service.enable(USER)
    reply = handle_command(service, USER, True, "记住 偏好 温柔")
    tail = reply.splitlines()[-1]
    templates = [line.format(id=1) for line in FLAVOR_POOLS["remember"]]
    assert tail in templates
    assert "#1" in tail


def test_errors_and_usage_stay_neutral(service):
    service.startup()
    replies = [
        handle_command(service, USER, True, "记住"),
        handle_command(service, USER, True, "忘记 x"),
        handle_command(service, USER, True, "修改 1"),
        handle_command(service, USER, True, "随便说说"),
        handle_command(service, USER, True, "关闭 随便"),
        handle_command(service, USER, False, ""),
    ]
    assert PRIVATE_ONLY_TEXT in replies
    for reply in replies:
        assert not _has_flavor(reply), reply


def test_global_off_and_failed_cleanup_stay_neutral(store, feed, clock, monkeypatch):
    service = MemoryService(store, feed, global_enabled=False, version="0.1.0",
                            clock=clock.now)
    status = handle_command(service, USER, True, "状态")
    assert "全局：未启用" in status
    assert not _has_flavor(status)
    assert handle_command(service, USER, True, "记住 x") == GLOBAL_OFF_TEXT

    service.global_enabled = True
    service.startup()
    service.enable(USER)
    service.remember(USER, "喜欢温柔")
    monkeypatch.setattr(feed, "delete_context",
                        lambda digest, timeout_ms=1000: False)
    monkeypatch.setattr(feed, "expire_context",
                        lambda digest, timeout_ms=1000: False)
    assert handle_command(service, USER, True, "清空").startswith("确认清空")
    reply = handle_command(service, USER, True, "清空 确认")
    assert reply.startswith("已清空，但文件清理未完成")
    assert not _has_flavor(reply)


def test_flavor_disabled_restores_plain_text(service):
    service.startup()
    service.flavor_enabled = False
    assert handle_command(service, USER, True, "开启") == (
        "羽忆已开启：自动历史与主题记录一并打开。"
        "需要单独关闭时用 /羽忆 关闭 自动 或 /羽忆 关闭 主题。")
    assert handle_command(service, USER, True, "记住 偏好 温柔") == "已保存 #1。"


def test_consecutive_same_action_avoids_repeat(service, monkeypatch):
    service.startup()
    monkeypatch.setattr(chat.random, "choice", lambda seq: seq[0])
    first = chat._with_flavor(service, "generic", "功能句")
    second = chat._with_flavor(service, "generic", "功能句")
    assert first.splitlines()[-1] != second.splitlines()[-1]
    assert first.splitlines()[-1] == FLAVOR_POOLS["generic"][0]
    assert second.splitlines()[-1] == FLAVOR_POOLS["generic"][1]


def test_random_is_drawn_once_per_reply(service, monkeypatch):
    service.startup()
    calls = []
    real_choice = chat.random.choice

    def counting(seq):
        calls.append(seq)
        return real_choice(seq)

    monkeypatch.setattr(chat.random, "choice", counting)
    handle_command(service, USER, True, "记住 偏好 温柔")
    assert len(calls) == 1

    calls.clear()
    service.flavor_enabled = False
    handle_command(service, USER, True, "记住 偏好 安静")
    assert calls == []


def test_revised_enable_flavors_present():
    assert "好，本羽开始替你记着了。" in FLAVOR_POOLS["enable"]
    assert "本子打开了，之后的事我都会记着。" in FLAVOR_POOLS["enable"]
    assert "好，之后你私聊里的占卜，我会留意的。" in FLAVOR_POOLS["enable_auto"]
    assert "自动历史开了，本羽开始记着了。" in FLAVOR_POOLS["enable_auto"]
