"""契约 golden：四个 schema 的解析、往返、未知字段与降级。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from data.plugins.astrbot_plugin_feather_memory.core.contracts import (
    Auth,
    ContractError,
    Lease,
    MemoryContext,
    ReadingEvent,
)

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
NOW = datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)
CONTEXT_NOW = datetime(2026, 11, 21, 21, 0, 0, tzinfo=timezone.utc)


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text("utf-8"))


def test_lease_golden_roundtrip() -> None:
    payload = load("lease.json")
    lease = Lease.parse(payload)
    assert lease.to_dict() == payload
    assert lease.is_valid(NOW)
    assert not lease.is_valid(datetime(2026, 11, 21, 12, 10, 0, tzinfo=timezone.utc))


def test_auth_golden_roundtrip() -> None:
    payload = load("auth.json")
    auth = Auth.parse(payload)
    assert auth.to_dict() == payload
    assert auth.is_valid(NOW)
    assert not auth.is_valid(datetime(2027, 5, 20, 12, 0, 0, tzinfo=timezone.utc))


def test_event_golden_roundtrip() -> None:
    payload = load("event.json")
    event = ReadingEvent.parse(payload)
    assert event.to_dict() == payload
    assert event.conversation_scope == "private"
    assert event.topic_key == "工作"
    assert event.cards[0].id == "swords_03"


def test_context_golden_roundtrip() -> None:
    payload = load("context.json")
    context = MemoryContext.parse(payload)
    assert context.to_dict() == payload
    assert context.is_usable(CONTEXT_NOW)
    assert not context.is_usable(datetime(2027, 1, 1, tzinfo=timezone.utc))


def test_context_rejects_future_generated_or_inverted_times() -> None:
    payload = load("context.json")
    far_future = payload | {"generated_at": "2026-11-21T21:10:00Z"}
    assert not MemoryContext.parse(far_future).is_usable(CONTEXT_NOW)
    inverted = payload | {"generated_at": "2026-12-21T20:15:05Z"}
    assert not MemoryContext.parse(inverted).is_usable(CONTEXT_NOW)


def test_unknown_fields_are_ignored() -> None:
    payload = load("event.json") | {"future_field": 1}
    assert ReadingEvent.parse(payload).event_id == "01J00000000000000000000001"
    payload = load("context.json") | {"future_field": {"a": 1}}
    assert MemoryContext.parse(payload).revision == 12


@pytest.mark.parametrize("name,parser,field", [
    ("lease.json", Lease.parse, "expires_at"),
    ("auth.json", Auth.parse, "auto_history"),
    ("event.json", ReadingEvent.parse, "spread"),
    ("context.json", MemoryContext.parse, "text"),
])
def test_missing_required_field_rejected(name, parser, field) -> None:
    payload = load(name)
    payload.pop(field)
    with pytest.raises(ContractError):
        parser(payload)


def test_wrong_schema_rejected() -> None:
    payload = load("event.json") | {"schema": "star_feather.reading_event.v2"}
    with pytest.raises(ContractError):
        ReadingEvent.parse(payload)


def test_event_accepts_escaped_identity_prefix() -> None:
    payload = load("event.json") | {"platform_id": "bot:1", "user_key": "bot%3A1:u%3A2"}
    assert ReadingEvent.parse(payload).platform_id == "bot:1"


def test_event_rejects_unmatched_identity_prefix() -> None:
    payload = load("event.json") | {"platform_id": "bot:1", "user_key": "bot:1:u:2"}
    with pytest.raises(ContractError):
        ReadingEvent.parse(payload)
    payload = load("event.json") | {"platform_id": "aiocqhttp", "user_key": "123456"}
    with pytest.raises(ContractError):
        ReadingEvent.parse(payload)


def test_event_allows_bare_uid_only_without_platform() -> None:
    payload = load("event.json") | {"platform_id": "", "user_key": "123456"}
    assert ReadingEvent.parse(payload).user_key == "123456"


def test_event_topic_must_be_enum() -> None:
    payload = load("event.json") | {"topic_key": "原问题全文"}
    with pytest.raises(ContractError):
        ReadingEvent.parse(payload)


def test_event_user_key_must_match_platform() -> None:
    payload = load("event.json") | {"platform_id": "telegram"}
    with pytest.raises(ContractError):
        ReadingEvent.parse(payload)


def test_event_scope_must_be_known() -> None:
    payload = load("event.json") | {"conversation_scope": "channel"}
    with pytest.raises(ContractError):
        ReadingEvent.parse(payload)


def test_event_card_requires_upright_bool() -> None:
    payload = load("event.json")
    payload["cards"][0]["upright"] = "yes"
    with pytest.raises(ContractError):
        ReadingEvent.parse(payload)


def test_auth_hash_must_be_sha256_hex() -> None:
    payload = load("auth.json") | {"user_key_hash": "not-a-hash"}
    with pytest.raises(ContractError):
        Auth.parse(payload)


def test_context_group_scope_rejected() -> None:
    payload = load("context.json") | {"scope": "group"}
    with pytest.raises(ContractError):
        MemoryContext.parse(payload)


def test_context_text_over_600_chars_not_usable() -> None:
    payload = load("context.json") | {"text": "记" * 601}
    context = MemoryContext.parse(payload)
    assert not context.is_usable(NOW)
