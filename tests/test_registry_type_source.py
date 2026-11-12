"""the Registry is the single source of the Type vocabulary for the validator."""

from registry_helpers import make_ws

from okf_notebooks.registry import Registry
from okf_notebooks.store import Invalid, Store


def test_registry_types_include_required_and_stale_after(tmp_path):
    root = tmp_path
    ws = make_ws(
        root,
        "x",
        "name: X\n"
        "types:\n"
        "  - {name: Decision, required: [owner], stale_after: 90d}\n"
        "  - Term\n",
    )
    got = Registry(root).types(ws)
    assert set(got) == {"Decision", "Term"}
    assert got["Decision"].required == ("owner",)
    assert got["Decision"].stale_after == "90d"
    assert got["Term"].required == ()


def test_registry_reads_mapping_shape_too(root):
    got = Registry(root).types(root / "notebooks" / "notes")
    assert got["Decision"].required == ("owner",) and got["Decision"].stale_after == "180d"


def test_preset_supplies_required_to_notebook_types(tmp_path):
    pdir = tmp_path / "presets"
    pdir.mkdir()
    (pdir / "eng.yaml").write_text(
        "types:\n  - {name: Runbook, required: [severity], stale_after: 30d}\n"
    )
    ws = make_ws(tmp_path, "ops", "name: Ops\npreset: eng\ntypes: [Runbook]\n")
    spec = Registry(tmp_path, presets_dir=pdir).types(ws)["Runbook"]
    assert spec.required == ("severity",) and spec.stale_after == "30d"


def test_store_validates_against_registry_vocabulary(tmp_path):
    make_ws(tmp_path, "ops", "name: Ops\ntypes: [Term]\n")
    store = Store(tmp_path, git=False, types=Registry(tmp_path))
    store.write_concept(
        "ops", type="Term", title="Etag", frontmatter={"description": "d"},
        body="A validator token for concurrency.\n", actor="claude-code",
    )
    try:
        store.write_concept(
            "ops", type="Decision", title="D", frontmatter={"description": "d"},
            body="Body long enough to pass the check.\n", actor="claude-code",
        )
    except Invalid as e:
        assert any(v.rule == "type" for v in e.violations)
    else:
        raise AssertionError("undeclared type must be rejected")


def test_store_defaults_to_its_registry_as_type_source(tmp_path):
    make_ws(tmp_path, "ops", "name: Ops\ntypes: [Term]\n")
    store = Store(tmp_path, git=False)
    assert store.types is store.registry
