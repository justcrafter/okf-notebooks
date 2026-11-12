import json
import subprocess
import sys
import textwrap
import time

import filelock
import pytest

from okf_notebooks.store import Busy, Store


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _write(
    store, title="Deploy", actor="claude-code", body="a body long enough to pass\n"
):
    return store.write_concept(
        "notes",
        type="Playbook",
        title=title,
        frontmatter={"description": "d"},
        body=body,
        actor=actor,
    )


def test_write_appends_to_log_md(root):
    _write(Store(root, git=False), actor="opencode")
    log = (root / "notebooks/notes/log.md").read_text()
    assert "opencode" in log and "/playbooks/deploy" in log


def test_log_md_keeps_history_across_writes(root):
    store = Store(root, git=False)
    c = _write(store).concept
    store.append_concept("notes", c.id, text="more more more more\n", actor="human")
    lines = [
        ln
        for ln in (root / "notebooks/notes/log.md").read_text().splitlines()
        if ln.startswith("- ")
    ]
    assert len(lines) == 2 and "human" in lines[1]


def test_busy_when_notebook_lock_is_held(root):
    (root / ".tmp").mkdir()
    with filelock.FileLock(root / ".tmp" / "notes.lock"), pytest.raises(Busy) as e:
        _write(Store(root, git=False, lock_timeout=0.2))
    assert e.value.code == "busy"
    assert not (root / "notebooks/notes/playbooks").exists()


def test_other_notebook_lock_does_not_block(root):
    (root / ".tmp").mkdir()
    with filelock.FileLock(root / ".tmp" / "other.lock"):
        _write(Store(root, git=False, lock_timeout=0.2))


def test_write_is_committed_by_actor_with_notebook_message(root):
    res = _write(Store(root), actor="opencode")
    assert res.warnings == []
    assert git(root, "log", "-1", "--format=%an") == "opencode"
    assert git(root, "log", "-1", "--format=%s").startswith("notebook(notes):")
    changed = git(root, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert "notebooks/notes/playbooks/deploy.md" in changed
    assert "notebooks/notes/log.md" in changed
    assert (
        git(
            root,
            "status",
            "--porcelain",
            "--",
            "notebooks/notes/playbooks",
            "notebooks/notes/log.md",
        )
        == ""
    )


def test_each_write_is_one_commit_and_ignores_tmp(root):
    store = Store(root)
    c = _write(store).concept
    store.update_concept(
        "notes", c.id, base_etag=c.etag, body="n" * 25 + "\n", actor="human"
    )
    store.append_concept("notes", c.id, text="z" * 25 + "\n", actor="human")
    assert git(root, "rev-list", "--count", "HEAD") == "3"
    assert ".tmp/" in (root / ".gitignore").read_text()
    assert ".index/" in (root / ".gitignore").read_text()
    assert git(root, "ls-files", ".tmp") == ""


def test_git_failure_keeps_the_write_and_returns_warning(root):
    (root / ".git").write_text("not a repository")
    res = _write(Store(root))
    assert res.warnings and "git" in res.warnings[0]
    assert (
        (root / "notebooks/notes/playbooks/deploy.md")
        .read_text()
        .endswith("a body long enough to pass\n")
    )


WORKER = textwrap.dedent(
    """
    import json, sys, time, pathlib
    from okf_notebooks.store import Store, Conflict
    root, cid, etag, who, go = sys.argv[1:]
    pathlib.Path(go + "." + who + ".ready").touch()  # handshake: imports done, waiting
    while not pathlib.Path(go).exists():
        time.sleep(0.001)
    try:
        Store(root).update_concept("notes", cid, base_etag=etag, body=who + "\\n", actor=who)
        print(json.dumps({"who": who, "result": "ok"}))
    except Conflict:
        print(json.dumps({"who": who, "result": "conflict"}))
    """
)


def test_two_processes_updating_same_file_yield_exactly_one_conflict(root, tmp_path):
    c = _write(Store(root)).concept
    go = tmp_path / "go"
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", WORKER, str(root), c.id, c.etag, who, str(go)],
            stdout=subprocess.PIPE,
            text=True,
        )
        for who in ("alice", "bob")
    ]
    deadline = time.monotonic() + 30
    while not all((tmp_path / f"go.{who}.ready").exists() for who in ("alice", "bob")):
        assert time.monotonic() < deadline, "workers never signalled readiness"
        time.sleep(0.01)
    go.touch()
    results = [json.loads(p.communicate(timeout=30)[0]) for p in procs]
    assert sorted(r["result"] for r in results) == ["conflict", "ok"]
    winner = next(r["who"] for r in results if r["result"] == "ok")
    assert Store(root, git=False).read_concept("notes", c.id).body == winner + "\n"
    assert (
        git(
            root,
            "status",
            "--porcelain",
            "--",
            "notebooks/notes/playbooks",
            "notebooks/notes/log.md",
        )
        == ""
    )
