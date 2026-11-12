# Жизненный цикл блокнота и типов

[English version](../en/notebook-lifecycle.md)

Состояния блокнота: `proposed` → `active` → `archived`; отклонённая заявка уходит в архив с причиной (`rejected`).
Слаг занят, пока блокнот существует в любом состоянии, в том числе в архиве.

## Политики создания

`notebook_creation.default` (можно переопределять в `actors.<имя>.notebook_creation`):

| Политика | Что делает агент |
|---|---|
| `off` | создавать блокноты и типы нельзя |
| `proposal` (по умолчанию) | создаёт **заявку**, человек подтверждает |
| `direct` | блокнот или тип создаётся сразу |

Человек через CLI создаёт блокноты напрямую, без очереди.

## Агент просит новый блокнот

Агент вызывает `notebook_create`:

- `slug`: `^[a-z][a-z0-9-]{1,38}[a-z0-9]$` (шаблон меняется в `notebook_creation.slug_pattern`,
  зарезервированы `admin`, `tmp`, `archive`, `proposed` — `reserved_slugs`);
- `name` 3–80 символов, `description` 40–300, `scope` — что писать и чего не писать;
- `rationale` — почему не подходит ни один существующий блокнот;
- `preset` **или** `types` (до 12 типов).

Перед созданием сервер ищет похожие блокноты (имя, описание, `scope`). Если находит — возвращает ошибку
`similar_exists` со списком кандидатов. Агент либо использует существующий, либо повторяет вызов с
`confirm_distinct: true` и объясняет отличие в `rationale`; заявка помечается `[confirm_distinct]`.

## Человек разбирает очередь

```bash
uv run okf-notebooks notebook pending                       # заявки на блокноты и типы
uv run okf-notebooks notebook approve kube-platform         # в notebooks/, статус active
uv run okf-notebooks notebook reject  kube-platform --reason "дублирует platform-ops"
```

Причина отказа доступна автору через `notebook_describe`. Заявки живут в `_proposed/`, лимит — 3 на актора.

## Новый тип в существующем блокноте

Агент вызывает `notebook_type_define` (`notebook`, `name`, `description`, поля, `rationale`).
При `proposal` создаётся заявка:

```bash
uv run okf-notebooks type approve kube-platform Incident
uv run okf-notebooks type reject  kube-platform Incident --reason "…"
```

Человек может менять словарь сам:

```bash
uv run okf-notebooks type rename kube-platform Incident Outage
uv run okf-notebooks type delete kube-platform Outage
```

`rename` и `delete` отказывают, пока в блокноте есть заметки этого типа; при `rename` каталог типа не переименовывается.
Типы меняются только у активных блокнотов. Опции — `okf-notebooks type --help`.

## Архив и восстановление

```bash
uv run okf-notebooks notebook archive kube-platform    # в _archive/, слаг остаётся занятым
uv run okf-notebooks notebook restore kube-platform
```

Архивный блокнот не попадает в `notebooks_list` и поиск. `archive` недоступен агентам.

## Лимиты

`limits.max_notebooks` считает активные и ожидающие заявки вместе.
