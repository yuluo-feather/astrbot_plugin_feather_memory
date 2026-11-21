"""命令层：把 `/羽忆 …` 的文本解析成服务调用，并生成回复文案（纯 Python）。"""
from __future__ import annotations

from .service import MemoryService

CATEGORY_LABELS = {
    "preference": "偏好",
    "background": "背景",
    "goal": "目标",
}

HELP_TEXT = (
    "羽忆命令：\n"
    "/羽忆 查看记忆（也可 /羽忆 查看、/羽忆 列表 或直接 /羽忆）\n"
    "/羽忆 记住 <内容>（可用「偏好 …」「背景 …」「目标 …」）\n"
    "/羽忆 修改 <id> <新内容>\n"
    "/羽忆 忘记 <id>\n"
    "/羽忆 清空（需 /羽忆 清空 确认）\n"
    "/羽忆 开启（一次打开总开关、自动历史、主题记录）\n"
    "/羽忆 开启 自动 | 开启 主题（单项细调）\n"
    "/羽忆 关闭 自动 | 关闭 主题（单项关闭）\n"
    "/羽忆 关闭（全关并清除授权、context、待处理事件）\n"
    "/羽忆 状态\n"
    "请不要保存密码、令牌或账号凭据。"
)

GLOBAL_OFF_TEXT = "羽忆未启用：请管理员在 AstrBot 插件配置里打开「羽忆 → 启用」。"
PRIVATE_ONLY_TEXT = "羽忆的记忆查看与保存只能在私聊里进行；群聊可用 /羽忆 关闭 与 /羽忆 状态。"


def _label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


def _list_text(service: MemoryService, user_key: str) -> str:
    user = service.user_state(user_key)
    if user is None or not user["enabled"]:
        return ("羽忆还没开启。发送 /羽忆 开启 打开总开关；"
                "之后可以用 /羽忆 记住 … 保存偏好。")

    memories, topics = service.list_display(user_key)
    lines = ["羽忆 · 已开启", "主动保存"]
    if memories:
        lines.extend(f"  #{entry.memory_id} [{_label(entry.category)}] {entry.content}"
                     for entry in memories)
    else:
        lines.append("  （还没有）")
    lines.append("近期主题（最近 180 天）")
    if topics:
        lines.extend(f"  {topic.topic_key} · 最近 {topic.count} 次" for topic in topics)
    else:
        lines.append("  （还没有）")
    if not user["auto_history"]:
        lines.append("自动历史：关闭（发送 /羽忆 开启 自动）")
    elif not user["store_topic"]:
        lines.append("主题记录：关闭（发送 /羽忆 开启 主题）")
    lines.append("删除：/羽忆 忘记 <id>；修改：/羽忆 修改 <id> <新内容>")
    return "\n".join(lines)


def _status_text(service: MemoryService, user_key: str, is_private: bool) -> str:
    info = service.status(user_key)
    lines = ["羽忆状态"]
    lines.append("全局：" + ("已启用" if info["global_enabled"] else "未启用"))
    lease = info["lease"]
    if info["lease_valid"] and lease is not None and lease.expires_at:
        from ..core.timeutil import parse_ts
        remaining = max(0, int((parse_ts(lease.expires_at) - service.clock()).total_seconds()))
        lines.append(
            f"租约：有效（剩余 {remaining // 60} 分 {remaining % 60} 秒，"
            f"实例 {lease.instance_id[:8]}）")
    else:
        lines.append("租约：无 / 已过期")

    if not is_private:
        lines.append("群聊内不展示个人记忆与主题。")
        return "\n".join(lines)

    user = info["user"]
    context = info["context"]
    context_usable = context is not None and context.is_usable(service.clock())
    if user is None or not user["enabled"]:
        lines.append("本用户：未开启")
        lines.append(f"待处理事件：{info['pending_events']} 条")
        _append_suggestions(lines, info, user, context_usable)
        return "\n".join(lines)

    lines.append("本用户：已开启")
    lines.append("自动历史：" + ("开" if user["auto_history"] else "关"))
    lines.append("主题记录：" + ("开" if user["store_topic"] else "关"))
    if info["auth_valid"]:
        lines.append("授权文件：有效")
    elif info["auth"] is not None:
        lines.append("授权文件：已过期")
    else:
        lines.append("授权文件：无")
    dirty = "是" if user["context_dirty"] else "否"
    if context_usable:
        lines.append(f"记忆上下文：revision {context.revision}（dirty={dirty}）")
    else:
        lines.append(f"记忆上下文：无（dirty={dirty}）")
    lines.append(f"待处理事件：{info['pending_events']} 条")
    _append_suggestions(lines, info, user, context_usable)
    return "\n".join(lines)


def _append_suggestions(lines: list[str], info: dict, user: dict | None,
                        context_usable: bool) -> None:
    items: list[str] = []
    if not info["global_enabled"]:
        items.append("请管理员在羽忆插件配置打开 memory.enabled。")
    elif not info["lease_valid"]:
        items.append("确认羽忆已启用；启动后等 5–10 秒再看租约。")
    elif user is None or not user["enabled"]:
        items.append("发送 /羽忆 开启 打开总开关。")
    elif not user["auto_history"]:
        items.append("发送 /羽忆 开启 自动；或直接 /羽忆 开启 一键打开。")
    elif not info["auth_valid"]:
        items.append("发送 /羽忆 开启 刷新授权。")
    elif not context_usable:
        items.append("先做一次私聊普通占卜；仍没有可检查星羽侧 "
                     "memory.feed_enabled / context_enabled。")
    if info["pending_events"] > 0:
        items.append("待处理事件会在 5 秒内被消费，稍等再看。")
    if items:
        lines.append("下一步：")
        lines.extend(f"  - {item}" for item in items)


def handle_command(service: MemoryService, user_key: str,
                   is_private: bool, raw_text: str) -> str:
    text = (raw_text or "").strip()
    head, _, rest = text.partition(" ")
    sub = head.strip()
    arg = rest.strip()

    if not is_private:
        if sub == "状态":
            pass
        elif sub == "关闭" and arg == "":
            pass
        else:
            return PRIVATE_ONLY_TEXT

    def _close() -> str:
        if arg == "":
            service.disable(user_key)
            return ("已关闭羽忆：授权、记忆上下文与待处理事件已清除；"
                    "已保存的记忆仍保留，发送 /羽忆 清空 可彻底删除。")
        if arg == "自动":
            code = service.disable_auto(user_key)
            if code == "missing":
                return "当前还没有羽忆记录；发送 /羽忆 开启 可开启。"
            if code == "auth_failed":
                return "自动历史已关闭，但授权文件刷新失败；请重试或查看日志。"
            return "自动历史已关闭；主题记录保持不变。"
        if arg == "主题":
            code = service.disable_topic(user_key)
            if code == "missing":
                return "当前还没有羽忆记录；发送 /羽忆 开启 可开启。"
            if code == "auth_failed":
                return "主题记录已关闭，但授权文件刷新失败；请重试或查看日志。"
            return "主题记录已关闭；自动历史保持不变。"
        return "用法：/羽忆 关闭 | 关闭 自动 | 关闭 主题。"

    def _clear() -> str:
        if sub == "确认" or arg == "确认":
            if service.confirm_clear(user_key):
                return "已清空你的羽忆数据，并关闭自动历史与主题记录。"
            if sub == "确认":
                return "没有待确认或已过期的清空请求；发送 /羽忆 清空 重新发起。"
            return "确认已过期，请重新发送 /羽忆 清空。"
        service.request_clear(user_key)
        return ("确认清空你的全部羽忆数据？60 秒内发送 /羽忆 清空 确认 执行。")

    if not service.global_enabled:
        if sub == "状态":
            return _status_text(service, user_key, is_private)
        if sub == "关闭":
            return _close()
        if sub in ("清空", "确认"):
            return _clear()
        return GLOBAL_OFF_TEXT

    if sub == "" or sub in ("查看", "查看记忆", "列表"):
        return _list_text(service, user_key)

    if sub == "记住":
        if not arg:
            return ("用法：/羽忆 记住 <内容>（可加「偏好」「背景」「目标」前缀）。"
                    "示例：/羽忆 记住 偏好 温柔一点。"
                    "请不要保存密码、令牌或账号凭据。")
        memory_id, truncated = service.remember(user_key, arg)
        if not memory_id:
            return "内容为空，没有保存。"
        suffix = "（内容过长，已截断到 160 字）" if truncated else ""
        return f"已保存 #{memory_id}{suffix}。"

    if sub == "忘记":
        digits = arg.lstrip("#")
        if not digits.isdigit():
            return ("用法：/羽忆 忘记 <id>（发 /羽忆 查看 看列表里的 #12，"
                    "写 12 或 #12 都可以）。")
        memory_id = int(digits)
        if service.forget(user_key, memory_id):
            return f"已删除 #{memory_id}。"
        return f"没有找到 #{memory_id}。"

    if sub == "修改":
        parts = arg.split(maxsplit=1)
        if (len(parts) < 2 or not parts[0].lstrip("#").isdigit()
                or not parts[1].strip()):
            return ("用法：/羽忆 修改 <id> <新内容>。"
                    "示例：/羽忆 修改 #12 偏好 温柔一点。")
        memory_id = int(parts[0].lstrip("#"))
        code, truncated = service.update_memory(user_key, memory_id, parts[1])
        if code == "missing":
            return f"没有找到 #{memory_id}，旧内容未改变。"
        if code == "duplicate":
            return "已有一条相同内容，旧内容未改变。"
        if code == "empty":
            return "新内容为空，旧内容未改变。"
        suffix = "（内容过长，已截断到 160 字）" if truncated else ""
        return f"已更新 #{memory_id}{suffix}。"

    if sub in ("清空", "确认"):
        return _clear()

    if sub == "开启":
        if arg == "":
            result = service.enable(user_key)
            if not result.get("auth_ok", True):
                return "羽忆已开启，但授权文件写入失败；请重试或查看日志。"
            return ("羽忆已开启：自动历史与主题记录一并打开。"
                    "需要单独关闭时用 /羽忆 关闭 自动 或 /羽忆 关闭 主题。")
        if arg == "自动":
            code = service.enable_auto(user_key)
            if code == "not_enabled":
                return "请先发送 /羽忆 开启。"
            if code == "auth_failed":
                return "自动历史已开启，但授权文件写入失败；请重试或查看日志。"
            return "自动历史已开启：之后私聊的普通占卜会记入近期主题（不保存原始问题）。"
        if arg == "主题":
            code = service.enable_topic(user_key)
            if code == "not_enabled":
                return "请先发送 /羽忆 开启。"
            if code == "auto_required":
                return "请先发送 /羽忆 开启 自动。"
            if code == "auth_failed":
                return "主题记录已开启，但授权文件写入失败；请重试或查看日志。"
            return "主题记录已开启：事件里会带上固定主题枚举。"
        return "用法：/羽忆 开启 | 开启 自动 | 开启 主题。"

    if sub == "关闭":
        return _close()

    if sub == "状态":
        return _status_text(service, user_key, is_private)

    return HELP_TEXT
