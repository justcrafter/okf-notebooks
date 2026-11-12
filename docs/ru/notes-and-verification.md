# Заметки: запись, правка, проверка

[English version](../en/notes-and-verification.md)

## Формат заметки

Markdown с YAML frontmatter. Обязательные поля: `type` (задаётся сервером по типу), `title`, `description`
(одно предложение, показывается в поиске), тело не короче 20 символов. До 10 тегов (slug-строки), `links` —
ссылки на другие заметки блокнота вида `/decisions/x.md`, `sources`, `stale_after`.
Поля из `required` типа блокнота обязательны.

Агент не может менять поля `type`, `generated`, `status`, `verified`: их ставит сервер или человек.

## Жизнь заметки

1. Агент пишет заметку через `notebook_write` — статус `draft`.
2. Человек проверяет и подтверждает:

   ```bash
   uv run okf-notebooks verify kube-platform /decisions/use-argocd
   uv run okf-notebooks mark   kube-platform /decisions/use-argocd --status stable
   uv run okf-notebooks mark   kube-platform /decisions/old-way    --status deprecated
   ```

3. Если агент изменит проверенную заметку, `verified` снимается, а `stable` возвращается в `draft`
   (в ответе приходит предупреждение `verified-reset` / `status-reset`). Заметка `deprecated` остаётся
   устаревшей — это решение человека.

По умолчанию поиск не показывает `deprecated`; их можно запросить явно через `status`.

## stale_after

Тип может задать срок устаревания (`stale_after: 180d`). Сервер подставляет его в новую заметку, если автор
не указал другой. Некорректное значение в шаблоне даёт предупреждение `stale-after`, а запись типа не ломает.

## Поиск и чтение

- `notebook_search` — полнотекстовый (bm25, русский и английский), фильтры: `notebook`, `types`, `tags`, `status`.
- `notebook_list` — постраничный список с `cursor`.
- `notebook_read` — тело в маркерах с nonce и `etag`.

Индекс (`index.path`, по умолчанию `.index/fts.sqlite`) пересобирается сервером; его можно удалить, он создастся заново.

## Аудит ручных правок

Файлы в `data/` можно править руками. Проверить, что всё соответствует правилам:

```bash
uv run okf-notebooks validate                 # все блокноты
uv run okf-notebooks validate --notebook demo
```

Агент проверяет заметку без записи через `notebook_validate`.
