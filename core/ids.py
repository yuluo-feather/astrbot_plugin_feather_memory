"""事件 / 实例 ID：ULID（时间有序，26 字符 Crockford Base32）。"""
from __future__ import annotations

import os
from datetime import datetime

from .timeutil import now_utc

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid(moment: datetime | None = None, randomness: bytes | None = None) -> str:
    moment = moment or now_utc()
    if moment.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    millis = int(moment.timestamp() * 1000)
    if not 0 <= millis < (1 << 48):
        raise ValueError("timestamp out of ULID range")
    rand = os.urandom(10) if randomness is None else randomness
    if len(rand) != 10:
        raise ValueError("randomness must be exactly 10 bytes")
    value = (millis << 80) | int.from_bytes(rand, "big")
    return "".join(_ALPHABET[(value >> shift) & 0x1F]
                   for shift in range(125, -1, -5))
