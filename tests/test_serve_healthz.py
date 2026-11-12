import json

from conftest import local_opener


def test_healthz_without_token_returns_ok(server):
    _, url, _ = server()
    with local_opener.open(url + "/healthz") as r:
        assert r.status == 200
        assert json.loads(r.read()) == {"status": "ok"}


def test_serve_reads_config_path_from_env(server):
    _, url, _ = server(use_env=True)
    with local_opener.open(url + "/healthz") as r:
        assert json.loads(r.read()) == {"status": "ok"}
