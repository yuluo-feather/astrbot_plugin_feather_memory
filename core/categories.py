"""显式记忆的分类标签；命令层与导出共用同一份映射。"""
from __future__ import annotations

CATEGORY_LABELS = {
    "preference": "偏好",
    "background": "背景",
    "goal": "目标",
}


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)
