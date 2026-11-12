# Доступ по сети

[English version](../en/network-access.md)

По умолчанию сервер принимает запросы только с `Host`, равным loopback (`localhost`, `127.0.0.1`, `[::1]`).
Остальные `Host` отклоняются с кодом **421**, чужой `Origin` — с **403**. Это защита от DNS-rebinding.
Каждый запрос требует `Authorization: Bearer <токен>`.

## Только эта машина

```yaml
server:
  host: 127.0.0.1
  port: 8765
  allowed_hosts: ["127.0.0.1:8765", "localhost:8765"]
```

## Домашняя сеть или VPN

Сервер слушает все интерфейсы, адреса клиентов указаны подсетью:

```yaml
server:
  host: 0.0.0.0
  allowed_hosts:
    - 192.168.88            # префикс = 192.168.88.0/24
    - 10.8.0.0/16           # CIDR
    - localhost
```

Подсеть сравнивается с заголовком `Host` (по какому адресу клиент **обратился** к серверу), а не с адресом
клиента. Поддерживаются IPv4-подсети и любые порты; запись без порта разрешает любой порт, `host:port` — один.
Ограничить, кто может подключиться, надо на уровне файрвола или `server.host`.

## Tailscale / имя хоста

```yaml
server:
  allowed_hosts: ["notebooks.tailnet.ts.net"]
```

Клиенту нужен `https://` (через `tailscale serve` или reverse proxy). Голый `http://` допустим только в доверенной
сети; `mcp-remote` в Claude Desktop тогда запускается с `--allow-http`.

## Reverse proxy

Прокси должен передавать исходный `Host` (в nginx — `proxy_set_header Host $host;`) и входить в `allowed_hosts`
по публичному имени. Если нужен CORS/браузерный клиент, добавьте источник в `server.allowed_origins`.

## Проверка

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://192.168.88.10:8765/healthz
curl -s -H "Host: evil.example.com" http://127.0.0.1:8765/mcp   # 421
```

Клиенты: [Claude Code и Claude Desktop](../../README.ru.md#подключение-агента). Не пробрасывайте порт на роутере в интернет.
