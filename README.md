# 羽忆（astrbot_plugin_feather_memory）

羽忆是**星羽塔罗**的可选记忆插件：它记住你主动保存的偏好 / 背景 / 目标，以及私聊普通占卜形成的近期主题，并在下一次占卜时把这份记忆作为可选上下文交给星羽。不安装羽忆时，星羽的行为完全不变。

## 依赖

- AstrBot `>=4.16,<5`，Python 3.12+
- 星羽塔罗 `>=0.11,<1`（提供 `_shared/feather_memory/v1` 共享文件契约）
- 羽忆插件配置里打开「启用」；星羽塔罗侧另外打开「记忆投递」与「记忆注入」

## 部署前置

- AstrBot 若使用显式 `plugin_set` 列表，必须包含 `feather_memory`（`metadata.yaml` 的 `name`）。缺少时插件可能已加载，但指令 handler 会被框架过滤，`/羽忆` 无响应并落到 LLM。
- 羽忆插件配置里打开 `memory.enabled`；星羽塔罗侧打开 `memory.feed_enabled` 与 `memory.context_enabled`。
- 修改配置后重载对应插件；羽忆启动后 5–10 秒内会写入服务租约。

## 命令（仅私聊可用保存与查看）

| 命令 | 作用 |
|---|---|
| `/羽忆` | 查看主动保存与近期主题 |
| `/羽忆 记住 <内容>` | 保存偏好 / 背景 / 目标（自动开启总开关） |
| `/羽忆 忘记 <id>` | 删除一条主动保存 |
| `/羽忆 清空` | 二次确认后清空全部数据 |
| `/羽忆 开启` | 打开总开关 |
| `/羽忆 开启 自动` | 允许把私聊普通占卜记入近期主题 |
| `/羽忆 开启 主题` | 允许事件携带固定主题枚举 |
| `/羽忆 关闭` | 关闭并删除授权、context 与待处理事件 |
| `/羽忆 状态` | 查看租约、开关、授权与 context |

群聊里只允许 `/羽忆 关闭` 与 `/羽忆 状态`，且不展示个人记忆内容。

## 记什么、不记什么

- 记：你主动保存的短句；私聊普通占卜 / 单抽的牌阵、牌面与固定主题枚举。
- 不记：群聊事件、今日牌运、全量聊天、原始占卜问题。
- 主题只取固定枚举（工作 / 学业 / 感情 / 家庭 / 财务 / 健康 / 人际 / 出行）；一句命中多个主题或无法归类时留空。
- 请不要保存密码、令牌或账号凭据；记忆内容会作为不可信资料注入提示词，不会覆盖系统提示。

## 数据落点与卸载

- 记忆正文只进羽忆自己的 SQLite：`data/plugin_data/feather_memory/feather_memory.sqlite3`。
- 与星羽共享的文件在 `data/plugin_data/_shared/feather_memory/v1/`：服务租约、授权、事件、context。
- 卸载羽忆后租约最多 5 分钟失效；共享目录里的旧文件由 TTL 清扫（事件 7 天，授权 / context 按各自过期时间）。
- 宿主备份包含 `plugin_data`，因此上述数据会随宿主备份一起备份。

## 契约与版本

- 共享契约 v1 已冻结，字段与失败语义见 [`docs/contracts_v1.md`](docs/contracts_v1.md)。
- 契约只增字段、不改语义；破坏性变更走 v2 目录。
- 备份与恢复：[`docs/backup_restore.md`](docs/backup_restore.md)。
- 市场条目草稿：[`docs/market_listing.md`](docs/market_listing.md)。

## 开发

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m mypy .
python -m pytest
```

插件没有第三方运行时依赖，只使用 Python 标准库与 AstrBot 宿主 API。
