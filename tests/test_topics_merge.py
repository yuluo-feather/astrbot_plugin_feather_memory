"""主题分类与双来源合并。"""
from __future__ import annotations

from data.plugins.astrbot_plugin_feather_memory.core.merge import (
    ExplicitEntry,
    TopicStat,
    compose_context,
)
from data.plugins.astrbot_plugin_feather_memory.core.topics import TOPIC_KEYS, classify


def test_classify_single_topic_each() -> None:
    samples = {
        "工作": "最近工作压力很大",
        "学业": "考试快到了",
        "感情": "我喜欢一个人",
        "家庭": "和父母吵架了",
        "财务": "最近财运怎么样",
        "健康": "总是失眠",
        "人际": "和朋友闹别扭",
        "出行": "想搬家",
    }
    for expected, question in samples.items():
        assert classify(question) == expected
    assert set(samples) == set(TOPIC_KEYS)


def test_classify_multi_topic_is_empty() -> None:
    assert classify("工作和感情怎么选") == ""


def test_classify_no_match_is_empty() -> None:
    assert classify("帮我算一卦") == ""
    assert classify("") == ""


def test_merge_explicit_first_and_topic_fill() -> None:
    explicit = [ExplicitEntry(i, "preference", f"偏好{i}") for i in range(1, 4)]
    topics = [TopicStat("工作", 3, "2026-11-21T10:00:00Z"),
              TopicStat("感情", 2, "2026-11-20T10:00:00Z"),
              TopicStat("学业", 1, "2026-11-19T10:00:00Z")]
    items, text = compose_context(explicit, topics)
    assert [item.kind for item in items] == [
        "preference", "preference", "preference", "recent_topic", "recent_topic"]
    assert [item.text for item in items[3:]] == ["工作（最近 3 次）", "感情（最近 2 次）"]
    assert text.startswith("这位用户偏好1；偏好2；偏好3；最近关注工作")
    assert len(items) == 5


def test_merge_topics_only() -> None:
    items, text = compose_context([], [TopicStat("工作", 3, "2026-11-21T10:00:00Z")])
    assert [item.kind for item in items] == ["recent_topic"]
    assert text == "这位用户最近关注工作（最近 3 次）。"


def test_merge_empty() -> None:
    items, text = compose_context([], [])
    assert items == []
    assert text == ""


def test_merge_truncation_drops_topics_not_explicit() -> None:
    explicit = [ExplicitEntry(i, "preference", "长" * 220) for i in range(1, 4)]
    topics = [TopicStat("工作", 3, "2026-11-21T10:00:00Z")]
    items, text = compose_context(explicit, topics)
    assert all(item.kind == "preference" for item in items)
    assert "工作" not in text
    assert len(text) <= 600


def test_merge_drops_whole_entries_instead_of_slicing() -> None:
    explicit = [ExplicitEntry(i, "preference", f"{i}:" + "长" * 158)
                for i in range(1, 5)]
    items, text = compose_context(explicit, [])
    assert len(text) <= 600
    assert len(items) == 3
    assert all(item.text in text for item in items)
    assert sum(len(item.text) for item in items) <= len(text)


def test_merge_skips_zero_count_and_empty_topics() -> None:
    items, _ = compose_context([], [TopicStat("", 3, "x"), TopicStat("工作", 0, "x")])
    assert items == []
