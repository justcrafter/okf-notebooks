"""git remote background push, sync, doctor.

Remotes are always local bare repos under tmp_path; no network.
"""

import subprocess

import pytest
from conftest import cli

from okf_notebooks.config import ConfigError, load_config
from okf_notebooks.gitremote import auth_env, check_remote_url
from okf_notebooks.store import Store


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def remote(tmp_path):
    r = tmp_path / "notebooks-private.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(r)], check=True)
    return r


def _write(store, title="Deploy"):
    return store.write_concept(
        "notes", type="Playbook", title=title,
        frontmatter={"description": "How to deploy"},
        body="Steps to deploy the service safely.\n",
        actor="a",
    )


def test_commit_is_pushed_in_background(root, remote):
    store = Store(root, remote=str(remote))
    _write(store)
    store.wait_push()
    assert git(remote, "rev-parse", "main") == git(root, "rev-parse", "HEAD")


def test_remote_down_warns_and_keeps_write(root, tmp_path):
    store = Store(root, remote=str(tmp_path / "missing.git"))
    res = _write(store)
    store.wait_push()
    assert (root / "notebooks/notes/playbooks/deploy.md").exists()
    assert store.push_warning and "push failed" in store.push_warning
    # the failure surfaces as a warning on the next write
    res2 = _write(store, "Other")
    assert any("push failed" in w for w in res2.warnings)
    assert res.concept.id == "/playbooks/deploy"


def test_write_does_not_wait_for_push(root, remote, monkeypatch):
    import threading

    import okf_notebooks.gitremote as gr

    gate = threading.Event()
    real = gr.push

    def slow(*a, **kw):
        gate.wait(10)
        return real(*a, **kw)

    monkeypatch.setattr(gr, "push", slow)
    store = Store(root, remote=str(remote))
    _write(store)  # returns while push is blocked
    assert (
        subprocess.run(
            ["git", "-C", str(remote), "rev-parse", "main"],
            capture_output=True,
            check=False,
        ).returncode
        != 0
    )
    gate.set()
    store.wait_push()
    assert git(remote, "rev-parse", "main") == git(root, "rev-parse", "HEAD")


def test_sync_pushes_accumulated_commits_fast_forward(root, remote, tmp_path):
    down = Store(root, remote=str(tmp_path / "missing.git"))
    _write(down, "One")
    _write(down, "Two")
    down.wait_push()
    r = cli("sync", "--config", _cfg(tmp_path, root, remote))
    assert r.returncode == 0, r.stderr
    assert git(remote, "rev-parse", "main") == git(root, "rev-parse", "HEAD")
    # second push is a fast-forward on top of existing history
    _write(Store(root, git=True), "Three")
    r = cli("sync", "--config", _cfg(tmp_path, root, remote))
    assert r.returncode == 0, r.stderr
    assert git(remote, "rev-list", "--count", "main") == git(
        root, "rev-list", "--count", "HEAD"
    )


def test_sync_fails_on_diverged_remote(root, remote, tmp_path):
    store = Store(root, remote=str(remote))
    _write(store)
    store.wait_push()
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True)
    (other / "x").write_text("x")
    git(other, "add", "x")
    git(other, "-c", "user.name=u", "-c", "user.email=u@x", "commit", "-qm", "x")
    git(other, "push", "-q", "origin", "HEAD:main")
    _write(Store(root), "Two")
    r = cli("sync", "--config", _cfg(tmp_path, root, remote))
    assert r.returncode == 1 and "error" in r.stderr


def test_sync_without_remote_configured(root, tmp_path):
    r = cli("sync", "--config", _cfg(tmp_path, root, None))
    assert r.returncode == 2 and "git.remote" in r.stderr


def test_doctor_commits_uncommitted_changes(root, remote, tmp_path):
    _write(Store(root))
    (root / "notebooks/notes/playbooks/hand.md").write_text("manual\n")
    (root / "notebooks/notes/log.md").write_text("tampered\n")
    r = cli("doctor", "--config", _cfg(tmp_path, root, remote))
    assert r.returncode == 0, r.stderr
    assert git(root, "status", "--porcelain") == ""
    assert "hand.md" in git(root, "show", "--stat", "HEAD")


def test_doctor_initialises_repo_and_ignores_tmp_and_index(root, tmp_path):
    (root / ".index").mkdir()
    (root / ".index/fts.sqlite").write_text("x")
    r = cli("doctor", "--config", _cfg(tmp_path, root, None))
    assert r.returncode == 0, r.stderr
    assert git(root, "status", "--porcelain") == ""
    assert ".index" not in git(root, "ls-files")


def test_commit_per_write_false_defers_commits_to_doctor(root, tmp_path):
    cfg = load_config(
        _cfg(tmp_path, root, None, extra="git:\n  commit_per_write: false\n")
    )
    store = Store.from_config(cfg)
    _write(store)
    assert not (root / ".git").exists()
    r = cli("doctor", "--config", _cfg(tmp_path, root, None))
    assert r.returncode == 0
    assert git(root, "status", "--porcelain") == ""


def test_git_disabled_in_config_means_no_repo(root, tmp_path):
    cfg = load_config(_cfg(tmp_path, root, None, extra="git:\n  enabled: false\n"))
    _write(Store.from_config(cfg))
    assert not (root / ".git").exists()


# -- git.remote validation --------------------------------------------------
@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/someone/okf-notebooks.git",
        "git@github.com:someone/okf-notebooks.git",
        "ssh://git@github.com/someone/mcp-okf-notebooks",
        "https://GitHub.com/Someone/OKF-Notebooks/",
    ],
)
def test_remote_pointing_at_code_repo_is_rejected(url):
    with pytest.raises(ValueError, match="public code repository"):
        check_remote_url(url, [])


def test_remote_in_configured_public_list_is_rejected():
    with pytest.raises(ValueError, match="public code repository"):
        check_remote_url("git@github.com:me/other.git", ["github.com/me/other"])


def test_remote_with_embedded_credentials_is_rejected():
    with pytest.raises(ValueError, match="credentials"):
        check_remote_url("https://user:secret@example.com/me/mem.git", [])


@pytest.mark.parametrize(
    "url",
    [
        "https://ghp_s3cr3tvalue@example.com/me/mem.git",
        "http://s3cr3tvalue@example.com/me/mem.git",
    ],
)
def test_remote_with_token_only_userinfo_is_rejected_without_echo(url):
    with pytest.raises(ValueError, match="credentials") as e:
        check_remote_url(url, [])
    assert "s3cr3tvalue" not in str(e.value)


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:me/agent-notebooks.git",
        "ssh://git@example.com/me/mem.git",
        "https://example.com/me/mem",
        "/srv/mem.git",
    ],
)
def test_private_looking_remotes_are_accepted(url):
    check_remote_url(url, [])


@pytest.mark.parametrize(
    "url",
    [
        "ssh://deploy@nas.local/srv/mem.git",
        "ssh://gitea@h/me/m.git",
        "ssh://GIT@h/me/m.git",
        "ssh+git://deploy@h/me/m.git",
        "deploy@h:me/mem.git",
        "https://git@h/me/m.git",
    ],
)
def test_ssh_usernames_are_not_credentials(url):
    check_remote_url(url, [])


@pytest.mark.parametrize(
    "url",
    [
        "ssh://deploy:pw@h/me/m.git",
        "ssh://git:pw@h/me/m.git",
        "https://git:pw@h/me/m.git",
        "https://deploy@h/me/m.git",
        "https://ghp_x@h/me/m.git",
        "https://%67hp_x@h/me/m.git",
        "https://git%3Apw@h/me/m.git",
        "http://deploy@h/me/m.git",
        "HTTPS://GHP_X@h/me/m.git",
    ],
)
def test_other_userinfo_stays_rejected(url):
    with pytest.raises(ValueError, match="credentials") as e:
        check_remote_url(url, [])
    assert "pw@" not in str(e.value) and "ghp_x" not in str(e.value)


@pytest.mark.parametrize(
    "url",
    [" https://tok@h/x/y", "https://tok@h/x/y\n", "\thttps://tok@h/x/y ", "\u00a0https://tok@h/x/y"],
)
def test_surrounding_whitespace_does_not_bypass_credential_check(url):
    with pytest.raises(ValueError, match="credentials"):
        check_remote_url(url, [])


def test_config_stores_the_stripped_remote(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(f"root: {tmp_path}\ngit:\n  remote: '  ssh://deploy@h/me/m.git '\n")
    assert load_config(p).git.remote == "ssh://deploy@h/me/m.git"


@pytest.mark.parametrize(
    "url",
    [
        "https://h/x/okf-notebooks.git?a=1",
        "https://h/x/okf-notebooks.git#frag",
        "https://h/x/okf-notebooks.git%2F",
        "https://h/x/okf-notebooks%2Egit",
        "https://h/x/okf%2Dnotebooks.git/",
        "https://h/x/mcp-okf-notebooks.git/?a=1#f",
        "https://h/x/okf-notebooks.git//",
    ],
)
def test_code_repo_name_check_ignores_query_fragment_and_encoding(url):
    with pytest.raises(ValueError, match="public code repository"):
        check_remote_url(url, [])


@pytest.mark.parametrize(
    "url",
    [
        "https://h/o/r?access_token=s3cr3tq",
        "https://h/o/r.git?x=1",
        "https://h/o/r#fragsecret",
        "ssh://deploy@h/o/r.git?x=1",
        "ssh://deploy@h/o/r.git#frag",
        "ssh+git://h/o/r?token=s3cr3tq",
        "deploy@h:o/r.git?x=1",
        "deploy@h:o/r.git#frag",
        "h:o/r.git?x=1",
        "file:///srv/mem.git?x=1",
        "file:///srv/mem.git#frag",
    ],
)
def test_query_or_fragment_is_rejected_without_echo(url):
    with pytest.raises(ValueError, match="query") as e:
        check_remote_url(url, [])
    msg = str(e.value)
    assert "s3cr3tq" not in msg and "fragsecret" not in msg and "x=1" not in msg


@pytest.mark.parametrize(
    "url",
    [
        "/srv/a#b/mem.git",
        "/srv/mem dir/a?b",
        "/srv/mem.git?",
        "rel/a#b/mem",
        "./x?y/mem.git",
        "/a:b#c",
        "./h:p?x",
        "a/b:c?d",
    ],
)
def test_local_filesystem_paths_may_contain_hash_and_question_mark(url):
    check_remote_url(url, [])


@pytest.mark.parametrize(
    "url",
    ["C:\\x?t", "user@host:path?token=s3cr3tq", "h:p#fragsecret", "host:path#a?b"],
)
def test_scp_like_and_drive_forms_reject_query_and_fragment_without_echo(url):
    with pytest.raises(ValueError, match="query") as e:
        check_remote_url(url, [])
    assert "s3cr3tq" not in str(e.value) and "fragsecret" not in str(e.value)


def test_config_rejects_public_remote(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        f"root: {tmp_path}\ngit:\n  remote: https://github.com/x/okf-notebooks.git\n"
    )
    with pytest.raises(ConfigError, match="public code repository"):
        load_config(p)


# -- auth ---------------------------------------------------------------------
def test_auth_env_ssh_key_and_token():
    env = auth_env(
        {"OKF_NOTEBOOKS_GIT_SSH_KEY": "/run/secrets/k", "OKF_NOTEBOOKS_GIT_TOKEN": "tok123"}
    )
    assert "-i /run/secrets/k" in env["GIT_SSH_COMMAND"]
    assert "IdentitiesOnly=yes" in env["GIT_SSH_COMMAND"]
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
    assert "tok123" not in env["GIT_CONFIG_VALUE_0"]  # base64-encoded, not raw


def test_token_never_lands_in_repo_config_or_warning(root, tmp_path, monkeypatch):
    monkeypatch.setenv("OKF_NOTEBOOKS_GIT_TOKEN", "tok-SECRET-123")
    store = Store(root, remote=str(tmp_path / "missing.git"))
    _write(store)
    store.wait_push()
    assert "tok-SECRET-123" not in (store.push_warning or "")
    assert "tok-SECRET-123" not in (root / ".git/config").read_text()


def _cfg(tmp_path, root, remote, extra=""):
    p = tmp_path / "cfg.yaml"
    git_block = ""
    if remote is not None:
        git_block = f"git:\n  remote: {remote}\n"
    p.write_text(f"root: {root}\n{git_block}{extra if remote is None else ''}")
    return str(p)


def test_push_warning_is_reported_once_per_outage(root, tmp_path):
    store = Store(root, remote=str(tmp_path / "missing.git"))
    _write(store, "A")
    store.wait_push()
    assert any("push failed" in w for w in _write(store, "B").warnings)
    store.wait_push()
    assert not any("push failed" in w for w in _write(store, "C").warnings)


def test_warning_cleared_after_external_sync_pushed_the_backlog(root, tmp_path):
    from okf_notebooks import gitremote

    bare = tmp_path / "later.git"
    store = Store(root, remote=str(bare))
    _write(store, "A")
    store.wait_push()
    assert "push failed" in (store.push_warning or "")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    gitremote.push(root, str(bare))  # what `okf-notebooks sync` does, in another process
    store.wait_push()
    res = _write(store, "B")
    store.wait_push()
    assert not any("push failed" in w for w in res.warnings)
    assert store.push_warning is None
    assert not any("push failed" in w for w in _write(store, "C").warnings)


@pytest.mark.parametrize(
    "remote",
    [
        "https://alice:hunter2-secret@example.com/me/mem.git",
        "https://alice:hunter2-secret@github.com/x/okf-notebooks.git",
    ],
)
def test_config_error_does_not_echo_credentials_in_remote_url(tmp_path, remote):
    p = tmp_path / "c.yaml"
    p.write_text(f"root: {tmp_path}\ngit:\n  remote: {remote}\n")
    with pytest.raises(ConfigError, match="git.remote") as e:
        load_config(p)
    assert "hunter2" not in str(e.value) and "alice" not in str(e.value)
    r = cli("serve", "--config", str(p))
    assert r.returncode == 2 and "hunter2" not in r.stderr + r.stdout
