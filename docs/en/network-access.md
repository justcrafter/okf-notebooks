# Network access

[Русская версия](../ru/network-access.md)

By default the server accepts only requests whose `Host` is loopback (`localhost`, `127.0.0.1`, `[::1]`).
Any other `Host` is rejected with **421**, a foreign `Origin` with **403**. This protects against DNS rebinding.
Every request requires `Authorization: Bearer <token>`.

## This machine only

```yaml
server:
  host: 127.0.0.1
  port: 8765
  allowed_hosts: ["127.0.0.1:8765", "localhost:8765"]
```

## Home network or VPN

The server listens on all interfaces and the client addresses are given as subnets:

```yaml
server:
  host: 0.0.0.0
  allowed_hosts:
    - 192.168.88            # prefix = 192.168.88.0/24
    - 10.8.0.0/16           # CIDR
    - localhost
```

The subnet is compared with the `Host` header (the address the client **used to reach** the server), not with the
client's own address. IPv4 subnets and any port are supported; an entry without a port allows any port, `host:port`
allows one. Restrict who can connect at the firewall level or with `server.host`.

## Tailscale / a host name

```yaml
server:
  allowed_hosts: ["notebooks.tailnet.ts.net"]
```

The client needs `https://` (through `tailscale serve` or a reverse proxy). Plain `http://` is acceptable only in a
trusted network; `mcp-remote` in Claude Desktop must then be started with `--allow-http`.

## Reverse proxy

The proxy must pass the original `Host` (in nginx: `proxy_set_header Host $host;`), and its public name must be in
`allowed_hosts`. If you need CORS or a browser client, add the origin to `server.allowed_origins`.

## Checking

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://192.168.88.10:8765/healthz
curl -s -H "Host: evil.example.com" http://127.0.0.1:8765/mcp   # 421
```

Clients: [Claude Code and Claude Desktop](../../README.md#connecting-an-agent). Never forward the port on your router to the internet.
