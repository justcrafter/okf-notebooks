"""ASGI application: /healthz plus the MCP endpoint behind the guard middleware."""

from __future__ import annotations

import contextlib
import ipaddress
import json
import re
import time
from collections import OrderedDict, deque

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from okf_notebooks.auth import (
    TokenStore,
    actor_for_token,
    reset_current_actor,
    set_current_actor,
    tokens_path,
)
from okf_notebooks.config import Config, parse_rate
from okf_notebooks.lifecycle import cleanup_tmp

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}
_VERSION_RE = re.compile(r"[^A-Za-z0-9._+-]")
_MAX_SESSIONS = 1024


async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def _ipv4_network(entry: str) -> ipaddress.IPv4Network | None:
    """CIDR (`192.168.88.0/24`) or dotted prefix (`192.168.88` = /24, `10.1` = /16); else None."""
    if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){0,3}(/\d{1,2})?", entry):
        return None
    addr, _, bits = entry.partition("/")
    octets = addr.split(".")
    try:
        return ipaddress.IPv4Network(
            ".".join(octets + ["0"] * (4 - len(octets))) + "/" + (bits or str(8 * len(octets))),
            strict=False,
        )
    except ValueError:
        return None


def host_allowed(host_header: str, allowed: list[str]) -> bool:
    """Empty `allowed` means loopback only. Entries without a port match any port.

    An entry may also be an IPv4 subnet (any port): CIDR `192.168.88.0/24` or prefix `192.168.88`.
    """
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1]:8765
        bare = host.split("]", 1)[0] + "]"
    else:
        bare = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    candidates = {h.strip().lower() for h in allowed} if allowed else _LOOPBACK_HOSTS
    if host in candidates or bare in candidates:
        return True
    try:
        ip = ipaddress.IPv4Address(bare)
    except ValueError:
        return False
    return any(net is not None and ip in net for net in map(_ipv4_network, candidates))


def sanitize_version(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    v = _VERSION_RE.sub("", value.strip())[:64]
    return v or None


def initialize_client_version(body: bytes) -> str | None:
    """Client version from an MCP `initialize` request body, else None."""
    try:
        msg = json.loads(body)
        if isinstance(msg, dict) and msg.get("method") == "initialize":
            return sanitize_version(msg["params"]["clientInfo"]["version"])
    except (ValueError, KeyError, TypeError):
        pass
    return None


class SlidingWindowLimiter:
    def __init__(self, limit: int, window: int):
        self.limit, self.window = limit, window
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str) -> int:
        """0 if allowed (and counted); otherwise seconds until a slot frees up."""
        now = time.monotonic()
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.limit:
            return max(1, int(self.window - (now - q[0])) + 1)
        q.append(now)
        return 0


class GuardMiddleware:
    """Bearer token -> Host/Origin -> body size -> rate limit. /healthz is exempt."""

    def __init__(self, app: ASGIApp, config: Config):
        self.app = app
        self.config = config
        self.store = TokenStore(tokens_path(config))
        n, window = parse_rate(config.server.rate_limit_per_token)
        self.limiter = SlidingWindowLimiter(n, window)
        self.sessions: OrderedDict[tuple[str, str], str] = OrderedDict()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == "/healthz":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}

        # 1. Bearer token (before anything else touches the request)
        auth = headers.get("authorization", "")
        scheme, _, presented = auth.partition(" ")
        record = self.store.verify(presented.strip()) if scheme.lower() == "bearer" else None
        if record is None:
            await self._reject(
                scope, receive, send, 401, "unauthorized", {"WWW-Authenticate": 'Bearer realm="okf-notebooks"'}
            )
            return

        # 2. Host / Origin
        srv = self.config.server
        if not host_allowed(headers.get("host", ""), srv.allowed_hosts):
            await self._reject(scope, receive, send, 421, "host not allowed")
            return
        origin = headers.get("origin")
        if origin is not None and origin not in srv.allowed_origins:
            await self._reject(scope, receive, send, 403, "origin not allowed")
            return

        # 3. Body size (buffered up to the limit, then replayed to the app)
        limit = srv.max_body_bytes
        declared = headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await self._reject(scope, receive, send, 413, "request body too large")
            return
        body, trailing = bytearray(), []
        while True:
            msg = await receive()
            if msg["type"] != "http.request":
                trailing.append(msg)
                break
            body += msg.get("body", b"")
            if len(body) > limit:
                await self._reject(scope, receive, send, 413, "request body too large")
                return
            if not msg.get("more_body"):
                break

        # 4. Rate limit per token
        retry = self.limiter.check(record["id"])
        if retry:
            await self._reject(
                scope, receive, send, 429, "rate limit exceeded", {"Retry-After": str(retry)}
            )
            return

        actor = actor_for_token(self.config, record)
        sid = headers.get("mcp-session-id")
        version = initialize_client_version(bytes(body))
        if version is None and sid:
            version = self.sessions.get((record["id"], sid))
        if version is not None:
            from dataclasses import replace

            actor = replace(actor, client_version=version)

        replay = [{"type": "http.request", "body": bytes(body), "more_body": False}, *trailing]

        async def replay_receive() -> Message:
            return replay.pop(0) if replay else await receive()

        async def capture_send(message: Message) -> None:
            if message["type"] == "http.response.start" and version is not None and not sid:
                for k, v in message.get("headers", []):
                    if k.lower() == b"mcp-session-id":
                        self.sessions[(record["id"], v.decode("latin-1"))] = version
                        while len(self.sessions) > _MAX_SESSIONS:
                            self.sessions.popitem(last=False)
            await send(message)

        ctx = set_current_actor(actor)
        try:
            await self.app(scope, replay_receive, capture_send)
        finally:
            reset_current_actor(ctx)

    async def _reject(
        self, scope: Scope, receive: Receive, send: Send, status: int, error: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        response = Response(
            json.dumps({"error": error}), status_code=status,
            media_type="application/json", headers=headers,
        )
        await response(scope, receive, send)


class _MountAt:
    """Serve `app` at `prefix` and `prefix/...` alike (Starlette's Mount redirects the bare path)."""

    def __init__(self, app: ASGIApp, prefix: str):
        self.app = app
        self.prefix = "/" + prefix.strip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope["path"]
        if scope["type"] == "http" and (path == self.prefix or path.startswith(self.prefix + "/")):
            sub = dict(scope)
            sub["root_path"] = scope.get("root_path", "") + self.prefix
            sub["path"] = path[len(self.prefix) :] or "/"
            await self.app(sub, receive, send)
            return
        await Response("not found", status_code=404)(scope, receive, send)


class _Dispatch:
    """MCP endpoint and /healthz go through the Token guard; everything else is the Review UI."""

    def __init__(self, guarded: ASGIApp, ui: ASGIApp, mcp_path: str):
        self.guarded, self.ui = guarded, ui
        self.prefix = "/" + mcp_path.strip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope["path"]
            if not (path == "/healthz" or path == self.prefix or path.startswith(self.prefix + "/")):
                await self.ui(scope, receive, send)
                return
        await self.guarded(scope, receive, send)


def create_app(config: Config, mcp_app: ASGIApp | None = None, ui_app: ASGIApp | None = None) -> ASGIApp:
    """`mcp_app` is the MCP endpoint; it is mounted at server.path behind the guard.

    `ui_app` (the Review UI) serves every other path with its own Human-session auth.
    """
    cleanup_tmp(config.root)  # leftovers of crashed notebook assemblies
    routes: list = [Route("/healthz", healthz)]
    lifespan = None
    if mcp_app is not None:
        routes.append(Mount("/", app=_MountAt(mcp_app, config.server.path)))
        # Starlette does not run a mounted app's lifespan; the MCP session manager needs it.
        sub = getattr(getattr(mcp_app, "router", None), "lifespan_context", None)
        if sub is not None:

            @contextlib.asynccontextmanager
            async def lifespan(_app: Starlette):
                async with sub(mcp_app):
                    yield

    guarded = GuardMiddleware(Starlette(routes=routes, lifespan=lifespan), config)
    return _Dispatch(guarded, ui_app, config.server.path) if ui_app is not None else guarded
