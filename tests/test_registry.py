import os

import pytest
from registry_helpers import KUBE, make_ws

from okf_notebooks.registry import NotebookNotFound, Registry


def test_list_notebooks_summaries(root):
    make_ws(
        root,
        "kube",
        KUBE,
        [
            ("decisions/a.md", "---\ntitle: A\ntags: [cd]\n---\nx\n"),
            ("decisions/b.md", "---\ntitle: B\n---\nx\n"),
        ],
    )
    old = root / "notebooks/kube/decisions/a.md"
    os.utime(old, (1_700_000_000, 1_700_000_000))
    make_ws(root, "hidden", "name: H\nstatus: proposed\n", where="_proposed")
    make_ws(root, "gone", "name: G\nstatus: archived\n", where="_archive")

    got = {s.slug: s for s in Registry(root).list_notebooks()}

    assert set(got) == {"notes", "kube"}  # only active ones
    k = got["kube"]
    assert (k.name, k.description) == (
        "Платформа Kubernetes",
        "Решения и плейбуки по кластерам",
    )
    assert k.scope == "Что сюда писать: деплой"
    assert k.types == ["Decision", "Term"]
    assert k.note_count == 2
    assert k.last_modified is not None and k.last_modified > "2023-11-14"
    # minimal fixture bundle (slug+status only) still lists, with no notes
    assert got["notes"].note_count == 0
    assert got["notes"].last_modified is None
    assert got["notes"].name == "notes"


def test_describe_types_fields_counters_tags_index(root):
    make_ws(
        root,
        "kube",
        KUBE,
        [
            ("decisions/a.md", "---\ntitle: A\ntags: [cd, k8s]\n---\nx\n"),
            ("decisions/b.md", "---\ntitle: B\ntags: [cd]\n---\nx\n"),
        ],
    )
    (root / "notebooks/kube/index.md").write_text("# hand index\n")
    d = Registry(root).describe("kube")

    assert d.status == "active"
    assert d.index_md == "# hand index\n"
    assert d.top_tags[0] == {"tag": "cd", "count": 2}
    assert {"tag": "k8s", "count": 1} in d.top_tags
    by = {t.name: t for t in d.types}
    dec = by["Decision"]
    assert dec.dir == "decisions"
    assert dec.count == 2
    assert dec.description.startswith("A decision taken")  # from builtin core
    assert "description" in dec.fields
    assert by["Term"].count == 0


def test_describe_proposed_and_rejected(root):
    make_ws(root, "wip", "name: WIP\nstatus: proposed\n", where="_proposed")
    make_ws(
        root,
        "nope-2026-11-08",
        "name: Nope\nstatus: archived\nrejected: {reason: duplicates kube}\n",
        where="_archive",
    )
    r = Registry(root)
    assert r.describe("wip").status == "proposed"
    rej = r.describe("nope")
    assert rej.status == "rejected"
    assert rej.rejection_reason == "duplicates kube"
    with pytest.raises(NotebookNotFound):
        r.describe("missing")
    with pytest.raises(NotebookNotFound):
        r.describe("../etc")


def test_builtin_core_preset_has_four_types(tmp_path):
    core = Registry(tmp_path).presets()["core"]
    assert [t.name for t in core.types] == ["Project", "Decision", "Playbook", "Term"]
    assert all(t.description for t in core.types)


def test_presets_dir_hot_pickup_without_restart(tmp_path, root):
    pdir = tmp_path / "presets"
    pdir.mkdir()
    reg = Registry(root, presets_dir=pdir)
    assert set(reg.presets()) == {"core"}

    (pdir / "eng.yaml").write_text(
        "description: Engineering\n"
        "types:\n"
        "  - {name: Runbook, description: Ops steps, fields: [severity]}\n"
    )
    (pdir / "broken.yaml").write_text("types: [unclosed\n")  # must not break us
    got = reg.presets()
    assert set(got) == {"core", "eng"}
    assert got["eng"].type("runbook").fields == ("severity",)

    make_ws(root, "ops", "name: Ops\npreset: eng\ntypes: [Runbook]\n")
    d = reg.describe("ops")
    assert d.types[0].name == "Runbook"
    assert d.types[0].description == "Ops steps"
    assert d.types[0].fields == ["severity"]
    assert d.types[0].dir == "runbooks"


def test_template_file_overrides_preset_fields(root):
    ws = make_ws(root, "kube", KUBE)
    (ws / ".okf/templates").mkdir()
    (ws / ".okf/templates/Decision.md").write_text(
        "---\ndescription: ''\ndecided: ''\nowner: ''\n---\n"
    )
    t = {t.name: t for t in Registry(root).describe("kube").types}["Decision"]
    assert t.fields == ["description", "decided", "owner"]


def test_declared_type_dir(root):
    make_ws(
        root,
        "x",
        "name: X\ntypes:\n  - {name: Decision, dir: adrs}\n  - Term\n",
    )
    reg = Registry(root)
    assert reg.declared_type_dir("x", "decision") == "adrs"
    assert reg.declared_type_dir("x", "Term") == "terms"
    assert reg.declared_type_dir("x", "Other") is None
