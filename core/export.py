"""用户导出的数据结构：只含本人数据，不含账号标识与原始问题。"""
from __future__ import annotations

from .categories import category_label
from .merge import ExplicitEntry, TopicStat

EXPORT_DATA_TYPE = "feather_memory.user_export"
EXPORT_DATA_VERSION = 1

EXPORT_NOTES = (
    "本文件只包含你自己的羽忆数据：主动保存的记忆、近期主题统计与开关状态。"
    "不含账号标识（user_key / platform_id）、原始占卜问题或其他用户的数据。"
)


def build_export(*, exported_at: str, plugin_version: str,
                 enabled: bool, auto_history: bool, store_topic: bool,
                 memories: list[ExplicitEntry],
                 topics: list[TopicStat]) -> dict:
    return {
        "data_type": EXPORT_DATA_TYPE,
        "data_version": EXPORT_DATA_VERSION,
        "exported_at": exported_at,
        "plugin_version": plugin_version,
        "switches": {
            "enabled": bool(enabled),
            "auto_history": bool(auto_history),
            "store_topic": bool(store_topic),
        },
        "memories": [
            {
                "id": entry.memory_id,
                "category": entry.category,
                "category_label": category_label(entry.category),
                "content": entry.content,
                "updated_at": entry.updated_at,
            }
            for entry in memories
        ],
        "recent_topics": [
            {
                "topic": topic.topic_key,
                "count": topic.count,
                "last_at": topic.last_at,
            }
            for topic in topics
        ],
        "notes": EXPORT_NOTES,
    }
