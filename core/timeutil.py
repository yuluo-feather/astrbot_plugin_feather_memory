"""UTC ISO-8601 时间工具：全项目统一 `YYYY-MM-DDTHH:MM:SSZ`。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

UTC = timezone.utc


def now_utc() -> datetime:
    return datetime.now(UTC)


def format_ts(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_ts_precise(moment: datetime) -> str:
    """保留微秒：只用于同一秒内的比较（例如 cleared_at 的边界）。"""
    if moment.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_ts(text: str) -> datetime:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("timestamp must be a non-empty string")
    raw = text.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return moment.astimezone(UTC)


def add_days(moment: datetime, days: int) -> datetime:
    return moment + timedelta(days=days)


def add_seconds(moment: datetime, seconds: int) -> datetime:
    return moment + timedelta(seconds=seconds)
