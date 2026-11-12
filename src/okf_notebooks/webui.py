"""Review UI: Human session auth, JSON API under /api, and the built SPA under /.

Mounted only when the Human password is set (see ADR 0001). The Human session is a signed,
stateless cookie; it never carries a Token and the MCP endpoint never accepts it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from okf_notebooks import history as hist
from okf_notebooks.app import SlidingWindowLimiter, host_allowed
from okf_notebooks.auth import mentionable_actors
from okf_notebooks.comments import HUMAN
from okf_notebooks.config import Config
from okf_notebooks.lifecycle import Lifecycle
from okf_notebooks.registry import NotebookNotFound
from okf_notebooks.store import Concept, Store, StoreError
from okf_notebooks.validator import extract_links

PASSWORD_ENV = "OKF_NOTEBOOKS_UI_PASSWORD"
COOKIE = "okf_session"
SESSION_TTL = 12 * 3600
_STATUSES = ("draft", "stable", "deprecated")
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
_MAX_CONFIG_FILES = 100
_MAX_CONFIG_BYTES = 64 * 1024
_HTTP_CODES = {"not_found": 404, "conflict": 409, "busy": 503, "limit_exceeded": 409}


def default_dist() -> Path:
    return Path(__file__).parent / "webui_dist"


class _Json(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, default=str, ensure_ascii=False).encode("utf-8")


def _err(status: int, message: str) -> JSONResponse:
    return _Json({"error": message}, status_code=status, headers={"Cache-Control": "no-store"})


def _ok(data: Any, status: int = 200) -> JSONResponse:
    return _Json(data, status_code=status, headers={"Cache-Control": "no-store"})


class Sessions:
    """Stateless signed cookie: `<expiry>.<hmac>`; changing the password invalidates every session."""

    def __init__(self, password: str):
        self._pw = password.encode("utf-8")
        self._key = hashlib.sha256(b"okf-notebooks-human-session\0" + self._pw).digest()

    def check_password(self, given: str) -> bool:
        a = hashlib.sha256(given.encode("utf-8")).digest()
        return hmac.compare_digest(a, hashlib.sha256(self._pw).digest())

    def issue(self, now: float | None = None) -> str:
        exp = str(int((now or time.time()) + SESSION_TTL))
        return f"{exp}.{self._sign(exp)}"

    def valid(self, cookie: str | None, now: float | None = None) -> bool:
        if not cookie or "." not in cookie:
            return False
        exp, _, sig = cookie.partition(".")
        if not exp.isdigit() or not hmac.compare_digest(sig, self._sign(exp)):
            return False
        return int(exp) > (now or time.time())

    def _sign(self, exp: str) -> str:
        mac = hmac.new(self._key, exp.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def _concept_json(notebook: str, c: Concept, notebook_status: str = "active", raw: str | None = None) -> dict[str, Any]:
    out = {
        "notebook": notebook, "notebook_status": notebook_status, "id": c.id,
        "frontmatter": c.frontmatter, "body": c.body, "etag": c.etag,
    }  # fmt: skip
    if raw is not None:
        out["raw"] = raw
    return out


def _tags(frontmatter: dict[str, Any]) -> list[str]:
    value = frontmatter.get("tags")
    return [str(t) for t in value] if isinstance(value, list) else []


def _cid(request: Request) -> str:
    return "/" + request.path_params["type"] + "/" + request.path_params["name"]


def build(config: Config, store: Store, lifecycle: Lifecycle, password: str, dist: Path | None = None) -> ASGIApp:
    sessions = Sessions(password)
    dist = dist or default_dist()
    login_limiter = SlidingWindowLimiter(10, 60)

    def guarded(fn: Callable[[Request], Response], *, write: bool = False) -> Callable[[Request], Response]:
        def handler(request: Request) -> Response:
            if not sessions.valid(request.cookies.get(COOKIE)):
                return _err(401, "unauthorized")
            if write and not _same_origin(request):
                return _err(403, "origin not allowed")
            try:
                return fn(request)
            except NotebookNotFound as e:
                return _err(404, str(e))
            except StoreError as e:
                return _err(_HTTP_CODES.get(getattr(e, "code", ""), 400), str(e))

        return handler

    def _same_origin(request: Request) -> bool:
        origin = request.headers.get("origin")
        host = request.headers.get("host", "")
        if origin is None:
            return False
        netloc = origin.split("://", 1)[-1]
        return netloc == host or origin in config.server.allowed_origins

    def session(request: Request) -> Response:
        return _ok({"authenticated": sessions.valid(request.cookies.get(COOKIE)), "git": store.git and store.commit_per_write})

    async def login(request: Request) -> Response:
        if not _same_origin(request):
            return _err(403, "origin not allowed")
        wait = login_limiter.check("login")
        if wait:
            return JSONResponse({"error": "too many attempts"}, status_code=429, headers={"Retry-After": str(wait)})
        try:
            body = await request.json()
            given = body.get("password") if isinstance(body, dict) else None
        except ValueError:
            given = None
        if not isinstance(given, str) or not sessions.check_password(given):
            return _err(401, "wrong password")
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        resp = _ok({"authenticated": True})
        resp.set_cookie(COOKIE, sessions.issue(), max_age=SESSION_TTL, httponly=True, samesite="strict", secure=secure, path="/")
        return resp

    def logout(request: Request) -> Response:
        if not _same_origin(request):
            return _err(403, "origin not allowed")
        resp = _ok({"authenticated": False})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    def notebooks(request: Request) -> Response:
        out = [{**asdict(n), "status": "active"} for n in store.registry.list_notebooks()]
        for p in lifecycle.pending():
            if p.kind != "notebook":
                continue
            row, _ = store.registry.summary(p.slug)
            out.append(
                {**asdict(row), "status": "proposed", "author": p.author, "rationale": p.rationale, "proposed_at": p.at}
            )
        return _ok(out)

    def _items(slug: str, status: list[str]) -> list[dict[str, Any]]:
        items, cursor = [], None
        while True:
            page = store.index.list(notebook=slug, status=status, limit=200, cursor=cursor)
            items += [asdict(i) for i in page.items]
            cursor = page.next_cursor
            if not cursor:
                return items

    def notes(request: Request) -> Response:
        slug = request.path_params["slug"]
        store.resolve(slug)  # NotFound for unknown / archived notebooks
        status = [s for s in request.query_params.get("status", "").split(",") if s in _STATUSES] or list(_STATUSES)
        items = _items(slug, status)
        times = hist.last_revised(store, slug, [i["id"] for i in items])
        for i in items:
            i["last_revised"] = times[i["id"]]
            try:
                i["tags"] = _tags(store.read_concept(slug, i["id"]).frontmatter)
            except (StoreError, ValueError, OSError):
                i["tags"] = []
        # newest first; notes without a Revision (not yet committed) go to the top; sort is stable
        items.sort(
            key=lambda i: datetime.fromisoformat(i["last_revised"]) if i["last_revised"] else datetime.max.replace(tzinfo=UTC),
            reverse=True,
        )
        return _ok(items)

    def types(request: Request) -> Response:
        """The notebook's description and its types (description, fields, count) for the Review UI tree."""
        slug = request.path_params["slug"]
        store.resolve(slug)
        d = store.registry.describe(slug)
        return _ok(
            {
                "slug": d.slug, "name": d.name, "description": d.description, "scope": d.scope,
                "status": d.status, "note_count": d.note_count, "types": [asdict(t) for t in d.types],
                "top_tags": d.top_tags,
            }
        )  # fmt: skip

    def relations(request: Request) -> Response:
        """Links to (from the note) and Cited by (found by scanning the notebook); no index change."""
        slug, cid = request.path_params["slug"], _cid(request)
        concept = store.read_concept(slug, cid)
        known = {i["id"]: i for i in _items(slug, list(_STATUSES))}

        def ref(target: str) -> dict[str, Any]:
            i = known.get(target)
            return {
                "id": target, "title": i["title"] if i else None, "type": i["type"] if i else None,
                "status": i["status"] if i else None, "broken": i is None,
            }  # fmt: skip

        links_to = [ref(t) for t in extract_links(concept.body, concept.frontmatter) if t != cid]
        cited_by = []
        for other in sorted(known):
            if other == cid:
                continue
            try:
                c = store.read_concept(slug, other)
            except (StoreError, ValueError, OSError):
                continue
            if cid in extract_links(c.body, c.frontmatter):
                cited_by.append(ref(other))
        return _ok({"links_to": links_to, "cited_by": cited_by})

    def config_files(request: Request) -> Response:
        """Raw text of every regular file under the notebook's `.okf/` (read-only)."""
        bundle = store.resolve(request.path_params["slug"])[0]
        root = bundle / ".okf"
        real_root = root.resolve()
        files = []
        for f in sorted(root.rglob("*")):
            if len(files) >= _MAX_CONFIG_FILES:
                break
            # symlinks (to files or directories) must not lead out of `.okf/`
            if f.is_symlink() or not f.is_file() or real_root not in f.resolve().parents:
                continue
            try:
                data = f.read_bytes()[: _MAX_CONFIG_BYTES + 1]
                text = data[:_MAX_CONFIG_BYTES].decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            files.append({"path": str(f.relative_to(bundle)), "content": text, "truncated": len(data) > _MAX_CONFIG_BYTES})
        return _ok({"files": files})

    def note(request: Request) -> Response:
        slug = request.path_params["slug"]
        cid = _cid(request)
        return _ok(_concept_json(slug, store.read_concept(slug, cid), store.resolve(slug)[1], store.read_raw(slug, cid)))

    async def _mark_body(request: Request) -> tuple[str | None, bool] | None:
        try:
            body = await request.json()
        except ValueError:
            return None
        if not isinstance(body, dict):
            return None
        status, verify = body.get("status"), body.get("verify", False)
        if (status is not None and status not in _STATUSES) or not isinstance(verify, bool):
            return None
        return status, verify

    async def mark(request: Request) -> Response:
        if not sessions.valid(request.cookies.get(COOKIE)):
            return _err(401, "unauthorized")
        if not _same_origin(request):
            return _err(403, "origin not allowed")
        parsed = await _mark_body(request)
        if parsed is None:
            return _err(400, "body must be {status?: draft|stable|deprecated, verify?: bool}")
        status, verify = parsed
        slug, cid = request.path_params["slug"], _cid(request)
        def work() -> Response:
            if store.resolve(slug)[1] != "active":
                return _err(409, "notebook is pending approval; decide on the proposal first")
            warnings = lifecycle.mark_concept(slug, cid, status=status, verify=verify)
            return _ok({**_concept_json(slug, store.read_concept(slug, cid)), "warnings": warnings})

        try:
            return await run_in_threadpool(work)
        except NotebookNotFound as e:
            return _err(404, str(e))
        except StoreError as e:
            return _err(_HTTP_CODES.get(getattr(e, "code", ""), 400), str(e))

    async def decide(request: Request) -> Response:
        """Approve or reject a proposed notebook (Human only; the decision is the CLI's `approve|reject`)."""
        if not sessions.valid(request.cookies.get(COOKIE)):
            return _err(401, "unauthorized")
        if not _same_origin(request):
            return _err(403, "origin not allowed")
        slug = request.path_params["slug"]
        approve = request.url.path.endswith("/approve")
        reason = ""
        if not approve:
            try:
                body = await request.json()
            except ValueError:
                body = None
            reason = body.get("reason") if isinstance(body, dict) else None
            if not isinstance(reason, str) or not reason.strip():
                return _err(400, "a reason is required")
        try:
            result = await run_in_threadpool(
                lambda: lifecycle.approve(slug) if approve else lifecycle.reject(slug, reason)
            )
        except NotebookNotFound as e:
            return _err(404, str(e))
        except StoreError as e:
            return _err(_HTTP_CODES.get(getattr(e, "code", ""), 400), str(e))
        return _ok({"status": result.status, "slug": result.slug, "warnings": result.warnings})

    def history(request: Request) -> Response:
        slug = request.path_params["slug"]
        h = hist.history(store, slug, _cid(request))
        return _ok({"available": h.available, "revisions": [asdict(r) for r in h.revisions]})

    def diff(request: Request) -> Response:
        slug = request.path_params["slug"]
        return _ok({"diff": hist.diff(store, slug, _cid(request), request.path_params["sha"])})

    # -- comments (Human side; the agents' side is the MCP tools) -----------------------
    def guarded_json(fn: Callable[[Request, dict[str, Any]], Response]):
        """State-changing comment routes: Human session, same origin, a JSON object body."""

        async def handler(request: Request) -> Response:
            if not sessions.valid(request.cookies.get(COOKIE)):
                return _err(401, "unauthorized")
            if not _same_origin(request):
                return _err(403, "origin not allowed")
            try:
                body = await request.json()
            except ValueError:
                body = None
            if not isinstance(body, dict):
                return _err(400, "body must be a JSON object")
            try:
                return await run_in_threadpool(fn, request, body)
            except NotebookNotFound as e:
                return _err(404, str(e))
            except StoreError as e:
                return _err(_HTTP_CODES.get(getattr(e, "code", ""), 400), str(e))

        return handler

    def _threads(slug: str, cid: str) -> dict[str, Any]:
        return {
            "threads": store.comments.list(notebook=slug, concept=cid),
            "mentionable": sorted(mentionable_actors(config)),
        }

    def threads(request: Request) -> Response:
        slug, cid = request.path_params["slug"], _cid(request)
        store.read_concept(slug, cid)  # NotFound before touching the comments
        return _ok(_threads(slug, cid))

    def thread_create(request: Request, body: dict[str, Any]) -> Response:
        slug, cid = request.path_params["slug"], _cid(request)
        store.read_concept(slug, cid)
        fields = {k: body.get(k, "") for k in ("quote", "prefix", "suffix", "body")}
        if not all(isinstance(v, str) for v in fields.values()):
            return _err(400, "quote, prefix, suffix and body must be strings")
        store.comments.create_thread(
            slug, cid, author=HUMAN, mentionable=mentionable_actors(config), **fields
        )
        return _ok(_threads(slug, cid), 201)

    def _thread_route(request: Request) -> tuple[int, dict[str, Any]]:
        tid = int(request.path_params["tid"])
        return tid, store.comments.get(tid)

    def comment_add(request: Request, body: dict[str, Any]) -> Response:
        tid, thread = _thread_route(request)
        parent = body.get("parent_id")
        if parent is not None and not isinstance(parent, int):
            return _err(400, "parent_id must be a number")
        text = body.get("body", "")
        if not isinstance(text, str):
            return _err(400, "body must be a string")
        store.comments.reply(
            tid, body=text, author=HUMAN, parent_id=parent, mentionable=mentionable_actors(config)
        )
        return _ok(_threads(thread["notebook"], thread["concept"]), 201)

    def thread_state(request: Request, body: dict[str, Any]) -> Response:
        tid, thread = _thread_route(request)
        state = body.get("state")
        if not isinstance(state, str):
            return _err(400, "state must be open or resolved")
        store.comments.set_state(tid, state)
        return _ok(_threads(thread["notebook"], thread["concept"]))

    def thread_delete(request: Request, body: dict[str, Any]) -> Response:
        tid, thread = _thread_route(request)
        store.comments.delete_thread(tid)
        return _ok(_threads(thread["notebook"], thread["concept"]))

    def not_found(request: Request) -> Response:
        return _err(404, "not found")

    base = "/api/notebooks/{slug}/notes/{type}/{name}"
    api = Starlette(
        routes=[
            Route("/api/session", session, methods=["GET"]),
            Route("/api/login", login, methods=["POST"]),
            Route("/api/logout", logout, methods=["POST"]),
            Route("/api/notebooks", guarded(notebooks), methods=["GET"]),
            Route("/api/notebooks/{slug}/notes", guarded(notes), methods=["GET"]),
            Route("/api/notebooks/{slug}/config", guarded(config_files), methods=["GET"]),
            Route("/api/notebooks/{slug}/types", guarded(types), methods=["GET"]),
            Route("/api/notebooks/{slug}/approve", decide, methods=["POST"]),
            Route("/api/notebooks/{slug}/reject", decide, methods=["POST"]),
            Route(base, guarded(note), methods=["GET"]),
            Route(base + "/mark", mark, methods=["POST"]),
            Route(base + "/relations", guarded(relations), methods=["GET"]),
            Route(base + "/history", guarded(history), methods=["GET"]),
            Route(base + "/diff/{sha}", guarded(diff), methods=["GET"]),
            Route(base + "/threads", guarded(threads), methods=["GET"]),
            Route(base + "/threads", guarded_json(thread_create), methods=["POST"]),
            Route("/api/threads/{tid:int}/comments", guarded_json(comment_add), methods=["POST"]),
            Route("/api/threads/{tid:int}/state", guarded_json(thread_state), methods=["POST"]),
            Route("/api/threads/{tid:int}/delete", guarded_json(thread_delete), methods=["POST"]),
            Route("/api/{rest:path}", not_found),
        ]
    )

    def static(path: str) -> Response:
        root = dist.resolve()
        if not (root / "index.html").is_file():
            return Response("Review UI is not built (see docs/review-ui.md)", status_code=404, media_type="text/plain")
        target = (root / path.lstrip("/")).resolve()
        if path not in ("", "/") and target.is_file() and root in target.parents:
            cache = "public, max-age=31536000, immutable" if "/assets/" in "/" + path else "no-cache"
            return FileResponse(target, headers={"Cache-Control": cache})
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        if not host_allowed(headers.get("host", ""), config.server.allowed_hosts):
            resp: Response = _err(421, "host not allowed")
        elif scope["path"].startswith("/api/"):
            await _with_headers(api, scope, receive, send)
            return
        elif scope["method"] in ("GET", "HEAD"):
            resp = static(scope["path"])
        else:
            resp = _err(405, "method not allowed")
        await _send_with_headers(resp, scope, receive, send)

    return app


async def _with_headers(app: ASGIApp, scope: Scope, receive: Receive, send: Send) -> None:
    async def wrapped(message: Any) -> None:
        if message["type"] == "http.response.start":
            h = list(message.get("headers", []))
            h += [(k.lower().encode(), v.encode()) for k, v in _SECURITY_HEADERS.items()]
            message = {**message, "headers": h}
        await send(message)

    await app(scope, receive, wrapped)


async def _send_with_headers(resp: Response, scope: Scope, receive: Receive, send: Send) -> None:
    for k, v in _SECURITY_HEADERS.items():
        resp.headers[k] = v
    await resp(scope, receive, send)
