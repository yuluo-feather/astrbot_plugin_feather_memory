"""pytest 基座：把插件目录挂成 AstrBot 的运行时包路径，并在无框架时打桩。

导入约定与星羽一致：测试一律用 `data.plugins.astrbot_plugin_feather_memory.*`
（插件模块的唯一身份）；不要退回「目录进 sys.path + 顶层名」。
"""
from __future__ import annotations

import importlib
import importlib.machinery
import logging
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

_PLUGIN_DIR = Path(__file__).resolve().parents[1]
_PKG = "data.plugins.astrbot_plugin_feather_memory"


def _install_plugin_package() -> None:
    parts = _PKG.split(".")
    parent = None
    for index, part in enumerate(parts):
        name = ".".join(parts[:index + 1])
        module = sys.modules.get(name)
        if module is None:
            module = types.ModuleType(name)
            module.__path__ = [str(_PLUGIN_DIR)] if index == len(parts) - 1 else []
            module.__package__ = name
            module.__spec__ = importlib.machinery.ModuleSpec(name, None, is_package=True)
            sys.modules[name] = module
        if parent is not None:
            setattr(parent, part, module)
        parent = module


def _install_astrbot_stubs() -> None:
    try:
        import astrbot  # noqa: F401
        return
    except ImportError:
        pass

    class _Logger:
        @staticmethod
        def _noop(*args, **kwargs):
            return None

        info = warning = error = exception = debug = _noop

    class Context:
        pass

    class Star:
        def __init__(self, context=None):
            self.context = context

    class AstrBotConfig(dict):
        pass

    class AstrMessageEvent:
        pass

    class _Filter:
        @staticmethod
        def command(*args, **kwargs):
            def decorate(fn):
                return fn
            return decorate

        @staticmethod
        def llm_tool(*args, **kwargs):
            def decorate(fn):
                return fn
            return decorate

    class StarTools:
        data_dir: Path | None = None

        @classmethod
        def get_data_dir(cls, plugin_name=None):
            return Path(cls.data_dir or ".")

    def register(*args, **kwargs):
        def decorate(cls):
            return cls
        return decorate

    astrbot_mod = types.ModuleType("astrbot")
    astrbot_mod.__path__ = []
    api_mod = types.ModuleType("astrbot.api")
    api_mod.__path__ = []
    event_mod = types.ModuleType("astrbot.api.event")
    event_mod.__path__ = []
    star_mod = types.ModuleType("astrbot.api.star")
    star_mod.__path__ = []

    setattr(api_mod, "AstrBotConfig", AstrBotConfig)
    setattr(api_mod, "logger", _Logger())
    setattr(event_mod, "AstrMessageEvent", AstrMessageEvent)
    setattr(event_mod, "filter", _Filter())
    setattr(star_mod, "Context", Context)
    setattr(star_mod, "Star", Star)
    setattr(star_mod, "StarTools", StarTools)
    setattr(star_mod, "register", register)

    setattr(astrbot_mod, "api", api_mod)
    setattr(api_mod, "event", event_mod)
    setattr(api_mod, "star", star_mod)

    for name, module in {
        "astrbot": astrbot_mod,
        "astrbot.api": api_mod,
        "astrbot.api.event": event_mod,
        "astrbot.api.star": star_mod,
    }.items():
        sys.modules[name] = module


_install_plugin_package()
_install_astrbot_stubs()

_contracts = importlib.import_module(f"{_PKG}.core.contracts")
_feed = importlib.import_module(f"{_PKG}.adapters.memory_feed")
_store = importlib.import_module(f"{_PKG}.adapters.sqlite_store")
_service = importlib.import_module(f"{_PKG}.app.service")

if TYPE_CHECKING:
    from data.plugins.astrbot_plugin_feather_memory.adapters.memory_feed import (
        FeedLayout,
        MemoryFeed,
    )
    from data.plugins.astrbot_plugin_feather_memory.adapters.sqlite_store import (
        SqliteStore,
    )
    from data.plugins.astrbot_plugin_feather_memory.app.service import MemoryService
    from data.plugins.astrbot_plugin_feather_memory.core.contracts import (
        Card,
        ReadingEvent,
    )
else:
    Card = _contracts.Card
    ReadingEvent = _contracts.ReadingEvent
    FeedLayout = _feed.FeedLayout
    MemoryFeed = _feed.MemoryFeed
    SqliteStore = _store.SqliteStore
    MemoryService = _service.MemoryService


class MutableClock:
    def __init__(self, moment: datetime | None = None):
        self.moment = moment or datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.moment

    def advance(self, *, seconds: int = 0, days: int = 0, minutes: int = 0) -> None:
        self.moment += timedelta(seconds=seconds, days=days, minutes=minutes)


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock()


@pytest.fixture
def layout(tmp_path: Path) -> FeedLayout:
    return FeedLayout(tmp_path / "plugin_data" / "_shared" / "feather_memory" / "v1")


@pytest.fixture
def feed(layout: FeedLayout) -> MemoryFeed:
    return MemoryFeed(layout)


@pytest.fixture
def store(tmp_path: Path) -> SqliteStore:
    instance = SqliteStore(tmp_path / "feather_memory.sqlite3")
    instance.initialize()
    return instance


@pytest.fixture
def service(store: SqliteStore, feed: MemoryFeed, clock: MutableClock) -> MemoryService:
    return MemoryService(
        store,
        feed,
        global_enabled=True,
        version="0.1.0",
        clock=clock.now,
        log=logging.getLogger("feather_memory.tests"),
        instance_id="01JTESTINSTANCE00000000000",
    )


@pytest.fixture
def make_event(clock: MutableClock):
    def _make(event_id: str = "01JEVENT000000000000000001",
              user_key: str = "aiocqhttp:123456",
              *, kind: str = "spread", scope: str = "private",
              topic_key: str = "工作", created_at: str | None = None) -> ReadingEvent:
        from data.plugins.astrbot_plugin_feather_memory.core.timeutil import format_ts
        platform_id = user_key.split(":", 1)[0]
        return ReadingEvent(
            event_id=event_id,
            created_at=created_at or format_ts(clock.now()),
            source_version="0.11.0",
            platform_id=platform_id,
            user_key=user_key,
            conversation_scope=scope,
            kind=kind,
            spread="羽时三刻",
            cards=(Card(id="swords_03", upright=True),),
            topic_key=topic_key,
            spirit_line_present=True,
        )
    return _make


@pytest.fixture
def enabled_user(service: MemoryService, clock: MutableClock) -> str:
    user_key = "aiocqhttp:123456"
    service.startup()
    service.enable(user_key)
    service.enable_auto(user_key)
    service.enable_topic(user_key)
    return user_key
