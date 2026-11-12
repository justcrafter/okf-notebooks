# Contributing

**English** · [Русский](#вклад-в-проект)

Thanks for your interest in okf-notebooks. Bug reports, documentation fixes and pull requests are welcome.

## Setup

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), `git`, Node.js 22 for the frontend, and Docker only
for the image test.

```bash
uv sync                 # Python dependencies, dev tools included
uv run pytest           # all tests (the Docker image test is skipped without Docker)
uv run ruff check .     # linter

cd web
npm ci
npm test                # vitest
npm run build           # builds into src/okf_notebooks/webui_dist
```

Sources are in `src/okf_notebooks/` (see the module list in the [README](README.md#development)); the Review UI is
in `web/`. Domain terms are defined in the [glossary](docs/en/glossary.md): please use them in code and docs.

## Pull requests

- Open an issue first for anything larger than a small fix, so the approach can be agreed.
- Keep a change focused, and add or update tests. A bug fix starts with a failing test.
- `uv run pytest` and `uv run ruff check .` must pass; so must `npm test` and `npm run build` for UI changes.
- Code, comments, error messages and tool descriptions are in English. Documentation is bilingual: change both
  `docs/en/` and `docs/ru/` (and `README.md` / `README.ru.md`) together. If you cannot write Russian, say so in the
  PR and a maintainer will help with the translation.
- Never commit secrets, tokens or real notebook data.

## Reporting security issues

Do not open a public issue; follow [SECURITY.md](SECURITY.md).

## License

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE).

---

# Вклад в проект

Спасибо за интерес к okf-notebooks. Приветствуются сообщения об ошибках, правки документации и pull request-ы.

## Окружение

Нужны Python 3.11+, [uv](https://docs.astral.sh/uv/), `git`, Node.js 22 для фронтенда и Docker только для теста образа.

```bash
uv sync                 # зависимости Python вместе с dev-инструментами
uv run pytest           # все тесты (тест Docker-образа без Docker пропускается)
uv run ruff check .     # линтер

cd web
npm ci
npm test                # vitest
npm run build           # собирает в src/okf_notebooks/webui_dist
```

Исходники — в `src/okf_notebooks/` (список модулей — в [README](README.ru.md#разработка)), веб-интерфейс — в `web/`.
Термины предметной области описаны в [глоссарии](docs/ru/glossary.md): используйте их в коде и документации.

## Pull request-ы

- Для всего, что больше мелкой правки, сначала откройте issue, чтобы согласовать подход.
- Держите изменение узким, добавляйте или обновляйте тесты. Исправление бага начинается с падающего теста.
- `uv run pytest` и `uv run ruff check .` должны проходить; для правок UI ещё `npm test` и `npm run build`.
- Код, комментарии, сообщения об ошибках и описания инструментов пишутся на английском. Документация двуязычная:
  меняйте `docs/en/` и `docs/ru/` (и `README.md` / `README.ru.md`) вместе. Если не пишете по-русски, скажите об
  этом в PR, и мейнтейнер поможет с переводом.
- Не коммитьте секреты, токены и реальные данные блокнотов.

## Уязвимости

Не открывайте публичный issue, см. [SECURITY.md](SECURITY.md).

## Лицензия

Отправляя вклад, вы соглашаетесь, что он распространяется под [лицензией MIT](LICENSE).
