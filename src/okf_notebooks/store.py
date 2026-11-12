"""store: paths, atomic file IO, etag, locking and git for Concepts.

Public surface: `Store` plus the result/error types below. Everything else is private.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import subprocess
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import filelock
import yaml

from okf_notebooks.config import Config
from okf_notebooks.fsutil import PUBLIC_MODE, atomic_write, utc_now_iso
from okf_notebooks.gitremote import BackgroundPusher, ensure_repo
from okf_notebooks.indexer import Index, render_index
from okf_notebooks.registry import NotebookNotFound, Registry, is_slug
from okf_notebooks.validator import (
    Context,
    TypeSource,
    Violation,
    clip_name,
    extract_links,
    finalize_frontmatter,
    validate_file,
)

_SEGMENT_RE = re.compile(r"^[^/\\\x00.][^/\\\x00]*$")


class StoreError(Exception):
    code = "error"


class Invalid(StoreError):
    code = "invalid"

    def __init__(self, message: str, violations: list[Violation] | None = None):
        super().__init__(message)
        self.violations = violations or []


class Busy(StoreError):
    code = "busy"


class NotFound(StoreError):
    code = "not_found"


@dataclass(frozen=True)
class Concept:
    id: str
    frontmatter: dict[str, Any]
    body: str
    etag: str


@dataclass(frozen=True)
class WriteResult:
    concept: Concept
    warnings: list[str] = field(default_factory=list)


class Conflict(StoreError):
    code = "conflict"

    def __init__(self, current: Concept):
        super().__init__(f"etag mismatch for {current.id}")
        self.current = current


def _slugify(text: str) -> str:
    s = re.sub(r"[^\w]+", "-", text.strip().lower(), flags=re.UNICODE).strip("-_")
    s = re.sub(r"[-_]+", "-", s)
    if not s or s.startswith("."):
        raise Invalid(f"cannot derive a slug from {text!r}")
    return s


_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "є": "ye", "і": "i", "ї": "yi", "ґ": "g",
}  # fmt: skip
MAX_SLUG = 80
MAX_TYPE_DIR = 64


def _title_slug(title: str) -> str:
    """ASCII `[a-z0-9-]` slug: Cyrillic transliterated, accents dropped, emoji/punct gone."""
    s = "".join(_CYR.get(ch, ch) for ch in title.strip().lower())
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:MAX_SLUG].strip("-")
    if not s:
        raise Invalid(
            f"cannot derive a slug from the title {title!r}",
            [Violation("title", "error", "title must contain letters or digits")],
        )
    return s


def _type_dir(type_: str) -> str:
    s = _slugify(type_)
    if len(s) > MAX_TYPE_DIR:
        raise Invalid(
            f"bad type {clip_name(type_)}", [Violation("type", "error", "type name is too long")]
        )
    if not re.fullmatch(r"[^\W_]+(-[^\W_]+)*", s):
        raise Invalid(f"bad type {clip_name(type_)}")
    return s if s.endswith("s") else s + "s"


def _etag(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _render(frontmatter: dict[str, Any], body: str) -> bytes:
    try:
        fm = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False)
        if not frontmatter:
            fm = ""
        return f"---\n{fm}---\n{body}".encode()
    except (yaml.YAMLError, UnicodeEncodeError) as e:
        rule = "utf8" if isinstance(e, UnicodeEncodeError) else "yaml"
        raise Invalid(
            "concept cannot be serialised",
            [Violation(rule, "error", f"cannot serialise concept: {e}")],
        ) from None


def _parse(cid: str, data: bytes) -> Concept:
    text = data.decode("utf-8")
    fm: dict[str, Any] = {}
    body = text
    if text.startswith("---\n"):
        rest = text[4:]
        if rest.startswith("---\n"):
            body = rest[4:]
        else:
            end = rest.find("\n---\n")
            if end != -1:
                fm = yaml.safe_load(rest[: end + 1]) or {}
                body = rest[end + 5 :]
    return Concept(cid, fm, body, _etag(data))


def clean_label(label: str | None) -> str | None:
    """A machine label made safe for log.md lines and commit subjects."""
    return re.sub(r"[^\w .@-]", "_", label)[:64] if label else None


def label_suffix(label: str | None) -> str:
    """` [label]` after an actor name in log lines and commit subjects; empty without a label."""
    label = clean_label(label)
    return f" [{label}]" if label else ""


class Store:
    def __init__(
        self,
        root: Path | str,
        *,
        git: bool = True,
        lock_timeout: float = 5.0,
        max_concept_bytes: int = 65536,
        types: TypeSource | None = None,
        remote: str | None = None,
        commit_per_write: bool = True,
        registry: Registry | None = None,
        index_path: Path | str | None = None,
        comments_path: Path | str | None = None,
    ):
        self.root = Path(root)
        self.git = git
        self.lock_timeout = lock_timeout
        self.max_concept_bytes = max_concept_bytes
        self.registry = registry or Registry(self.root)
        self.types: TypeSource = types or self.registry
        self.commit_per_write = commit_per_write
        self.index = Index(self.root, index_path)
        # Imported here: `comments` raises this module's errors, so it imports `store` itself.
        from okf_notebooks.comments import Comments

        self.comments = Comments(
            Path(comments_path) if comments_path else self.root / ".comments" / "threads.sqlite"
        )
        self._pusher = BackgroundPusher(self.root, remote) if remote else None

    @classmethod
    def from_config(cls, cfg: Config) -> Store:
        registry = Registry(cfg.root, cfg.presets_dir)
        index_path = cfg.index.path
        if not index_path.is_absolute():
            index_path = cfg.root / index_path
        comments_path = cfg.comments.path
        if not comments_path.is_absolute():
            comments_path = cfg.root / comments_path
        return cls(
            cfg.root,
            registry=registry,
            index_path=index_path,
            comments_path=comments_path,
            max_concept_bytes=cfg.limits.max_concept_bytes,
            git=cfg.git.enabled,
            remote=cfg.git.remote,
            commit_per_write=cfg.git.commit_per_write,
        )

    @property
    def push_warning(self) -> str | None:
        return self._pusher.warning if self._pusher else None

    def wait_push(self, timeout: float = 30) -> None:
        if self._pusher:
            self._pusher.wait(timeout)

    # -- paths and visibility -------------------------------------------
    def visible_status(self, actor: str, notebook: str) -> str:
        """Status of a notebook as `actor` may see it, else `NotFound`.

        Active notebooks are visible to everyone; proposed and rejected ones only to
        the actor that created the proposal and to `human`.
        """
        if not is_slug(notebook):
            raise NotFound(f"notebook {notebook!r} not found")
        try:
            status = self.registry.status_of(notebook)
            if status == "active":
                return status
            if status in ("proposed", "rejected") and (
                actor == "human" or actor == self.registry.author_of(notebook)
            ):
                return status
        except NotebookNotFound:
            pass
        raise NotFound(f"notebook {notebook!r} not found")

    def resolve(self, notebook: str, actor: str | None = None) -> tuple[Path, str]:
        """(bundle directory, status) of a notebook that holds Concepts.

        Only `notebooks/<slug>` (active) and `_proposed/<slug>` (proposed) qualify;
        archived and rejected ones do not. With `actor`, visibility is enforced; None
        is for trusted in-process callers (CLI, lifecycle).
        """
        if not is_slug(notebook):
            raise Invalid(f"bad notebook slug {notebook!r}")
        if actor is not None:
            status = self.visible_status(actor, notebook)
        else:
            status = self.registry.status_of(notebook) or ""
        if status not in ("active", "proposed"):
            raise NotFound(f"notebook {notebook!r} not found")
        b = self.root / ("notebooks" if status == "active" else "_proposed") / notebook
        if b.is_symlink() or not (b / ".okf" / "notebook.yaml").is_file():
            raise NotFound(f"notebook {notebook!r} not found")
        return b, status

    def _bundle(self, notebook: str, actor: str | None = None) -> Path:
        return self.resolve(notebook, actor)[0]

    def _path(self, bundle: Path, cid: str) -> Path:
        parts = cid.split("/")
        if (
            len(parts) != 3
            or parts[0] != ""
            or not all(_SEGMENT_RE.match(p) for p in parts[1:])
        ):
            raise Invalid(f"bad concept id {cid!r}")
        path = bundle / parts[1] / (parts[2] + ".md")
        cur = bundle
        for part in path.relative_to(bundle).parts:
            cur = cur / part
            if cur.is_symlink():
                raise Invalid(f"symlink in path for {cid!r}")
        return path

    def concept_path(self, notebook: str, cid: str) -> Path:
        """Absolute file of a Concept (trusted in-process callers; no visibility check)."""
        return self._path(self._bundle(notebook), cid)

    # -- API -----------------------------------------------------------
    def read_concept(self, notebook: str, cid: str, *, actor: str | None = None) -> Concept:
        path = self._path(self._bundle(notebook, actor), cid)
        try:
            return _parse(cid, path.read_bytes())
        except FileNotFoundError:
            raise NotFound(f"{cid} not found") from None

    def read_raw(self, notebook: str, cid: str, *, actor: str | None = None) -> str:
        """The Concept's file exactly as stored, frontmatter included."""
        path = self._path(self._bundle(notebook, actor), cid)
        try:
            return path.read_text("utf-8")
        except FileNotFoundError:
            raise NotFound(f"{cid} not found") from None

    def write_concept(
        self,
        notebook: str,
        *,
        type: str,
        title: str,
        frontmatter: dict[str, Any],
        body: str,
        actor: str,
        generated_by: str | None = None,
        label: str | None = None,
    ) -> WriteResult:
        self.resolve(notebook, actor)  # visibility before anything else is revealed
        type_dir = self.registry.declared_type_dir(notebook, type) or _type_dir(type)
        title = title.strip()
        cid = f"/{type_dir}/{_title_slug(title)}"

        def compute(cur: Concept | None):
            return frontmatter, body, type, title

        return self._transaction(
            notebook, cid, "write", actor, compute, generated_by, label, unique=True
        )

    def update_concept(
        self,
        notebook: str,
        cid: str,
        *,
        base_etag: str,
        actor: str,
        frontmatter: dict[str, Any] | None = None,
        fields: dict[str, Any] | None = None,
        body: str | None = None,
        generated_by: str | None = None,
        label: str | None = None,
        keep_generated: bool = False,
    ) -> WriteResult:
        """`frontmatter` replaces the agent-owned fields, `fields` merges into the stored ones.

        `keep_generated`: a status/verified mark by a human is not a rewrite of the content,
        so the author's `generated` stamp stays.
        """
        def compute(cur: Concept | None):
            if cur is None:
                raise NotFound(f"{cid} not found")
            if cur.etag != base_etag:
                raise Conflict(cur)
            base = cur.frontmatter if frontmatter is None else frontmatter
            return (
                {**base, **fields} if fields else base,
                cur.body if body is None else body,
                None,
                None,
            )

        return self._transaction(
            notebook, cid, "update", actor, compute, generated_by, label,
            keep_generated=keep_generated,
        )

    def append_concept(
        self,
        notebook: str,
        cid: str,
        *,
        text: str,
        actor: str,
        generated_by: str | None = None,
        label: str | None = None,
    ) -> WriteResult:
        def compute(cur: Concept | None):
            if cur is None:
                raise NotFound(f"{cid} not found")
            sep = "" if not cur.body or cur.body.endswith("\n") else "\n"
            return cur.frontmatter, cur.body + sep + text, None, None

        return self._transaction(
            notebook, cid, "append", actor, compute, generated_by, label
        )

    def neighbours(
        self, notebook: str, cid: str, *, actor: str | None = None
    ) -> tuple[list[str], list[str]]:
        """(outgoing, incoming) in-bundle links of a concept, as ids."""
        bundle = self._bundle(notebook, actor)
        cur = self.read_concept(notebook, cid, actor=actor)
        outgoing = [x for x in extract_links(cur.body, cur.frontmatter) if x != cid]
        incoming: list[str] = []
        for d in sorted(bundle.iterdir()):
            if d.is_symlink() or not d.is_dir() or d.name.startswith("."):
                continue
            for f in sorted(d.glob("*.md")):
                other = f"/{d.name}/{f.stem}"
                if other == cid or f.is_symlink():
                    continue
                try:
                    c = _parse(other, f.read_bytes())
                except (OSError, UnicodeDecodeError, yaml.YAMLError):
                    continue
                if cid in extract_links(c.body, c.frontmatter):
                    incoming.append(other)
        return outgoing, incoming

    # -- write pipeline: lock -> read -> compute -> write -> log.md -> git ----
    def _transaction(
        self,
        notebook: str,
        cid: str,
        action: str,
        actor: str,
        compute,
        generated_by: str | None = None,
        label: str | None = None,
        unique: bool = False,
        keep_generated: bool = False,
    ) -> WriteResult:
        """`unique`: create under a free id, taking `-2`, `-3` ... on a slug collision."""
        self.resolve(notebook, actor)  # fail fast, before taking the lock
        label = clean_label(label)
        with self._lock(f"{notebook}.lock"):
            # re-resolve under the lock: approve/reject move the bundle holding this lock
            bundle, status = self.resolve(notebook, actor)
            path = self._path(bundle, cid)
            if unique:
                base, n = cid, 1
                while path.exists() or path.is_symlink():
                    n += 1
                    cid = f"{base}-{n}"
                    path = self._path(bundle, cid)
            try:
                cur = _parse(cid, path.read_bytes())
            except FileNotFoundError:
                cur = None
            agent_fm, body, type_, title = compute(cur)
            types = self.types.types(bundle)
            if type_ is None:  # update/append: type is fixed by the stored file
                type_ = str((cur.frontmatter if cur else {}).get("type", ""))
            fm, extra = finalize_frontmatter(
                current=cur.frontmatter if cur else None,
                proposed=agent_fm,
                type_=type_,
                title=title,
                spec=types.get(type_),
                actor=actor,
                generated_by=generated_by,
                keep_generated=keep_generated,
            )
            data = _render(fm, body)
            found = extra + validate_file(
                data, Context(bundle, cid, types, self.max_concept_bytes)
            )
            errors = [v for v in found if v.level == "error"]
            if errors:
                raise Invalid("; ".join(str(v) for v in errors), found)
            soft = [str(v) for v in found if v.level == "warning"]
            self._atomic_write(path, data)
            log = bundle / "log.md"
            stamp = utc_now_iso()
            who = actor + label_suffix(label)
            line = f"- {stamp} {who} {action} {cid}\n"
            old = log.read_bytes() if log.exists() else b"# Log\n\n"
            self._atomic_write(log, old + line.encode(), mode=PUBLIC_MODE)
            index = bundle / "index.md"
            self._atomic_write(
                index,
                render_index(self.registry, notebook, bundle).encode(),
                mode=PUBLIC_MODE,
            )
            try:
                self.index.upsert(notebook, cid, proposed=status == "proposed")
            except (sqlite3.Error, OSError):
                pass  # the index is a cache; the next sync heals it
            warnings = soft + self._commit(
                [path, log, index],
                actor,
                f"notebook({notebook}): {action} {cid}" + (f" [{label}]" if label else ""),
            )
        return WriteResult(_parse(cid, data), warnings)

    def lock(self, name: str) -> _TimedLock:
        """Named lock under `.tmp/` (`<notebook>.lock`, `registry.lock`), `Busy` on timeout."""
        return self._lock(name)

    def commit_paths(self, paths: list[Path], actor: str, message: str) -> list[str]:
        """Commit paths (files or directories, including ones just moved away).

        Paths that neither exist nor are tracked are ignored. Returns warnings; a git
        failure never raises.
        """
        keep = [p for p in paths if p.exists() or self._tracked(p)]
        return self._commit(keep, actor, message) if keep else []

    def _tracked(self, path: Path) -> bool:
        if not self.git or not self.commit_per_write:
            return False
        r = subprocess.run(
            ["git", "-C", str(self.root), "ls-files", "--", str(path.relative_to(self.root))],
            capture_output=True,
            text=True,
            check=False,
        )
        return r.returncode == 0 and bool(r.stdout.strip())

    def _lock(self, name: str) -> _TimedLock:
        (self.root / ".tmp").mkdir(parents=True, exist_ok=True)
        return _TimedLock(self.root / ".tmp" / name, self.lock_timeout)

    # -- git -----------------------------------------------------------
    def _commit(self, paths: list[Path], actor: str, message: str) -> list[str]:
        if not self.git or not self.commit_per_write:
            return []
        try:
            with self._lock("git.lock"):
                rel = [str(p.relative_to(self.root)) for p in paths]
                if ensure_repo(self.root):
                    rel.append(".gitignore")
                name = re.sub(r"[^\w.-]", "_", actor) or "unknown"
                env = {
                    "GIT_AUTHOR_NAME": name,
                    "GIT_AUTHOR_EMAIL": f"{name}@okf-notebooks.local",
                    "GIT_COMMITTER_NAME": name,
                    "GIT_COMMITTER_EMAIL": f"{name}@okf-notebooks.local",
                }
                self._git("add", "--", *rel)
                self._git(
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-q",
                    "--no-verify",
                    "-m",
                    message,
                    "--",
                    *rel,
                    env=env,
                )
        except (StoreError, OSError, subprocess.SubprocessError) as e:
            return [f"git commit failed: {e}"]
        if self._pusher:
            prev = self._pusher.take_warning()  # earlier push failure -> warn once
            self._pusher.schedule()
            return [prev] if prev else []
        return []

    def _git(self, *args: str, env: dict[str, str] | None = None) -> None:
        r = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
            env={**os.environ, **(env or {})},
            timeout=30,
            check=False,
        )
        if r.returncode:
            raise subprocess.SubprocessError((r.stderr or r.stdout).strip())

    # -- io ------------------------------------------------------------
    def _atomic_write(self, path: Path, data: bytes, *, mode: int | None = None) -> None:
        atomic_write(path, data, mode=mode, tmp_dir=self.root / ".tmp")


class _TimedLock:
    """filelock context manager that raises `Busy` instead of `Timeout`."""

    def __init__(self, path: Path, timeout: float):
        self._lock = filelock.FileLock(path, timeout=timeout)
        self._path = path

    def __enter__(self):
        try:
            self._lock.acquire()
        except filelock.Timeout:
            raise Busy(f"lock {self._path.name} is busy") from None
        return self

    def __exit__(self, *exc):
        self._lock.release()
