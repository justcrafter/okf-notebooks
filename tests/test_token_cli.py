import hashlib
import json
import re

from conftest import cli, free_port, write_config


def _cfg(tmp_path):
    return str(write_config(tmp_path, free_port()))


def _tokens_file(tmp_path):
    return tmp_path / "data" / ".auth" / "tokens.json"


def _create(tmp_path, actor="claude-code", label="laptop"):
    r = cli("token", "create", "--actor", actor, "--label", label, "--config", _cfg(tmp_path))
    assert r.returncode == 0, r.stderr
    token = re.search(r"token:\s*(\S+)", r.stdout).group(1)
    tid = re.search(r"id:\s*(\S+)", r.stdout).group(1)
    return tid, token, r


def test_create_shows_token_once_and_stores_only_sha256(tmp_path):
    tid, token, _ = _create(tmp_path)
    raw = _tokens_file(tmp_path).read_text()
    assert token not in raw
    data = json.loads(raw)
    rec = next(t for t in data["tokens"] if t["id"] == tid)
    assert rec["sha256"] == hashlib.sha256(token.encode()).hexdigest()
    assert rec["actor"] == "claude-code" and rec["label"] == "laptop"

    listing = cli("token", "list", "--config", _cfg(tmp_path))
    assert listing.returncode == 0
    assert token not in listing.stdout and rec["sha256"] not in listing.stdout
    assert tid in listing.stdout and "claude-code" in listing.stdout
    assert "laptop" in listing.stdout and "active" in listing.stdout


def test_tokens_are_unique_per_create(tmp_path):
    _, t1, _ = _create(tmp_path)
    _, t2, _ = _create(tmp_path, label="nas")
    assert t1 != t2


def test_create_refuses_human_actor(tmp_path):
    r = cli("token", "create", "--actor", "human", "--label", "x", "--config", _cfg(tmp_path))
    assert r.returncode != 0
    assert "human" in r.stderr
    assert not _tokens_file(tmp_path).exists()


def test_create_refuses_unknown_actor(tmp_path):
    r = cli("token", "create", "--actor", "mallory", "--label", "x", "--config", _cfg(tmp_path))
    assert r.returncode != 0
    assert "mallory" in r.stderr


def test_revoke_marks_token_revoked_in_list(tmp_path):
    tid, _, _ = _create(tmp_path)
    r = cli("token", "revoke", tid, "--config", _cfg(tmp_path))
    assert r.returncode == 0
    listing = cli("token", "list", "--config", _cfg(tmp_path))
    assert "revoked" in listing.stdout and "active" not in listing.stdout


def test_revoke_unknown_id_fails(tmp_path):
    _create(tmp_path)
    r = cli("token", "revoke", "t-nope", "--config", _cfg(tmp_path))
    assert r.returncode == 1
    assert "t-nope" in r.stderr


def test_list_on_empty_store_is_ok(tmp_path):
    r = cli("token", "list", "--config", _cfg(tmp_path))
    assert r.returncode == 0
