"""宿主适配层：身份读取的两级降级与异常兜底（不启动 AstrBot）。"""
from __future__ import annotations

from types import SimpleNamespace

from data.plugins.astrbot_plugin_feather_memory.adapters.host import (
    command_argument,
    is_private_chat,
    platform_id_from_event,
    sender_id_from_event,
)


class _Event:
    def __init__(self, *, sender_id=None, raw_sender_id=None, platform_id="aiocqhttp",
                 private=True, sender_raises=False, raw_raises=False,
                 platform_raises=False, private_raises=False):
        self._sender_id = sender_id
        self._sender_raises = sender_raises
        self._raw_raises = raw_raises
        self._platform_id = platform_id
        self._platform_raises = platform_raises
        self._private = private
        self._private_raises = private_raises
        self.message_obj = SimpleNamespace(
            sender=SimpleNamespace(user_id=raw_sender_id))

    def get_sender_id(self):
        if self._sender_raises:
            raise RuntimeError("no sender")
        return self._sender_id

    def get_platform_id(self):
        if self._platform_raises:
            raise RuntimeError("no platform")
        return self._platform_id

    def is_private_chat(self):
        if self._private_raises:
            raise RuntimeError("no scope")
        return self._private

    @property
    def raw_sender_id(self):
        return None


def test_sender_uses_official_getter_first():
    assert sender_id_from_event(_Event(sender_id="123")) == "123"


def test_sender_falls_back_to_raw_int_id():
    event = _Event(sender_id="", raw_sender_id=456)
    assert sender_id_from_event(event) == "456"


def test_sender_falls_back_when_getter_raises():
    event = _Event(sender_raises=True, raw_sender_id=789)
    assert sender_id_from_event(event) == "789"


def test_sender_empty_when_both_sources_fail():
    assert sender_id_from_event(_Event(sender_id="", raw_sender_id=None)) == ""
    assert sender_id_from_event(_Event(sender_raises=True, raw_raises=True)) == ""


def test_platform_exception_degrades_to_empty():
    assert platform_id_from_event(_Event(platform_raises=True)) == ""
    assert platform_id_from_event(_Event(platform_id="bot:1")) == "bot:1"


def test_scope_exception_degrades_to_group():
    assert is_private_chat(_Event(private_raises=True)) is False
    assert is_private_chat(_Event(private=True)) is True


class _MessageEvent:
    def __init__(self, message_str="", *, raises=False):
        self._message_str = message_str
        self._raises = raises

    def get_message_str(self):
        if self._raises:
            raise RuntimeError("no message")
        return self._message_str


def test_command_argument_keeps_full_text():
    assert command_argument(_MessageEvent("/羽忆 开启 自动")) == "开启 自动"
    assert command_argument(_MessageEvent("羽忆 记住 偏好 温柔 一点")) == "记住 偏好 温柔 一点"
    assert command_argument(_MessageEvent("@bot /羽忆 清空 确认")) == "清空 确认"


def test_command_argument_empty_cases():
    assert command_argument(_MessageEvent("/羽忆")) == ""
    assert command_argument(_MessageEvent("/羽忆   ")) == ""
    assert command_argument(_MessageEvent("别的命令")) == ""
    assert command_argument(_MessageEvent(raises=True)) == ""
