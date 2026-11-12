from conftest import cli, free_port, write_config


def test_unknown_top_level_key_stops_startup(tmp_path):
    cfg = write_config(tmp_path, free_port(), extra="bogus: 1\n")
    r = cli("serve", "--config", str(cfg))
    assert r.returncode == 2
    assert "bogus" in r.stderr


def test_unknown_nested_key_stops_startup(tmp_path):
    cfg = write_config(tmp_path, free_port(), extra="limits:\n  max_oops: 1\n")
    r = cli("serve", "--config", str(cfg))
    assert r.returncode == 2
    assert "max_oops" in r.stderr


def test_missing_config_stops_startup(tmp_path):
    r = cli("serve", env={"OKF_NOTEBOOKS_CONFIG": ""})
    assert r.returncode == 2
    assert "--config" in r.stderr


def test_wrong_type_stops_startup(tmp_path):
    cfg = write_config(tmp_path, free_port(), extra="limits:\n  max_notebooks: many\n")
    r = cli("serve", "--config", str(cfg))
    assert r.returncode == 2
    assert "max_notebooks" in r.stderr


def test_empty_config_file_stops_startup(tmp_path):
    cfg = tmp_path / "empty.yaml"
    cfg.write_text("")
    r = cli("serve", "--config", str(cfg))
    assert r.returncode == 2
    assert "error:" in r.stderr


def test_non_utf8_config_stops_startup_with_message(tmp_path):
    cfg = tmp_path / "bad.yaml"
    cfg.write_bytes(b"root: \xff\xfe\n")
    r = cli("serve", "--config", str(cfg))
    assert r.returncode == 2
    assert "error:" in r.stderr
    assert "Traceback" not in r.stderr


def test_port_out_of_range_stops_startup(tmp_path):
    cfg = write_config(tmp_path, 99999)
    r = cli("serve", "--config", str(cfg))
    assert r.returncode == 2
    assert "port" in r.stderr


def test_stdio_transport_is_refused_by_serve_until_implemented(tmp_path):
    # `extra` is appended right after the `server:` block, so it extends that block.
    cfg = write_config(tmp_path, free_port(), extra="  transport: stdio\n")
    r = cli("serve", "--config", str(cfg))
    assert r.returncode == 2
    assert "stdio" in r.stderr


def test_invalid_rate_limit_stops_startup(tmp_path):
    cfg = write_config(tmp_path, free_port(), extra="  rate_limit_per_token: lots\n")
    r = cli("serve", "--config", str(cfg))
    assert r.returncode == 2
    assert "rate_limit_per_token" in r.stderr


def test_unknown_actor_in_config_stops_startup(tmp_path):
    cfg = write_config(tmp_path, free_port(), extra="actors:\n  human:\n    allow: [read]\n")
    r = cli("serve", "--config", str(cfg))
    assert r.returncode == 2
    assert "human" in r.stderr


def test_human_only_permission_not_grantable_to_agents(tmp_path):
    cfg = write_config(tmp_path, free_port(), extra="actors:\n  opencode:\n    allow: [verify]\n")
    r = cli("serve", "--config", str(cfg))
    assert r.returncode == 2
    assert "verify" in r.stderr


def test_unknown_key_in_actor_config_stops_startup(tmp_path):
    cfg = write_config(tmp_path, free_port(), extra="actors:\n  opencode:\n    admin: true\n")
    r = cli("serve", "--config", str(cfg))
    assert r.returncode == 2
    assert "admin" in r.stderr


def test_invalid_slug_pattern_regex_stops_startup(tmp_path):
    cfg = write_config(tmp_path, free_port(), extra="notebook_creation:\n  slug_pattern: '[a-'\n")
    r = cli("serve", "--config", str(cfg))
    assert r.returncode == 2
    assert "slug_pattern" in r.stderr
