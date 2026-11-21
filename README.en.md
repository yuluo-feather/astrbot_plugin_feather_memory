# Feather Memory (astrbot_plugin_feather_memory)

Feather Memory is an optional memory plugin for **Star Feather Tarot** (`astrbot_plugin_star_feather`). It remembers the preferences, background and goals you save explicitly, plus recent topics inferred from private normal readings, and offers that memory back to Star Feather as optional context for the next reading. Without Feather Memory, Star Feather behaves exactly as before.

## Requirements

- AstrBot `>=4.16,<5`, Python 3.12+
- Star Feather Tarot `>=0.11,<1` (provides the `_shared/feather_memory/v1` file contract)
- Enable Feather Memory in its plugin configuration; enable memory delivery and memory injection on the Star Feather side

## Deployment prerequisites

- If AstrBot uses an explicit `plugin_set` list, it must contain `feather_memory` (the `name` in `metadata.yaml`). Without it the plugin may be loaded while its command handlers are filtered out: `/羽忆` gets no response and the message falls through to the LLM.
- Enable `memory.enabled` in Feather Memory; enable `memory.feed_enabled` and `memory.context_enabled` on the Star Feather side.
- Reload the corresponding plugin after changing configuration; Feather Memory writes its service lease within 5–10 seconds of startup.

## Commands (saving and viewing are private-chat only)

| Command | Action |
|---|---|
| `/羽忆` | Show saved memories and recent topics |
| `/羽忆 记住 <text>` | Save a preference / background / goal (enables the master switch) |
| `/羽忆 忘记 <id>` | Delete one saved memory |
| `/羽忆 清空` | Clear all data after a second confirmation |
| `/羽忆 开启` | Turn on the master switch |
| `/羽忆 开启 自动` | Allow private normal readings to feed recent topics |
| `/羽忆 开启 主题` | Allow events to carry a fixed topic enum |
| `/羽忆 关闭` | Close and delete auth, context and pending events |
| `/羽忆 状态` | Show lease, switches, auth and context status |

In group chats only `/羽忆 关闭` and `/羽忆 状态` are accepted, and no personal memory content is shown.

## What is stored

- Saved: short explicit entries; spread, cards and the fixed topic enum of private normal readings / single-card draws.
- Not stored: group-chat events, daily fortune, full chat logs, original questions.
- Topics use a fixed enum (work / study / relationship / family / finance / health / social / travel). A question hitting several topics, or none, yields an empty topic.
- Do not save passwords, tokens or account credentials. Memory text is injected as untrusted reference material and never replaces the system prompt.

## Data location and uninstall

- Memory bodies live only in Feather Memory's SQLite database: `data/plugin_data/feather_memory/feather_memory.sqlite3`.
- Shared files under `data/plugin_data/_shared/feather_memory/v1/`: service lease, auth, events and context.
- After uninstalling Feather Memory the lease expires within 5 minutes; leftover shared files are removed by TTL cleanup (events after 7 days, auth / context at their own expiry).
- Host backups include `plugin_data`, so the data above is backed up with the host.

## Contract and versioning

- Shared contract v1 is frozen. Field and failure semantics: [`docs/contracts_v1.md`](docs/contracts_v1.md).
- Contract v1 only adds fields; breaking changes go to a v2 directory.
- Backup and restore: [`docs/backup_restore.md`](docs/backup_restore.md).
- Market listing draft: [`docs/market_listing.md`](docs/market_listing.md).

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m mypy .
python -m pytest
```

There are no third-party runtime dependencies; only the Python standard library and the AstrBot host API are used.

## License

AGPL-3.0. See [LICENSE](LICENSE).
