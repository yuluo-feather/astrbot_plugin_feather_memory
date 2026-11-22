"""双来源合并：显式记忆优先，自动主题填充剩余位置，总长不超过 600 字。"""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import CONTEXT_ITEMS_MAX, CONTEXT_TEXT_MAX_CHARS

EXPLICIT_LIMIT = 5
TOPIC_PREFIX = "最近关注"


@dataclass(frozen=True, slots=True)
class ExplicitEntry:
    memory_id: int
    category: str
    content: str
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class TopicStat:
    topic_key: str
    count: int
    last_at: str


@dataclass(frozen=True, slots=True)
class ComposedItem:
    kind: str
    text: str


def _render(explicit: list[ExplicitEntry], topics: list[TopicStat]) -> str:
    parts = [_clean(entry.content) for entry in explicit if _clean(entry.content)]
    if topics:
        parts.append(TOPIC_PREFIX + "、".join(
            f"{topic.topic_key}（最近 {topic.count} 次）" for topic in topics))
    if not parts:
        return ""
    return "这位用户" + "；".join(parts) + "。"


def _clean(text: str) -> str:
    return (text or "").strip().rstrip("。；; ")


def compose_context(
    explicit: list[ExplicitEntry],
    topics: list[TopicStat],
    *,
    max_items: int = CONTEXT_ITEMS_MAX,
    explicit_limit: int = EXPLICIT_LIMIT,
    text_limit: int = CONTEXT_TEXT_MAX_CHARS,
) -> tuple[list[ComposedItem], str]:
    picked = [entry for entry in explicit[:explicit_limit] if _clean(entry.content)]
    slots = max(0, max_items - len(picked))
    picked_topics = [topic for topic in topics[:slots]
                     if topic.topic_key and topic.count > 0]

    while True:
        text = _render(picked, picked_topics)
        if len(text) <= text_limit:
            break
        # 超限时整条丢弃，保证 items 与 text 始终一致；不对拼好的字符串切片。
        if picked_topics:
            picked_topics.pop()
        elif picked:
            picked.pop()
        else:
            text = ""
            break

    items: list[ComposedItem] = [
        ComposedItem(kind=entry.category, text=_clean(entry.content)) for entry in picked
    ]
    items.extend(
        ComposedItem(kind="recent_topic",
                     text=f"{topic.topic_key}（最近 {topic.count} 次）")
        for topic in picked_topics
    )
    return items, text
