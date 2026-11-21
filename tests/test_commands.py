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
    assert "记忆上下文：有效 · revision 1" in status

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


def test_help_commands_are_executable(service):
    service.startup()
    commands = [
        "查看记忆", "查看", "列表", "导出", "",
        "记住 偏好 温柔一点", "修改 1 偏好 更温柔", "忘记 1",
        "清空",
        "开启", "开启 自动", "开启 主题",
        "关闭 自动", "关闭 主题", "关闭", "状态",
    ]
    for command in commands:
        assert handle_command(service, USER, True, command) != HELP_TEXT, command


def test_view_aliases_equal_bare_command(service):
    service.startup()
    service.enable(USER)
    service.remember(USER, "喜欢温柔")
    base = handle_command(service, USER, True, "")
    for alias in ("查看", "查看记忆", "列表"):
        assert handle_command(service, USER, True, alias) == base


def test_remember_usage_includes_example(service):
    service.startup()
    reply = handle_command(service, USER, True, "记住")
    assert "示例：/羽忆 记住 偏好 温柔一点" in reply


def test_forget_usage_points_to_view(service):
    service.startup()
    reply = handle_command(service, USER, True, "忘记 x")
    assert "/羽忆 查看" in reply


def test_modify_memory(service):
    service.startup()
    service.enable(USER)
    service.remember(USER, "偏好 温柔")
    assert handle_command(service, USER, True, "修改 1 更温柔") == "已更新 #1。"
    listing = handle_command(service, USER, True, "")
    assert "#1 [偏好] 更温柔" in listing
    assert handle_command(service, USER, True, "修改 #1 背景 学生") == "已更新 #1。"
    listing = handle_command(service, USER, True, "")
    assert "#1 [背景] 学生" in listing
    assert handle_command(service, USER, True, "修改 99 随便") == "没有找到 #99，旧内容未改变。"
    assert handle_command(service, USER, True, "修改 1").startswith("用法：/羽忆 修改")
    assert handle_command(service, USER, True, "修改 1 " + "长" * 200).endswith(
        "（内容过长，已截断到 160 字）。")


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
    assert handle_command(service, USER, True, "清空 确认") == (
        "已清空你的羽忆数据。只删除已有数据，之后仍会继续记录；"
        "要停止请发送 /羽忆 关闭。")


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
    assert handle_command(service, USER, True, "确认") == (
        "已清空你的羽忆数据。只删除已有数据，之后仍会继续记录；"
        "要停止请发送 /羽忆 关闭。")


def test_confirm_without_request(service):
    service.startup()
    assert handle_command(service, USER, True, "确认") == "没有待确认或已过期的清空请求；发送 /羽忆 清空 重新发起。"


def test_clear_opt_out_user_reports_no_recording(service):
    service.startup()
    assert handle_command(service, USER, True, "清空").startswith("确认清空")
    reply = handle_command(service, USER, True, "确认")
    assert reply.startswith("已清空你的羽忆数据。")
    assert "当前未开启自动记录" in reply
    row = service.user_state(USER)
    assert (row["enabled"], row["auto_history"], row["store_topic"]) == (0, 0, 0)
    auth = service.feed.read_auth(user_key_hash(USER))
    assert auth is not None and auth.auto_history is False


def test_forget_accepts_hash_prefix(service):
    service.startup()
    handle_command(service, USER, True, "开启")
    handle_command(service, USER, True, "记住 喜欢温柔")
    assert handle_command(service, USER, True, "忘记 #1") == "已删除 #1。"


def test_disable_failure_message(service, feed, monkeypatch, enabled_user):
    def boom(auth):
        raise OSError("disk full")

    monkeypatch.setattr(feed, "write_auth", boom)
    reply = handle_command(service, enabled_user, True, "关闭")
    assert reply.startswith("已关闭，但文件清理未完成（auth")


def test_clear_failure_message(service, feed, monkeypatch, enabled_user):
    service.remember(enabled_user, "喜欢温柔")
    monkeypatch.setattr(feed, "delete_context",
                        lambda digest, timeout_ms=1000: False)
    monkeypatch.setattr(feed, "expire_context",
                        lambda digest, timeout_ms=1000: False)
    assert handle_command(service, enabled_user, True, "清空").startswith("确认清空")
    reply = handle_command(service, enabled_user, True, "清空 确认")
    assert reply.startswith("已清空，但文件清理未完成（context")


def test_list_footer_has_delete_and_modify(service):
    service.startup()
    service.enable(USER)
    service.remember(USER, "喜欢温柔")
    listing = handle_command(service, USER, True, "")
    assert "删除：/羽忆 忘记 <id>；修改：/羽忆 修改 <id> <新内容>" in listing


def test_status_suggests_global_switch(store, feed, clock):
    service = MemoryService(store, feed, global_enabled=False, version="0.1.0",
                            clock=clock.now)
    assert "memory.enabled" in handle_command(service, USER, True, "状态")


def test_status_suggests_lease_wait(service, feed):
    service.startup()
    feed.layout.lease_path.unlink()
    assert "5–10 秒" in handle_command(service, USER, True, "状态")


def test_status_suggests_enable_and_auto(service):
    service.startup()
    assert "/羽忆 开启 打开总开关" in handle_command(service, USER, True, "状态")
    service.enable(USER)
    service.disable_auto(USER)
    assert "开启 自动" in handle_command(service, USER, True, "状态")


def test_status_suggests_auth_and_first_reading(service, feed):
    service.startup()
    service.enable(USER)
    feed.delete_auth(user_key_hash(USER))
    assert "刷新授权" in handle_command(service, USER, True, "状态")
    service.enable(USER)
    assert "私聊普通占卜" in handle_command(service, USER, True, "状态")


def test_status_suggests_pending_and_quiet_when_healthy(
        service, feed, clock, make_event):
    service.startup()
    service.enable(USER)
    feed.write_event(make_event("01J1", USER))
    assert "5 秒内" in handle_command(service, USER, True, "状态")
    service.consume_pending(clock.now())
    service.remember(USER, "喜欢温柔")
    assert "下一步：" not in handle_command(service, USER, True, "状态")


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
    auth = feed.read_auth(user_key_hash(USER))
    assert auth is not None and auth.auto_history is False
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
