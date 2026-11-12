"""A malformed `stale_after` in a type template is caught at definition time and never poisons writes."""

import pytest
import yaml
from lifecycle_helpers import actor, args, make_lc
from test_lifecycle_ops import make_bundle

from okf_notebooks.lifecycle import human_actor
from okf_notebooks.registry import Registry
from okf_notebooks.store import Invalid, Store

H = human_actor()
D = actor(policy="direct")
BAD = ["99999999999999d", "soon", "180", "-5d", "1.5y", "99999y"]


def _rules(e):
    return {v.rule for v in e.value.violations}


def _says_type(e, name):
    return any(name in v.message and "stale_after" in v.message for v in e.value.violations)


@pytest.fixture
def lc(tmp_path):
    return make_lc(tmp_path / "root")


@pytest.mark.parametrize("bad", BAD)
def test_create_notebook_rejects_bad_type_stale_after(lc, bad):
    t = {"name": "Runbook", "description": "d", "stale_after": bad}
    with pytest.raises(Invalid) as e:
        lc.create_notebook(D, **args(preset=None, types=[t]))
    assert "types" in _rules(e) and _says_type(e, "Runbook")
    assert not (lc.root / "notebooks" / "kube").exists()


@pytest.mark.parametrize("bad", BAD)
def test_define_type_rejects_bad_stale_after(lc, bad):
    lc.create_notebook(H, **args())
    with pytest.raises(Invalid) as e:
        lc.define_type(D, "kube", name="Runbook", description="d", stale_after=bad)
    assert "types" in _rules(e) and _says_type(e, "Runbook")


def test_define_type_accepts_good_stale_after(lc):
    lc.create_notebook(H, **args())
    lc.define_type(D, "kube", name="Runbook", description="d", stale_after="90d")


def test_bad_preset_is_skipped_not_applied(tmp_path):
    pdir = tmp_path / "presets"
    pdir.mkdir()
    (pdir / "bad.yaml").write_text(
        "name: bad\ntypes:\n  - {name: Runbook, description: d, stale_after: soon}\n"
    )
    (pdir / "good.yaml").write_text(
        "name: good\ntypes:\n  - {name: Runbook, description: d, stale_after: 90d}\n"
    )
    reg = Registry(tmp_path / "root", presets_dir=pdir)
    assert "bad" not in reg.presets() and "good" in reg.presets()


def test_adopt_reports_bad_template_stale_after(lc, tmp_path):
    src = make_bundle(tmp_path / "b", with_yaml=True)
    wy = src / ".okf" / "notebook.yaml"
    m = yaml.safe_load(wy.read_text())
    m["types"] = [{"name": "Decision", "description": "d", "stale_after": "99999999999999d"}]
    wy.write_text(yaml.safe_dump(m))
    with pytest.raises(Invalid) as e:
        lc.adopt(src, slug="adopted")
    assert "types" in _rules(e) and _says_type(e, "Decision")
    assert not (lc.root / "notebooks" / "adopted").exists()


def _poison(root):
    p = root / "notebooks" / "notes" / ".okf" / "notebook.yaml"
    p.write_text(p.read_text().replace("stale_after: 180d", "stale_after: 99999999999999d"))


def test_hand_edited_bad_template_does_not_break_writes_with_a_clear_warning(root):
    _poison(root)
    s = Store(root, git=False)
    res = s.write_concept(
        "notes", type="Decision", title="Pick", body="x" * 30, actor="claude-code",
        frontmatter={"description": "d", "owner": "o"},
    )
    (w,) = [w for w in res.warnings if w.startswith("stale-after")]
    assert "Decision" in w and "template" in w
    assert "stale_after" not in s.read_concept("notes", res.concept.id).frontmatter
    assert [h.id for h in s.index.search("x").hits] == [res.concept.id]
    assert [i.id for i in s.index.list().items] == [res.concept.id]
    assert Registry(root).describe("notes").note_count == 1


def test_audit_names_the_bad_template(root):
    _poison(root)
    lc = make_lc(root)
    vs = lc.validate_bundle(root / "notebooks" / "notes", audit=True)
    assert any(v.rule == "types" and "Decision" in v.message for v in vs)


# -- E1: ordinary external bundles are adopted; agent writes stay strict ----------
EXTERNAL = ["90 days", "1 year", "12 months", "10000d", 180]


@pytest.mark.parametrize("val", EXTERNAL)
def test_adopt_accepts_external_concept_stale_after_with_a_warning(lc, tmp_path, val):
    src = make_bundle(tmp_path / "ext", with_yaml=True)
    p = src / "decisions" / "use-argocd.md"
    p.write_text(
        "---\ntype: Decision\ntitle: Use ArgoCD\ndescription: why\n"
        f"stale_after: {val!r}\n---\nWe use ArgoCD as decided.\n"
    )
    res = lc.adopt(src, slug="ext")
    assert res.slug == "ext"
    assert [h.id for h in lc.store.index.search("ArgoCD").hits] == ["/decisions/use-argocd"]
    assert "/decisions/use-argocd" in [i.id for i in lc.store.index.list().items]
    vs = lc.validate_bundle(lc.root / "notebooks" / "ext", audit=True)
    assert any(v.rule == "stale-after" and v.level == "warning" for v in vs)
    assert not [v for v in vs if v.rule == "stale-after" and v.level == "error"]


@pytest.mark.parametrize("val", EXTERNAL)
def test_agent_write_still_rejects_the_same_values(root, val):
    s = Store(root, git=False)
    with pytest.raises(Invalid) as e:
        s.write_concept(
            "notes", type="Term", title="T", body="x" * 30, actor="claude-code",
            frontmatter={"description": "d", "stale_after": val},
        )
    assert "stale-after" in _rules(e)
