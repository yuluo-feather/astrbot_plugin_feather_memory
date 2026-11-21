# 羽忆 · 共享文件契约 v1（M0 冻结）

> 状态：**冻结**（2026-11-21）。v1 只增字段、不改语义；破坏性变更走 v2 目录。
> 真源：`羽忆插件计划书_20261121.md` §3；本文件是实施口径，两者冲突时先回计划书裁定。
> 实现：`core/contracts.py`（模型与校验）、`adapters/memory_feed.py`（读写与清扫）。

## 0. 目录与文件

```text
data/plugin_data/_shared/feather_memory/v1/
├── lease.json                  # 羽忆写，核心读
├── state.lock                  # 羽忆写/锁：跨进程状态转换串行化
├── auth/{sha256(user_key)}.json
├── events/{event_id}.json      # 核心写，羽忆读
├── context/{sha256(user_key)}.json
└── context/{sha256(user_key)}.lock
```

- `platform_id` 取宿主适配器 ID（AstrBot `event.get_platform_id()`），**不是**平台类型名。
- `user_key = "{escape(platform_id)}:{escape(uid)}"`；`escape` 把 `%` → `%25`、`:` → `%3A`。
  平台 ID 为空时退化为裸 `escape(uid)`；发送者 ID 为空则不产生事件。
- 身份只从宿主事件适配器取，模型 / 命令参数不能指定 `user_key`。
- 所有写入：同目录临时文件 + `os.replace`。
- 事件文件上限 **16 KB**；context **8 KB**；租约 / 授权 **4 KB**；超限按损坏处理。
- 未知字段一律忽略；必填字段缺失、类型不符、枚举越界 → 该文件不生效。

## 1. 服务租约 `star_feather.memory_lease.v1`

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema` | string | `star_feather.memory_lease.v1` |
| `instance_id` | string | ULID；只用于优雅关闭时判断「是不是我写的租约」 |
| `started_at` | string | UTC ISO-8601 `Z` |
| `refreshed_at` | string | UTC ISO-8601 `Z` |
| `expires_at` | string | UTC ISO-8601 `Z`；TTL 5 分钟 |
| `source` | string | `feather_memory/{version}` |

- 羽忆启用时写，运行期每 60 秒刷新；优雅关闭时仅删除 `instance_id` 相同的租约。
- 租约写入与删除都在 `lease.lock` 内完成；删除前在锁内复查 `instance_id`，避免误删新实例的租约。
- 核心在写事件、读 context 前都先读租约；缺失 / 过期 / schema 不符 → 按无羽忆处理。
- 租约是**服务存活**，不是用户记忆过期；授权 TTL 另算。

## 2. 用户授权 `star_feather.memory_auth.v1`

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema` | string | `star_feather.memory_auth.v1` |
| `user_key_hash` | string | `sha256(user_key)` 小写 hex，64 字符 |
| `generated_at` | string | UTC ISO-8601 `Z` |
| `expires_at` | string | UTC ISO-8601 `Z`；TTL 180 天 |
| `auto_history` | bool | 是否允许核心写事件 |
| `store_topic` | bool | 是否允许事件携带 `topic_key` |
| `source` | string | `feather_memory/{version}` |

- 核心写事件前依次检查：租约有效 → 授权文件存在、未过期、schema 相符 → `auto_history=true`。
- `store_topic=false` 时核心必须写空 `topic_key`。
- 羽忆在启动、用户命令、每日维护时刷新；用户关闭 / 清空时删除。

## 3. 事件 `star_feather.reading_event.v1`

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema` | string | `star_feather.reading_event.v1` |
| `event_id` | string | ULID；SQLite 唯一约束 |
| `created_at` | string | UTC ISO-8601 `Z` |
| `source_version` | string | 核心版本，例如 `0.11.0` |
| `platform_id` | string | 例如 `aiocqhttp` |
| `user_key` | string | `escape(platform_id):escape(uid)`；前缀与 `platform_id` 的转义形式一致 |
| `conversation_scope` | string | `private` / `group`；羽忆只消费 `private` |
| `kind` | string | `spread` / `single`；其他值直接丢弃 |
| `spread` | string | 牌阵名 |
| `cards` | array | `[{"id": "...", "upright": true}]` |
| `topic_key` | string | 固定枚举或空串（见 §5） |
| `spirit_line_present` | bool | 本次是否生成了牌灵的话 |

- 核心只在「租约有效 + 投递开关开 + 私聊 + `present()` 返回 True + 非今日牌运 + 授权有效」时写。
- 不写群聊事件、不写今日牌运事件、不写原始问题；v1 没有 `topic_excerpt`。

## 4. 事件消费协议

```text
PENDING
  → 读取并校验 schema（含 16 KB 上限）
  → 校验租约：失效则暂停本批消费，事件文件保留（7 天清扫兜底）
  → 校验用户授权：失效则直接删除，不入库
  → 校验 conversation_scope=private、kind ∈ {spread,single}、created_at > cleared_at
  → SQLite 事务提交（event_id 唯一约束）+ revision+1 + context_dirty=1
  → 删除事件文件
  → 重建 context
  → CONSUMED
```

- 裁定（2026-11-21）：租约失效保留事件、授权失效删除事件。租约是服务自检，
  瞬时写入失败不应导致已授权事件被丢弃；授权失效（文件缺失 / 过期 / `auto_history=false`）
  代表用户不再允许采集，必须删除事件。
- 停用会写 `users.disabled_at`；重新启用不清除它，`created_at <= disabled_at` 的事件一律丢弃。
- 先提交、后删除；删除失败只记 warning，不回滚数据库。
- 消费提交前在同一个 SQLite 写事务里复查 `users.enabled` 与 `cleared_at`；
  关闭 / 清空与消费竞态时丢弃事件，避免旧阅读记录回到库里。
- 重复 `event_id` 直接删除文件，不重复计数。
- 损坏 / 越权事件直接删除，避免毒文件反复重试。
- `topic_key` 与授权不一致时按「不保存主题」处理：只清空该字段，不丢整条事件。

## 5. 上下文 `star_feather.memory_context.v1`

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema` | string | `star_feather.memory_context.v1` |
| `revision` | int | 与 `users.context_revision` 同源，单调递增 |
| `generated_at` | string | UTC ISO-8601 `Z` |
| `expires_at` | string | UTC ISO-8601 `Z`；TTL 30 天，启动重建续期 |
| `source` | string | `feather_memory/{version}` |
| `scope` | string | 只允许 `private` |
| `items` | array | `[{"kind": "...", "text": "..."}]`，最多 5 条 |
| `text` | string | 最终注入文本，≤ 600 字 |

核心读取条件：租约有效、注入开关开、文件有效、`scope=private`、当前会话为私聊。

失败分级：

| 情况 | 处理 |
|---|---|
| 不存在 | 正常无记忆 |
| JSON 损坏 / schema 不符 | 忽略，warning 一次 |
| 已过期 | 忽略 |
| `generated_at >= expires_at`，或 `generated_at` 明显晚于当前（>5 分钟） | 忽略 |
| 超过 8 KB / `text` 超 600 字 / items 超 5 条 | 忽略 |
| 短暂读取失败 | 本次无记忆，下次重试 |
| 权限错误 | warning 一次，不刷屏 |

## 6. context 写入串行化

1. 取 `context/{sha256}.lock` 跨进程锁（Windows `msvcrt.locking` / POSIX `fcntl.flock`）；
2. 锁内读现有 context 的 `revision`；
3. 新 revision 小于现有值 → 放弃写入；
4. 临时文件 + `os.replace`；
5. 释放锁。

- 锁等待上限 200 ms；超时放弃写入并置 `context_dirty=1`。
- 写入成功后，只有在 `users.context_revision` 仍等于本次快照时才清 `context_dirty`；
  空 context / 停用分支同样条件清。revision 已变则保持 dirty，等下一次重建。
- 进程内状态转换（开启 / 关闭 / 清空 / 单项开关）用同一把可重入锁串行化，
  并再取 `state.lock` 做跨进程互斥；锁序固定为 state.lock → context.lock。
- 空 context / 停用分支删除 context 前也要在 context 锁内复查 revision 与启用状态；
  guard 失败不删新文件；删成功但条件清 dirty 失败时补置 dirty=1。
- 进程崩溃时操作系统自动释放锁，不依赖删锁文件。
- `context_dirty=1` 的用户在启动与每小时维护时重建；成功后清 0。
- 删除 / 清空 / 关闭时立即删除 context 文件，避免旧记忆继续注入。

## 7. 开关状态转换表

| 操作 | `enabled` | `auto_history` | `store_topic` | 授权文件 | context | 待处理事件 |
|---|---|---|---|---|---|---|
| `/羽忆 开启` | 1 | 1 | 1 | 写一次（auto/store=true） | 重建 | 保留 |
| `/羽忆 开启 自动` | 必须已为 1 | 1 | 不变 | 写 / 刷新 | 重建 | 保留 |
| `/羽忆 开启 主题` | 必须已为 1 | 必须已为 1 | 1 | 写 / 刷新 | 重建 | 保留 |
| `/羽忆 关闭 自动` | 不变 | 0 | 不变 | 刷新（auto=false） | 不变 | 保留（消费时按授权丢弃） |
| `/羽忆 关闭 主题` | 不变 | 不变 | 0 | 刷新（store=false） | 不变 | 保留（消费时按授权丢弃） |
| `/羽忆 关闭` | 0 | 0 | 0 | 删除 | 删除 | 删除 |
| `/羽忆 清空` | 不变 | 0 | 0 | 删除 | 删除 | 删除 |
| 全局 `memory.enabled=false` | 不变 | 不变 | 不变 | 保留 | 保留但租约失效后不读 | 保留但租约失效后不写 |

## 8. 清扫

- 事件：超过 7 天删除（按文件 mtime）。
- 授权 / context：`expires_at` 已过则删除。
- 租约：`expires_at` 超过 1 天则删除。
- 启动时一次；之后每小时一次；失败只 warning，不影响占卜。
- 清扫不受全局 `memory.enabled` 限制：关闭时仍清理过期共享文件与超窗占卜记录。
- `context/*.lock`、`state.lock`、`lease.lock` 是持久协调文件，不含记忆正文；清扫只处理 `.json`，锁文件可随目录手动删除。

## 9. 数据保留

- 占卜事件：每用户最近 **200 条 / 180 天**；主题次数只统计这个窗口。
- 显式记忆：默认不过期；单条 ≤ 160 字。
- 清空不删 `users` 行：保留 `enabled` 与 `cleared_at` 等状态，用于挡住清空前的旧事件并支持后续重开。
- 停用写 `disabled_at`；重新启用不清除，停用前产生的事件不会在重开后复活。
- 启动与每小时维护会记录只读统计（用户 / 记忆 / 占卜 / 事件 / auth / context 数量），不设上限、不改变行为。
- `suppressed_topics`：v1 表已建，命令留待 v2。
