"""Request-scoped Actor accessor (consumed by the MCP tools in ticket 08).

In-process ASGI: a probe endpoint stands in for the MCP app and reports what
`current_actor()` resolves to inside the request.
"""

import dataclasses
import json

import httpx
import pytest
from conftest import free_port, write_config

from okf_notebooks.app import create_app, host_allowed, initialize_client_version
from okf_notebooks.auth import Actor, TokenStore, current_actor, tokens_path
from okf_notebooks.config import load_config


async def probe(scope, receive, send):
    actor = current_actor()
    payload = None
    if actor:
        payload = {
            "actor": actor.name, "label": actor.label, "version": actor.client_version,
            "by": actor.generated_by, "perms": sorted(actor.permissions),
            "wc": actor.notebook_creation, "can_wc": actor.can("notebook_creation"),
            "can_verify": actor.can("verify"),
        }
    await receive()
    await send({"type": "http.response.start", "status": 200, "headers": [
        (b"content-type", b"application/json"), (b"mcp-session-id", b"sess-1")]})
    await send({"type": "http.response.body", "body": json.dumps(payload).encode()})


def make(tmp_path, extra=""):
    cfg = load_config(write_config(tmp_path, free_port(), extra))
    store = TokenStore(tokens_path(cfg))
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(cfg, mcp_app=probe)),
        base_url="http://127.0.0.1:8000",
    )
    return store, client


def init_body(version="1.2.3"):
    return json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"clientInfo": {"name": "claude-code", "version": version}}})


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_actor_comes_from_token_not_from_arguments(tmp_path):
    store, client = make(tmp_path)
    _, tok = store.create("opencode", "nas")
    body = json.dumps({"actor": "human", "params": {"arguments": {"actor": "human"}}})
    r = await client.post("/mcp/", content=body, headers={"Authorization": f"Bearer {tok}"})
    got = r.json()
    assert got["actor"] == "opencode" and got["label"] == "nas"
    assert got["can_verify"] is False


@pytest.mark.anyio
async def test_initialize_client_version_becomes_generated_by(tmp_path):
    store, client = make(tmp_path)
    _, tok = store.create("claude-code", "laptop")
    r = await client.post("/mcp/", content=init_body("2.0.1"),
                          headers={"Authorization": f"Bearer {tok}"})
    assert r.json()["by"] == "claude-code/2.0.1"


@pytest.mark.anyio
async def test_version_is_remembered_for_the_session_of_the_same_token_only(tmp_path):
    store, client = make(tmp_path)
    _, tok = store.create("claude-code", "laptop")
    _, other = store.create("claude-code", "nas")
    await client.post("/mcp/", content=init_body("2.0.1"),
                      headers={"Authorization": f"Bearer {tok}"})
    again = await client.post("/mcp/", content="{}", headers={
        "Authorization": f"Bearer {tok}", "Mcp-Session-Id": "sess-1"})
    assert again.json()["by"] == "claude-code/2.0.1"
    stolen = await client.post("/mcp/", content="{}", headers={
        "Authorization": f"Bearer {other}", "Mcp-Session-Id": "sess-1"})
    assert stolen.json()["by"] == "claude-code/unknown"


@pytest.mark.anyio
async def test_no_initialize_means_unknown_version(tmp_path):
    store, client = make(tmp_path)
    _, tok = store.create("claude-code", "laptop")
    r = await client.post("/mcp/", content="{}", headers={"Authorization": f"Bearer {tok}"})
    assert r.json()["by"] == "claude-code/unknown"


@pytest.mark.anyio
async def test_permissions_default_and_config_override(tmp_path):
    extra = (
        "actors:\n  opencode:\n    allow: [read]\n"
        "  external-harness:\n    allow: [read, write, notebook_creation]\n"
        "    notebook_creation: direct\n"
    )
    store, client = make(tmp_path, extra)
    out = {}
    for a in ("claude-code", "opencode", "external-harness"):
        _, tok = store.create(a, "m")
        out[a] = (await client.post("/mcp/", content="{}",
                  headers={"Authorization": f"Bearer {tok}"})).json()
    assert out["claude-code"]["perms"] == ["comments", "read", "write"]
    assert out["claude-code"]["can_wc"] is True  # default policy `proposal` applies
    assert out["claude-code"]["wc"] == "proposal"
    assert out["opencode"]["can_wc"] is False  # read-only by config
    assert out["opencode"]["perms"] == ["read"]
    assert out["external-harness"]["wc"] == "direct" and out["external-harness"]["can_wc"]


@pytest.mark.anyio
async def test_external_harness_defaults_to_read_only_plus_comments(tmp_path):
    store, client = make(tmp_path)
    _, tok = store.create("external-harness", "m")
    got = (await client.post("/mcp/", content="{}",
                             headers={"Authorization": f"Bearer {tok}"})).json()
    assert got["perms"] == ["comments", "read"] and got["can_wc"] is False


@pytest.mark.anyio
async def test_policy_off_blocks_creation_for_writers(tmp_path):
    store, client = make(tmp_path, "notebook_creation:\n  default: off\n")
    _, tok = store.create("claude-code", "m")
    got = (await client.post("/mcp/", content="{}",
                             headers={"Authorization": f"Bearer {tok}"})).json()
    assert got["perms"] == ["comments", "read", "write"] and got["can_wc"] is False


@pytest.mark.anyio
async def test_no_actor_outside_authenticated_request(tmp_path):
    assert current_actor() is None


@pytest.mark.anyio
async def test_unauthenticated_request_never_reaches_app(tmp_path):
    _, client = make(tmp_path)
    assert (await client.post("/mcp/", content="{}")).status_code == 401


def test_initialize_client_version_parser():
    assert initialize_client_version(init_body("9.9")) == "9.9"
    assert initialize_client_version(init_body("1.0\nrm -rf")) == "1.0rm-rf"
    assert initialize_client_version(b"not json") is None
    assert initialize_client_version(b'{"method":"tools/list"}') is None


@pytest.mark.parametrize("host,allowed,ok", [
    ("127.0.0.1:8765", [], True), ("localhost", [], True), ("[::1]:80", [], True),
    ("evil.com", [], False), ("evil.com:8765", ["notebooks.ts.net"], False),
    ("notebooks.ts.net:8765", ["notebooks.ts.net"], True),
    ("NOTEBOOKS.ts.net", ["notebooks.ts.net"], True),
    ("notebooks.ts.net:1", ["notebooks.ts.net:8765"], False),
    ("127.0.0.1", ["notebooks.ts.net"], False),
    ("192.168.88.5:8765", ["192.168.88"], True),
    ("192.168.89.5", ["192.168.88"], False),
    ("192.168.1.9", ["192.168"], True),
    ("192.168.88.200:80", ["192.168.88.0/24"], True),
    ("192.168.89.1", ["192.168.88.0/24"], False),
    ("10.0.0.1", ["10.0.0.0/8"], True),
    ("192.168.880.1", ["192.168.88"], False),
    ("evil.com", ["192.168.88"], False),
])
def test_host_allowed(host, allowed, ok):
    assert host_allowed(host, allowed) is ok


def test_actor_is_immutable():
    a = Actor("opencode", "m", "t-1", frozenset({"read"}), "off")
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.name = "human"  # type: ignore[misc]
