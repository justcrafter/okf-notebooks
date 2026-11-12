"""CLI: notebook/type/verify/mark/validate commands against a tmp root."""

import os
import subprocess
import sys
import time

import pytest
from conftest import cli, free_port, write_config
from lifecycle_helpers import DESC, SCOPE, actor, args, meta

from okf_notebooks.config import load_config
from okf_notebooks.lifecycle import Lifecycle
from okf_notebooks.registry import Registry


@pytest.fixture
def env(tmp_path):
    cfg = write_config(tmp_path, free_port(), "git:\n  enabled: false\n")
    root = tmp_path / "data"

    def run(*a, ok=True):
        r = cli(*a, "--config", str(cfg))
        if ok:
            assert r.returncode == 0, r.stderr + r.stdout
        return r

    return run, root, cfg


def create(run, slug="kube", **kw):
    extra = []
    for k, v in kw.items():
        extra += [f"--{k.replace('_', '-')}", v]
    return run("notebook", "create", slug, "--description", DESC, "--scope", SCOPE,
               *(extra or ["--preset", "core"]), ok=kw.pop("ok", True))


def lc_of(cfg):
    return Lifecycle.from_config(load_config(cfg))


def propose(cfg, slug="kube", who="claude-code"):
    return lc_of(cfg).create_notebook(actor(who, policy="proposal"), **args(slug))


def test_create_active_via_cli_with_preset(env):
    run, root, _ = env
    r = create(run, preset="core")
    assert "notebooks/kube" in r.stdout
    assert Registry(root).describe("kube").status == "active"
    assert meta(root, "notebooks", "kube")["created"]["by"] == "human"


def test_create_cli_with_types_file_and_errors_listed(env, tmp_path):
    run, root, _ = env
    tf = tmp_path / "types.yaml"
    tf.write_text("- {name: Runbook, description: Ops steps}\n")
    run("notebook", "create", "ops", "--description", DESC, "--scope", SCOPE,
        "--types-file", str(tf))
    assert Registry(root).describe("ops").types[0].name == "Runbook"
    r = run("notebook", "create", "Bad", "--description", "short", "--scope", "x",
            "--preset", "nope", ok=False)
    assert r.returncode == 1
    for rule in ("slug:", "description:", "preset:"):
        assert rule in r.stderr
    assert "[invalid]" in r.stderr


def test_create_cli_similar_exists_then_confirm_distinct(env):
    run, root, _ = env
    create(run, preset="core")
    r = run("notebook", "create", "kube2", "--description", DESC, "--scope", SCOPE,
            "--preset", "core", "--name", "Kubernetes platform", ok=False)
    assert r.returncode == 1 and "similar_exists" in r.stderr and "candidate kube" in r.stderr
    run("notebook", "create", "kube2", "--description", DESC, "--scope", SCOPE,
        "--preset", "core", "--name", "Kubernetes platform", "--confirm-distinct")
    assert (root / "notebooks/kube2").is_dir()


def test_pending_approve_flow(env):
    run, root, cfg = env
    propose(cfg)
    out = run("notebook", "pending").stdout
    assert "kube" in out and "claude-code" in out and "No existing notebook" in out
    run("notebook", "approve", "kube")
    assert Registry(root).describe("kube").status == "active"
    assert run("notebook", "pending").stdout.strip() == ""
    assert run("notebook", "approve", "kube", ok=False).returncode == 1


def test_reject_with_reason_visible_via_describe(env):
    run, root, cfg = env
    propose(cfg)
    r = run("notebook", "reject", "kube", ok=False)  # --reason is mandatory
    assert r.returncode == 2
    run("notebook", "reject", "kube", "--reason", "duplicate of infra")
    d = Registry(root).describe("kube")
    assert (d.status, d.rejection_reason) == ("rejected", "duplicate of infra")


def test_archive_restore_and_reserved_slug(env):
    run, root, _ = env
    create(run, preset="core")
    run("notebook", "archive", "kube")
    assert Registry(root).describe("kube").status == "archived"
    r = run("notebook", "create", "kube", "--description", DESC, "--scope", SCOPE,
            "--preset", "core", ok=False)
    assert "already taken" in r.stderr
    run("notebook", "restore", "kube")
    assert Registry(root).describe("kube").status == "active"
    assert run("notebook", "restore", "kube", ok=False).returncode == 1


def test_adopt_via_cli(env, tmp_path):
    run, root, _ = env
    b = tmp_path / "okfb"
    (b / "terms").mkdir(parents=True)
    (b / "terms" / "etag.md").write_text(
        "---\ntype: Term\ntitle: ETag\ndescription: concurrency token\n---\nA token for CAS.\n"
    )
    run("notebook", "adopt", str(b), "--slug", "adopted")
    assert Registry(root).describe("adopted").note_count == 1
    bad = tmp_path / "badb"
    (bad / "terms").mkdir(parents=True)
    (bad / "terms" / "x.md").write_text("no frontmatter\n")
    r = run("notebook", "adopt", str(bad), ok=False)
    assert r.returncode == 1 and "yaml:" in r.stderr


def test_type_delete_rename_refused_with_notes_then_allowed(env):
    run, root, cfg = env
    create(run, preset="core")
    lc = lc_of(cfg)
    lc.store.write_concept("kube", type="Term", title="ETag", frontmatter={"description": "d"},
                           body="A concurrency token for writes.\n", actor="claude-code")
    for argv in (("type", "delete", "kube", "Term"), ("type", "rename", "kube", "Term", "Word")):
        r = run(*argv, ok=False)
        assert r.returncode == 1 and "1 concept" in r.stderr
    run("type", "rename", "kube", "Playbook", "Procedure")
    run("type", "delete", "kube", "Project")
    names = [t.name for t in Registry(root).describe("kube").types]
    assert names == ["Decision", "Procedure", "Term"]


def test_type_proposal_approve_reject_cli(env):
    run, root, cfg = env
    create(run, preset="core")
    lc = lc_of(cfg)
    p = actor(policy="proposal")
    lc.define_type(p, "kube", name="Runbook", description="Ops", rationale="r")
    lc.define_type(p, "kube", name="Faq", description="Q", rationale="r")
    assert "type Runbook" in run("notebook", "pending").stdout
    run("type", "approve", "kube", "Runbook")
    run("type", "reject", "kube", "Faq", "--reason", "no")
    names = [t.name for t in Registry(root).describe("kube").types]
    assert "Runbook" in names and "Faq" not in names


def test_verify_and_mark_via_cli(env):
    run, _, cfg = env
    create(run, preset="core")
    lc_of(cfg).store.write_concept(
        "kube", type="Decision", title="Use ArgoCD", frontmatter={"description": "d"},
        body="We use ArgoCD as decided.\n", actor="claude-code")
    cid = "/decisions/use-argocd"
    run("mark", "kube", cid, "--status", "stable")
    run("verify", "kube", cid)
    fm = lc_of(cfg).store.read_concept("kube", cid).frontmatter
    assert fm["status"] == "stable" and fm["verified"]
    assert run("mark", "kube", cid, "--status", "bogus", ok=False).returncode == 1
    assert run("verify", "kube", "/decisions/none", ok=False).returncode == 1


def test_validate_command_exit_codes(env):
    run, root, _ = env
    create(run, preset="core")
    r = run("validate", "--no-okflint")
    assert "0 error(s)" in r.stderr + r.stdout
    (root / "notebooks/kube/terms/hand.md").write_text(
        "---\ntype: Term\ntitle: H\ndescription: d\n---\nSee /terms/gone.md for the rest.\n"
    )
    r = run("validate", "--notebook", "kube", "--no-okflint")
    assert "warning" in r.stdout and "link" in r.stdout
    (root / "notebooks/kube/terms/bad.md").write_text("no frontmatter at all\n")
    r = run("validate", "--no-okflint", ok=False)
    assert r.returncode == 1 and "error" in r.stdout and "bad" in r.stdout
    assert run("validate", "--notebook", "nope", ok=False).returncode == 1


def test_two_cli_processes_one_slug_exactly_one_wins(env):
    _, root, cfg = env
    cmd = [sys.executable, "-m", "okf_notebooks", "notebook", "create", "race", "--description",
           DESC, "--scope", SCOPE, "--preset", "core", "--config", str(cfg)]
    procs = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(2)]
    for p in procs:
        p.communicate(timeout=60)
    assert sorted(p.returncode for p in procs) == [0, 1]
    assert [d.name for d in (root / "notebooks").iterdir()] == ["race"]


def test_server_start_cleans_stale_tmp(tmp_path, server):
    tmp = tmp_path / "data" / ".tmp"
    old, new = tmp / "stale-uuid", tmp / "fresh-uuid"
    for d in (old, new):
        d.mkdir(parents=True)
        (d / "f").write_text("x")
    past = time.time() - 2 * 3600
    os.utime(old, (past, past))
    server("git:\n  enabled: false\n")
    assert not old.exists() and new.is_dir()
