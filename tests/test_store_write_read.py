import hashlib
import os

import pytest

from okf_notebooks.store import Invalid, NotFound, Store


def test_write_then_read_roundtrip(root):
    store = Store(root, git=False)
    res = store.write_concept(
        "notes",
        type="Decision",
        title="Use ArgoCD",
        frontmatter={
            "description": "Why we picked ArgoCD",
            "tags": ["cd", "k8s"],
            "owner": "andrey",
        },
        body="We use ArgoCD, as decided in the last review.\n",
        actor="claude-code",
    )
    assert res.concept.id == "/decisions/use-argocd"
    on_disk = root / "notebooks/notes/decisions/use-argocd.md"
    assert on_disk.is_file()

    got = store.read_concept("notes", "/decisions/use-argocd")
    assert got.frontmatter["description"] == "Why we picked ArgoCD"
    assert got.frontmatter["tags"] == ["cd", "k8s"]
    assert got.frontmatter["status"] == "draft"
    assert got.body == "We use ArgoCD, as decided in the last review.\n"
    assert got.etag == res.concept.etag
    assert got.etag == hashlib.sha256(on_disk.read_bytes()).hexdigest()


def test_write_leaves_no_temp_files(root):
    Store(root, git=False).write_concept(
        "notes",
        type="Term",
        title="ETag",
        frontmatter={"description": "d"},
        body="x" * 25,
        actor="human",
    )
    assert list((root / ".tmp").glob("*.md*")) == []
    assert [p.name for p in (root / "notebooks/notes/terms").iterdir()] == ["etag.md"]


def test_unknown_notebook_is_not_found(root):
    with pytest.raises(NotFound):
        Store(root, git=False).read_concept("nope", "/terms/x")


def test_read_missing_concept_is_not_found(root):
    with pytest.raises(NotFound):
        Store(root, git=False).read_concept("notes", "/terms/x")


@pytest.mark.parametrize(
    "cid",
    [
        "/terms/../../x",
        "../terms/x",
        "/terms/..",
        "terms/x",
        "/etc/passwd/x",
        "/a/b/c",
        "//x",
    ],
)
def test_read_rejects_unsafe_ids(root, cid):
    with pytest.raises(Invalid):
        Store(root, git=False).read_concept("notes", cid)


@pytest.mark.parametrize("ws", ["../notes", "a/b", "/abs", ""])
def test_rejects_unsafe_notebook_slug(root, ws):
    with pytest.raises(Invalid):
        Store(root, git=False).read_concept(ws, "/terms/x")


def test_traversal_in_title_or_type_stays_inside_bundle(root):
    res = Store(root, git=False).write_concept(
        "notes",
        type="Term",
        title="../../../evil",
        frontmatter={"description": "d"},
        body="x" * 25,
        actor="human",
    )
    path = root / "notebooks/notes" / (res.concept.id.lstrip("/") + ".md")
    assert path.resolve().is_relative_to((root / "notebooks/notes").resolve())
    with pytest.raises(Invalid):
        Store(root, git=False).write_concept(
            "notes",
            type="Term",
            title="!!!",
            frontmatter={"description": "d"},
            body="x" * 25,
            actor="human",
        )


def test_symlinked_type_dir_is_rejected(root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "notebooks/notes/terms").symlink_to(outside)
    with pytest.raises(Invalid):
        Store(root, git=False).write_concept(
            "notes",
            type="Term",
            title="x",
            frontmatter={"description": "d"},
            body="y" * 25,
            actor="human",
        )
    assert list(outside.iterdir()) == []
    with pytest.raises(Invalid):
        Store(root, git=False).read_concept("notes", "/terms/x")


def test_symlinked_concept_file_is_rejected(root, tmp_path):
    secret = tmp_path / "secret.md"
    secret.write_text("---\n---\nsecret\n")
    d = root / "notebooks/notes/terms"
    d.mkdir()
    (d / "x.md").symlink_to(secret)
    with pytest.raises(Invalid):
        Store(root, git=False).read_concept("notes", "/terms/x")


def test_store_alone_keeps_log_and_index_public_and_concepts_private(root):
    s = Store(root, git=False)
    c = s.write_concept(
        "notes", type="Term", title="T", body="x" * 30, actor="claude-code",
        frontmatter={"description": "d"},
    ).concept
    ws = root / "notebooks" / "notes"
    mode = lambda p: os.stat(p).st_mode & 0o777
    assert mode(ws / "log.md") == 0o644 and mode(ws / "index.md") == 0o644
    assert mode(ws / (c.id.lstrip("/") + ".md")) == 0o600
