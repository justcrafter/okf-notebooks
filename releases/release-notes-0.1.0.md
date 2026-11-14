## okf-notebooks 0.1.0

First public release. / Первый публичный релиз.

**EN.** okf-notebooks is an MCP server that gives AI agents shared notebooks stored as Markdown under git.
Agents write drafts; only a human can mark a note as verified or stable.

**RU.** okf-notebooks — MCP-сервер, который даёт ИИ-агентам общие блокноты заметок в Markdown под git.
Агенты пишут черновики; подтвердить заметку может только человек.

### Highlights / Главное

- **MCP over Streamable HTTP**: list, search (SQLite FTS5), read, write, update, validate; optimistic locking by `etag`.
  / **MCP по Streamable HTTP**: список, поиск (SQLite FTS5), чтение, запись, правка, проверка; оптимистичная блокировка по `etag`.
- **Plain files in git**: OKF v0.2 bundles, one commit per write, optional background push to a private remote.
  / **Обычные файлы в git**: OKF v0.2, коммит на каждую запись, необязательный фоновый push в приватный remote.
- **Several agents, one trust model**: actors by Bearer token, per-actor permissions, rate limits, Host/Origin checks.
  / **Несколько агентов, одна модель доверия**: акторы по Bearer-токену, права на актора, лимиты, проверка Host/Origin.
- **Types and presets**: `core`, `dev-project` and custom YAML; new notebooks and types are requested by agents and approved by a human.
  / **Типы и пресеты**: `core`, `dev-project` и свои YAML; новые блокноты и типы агенты запрашивают, решает человек.
- **Review UI**: reading, status and `verified`, revision history with diffs, links and backlinks, Mermaid,
  comment threads for agents, light/dark themes, English and Russian.
  / **Веб-интерфейс ревью**: чтение, статус и `verified`, история ревизий с diff, ссылки и обратные ссылки, Mermaid,
  треды комментариев для агентов, светлая и тёмная темы, английский и русский.
- **Docker**: read-only root filesystem, dropped capabilities, `linux/amd64` and `linux/arm64`.
  / **Docker**: read-only файловая система, сброшенные capabilities, `linux/amd64` и `linux/arm64`.

### Quick start / Быстрый старт

```bash
docker pull ghcr.io/justcrafter/okf-notebooks:0.1.0
```

Full instructions: [README](https://github.com/justcrafter/okf-notebooks#readme) ·
[README.ru](https://github.com/justcrafter/okf-notebooks/blob/main/README.ru.md).
Подробная инструкция — в README выше.

Full changelog: [CHANGELOG.md](https://github.com/justcrafter/okf-notebooks/blob/main/CHANGELOG.md).
