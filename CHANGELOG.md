# Changelog / Список изменений

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

Все заметные изменения описываются здесь. Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии — [SemVer](https://semver.org/lang/ru/).

## [0.1.0] - 2026-11-12

First public release. / Первый публичный релиз.

### Added / Добавлено

- MCP server over Streamable HTTP with notebook tools: list, search (SQLite FTS5), read, write, update, validate,
  with optimistic locking by `etag`. / MCP-сервер по Streamable HTTP с инструментами блокнотов: список, поиск
  (SQLite FTS5), чтение, запись, правка, проверка; оптимистичная блокировка по `etag`.
- Notebooks as OKF v0.2 Markdown bundles under one git repository, one commit per write, optional background push to
  a private remote. / Блокноты как OKF v0.2 Markdown-бандлы под одним git-репозиторием, коммит на каждую запись,
  необязательный фоновый push в приватный remote.
- Actors identified by Bearer token, per-actor permissions, rate limits, host and origin checks.
  / Акторы по Bearer-токену, права на актора, лимиты запросов, проверка Host и Origin.
- Types and presets (`core`, `dev-project`, custom YAML), notebook and type requests approved by a human.
  / Типы и пресеты (`core`, `dev-project`, свои YAML), заявки на блокноты и типы с решением человека.
- Review UI: reading, status and `verified`, revision history with diffs, links and backlinks, tables, Mermaid,
  comment threads for agents, light and dark themes, English and Russian. / Веб-интерфейс ревью: чтение, статус и
  `verified`, история ревизий с diff, ссылки и обратные ссылки, таблицы, Mermaid, треды комментариев для агентов,
  светлая и тёмная темы, английский и русский.
- Docker image and Compose file (read-only root filesystem, dropped capabilities). / Docker-образ и Compose-файл
  (read-only файловая система, сброшенные capabilities).
- Bilingual documentation (English and Russian). / Двуязычная документация (английский и русский).
