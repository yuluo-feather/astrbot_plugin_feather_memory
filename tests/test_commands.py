"""命令层文案与开关链行为。"""
from __future__ import annotations

from data.plugins.astrbot_plugin_feather_memory.app.chat import (
    GLOBAL_OFF_TEXT,
    HELP_TEXT,
    PRIVATE_ONLY_TEXT,
    handle_command,
)
from data.plugins.astrbot_plugin_feather_memory.app.service import MemoryService

USER = "aiocqhttp:123456"


def test_global_disabled_refuses_except_status(tmp_path, feed, store, clock):
    service = MemoryService(store, feed, global_enabled=False, version="0.1.0",
                            clock=clock.now)
    assert handle_command(service, USER, True, "开启") == GLOBAL_OFF_TEXT
    assert "全局：未启用" in handle_command(service, USER, True, "状态")


def test_full_command_flow(service):
    service.startup()
    assert "还没开启" in handle_command(service, USER, True, "")
    assert "羽忆已开启" in handle_command(service, USER, True, "开启")
    assert handle_command(service, USER, True, "记住 偏好 温柔一点") == "已保存 #1。"
    listing = handle_command(service, USER, True, "")
    assert "#1 [偏好] 温柔一点" in listing
    assert "自动历史：关闭" in listing

    assert handle_command(service, USER, True, "开启 自动").startswith("自动历史已开启")
    assert handle_command(service, USER, True, "开启 主题").startswith("主题记录已开启")
    status = handle_command(service, USER, True, "状态")
    assert "自动历史：开" in status and "主题记录：开" in status
    assert "授权文件：有效" in status
    assert "记忆上下文：revision 1" in status

    assert handle_command(service, USER, True, "忘记 1") == "已删除 #1。"
    assert handle_command(service, USER, True, "忘记 1") == "没有找到 #1。"


def test_remember_category_prefix(service):
    service.startup()
    handle_command(service, USER, True, "开启")
    handle_command(service, USER, True, "记住 背景 我是学生")
    listing = handle_command(service, USER, True, "")
    assert "[背景] 我是学生" in listing


def test_remember_truncation_notice(service):
    service.startup()
    reply = handle_command(service, USER, True, "记住 " + "长" * 200)
    assert "已截断到 160 字" in reply


def test_clear_requires_confirmation(service, clock):
    service.startup()
    handle_command(service, USER, True, "开启")
    handle_command(service, USER, True, "记住 喜欢温柔")
    first = handle_command(service, USER, True, "清空")
    assert first.startswith("确认清空")
    assert handle_command(service, USER, True, "清空 确认") == "已清空羽忆数据，并关闭自动历史与主题记录。"


def test_clear_confirmation_expires(service, clock):
    service.startup()
    service.enable(USER)
    assert handle_command(service, USER, True, "清空").startswith("确认清空")
    clock.advance(seconds=61)
    assert handle_command(service, USER, True, "清空 确认") == "确认已过期，请重新发送 /羽忆 清空。"


def test_group_only_allows_status_and_disable(service):
    service.startup()
    service.enable(USER)
    assert handle_command(service, USER, False, "") == PRIVATE_ONLY_TEXT
    assert handle_command(service, USER, False, "记住 喜欢温柔") == PRIVATE_ONLY_TEXT
    status = handle_command(service, USER, False, "状态")
    assert "群聊内不展示个人记忆与主题" in status
    assert "已关闭羽忆" in handle_command(service, USER, False, "关闭")


def test_enable_auto_and_topic_require_prerequisites(service):
    service.startup()
    assert handle_command(service, USER, True, "开启 自动") == "请先发送 /羽忆 开启。"
    handle_command(service, USER, True, "开启")
    assert handle_command(service, USER, True, "开启 主题") == "请先发送 /羽忆 开启 自动。"


def test_unknown_subcommand_shows_help(service):
    service.startup()
    assert handle_command(service, USER, True, "随便说说") == HELP_TEXT
