# Changelog / Список изменений

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

Все заметные изменения описываются здесь. Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии — [SemVer](https://semver.org/lang/ru/).

## [Unreleased]

### Added / Добавлено

- Project site at <https://okf-notebooks.kazakov.dev/> (`site/`, Hugo, EN/RU): landing page, install guide, scenarios
  and documentation; its own nginx image `ghcr.io/justcrafter/okf-notebooks-site`. / Сайт проекта (`site/`, Hugo,
  EN/RU): лендинг, установка, сценарии и документация; свой образ на nginx.
- Presets `personal-finance` (accounts, debts, budget, goals, investments, reports, decisions) and `agent-retros`
  (agent sessions, patterns, environment improvements) in `presets/`, with documentation pages. / Пресеты
  `personal-finance` и `agent-retros` в `presets/` со страницами документации.
- Review UI: a text width switcher (narrow / wide) in the top-right corner of a note on screens 1600px and wider; the
  choice is remembered in the browser. / Review UI: переключатель ширины текста (узко / широко) в правом верхнем углу
  заметки на экранах от 1600px; выбор запоминается в браузере.

### Changed / Изменено

- Documentation moved from `docs/` to `site/content/`; the READMEs keep the idea and a quick start and link to the
  site. Release notes moved to `releases/`. / Документация переехала из `docs/` в `site/content/`; в README остались
  идея и быстрый старт со ссылками на сайт. Release notes — в `releases/`.

- Wide screens (from 1600 px): 20% | 60% | 20% layout. The notebook tree hugs the left edge, the right panel the right
  edge, the note is centred in a reading column up to 760 px; narrower windows keep the compact layout. / Широкие
  экраны (от 1600 px): раскладка 20% | 60% | 20%. Дерево блокнота прижато к левому краю, правая панель — к правому,
  заметка по центру в колонке чтения до 760 px; на более узких окнах прежняя компактная раскладка.

## [0.2.0] - 2026-11-14

Review UI redesign; no changes to MCP, storage or configuration. / Редизайн веб-интерфейса ревью; MCP, хранилище и
конфигурация не менялись.

### Changed / Изменено

- Dropdowns (notebook and language switchers) draw their own arrow at a fixed distance from the edge; the native arrow
  no longer shifts or overlaps the text. / Выпадающие списки (блокнот и язык) рисуют свою стрелку на фиксированном
  расстоянии от края; нативная стрелка больше не съезжает и не наезжает на текст.
- Right panel of a note: a consistent spacing rhythm, sections separated by lines, counters in headers, links and
  citations as roomy rows, a full-width trust control. The column is 320 px wide. / Правая панель заметки: единый ритм
  отступов, секции разделены линиями, счётчики в заголовках, ссылки и цитирования — просторные строки, статус доверия
  на всю ширину. Ширина колонки — 320 px.
- Comments: a "Comment" button with an icon, a roomier popup, quote and reply tree with a guide line, text-link
  "Reply", a footer with "Resolve" and "Delete", cards with "Resolved" and "Detached" badges in the side list. Authors
  are shown by name only (an agent name or `human`), without avatars. / Комментарии: кнопка «Комментировать» с иконкой,
  просторное окно, цитата и дерево ответов с направляющей, «Ответить» как текстовая ссылка, нижняя панель
  «Решено»/«Удалить», карточки с бейджами «Решён» и «Потерян» в списке справа. Авторы показываются только именем
  (имя агента или `human`), без аватарок.

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
