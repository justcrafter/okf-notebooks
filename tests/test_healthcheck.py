import pytest
from conftest import cli, free_port, stub_http_server, write_config


def test_healthcheck_exit_zero_when_server_up(server):
    _, _, cfg = server()
    assert cli("healthcheck", "--config", str(cfg)).returncode == 0


def test_healthcheck_exit_nonzero_when_server_down(tmp_path):
    cfg = write_config(tmp_path, free_port())
    assert cli("healthcheck", "--config", str(cfg)).returncode != 0


def test_healthcheck_reaches_server_bound_to_all_interfaces(server):
    _, _, cfg = server(host="0.0.0.0")
    assert cli("healthcheck", "--config", str(cfg)).returncode == 0


@pytest.mark.parametrize(
    "body",
    [b'{"status":"degraded"}', b"<html>not json</html>"],
    ids=["degraded", "not-json"],
)
def test_healthcheck_fails_cleanly_when_endpoint_does_not_report_ok(tmp_path, body):
    with stub_http_server(body) as port:
        cfg = write_config(tmp_path, port)
        r = cli("healthcheck", "--config", str(cfg))
    assert r.returncode == 1
    assert "unhealthy" in r.stderr
    assert "Traceback" not in r.stderr


def test_healthcheck_ignores_proxy_environment(server):
    _, _, cfg = server()
    dead_proxy = f"http://127.0.0.1:{free_port()}"
    env = {"http_proxy": dead_proxy, "HTTP_PROXY": dead_proxy}
    assert cli("healthcheck", "--config", str(cfg), env=env).returncode == 0


def test_healthcheck_probes_ipv6_loopback_host(tmp_path):
    try:
        server_cm = stub_http_server(b'{"status":"ok"}', host="::1")
        port = server_cm.__enter__()
    except OSError:
        pytest.skip("IPv6 loopback unavailable")
    try:
        cfg = write_config(tmp_path, port, host="::1")
        assert cli("healthcheck", "--config", str(cfg)).returncode == 0
    finally:
        server_cm.__exit__(None, None, None)


def test_healthcheck_cli_flag_wins_over_env_var(server, tmp_path):
    _, _, cfg = server()
    other = tmp_path / "other"
    other.mkdir()
    dead = write_config(other, free_port())
    # env points at a dead server; the explicit flag points at the live one
    r = cli("healthcheck", "--config", str(cfg), env={"OKF_NOTEBOOKS_CONFIG": str(dead)})
    assert r.returncode == 0


def test_healthcheck_malformed_host_fails_without_traceback(tmp_path):
    cfg = write_config(tmp_path, free_port(), host='"foo bar"')
    r = cli("healthcheck", "--config", str(cfg))
    assert r.returncode == 1
    assert "unhealthy" in r.stderr
    assert "Traceback" not in r.stderr
