"""宿主适配：AstrBot 注册符号、配置、数据目录、事件身份。

只有这一层 `import astrbot`；插件类必须定义在 main.py（AstrBot 按 main 模块路径
绑定 `@filter.command` handler），由本层转出 `register` / `filter` 等符号。
"""
from __future__ import annotations

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

from ..app.service import MemoryService
from ..core.timeutil import now_utc
from ..core.version import VERSION
from .memory_feed import FeedLayout, MemoryFeed
from .sqlite_store import SqliteStore

PLUGIN_NAME = "feather_memory"
PLUGIN_DESC = "羽忆：为星羽塔罗记住偏好与近期主题（需要星羽塔罗 0.11+ 的共享文件契约）"
TICK_SECONDS = 5
DB_FILENAME = "feather_memory.sqlite3"

__all__ = [
    "AstrBotConfig",
    "AstrMessageEvent",
    "Context",
    "Star",
    "filter",
    "register",
    "logger",
    "PLUGIN_NAME",
    "PLUGIN_DESC",
    "TICK_SECONDS",
    "build_service",
    "command_argument",
    "is_private_chat",
    "memory_enabled",
    "platform_id_from_event",
    "sender_id_from_event",
]


class _HostLog:
    """把 core/app 的 `%s` 日志转发给宿主 logger（loguru 用 `{}`，先格式化）。"""

    @staticmethod
    def _fmt(template: str, args: tuple) -> str:
        return template % args if args else template

    def info(self, template: str, *args) -> None:
        logger.info("[羽忆] " + self._fmt(template, args))

    def warning(self, template: str, *args) -> None:
        logger.warning("[羽忆] " + self._fmt(template, args))

    def error(self, template: str, *args) -> None:
        logger.error("[羽忆] " + self._fmt(template, args))

    def exception(self, template: str, *args) -> None:
        logger.exception("[羽忆] " + self._fmt(template, args))


def memory_enabled(config: AstrBotConfig | None) -> bool:
    try:
        section = (config or {}).get("memory") or {}
    except AttributeError:
        return False
    return bool(section.get("enabled", False)) if isinstance(section, dict) else False


def platform_id_from_event(event: AstrMessageEvent) -> str:
    """宿主适配器 ID；异常按空串处理（与核心侧降级一致）。"""
    try:
        return str(event.get_platform_id() or "").strip()
    except Exception:
        return ""


def _raw_sender_id(event: AstrMessageEvent) -> str:
    try:
        sender = getattr(getattr(event, "message_obj", None), "sender", None)
        return str(getattr(sender, "user_id", "") or "")
    except Exception:
        return ""


def sender_id_from_event(event: AstrMessageEvent) -> str:
    """两级降级：官方 get_sender_id() → 原始 sender.user_id（兼容 int 型 ID）。"""
    for getter in (lambda: event.get_sender_id(), lambda: _raw_sender_id(event)):
        try:
            value = str(getter() or "").strip()
        except Exception:
            continue
        if value:
            return value
    return ""


def is_private_chat(event: AstrMessageEvent) -> bool:
    """判不出时按群聊处理，与核心侧「宁可少记」口径一致。"""
    try:
        return bool(event.is_private_chat())
    except Exception:
        return False


def command_argument(event: AstrMessageEvent) -> str:
    """取 `/羽忆` 之后的完整参数串。

    AstrBot 的普通 str 参数只拿空格分隔后的第一个 token（`开启 自动` 只剩 `开启`），
    所以这里直接读整条消息，从命令名之后截取。
    """
    try:
        raw = str(event.get_message_str() or "").strip()
    except Exception:
        return ""
    index = raw.find("羽忆")
    if index < 0:
        return ""
    return raw[index + len("羽忆"):].strip()


def build_service(config: AstrBotConfig | None) -> MemoryService:
    data_dir = StarTools.get_data_dir(PLUGIN_NAME)
    layout = FeedLayout.from_plugin_data_dir(data_dir)
    return MemoryService(
        SqliteStore(data_dir / DB_FILENAME),
        MemoryFeed(layout),
        global_enabled=memory_enabled(config),
        version=VERSION,
        clock=now_utc,
        log=_HostLog(),
    )
