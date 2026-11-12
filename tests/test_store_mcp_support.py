"""Core support for the MCP layer: client identity, field patches, link graph, config wiring."""

import subprocess

from conftest import write_config

from okf_notebooks.config import load_config
from okf_notebooks.store import Store

BODY = "A body that is long enough to pass the validator.\n"


def _write(store, title="Deploy", body=BODY, **kw):
    return store.write_concept(
        "notes", type="Playbook", title=title, frontmatter={"description": "d"},
        body=body, actor="claude-code", **kw,
    )


def test_generated_by_and_label_come_from_the_caller(root):
    store = Store(root, git=True)
    res = _write(store, generated_by="claude-code/2.0.1", label="laptop")
    assert res.concept.frontmatter["generated"]["by"] == "claude-code/2.0.1"
    log = (root / "notebooks/notes/log.md").read_text()
    assert "claude-code" in log and "laptop" in log
    msg = subprocess.run(
        ["git", "-C", str(root), "log", "-1", "--format=%s"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "laptop" in msg


def test_default_generated_by_is_unchanged_without_identity(root):
    res = _write(Store(root, git=False))
    assert res.concept.frontmatter["generated"]["by"].startswith("claude-code/")


def test_update_with_field_patch_keeps_other_fields(root):
    store = Store(root, git=False)
    c = _write(store).concept
    res = store.update_concept(
        "notes", c.id, base_etag=c.etag, actor="claude-code",
        fields={"tags": ["ops"], "description": "new"},
    )
    fm = res.concept.frontmatter
    assert fm["tags"] == ["ops"] and fm["description"] == "new"
    assert fm["title"] == "Deploy" and fm["status"] == "draft"
    assert res.concept.body == BODY


def test_neighbours_lists_outgoing_and_incoming_links(root):
    store = Store(root, git=False)
    a = _write(store, "Alpha").concept
    store.write_concept(
        "notes", type="Term", title="Beta", frontmatter={"description": "d", "links": [f"{a.id}.md"]},
        body="See also " + f"{a.id}.md" + " for details.\n", actor="claude-code",
    )
    out, inc = store.neighbours("notes", "/terms/beta")
    assert out == [f"{a.id}"]
    assert inc == []
    out, inc = store.neighbours("notes", a.id)
    assert out == [] and inc == ["/terms/beta"]


def test_from_config_honours_index_path_and_concept_limit(tmp_path):
    extra = "index:\n  path: custom/fts.sqlite\nlimits:\n  max_concept_bytes: 1234\n"
    cfg = load_config(write_config(tmp_path, 1, extra))
    store = Store.from_config(cfg)
    assert store.max_concept_bytes == 1234
    assert store.index.path == cfg.root / "custom" / "fts.sqlite"
