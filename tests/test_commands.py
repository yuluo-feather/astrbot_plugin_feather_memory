"""命令层文案与开关链行为。"""
from __future__ import annotations

from data.plugins.astrbot_plugin_feather_memory.app.chat import (
    GLOBAL_OFF_TEXT,
    HELP_TEXT,
    PRIVATE_ONLY_TEXT,
    handle_command,
)
from data.plugins.astrbot_plugin_feather_memory.app.service import MemoryService
from data.plugins.astrbot_plugin_feather_memory.core.identity import user_key_hash

USER = "aiocqhttp:123456"


def test_global_disabled_refuses_except_status(tmp_path, feed, store, clock):
    service = MemoryService(store, feed, global_enabled=False, version="0.1.0",
                            clock=clock.now)
    assert handle_command(service, USER, True, "开启") == GLOBAL_OFF_TEXT
    assert "全局：未启用" in handle_command(service, USER, True, "状态")


def test_full_command_flow(service):
    service.startup()
    assert "还没开启" in handle_command(service, USER, True, "")
    reply = handle_command(service, USER, True, "开启")
    assert "自动历史与主题记录一并打开" in reply
    assert "关闭 自动" in reply and "关闭 主题" in reply
    assert handle_command(service, USER, True, "记住 偏好 温柔一点") == "已保存 #1。"
    listing = handle_command(service, USER, True, "")
    assert "#1 [偏好] 温柔一点" in listing

    assert handle_command(service, USER, True, "开启 自动").startswith("自动历史已开启")
    assert handle_command(service, USER, True, "开启 主题").startswith("主题记录已开启")
    status = handle_command(service, USER, True, "状态")
    assert "自动历史：开" in status and "主题记录：开" in status
    assert "授权文件：有效" in status
    assert "记忆上下文：revision 1" in status

    assert handle_command(service, USER, True, "关闭 主题") == "主题记录已关闭；自动历史保持不变。"
    status = handle_command(service, USER, True, "状态")
    assert "自动历史：开" in status and "主题记录：关" in status

    assert handle_command(service, USER, True, "关闭 自动") == "自动历史已关闭；主题记录保持不变。"
    status = handle_command(service, USER, True, "状态")
    assert "自动历史：关" in status

    assert handle_command(service, USER, True, "开启 自动").startswith("自动历史已开启")
    assert handle_command(service, USER, True, "开启 主题").startswith("主题记录已开启")

    assert handle_command(service, USER, True, "忘记 1") == "已删除 #1。"
    assert handle_command(service, USER, True, "忘记 1") == "没有找到 #1。"
    listing = handle_command(service, USER, True, "")
    assert "#1" not in listing


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
    assert handle_command(service, USER, True, "清空 确认") == "已清空你的羽忆数据，并关闭自动历史与主题记录。"


def test_clear_confirmation_expires(service, clock):
    service.startup()
    service.enable(USER)
    assert handle_command(service, USER, True, "清空").startswith("确认清空")
    clock.advance(seconds=61)
    assert handle_command(service, USER, True, "清空 确认") == "确认已过期，请重新发送 /羽忆 清空。"


def test_standalone_confirm_clears(service):
    service.startup()
    handle_command(service, USER, True, "开启")
    handle_command(service, USER, True, "记住 喜欢温柔")
    assert handle_command(service, USER, True, "清空").startswith("确认清空你的")
    assert handle_command(service, USER, True, "确认") == "已清空你的羽忆数据，并关闭自动历史与主题记录。"


def test_confirm_without_request(service):
    service.startup()
    assert handle_command(service, USER, True, "确认") == "没有待确认或已过期的清空请求；发送 /羽忆 清空 重新发起。"


def test_forget_accepts_hash_prefix(service):
    service.startup()
    handle_command(service, USER, True, "开启")
    handle_command(service, USER, True, "记住 喜欢温柔")
    assert handle_command(service, USER, True, "忘记 #1") == "已删除 #1。"


def test_global_disabled_still_allows_close_and_clear(store, feed, clock):
    service = MemoryService(store, feed, global_enabled=False, version="0.1.0",
                            clock=clock.now)
    service.store.ensure_user(USER, clock.now())
    service.store.set_user_flags(
        USER, clock.now(), enabled=1, auto_history=1, store_topic=1)
    service.refresh_auth(USER, clock.now())
    service.store.save_memory(USER, "preference", "喜欢温柔", "喜欢温柔", clock.now())
    assert "已关闭羽忆" in handle_command(service, USER, True, "关闭")
    assert service.user_state(USER)["enabled"] == 0
    assert feed.read_auth(user_key_hash(USER)) is None
    service.store.save_memory(USER, "preference", "喜欢雨天", "喜欢雨天", clock.now())
    assert handle_command(service, USER, True, "清空").startswith("确认清空你的")
    assert handle_command(service, USER, True, "确认").startswith("已清空你的")
    assert service.store.count_memories(USER) == 0


def test_group_only_allows_status_and_disable(service):
    service.startup()
    service.enable(USER)
    assert handle_command(service, USER, False, "") == PRIVATE_ONLY_TEXT
    assert handle_command(service, USER, False, "记住 喜欢温柔") == PRIVATE_ONLY_TEXT
    assert handle_command(service, USER, False, "关闭 自动") == PRIVATE_ONLY_TEXT
    assert handle_command(service, USER, False, "关闭 主题") == PRIVATE_ONLY_TEXT
    status = handle_command(service, USER, False, "状态")
    assert "群聊内不展示个人记忆与主题" in status
    assert "已关闭羽忆" in handle_command(service, USER, False, "关闭")


def test_enable_auto_and_topic_require_prerequisites(service):
    service.startup()
    assert handle_command(service, USER, True, "开启 自动") == "请先发送 /羽忆 开启。"
    handle_command(service, USER, True, "开启")
    service.disable_auto(USER)
    assert handle_command(service, USER, True, "开启 主题") == "请先发送 /羽忆 开启 自动。"
    assert handle_command(service, USER, True, "开启 自动").startswith("自动历史已开启")
    assert handle_command(service, USER, True, "开启 主题").startswith("主题记录已开启")


def test_close_subcommands_on_unknown_user(service):
    service.startup()
    assert handle_command(service, USER, True, "关闭 自动") == "当前还没有羽忆记录；发送 /羽忆 开启 可开启。"
    assert handle_command(service, USER, True, "关闭 主题") == "当前还没有羽忆记录；发送 /羽忆 开启 可开启。"
    assert handle_command(service, USER, True, "关闭 随便") == "用法：/羽忆 关闭 | 关闭 自动 | 关闭 主题。"


def test_unknown_subcommand_shows_help(service):
    service.startup()
    assert handle_command(service, USER, True, "随便说说") == HELP_TEXT
