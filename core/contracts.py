"""跨插件文件契约 v1：schema 常量、数据模型、解析与校验。

契约根目录：`data/plugin_data/_shared/feather_memory/v1/`。
四个对象：lease / auth / reading_event / memory_context。
解析规则：未知字段忽略；必填字段缺失、类型不符、枚举越界一律 ContractError。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .identity import escape_identity_part
from .timeutil import parse_ts
from .topics import TOPIC_KEYS

SCHEMA_LEASE = "star_feather.memory_lease.v1"
SCHEMA_AUTH = "star_feather.memory_auth.v1"
SCHEMA_EVENT = "star_feather.reading_event.v1"
SCHEMA_CONTEXT = "star_feather.memory_context.v1"

# 文件大小上限（字节）。事件 16 KB；context 8 KB；租约 / 授权 4 KB。
EVENT_MAX_BYTES = 16 * 1024
CONTEXT_MAX_BYTES = 8 * 1024
LEASE_MAX_BYTES = 4 * 1024
AUTH_MAX_BYTES = 4 * 1024

CONTEXT_TEXT_MAX_CHARS = 600
CONTEXT_ITEMS_MAX = 5
CONTEXT_TTL_DAYS = 30
AUTH_TTL_DAYS = 180
LEASE_TTL_SECONDS = 300
LEASE_REFRESH_SECONDS = 60
EVENT_RETENTION_DAYS = 7
READING_RETENTION_COUNT = 200
READING_RETENTION_DAYS = 180
ALLOWED_EVENT_KINDS = ("spread", "single")
ALLOWED_SCOPES = ("private", "group")

SOURCE = "feather_memory"


class ContractError(ValueError):
    """契约文件不合法；调用方按失败分级处理，不向上抛给宿主。"""


def _schema_of(payload: object, schema: str) -> dict:
    if not isinstance(payload, dict):
        raise ContractError(f"{schema}: payload must be an object")
    actual = payload.get("schema")
    if actual != schema:
        raise ContractError(f"{schema}: unexpected schema {actual!r}")
    return payload


def _str(payload: dict, key: str, schema: str, *, allow_empty: bool = False) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ContractError(f"{schema}: field '{key}' must be a string")
    if not allow_empty and not value:
        raise ContractError(f"{schema}: field '{key}' must not be empty")
    return value


def _bool(payload: dict, key: str, schema: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ContractError(f"{schema}: field '{key}' must be a boolean")
    return value


def _int(payload: dict, key: str, schema: str, *, minimum: int = 0) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{schema}: field '{key}' must be an integer")
    if value < minimum:
        raise ContractError(f"{schema}: field '{key}' must be >= {minimum}")
    return value


def _ts(payload: dict, key: str, schema: str) -> str:
    value = _str(payload, key, schema)
    try:
        parse_ts(value)
    except ValueError as exc:
        raise ContractError(f"{schema}: field '{key}' is not a valid timestamp: {exc}") from None
    return value


def _hash(value: str, schema: str) -> str:
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ContractError(f"{schema}: user_key_hash must be sha256 hex")
    return value


@dataclass(frozen=True, slots=True)
class Card:
    id: str
    upright: bool

    def to_dict(self) -> dict:
        return {"id": self.id, "upright": self.upright}

    @classmethod
    def parse(cls, payload: object, schema: str) -> "Card":
        if not isinstance(payload, dict):
            raise ContractError(f"{schema}: card must be an object")
        return cls(id=_str(payload, "id", schema), upright=_bool(payload, "upright", schema))


@dataclass(frozen=True, slots=True)
class Lease:
    instance_id: str
    started_at: str
    refreshed_at: str
    expires_at: str
    source: str

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_LEASE,
            "instance_id": self.instance_id,
            "started_at": self.started_at,
            "refreshed_at": self.refreshed_at,
            "expires_at": self.expires_at,
            "source": self.source,
        }

    def is_valid(self, now) -> bool:
        try:
            return now < parse_ts(self.expires_at)
        except ValueError:
            return False

    @classmethod
    def parse(cls, payload: object) -> "Lease":
        data = _schema_of(payload, SCHEMA_LEASE)
        return cls(
            instance_id=_str(data, "instance_id", SCHEMA_LEASE),
            started_at=_ts(data, "started_at", SCHEMA_LEASE),
            refreshed_at=_ts(data, "refreshed_at", SCHEMA_LEASE),
            expires_at=_ts(data, "expires_at", SCHEMA_LEASE),
            source=_str(data, "source", SCHEMA_LEASE),
        )


@dataclass(frozen=True, slots=True)
class Auth:
    user_key_hash: str
    generated_at: str
    expires_at: str
    auto_history: bool
    store_topic: bool
    source: str

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_AUTH,
            "user_key_hash": self.user_key_hash,
            "generated_at": self.generated_at,
            "expires_at": self.expires_at,
            "auto_history": self.auto_history,
            "store_topic": self.store_topic,
            "source": self.source,
        }

    def is_valid(self, now) -> bool:
        try:
            return now < parse_ts(self.expires_at)
        except ValueError:
            return False

    @classmethod
    def parse(cls, payload: object) -> "Auth":
        data = _schema_of(payload, SCHEMA_AUTH)
        return cls(
            user_key_hash=_hash(_str(data, "user_key_hash", SCHEMA_AUTH), SCHEMA_AUTH),
            generated_at=_ts(data, "generated_at", SCHEMA_AUTH),
            expires_at=_ts(data, "expires_at", SCHEMA_AUTH),
            auto_history=_bool(data, "auto_history", SCHEMA_AUTH),
            store_topic=_bool(data, "store_topic", SCHEMA_AUTH),
            source=_str(data, "source", SCHEMA_AUTH),
        )


@dataclass(frozen=True, slots=True)
class ReadingEvent:
    event_id: str
    created_at: str
    source_version: str
    platform_id: str
    user_key: str
    conversation_scope: str
    kind: str
    spread: str
    cards: tuple[Card, ...] = field(default_factory=tuple)
    topic_key: str = ""
    spirit_line_present: bool = False

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_EVENT,
            "event_id": self.event_id,
            "created_at": self.created_at,
            "source_version": self.source_version,
            "platform_id": self.platform_id,
            "user_key": self.user_key,
            "conversation_scope": self.conversation_scope,
            "kind": self.kind,
            "spread": self.spread,
            "cards": [card.to_dict() for card in self.cards],
            "topic_key": self.topic_key,
            "spirit_line_present": self.spirit_line_present,
        }

    @classmethod
    def parse(cls, payload: object) -> "ReadingEvent":
        data = _schema_of(payload, SCHEMA_EVENT)
        platform_id = _str(data, "platform_id", SCHEMA_EVENT, allow_empty=True)
        user_key = _str(data, "user_key", SCHEMA_EVENT)
        if ":" in user_key:
            prefix = user_key.split(":", 1)[0]
            if prefix != escape_identity_part(platform_id):
                raise ContractError(f"{SCHEMA_EVENT}: user_key platform does not match platform_id")
        elif platform_id:
            raise ContractError(f"{SCHEMA_EVENT}: user_key must be 'platform:uid'")
        scope = _str(data, "conversation_scope", SCHEMA_EVENT)
        if scope not in ALLOWED_SCOPES:
            raise ContractError(f"{SCHEMA_EVENT}: conversation_scope must be one of {ALLOWED_SCOPES}")
        topic_key = _str(data, "topic_key", SCHEMA_EVENT, allow_empty=True)
        if topic_key and topic_key not in TOPIC_KEYS:
            raise ContractError(f"{SCHEMA_EVENT}: topic_key must be a fixed enum value")
        cards_raw = data.get("cards")
        if not isinstance(cards_raw, list):
            raise ContractError(f"{SCHEMA_EVENT}: field 'cards' must be a list")
        cards = tuple(Card.parse(card, SCHEMA_EVENT) for card in cards_raw)
        return cls(
            event_id=_str(data, "event_id", SCHEMA_EVENT),
            created_at=_ts(data, "created_at", SCHEMA_EVENT),
            source_version=_str(data, "source_version", SCHEMA_EVENT),
            platform_id=platform_id,
            user_key=user_key,
            conversation_scope=scope,
            kind=_str(data, "kind", SCHEMA_EVENT),
            spread=_str(data, "spread", SCHEMA_EVENT),
            cards=cards,
            topic_key=topic_key,
            spirit_line_present=_bool(data, "spirit_line_present", SCHEMA_EVENT),
        )


@dataclass(frozen=True, slots=True)
class MemoryItem:
    kind: str
    text: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "text": self.text}

    @classmethod
    def parse(cls, payload: object) -> "MemoryItem":
        if not isinstance(payload, dict):
            raise ContractError(f"{SCHEMA_CONTEXT}: item must be an object")
        return cls(
            kind=_str(payload, "kind", SCHEMA_CONTEXT),
            text=_str(payload, "text", SCHEMA_CONTEXT),
        )


@dataclass(frozen=True, slots=True)
class MemoryContext:
    revision: int
    generated_at: str
    expires_at: str
    source: str
    scope: str
    items: tuple[MemoryItem, ...] = field(default_factory=tuple)
    text: str = ""

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_CONTEXT,
            "revision": self.revision,
            "generated_at": self.generated_at,
            "expires_at": self.expires_at,
            "source": self.source,
            "scope": self.scope,
            "items": [item.to_dict() for item in self.items],
            "text": self.text,
        }

    def is_usable(self, now) -> bool:
        try:
            fresh = now < parse_ts(self.expires_at)
        except ValueError:
            return False
        return (
            fresh
            and self.scope == "private"
            and bool(self.text.strip())
            and len(self.text) <= CONTEXT_TEXT_MAX_CHARS
            and len(self.items) <= CONTEXT_ITEMS_MAX
        )

    @classmethod
    def parse(cls, payload: object) -> "MemoryContext":
        data = _schema_of(payload, SCHEMA_CONTEXT)
        scope = _str(data, "scope", SCHEMA_CONTEXT)
        if scope != "private":
            raise ContractError(f"{SCHEMA_CONTEXT}: scope must be 'private' in v1")
        items_raw = data.get("items")
        if not isinstance(items_raw, list):
            raise ContractError(f"{SCHEMA_CONTEXT}: field 'items' must be a list")
        return cls(
            revision=_int(data, "revision", SCHEMA_CONTEXT),
            generated_at=_ts(data, "generated_at", SCHEMA_CONTEXT),
            expires_at=_ts(data, "expires_at", SCHEMA_CONTEXT),
            source=_str(data, "source", SCHEMA_CONTEXT),
            scope=scope,
            items=tuple(MemoryItem.parse(item) for item in items_raw),
            text=_str(data, "text", SCHEMA_CONTEXT, allow_empty=True),
        )
