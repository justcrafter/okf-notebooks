# Подключение существующей OKF-базы

[English version](../en/adopt-existing.md)

Если у вас уже есть каталог с OKF-заметками (например, папка `docs/` проекта), его можно взять под управление:

```bash
uv run okf-notebooks notebook adopt ~/code/myproject/docs --slug myproject
```

Что делает команда:

- копирует каталог в `notebooks/<slug>/` (`.git` и `.obsidian` не копируются), исходник не трогает;
- если нет `.okf/notebook.yaml`, создаёт его;
- проверяет все файлы по правилам валидатора; при ошибках блокнот **не создаётся**, список нарушений выводится;
- делает отдельный коммит `notebook(<slug>): adopt bundle`.

Условия: слаг подходит под `slug_pattern`, не занят и не зарезервирован; в каталоге нет символических ссылок;
не превышен `limits.max_notebooks`. Если `--slug` не указан, берётся имя каталога.

После adopt:

```bash
uv run okf-notebooks validate --notebook myproject
uv run okf-notebooks notebook pending     # заявок нет: блокнот сразу active
```

Заполните `description` и `scope` в `.okf/notebook.yaml`, иначе агенту трудно выбрать блокнот.
Если типы в старых заметках отличаются от словаря блокнота, поправьте их через `type rename` или добавьте нужные.
