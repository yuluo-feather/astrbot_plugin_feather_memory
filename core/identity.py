"""用户身份：`platform_id:uid` 是唯一键，文件名只出现它的 sha256。

身份键与星羽核心保持同一套转义规则：`%` → `%25`、`:` → `%3A`；
平台 ID 取宿主适配器 ID（`get_platform_id()`），不是平台类型名。
取不到平台 ID 时退回裸 uid（与核心的降级口径一致）。
"""
from __future__ import annotations

import hashlib


def escape_identity_part(part: str) -> str:
    return part.replace("%", "%25").replace(":", "%3A")


def build_user_key(platform_id: str, uid: str) -> str:
    sender = escape_identity_part(str(uid or "").strip())
    if not sender:
        return ""
    platform = escape_identity_part(str(platform_id or "").strip())
    return f"{platform}:{sender}" if platform else sender


def user_key_hash(user_key: str) -> str:
    if not isinstance(user_key, str) or not user_key:
        raise ValueError("user_key must be a non-empty string")
    return hashlib.sha256(user_key.encode("utf-8")).hexdigest()
