# Формат блокнота (OKF)

[English version](../en/okf-format.md)

okf-notebooks хранит заметки в формате **Open Knowledge Format** (OKF, [okf.md](https://okf.md/), MIT): каталог
Markdown-файлов с YAML-frontmatter. Сервер пишет OKF версии `0.2`. Здесь описано, как блокнот выглядит на диске;
точное определение формата — в спецификации OKF.

## Структура каталога

```
<root>/                         один git-репозиторий
├── notebooks/
│   └── <slug>/                 один блокнот = один OKF-бандл
│       ├── index.md            манифест: okf_version, заголовок, список заметок (генерирует сервер)
│       ├── log.md              журнал действий (только дописывание)
│       ├── .okf/
│       │   ├── notebook.yaml   имя, описание, scope, пресет, типы, статус
│       │   ├── okf-base.yaml   базовый словарь
│       │   └── templates/      шаблоны типов
│       ├── decisions/          подкаталог на каждый тип
│       │   └── use-argocd.md   заметка (concept): id /decisions/use-argocd
│       └── terms/
├── _proposed/                  блокноты, ожидающие решения человека
├── _archive/                   архивные блокноты
├── .auth/tokens.json           хэши токенов (SHA-256)
├── .index/fts.sqlite           полнотекстовый индекс (пересоздаваемый)
└── .comments/threads.sqlite    треды комментариев (включите в бэкап)
```

## Заметка

```markdown
---
type: Decision
title: Use ArgoCD for deployments
description: Why the platform team deploys through ArgoCD.
tags: [adr, deploy]
sources: [https://argo-cd.readthedocs.io/]
status: draft
generated:
  by: claude-code/1.2.3
  at: '2026-11-10T14:39:13Z'
---
# Decision

Тело в Markdown, не короче 20 символов.
```

- `type`, `generated`, `status` и `verified` ставит сервер или человек, агент их не задаёт.
- `status` — `draft`, `stable` или `deprecated`; всё, что пишет агент, начинается с `draft`.
- id заметки — путь внутри блокнота без расширения: `/decisions/use-argocd`.

Блокноты — обычные файлы: их можно читать в любом редакторе, смотреть через `git diff` и откатывать через
`git revert`. Правки вне сервера проверяет `okf-notebooks validate`.
Правила и поля — в [заметках и проверке](notes-and-verification.md), типы — в [пресетах](presets.md).
