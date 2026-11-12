"""auth + middleware over the running ASGI server.

An authenticated request that passes every gate reaches the MCP endpoint, which answers
400 to the junk bodies used here; that is the "let through" signal (no guard status).
"""

import http.client
import re
from urllib.parse import urlsplit

from conftest import cli

PASSED = 400


def issue(cfg, actor="claude-code", label="laptop"):
    r = cli("token", "create", "--actor", actor, "--label", label, "--config", str(cfg))
    assert r.returncode == 0, r.stderr
    return (
        re.search(r"id:\s*(\S+)", r.stdout).group(1),
        re.search(r"token:\s*(\S+)", r.stdout).group(1),
    )


def call(url, token=None, method="POST", path="/mcp", headers=None, body=b"{}", host=None):
    u = urlsplit(url)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=5)
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    h.update(headers or {})
    conn.putrequest(method, path, skip_host=True)
    conn.putheader("Host", host or f"{u.hostname}:{u.port}")
    for k, v in h.items():
        conn.putheader(k, v)
    conn.putheader("Content-Length", str(len(body)))
    conn.endheaders(body)
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, data


def test_valid_token_passes_the_gates(server):
    _, url, cfg = server()
    _, tok = issue(cfg)
    assert call(url, tok)[0] == PASSED


def test_no_token_is_401_before_mcp_parsing(server):
    _, url, _ = server()
    status, headers, _ = call(url, None, body=b"this is not json at all")
    assert status == 401
    assert headers.get("www-authenticate", "").startswith("Bearer")


def test_unknown_token_is_401(server):
    _, url, cfg = server()
    issue(cfg)
    assert call(url, "okf_not-a-real-token")[0] == 401


def test_non_bearer_scheme_is_401(server):
    _, url, cfg = server()
    _, tok = issue(cfg)
    assert call(url, None, headers={"Authorization": f"Basic {tok}"})[0] == 401


def test_revoked_token_is_401_without_restart(server):
    _, url, cfg = server()
    tid, tok = issue(cfg)
    assert call(url, tok)[0] == PASSED
    assert cli("token", "revoke", tid, "--config", str(cfg)).returncode == 0
    assert call(url, tok)[0] == 401


def test_revoking_one_token_keeps_others_working(server):
    _, url, cfg = server()
    tid1, _ = issue(cfg, label="a")
    _, tok2 = issue(cfg, label="b")
    cli("token", "revoke", tid1, "--config", str(cfg))
    assert call(url, tok2)[0] == PASSED


def test_healthz_needs_no_token(server):
    _, url, _ = server()
    assert call(url, None, method="GET", path="/healthz")[0] == 200


def test_token_of_human_in_store_is_refused(server):
    # A hand-edited store must not turn a token into the `human` actor.
    import json

    _, url, cfg = server()
    _, tok = issue(cfg)
    f = cfg.parent / "data" / ".auth" / "tokens.json"
    data = json.loads(f.read_text())
    data["tokens"][0]["actor"] = "human"
    f.write_text(json.dumps(data))
    assert call(url, tok)[0] == 401


def test_foreign_host_is_rejected(server):
    _, url, cfg = server()
    _, tok = issue(cfg)
    assert call(url, tok, host="evil.example.com")[0] == 421


def test_allowed_host_from_config_passes(server):
    _, url, cfg = server(extra="  allowed_hosts: ['notebooks.tailnet.ts.net']\n")
    _, tok = issue(cfg)
    assert call(url, tok, host="notebooks.tailnet.ts.net:8765")[0] == PASSED
    assert call(url, tok, host="evil.example.com")[0] == 421


def test_foreign_origin_is_rejected(server):
    _, url, cfg = server()
    _, tok = issue(cfg)
    status, _, _ = call(url, tok, headers={"Origin": "https://evil.example.com"})
    assert status == 403


def test_allowed_origin_from_config_passes(server):
    _, url, cfg = server(extra="  allowed_origins: ['https://app.example.com']\n")
    _, tok = issue(cfg)
    assert call(url, tok, headers={"Origin": "https://app.example.com"})[0] == PASSED
    assert call(url, tok, headers={"Origin": "https://evil.example.com"})[0] == 403


def test_oversized_body_is_413(server):
    _, url, cfg = server(extra="  max_body_bytes: 100\n")
    _, tok = issue(cfg)
    assert call(url, tok, body=b"x" * 101)[0] == 413
    assert call(url, tok, body=b"x" * 100)[0] == PASSED


def test_oversized_body_without_token_is_still_401(server):
    _, url, _ = server(extra="  max_body_bytes: 100\n")
    assert call(url, None, body=b"x" * 101)[0] == 401


def test_rate_limit_is_per_token(server):
    _, url, cfg = server(extra="  rate_limit_per_token: 3/min\n")
    _, a = issue(cfg, label="a")
    _, b = issue(cfg, label="b")
    assert [call(url, a)[0] for _ in range(3)] == [PASSED] * 3
    status, headers, _ = call(url, a)
    assert status == 429
    assert int(headers["retry-after"]) >= 1
    assert call(url, b)[0] == PASSED


def test_unauthenticated_requests_do_not_consume_rate_limit(server):
    _, url, cfg = server(extra="  rate_limit_per_token: 2/min\n")
    _, tok = issue(cfg)
    for _ in range(5):
        assert call(url, "okf_bad")[0] == 401
    assert call(url, tok)[0] == PASSED


def test_healthz_is_not_rate_limited_or_host_checked(server):
    _, url, _ = server(extra="  rate_limit_per_token: 1/min\n")
    for _ in range(3):
        assert call(url, None, method="GET", path="/healthz", host="anything")[0] == 200
