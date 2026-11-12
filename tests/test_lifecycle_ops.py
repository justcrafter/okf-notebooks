"""approve/reject/archive/restore/adopt, type changes, marking, audit, tmp cleanup."""

import os
import time

import pytest
from lifecycle_helpers import actor, args, make_lc, meta

from okf_notebooks.lifecycle import (
    Forbidden,
    LimitExceeded,
    cleanup_tmp,
    human_actor,
)
from okf_notebooks.registry import NotebookNotFound, Registry
from okf_notebooks.store import Invalid, NotFound, Store

H = human_actor()
P = actor(policy="proposal")


@pytest.fixture
def lc(tmp_path):
    return make_lc(tmp_path / "root")


def other(slug, word):
    return args(slug, name=f"{word.title()} space", description=(word + " ") * 12 + "end",
                scope=f"{word} only")


def note(lc, ws="kube", type="Decision", title="Use ArgoCD", actor="claude-code", **fm):
    return lc.store.write_concept(
        ws, type=type, title=title,
        frontmatter={"description": "why we picked it", **fm},
        body="We use ArgoCD as decided in the review.\n", actor=actor,
    )


# -- approve / reject / pending ------------------------------------------------------
def test_pending_lists_author_rationale_description(lc):
    lc.create_notebook(P, **args("kube"))
    [it] = lc.pending()
    assert (it.kind, it.slug, it.author) == ("notebook", "kube", "claude-code")
    assert "No existing notebook" in it.rationale and it.description.startswith("Decisions")
    assert lc.pending(author="opencode") == []


def test_approve_moves_to_active_keeps_notes_and_logs(lc):
    lc.create_notebook(P, **args("kube"))
    lc.approve("kube")
    assert not (lc.root / "_proposed" / "kube").exists()
    assert Registry(lc.root).describe("kube").status == "active"
    m = meta(lc.root, "notebooks", "kube")
    assert m["status"] == "active" and m["approved"]["by"] == "human"
    assert "approve" in (lc.root / "notebooks/kube/log.md").read_text()
    assert lc.pending() == []
    note(lc)  # now writable through the store


def test_proposed_notebook_keeps_notes_across_approval(lc):
    lc.create_notebook(P, **args("kube"))
    # author writes into the proposed bundle (placed directly; store writes target active only)
    d = lc.root / "_proposed/kube/decisions"
    (d / "x.md").write_text("---\ntype: Decision\ntitle: X\ndescription: d\n---\nbody body body body body\n")
    lc.approve("kube")
    assert (lc.root / "notebooks/kube/decisions/x.md").is_file()


def test_approve_unknown_or_active_raises_not_found(lc):
    lc.create_notebook(H, **args("kube"))
    for slug in ("kube", "nope", "../x"):
        with pytest.raises(NotebookNotFound):
            lc.approve(slug)


def test_reject_archives_with_reason_visible_in_describe(lc):
    lc.create_notebook(P, **args("kube"))
    lc.reject("kube", "duplicates the infra notebook")
    reg = Registry(lc.root)
    d = reg.describe("kube")
    assert d.status == "rejected" and d.rejection_reason == "duplicates the infra notebook"
    assert not (lc.root / "_proposed" / "kube").exists()
    assert reg.list_notebooks() == []
    assert lc.pending() == []


def test_reject_requires_reason_and_a_pending_slug(lc):
    lc.create_notebook(P, **args("kube"))
    with pytest.raises(Invalid):
        lc.reject("kube", "  ")
    assert (lc.root / "_proposed" / "kube").is_dir()
    with pytest.raises(NotebookNotFound):
        lc.reject("zzz", "no")


def test_rejected_slug_stays_reserved_and_cannot_be_restored(lc):
    lc.create_notebook(P, **args("kube"))
    lc.reject("kube", "no")
    with pytest.raises(Invalid) as e:
        lc.create_notebook(H, **args("kube"))
    assert "slug" in {v.rule for v in e.value.violations}
    with pytest.raises(Invalid):
        lc.restore("kube")


def test_rejection_frees_the_pending_slot(lc):
    for w in ("alpha", "bravo", "charlie"):
        lc.create_notebook(P, **other(w, w))
    with pytest.raises(LimitExceeded):
        lc.create_notebook(P, **other("delta", "delta"))
    lc.reject("alpha", "meh")
    lc.create_notebook(P, **other("delta", "delta"))


# -- machine label in audit trail ----------------------------------------------------
def _git(root, *a):
    import subprocess

    return subprocess.run(
        ["git", "-C", str(root), *a], capture_output=True, text=True, check=True
    ).stdout


def test_agent_notebook_creation_carries_machine_label(tmp_path):
    root = tmp_path / "root"
    lc = make_lc(root)
    lc.store.git = True
    lc.create_notebook(actor(policy="direct"), **args("kube"))
    assert "claude-code [laptop] create kube" in (root / "notebooks/kube/log.md").read_text()
    assert _git(root, "log", "-1", "--format=%s").strip().endswith("[laptop]")


def test_agent_define_type_and_type_proposal_carry_machine_label(tmp_path):
    root = tmp_path / "root"
    lc = make_lc(root)
    lc.store.git = True
    lc.create_notebook(H, **args("kube"))
    lc.define_type(actor(policy="direct"), "kube", name="Runbook", description="How to operate things.")
    assert "claude-code [laptop] type-define Runbook" in (root / "notebooks/kube/log.md").read_text()
    assert _git(root, "log", "-1", "--format=%s").strip().endswith("[laptop]")
    lc.define_type(
        actor(policy="proposal"), "kube", name="Faq", description="Frequent questions.",
        rationale="needed for onboarding",
    )
    assert _git(root, "log", "-1", "--format=%s").strip().endswith("[laptop]")


def test_human_actions_have_no_machine_label(tmp_path):
    root = tmp_path / "root"
    lc = make_lc(root)
    lc.create_notebook(H, **args("kube"))
    assert "human create kube" in (root / "notebooks/kube/log.md").read_text()


# -- archive / restore -------------------------------------------------------------
def test_archive_hides_everywhere_and_keeps_slug_reserved(lc):
    lc.create_notebook(H, **args("kube"))
    note(lc)
    lc.archive("kube")
    reg = Registry(lc.root)
    assert reg.list_notebooks() == []
    assert not (lc.root / "notebooks" / "kube").exists()
    assert reg.describe("kube").status == "archived"
    [arch] = list((lc.root / "_archive").iterdir())
    assert arch.name.startswith("kube-") and (arch / "decisions/use-argocd.md").is_file()
    with pytest.raises(NotFound):  # store no longer serves it
        lc.store.read_concept("kube", "/decisions/use-argocd")
    with pytest.raises(Invalid):
        lc.create_notebook(H, **args("kube"))


def test_archive_requires_active_notebook(lc):
    lc.create_notebook(P, **args("kube"))
    with pytest.raises(NotebookNotFound):
        lc.archive("kube")  # proposed
    with pytest.raises(NotebookNotFound):
        lc.archive("nope")


def test_restore_brings_back_with_notes(lc):
    lc.create_notebook(H, **args("kube"))
    note(lc)
    lc.archive("kube")
    lc.restore("kube")
    assert Registry(lc.root).describe("kube").status == "active"
    assert lc.store.read_concept("kube", "/decisions/use-argocd").frontmatter["title"] == "Use ArgoCD"
    assert "archived" not in meta(lc.root, "notebooks", "kube")
    assert not list((lc.root / "_archive").iterdir())
    with pytest.raises(Invalid):  # active already
        lc.restore("kube")


def test_archive_waits_for_an_in_flight_write_to_the_notebook(tmp_path):
    from okf_notebooks.store import Busy

    lc = make_lc(tmp_path / "root")
    lc.store.lock_timeout = 0.2
    lc.create_notebook(H, **args("kube"))
    with lc.store.lock("kube.lock"), pytest.raises(Busy):  # a write is in flight
        lc.archive("kube")
    assert (lc.root / "notebooks/kube/.okf/notebook.yaml").is_file()
    assert not (lc.root / "_archive").exists() or not list((lc.root / "_archive").iterdir())


def test_restore_waits_for_the_notebook_lock(tmp_path):
    from okf_notebooks.store import Busy

    lc = make_lc(tmp_path / "root")
    lc.store.lock_timeout = 0.2
    lc.create_notebook(H, **args("kube"))
    lc.archive("kube")
    with lc.store.lock("kube.lock"), pytest.raises(Busy):
        lc.restore("kube")
    assert not (lc.root / "notebooks" / "kube").exists()


def test_write_in_flight_vs_archive_never_leaves_an_orphan_dir(tmp_path):
    import threading

    lc = make_lc(tmp_path / "root")
    lc.store.lock_timeout = 5
    lc.create_notebook(H, **args("kube"))
    results: list[object] = []

    def writer():
        try:
            results.append(note(lc))
        except NotFound as e:  # NotFound once archived is fine
            results.append(e)

    # Handshake: every thread signals right before it asks for the held notebook lock.
    asking = threading.Semaphore(0)
    real_lock = lc.store._lock  # the one entry point of write_concept and lock()

    def signalling_lock(name):
        if name == "kube.lock":
            asking.release()
        return real_lock(name)

    with real_lock("kube.lock"):
        lc.store._lock = signalling_lock
        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=lambda: lc.archive("kube"))
        t1.start()
        t2.start()
        assert asking.acquire(timeout=5) and asking.acquire(timeout=5)
        # both are inside (or about to enter) the lock wait; neither can finish while we hold it
        t1.join(0.05)
        t2.join(0.05)
        assert t1.is_alive() and t2.is_alive()
        assert (lc.root / "notebooks" / "kube").exists()
    t1.join()
    t2.join()
    ws = lc.root / "notebooks" / "kube"
    assert not ws.exists() or (ws / ".okf" / "notebook.yaml").is_file()
    assert len(list((lc.root / "_archive").iterdir())) == 1


def test_restore_respects_max_notebooks(tmp_path):
    lc = make_lc(tmp_path / "root", max_notebooks=1)
    lc.create_notebook(H, **args("kube"))
    lc.archive("kube")
    lc.create_notebook(H, **other("other", "other"))
    with pytest.raises(LimitExceeded):
        lc.restore("kube")


# -- adopt ---------------------------------------------------------------------------
def make_bundle(path, with_yaml=False, bad=False):
    (path / "decisions").mkdir(parents=True)
    (path / "decisions" / "use-argocd.md").write_text(
        "---\ntype: Decision\ntitle: Use ArgoCD\ndescription: why\n---\nWe use ArgoCD as decided.\n"
    )
    (path / "decisions" / "broken.md").write_text(
        "---\ntype: Nonsense\ntitle: B\n---\nx\n" if bad else
        "---\ntype: Decision\ntitle: B\ndescription: d\n---\nSee /decisions/gone.md for details.\n"
    )
    (path / "index.md").write_text("# hand\n")
    if with_yaml:
        (path / ".okf").mkdir()
        (path / ".okf/notebook.yaml").write_text(
            "name: Old bundle\ndescription: An existing okf-init bundle with plenty of text.\n"
            "scope: everything\ntypes: [Decision]\nstatus: proposed\n"
        )
    return path


def test_adopt_adds_notebook_yaml_when_missing(lc, tmp_path):
    src = make_bundle(tmp_path / "myproj")
    res = lc.adopt(src)
    assert (res.status, res.slug) == ("created", "myproj")
    reg = Registry(lc.root)
    d = reg.describe("myproj")
    assert d.status == "active" and [t.name for t in d.types] == ["Decision"]
    assert d.note_count == 2
    assert (lc.root / "notebooks/myproj/log.md").is_file()
    assert src.is_dir() and (src / "decisions/use-argocd.md").is_file()  # source untouched
    assert not (src / ".okf").exists()


def test_adopt_keeps_existing_yaml_and_forces_active(lc, tmp_path):
    lc.adopt(make_bundle(tmp_path / "x", with_yaml=True), slug="oldb")
    m = meta(lc.root, "notebooks", "oldb")
    assert m["status"] == "active" and m["name"] == "Old bundle"


def test_adopt_rejects_invalid_bundle_listing_errors_and_leaves_nothing(lc, tmp_path):
    with pytest.raises(Invalid) as e:
        lc.adopt(make_bundle(tmp_path / "bad", bad=True, with_yaml=True))
    assert {"type", "description"} <= {v.rule for v in e.value.violations}
    assert not (lc.root / "notebooks" / "bad").exists()
    assert not [p for p in (lc.root / ".tmp").iterdir() if p.is_dir()]


def test_adopt_rejects_taken_slug_reserved_and_symlinks(lc, tmp_path):
    lc.create_notebook(H, **args("kube"))
    src = make_bundle(tmp_path / "b")
    with pytest.raises(Invalid):
        lc.adopt(src, slug="kube")
    with pytest.raises(Invalid):
        lc.adopt(src, slug="admin")
    (src / "link.md").symlink_to(tmp_path / "b" / "index.md")
    with pytest.raises(Invalid):
        lc.adopt(src, slug="fresh")
    with pytest.raises(Invalid):
        lc.adopt(tmp_path / "missing", slug="fresh")


# -- types -----------------------------------------------------------------------------
def test_type_define_direct_adds_type_template_and_dir(lc):
    lc.create_notebook(H, **args("kube"))
    r = lc.define_type(actor(policy="direct"), "kube", name="Runbook",
                       description="Ops steps", required=["severity"], fields=["severity"])
    assert (r.status, r.name) == ("defined", "Runbook")
    d = Registry(lc.root).describe("kube")
    t = next(t for t in d.types if t.name == "Runbook")
    assert (t.dir, t.description) == ("runbooks", "Ops steps") and "severity" in t.fields
    assert lc.registry.types(lc.root / "notebooks/kube")["Runbook"].required == ("severity",)
    note(lc, type="Runbook", title="Restart", severity="high", actor="claude-code")
    assert (lc.root / "notebooks/kube/runbooks/restart.md").is_file()


def test_type_define_policies(lc):
    lc.create_notebook(H, **args("kube"))
    with pytest.raises(Forbidden):
        lc.define_type(actor(policy="off"), "kube", name="Runbook", description="d")
    with pytest.raises(Forbidden):
        lc.define_type(actor(policy="direct", perms=("read",)), "kube",
                       name="Runbook", description="d")
    r = lc.define_type(P, "kube", name="Runbook", description="Ops steps", rationale="need runbooks")
    assert r.status == "proposed"
    assert [t.name for t in Registry(lc.root).describe("kube").types] == [
        "Project", "Decision", "Playbook", "Term"
    ]
    f = lc.root / "_proposed" / "kube.type-Runbook.yaml"
    assert f.is_file()
    [it] = lc.pending()
    assert (it.kind, it.slug, it.name, it.author) == ("type", "kube", "Runbook", "claude-code")
    with pytest.raises(Invalid):  # rationale mandatory for a proposal
        lc.define_type(P, "kube", name="Other", description="d")
    with pytest.raises(Invalid):  # duplicate proposal
        lc.define_type(P, "kube", name="Runbook", description="d", rationale="again")


def test_type_proposal_approve_and_reject(lc):
    lc.create_notebook(H, **args("kube"))
    lc.define_type(P, "kube", name="Runbook", description="Ops", rationale="r")
    lc.define_type(P, "kube", name="Faq", description="Q and A", rationale="r")
    lc.approve_type("kube", "Runbook")
    assert "Runbook" in [t.name for t in Registry(lc.root).describe("kube").types]
    lc.reject_type("kube", "Faq", "not needed")
    assert "Faq" not in [t.name for t in Registry(lc.root).describe("kube").types]
    assert lc.pending() == []
    with pytest.raises(NotebookNotFound):
        lc.approve_type("kube", "Faq")


def test_type_define_validation_errors(lc):
    lc.create_notebook(H, **args("kube"))
    d = actor(policy="direct")
    with pytest.raises(Invalid) as e:  # existing, case-insensitive
        lc.define_type(d, "kube", name="decision", description="d")
    assert "types" in {v.rule for v in e.value.violations}
    with pytest.raises(Invalid):
        lc.define_type(d, "kube", name="../x", description="d")
    with pytest.raises(Invalid):
        lc.define_type(d, "kube", name="Fine", description=" ")
    with pytest.raises(NotebookNotFound):
        lc.define_type(d, "missing", name="Fine", description="d")
    lc.create_notebook(P, **other("wip", "wip"))
    with pytest.raises(Invalid):
        lc.define_type(d, "wip", name="Fine", description="d")


def test_type_delete_refused_when_notes_exist(lc):
    lc.create_notebook(H, **args("kube"))
    note(lc)
    with pytest.raises(Invalid) as e:
        lc.delete_type("kube", "Decision")
    assert "1 concept" in str(e.value)
    assert "Decision" in [t.name for t in Registry(lc.root).describe("kube").types]
    r = lc.delete_type("kube", "Playbook")
    assert r.status == "deleted"
    assert "Playbook" not in [t.name for t in Registry(lc.root).describe("kube").types]
    assert not (lc.root / "notebooks/kube/playbooks").exists()
    assert not (lc.root / "notebooks/kube/.okf/templates/Playbook.md").exists()
    with pytest.raises(Invalid):  # unknown
        lc.delete_type("kube", "Nope")


def test_type_rename_refused_when_notes_exist_else_keeps_dir(lc):
    lc.create_notebook(H, **args("kube"))
    note(lc)
    with pytest.raises(Invalid):
        lc.rename_type("kube", "Decision", "Choice")
    lc.rename_type("kube", "Playbook", "Procedure")
    d = Registry(lc.root).describe("kube")
    t = next(t for t in d.types if t.name == "Procedure")
    assert t.dir == "playbooks" and t.description  # dir fixed, description kept
    assert (lc.root / "notebooks/kube/.okf/templates/Procedure.md").is_file()
    assert (lc.root / "notebooks/kube/.okf/templates/Playbook.md").exists() is False
    with pytest.raises(Invalid):  # name clash
        lc.rename_type("kube", "Term", "decision")
    with pytest.raises(Invalid):
        lc.rename_type("kube", "Term", "bad/name")
    note(lc, type="Procedure", title="Deploy")  # usable immediately
    assert (lc.root / "notebooks/kube/playbooks/deploy.md").is_file()


# -- marking (story 26) ---------------------------------------------------------------------
def test_mark_status_and_verify_are_human_only_paths(lc):
    lc.create_notebook(H, **args("kube"))
    note(lc)
    cid = "/decisions/use-argocd"
    lc.mark_concept("kube", cid, status="stable")
    c = lc.store.read_concept("kube", cid)
    assert c.frontmatter["status"] == "stable" and "verified" not in c.frontmatter
    lc.mark_concept("kube", cid, verify=True)
    c = lc.store.read_concept("kube", cid)
    assert c.frontmatter["verified"] and c.frontmatter["status"] == "stable"
    lc.mark_concept("kube", cid, status="deprecated")
    assert lc.store.read_concept("kube", cid).frontmatter["status"] == "deprecated"
    # an agent edit afterwards clears verified but cannot un-deprecate
    res = lc.store.append_concept("kube", cid, text="more\n", actor="claude-code")
    assert res.concept.frontmatter["status"] == "deprecated"
    assert "verified" not in res.concept.frontmatter


def test_mark_rejects_bad_input(lc):
    lc.create_notebook(H, **args("kube"))
    note(lc)
    with pytest.raises(Invalid):
        lc.mark_concept("kube", "/decisions/use-argocd", status="verified")
    with pytest.raises(Invalid):
        lc.mark_concept("kube", "/decisions/use-argocd")
    with pytest.raises(NotFound):
        lc.mark_concept("kube", "/decisions/missing", verify=True)


# -- validate (story 28) ------------------------------------------------------------------------
def test_validate_audits_hand_edits_with_broken_links_as_warnings(lc):
    lc.create_notebook(H, **args("kube"))
    note(lc)
    rep = lc.validate(run_okflint=False)
    assert rep.ok and rep.notebooks == ["kube"]
    d = lc.root / "notebooks/kube/decisions"
    (d / "hand.md").write_text(
        "---\ntype: Decision\ntitle: Hand\ndescription: d\n---\nSee /decisions/gone.md here ok.\n"
    )
    rep = lc.validate("kube", run_okflint=False)
    assert rep.ok
    assert any(f.violation.rule == "link" and f.violation.level == "warning"
               and f.cid == "/decisions/hand" for f in rep.findings)
    (d / "bad.md").write_text("---\ntype: Weird\ntitle: Bad\ndescription: d\n---\nlong enough body text\n")
    (d / "secret.md").write_text(
        "---\ntype: Decision\ntitle: S\ndescription: d\n---\n-----BEGIN RSA PRIVATE KEY-----\n"
    )
    rep = lc.validate(run_okflint=False)
    assert not rep.ok
    assert {(f.cid, f.violation.rule) for f in rep.errors} >= {
        ("/decisions/bad", "type"), ("/decisions/secret", "secret")
    }


def test_validate_unknown_notebook_and_structure(lc):
    with pytest.raises(NotebookNotFound):
        lc.validate("nope")
    lc.create_notebook(H, **args("kube"))
    (lc.root / "notebooks/kube/index.md").unlink()
    rep = lc.validate("kube", run_okflint=False)
    assert any(f.violation.rule == "bundle" for f in rep.errors)


def test_validate_runs_okflint_when_installed(lc, tmp_path, monkeypatch):
    lc.create_notebook(H, **args("kube"))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "okflint"
    exe.write_text("#!/bin/sh\necho linted $1\nexit 1\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    rep = lc.validate(run_okflint=True)
    assert "linted" in rep.okflint and rep.okflint_ok is False and not rep.ok
    assert lc.validate(run_okflint=False).okflint is None


# -- startup tmp cleanup -------------------------------------------------------------------------
def test_cleanup_tmp_removes_only_entries_older_than_an_hour(tmp_path):
    tmp = tmp_path / ".tmp"
    old, new = tmp / "old-uuid", tmp / "new-uuid"
    for d in (old, new):
        (d / "sub").mkdir(parents=True)
        (d / "sub" / "f").write_text("x")
    part = tmp / "x.part"
    part.write_text("x")
    lock = tmp / "registry.lock"
    lock.write_text("")
    past = time.time() - 2 * 3600
    for p in (old, part, lock):
        os.utime(p, (past, past))
    removed = cleanup_tmp(tmp_path)
    assert sorted(removed) == ["old-uuid", "x.part"]
    assert not old.exists() and not part.exists()
    assert new.is_dir() and lock.exists()
    assert cleanup_tmp(tmp_path / "nowhere") == []


def test_limit_applies_to_adopt(tmp_path):
    lc = make_lc(tmp_path / "root", max_notebooks=1)
    lc.create_notebook(H, **args("kube"))
    with pytest.raises(LimitExceeded):
        lc.adopt(make_bundle(tmp_path / "b"), slug="second")


def test_lifecycle_from_config_wires_limits_and_presets(tmp_path):
    from okf_notebooks.config import load_config
    from okf_notebooks.lifecycle import Lifecycle

    pdir = tmp_path / "presets"
    pdir.mkdir()
    (pdir / "eng.yaml").write_text("types:\n  - {name: Runbook, description: Ops}\n")
    cfgp = tmp_path / "c.yaml"
    cfgp.write_text(
        f"root: {tmp_path / 'r'}\npresets_dir: {pdir}\nlimits:\n  max_notebooks: 1\n"
        "notebook_creation:\n  slug_pattern: '^[a-z]{3,10}$'\n  reserved_slugs: [kube]\n"
        "git:\n  enabled: false\n"
    )
    lc = Lifecycle.from_config(load_config(cfgp))
    with pytest.raises(Invalid):
        lc.create_notebook(H, **args("kube", preset="eng"))  # reserved
    with pytest.raises(Invalid):
        lc.create_notebook(H, **args("has-dash", preset="eng"))  # pattern
    lc.create_notebook(H, **args("okslug", preset="eng"))
    assert Registry(tmp_path / "r").describe("okslug").types[0].name == "Runbook"
    with pytest.raises(LimitExceeded):
        lc.create_notebook(H, **other("second", "zeta"))




def test_every_transition_is_committed_and_tree_stays_clean(tmp_path):
    import subprocess

    from okf_notebooks.lifecycle import Lifecycle

    root = tmp_path / "root"
    lc = Lifecycle(Store(root, git=True))

    def clean():
        out = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                             capture_output=True, text=True, check=True).stdout
        assert out.strip() == "", out

    lc.create_notebook(P, **args("kube"))
    clean()
    lc.approve("kube")
    clean()
    lc.define_type(P, "kube", name="Runbook", description="Ops", rationale="r")
    clean()
    lc.approve_type("kube", "Runbook")
    clean()
    lc.rename_type("kube", "Runbook", "Guide")
    clean()
    lc.delete_type("kube", "Guide")
    clean()
    lc.archive("kube")
    clean()
    lc.restore("kube")
    clean()
    lc.create_notebook(P, **other("zeta", "zeta"))
    lc.reject("zeta", "no")
    clean()
    lc.adopt(make_bundle(tmp_path / "bundle"), slug="adopted")
    clean()
    log = subprocess.run(["git", "-C", str(root), "log", "--format=%an"],
                         capture_output=True, text=True, check=True).stdout.split()
    assert "human" in log and "claude-code" in log


def test_verify_and_mark_keep_the_authors_generated_stamp(lc):
    lc.create_notebook(H, **args("kube"))
    note(lc)
    cid = "/decisions/use-argocd"
    before = lc.store.read_concept("kube", cid).frontmatter["generated"]
    lc.mark_concept("kube", cid, verify=True)
    lc.mark_concept("kube", cid, status="stable")
    c = lc.store.read_concept("kube", cid)
    assert c.frontmatter["generated"] == before
    assert c.frontmatter["verified"] and c.frontmatter["status"] == "stable"


# -- file modes: lifecycle files are 0644 (as before the shared helper) -------------
def _mode(p):
    return os.stat(p).st_mode & 0o777


def test_lifecycle_files_keep_mode_0644_through_create_approve_archive_restore(tmp_path):
    lc = make_lc(tmp_path / "root")
    lc.create_notebook(P, **args("kube"))
    prop = lc.root / "_proposed" / "kube"
    for f in ("log.md", "index.md", ".okf/notebook.yaml"):
        assert _mode(prop / f) == 0o644, f
    lc.approve("kube")
    ws = lc.root / "notebooks" / "kube"
    for f in ("log.md", "index.md", ".okf/notebook.yaml"):
        assert _mode(ws / f) == 0o644, f
    lc.archive("kube")
    (arch,) = (lc.root / "_archive").iterdir()
    for f in ("log.md", "index.md", ".okf/notebook.yaml"):
        assert _mode(arch / f) == 0o644, f
    lc.restore("kube")
    for f in ("log.md", "index.md", ".okf/notebook.yaml"):
        assert _mode(ws / f) == 0o644, f


def test_type_proposal_and_rejection_files_are_0644(tmp_path):
    lc = make_lc(tmp_path / "root")
    lc.create_notebook(H, **args("kube"))
    lc.define_type(P, "kube", name="Runbook", description="d", rationale="needed")
    (f,) = (lc.root / "_proposed").glob("kube.type-*.yaml")
    assert _mode(f) == 0o644
    lc.reject_type("kube", "Runbook", "no")
    (r,) = (lc.root / "_archive").glob("kube.type-*.rejected-*.yaml")
    assert _mode(r) == 0o644


def test_concept_files_and_token_file_keep_their_modes(tmp_path):
    from okf_notebooks.auth import TokenStore

    lc = make_lc(tmp_path / "root")
    lc.create_notebook(H, **args("kube"))
    c = note(lc).concept
    path = lc.root / "notebooks" / "kube" / (c.id.lstrip("/") + ".md")
    assert _mode(path) == 0o600  # store files were private before the shared helper too
    ts = TokenStore(tmp_path / ".auth" / "tokens.json")
    ts.create("claude-code", "laptop")
    assert _mode(ts.path) == 0o600


def test_bundle_metadata_modes_do_not_depend_on_the_last_writer(tmp_path):
    lc = make_lc(tmp_path / "root")
    lc.create_notebook(P, **args("kube"))
    lc.approve("kube")
    lc.define_type(H, "kube", name="Runbook", description="d")
    ws = lc.root / "notebooks" / "kube"
    c = note(lc).concept  # an agent write after the lifecycle writes
    for f in ("log.md", "index.md", ".okf/notebook.yaml"):
        assert _mode(ws / f) == 0o644, f
    assert _mode(ws / (c.id.lstrip("/") + ".md")) == 0o600
    lc.define_type(H, "kube", name="Other", description="d")  # and the other way round
    for f in ("log.md", "index.md", ".okf/notebook.yaml"):
        assert _mode(ws / f) == 0o644, f


# -- F1: bundle metadata modes do not depend on the umask --------------------------
@pytest.fixture
def umask077():
    old = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(old)


def _meta_files(bundle):
    fixed = [bundle / "log.md", bundle / "index.md"]
    return fixed + [p for p in (bundle / ".okf").rglob("*") if p.is_file()]


def _assert_public(bundle, templates=True):
    files = _meta_files(bundle)
    assert {p.name for p in files} >= {
        "log.md", "index.md", "notebook.yaml", "okf-base.yaml"
    }
    assert not templates or any(p.parent.name == "templates" for p in files)
    assert {str(p.relative_to(bundle)): _mode(p) for p in files if _mode(p) != 0o644} == {}


def test_proposed_notebook_metadata_is_0644_under_a_strict_umask(tmp_path, umask077):
    lc = make_lc(tmp_path / "root")
    lc.create_notebook(P, **args("kube"))
    _assert_public(lc.root / "_proposed" / "kube")


def test_direct_notebook_metadata_is_0644_under_a_strict_umask(tmp_path, umask077):
    lc = make_lc(tmp_path / "root")
    lc.create_notebook(actor(policy="direct"), **args("kube"))
    _assert_public(lc.root / "notebooks" / "kube")


@pytest.mark.parametrize("with_yaml", [False, True])
def test_adopted_notebook_metadata_is_0644_under_a_strict_umask(tmp_path, umask077, with_yaml):
    lc = make_lc(tmp_path / "root")
    src = make_bundle(tmp_path / "ext", with_yaml=with_yaml)
    for p in src.rglob("*"):
        if p.is_file():
            p.chmod(0o600)
    lc.adopt(src, slug="ext")
    _assert_public(lc.root / "notebooks" / "ext", templates=False)


def _okf_files(bundle):
    return [p for p in (bundle / ".okf").rglob("*") if p.is_file()]


def _all_public(bundle):
    files = _meta_files(bundle)
    assert {str(p.relative_to(bundle)): _mode(p) for p in files if _mode(p) != 0o644} == {}


def test_type_changes_keep_every_okf_file_0644_under_a_strict_umask(tmp_path, umask077):
    lc = make_lc(tmp_path / "root")
    lc.create_notebook(H, **args("kube"))
    ws = lc.root / "notebooks" / "kube"
    lc.define_type(actor(policy="direct"), "kube", name="Runbook", description="d")
    assert (ws / ".okf" / "templates" / "Runbook.md").is_file()
    _all_public(ws)
    lc.define_type(P, "kube", name="Faq", description="d", rationale="needed")
    lc.approve_type("kube", "Faq")
    assert (ws / ".okf" / "templates" / "Faq.md").is_file()
    _all_public(ws)
    lc.rename_type("kube", "Faq", "Question")
    assert (ws / ".okf" / "templates" / "Question.md").is_file()
    _all_public(ws)
    lc.delete_type("kube", "Question")
    _all_public(ws)
