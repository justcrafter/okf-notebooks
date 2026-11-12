"""Image test: builds the image locally (native arch, never pushed) and runs it with the
compose-equivalent flags. Skipped when docker is unavailable."""

import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

IMAGE = "okf-notebooks:t10-test"
PREFIX = "okf-t10-"


def docker(*args, check=True, timeout=600):
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check, timeout=timeout
    )


def _docker_ok():
    if shutil.which("docker") is None:
        return False
    try:
        return docker("info", check=False, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(not _docker_ok(), reason="docker is not available")


@pytest.fixture(scope="module")
def image():
    docker("build", "-t", IMAGE, str(Path(__file__).resolve().parent.parent))
    yield IMAGE
    docker("rmi", "-f", IMAGE, check=False)


@pytest.fixture
def stack(image, tmp_path):
    """run(): start a container the way docker-compose.yml does; cleans up afterwards."""
    suffix = uuid.uuid4().hex[:8]
    volume = f"{PREFIX}data-{suffix}"
    names = []
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "config.yaml").write_text("root: /data\nserver:\n  host: 0.0.0.0\n  port: 8765\n")
    docker("volume", "create", volume)

    def run():
        name = f"{PREFIX}{suffix}-{len(names)}"
        names.append(name)
        docker(
            "run", "-d", "--name", name,
            "-p", "127.0.0.1::8765",
            "-v", f"{volume}:/data", "-v", f"{cfg}:/config:ro",
            "--read-only", "--tmpfs", "/tmp",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--health-interval", "1s", "--health-retries", "30",
            image,
        )  # fmt: skip
        return name

    def wait_healthy(name):
        for _ in range(60):
            st = docker("inspect", "-f", "{{.State.Health.Status}}", name).stdout.strip()
            if st == "healthy":
                return
            time.sleep(1)
        pytest.fail(f"container not healthy: {docker('logs', name, check=False).stdout}")

    yield run, wait_healthy
    for n in names:
        docker("rm", "-f", n, check=False)
    docker("volume", "rm", "-f", volume, check=False)


def test_non_root_healthy_and_data_survives_recreation(stack):
    run, wait_healthy = stack
    name = run()
    wait_healthy(name)  # healthy implies serve passed the FTS5 startup check

    assert docker("exec", name, "id", "-u").stdout.strip() == "10001"
    assert docker("exec", name, "git", "config", "--global", "--get-all", "safe.directory").stdout.split() == ["/data"]
    inspect = docker("inspect", "-f", "{{.Config.Image}} {{.HostConfig.ReadonlyRootfs}}", name).stdout
    assert inspect.split()[1] == "true"

    docker("exec", name, "okf-notebooks", "token", "create", "--actor", "claude-code", "--label", "t10")
    docker(
        "exec", name, "okf-notebooks", "notebook", "create", "kube",
        "--description", "Kubernetes platform notes: clusters, deploys and rollbacks for the team.",
        "--scope", "Write cluster facts and decisions here; not application code notes.",
        "--preset", "core",
    )  # fmt: skip

    docker("rm", "-f", name)
    name2 = run()
    wait_healthy(name2)
    assert "t10" in docker("exec", name2, "okf-notebooks", "token", "list").stdout
    out = docker("exec", name2, "okf-notebooks", "validate").stdout
    assert "1 notebook(s), 0 error(s)" in out


def test_review_ui_is_built_into_the_image(image):
    """The Node stage output ships inside the wheel; the UI answers once the password is set."""
    out = docker("run", "--rm", "--entrypoint", "python", image, "-c",
                 "import okf_notebooks.webui as w; print((w.default_dist() / 'index.html').is_file())").stdout
    assert out.strip() == "True"
