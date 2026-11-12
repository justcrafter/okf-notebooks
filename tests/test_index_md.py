from registry_helpers import KUBE, make_ws

from okf_notebooks.store import Store


def write(store, ws, type_, title, desc):
    return store.write_concept(
        ws,
        type=type_,
        title=title,
        frontmatter={"title": title, "description": desc},
        body="b\n",
        actor="claude-code",
    )


def test_write_regenerates_index_md_from_files(root):
    make_ws(root, "kube", KUBE)
    (root / "notebooks/kube/index.md").write_text("hand edit\n")
    store = Store(root, git=False)

    write(store, "kube", "Decision", "Use ArgoCD", "Why ArgoCD")
    write(store, "kube", "Term", "Pod", "Smallest unit")
    write(store, "kube", "Decision", "Adopt Helm", "Charts")

    text = (root / "notebooks/kube/index.md").read_text()
    assert "hand edit" not in text
    assert text.startswith('---\nokf_version: "0.2"\n---\n')
    assert "# Платформа Kubernetes" in text
    assert "Решения и плейбуки по кластерам" in text
    assert text.index("## Decision") < text.index("## Term")  # declared order
    assert "- [Adopt Helm](/decisions/adopt-helm.md) — Charts" in text
    assert "- [Use ArgoCD](/decisions/use-argocd.md) — Why ArgoCD" in text
    assert text.index("Adopt Helm") < text.index("Use ArgoCD")  # sorted by title
    assert "- [Pod](/terms/pod.md) — Smallest unit" in text


def test_hand_edit_overwritten_on_next_write_and_in_git(root):
    make_ws(root, "kube", KUBE)
    store = Store(root)
    write(store, "kube", "Term", "Pod", "d")
    (root / "notebooks/kube/index.md").write_text("tampered\n")
    write(store, "kube", "Term", "Node", "d2")
    assert "tampered" not in (root / "notebooks/kube/index.md").read_text()
    import subprocess

    tracked = subprocess.run(
        ["git", "-C", str(root), "show", "HEAD", "--name-only", "--format="],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    assert "notebooks/kube/index.md" in tracked


def test_untitled_file_listed_with_slug_fallback(root):
    # a hand-made note without title is still listed, using the file slug
    terms = root / "notebooks/notes/terms"
    terms.mkdir(parents=True)
    (terms / "etag.md").write_text("---\ndescription: d\n---\nbody\n")
    store = Store(root, git=False)
    store.write_concept(
        "notes",
        type="Term",
        title="Other",
        frontmatter={"description": "Another term"},
        body="A sufficiently long body for a term.\n",
        actor="human",
    )
    text = (root / "notebooks/notes/index.md").read_text()
    assert "- [etag](/terms/etag.md)" in text


def test_store_uses_registry_declared_dir(root):
    make_ws(root, "x", "name: X\ntypes:\n  - {name: Decision, dir: adrs}\n")
    res = write(Store(root, git=False), "x", "Decision", "Use Helm", "d")
    assert res.concept.id == "/adrs/use-helm"
    assert (root / "notebooks/x/adrs/use-helm.md").is_file()
