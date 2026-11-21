"""命令层：把 `/羽忆 …` 的文本解析成服务调用，并生成回复文案（纯 Python）。"""
from __future__ import annotations

import random

from ..core.categories import category_label
from ..core.timeutil import parse_ts
from .service import MemoryService

HELP_TEXT = (
    "羽忆命令：\n"
    "/羽忆 查看记忆（也可 /羽忆 查看、/羽忆 列表 或直接 /羽忆）\n"
    "/羽忆 导出（把本人数据写入 plugin_data，仅私聊）\n"
    "/羽忆 记住 <内容>（可用「偏好 …」「背景 …」「目标 …」）\n"
    "/羽忆 修改 <id> <新内容>\n"
    "/羽忆 忘记 <id>\n"
    "/羽忆 清空（只删已有数据，需 /羽忆 清空 确认；要停止请用 /羽忆 关闭）\n"
    "/羽忆 开启（一次打开总开关、自动历史、主题记录）\n"
    "/羽忆 开启 自动 | 开启 主题（单项细调）\n"
    "/羽忆 关闭 自动 | 关闭 主题（单项关闭）\n"
    "/羽忆 关闭（全关并清除授权、context、待处理事件）\n"
    "/羽忆 状态\n"
    "请不要保存密码、令牌或账号凭据。"
)

GLOBAL_OFF_TEXT = "羽忆未启用：请管理员在 AstrBot 插件配置里打开「羽忆 → 启用」。"
PRIVATE_ONLY_TEXT = "羽忆的记忆查看与保存只能在私聊里进行；群聊可用 /羽忆 关闭 与 /羽忆 状态。"

FLAVOR_POOLS = {
    "remember": (
        "记下了，第 #{id} 条。你说的，我都记着呢。",
        "好，#{id}。本羽记性很好。",
    ),
    "modify": (
        "改好了，#{id} 现在是这个样子。",
        "嗯，改过来了。",
    ),
    "forget": (
        "忘掉了 #{id}。往事如烟。",
        "好，忘了。",
    ),
    "enable": (
        "好，本羽开始替你记着了。",
        "本子打开了，之后的事我都会记着。",
    ),
    "enable_auto": (
        "好，之后你私聊里的占卜，我会留意的。",
        "自动历史开了，本羽开始记着了。",
    ),
    "enable_topic": (
        "主题也记上了。",
        "好，本羽知道该记哪些了。",
    ),
    "disable": (
        "好，本羽先合上本子。已存的记忆还在。",
        "先停在这儿，本羽不看了。",
    ),
    "disable_auto": (
        "好，自动历史先停了。",
        "本羽不记新的了，旧的还在。",
    ),
    "disable_topic": (
        "主题先不记了。",
        "好，只留已经记下的。",
    ),
    "clear": (
        "本羽都删干净了。",
        "清干净了，还有需要本羽的地方吗？",
    ),
    "export": (
        "拿去吧，这是本羽替你记下的全部。",
        "本羽都收拾好放在这儿了，别弄丢。",
    ),
    "generic": (
        "本羽不替你做决定，只会陪你记着。",
        "想不起来的时候，来问本羽。",
        "说过的，都算数。",
    ),
}

_last_flavor: dict[str, str] = {}


def _pick_flavor(action: str) -> str:
    pool = FLAVOR_POOLS[action]
    last = _last_flavor.get(action)
    candidates = [line for line in pool if line != last] or list(pool)
    choice = random.choice(candidates)
    _last_flavor[action] = choice
    return choice


def _with_flavor(service: MemoryService, action: str, text: str,
                 *, memory_id: int | None = None) -> str:
    if not getattr(service, "flavor_enabled", True):
        return text
    flavor = _pick_flavor(action)
    if memory_id is not None:
        flavor = flavor.format(id=memory_id)
    return f"{text}\n{flavor}" if text else flavor


def _short_ts(value: str | None) -> str:
    if not value:
        return "未知"
    try:
        return parse_ts(value).strftime("%Y-%m-%d %H:%M") + " UTC"
    except (TypeError, ValueError):
        return value


def _last_reading_text(value: str | None) -> str:
    return _short_ts(value) if value else "还没有"


def _clear_effect_text(service: MemoryService, user_key: str) -> str:
    user = service.user_state(user_key)
    if user is not None and user["enabled"] and user["auto_history"]:
        return "只删除已有数据，之后仍会继续记录；要停止请发送 /羽忆 关闭。"
    return "只删除已有数据；当前未开启自动记录，之后不会继续记录；要开启请发送 /羽忆 开启。"


def _list_text(service: MemoryService, user_key: str) -> str:
    user = service.user_state(user_key)
    if user is None or not user["enabled"]:
        return ("羽忆还没开启。发送 /羽忆 开启 打开总开关；"
                "之后可以用 /羽忆 记住 … 保存偏好。")

    memories, topics = service.list_display(user_key)
    lines = ["羽忆 · 已开启", "主动保存"]
    if memories:
        lines.extend(f"  #{entry.memory_id} [{category_label(entry.category)}] {entry.content}"
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
    return _with_flavor(service, "generic", "\n".join(lines))


def _status_text(service: MemoryService, user_key: str, is_private: bool) -> str:
    info = service.status(user_key)
    lines = ["羽忆状态"]
    lines.append("全局：" + ("已启用" if info["global_enabled"] else "未启用"))
    lease = info["lease"]
    if info["lease_valid"] and lease is not None and lease.expires_at:
        remaining = max(0, int((parse_ts(lease.expires_at) - service.clock()).total_seconds()))
        lines.append(
            f"租约：有效（剩余 {remaining // 60} 分 {remaining % 60} 秒，"
            f"实例 {lease.instance_id[:8]}）")
    else:
        lines.append("租约：无 / 已过期")

    if not is_private:
        lines.append("群聊内不展示个人记忆与主题。")
        return "\n".join(lines)

    def _finish() -> str:
        text = "\n".join(lines)
        return _with_flavor(service, "generic", text) if info["global_enabled"] else text

    user = info["user"]
    context = info["context"]
    context_usable = context is not None and context.is_usable(service.clock())
    if user is None or not user["enabled"]:
        lines.append("本用户：未开启")
        lines.append(f"待处理事件：{info['pending_events']} 条")
        lines.append("最近消费：" + _last_reading_text(info.get("last_reading_at")))
        _append_suggestions(lines, info, user, context_usable)
        return _finish()

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
    if context is None:
        lines.append(f"记忆上下文：无（dirty={dirty}）")
    elif context_usable:
        lines.append(
            f"记忆上下文：有效 · revision {context.revision} · "
            f"{len(context.items)} 条 / {len(context.text)} 字 · "
            f"生成于 {_short_ts(context.generated_at)}（dirty={dirty}）")
    else:
        lines.append(
            f"记忆上下文：已过期 · revision {context.revision} · "
            f"生成于 {_short_ts(context.generated_at)}（dirty={dirty}）")
    lines.append("最近消费：" + _last_reading_text(info.get("last_reading_at")))
    lines.append(f"待处理事件：{info['pending_events']} 条")
    _append_suggestions(lines, info, user, context_usable)
    return _finish()


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
            _, failures = service.disable(user_key)
            if failures:
                return ("已关闭，但文件清理未完成（"
                        + "/".join(failures)
                        + "），已标记待重试，请稍后再试或查看日志。")
            return _with_flavor(
                service, "disable",
                "已关闭羽忆：记忆上下文与待处理事件已清除，授权已标记为不可投递；"
                "已保存的记忆仍保留，发送 /羽忆 清空 可彻底删除。")
        if arg == "自动":
            code = service.disable_auto(user_key)
            if code == "missing":
                return "当前还没有羽忆记录；发送 /羽忆 开启 可开启。"
            if code == "auth_failed":
                return "自动历史已关闭，但授权文件刷新失败；请重试或查看日志。"
            return _with_flavor(service, "disable_auto",
                                "自动历史已关闭；主题记录保持不变。")
        if arg == "主题":
            code = service.disable_topic(user_key)
            if code == "missing":
                return "当前还没有羽忆记录；发送 /羽忆 开启 可开启。"
            if code == "auth_failed":
                return "主题记录已关闭，但授权文件刷新失败；请重试或查看日志。"
            return _with_flavor(service, "disable_topic",
                                "主题记录已关闭；自动历史保持不变。")
        return "用法：/羽忆 关闭 | 关闭 自动 | 关闭 主题。"

    def _clear() -> str:
        if sub == "确认" or arg == "确认":
            failures = service.confirm_clear(user_key)
            if failures is None:
                if sub == "确认":
                    return "没有待确认或已过期的清空请求；发送 /羽忆 清空 重新发起。"
                return "确认已过期，请重新发送 /羽忆 清空。"
            if failures:
                return ("已清空，但文件清理未完成（"
                        + "/".join(failures)
                        + "），已标记待重试，请稍后再试或查看日志。")
            return _with_flavor(
                service, "clear",
                "已清空你的羽忆数据。" + _clear_effect_text(service, user_key))
        service.request_clear(user_key)
        return ("确认清空你的全部羽忆数据？60 秒内发送 /羽忆 清空 确认 执行。"
                + _clear_effect_text(service, user_key))

    def _export() -> str:
        try:
            exported = service.export_data(user_key)
        except OSError:
            return "导出失败：无法写入导出文件，请查看日志后重试。"
        if exported is None:
            return "还没有羽忆记录可以导出；先发送 /羽忆 开启 并保存一些内容。"
        path, payload = exported
        return _with_flavor(
            service, "export",
            f"已导出你的羽忆数据：{len(payload['memories'])} 条主动保存，"
            f"{len(payload['recent_topics'])} 个近期主题。\n"
            f"文件：{path}\n"
            "发送 /羽忆 清空 会一并删除导出副本；文件不含账号标识与原始占卜问题。")

    if not service.global_enabled:
        if sub == "状态":
            return _status_text(service, user_key, is_private)
        if sub == "关闭":
            return _close()
        if sub in ("清空", "确认"):
            return _clear()
        if sub == "导出":
            return _export()
        return GLOBAL_OFF_TEXT

    if sub == "" or sub in ("查看", "查看记忆", "列表"):
        return _list_text(service, user_key)

    if sub == "导出":
        return _export()

    if sub == "记住":
        if not arg:
            return ("用法：/羽忆 记住 <内容>（可加「偏好」「背景」「目标」前缀）。"
                    "示例：/羽忆 记住 偏好 温柔一点。"
                    "请不要保存密码、令牌或账号凭据。")
        memory_id, truncated = service.remember(user_key, arg)
        if not memory_id:
            return "内容为空，没有保存。"
        suffix = "（内容过长，已截断到 160 字）" if truncated else ""
        return _with_flavor(service, "remember", f"已保存 #{memory_id}{suffix}。",
                            memory_id=memory_id)

    if sub == "忘记":
        digits = arg.lstrip("#")
        if not digits.isdigit():
            return ("用法：/羽忆 忘记 <id>（发 /羽忆 查看 看列表里的 #12，"
                    "写 12 或 #12 都可以）。")
        memory_id = int(digits)
        if service.forget(user_key, memory_id):
            return _with_flavor(service, "forget", f"已删除 #{memory_id}。",
                                memory_id=memory_id)
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
        return _with_flavor(service, "modify", f"已更新 #{memory_id}{suffix}。",
                            memory_id=memory_id)

    if sub in ("清空", "确认"):
        return _clear()

    if sub == "开启":
        if arg == "":
            result = service.enable(user_key)
            if not result.get("auth_ok", True):
                return "羽忆已开启，但授权文件写入失败；请重试或查看日志。"
            return _with_flavor(
                service, "enable",
                "羽忆已开启：自动历史与主题记录一并打开。"
                "需要单独关闭时用 /羽忆 关闭 自动 或 /羽忆 关闭 主题。")
        if arg == "自动":
            code = service.enable_auto(user_key)
            if code == "not_enabled":
                return "请先发送 /羽忆 开启。"
            if code == "auth_failed":
                return "自动历史已开启，但授权文件写入失败；请重试或查看日志。"
            return _with_flavor(
                service, "enable_auto",
                "自动历史已开启：之后私聊的普通占卜会记入近期主题（不保存原始问题）。")
        if arg == "主题":
            code = service.enable_topic(user_key)
            if code == "not_enabled":
                return "请先发送 /羽忆 开启。"
            if code == "auto_required":
                return "请先发送 /羽忆 开启 自动。"
            if code == "auth_failed":
                return "主题记录已开启，但授权文件写入失败；请重试或查看日志。"
            return _with_flavor(service, "enable_topic",
                                "主题记录已开启：事件里会带上固定主题枚举。")
        return "用法：/羽忆 开启 | 开启 自动 | 开启 主题。"

    if sub == "关闭":
        return _close()

    if sub == "状态":
        return _status_text(service, user_key, is_private)

    return HELP_TEXT
