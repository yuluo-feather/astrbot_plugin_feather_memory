"""身份键：与星羽核心同一套转义与降级口径。"""
from __future__ import annotations

from data.plugins.astrbot_plugin_feather_memory.core.identity import (
    build_user_key,
    escape_identity_part,
    user_key_hash,
)


def test_plain_ids_are_unchanged() -> None:
    assert build_user_key("aiocqhttp", "123456") == "aiocqhttp:123456"


def test_separators_are_escaped() -> None:
    assert build_user_key("bot:1", "u:2") == "bot%3A1:u%3A2"
    assert build_user_key("%", "50%") == "%25:50%25"
    assert escape_identity_part("a%b:c") == "a%25b%3Ac"


def test_missing_platform_falls_back_to_bare_uid() -> None:
    assert build_user_key("", "123456") == "123456"


def test_missing_sender_yields_empty_key() -> None:
    assert build_user_key("aiocqhttp", "") == ""
    assert build_user_key("aiocqhttp", "   ") == ""


def test_hash_is_stable_and_hex() -> None:
    digest = user_key_hash("aiocqhttp:123456")
    assert digest == user_key_hash("aiocqhttp:123456")
    assert len(digest) == 64
    assert digest != user_key_hash("aiocqhttp:123457")
