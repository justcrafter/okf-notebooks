"""gitremote: private git-remote publication, `sync` and `doctor`.

Model: publish only (push), fast-forward, best-effort. The server is the sole
writer of `root`, so a rejected (non-fast-forward) push is an operator error.

Auth comes from the process environment and is never written to the image,
the config or the repository:
  OKF_NOTEBOOKS_GIT_SSH_KEY  path to an SSH deploy key (mounted volume)
  OKF_NOTEBOOKS_GIT_TOKEN    HTTPS access token
"""

from __future__ import annotations

import base64
import logging
import os
import re
import shlex
import subprocess
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import filelock

log = logging.getLogger("okf_notebooks.git")

REMOTE_NAME = "notebooks"
BRANCH = "main"
# Names of the public MIT code repository. A notebooks remote must never be one of
# them (the notes would leak); extra URLs go in `git.public_code_repos`.
CODE_REPO_NAMES = frozenset({"okf-notebooks", "mcp-okf-notebooks"})
_SECRET_ENV = ("OKF_NOTEBOOKS_GIT_TOKEN",)


class PushError(Exception):
    pass


def _normalize(url: str) -> str:
    u = url.strip()
    u = re.split(r"[?#]", u, maxsplit=1)[0]  # query/fragment never name the repository
    u = unquote(u)
    u = re.sub(r"^[a-z+]+://", "", u, flags=re.IGNORECASE)
    u = re.sub(r"^[^@/]*@", "", u)  # user@
    if re.match(r"^[^/:]+:(?!\d+/)", u):  # scp-like host:path
        u = u.replace(":", "/", 1)
    return u.rstrip("/").removesuffix(".git").rstrip("/").lower()


def _embeds_credentials(url: str) -> bool:
    """A password anywhere, or (http/https) any userinfo but the plain `git` user.

    An ssh username (`deploy@host`) is not a secret; an HTTP userinfo is usually a token.
    """
    m = re.match(r"^([a-z+]+)://([^/@]*)@", url, flags=re.IGNORECASE)
    if m:
        scheme, userinfo = m.group(1).lower(), unquote(m.group(2))
        if ":" in userinfo:
            return True
        return scheme in ("http", "https") and userinfo != "git"
    return re.match(r"^[^/@]*:[^/@]*@", url) is not None  # scp form `user:password@host:path`


def _is_remote_form(url: str) -> bool:
    """`scheme://...` (file:// too) or scp-like `[user@]host:path`; not a filesystem path."""
    return re.match(r"^[a-z][a-z0-9+.-]*://", url, flags=re.IGNORECASE) is not None or (
        re.match(r"^[^/:]+:", url) is not None
    )


def check_remote_url(url: str, public_code_repos: list[str]) -> None:
    """Raise ValueError unless `url` may serve as the private notebooks remote."""
    url = url.strip()
    if _embeds_credentials(url):
        raise ValueError(
            "git.remote must not embed credentials; use OKF_NOTEBOOKS_GIT_TOKEN "
            "or OKF_NOTEBOOKS_GIT_SSH_KEY"
        )
    norm = _normalize(url)
    known = {_normalize(u) for u in public_code_repos}
    if norm in known or norm.rsplit("/", 1)[-1] in CODE_REPO_NAMES:
        raise ValueError(
            "git.remote points at the public code repository; notebooks must go "
            "to a separate private repository"
        )
    # a query string is where tokens end up in .git/config; plain filesystem paths are exempt
    if _is_remote_form(url) and re.search(r"[?#]", url):
        raise ValueError(
            "git.remote must not contain a query string or fragment; "
            "use OKF_NOTEBOOKS_GIT_TOKEN or OKF_NOTEBOOKS_GIT_SSH_KEY"
        )


def auth_env(environ: Mapping[str, str]) -> dict[str, str]:
    env = {"GIT_TERMINAL_PROMPT": "0"}
    key = environ.get("OKF_NOTEBOOKS_GIT_SSH_KEY")
    ssh = "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
    if key:
        ssh += f" -i {shlex.quote(key)} -o IdentitiesOnly=yes"
    env["GIT_SSH_COMMAND"] = ssh
    token = environ.get("OKF_NOTEBOOKS_GIT_TOKEN")
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
        env["GIT_CONFIG_VALUE_0"] = f"Authorization: Basic {basic}"
    return env


def _scrub(text: str, environ: Mapping[str, str]) -> str:
    for name in _SECRET_ENV:
        v = environ.get(name)
        if v:
            text = text.replace(v, "***")
            text = text.replace(
                base64.b64encode(f"x-access-token:{v}".encode()).decode(), "***"
            )
    return text.strip()


def _run(root: Path, *args: str, env: Mapping[str, str] | None = None) -> str:
    r = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        timeout=120,
        check=False,
    )
    if r.returncode:
        raise subprocess.SubprocessError((r.stderr or r.stdout).strip())
    return r.stdout


def ensure_repo(root: Path) -> bool:
    """Create the root repository if absent. Returns True when created."""
    if (root / ".git").exists():
        return False
    _run(root, "init", "-q", "-b", BRANCH)
    (root / ".gitignore").write_text(".tmp/\n.index/\n")
    return True


def push(root: Path, remote: str, environ: Mapping[str, str] | None = None) -> int:
    """Fast-forward push of HEAD to `remote`; returns the number of commits sent."""
    environ = os.environ if environ is None else environ
    try:
        if not (root / ".git").exists():
            raise PushError("nothing to push: root has no git repository")
        try:
            _run(root, "remote", "set-url", REMOTE_NAME, remote)
        except subprocess.SubprocessError:
            _run(root, "remote", "add", REMOTE_NAME, remote)
        try:
            rng = f"refs/remotes/{REMOTE_NAME}/{BRANCH}..HEAD"
            _run(
                root,
                "rev-parse",
                "--verify",
                "-q",
                f"refs/remotes/{REMOTE_NAME}/{BRANCH}",
            )
        except subprocess.SubprocessError:
            rng = "HEAD"
        ahead = int(_run(root, "rev-list", "--count", rng).strip() or 0)
        _run(
            root,
            "push",
            "-q",
            REMOTE_NAME,
            f"HEAD:refs/heads/{BRANCH}",
            env=auth_env(environ),
        )
        return ahead
    except (subprocess.SubprocessError, OSError) as e:
        raise PushError(_scrub(str(e), environ)) from None


class BackgroundPusher:
    """Coalescing best-effort push thread; never blocks or fails the caller."""

    def __init__(self, root: Path, remote: str):
        self.root, self.remote = root, remote
        self.warning: str | None = None
        self._reported = False  # the current outage was already surfaced to a writer
        self._failed_head: str | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._again = False

    def schedule(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                self._again = True
                return
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while True:
            with self._lock:
                self._again = False
            try:
                push(self.root, self.remote)
                self.warning, self._reported = None, False
            except Exception as e:  # noqa: BLE001 - best-effort, never propagate
                if self.warning is None:
                    self._reported = False
                self.warning = f"git push failed: {e}"
                try:
                    self._failed_head = _run(self.root, "rev-parse", "HEAD").strip()
                except (subprocess.SubprocessError, OSError):
                    self._failed_head = None
                log.warning(self.warning)
            with self._lock:
                if not self._again:
                    self._thread = None
                    return

    def take_warning(self) -> str | None:
        """The push failure to show a writer: once per outage, never after the backlog landed."""
        w = self.warning
        if w is None or self._reported:
            return None
        if self._failed_head and self._landed(self._failed_head):
            self.warning = None  # e.g. `okf-notebooks sync` pushed it from another process
            return None
        self._reported = True
        return w

    def _landed(self, sha: str) -> bool:
        try:
            _run(
                self.root, "merge-base", "--is-ancestor", sha,
                f"refs/remotes/{REMOTE_NAME}/{BRANCH}",
            )
            return True
        except (subprocess.SubprocessError, OSError):
            return False

    def wait(self, timeout: float = 30) -> None:
        while (t := self._thread) is not None:
            t.join(timeout)
            if t.is_alive():
                return


@dataclass(frozen=True)
class DoctorReport:
    committed: bool
    files: list[str]


def doctor(root: Path) -> DoctorReport:
    """Commit every uncommitted change, then verify none remain."""
    (root / ".tmp").mkdir(parents=True, exist_ok=True)
    try:
        with filelock.FileLock(root / ".tmp" / "git.lock", timeout=10):
            ensure_repo(root)
            _run(root, "add", "-A")
            files = [
                ln
                for ln in _run(root, "diff", "--cached", "--name-only").splitlines()
                if ln
            ]
            if files:
                who = {
                    "GIT_AUTHOR_NAME": "doctor",
                    "GIT_AUTHOR_EMAIL": "doctor@okf-notebooks.local",
                    "GIT_COMMITTER_NAME": "doctor",
                    "GIT_COMMITTER_EMAIL": "doctor@okf-notebooks.local",
                }
                _run(
                    root,
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-q",
                    "--no-verify",
                    "-m",
                    f"doctor: commit {len(files)} uncommitted file(s)",
                    env=who,
                )
            left = _run(root, "status", "--porcelain").strip()
    except (subprocess.SubprocessError, OSError, filelock.Timeout) as e:
        raise PushError(f"doctor failed: {e}") from None
    if left:
        raise PushError(f"uncommitted changes remain:\n{left}")
    return DoctorReport(bool(files), files)
