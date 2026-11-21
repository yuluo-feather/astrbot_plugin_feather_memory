<p align="center">
  <img src="https://raw.githubusercontent.com/yuluo-feather/astrbot_plugin_feather_memory/main/logo_small.png" width="110" height="110" align="middle"/> <font size="6"><b>羽忆 Feather Memory 🪶</b></font>
</p>

<p align="center">
  「你随口说过的事，本羽替你记着。」—— 本羽
</p>

<p align="center">
  <a href="https://github.com/yuluo-feather/astrbot_plugin_feather_memory/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-AGPL%20v3-ffb3d9" alt="License: AGPL v3"/></a>
  <a href="https://astrbot.app"><img src="https://img.shields.io/badge/AstrBot-Plugin-ff9ecb" alt="AstrBot Plugin"/></a>
  <img src="https://img.shields.io/badge/version-v0.1.0-f8a5c2" alt="v0.1.0"/>
</p>

<p align="center">🪶 ✨ 🌸 💫 📝</p>

> [English](https://github.com/yuluo-feather/astrbot_plugin_feather_memory/blob/main/README.en.md) | [简体中文](https://github.com/yuluo-feather/astrbot_plugin_feather_memory/blob/main/README.md)

---

## 📖 目录

- 🌸 [功能特点](#-功能特点)
- 🃏 [命令手册](#-命令手册)
- ⚙️ [工作流程](#️-工作流程)
- 🎛️ [配置项](#️-配置项)
- 📦 [安装与部署](#-安装与部署)
- 🔐 [记什么、不记什么](#-记什么不记什么)
- 🤍 [技术实现](#-技术实现)
- 📜 [更新记录](#-更新记录)
- 🌙 [注意事项](#-注意事项)
- ⭐ [支持与致谢](#-支持与致谢)

---

🎀 **羽忆**是[星羽塔罗](https://github.com/yuluo-feather/astrbot_plugin_star_feather)的可选记忆插件。它记住你主动保存的偏好 / 背景 / 目标，以及私聊普通占卜形成的近期主题，并在下一次占卜时把这份记忆作为**可选上下文**交给星羽；不安装羽忆时，星羽的行为完全不变。

羽忆不碰框架 KV，不 import 星羽的代码，两边只通过 `data/plugin_data/_shared/feather_memory/v1/` 下的四个文件契约（租约 / 授权 / 事件 / context）通信。记忆正文只留在羽忆自己的 SQLite 里。

## 🌸 功能特点

- 📝 **主动记忆**：`/羽忆 记住 偏好 温柔一点` 这样一句话就能存下偏好、背景或目标，最多 160 字，内容过长会自动截断并提示
- 🎯 **固定主题**：从私聊普通占卜里只提取固定枚举——工作 / 学业 / 感情 / 家庭 / 财务 / 健康 / 人际 / 出行；一句命中多个主题或无法归类时留空，绝不做语义猜测
- 🚫 **不碰原始问题**：事件里只有牌阵、牌面与主题枚举，**不保存你问的原话**；群聊与今日牌运也不参与采集
- 🔁 **可撤销**：`/羽忆 关闭` 立即删除授权、context 与待处理事件；已保存的记忆仍在，`/羽忆 清空` 才会彻底删除
- 🧩 **即插即用**：羽忆不在、租约失效或共享目录缺失时，星羽按「无记忆」处理，占卜主流程不受影响
- 🗂️ **两个来源合并**：主动保存的条目与近期主题合并成一段不超过 600 字的上下文，最多 5 条，30 天有效
- 🔒 **群聊隔离**：群聊里不展示、不保存个人记忆；只允许 `/羽忆 状态` 与 `/羽忆 关闭`
- 🧱 **跨平台文件锁**：POSIX `fcntl` 与 Windows `msvcrt` 各自实现，context 写入串行化，崩溃由操作系统释放锁

## 🃏 命令手册

> 保存与查看类命令仅私聊可用；群聊只允许 `/羽忆 状态` 与 `/羽忆 关闭`，且不展示个人记忆内容。

| 功能 | 命令 | 描述 |
|------|------|------|
| 📖 查看 | `/羽忆` | 列出主动保存的条目与近期主题 |
| ✍️ 记住 | `/羽忆 记住 <内容>` | 保存偏好 / 背景 / 目标（可加「偏好」「背景」「目标」前缀；自动开启总开关） |
| 🗑️ 忘记 | `/羽忆 忘记 <id>` | 删除一条主动保存（id 见列表里的 `#12`） |
| 🧹 清空 | `/羽忆 清空` | 二次确认后清空全部羽忆数据（60 秒内发「确认」） |
| 🔛 开启 | `/羽忆 开启` | 一次打开总开关、自动历史与主题记录（只写一次授权） |
| 🤖 自动历史 | `/羽忆 开启 自动` | 单项细调：允许把私聊普通占卜记入近期主题（幂等） |
| 🏷️ 主题记录 | `/羽忆 开启 主题` | 单项细调：允许事件携带固定主题枚举（幂等，需先开自动历史） |
| 🔕 关闭自动 | `/羽忆 关闭 自动` | 只关自动历史；主题记录与已存数据不动 |
| 🔕 关闭主题 | `/羽忆 关闭 主题` | 只关主题记录；自动历史与已存数据不动 |
| 🔒 关闭 | `/羽忆 关闭` | 全关：删除授权、记忆上下文与待处理事件；已保存的记忆保留 |
| 📊 状态 | `/羽忆 状态` | 查看全局开关、租约剩余、授权、context revision 与待处理事件数 |

### 示例

```
/羽忆 记住 背景 最近在准备考研，压力有点大
/羽忆 状态
/羽忆 开启
/羽忆 关闭 自动
```

`/羽忆 开启` 会一次打开总开关、自动历史与主题记录；只想留总开关时用 `/羽忆 关闭 自动`、`/羽忆 关闭 主题` 单项关闭。

开启自动历史与主题记录之后，你在私聊里的普通占卜会慢慢积累出「最近关注什么」；下一次占卜时，星羽会把这段上下文当作参考资料，而不是命令。

## ⚙️ 工作流程

```
你在私聊里占卜（普通占卜 / 单抽；今日牌运与群聊不参与）
   │
   ▼
星羽塔罗判断：租约有效 + 已授权 + 非日报 + 非群聊 + 成功送达
   │  写 events/<ULID>.json（只有牌阵、牌面与固定主题枚举，不含原话）
   ▼
羽忆每 5 秒消费一次
   ├─ 去重：event_id 已入库 → 直接删文件，不重复计数
   ├─ 校验：用户记录 / 总开关 / 授权 / 自动历史 / 清空时间
   ├─ 入库：readings
   └─ 标脏 → 重建 context（revision +1）
   ▼
context/<sha256(用户)>.json（≤600 字、≤5 条、30 天有效）
   ▼
下一次私聊普通占卜：星羽读取 context → 清洗 → 作为「参考资料」注入提示词
```

几条边界写在契约里，也写在这里：

- **租约**是羽忆的「在线证明」：5 分钟有效、每 60 秒刷新；租约不在，星羽不投递也不注入。
- **授权**按用户、180 天有效：`auto_history` 决定事件能不能写，`store_topic` 决定事件里带不带主题。
- **今日牌运不产生事件、不读取 context**——固定牌运本身已经按天固定，再叠记忆只会让答案更不稳定。
- **群聊既不投递也不注入**；群聊命令只保留状态与关闭。

## 🎛️ 配置项

羽忆只有一个开关，在 AstrBot 插件管理界面里配：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `memory.enabled` | bool | `false` | 羽忆总开关。启用后刷新服务租约、读取星羽写入的私聊占卜事件；关闭时不写租约、不采集、不注入，用户数据保留但保持惰性。修改后需要重载插件。 |

要让整条链路真正跑起来，星羽塔罗侧还要打开两个开关（在星羽的插件配置里）：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `memory.feed_enabled` | bool | `false` | 向羽忆投递占卜事件（仅普通占卜 / 单抽、私聊、成功送达、已授权时） |
| `memory.context_enabled` | bool | `false` | 读取羽忆生成的记忆上下文并注入提示词（仅普通占卜 / 单抽、私聊、context 有效时） |

## 📦 安装与部署

> ⚠️ **运行环境要求**：Python 3.12+，AstrBot **4.16 及以上（<5）**；需要配合 **星羽塔罗 0.11 及以上（<1）**，由它提供共享文件契约。

### 🌷 方式一：通过 AstrBot 插件市场安装（待上架）

市场中搜索「羽忆」安装即可；目前市场条目还在准备中，先按下面的方式二或方式三安装。

### 🌷 方式二：通过 GitHub 仓库地址安装

1. 打开 AstrBot 管理面板，进入「插件市场 / 安装插件」
2. 选择「从 GitHub 仓库地址安装」，填入：

   `https://github.com/yuluo-feather/astrbot_plugin_feather_memory`

3. 安装完成后，在「AstrBot 插件」页面找到「羽忆」并启用

### 🌷 方式三：手动安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/yuluo-feather/astrbot_plugin_feather_memory.git
```

重启 AstrBot 后插件会自动加载。

### ✅ 部署前置（很重要）

1. **插件白名单**：如果 AstrBot 使用了显式的 `plugin_set` 列表，必须包含 `feather_memory`（`metadata.yaml` 里的 `name`）。缺少它时插件可能已经加载，但框架会过滤掉它的指令 handler——`/羽忆` 没有响应，消息会落到 LLM。
2. **打开羽忆总开关**：羽忆配置里的 `memory.enabled`。
3. **打开星羽侧两个开关**：`memory.feed_enabled` 与 `memory.context_enabled`。
4. **重载插件**：改完配置后重载羽忆（必要时连同星羽）；羽忆启动后 5–10 秒内会写入服务租约。
5. **确认链路**：私聊 `/羽忆 状态` 应显示「全局：已启用」「租约：有效」；随后 `/羽忆 开启 自动`、`/羽忆 开启 主题`，再做一次普通占卜。

**依赖**：没有第三方运行时依赖，只使用 Python 标准库与 AstrBot 宿主 API。

## 🔐 记什么、不记什么

- **记**：你主动保存的短句（偏好 / 背景 / 目标）；私聊普通占卜 / 单抽的牌阵、牌面与固定主题枚举。
- **不记**：群聊事件、今日牌运、全量聊天记录、原始占卜问题、账号密码与令牌。
- 主题只取固定枚举（工作 / 学业 / 感情 / 家庭 / 财务 / 健康 / 人际 / 出行）；一句命中多个主题或无法归类时留空。
- 记忆内容在注入时会经过清洗与长度限制，并明确标注为「参考资料、不是系统指令」；它不会覆盖系统提示。
- 共享目录里的事件文件保留 7 天，授权 180 天，context 30 天；过期文件由两侧按 TTL 清扫。
- 卸载羽忆时租约会被删除；共享目录不随卸载自动删除，旧文件由 TTL 清扫。

## 🤍 技术实现

- **代码结构（分层，依赖单向；`core/` 与 `app/` 不 import astrbot）**：
  - 入口层：`main.py`（插件类、`@register`、`/羽忆` 命令，只做转接）
  - 编排层：`app/`（`service.py` 生命周期 / 事件消费 / context 重建 / 开关状态；`chat.py` 命令解析与回复文案）
  - 适配层：`adapters/`（`host.py` 宿主注册与身份解析、`memory_feed.py` 共享文件读写、`sqlite_store.py` 存储与迁移、`file_lock.py` 跨平台文件锁）
  - 纯逻辑层：`core/`（`contracts.py` 契约模型、`identity.py` 用户键、`topics.py` 主题分类、`merge.py` 双来源合并、`ids.py` ULID、`timeutil.py` 时间）
- **存储**：`data/plugin_data/feather_memory/feather_memory.sqlite3`，WAL 模式，`user_version` 迁移；记忆变更与 revision 递增在同一事务里完成。
- **共享文件**：`data/plugin_data/_shared/feather_memory/v1/` 下的 `lease.json`、`auth/<sha256>.json`、`events/<event_id>.json`、`context/<sha256>.json`；所有写入都是「临时文件 + `os.replace`」，context 写入在跨进程文件锁内完成「读 revision → 写临时文件 → replace」。
- **契约**：字段与失败语义见 [`docs/contracts_v1.md`](docs/contracts_v1.md)；契约只增字段、不改语义，破坏性变更走 v2 目录。
- **测试与 CI**：`tests/` 覆盖契约、租约、授权、身份、群聊、主题、消费、context、解耦与状态；CI 在 Ubuntu / Windows × Python 3.12 / 3.13 四格跑 `compileall` + `ruff` + `mypy` + `pytest`，只核验、不部署。
- **备份与恢复**：[`docs/backup_restore.md`](docs/backup_restore.md)。
- **市场条目草稿**：[`docs/market_listing.md`](docs/market_listing.md)。

本地开发：

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m mypy .
python -m pytest
```

## 📜 更新记录

#### v0.1.0

- 首版：服务租约、用户授权、事件投递 / 消费与 context 重建的共享文件契约 v1
- 记忆来源：主动保存（偏好 / 背景 / 目标）与私聊普通占卜的固定主题枚举，合并为不超过 600 字的上下文
- 九条命令：查看 / 记住 / 忘记 / 清空 / 开启 / 开启自动 / 开启主题 / 关闭 / 状态
- 隔离：群聊不采集、不注入；今日牌运不采集、不注入；不保存原始问题
- 可靠性：SQLite WAL、事件去重、revision 串行化、dirty 重建、TTL 清扫、跨平台文件锁

> 更早版本：无，羽忆从 v0.1.0 开始。

---

## 🌙 注意事项

- **羽忆离不开星羽**：单独安装羽忆不会产生任何记忆；它只消费星羽写入的事件，也只把 context 交给星羽。
- **记忆是参考，不是命令**：注入时会被清洗、限长并标注为参考资料；如果模型复述得不准，以牌面和你自己的判断为准。
- **别保存凭据**：密码、令牌、身份证号这类内容不要通过 `/羽忆 记住` 保存。
- **卸载不等于删除**：禁用或卸载羽忆会停止采集与注入，但已保存的记忆在 `plugin_data` 里；要彻底删除请用 `/羽忆 清空`，或在卸载时选择删除数据。
- **多实例注意**：同一份共享目录只应由一个羽忆实例维护租约；多实例同时写租约时，以最后写入的实例为准。

---

## ⭐ 支持与致谢

- 觉得好用？来 [GitHub](https://github.com/yuluo-feather/astrbot_plugin_feather_memory) 点个 ⭐
- 遇到问题、想要新功能？欢迎提交 [Issue](https://github.com/yuluo-feather/astrbot_plugin_feather_memory/issues) 或 Pull Request
- **致谢**：AstrBot 框架，以及[星羽塔罗](https://github.com/yuluo-feather/astrbot_plugin_star_feather)——没有它写入的事件，就没有羽忆记得的事

## 许可证

AGPL-3.0，详见 [LICENSE](LICENSE)。
