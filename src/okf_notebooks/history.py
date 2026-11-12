"""Revisions of a Concept from git: `git log --follow` and a per-file diff against the parent."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from okf_notebooks.store import Invalid, NotFound, Store

_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_SEP = "\x1f"
_MAX_REVISIONS = 200
_MAX_DIFF_BYTES = 256 * 1024


@dataclass(frozen=True)
class Revision:
    sha: str
    actor: str
    time: str  # ISO-8601
    subject: str


@dataclass(frozen=True)
class History:
    available: bool
    revisions: list[Revision]


def _git(store: Store, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(store.root), *args],
        capture_output=True, text=True, timeout=30, check=False,
    )


def _rel(store: Store, notebook: str, cid: str) -> str:
    store.read_concept(notebook, cid)  # NotFound / Invalid before touching git
    return str(store.concept_path(notebook, cid).relative_to(store.root))


def _available(store: Store) -> bool:
    return store.git and store.commit_per_write and (store.root / ".git").exists()


def history(store: Store, notebook: str, cid: str) -> History:
    rel = _rel(store, notebook, cid)
    if not _available(store):
        return History(False, [])
    fmt = _SEP.join(["%H", "%an", "%aI", "%s"])
    r = _git(store, "log", "--follow", f"-n{_MAX_REVISIONS}", f"--format={fmt}", "--", rel)
    if r.returncode:
        return History(False, [])
    revs = []
    for line in r.stdout.splitlines():
        parts = line.split(_SEP, 3)
        if len(parts) == 4:
            revs.append(Revision(*parts))
    return History(True, revs)


def last_revised(store: Store, notebook: str, cids: list[str]) -> dict[str, str | None]:
    """Time of each Concept's latest Revision (ISO-8601), from one `git log` over the notebook.

    A Concept with no Revision, or any Concept when history is unavailable, maps to None.
    """
    out: dict[str, str | None] = {c: None for c in cids}
    if not cids or not _available(store):
        return out
    bundle = store.resolve(notebook)[0].relative_to(store.root)
    r = _git(store, "log", f"--format={_SEP}%aI", "--name-only", "--", str(bundle))
    if r.returncode:
        return out
    wanted = {str(store.concept_path(notebook, c).relative_to(store.root)): c for c in cids}
    seen: dict[str, str] = {}
    time = ""
    for line in r.stdout.splitlines():
        if line.startswith(_SEP):
            time = line[1:]
        elif line and time and line not in seen:  # newest commit first: the first sighting is the latest
            seen[line] = time
    for rel, cid in wanted.items():
        out[cid] = seen.get(rel)
    return out


def diff(store: Store, notebook: str, cid: str, sha: str) -> str:
    """Unified diff of this file in commit `sha` against its parent (empty tree for the first commit)."""
    if not _SHA_RE.match(sha):
        raise Invalid("bad revision")
    rel = _rel(store, notebook, cid)
    if not _available(store):
        raise NotFound("no history")
    r = _git(store, "log", "--follow", "--format=%H", "--", rel)
    if r.returncode or not any(h.startswith(sha) for h in r.stdout.split()):
        raise NotFound("revision not found for this note")
    r = _git(store, "show", "--format=", "--patch", "--no-color", "--no-ext-diff", sha, "--", rel)
    if r.returncode:
        raise NotFound("revision not found for this note")
    return r.stdout[:_MAX_DIFF_BYTES]
