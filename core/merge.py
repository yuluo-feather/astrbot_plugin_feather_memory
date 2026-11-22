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
    limit = min(explicit_limit, max_items)
    candidates = [
        entry for entry in explicit
        if _clean(entry.content) and len(_render([entry], [])) <= text_limit
    ]
    picked = candidates[:limit]
    # 显式优先：显式条目自己放不下时从最旧开始整条丢弃，不对字符串切片。
    while picked and len(_render(picked, [])) > text_limit:
        picked.pop()

    slots = max(0, max_items - len(picked))
    picked_topics: list[TopicStat] = []
    for topic in topics:
        if len(picked_topics) >= slots:
            break
        if not topic.topic_key or topic.count <= 0:
            continue
        trial = picked_topics + [topic]
        if len(_render(picked, trial)) <= text_limit:
            picked_topics = trial
        else:
            break  # 最近优先：第一条放不下就停，不跳过它去收更旧的主题。

    text = _render(picked, picked_topics)

    items: list[ComposedItem] = [
        ComposedItem(kind=entry.category, text=_clean(entry.content)) for entry in picked
    ]
    items.extend(
        ComposedItem(kind="recent_topic",
                     text=f"{topic.topic_key}（最近 {topic.count} 次）")
        for topic in picked_topics
    )
    return items, text
