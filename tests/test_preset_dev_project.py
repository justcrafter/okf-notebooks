"""The shipped `dev-project` preset loads, stays within limits and works end to end."""

from pathlib import Path

import pytest
from lifecycle_helpers import args

from okf_notebooks.lifecycle import Lifecycle, human_actor
from okf_notebooks.registry import Registry
from okf_notebooks.store import Invalid, Store

PRESETS = Path(__file__).resolve().parent.parent / "presets"
BODY = "A body that is certainly long enough to pass."


@pytest.fixture
def env(tmp_path):
    reg = Registry(tmp_path, PRESETS)
    store = Store(tmp_path, git=False, registry=reg)
    lc = Lifecycle(store)
    lc.create_notebook(
        human_actor(), **args("proj", preset="dev-project", name="Project", rationale="Dev knowledge for the project.")
    )
    return reg, store


def test_preset_is_discovered_and_valid(env):
    reg, _ = env
    p = reg.preset("dev-project")
    assert p is not None
    names = [t.name for t in p.types]
    assert names == ["Project", "Term", "Decision", "Spec", "Ticket", "Research", "Prototype", "Bug", "Retro", "Playbook"]
    assert len(names) <= 12
    dirs = [t.dir for t in p.types]
    assert len(set(dirs)) == len(dirs) and all(t.description for t in p.types)


def test_notebook_gets_all_types(env):
    reg, _ = env
    detail = reg.describe("proj")
    assert [t.name for t in detail.types][:3] == ["Project", "Term", "Decision"]
    assert len(detail.types) == 10


@pytest.mark.parametrize(
    "type_,fm",
    [
        ("Term", {"description": "A glossary term"}),
        ("Decision", {"description": "A decision", "decided": "2026-11-11"}),
        ("Ticket", {"description": "A ticket", "category": "bug", "triage": "needs-triage"}),
        ("Research", {"description": "Findings", "question": "Does X work?"}),
        ("Bug", {"description": "A bug", "symptom": "It crashes"}),
    ],
)
def test_agent_can_write_each_type(env, type_, fm):
    _, store = env
    r = store.write_concept("proj", type=type_, title=f"{type_} sample", frontmatter=fm, body=BODY, actor="claude-code")
    assert r.concept.frontmatter["status"] == "draft"


def test_required_fields_are_enforced(env):
    _, store = env
    with pytest.raises(Invalid) as e:
        store.write_concept("proj", type="Decision", title="No date", frontmatter={"description": "d"}, body=BODY, actor="claude-code")
    assert "decided" in str(e.value)

