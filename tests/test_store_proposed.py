"""Story 15, seam 1: an author writes into their own proposed Notebook before approval."""

import subprocess

import pytest
from lifecycle_helpers import actor, args, make_lc

from okf_notebooks.store import Conflict, Invalid, NotFound

BODY = "Roll back with ArgoCD when the sync health turns red.\n"


@pytest.fixture
def prop(tmp_path):
    """(lifecycle, store, root) with `kube` proposed by claude-code."""
    root = tmp_path / "root"
    lc = make_lc(root)
    lc.create_notebook(actor("claude-code"), **args("kube"))
    return lc, lc.store, root


def put(store, who="claude-code", title="Rollback", ws="kube", **over):
    kw = {"type": "Playbook", "title": title, "frontmatter": {"description": "How to roll back"},
          "body": BODY, "actor": who}
    kw.update(over)
    return store.write_concept(ws, **kw)


def test_author_writes_reads_updates_appends_in_proposed(prop):
    _, store, root = prop
    w = put(store)
    assert w.concept.id == "/playbooks/rollback"
    assert (root / "_proposed/kube/playbooks/rollback.md").is_file()
    assert not (root / "notebooks/kube").exists()
    fm = w.concept.frontmatter
    assert fm["status"] == "draft" and fm["generated"]["by"].startswith("claude-code")
    got = store.read_concept("kube", w.concept.id, actor="claude-code")
    assert got.etag == w.concept.etag and got.body == BODY
    up = store.update_concept("kube", w.concept.id, base_etag=got.etag, actor="claude-code",
                              body="A brand new body that is long enough.\n")
    ap = store.append_concept("kube", w.concept.id, text="- more\n", actor="claude-code")
    assert ap.concept.body.endswith("- more\n") and ap.concept.etag != up.concept.etag
    with pytest.raises(Conflict):
        store.update_concept("kube", w.concept.id, base_etag=w.concept.etag, actor="claude-code",
                             body="Stale write that is long enough.\n")
    log = (root / "_proposed/kube/log.md").read_text()
    assert "claude-code write /playbooks/rollback" in log and "append" in log
    assert "Rollback" in (root / "_proposed/kube/index.md").read_text()


def test_validation_applies_in_proposed(prop):
    _, store, _ = prop
    with pytest.raises(Invalid):
        put(store, type="Nonsense")
    with pytest.raises(Invalid):
        put(store, frontmatter={})


def test_other_actor_gets_not_found_everywhere(prop):
    _, store, _ = prop
    w = put(store)
    cid = w.concept.id
    for call in (
        lambda: put(store, "opencode", "Other"),
        lambda: store.read_concept("kube", cid, actor="opencode"),
        lambda: store.update_concept("kube", cid, base_etag=w.concept.etag, actor="opencode", body=BODY),
        lambda: store.append_concept("kube", cid, text="x\n", actor="opencode"),
        lambda: store.neighbours("kube", cid, actor="opencode"),
        lambda: store.resolve("kube", "opencode"),
    ):
        with pytest.raises(NotFound):
            call()
    assert store.visible_status("claude-code", "kube") == "proposed"
    with pytest.raises(NotFound):
        store.visible_status("opencode", "kube")


def test_human_can_access_proposed(prop):
    _, store, _ = prop
    w = put(store)
    assert store.read_concept("kube", w.concept.id, actor="human").etag == w.concept.etag
    assert put(store, "human", "Human note").concept.frontmatter["generated"]["by"].startswith("human")


def test_proposed_concepts_stay_out_of_default_search_and_list(prop):
    _, store, _ = prop
    put(store, title="Rollback")
    idx = store.index
    assert idx.search("ArgoCD").hits == []
    assert idx.list().items == []
    assert [h.id for h in idx.search("ArgoCD", notebook="kube").hits] == ["/playbooks/rollback"]
    assert [i.id for i in idx.list(notebook="kube").items] == ["/playbooks/rollback"]


def test_approve_keeps_notes_and_makes_them_searchable_by_all(prop):
    lc, store, root = prop
    put(store)
    assert store.index.search("ArgoCD").hits == []
    lc.approve("kube")
    assert (root / "notebooks/kube/playbooks/rollback.md").is_file()
    assert not (root / "_proposed/kube").exists()
    assert store.read_concept("kube", "/playbooks/rollback", actor="opencode").body == BODY
    hits = store.index.search("ArgoCD").hits
    assert [(h.notebook, h.id) for h in hits] == [("kube", "/playbooks/rollback")]
    assert [i.id for i in store.index.list().items] == ["/playbooks/rollback"]
    # an active notebook is writable by everyone with write rights again
    assert put(store, "opencode", "Second").concept.id == "/playbooks/second"
    assert {h.id for h in store.index.search("ArgoCD").hits} == {
        "/playbooks/rollback", "/playbooks/second"}


def test_approve_regenerates_index_md(prop):
    lc, _, root = prop
    f = root / "_proposed/kube/playbooks/by-hand.md"
    f.write_text("---\ntype: Playbook\ntitle: By hand\ndescription: dropped in\n---\n" + BODY)
    lc.approve("kube")
    assert "By hand" in (root / "notebooks/kube/index.md").read_text()


def test_reject_stops_writes_and_drops_notes_from_the_index(prop):
    lc, store, root = prop
    w = put(store)
    store.index.search("ArgoCD", notebook="kube")
    lc.reject("kube", "duplicate of another notebook")
    with pytest.raises(NotFound):
        put(store, title="Late")
    with pytest.raises(NotFound):
        store.append_concept("kube", w.concept.id, text="x\n", actor="claude-code")
    assert store.index.search("ArgoCD").hits == []
    assert store.index.search("ArgoCD", notebook="kube").hits == []
    assert not (root / "_proposed/kube").exists()


def test_proposed_write_is_committed_with_actor_as_author(tmp_path):
    root = tmp_path / "root"
    lc = make_lc(root)
    lc.store.git = True
    lc.create_notebook(actor("claude-code"), **args("kube"))
    put(lc.store)
    out = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%an|%s", "--name-only"],
                         capture_output=True, text=True, check=True).stdout
    assert out.startswith("claude-code|notebook(kube): write /playbooks/rollback")
    assert "_proposed/kube/playbooks/rollback.md" in out and "_proposed/kube/log.md" in out


def test_symlinked_proposed_bundle_is_refused(tmp_path, prop):
    _, store, root = prop
    real = tmp_path / "elsewhere"
    (root / "_proposed/kube").rename(real)
    (root / "_proposed/kube").symlink_to(real)
    with pytest.raises((NotFound, Invalid)):
        put(store)
    assert not (real / "playbooks/rollback.md").exists()
