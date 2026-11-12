import contextlib
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

# Test probes of localhost must ignore any proxy configured in the environment.
local_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def write_config(tmp_path, port, extra="", host="127.0.0.1"):
    root = tmp_path / "data"
    root.mkdir(exist_ok=True)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"root: {root}\nserver:\n  host: {host}\n  port: {port}\n{extra}")
    return cfg


def cli(*args, env=None, **kw):
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, "-m", "okf_notebooks", *args],
        capture_output=True,
        text=True,
        env=full_env,
        timeout=30,
        check=False,
        **kw,
    )


@pytest.fixture
def server(tmp_path):
    procs = []

    def start(extra="", env=None, use_env=False, host="127.0.0.1"):
        port = free_port()
        cfg = write_config(tmp_path, port, extra, host)
        args = [sys.executable, "-m", "okf_notebooks", "serve"]
        full_env = {**os.environ, **(env or {})}
        if use_env:
            full_env["OKF_NOTEBOOKS_CONFIG"] = str(cfg)
        else:
            args += ["--config", str(cfg)]
        p = subprocess.Popen(
            args, env=full_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        procs.append(p)
        url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            if p.poll() is not None:
                break
            try:
                local_opener.open(url + "/healthz", timeout=0.5)
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("server did not become healthy within 10s")
        return p, url, cfg

    yield start
    for p in procs:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()


@contextlib.contextmanager
def stub_http_server(body: bytes, host: str = "127.0.0.1"):
    """Serve `body` with status 200 on any GET; yields the bound port."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    class Server(HTTPServer):
        address_family = socket.AF_INET6 if ":" in host else socket.AF_INET

    httpd = Server((host, 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield httpd.server_port
    finally:
        httpd.shutdown()


@pytest.fixture
def root(tmp_path):
    """A notebooks root holding one active notebook `notes` (minimal bundle)."""
    r = tmp_path / "root"
    ws = r / "notebooks" / "notes"
    (ws / ".okf").mkdir(parents=True)
    (ws / ".okf" / "notebook.yaml").write_text(
        "slug: notes\n"
        "status: active\n"
        "types:\n"
        "  Decision:\n"
        "    required: [owner]\n"
        "    stale_after: 180d\n"
        "  Playbook: {}\n"
        "  Term: {}\n"
        "  Project: {}\n"
    )
    (ws / "index.md").write_text("# notes\n")
    return r
