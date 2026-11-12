# Security policy

**English** · [Русский](#политика-безопасности)

## Supported versions

Only the latest release receives security fixes.

## Reporting a vulnerability

Please do not open a public issue. Report it privately through GitHub:
**Security → Report a vulnerability** on <https://github.com/justcrafter/okf-notebooks/security/advisories/new>.

Include what you found, the version, steps to reproduce and the impact. You can expect an acknowledgement within a
few days. Please give us reasonable time to fix the issue before disclosing it.

## Scope and threat model

okf-notebooks is a self-hosted server that stores notes written by AI agents. Areas that matter most:

- authentication (Bearer tokens stored as SHA-256, the Human password and session cookie);
- the boundary between an agent's permissions and the human's (`verify`, `archive`, `mark` are CLI/UI only);
- treating notebook text as data (nonce markers), the secret scanner and path handling inside `root`;
- the Review UI (CSP, Markdown rendering without raw HTML, same-origin checks);
- host and origin validation (DNS-rebinding protection).

Running the server on an untrusted network without TLS, forwarding its port to the internet, or sharing one token
between machines is outside the supported setup; see [network access](docs/en/network-access.md).

---

# Политика безопасности

## Поддерживаемые версии

Исправления безопасности получает только последний релиз.

## Как сообщить об уязвимости

Не открывайте публичный issue. Сообщите приватно через GitHub:
**Security → Report a vulnerability**, <https://github.com/justcrafter/okf-notebooks/security/advisories/new>.

Укажите, что вы нашли, версию, шаги воспроизведения и последствия. Подтверждение придёт в течение нескольких дней.
Просим дать разумное время на исправление до публикации деталей.

## Область и модель угроз

okf-notebooks — самостоятельно развёртываемый сервер, который хранит заметки, написанные ИИ-агентами. Важнее всего:

- аутентификация (Bearer-токены в виде SHA-256, пароль Human и cookie сессии);
- граница между правами агента и человека (`verify`, `archive`, `mark` доступны только через CLI и UI);
- текст блокнота как данные (маркеры с nonce), сканер секретов и работа с путями внутри `root`;
- веб-интерфейс ревью (CSP, Markdown без raw HTML, проверка same-origin);
- проверка Host и Origin (защита от DNS-rebinding).

Запуск сервера в недоверенной сети без TLS, проброс его порта в интернет и один токен на несколько машин не входят в
поддерживаемую конфигурацию; см. [доступ по сети](docs/ru/network-access.md).
