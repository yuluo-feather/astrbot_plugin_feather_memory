<p align="center">
  <img src="https://raw.githubusercontent.com/yuluo-feather/astrbot_plugin_feather_memory/main/logo_small.png" width="110" height="110" align="middle"/> <font size="6"><b>Feather Memory 🪶</b></font>
</p>

<p align="center">
  "The things you let slip — I'll keep them." — Yuluo
</p>

<p align="center">
  <a href="https://github.com/yuluo-feather/astrbot_plugin_feather_memory/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-AGPL%20v3-ffb3d9" alt="License: AGPL v3"/></a>
  <a href="https://astrbot.app"><img src="https://img.shields.io/badge/AstrBot-Plugin-ff9ecb" alt="AstrBot Plugin"/></a>
  <img src="https://img.shields.io/badge/version-v0.1.0-f8a5c2" alt="v0.1.0"/>
</p>

<p align="center">🪶 ✨ 🌸 💫 📝</p>

> [简体中文](https://github.com/yuluo-feather/astrbot_plugin_feather_memory/blob/main/README.md) | [English](https://github.com/yuluo-feather/astrbot_plugin_feather_memory/blob/main/README.en.md)

---

## 📖 Table of Contents

- 🌸 [Features](#-features)
- 🃏 [Commands](#-commands)
- ⚙️ [How It Works](#️-how-it-works)
- 🎛️ [Configuration](#️-configuration)
- 📦 [Installation & Deployment](#-installation--deployment)
- 🔐 [What Is Stored](#-what-is-stored)
- 🤍 [Technical Details](#-technical-details)
- 📜 [Changelog](#-changelog)
- 🌙 [Notes](#-notes)
- ⭐ [Support & Thanks](#-support--thanks)

---

🎀 **Feather Memory** is an optional memory plugin for [Star Feather Tarot](https://github.com/yuluo-feather/astrbot_plugin_star_feather). It remembers the preferences, background and goals you save explicitly, plus the recent topics that form from private normal readings, and offers that memory back to Star Feather as **optional context** for the next reading. Without Feather Memory, Star Feather behaves exactly as before.

Feather Memory does not touch the framework KV store and does not import Star Feather code. The two sides talk only through four files under `data/plugin_data/_shared/feather_memory/v1/` (lease / auth / event / context). Memory bodies stay in Feather Memory's own SQLite database.

## 🌸 Features

- 📝 **Explicit memory**: `/羽忆 记住 偏好 温柔一点` saves a preference, background or goal in one line — up to 160 characters, with a notice when it gets truncated
- 📤 **Export**: `/羽忆 导出` writes your saved memories, recent-topic stats and switch states to a JSON file; your data only, with no account identifiers or raw questions
- 🎯 **Fixed topics**: private normal readings contribute only a fixed enum — work / study / relationship / family / finance / health / social / travel. A question that hits several topics, or none, yields an empty topic; no semantic guessing
- 🚫 **No raw questions**: events carry the spread, cards and topic enum, plus an event id, platform / user identifiers, timestamp and core version for dedupe and indexing — **never the words you asked**. Group chats and the daily fortune do not feed it
- 🔁 **Revocable**: `/羽忆 关闭` immediately deletes auth, context and pending events; saved memories remain until `/羽忆 清空`
- 🧩 **Plug and play**: if Feather Memory is absent, the lease is stale or the shared directory is missing, Star Feather simply behaves as if there were no memory
- 🗂️ **Two sources merged**: at most 5 items, with explicit entries taking slots first and recent topics filling the rest; merged into one context block of at most 600 characters, valid for 30 days
- 🔒 **Group isolation**: no personal memory is shown or saved in group chats; only `/羽忆 状态` and `/羽忆 关闭` (without arguments) are accepted there, and partial disables are private-chat only
- 🧱 **Cross-platform file locks**: POSIX `fcntl` and Windows `msvcrt` each have their own implementation; context writes are serialized and a crashed process releases its lock via the OS

## 🃏 Commands

> Saving and viewing are private-chat only. In group chats only `/羽忆 状态` and `/羽忆 关闭` (without arguments) are accepted, and no personal memory content is shown; `关闭 自动` / `关闭 主题` are private-chat only.

| Feature | Command | Description |
|---------|---------|-------------|
| 📖 View | `/羽忆`, `/羽忆 查看`, `/羽忆 查看记忆`, `/羽忆 列表` | List saved entries and recent topics |
| 📤 Export | `/羽忆 导出` | Write your memories, recent topics and switch states to `plugin_data/feather_memory/exports/` and reply with the file path; the latest 5 exports per user are kept |
| ✍️ Remember | `/羽忆 记住 <text>` | Save a preference / background / goal (optional `偏好` / `背景` / `目标` prefix; enables the master switch) |
| ✏️ Modify | `/羽忆 修改 <id> <new text>` | Modify one saved entry; keeps its id, optional prefix changes category, truncates at 160 chars |
| 🗑️ Forget | `/羽忆 忘记 <id>` | Delete one saved entry (ids look like `#12` in the list) |
| 🧹 Clear | `/羽忆 清空` | Clear **your own** Feather Memory data after a second confirmation, including exported copies under `exports/` (send `/羽忆 清空 确认` within 60 seconds) |
| 🔛 Enable | `/羽忆 开启` | Turn on the master switch, auto history and topic recording in one step (one auth write) |
| 🤖 Auto history | `/羽忆 开启 自动` | Fine-grained: allow private normal readings to feed recent topics (idempotent) |
| 🏷️ Topic recording | `/羽忆 开启 主题` | Fine-grained: allow events to carry the fixed topic enum (idempotent, requires auto history first) |
| 🔕 Disable auto | `/羽忆 关闭 自动` | Turn off auto history only; topic recording and stored data stay |
| 🔕 Disable topics | `/羽忆 关闭 主题` | Turn off topic recording only; auto history and stored data stay |
| 🔒 Disable | `/羽忆 关闭` | Full stop: delete auth, memory context and pending events; saved memories remain |
| 📊 Status | `/羽忆 状态` | Show the global switch, lease remaining, auth, context validity and generation time, last consumption and pending events |

### Example

```
/羽忆 记住 背景 最近在准备考研，压力有点大
/羽忆 查看
/羽忆 修改 1 背景 最近在准备复试
/羽忆 状态
/羽忆 开启
/羽忆 关闭 自动
```

`/羽忆 开启` turns on the master switch, auto history and topic recording in one step; use `/羽忆 关闭 自动` or `/羽忆 关闭 主题` to turn off a single part while keeping the master switch on.

Once auto history and topic recording are on, your private normal readings slowly build up "what you've been focused on lately". On the next reading, Star Feather treats that context as reference material, not as instructions.

## ⚙️ How It Works

```
You draw in a private chat (normal reading / single draw; daily fortune and group chats are excluded)
   │
   ▼
Star Feather checks: lease valid + authorised + not daily + not a group + delivered
   │  writes events/<ULID>.json (spread, cards and the fixed topic enum only — no raw question)
   ▼
Feather Memory consumes every 5 seconds
   ├─ dedupe: event_id already stored → delete the file, do not count again
   ├─ validate: user record / master switch / auth / auto history / cleared-at
   ├─ store: readings
   └─ mark dirty → rebuild context (revision +1)
   ▼
context/<sha256(user)>.json (≤600 chars, ≤5 items, valid for 30 days)
   ▼
Next private normal reading: Star Feather reads the context → sanitises it → injects it as reference material
```

A few boundaries live in the contract and here:

- The **lease** is Feather Memory's proof of life: valid for 5 minutes, refreshed every 60 seconds. Without a lease, Star Feather neither publishes nor injects.
- **Auth** is per user and valid for 180 days: `auto_history` decides whether events may be written, `store_topic` decides whether they carry a topic.
- **The daily fortune never produces events and never reads context** — it is already fixed per day; layering memory on top would only make answers less stable.
- **Group chats neither publish nor inject**; only status and disable remain available there.

## 🎛️ Configuration

Feather Memory's settings live in the AstrBot plugin settings:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `memory.enabled` | bool | `false` | Master switch. When enabled, Feather Memory refreshes its lease and consumes the private-reading events Star Feather writes; when disabled it writes no lease, consumes nothing and injects nothing, while user data stays inert. Reload the plugin after changing it. |
| `context.min_topic_count` | int | `1` | Minimum occurrences for a recent topic to enter the context. `1` keeps every recent topic; `2` keeps only topics seen more than once. It only affects the context and never deletes stored stats. |

To make the whole chain work, two switches on the Star Feather side must also be on (in Star Feather's plugin settings):

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `memory.feed_enabled` | bool | `false` | Publish reading events to Feather Memory (normal reading / single draw, private chat, delivered, authorised only) |
| `memory.context_enabled` | bool | `false` | Read Feather Memory's context and inject it into the prompt (normal reading / single draw, private chat, valid context only) |

## 📦 Installation & Deployment

> ⚠️ **Requirements**: Python 3.12+, AstrBot **4.16 or later (<5)**, and **Star Feather Tarot 0.11 or later (<1)**, which provides the shared file contract.

### 🌷 Option 1: AstrBot plugin market (coming soon)

Search for "羽忆" in the market once the listing is published; for now use option 2 or 3.

### 🌷 Option 2: Install from the GitHub repository URL

1. Open the AstrBot dashboard and go to Plugins / Market
2. Choose "Install from GitHub repository URL" and enter:

   `https://github.com/yuluo-feather/astrbot_plugin_feather_memory`

3. After installation, find "羽忆" on the Plugins page and enable it

### 🌷 Option 3: Manual installation

```bash
cd AstrBot/data/plugins
git clone https://github.com/yuluo-feather/astrbot_plugin_feather_memory.git
```

Restart AstrBot and the plugin loads automatically.

### ✅ Deployment prerequisites (important)

1. **Plugin whitelist**: if AstrBot uses an explicit `plugin_set` list, it must contain `feather_memory` (the `name` in `metadata.yaml`). Without it the plugin may be loaded while the framework filters out its command handlers — `/羽忆` gets no response and the message falls through to the LLM.
2. **Turn on Feather Memory**: set `memory.enabled` in its configuration.
3. **Turn on the two Star Feather switches**: `memory.feed_enabled` and `memory.context_enabled`.
4. **Reload the plugins** after changing configuration (Feather Memory first, then Star Feather if needed); Feather Memory writes its lease within 5–10 seconds of startup.
5. **Check the chain**: send `/羽忆 状态` in a private chat — it should show "全局：已启用" and "租约：有效"; then run `/羽忆 开启` (master switch, auto history and topic recording in one step); use `开启 自动` / `开启 主题` only for fine-tuning, then do a normal reading.

**Dependencies**: none at runtime — only the Python standard library and the AstrBot host API.

## 🔐 What Is Stored

- **Stored**: short entries you save explicitly (preferences / background / goals); the spread, cards and fixed topic enum of private normal readings and single draws.
- **Not stored**: group-chat events, the daily fortune, full chat logs, original questions, passwords or tokens.
- Event files also contain `event_id`, `user_key`, `platform_id`, `created_at` and `source_version` for dedupe, indexing and diagnostics; the original question is not included.
- Topics use a fixed enum (work / study / relationship / family / finance / health / social / travel); a question hitting several topics, or none, yields an empty topic.
- Memory text is sanitised and length-limited at injection time and explicitly labelled as reference material, not system instructions; it never overrides the system prompt.
- Shared files: events are kept for 7 days, auth for 180 days, context for 30 days; expired files are swept by both sides according to their TTLs. `context/*.lock`, `auth/*.lock`, `state.lock` and `lease.lock` are persistent coordination artifacts with no memory body; cleanup only handles `.json`.
- Clear removes **your own** data; the `users` row keeps `enabled` and `cleared_at` so events from before the clear cannot be consumed again.
- Uninstalling Feather Memory deletes its lease; the shared directory is not removed automatically and leftover files are left to TTL cleanup.

## 🤍 Technical Details

- **Layering (one-way dependencies; `core/` and `app/` never import astrbot)**:
  - Entry layer: `main.py` (plugin class, `@register`, the `/羽忆` command — wiring only)
  - Orchestration: `app/` (`service.py` lifecycle / event consumption / context rebuild / switch state; `chat.py` command parsing and replies)
  - Adapters: `adapters/` (`host.py` host registration and identity, `memory_feed.py` shared-file IO, `sqlite_store.py` storage and migrations, `file_lock.py` cross-platform locks)
  - Pure logic: `core/` (`contracts.py` contract models, `identity.py` user keys, `topics.py` topic classifier, `merge.py` merging two sources, `ids.py` ULIDs, `timeutil.py` time)
- **Storage**: `data/plugin_data/feather_memory/feather_memory.sqlite3`, WAL mode, `user_version` migrations; a memory change and its revision bump happen in one transaction.
- **Consistency**: context clears dirty only when the snapshot revision still matches; state transitions are serialized under one re-entrant lock plus a cross-process `state.lock`, with lock order state → context.
- **Shared files**: `lease.json`, `auth/<sha256>.json`, `events/<event_id>.json`, `context/<sha256>.json` under `data/plugin_data/_shared/feather_memory/v1/`. Every write is "temp file + `os.replace`"; context writes run "read revision → write temp → replace" inside a cross-process file lock.
- **Contract**: field and failure semantics in [`docs/contracts_v1.md`](docs/contracts_v1.md); v1 only adds fields, breaking changes go to a v2 directory.
- **Tests and CI**: `tests/` covers contracts, lease, auth, identity, group isolation, topics, consumption, context, decoupling and state. CI runs `compileall` + `ruff` + `mypy` + `pytest` across Ubuntu / Windows × Python 3.12 / 3.13 (four jobs), verification only — no deployment.
- **Backup and restore**: [`docs/backup_restore.md`](docs/backup_restore.md).
- **Market listing draft**: [`docs/market_listing.md`](docs/market_listing.md).

Local development:

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m mypy .
python -m pytest
```

## 📜 Changelog

#### v0.1.0

- First release: shared file contract v1 for service lease, user auth, event publishing/consumption and context rebuild
- Memory sources: explicit entries (preferences / background / goals) and the fixed topic enum of private normal readings, merged into a context of at most 600 characters
- Commands: view / export / remember / modify / forget / clear / enable / enable auto / enable topic / disable / status
- Context: up to 5 explicit entries take slots first, recent topics fill the rest; `context.min_topic_count` can require a topic to repeat before entering the context
- Isolation: group chats and the daily fortune neither feed nor read memory; original questions are never stored
- Reliability: SQLite WAL, event dedupe, serialized revisions, dirty rebuilds, TTL cleanup, cross-platform file locks

> Earlier versions: none — Feather Memory starts at v0.1.0.

---

## 🌙 Notes

- **Feather Memory needs Star Feather**: installing it alone produces no memory; it only consumes events Star Feather writes and only hands context back to Star Feather.
- **Memory is reference, not instruction**: it is sanitised, length-limited and labelled as reference material when injected; if the model restates it inaccurately, trust the cards and your own judgement.
- **Do not save credentials**: never store passwords, tokens or ID numbers through `/羽忆 记住`.
- **Uninstalling is not deleting**: disabling or uninstalling Feather Memory stops it from consuming and injecting, but saved memories remain in `plugin_data`; use `/羽忆 清空`, or remove the data during uninstall, to delete them.
- **Multiple instances**: only one Feather Memory instance should maintain the lease for a given shared directory; if several write it at once, the last writer wins.

---

## ⭐ Support & Thanks

- If you find it useful, star the [GitHub repository](https://github.com/yuluo-feather/astrbot_plugin_feather_memory)
- Found a problem or want a feature? Open an [Issue](https://github.com/yuluo-feather/astrbot_plugin_feather_memory/issues) or a Pull Request
- **Thanks**: the AstrBot framework, and [Star Feather Tarot](https://github.com/yuluo-feather/astrbot_plugin_star_feather) — without the events it writes, there would be nothing for Feather Memory to remember

## License

AGPL-3.0. See [LICENSE](LICENSE).
