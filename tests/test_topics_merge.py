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


def _reconstructed(items) -> str:
    if not items:
        return ""
    explicit = [item.text for item in items if item.kind != "recent_topic"]
    topics = [item.text for item in items if item.kind == "recent_topic"]
    parts = list(explicit)
    if topics:
        parts.append("最近关注" + "、".join(topics))
    return "这位用户" + "；".join(parts) + "。"


def test_merge_truncation_drops_topics_not_explicit() -> None:
    explicit = [ExplicitEntry(i, "preference", "长" * 195) for i in range(1, 4)]
    topics = [TopicStat("工作", 3, "2026-11-21T10:00:00Z")]
    items, text = compose_context(explicit, topics)
    assert len(items) == 3
    assert all(item.kind == "preference" for item in items)
    assert "工作" not in text
    assert len(text) <= 600


def test_merge_drops_whole_entries_instead_of_slicing() -> None:
    explicit = [ExplicitEntry(i, "preference", f"{i}:" + "长" * 158)
                for i in range(1, 5)]
    items, text = compose_context(explicit, [])
    assert len(text) <= 600
    assert len(items) == 3
    assert text == _reconstructed(items)
    assert all(item.text in text for item in items)


def test_merge_mixed_items_reconstruct_exactly() -> None:
    explicit = [ExplicitEntry(i, "preference", f"偏好{i}") for i in range(1, 5)]
    topics = [TopicStat("工作", 3, "2026-11-21T10:00:00Z"),
              TopicStat("感情", 2, "2026-11-20T10:00:00Z")]
    items, text = compose_context(explicit, topics)
    assert len(items) == 5
    assert text == _reconstructed(items)


def test_merge_text_limit_boundary() -> None:
    fits = [ExplicitEntry(1, "preference", "长" * 297),
            ExplicitEntry(2, "preference", "短" * 297)]
    items, text = compose_context(fits, [])
    assert (len(items), len(text)) == (2, 600)

    over = [ExplicitEntry(1, "preference", "长" * 298),
            ExplicitEntry(2, "preference", "短" * 298)]
    items, text = compose_context(over, [])
    assert len(items) == 1
    assert text == _reconstructed(items)


def test_merge_single_oversized_entry_is_dropped() -> None:
    items, text = compose_context(
        [ExplicitEntry(1, "preference", "长" * 601)], [])
    assert items == [] and text == ""


def test_merge_drops_oldest_explicit_first() -> None:
    explicit = [ExplicitEntry(1, "preference", "新" + "长" * 299),
                ExplicitEntry(2, "preference", "中" + "长" * 299),
                ExplicitEntry(3, "preference", "旧" + "长" * 299)]
    items, text = compose_context(explicit, [])
    assert len(items) == 1
    assert len(text) <= 600
    assert items[0].text.startswith("新")
    assert "旧" not in text
    assert text == _reconstructed(items)


def test_merge_prefilter_keeps_short_entry_after_oversized() -> None:
    explicit = [ExplicitEntry(1, "preference", "长" * 601),
                ExplicitEntry(2, "preference", "短记忆")]
    items, text = compose_context(explicit, [])
    assert [item.text for item in items] == ["短记忆"]
    assert text == _reconstructed(items)


def test_merge_prefilter_runs_before_limit() -> None:
    explicit = ([ExplicitEntry(0, "preference", "长" * 700)]
                + [ExplicitEntry(i, "preference", f"短{i}") for i in range(1, 6)])
    items, text = compose_context(explicit, [])
    assert len(items) == 5
    assert items[0].text == "短1"
    assert text == _reconstructed(items)


def test_merge_limits_explicit_to_five() -> None:
    explicit = [ExplicitEntry(i, "preference", f"偏好{i}") for i in range(1, 7)]
    items, text = compose_context(explicit, [])
    assert [item.text for item in items] == ["偏好1", "偏好2", "偏好3", "偏好4", "偏好5"]
    assert text == _reconstructed(items)


def test_merge_topic_does_not_skip_newer_for_older() -> None:
    explicit = [ExplicitEntry(1, "preference", "长" * 289),
                ExplicitEntry(2, "preference", "短" * 289)]
    topics = [TopicStat("工作", 100, "2026-11-21T10:00:00Z"),
              TopicStat("感情", 3, "2026-11-20T10:00:00Z")]
    items, text = compose_context(explicit, topics)
    assert len(items) == 2
    assert "工作" not in text and "感情" not in text
    assert text == _reconstructed(items)


def test_merge_topics_stop_at_first_that_does_not_fit() -> None:
    explicit = [ExplicitEntry(i, "preference", "长" * 190) for i in range(1, 4)]
    topics = [TopicStat("工作", 3, "2026-11-21T10:00:00Z"),
              TopicStat("感情", 30, "2026-11-20T10:00:00Z")]
    items, text = compose_context(explicit, topics)
    assert [item.kind for item in items] == [
        "preference", "preference", "preference", "recent_topic"]
    assert "工作" in text and "感情" not in text
    assert text == _reconstructed(items)


def test_merge_skips_invalid_topic_and_keeps_next() -> None:
    topics = [TopicStat("", 5, "2026-11-21T10:00:00Z"),
              TopicStat("工作", 0, "2026-11-21T09:00:00Z"),
              TopicStat("感情", 3, "2026-11-20T10:00:00Z")]
    items, text = compose_context([], topics)
    assert [item.text for item in items] == ["感情（最近 3 次）"]
    assert text == _reconstructed(items)


def test_merge_topic_can_fill_exactly_six_hundred() -> None:
    explicit = [ExplicitEntry(i, "preference", "长" * size)
                for i, size in enumerate((160, 160, 160, 97), start=1)]
    items, text = compose_context(
        explicit, [TopicStat("学业", 1, "2026-11-21T10:00:00Z")])
    assert len(text) == 600
    assert "学业" in text
    assert text == _reconstructed(items)


def test_merge_refills_topic_slots_after_dropping_explicit() -> None:
    explicit = [ExplicitEntry(i, "preference", "长" * 160) for i in range(1, 6)]
    topics = [TopicStat("工作", 3, "2026-11-21T10:00:00Z"),
              TopicStat("感情", 2, "2026-11-20T10:00:00Z")]
    items, text = compose_context(explicit, topics)
    kinds = [item.kind for item in items]
    assert kinds == ["preference"] * 3 + ["recent_topic"] * 2
    assert text == _reconstructed(items)


def test_merge_skips_zero_count_and_empty_topics() -> None:
    items, _ = compose_context([], [TopicStat("", 3, "x"), TopicStat("工作", 0, "x")])
    assert items == []
