"""羽忆插件入口：插件类必须定义在本模块。

AstrBot 按 `metadata.module_path`（main）查找 `@register` 类与 `@filter.command`
handler；放在子模块会导致 handler 未被绑定（event 被当成 self）。宿主符号统一
从 adapters/host.py 转出，main.py 本身不直接 import astrbot。
"""
from __future__ import annotations

import asyncio

from .adapters.host import (
    PLUGIN_DESC,
    PLUGIN_NAME,
    TICK_SECONDS,
    AstrBotConfig,
    AstrMessageEvent,
    Context,
    Star,
    build_service,
    command_argument,
    filter,
    is_private_chat,
    logger,
    platform_id_from_event,
    register,
    sender_id_from_event,
)
from .app.chat import handle_command
from .core.identity import build_user_key
from .core.version import VERSION


@register(PLUGIN_NAME, "羽落", PLUGIN_DESC, VERSION)
class FeatherMemoryPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.service = build_service(config)
        self.config = config
        self._task: asyncio.Task | None = None
        self._fatal = ""

    async def initialize(self):
        try:
            await asyncio.to_thread(self.service.startup)
        except Exception as exc:
            self._fatal = f"{type(exc).__name__}: {exc}"
            logger.error(f"[羽忆] 启动失败：{self._fatal}")
            return
        logger.info(
            f"[羽忆] 已加载：全局={'开启' if self.service.global_enabled else '关闭'}；"
            f"数据目录={self.service.store.path.parent}；"
            f"共享目录={self.service.feed.layout.root}")
        self._task = asyncio.create_task(self._loop(), name="feather_memory_tick")

    async def _loop(self):
        while True:
            await asyncio.sleep(TICK_SECONDS)
            try:
                await asyncio.to_thread(self.service.tick)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"[羽忆] 后台任务失败：{type(exc).__name__}: {exc}")

    async def terminate(self):
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        try:
            await asyncio.to_thread(self.service.shutdown)
            logger.info("[羽忆] 已关闭：租约已删除（若属于本实例）")
        except Exception as exc:
            logger.error(f"[羽忆] 关闭失败：{type(exc).__name__}: {exc}")

    @filter.command("羽忆", desc="羽忆：查看/保存偏好与近期主题")
    async def feather_memory(self, event: AstrMessageEvent, text: str = ""):
        if self._fatal:
            return event.plain_result("羽忆暂时不可用，请查看日志后重载插件。")
        user_key = build_user_key(platform_id_from_event(event),
                                  sender_id_from_event(event))
        if not user_key:
            return event.plain_result("无法识别当前用户身份，羽忆没有执行任何操作。")
        try:
            argument = command_argument(event)
            if not argument and text.strip():
                argument = text.strip()
            reply = await asyncio.to_thread(
                handle_command, self.service, user_key,
                is_private_chat(event), argument)
        except Exception as exc:
            logger.error(f"[羽忆] 命令处理失败：{type(exc).__name__}: {exc}")
            reply = "羽忆暂时不可用，请稍后再试。"
        return event.plain_result(reply)


__all__ = ["FeatherMemoryPlugin", "VERSION"]
