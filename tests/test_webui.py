"""Review UI API over an in-process ASGI app (Human session, read, mark, history, diff)."""


import time

import pytest
from lifecycle_helpers import actor, args
from starlette.testclient import TestClient

from okf_notebooks import webui
from okf_notebooks.app import create_app
from okf_notebooks.config import Config
from okf_notebooks.lifecycle import Lifecycle, human_actor
from okf_notebooks.store import Store

PW = "s3cret-human"
HOST = "testserver"
ORIGIN = {"Origin": f"http://{HOST}"}
BODY = "A body that is certainly long enough."


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    cfg = Config(root=root, server={"allowed_hosts": [HOST]})
    store = Store.from_config(cfg)
    lc = Lifecycle.from_config(cfg, store)
    lc.create_notebook(human_actor(), **args("kube"))
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>")
    (dist / "assets" / "a.js").write_text("x")
    ui = webui.build(cfg, store, lc, PW, dist)
    client = TestClient(create_app(cfg, None, ui), base_url=f"http://{HOST}")
    return cfg, store, lc, client


def login(client):
    r = client.post("/api/login", json={"password": PW}, headers=ORIGIN)
    assert r.status_code == 200
    return r


def write_note(store, title="Use Argo", body=BODY):
    return store.write_concept(
        "kube", type="Decision", title=title, frontmatter={"description": "d"}, body=body, actor="claude-code"
    ).concept


def test_api_requires_session(env):
    *_, client = env
    for path in ("/api/notebooks", "/api/notebooks/kube/notes"):
        assert client.get(path).status_code == 401
    assert client.get("/api/session").json()["authenticated"] is False


def test_login_wrong_password_and_bad_origin(env):
    *_, client = env
    assert client.post("/api/login", json={"password": "no"}, headers=ORIGIN).status_code == 401
    assert client.post("/api/login", json={"password": PW}).status_code == 403
    assert client.post("/api/login", json={"password": PW}, headers={"Origin": "http://evil.example"}).status_code == 403


def test_login_rate_limited(env):
    *_, client = env
    codes = [client.post("/api/login", json={"password": "no"}, headers=ORIGIN).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[10] == 429


def test_session_cookie_flags_and_bearer_not_accepted(env):
    *_, client = env
    c = login(client).headers["set-cookie"].lower()
    assert "httponly" in c and "samesite=strict" in c
    other = TestClient(client.app, base_url=f"http://{HOST}")
    assert other.get("/api/notebooks", headers={"Authorization": "Bearer okf_x"}).status_code == 401


def test_forged_and_expired_cookie_rejected():
    s = webui.Sessions(PW)
    assert s.valid(s.issue())
    assert not s.valid(s.issue(now=1))
    assert not s.valid("9999999999.forged")
    assert not webui.Sessions("other").valid(s.issue())


def test_read_notebooks_notes_and_note(env):
    _cfg, store, _lc, client = env
    c = write_note(store)
    login(client)
    assert client.get("/api/notebooks").json()[0]["slug"] == "kube"
    items = client.get("/api/notebooks/kube/notes").json()
    assert [i["id"] for i in items] == [c.id] and items[0]["status"] == "draft"
    n = client.get(f"/api/notebooks/kube/notes{c.id}").json()
    assert n["body"].strip() == BODY and n["frontmatter"]["title"] == "Use Argo"
    assert client.get("/api/notebooks/kube/notes/decisions/nope").status_code == 404
    assert client.get("/api/notebooks/nope/notes").status_code == 404


def test_notes_are_ordered_by_last_revised_newest_first(env):
    _cfg, store, lc, client = env
    a = write_note(store, "Alpha")
    time.sleep(1.1)
    b = write_note(store, "Beta")
    login(client)
    items = client.get("/api/notebooks/kube/notes").json()
    assert [i["id"] for i in items] == [b.id, a.id]
    assert all(i["last_revised"] for i in items)
    time.sleep(1.1)
    lc.mark_concept("kube", a.id, status="deprecated")  # a status change is a Revision too
    items = client.get("/api/notebooks/kube/notes?status=draft,deprecated").json()
    assert [i["id"] for i in items] == [a.id, b.id]


def test_status_filter_includes_deprecated_when_asked(env):
    _cfg, store, lc, client = env
    c = write_note(store)
    lc.mark_concept("kube", c.id, status="deprecated")
    login(client)
    assert client.get("/api/notebooks/kube/notes").json() != []
    assert client.get("/api/notebooks/kube/notes?status=draft").json() == []


def test_mark_status_and_verify(env):
    _cfg, store, _lc, client = env
    c = write_note(store)
    login(client)
    url = f"/api/notebooks/kube/notes{c.id}/mark"
    assert client.post(url, json={"status": "stable"}).status_code == 403  # no Origin
    r = client.post(url, json={"status": "stable", "verify": True}, headers=ORIGIN)
    assert r.status_code == 200
    fm = r.json()["frontmatter"]
    assert fm["status"] == "stable" and fm["verified"]
    assert client.post(url, json={"status": "bogus"}, headers=ORIGIN).status_code == 400
    assert client.post(url, json={}, headers=ORIGIN).status_code == 400


def test_history_and_diff(env):
    _cfg, store, _lc, client = env
    c = write_note(store)
    store.update_concept("kube", c.id, base_etag=c.etag, actor="claude-code", body=BODY + " Edited line.")
    login(client)
    h = client.get(f"/api/notebooks/kube/notes{c.id}/history").json()
    assert h["available"] and len(h["revisions"]) == 2
    assert h["revisions"][0]["actor"] == "claude-code"
    d = client.get(f"/api/notebooks/kube/notes{c.id}/diff/{h['revisions'][0]['sha']}").json()["diff"]
    assert "+" in d and "Edited line." in d
    first = client.get(f"/api/notebooks/kube/notes{c.id}/diff/{h['revisions'][1]['sha']}").json()["diff"]
    assert "new file" in first
    assert client.get(f"/api/notebooks/kube/notes{c.id}/diff/zzzz").status_code == 400
    assert client.get(f"/api/notebooks/kube/notes{c.id}/diff/{'a' * 40}").status_code == 404


def test_diff_of_foreign_commit_refused(env):
    _cfg, store, _lc, client = env
    a = write_note(store)
    b = write_note(store, title="Other note")
    login(client)
    other = client.get(f"/api/notebooks/kube/notes{b.id}/history").json()["revisions"][0]["sha"]
    assert client.get(f"/api/notebooks/kube/notes{a.id}/diff/{other}").status_code == 404


def test_history_unavailable_without_git(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    cfg = Config(root=root, git={"enabled": False}, server={"allowed_hosts": [HOST]})
    store = Store.from_config(cfg)
    lc = Lifecycle.from_config(cfg, store)
    lc.create_notebook(human_actor(), **args("kube"))
    c = store.write_concept("kube", type="Decision", title="X1", frontmatter={"description": "d"}, body=BODY, actor="claude-code").concept
    client = TestClient(create_app(cfg, None, webui.build(cfg, store, lc, PW, tmp_path)), base_url=f"http://{HOST}")
    login(client)
    h = client.get(f"/api/notebooks/kube/notes{c.id}/history").json()
    assert h == {"available": False, "revisions": []}
    assert client.get("/api/session").json()["git"] is False


def test_static_spa_fallback_and_traversal(env):
    *_, client = env
    assert "spa" in client.get("/").text
    assert "spa" in client.get("/notebooks/kube").text
    assert client.get("/assets/a.js").text == "x"
    assert "spa" in client.get("/..%2f..%2fetc/passwd").text
    r = client.get("/")
    assert r.headers["x-frame-options"] == "DENY" and "default-src 'self'" in r.headers["content-security-policy"]


def test_host_not_allowed(env):
    *_, client = env
    assert client.get("/api/session", headers={"Host": "evil.example"}).status_code == 421


def test_mcp_path_still_needs_token_when_ui_enabled(env):
    *_, client = env
    login(client)
    assert client.post("/mcp", json={}).status_code == 401
    assert client.get("/healthz").status_code == 200


def test_proposed_notebook_is_listed_readable_and_not_markable(env):
    _cfg, _store, lc, client = env
    lc.create_notebook(
        actor(), confirm_distinct=True, **args("infra", name="Infra", description="Bare-metal hosts, networks and storage runbooks for the datacenter.", scope="Write: host facts. Do not write: app notes.", rationale="Nothing covers infrastructure yet.")
    )
    d = lc.root / "_proposed/infra/decisions"
    d.mkdir(exist_ok=True)
    (d / "x.md").write_text(
        "---\ntype: Decision\ntitle: X\ndescription: d\n---\nbody body body body body\n"
    )
    login(client)
    rows = {r["slug"]: r for r in client.get("/api/notebooks").json()}
    assert rows["kube"]["status"] == "active"
    p = rows["infra"]
    assert p["status"] == "proposed" and p["author"] == "claude-code" and "infrastructure" in p["rationale"]
    notes = client.get("/api/notebooks/infra/notes").json()
    assert [n["id"] for n in notes] == ["/decisions/x"]
    note = client.get("/api/notebooks/infra/notes/decisions/x").json()
    assert note["notebook_status"] == "proposed"
    r = client.post("/api/notebooks/infra/notes/decisions/x/mark", json={"status": "stable"}, headers=ORIGIN)
    assert r.status_code == 409


def _propose(lc, slug="infra"):
    lc.create_notebook(
        actor(), confirm_distinct=True,
        **args(slug, name="Infra", description="Bare-metal hosts, networks and storage runbooks for the datacenter.", scope="Write: host facts. Do not write: app notes.", rationale="Nothing covers infrastructure yet."),
    )  # fmt: skip


def test_approve_moves_proposal_to_active(env):
    _cfg, _store, lc, client = env
    _propose(lc)
    url = "/api/notebooks/infra/approve"
    assert client.post(url, headers=ORIGIN).status_code == 401
    login(client)
    assert client.post(url).status_code == 403  # no Origin
    r = client.post(url, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["status"] == "created"
    rows = {x["slug"]: x["status"] for x in client.get("/api/notebooks").json()}
    assert rows["infra"] == "active"
    assert client.post(url, headers=ORIGIN).status_code == 404  # no longer pending


def test_reject_requires_reason_and_archives(env):
    _cfg, _store, lc, client = env
    _propose(lc)
    login(client)
    url = "/api/notebooks/infra/reject"
    assert client.post(url, json={"reason": "  "}, headers=ORIGIN).status_code == 400
    assert client.post(url, json={}, headers=ORIGIN).status_code == 400
    r = client.post(url, json={"reason": "duplicates kube"}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert "infra" not in {x["slug"] for x in client.get("/api/notebooks").json()}
    assert (lc.root / "_archive").is_dir()


def test_cannot_approve_an_active_notebook(env):
    *_, client = env
    login(client)
    assert client.post("/api/notebooks/kube/approve", headers=ORIGIN).status_code == 404
    assert client.post("/api/notebooks/kube/reject", json={"reason": "x"}, headers=ORIGIN).status_code == 404


def test_notebook_config_lists_okf_files(env):
    *_, client = env
    assert client.get("/api/notebooks/kube/config").status_code == 401
    login(client)
    files = {f["path"]: f["content"] for f in client.get("/api/notebooks/kube/config").json()["files"]}
    assert ".okf/notebook.yaml" in files and "name: " in files[".okf/notebook.yaml"]
    assert any(p.startswith(".okf/templates/") for p in files)
    assert all(p.startswith(".okf/") for p in files)
    assert client.get("/api/notebooks/nope/config").status_code == 404


def test_notebook_config_skips_symlinks(env):
    _cfg, _store, lc, client = env
    okf = lc.root / "notebooks/kube/.okf"
    (okf / "leak.yaml").symlink_to("/etc/hosts")
    login(client)
    paths = [f["path"] for f in client.get("/api/notebooks/kube/config").json()["files"]]
    assert ".okf/leak.yaml" not in paths


def test_types_endpoint_describes_notebook_and_types(env):
    _cfg, store, _lc, client = env
    write_note(store)
    login(client)
    d = client.get("/api/notebooks/kube/types").json()
    assert d["slug"] == "kube" and d["note_count"] == 1
    assert any(t["name"] == "Decision" and t["count"] == 1 and "description" in t for t in d["types"])
    assert client.get("/api/notebooks/nope/types").status_code == 404


def test_note_carries_raw_file_and_list_carries_tags(env):
    _cfg, store, _lc, client = env
    c = store.write_concept(
        "kube", type="Decision", title="Tagged", frontmatter={"description": "d", "tags": ["k8s", "ops"]}, body=BODY, actor="claude-code"
    ).concept
    login(client)
    n = client.get(f"/api/notebooks/kube/notes{c.id}").json()
    assert n["raw"].startswith("---\n") and "title: Tagged" in n["raw"] and BODY in n["raw"]
    assert client.get("/api/notebooks/kube/notes").json()[0]["tags"] == ["k8s", "ops"]


def test_relations_links_to_and_cited_by(env):
    _cfg, store, _lc, client = env
    a = write_note(store, "Alpha")
    b = write_note(store, "Beta", body=f"{BODY} See {a.id}.md")
    login(client)
    rb = client.get(f"/api/notebooks/kube/notes{b.id}/relations").json()
    assert [(r["id"], r["broken"], r["title"]) for r in rb["links_to"]] == [(a.id, False, "Alpha")]
    assert rb["cited_by"] == []
    ra = client.get(f"/api/notebooks/kube/notes{a.id}/relations").json()
    assert [r["id"] for r in ra["cited_by"]] == [b.id] and ra["links_to"] == []
    assert client.get("/api/notebooks/kube/notes/decisions/nope/relations").status_code == 404


def test_relations_marks_a_deleted_target_as_broken(env):
    cfg, store, _lc, client = env
    a = write_note(store, "Alpha")
    b = write_note(store, "Beta", body=f"{BODY} See {a.id}.md")
    next(cfg.root.rglob("alpha.md")).unlink()
    login(client)
    rb = client.get(f"/api/notebooks/kube/notes{b.id}/relations").json()
    assert [(r["id"], r["broken"], r["title"]) for r in rb["links_to"]] == [(a.id, True, None)]
