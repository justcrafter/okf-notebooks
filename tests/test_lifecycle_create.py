"""notebook_create rules, policy, duplicates, atomic assembly."""

import os
import subprocess
import sys
import textwrap

import pytest
from lifecycle_helpers import DESC, actor, args, make_lc, meta

from okf_notebooks.lifecycle import (
    Forbidden,
    Lifecycle,
    LimitExceeded,
    SimilarExists,
    human_actor,
)
from okf_notebooks.registry import Registry
from okf_notebooks.store import Invalid, Store


@pytest.fixture
def lc(tmp_path):
    return make_lc(tmp_path / "root")


def test_direct_actor_creates_active_bundle(lc):
    res = lc.create_notebook(actor(policy="direct"), **args())
    assert (res.status, res.slug, res.path_in_root) == ("created", "kube", "notebooks/kube")
    b = lc.root / "notebooks" / "kube"
    assert (b / "index.md").is_file() and (b / "log.md").is_file()
    assert (b / ".okf" / "okf-base.yaml").is_file()
    for d in ("projects", "decisions", "playbooks", "terms"):
        assert (b / d).is_dir()
        assert (b / ".okf" / "templates" / f"{d[:-1].capitalize()}.md").is_file()
    m = meta(lc.root, "notebooks", "kube")
    assert m["status"] == "active" and m["preset"] == "core"
    assert m["created"]["by"] == "claude-code"
    d = Registry(lc.root).describe("kube")
    assert d.status == "active" and [t.name for t in d.types] == [
        "Project", "Decision", "Playbook", "Term"
    ]
    log = (b / "log.md").read_text()
    assert "claude-code" in log and "No existing notebook covers" in log


def test_proposal_actor_goes_to_proposed_and_is_not_listed(lc):
    res = lc.create_notebook(actor(policy="proposal"), **args())
    assert (res.status, res.path_in_root) == ("proposed", "_proposed/kube")
    assert not (lc.root / "notebooks" / "kube").exists()
    assert Registry(lc.root).describe("kube").status == "proposed"
    assert Registry(lc.root).list_notebooks() == []
    assert meta(lc.root, "_proposed", "kube")["status"] == "proposed"


def test_policy_off_is_forbidden_and_leaves_nothing(lc):
    with pytest.raises(Forbidden) as e:
        lc.create_notebook(actor(policy="off"), **args())
    assert e.value.code == "forbidden"
    assert not (lc.root / "_proposed").exists() and not (lc.root / "notebooks").exists()


def test_actor_without_permission_is_forbidden_even_with_policy(lc):
    with pytest.raises(Forbidden):
        lc.create_notebook(actor(policy="direct", perms=("read",)), **args())


def test_human_creates_active_regardless_of_policy_config(lc):
    res = lc.create_notebook(human_actor(), **args())
    assert res.status == "created"
    assert meta(lc.root, "notebooks", "kube")["created"]["by"] == "human"


def test_all_field_errors_returned_in_one_list(lc):
    with pytest.raises(Invalid) as e:
        lc.create_notebook(
            actor(policy="direct"),
            slug="Bad Slug",
            name="ab",
            description="too short",
            scope="",
            rationale="",
            preset="nope",
        )
    rules = {v.rule for v in e.value.violations}
    assert {"slug", "name", "description", "scope", "rationale", "preset"} <= rules
    assert e.value.code == "invalid"


@pytest.mark.parametrize(
    "over,rule",
    [
        ({"slug": "admin"}, "slug"),  # reserved
        ({"slug": "a"}, "slug"),  # pattern
        ({"name": "x" * 81}, "name"),
        ({"description": "d" * 301}, "description"),
        ({"description": "d" * 39}, "description"),
        ({"preset": None, "types": None}, "types"),  # neither
        ({"types": [{"name": "A", "description": "x"}]}, "types"),  # both preset and types
        (
            {"preset": None, "types": [{"name": f"T{i}", "description": "d"} for i in range(13)]},
            "types",
        ),
        ({"preset": None, "types": [{"name": "Dup", "description": "d"}] * 2}, "types"),
        ({"preset": None, "types": [{"name": "../x", "description": "d"}]}, "types"),
    ],
)
def test_each_field_rule_rejects(lc, over, rule):
    with pytest.raises(Invalid) as e:
        lc.create_notebook(actor(policy="direct"), **args(**over))
    assert rule in {v.rule for v in e.value.violations}


def test_boundaries_accepted(lc):
    lc.create_notebook(
        actor(policy="direct"),
        **args(
            "abc",
            name="x" * 3,
            description="d" * 40,
            preset=None,
            types=[{"name": f"T{i}", "description": "d"} for i in range(12)],
        ),
    )
    lc.create_notebook(
        actor(policy="direct"),
        **args("long", name="x" * 80, description="e" * 300, scope="s"),
    )


def test_custom_types_are_stored_with_dirs_and_templates(lc):
    lc.create_notebook(
        human_actor(),
        **args(
            preset=None,
            types=[
                {"name": "Runbook", "description": "Ops steps", "fields": ["severity"],
                 "required": ["severity"]},
            ],
        ),
    )
    d = Registry(lc.root).describe("kube")
    t = d.types[0]
    assert (t.name, t.dir, t.description) == ("Runbook", "runbooks", "Ops steps")
    assert "severity" in t.fields
    assert (lc.root / "notebooks/kube/runbooks").is_dir()
    spec = Registry(lc.root).types(lc.root / "notebooks/kube")["Runbook"]
    assert spec.required == ("severity",)


def test_slug_unique_across_active_proposed_archived(lc):
    h = human_actor()
    lc.create_notebook(h, **args("one", name="Alpha one", description="Alpha " * 8 + "stuff"))
    lc.create_notebook(
        actor(policy="proposal"),
        **args("two", name="Bravo two", description="Bravo " * 8 + "things", scope="zzz yyy"),
    )
    lc.create_notebook(h, **args("three", name="Charlie", description="Charlie " * 6 + "x",
                                  scope="qqq www"))
    lc.archive("three")
    for slug in ("one", "two", "three"):
        with pytest.raises(Invalid) as e:
            lc.create_notebook(
                h,
                **args(slug, name="Totally other", description="Other words entirely here, "
                       "nothing alike at all.", scope="unrelated scope text", confirm_distinct=True),
            )
        assert "slug" in {v.rule for v in e.value.violations}


def test_similar_exists_lists_candidates_and_creates_nothing(lc):
    lc.create_notebook(human_actor(), **args("kube"))
    with pytest.raises(SimilarExists) as e:
        lc.create_notebook(actor(policy="proposal"), **args("kubernetes", name="Kubernetes platform "))
    assert e.value.code == "similar_exists"
    assert [c["slug"] for c in e.value.candidates] == ["kube"]
    assert e.value.candidates[0]["name"] == "Kubernetes platform"
    assert not (lc.root / "_proposed" / "kubernetes").exists()


def test_similar_found_by_description_and_scope_and_among_proposed(lc):
    lc.create_notebook(actor(policy="proposal"), **args("kube"))
    with pytest.raises(SimilarExists):  # same description, other name/scope
        lc.create_notebook(human_actor(), **args("k8s", name="Cluster notes", scope="other scope here"))
    with pytest.raises(SimilarExists):  # same scope only
        lc.create_notebook(
            human_actor(),
            **args("k8s", name="Cluster notes", description="Completely different words go here, "
                   "none shared with the other."),
        )


def test_dissimilar_notebook_is_not_flagged(lc):
    lc.create_notebook(human_actor(), **args("kube"))
    lc.create_notebook(
        human_actor(),
        **args("cooking", name="Recipes", description="Family recipes, menus and shopping lists "
               "for the weekend.", scope="Write: recipes only."),
    )


def test_confirm_distinct_skips_check_and_is_recorded(lc):
    lc.create_notebook(human_actor(), **args("kube"))
    lc.create_notebook(
        actor(policy="proposal"), **args("kubernetes", confirm_distinct=True,
                                         rationale="Different clusters: staging only.")
    )
    m = meta(lc.root, "_proposed", "kubernetes")
    assert m["confirm_distinct"] is True
    assert "Different clusters" in m["rationale"]
    assert "confirm_distinct" in (lc.root / "_proposed/kubernetes/log.md").read_text()


def test_max_notebooks_counts_active_and_proposed(tmp_path):
    lc = make_lc(tmp_path / "root", max_notebooks=2)
    h = human_actor()
    lc.create_notebook(h, **args("aaa", name="Aaa", description="Alpha beta gamma delta epsilon " * 2))
    lc.create_notebook(
        actor(policy="proposal"),
        **args("bbb", name="Bbb", description="Sigma tau upsilon phi chi psi omega " * 2, scope="x y z"),
    )
    with pytest.raises(LimitExceeded) as e:
        lc.create_notebook(h, **args("ccc", name="Ccc", description="Orange apple banana mango " * 3,
                                      scope="fruit"))
    assert e.value.code == "limit_exceeded"
    assert not (lc.root / "notebooks" / "ccc").exists()


def test_pending_limit_is_three_per_actor(lc):
    words = ["alpha", "bravo", "charlie", "delta", "echo"]
    p = actor(policy="proposal")
    for w in words[:3]:
        lc.create_notebook(
            p, **args(w, name=w.title() + " space", description=(w + " ") * 12 + "end",
                      scope=f"{w} stuff")
        )
    with pytest.raises(LimitExceeded):
        lc.create_notebook(
            p, **args("delta", name="Delta space", description="delta " * 12 + "end", scope="delta stuff")
        )
    other = actor("opencode", policy="proposal")  # separate budget
    lc.create_notebook(
        other, **args("delta", name="Delta space", description="delta " * 12 + "end", scope="delta stuff")
    )
    # a human or direct actor is not subject to the pending limit
    lc.create_notebook(
        human_actor(), **args("echo", name="Echo space", description="echo " * 12 + "end",
                              scope="echo stuff")
    )


def test_target_already_existing_cancels_without_touching_it(lc):
    # a stray directory occupying the target (e.g. foreign process) must not be replaced
    (lc.root / "notebooks" / "kube").mkdir(parents=True)
    with pytest.raises(Invalid):
        lc.create_notebook(human_actor(), **args())
    assert list((lc.root / "notebooks" / "kube").iterdir()) == []
    assert not [p for p in (lc.root / ".tmp").iterdir() if p.is_dir()]


def test_failed_validation_removes_tmp_assembly(lc, tmp_path):
    pdir = tmp_path / "presets"
    pdir.mkdir()
    (pdir / "bad.yaml").write_text("types:\n  - {name: A, dir: same}\n  - {name: B, dir: same}\n")
    lc2 = make_lc(lc.root, registry=Registry(lc.root, presets_dir=pdir))
    with pytest.raises(Invalid):
        lc2.create_notebook(human_actor(), **args(preset="bad"))
    assert not (lc.root / "notebooks" / "kube").exists()
    assert not [p for p in (lc.root / ".tmp").iterdir() if p.is_dir()]


_RACE = textwrap.dedent(
    """
    import sys
    from lifecycle_helpers import args, make_lc
    from okf_notebooks.lifecycle import human_actor
    lc = make_lc(sys.argv[1])
    try:
        lc.create_notebook(human_actor(), **args("race"))
    except Exception as e:
        print("LOST", type(e).__name__)
        sys.exit(3)
    print("WON")
    """
)


def test_two_processes_creating_one_slug_exactly_one_wins(tmp_path):
    root = tmp_path / "root"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(os.path.dirname(__file__))])}
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _RACE, str(root)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for _ in range(2)
    ]
    outs = [p.communicate(timeout=60) for p in procs]
    codes = sorted(p.returncode for p in procs)
    assert codes == [0, 3], outs
    assert (root / "notebooks" / "race" / ".okf" / "notebook.yaml").is_file()
    assert (root / "notebooks" / "race" / "log.md").read_text().count("create") == 1
    assert [d.name for d in (root / "notebooks").iterdir()] == ["race"]


_CRASH = textwrap.dedent(
    """
    import os, sys
    from lifecycle_helpers import args, make_lc
    from okf_notebooks.lifecycle import human_actor
    def die(*a, **k):
        os._exit(9)
    os.rename = die
    make_lc(sys.argv[1]).create_notebook(human_actor(), **args("half"))
    """
)


def test_process_killed_before_rename_leaves_nothing_in_notebooks(tmp_path):
    root = tmp_path / "root"
    env = {**os.environ, "PYTHONPATH": os.path.dirname(__file__)}
    r = subprocess.run([sys.executable, "-c", _CRASH, str(root)], env=env, timeout=60, check=False)
    assert r.returncode == 9
    assert not (root / "notebooks" / "half").exists()
    assert not (root / "_proposed" / "half").exists()
    reg = Registry(root)
    assert reg.list_notebooks() == [] and reg.status_of("half") is None
    # the assembly is left in .tmp/<uuid>/ only
    left = [p for p in (root / ".tmp").iterdir() if p.is_dir()]
    assert len(left) == 1
    # and a retry succeeds
    make_lc(root).create_notebook(human_actor(), **args("half"))
    assert (root / "notebooks" / "half").is_dir()


def test_creation_is_committed_with_actor_as_author(tmp_path):
    root = tmp_path / "root"
    lc = Lifecycle(Store(root, git=True))
    lc.create_notebook(actor("opencode", policy="direct"), **args())
    out = subprocess.run(
        ["git", "-C", str(root), "log", "--format=%an|%s", "-1"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out.startswith("opencode|") and "kube" in out
    status = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                            capture_output=True, text=True, check=True).stdout
    assert status.strip() == ""


def test_description_constant_is_in_range():
    assert 40 <= len(DESC) <= 300


# -- B7: agent-supplied type names are never echoed unbounded --------------------
def _shown(exc):
    return [str(exc.value), *(v.message for v in exc.value.violations)]


@pytest.mark.parametrize(
    "bad_type",
    [
        {"name": "Q" * 5000, "description": "d"},
        {"name": 5000 * "Q", "description": ""},
        {"name": "Ok", "description": "d", "dir": "q_" * 2500},
        {"name": ["Q" * 5000], "description": "d"},
    ],
)
def test_create_notebook_clips_bad_type_names(lc, bad_type):
    with pytest.raises(Invalid) as e:
        lc.create_notebook(actor(policy="direct"), **args(preset=None, types=[bad_type]))
    assert any("types" in m for m in _shown(e))  # rejected for the type, not another reason
    assert all("Q" * 65 not in m and "q_" * 33 not in m for m in _shown(e))


def test_create_notebook_clips_duplicate_type_name(lc):
    t = {"name": "Dup", "description": "d"}
    with pytest.raises(Invalid) as e:
        lc.create_notebook(actor(policy="direct"), **args(preset=None, types=[t, t]))
    assert any("duplicate type 'Dup'" in m for m in _shown(e))


def test_type_define_clips_bad_type_name(lc):
    lc.create_notebook(human_actor(), **args())
    with pytest.raises(Invalid) as e:
        lc.define_type(actor(policy="direct"), "kube", name="Q" * 5000, description="d")
    assert all("Q" * 65 not in m for m in _shown(e))


def test_rename_and_delete_type_clip_names(lc):
    lc.create_notebook(human_actor(), **args())
    with pytest.raises(Invalid) as e:
        lc.rename_type("kube", "Decision", "Q" * 5000)
    assert all("Q" * 65 not in m for m in _shown(e))
    with pytest.raises(Invalid) as e:
        lc.delete_type("kube", "Q" * 5000)
    assert all("Q" * 65 not in m for m in _shown(e))
