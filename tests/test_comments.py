"""Comments: the store (visibility, state, mentions), the Review UI API and the config right."""

import pytest
from lifecycle_helpers import args
from starlette.testclient import TestClient

from okf_notebooks import webui
from okf_notebooks.app import create_app
from okf_notebooks.auth import mentionable_actors
from okf_notebooks.comments import Comments, parse_mentions
from okf_notebooks.config import Config
from okf_notebooks.lifecycle import Lifecycle, human_actor
from okf_notebooks.store import Invalid, NotFound, Store

PW = "s3cret-human"
HOST = "testserver"
ORIGIN = {"Origin": f"http://{HOST}"}
BODY = "A body that is certainly long enough."
ALL = {"claude-code", "opencode", "external-harness"}


@pytest.fixture
def db(tmp_path):
    return Comments(tmp_path / ".comments" / "threads.sqlite")


def thread(db, body="Please check this", concept="/decisions/a", **kw):
    return db.create_thread(
        "kube", concept, quote="rolls back", body=body, author="human", mentionable=ALL, **kw
    )


def test_parse_mentions_ignores_emails_and_dedupes():
    assert parse_mentions("@claude-code and @opencode, @claude-code; a@b.com") == [
        "claude-code",
        "opencode",
    ]


def test_database_dir_ignores_itself_and_never_loses_data(db):
    thread(db)
    assert (db.path.parent / ".gitignore").read_text() == "*\n"
    again = Comments(db.path)
    assert len(again.list()) == 1


def test_visibility_follows_mentions_of_the_whole_thread(db):
    t = thread(db)  # no mention: everybody
    assert db.addressed_to(db.get(t["id"]), "opencode")
    db.reply(t["id"], body="@claude-code look", author="human", mentionable=ALL)
    got = db.get(t["id"])
    assert got["mentions"] == ["claude-code"]
    assert db.addressed_to(got, "claude-code") and not db.addressed_to(got, "opencode")
    assert [x["id"] for x in db.list(actor="opencode")] == []
    assert [x["id"] for x in db.list(actor="claude-code")] == [t["id"]]


def test_mention_of_an_actor_without_comments_is_rejected(db):
    with pytest.raises(Invalid, match="@opencode"):
        db.create_thread(
            "kube", "/decisions/a", quote="q", body="hi @opencode", author="human",
            mentionable={"claude-code"},
        )
    assert db.list() == []


def test_human_reply_reopens_agent_reply_does_not(db):
    t = thread(db)
    db.set_state(t["id"], "resolved")
    db.reply(t["id"], body="done", author="claude-code", mentionable=ALL)
    assert db.get(t["id"])["state"] == "resolved"
    db.reply(t["id"], body="not quite", author="human", mentionable=ALL)
    assert db.get(t["id"])["state"] == "open"


def test_replies_form_a_tree_and_parent_must_belong_to_the_thread(db):
    t = thread(db)
    other = thread(db, concept="/decisions/b")
    first = t["comments"][0]["id"]
    db.reply(t["id"], body="one", author="human", parent_id=first, mentionable=ALL)
    db.reply(t["id"], body="two", author="claude-code", parent_id=first, mentionable=ALL)
    kids = [c for c in db.get(t["id"])["comments"] if c["parent_id"] == first]
    assert len(kids) == 2
    with pytest.raises(NotFound):
        db.reply(t["id"], body="x", author="human", parent_id=other["comments"][0]["id"], mentionable=ALL)


def test_state_filter_and_delete(db):
    a, b = thread(db), thread(db, concept="/decisions/b")
    db.set_state(a["id"], "resolved")
    assert [t["id"] for t in db.list(state="open")] == [b["id"]]
    assert [t["id"] for t in db.list(state="resolved")] == [a["id"]]
    db.delete_thread(a["id"])
    assert [t["id"] for t in db.list()] == [b["id"]]
    with pytest.raises(NotFound):
        db.get(a["id"])


@pytest.mark.parametrize("text", ["", "   ", "x" * 4001])
def test_bad_comment_text(db, text):
    with pytest.raises(Invalid):
        thread(db, body=text)


def test_config_comments_right():
    cfg = Config(root=".", actors={"opencode": {"allow": ["read", "write"]}})
    assert mentionable_actors(cfg) == {"claude-code", "external-harness"}
    with pytest.raises(ValueError):
        Config(root=".", actors={"opencode": {"allow": ["comment"]}})


# -- Review UI API -----------------------------------------------------------------
@pytest.fixture
def env(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    cfg = Config(root=root, server={"allowed_hosts": [HOST]})
    store = Store.from_config(cfg)
    lc = Lifecycle.from_config(cfg, store)
    lc.create_notebook(human_actor(), **args("kube"))
    store.write_concept(
        "kube", type="Decision", title="Use Argo", frontmatter={"description": "d"}, body=BODY,
        actor="claude-code",
    )
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>spa</html>")
    ui = webui.build(cfg, store, lc, PW, dist)
    client = TestClient(create_app(cfg, None, ui), base_url=f"http://{HOST}")
    assert client.post("/api/login", json={"password": PW}, headers=ORIGIN).status_code == 200
    return store, client


NOTE = "/api/notebooks/kube/notes/decisions/use-argo"


def test_api_thread_lifecycle(env):
    _, client = env
    r = client.post(
        NOTE + "/threads", headers=ORIGIN,
        json={"quote": "certainly long", "prefix": "is ", "suffix": " enough", "body": "@claude-code why?"},
    )
    assert r.status_code == 201
    t = r.json()["threads"][0]
    assert t["quote"] == "certainly long" and t["mentions"] == ["claude-code"]
    assert "claude-code" in r.json()["mentionable"]
    tid = t["id"]
    assert client.post(f"/api/threads/{tid}/state", json={"state": "resolved"}, headers=ORIGIN).status_code == 200
    r = client.post(f"/api/threads/{tid}/comments", json={"body": "still unclear"}, headers=ORIGIN)
    assert r.json()["threads"][0]["state"] == "open" and len(r.json()["threads"][0]["comments"]) == 2
    assert client.get(NOTE + "/threads").json()["threads"][0]["id"] == tid
    r = client.post(f"/api/threads/{tid}/delete", json={}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["threads"] == []


def test_api_guards(env):
    _, client = env
    body = {"quote": "q", "body": "hi"}
    assert client.post(NOTE + "/threads", json=body).status_code == 403  # no Origin
    assert client.post(NOTE + "/threads", json=body, headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.post(NOTE + "/threads", json={"quote": "", "body": "x"}, headers=ORIGIN).status_code == 400
    assert client.post(NOTE + "/threads", json={"quote": "q", "body": "@opencode-x hi"}, headers=ORIGIN).status_code == 400
    assert client.post("/api/notebooks/kube/notes/decisions/nope/threads", json=body, headers=ORIGIN).status_code == 404
    assert client.post("/api/threads/999/state", json={"state": "open"}, headers=ORIGIN).status_code == 404
    client.cookies.clear()
    assert client.get(NOTE + "/threads").status_code == 401
    assert client.post(NOTE + "/threads", json=body, headers=ORIGIN).status_code == 401


def test_commenting_does_not_touch_the_note(env):
    store, client = env
    before = store.read_concept("kube", "/decisions/use-argo")
    client.post(NOTE + "/threads", json={"quote": "long", "body": "hm"}, headers=ORIGIN)
    assert store.read_concept("kube", "/decisions/use-argo") == before
