# 羽忆 · 备份与恢复

> 本文只写羽忆自己的数据。宿主级备份范围见 AstrBot 文档；羽忆的数据都在 `plugin_data` 下，宿主备份会一并包含。

## 1. 数据落点

```text
data/plugin_data/feather_memory/
├── feather_memory.sqlite3        # 记忆正文、用户开关、占卜主题、revision
└── exports/                      # /羽忆 导出 生成的用户副本（可随时删除）
    └── <random-id>-<时间戳>.json
data/plugin_data/_shared/feather_memory/v1/
├── lease.json                    # 服务租约（可再生成）
├── auth/<sha256>.json            # 用户授权（可再生成）
├── events/<event_id>.json        # 待消费事件（最长 7 天）
└── context/<sha256>.json         # 注入缓存（可再生成）
```

- **必须备份**：`plugin_data/feather_memory/`（SQLite 及其 `-wal` / `-shm`）。
- **建议一起备份**：`_shared/feather_memory/v1/`，保持 DB 与 auth/context 来自同一快照。
- `lease.json` 不必备份；恢复旧租约反而会让核心误以为羽忆仍在运行。
- `exports/` 是用户主动导出的副本，含记忆正文，不参与恢复；每个用户最多保留最近 5 份，超出自动清理。`/羽忆 清空` 会删除该用户的导出副本，`/羽忆 关闭` 不会。

## 2. 备份

1. 优先在 AstrBot 停止运行、或停用羽忆后复制目录，避免拷到写入中的 WAL。
2. 运行中备份时，使用 SQLite 的在线备份（`sqlite3 feather_memory.sqlite3 ".backup backup.db"`）而不是直接复制主库文件。
3. 共享目录可与 DB 同批复制；也可以只备份 DB，auth/context 会在启动时重建。

## 3. 恢复

1. 停止 AstrBot。
2. 恢复 `plugin_data/feather_memory/`；若备份里有 `_shared/feather_memory/v1/`，一并恢复。
3. **删除 `lease.json`**：租约是服务存活标记，恢复旧文件没有意义，且可能让核心在羽忆未启动时短暂投递。
4. 若 DB 与 context 不是同一快照，**删除整个 `context/` 目录**：启动时会对所有已开启用户重建，避免旧 revision 的缓存留在磁盘上。
5. 启动 AstrBot，确认 `/羽忆 状态` 显示租约有效、context revision 与 DB 一致。

## 4. 已知取舍

- 羽忆启动时**先消费待处理事件、后刷新授权**。若只恢复 SQLite 而缺少 `_shared/auth`，已授权用户的待处理事件会按“授权缺失”丢弃；这是保守策略，不会把恢复期间的旧事件补录进来。
- 授权 TTL 180 天、context TTL 30 天。启动时会给 `enabled=1` 的用户刷新授权与 context 过期时间；过期文件由两边清扫。
- 恢复后的 `events/` 里如果还有超过 7 天的文件，会被羽忆或星羽的清扫删除。

## 5. 彻底清除

- `/羽忆 清空`：删除该用户的记忆、占卜记录、context 与导出副本，写 `cleared_at`；**不改变开关与授权**。已开启的用户继续记录，未开启的保持未开启（补写墓碑）。
- `/羽忆 关闭`：停止记录，删除 context 与待处理事件，把授权改写为墓碑（`auto_history=false`、`store_topic=false`），不删除授权文件。
- 卸载并删除数据：框架只删 `plugin_data/feather_memory/`，**不会删** `_shared/feather_memory/v1/`；如需彻底清除，手动删除共享目录，或等待 TTL 清扫。
- 共享目录里可能残留 `context/*.lock`、`auth/*.lock`、`state.lock` 与 `lease.lock` 锁文件；它们不含记忆正文，清扫只处理 `.json`，可随目录一起删除。
