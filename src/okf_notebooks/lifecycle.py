"""lifecycle: Notebook creation, approval, archive, Type changes and audits.

Public surface: `Lifecycle` (+ `from_config`), `human_actor`, `cleanup_tmp`, the result
dataclasses and the errors `Forbidden`, `LimitExceeded`, `SimilarExists` (validation
failures reuse `store.Invalid`, carrying every violation).

Layout on disk: `notebooks/<slug>/` (active), `_proposed/<slug>/` (+ type requests
`_proposed/<slug>.type-<Name>.yaml`), `_archive/<slug>-<date>/` (archived or rejected).

Atomicity: a bundle is assembled in `.tmp/<uuid>/`, fully validated and then moved with
`os.rename` into place. `.tmp/registry.lock` serialises every check-then-move
(slug uniqueness, `max_notebooks`, pending limit), so concurrent creators of one slug
cannot both win. Human-only operations (approve, reject, archive, restore, adopt,
type delete/rename, mark) take no actor: they are reachable from the CLI only.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from okf_notebooks.auth import PERMISSIONS, Actor
from okf_notebooks.config import Config
from okf_notebooks.fsutil import PUBLIC_MODE, atomic_write, utc_now_iso
from okf_notebooks.indexer import OKF_VERSION, render_index
from okf_notebooks.registry import (
    CORE_PRESET,
    NotebookNotFound,
    Registry,
    TypeSpec,
    default_type_dir,
    is_slug,
    read_frontmatter,
    slug_title,
)
from okf_notebooks.store import Invalid, Store, StoreError, label_suffix
from okf_notebooks.validator import (
    Context,
    Violation,
    clip_name,
    stale_after_ok,
    validate_file,
)

PENDING_LIMIT = 3
MAX_TYPES = 12
TMP_MAX_AGE = 3600.0
_NAME_RE = re.compile(r"^[^\W\d_][\w-]{0,39}$")
_DEFAULT_SLUG_PATTERN = "^[a-z][a-z0-9-]{1,38}[a-z0-9]$"
_STATUSES = ("draft", "stable", "deprecated")
_STOP = frozenset({"the", "and", "for", "with", "that", "this", "are", "from", "about"})


class Forbidden(StoreError):
    code = "forbidden"


class LimitExceeded(StoreError):
    code = "limit_exceeded"


class SimilarExists(StoreError):
    code = "similar_exists"

    def __init__(self, candidates: list[dict[str, Any]]):
        super().__init__(
            "similar notebook(s) exist: "
            + ", ".join(c.get("slug", "<another actor's pending proposal>") for c in candidates)
            + "; repeat with confirm_distinct=true if yours is really different"
        )
        self.candidates = candidates


@dataclass(frozen=True)
class CreateResult:
    status: str  # created | proposed
    slug: str
    path_in_root: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TypeResult:
    status: str  # defined | proposed
    notebook: str
    name: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PendingItem:
    kind: str  # notebook | type
    slug: str
    name: str  # notebook name, or the Type name for kind == "type"
    description: str
    author: str
    rationale: str
    at: str
    confirm_distinct: bool = False


@dataclass(frozen=True)
class Finding:
    notebook: str
    cid: str
    violation: Violation


@dataclass(frozen=True)
class ValidationReport:
    findings: list[Finding]
    notebooks: list[str]
    okflint: str | None = None  # output of okflint when it is installed
    okflint_ok: bool = True

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.violation.level == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors and self.okflint_ok


def human_actor() -> Actor:
    """The CLI operator: every permission, `direct` creation."""
    return Actor("human", "cli", "cli", frozenset(PERMISSIONS), "direct")


def _tag(actor: Actor) -> str:
    """` [label]` for agents (the machine label); the CLI human carries none."""
    return label_suffix(actor.label if actor.name != "human" else None)


def _who(actor: Actor) -> str:
    return actor.name + _tag(actor)


def _bad_stale_after(type_name: str, value: object) -> Violation:
    return Violation(
        "types",
        "error",
        f"type {clip_name(type_name)}: stale_after {clip_name(value, 24)} "
        "must look like 180d, 26w, 6m or 2y",
    )


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _dump(data: Any) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w{3,}", text.lower()) if w not in _STOP}


def _jaccard(a: str, b: str) -> float:
    x, y = _words(a), _words(b)
    return len(x & y) / len(x | y) if x and y else 0.0


def _oneline(text: str) -> str:
    return " ".join(text.split())


def cleanup_tmp(root: Path | str, max_age: float = TMP_MAX_AGE) -> list[str]:
    """Remove leftovers in `<root>/.tmp` older than `max_age` seconds (startup hygiene).

    Lock files are kept: another process may hold them.
    """
    tmp = Path(root) / ".tmp"
    removed: list[str] = []
    if not tmp.is_dir():
        return removed
    cutoff = time.time() - max_age
    for p in tmp.iterdir():
        if p.suffix == ".lock":
            continue
        try:
            if p.lstat().st_mtime >= cutoff:
                continue
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
            removed.append(p.name)
        except OSError:
            continue
    return removed


class Lifecycle:
    def __init__(
        self,
        store: Store,
        *,
        registry: Registry | None = None,
        max_notebooks: int = 30,
        slug_pattern: str = _DEFAULT_SLUG_PATTERN,
        reserved_slugs: Sequence[str] = ("admin", "tmp", "archive", "proposed"),
    ):
        self.store = store
        self.root = store.root
        self.registry = registry or store.registry
        self.max_notebooks = max_notebooks
        self.slug_re = re.compile(slug_pattern)
        self.reserved = frozenset(reserved_slugs)

    @classmethod
    def from_config(cls, cfg: Config, store: Store | None = None) -> Lifecycle:
        wc = cfg.notebook_creation
        return cls(
            store or Store.from_config(cfg),
            max_notebooks=cfg.limits.max_notebooks,
            slug_pattern=wc.slug_pattern,
            reserved_slugs=wc.reserved_slugs,
        )

    def cleanup_tmp(self) -> list[str]:
        return cleanup_tmp(self.root)

    # == create =============================================================
    def create_notebook(
        self,
        actor: Actor,
        *,
        slug: str,
        name: str,
        description: str,
        scope: str,
        rationale: str,
        preset: str | None = None,
        types: Sequence[Any] | None = None,
        confirm_distinct: bool = False,
    ) -> CreateResult:
        if not actor.can("notebook_creation"):
            raise Forbidden(
                f"actor {actor.name!r} may not create notebooks (policy: {actor.notebook_creation})"
            )
        direct = actor.notebook_creation == "direct"
        errors, specs = self._check_fields(
            slug=slug, name=name, description=description, scope=scope,
            rationale=rationale, preset=preset, types=types,
        )  # fmt: skip
        with self._registry_lock():
            if (state := self.registry.status_of(slug)) is not None:
                errors.append(
                    Violation("slug", "error", f"slug {slug!r} is already taken ({state})")
                )
            if errors:
                raise Invalid("; ".join(map(str, errors)), errors)
            self._check_capacity()
            if not direct:
                self._check_pending(actor.name)
            if not confirm_distinct:
                found = self._similar(slug, name, description, scope, actor)
                if found:
                    raise SimilarExists(found)
            dest_dir = "notebooks" if direct else "_proposed"
            meta: dict[str, Any] = {
                "name": name.strip(),
                "description": description.strip(),
                "scope": scope.strip(),
            }
            if preset:
                meta["preset"] = preset
                meta["types"] = [t.name for t in specs]
            else:
                meta["types"] = [self._type_entry(t) for t in specs]
            meta["status"] = "active" if direct else "proposed"
            meta["created"] = {"by": actor.name, "label": actor.label, "at": utc_now_iso()}
            meta["rationale"] = rationale.strip()
            if confirm_distinct:
                meta["confirm_distinct"] = True
            log_line = f"create {slug} rationale: {_oneline(rationale)}" + (
                " (confirm_distinct)" if confirm_distinct else ""
            )
            dest = self.root / dest_dir / slug
            self._assemble_and_publish(dest, meta, specs, _who(actor), log_line)
            warnings = self.store.commit_paths(
                [dest],
                actor.name,
                f"notebook({slug}): create notebook ({meta['status']})" + _tag(actor),
            )
        return CreateResult(
            "created" if direct else "proposed", slug, f"{dest_dir}/{slug}", warnings
        )

    # -- field validation ------------------------------------------------
    def _check_fields(
        self,
        *,
        slug: str,
        name: str,
        description: str,
        scope: str,
        rationale: str,
        preset: str | None,
        types: Sequence[Any] | None,
    ) -> tuple[list[Violation], list[TypeSpec]]:
        errs: list[Violation] = []

        def bad(rule: str, msg: str) -> None:
            errs.append(Violation(rule, "error", msg))

        if not isinstance(slug, str) or not self.slug_re.fullmatch(slug):
            bad("slug", f"slug must match {self.slug_re.pattern}")
        elif slug in self.reserved:
            bad("slug", f"slug {slug!r} is reserved")
        elif not is_slug(slug):
            bad("slug", "slug may only contain a-z, 0-9 and '-'")
        n = len((name or "").strip())
        if not 3 <= n <= 80:
            bad("name", f"name must be 3-80 characters, got {n}")
        n = len((description or "").strip())
        if not 40 <= n <= 300:
            bad("description", f"description must be 40-300 characters, got {n}")
        if not (scope or "").strip():
            bad("scope", "scope is required: what to write here and what not")
        if not (rationale or "").strip():
            bad("rationale", "rationale is required: why no existing notebook fits")
        specs: list[TypeSpec] = []
        if preset and types:
            bad("types", "pass either preset or types, not both")
        elif preset:
            p = self.registry.preset(preset)
            if p is None:
                known = ", ".join(sorted(self.registry.presets()))
                bad("preset", f"unknown preset {preset!r} (known: {known})")
            else:
                specs = list(p.types)
        elif types:
            specs = self._parse_types(types, errs)
        else:
            bad("types", "either preset or types is required")
        if len(specs) > MAX_TYPES:
            bad("types", f"at most {MAX_TYPES} types, got {len(specs)}")
        seen: dict[str, str] = {}
        for t in specs:
            d = t.dir or default_type_dir(t.name)
            if (other := seen.get(d.lower())) is not None:
                bad("types", f"types {other!r} and {t.name!r} share the directory {d!r}")
            seen[d.lower()] = t.name
        return errs, specs

    @staticmethod
    def _parse_types(types: Sequence[Any], errs: list[Violation]) -> list[TypeSpec]:
        out: list[TypeSpec] = []
        names: set[str] = set()
        for raw in types:
            d = raw if isinstance(raw, dict) else {"name": raw}
            nm = d.get("name")
            if not isinstance(nm, str) or not _NAME_RE.fullmatch(nm):
                errs.append(Violation("types", "error", f"invalid type name {clip_name(nm)}"))
                continue
            if nm.lower() in names:
                errs.append(Violation("types", "error", f"duplicate type {clip_name(nm)}"))
                continue
            names.add(nm.lower())
            if not str(d.get("description") or "").strip():
                errs.append(Violation("types", "error", f"type {clip_name(nm)} needs a description"))
            dr = d.get("dir")
            if dr is not None and not re.fullmatch(r"[^\W_]+(-[^\W_]+)*", str(dr)):
                errs.append(Violation("types", "error", f"bad directory {clip_name(dr)} for type {clip_name(nm)}"))
                continue
            if d.get("stale_after") is not None and not stale_after_ok(d["stale_after"]):
                errs.append(_bad_stale_after(nm, d["stale_after"]))
                continue
            out.append(
                TypeSpec(
                    nm,
                    str(d.get("description") or "").strip(),
                    dr,
                    tuple(str(f) for f in d.get("fields") or ()),
                    tuple(str(r) for r in d.get("required") or ()),
                    None if d.get("stale_after") is None else str(d["stale_after"]),
                )
            )
        return out

    @staticmethod
    def _type_entry(t: TypeSpec) -> dict[str, Any]:
        e: dict[str, Any] = {
            "name": t.name,
            "description": t.description,
            "dir": t.dir or default_type_dir(t.name),
        }
        if t.fields:
            e["fields"] = list(t.fields)
        if t.required:
            e["required"] = list(t.required)
        if t.stale_after:
            e["stale_after"] = t.stale_after
        return e

    # -- capacity, duplicates --------------------------------------------
    def _registry_lock(self):
        return self.store.lock("registry.lock")

    def _bundles(self, sub: str) -> Iterator[tuple[str, dict[str, Any]]]:
        base = self.root / sub
        if not base.is_dir():
            return
        for d in sorted(base.iterdir()):
            meta = self._load(d / ".okf" / "notebook.yaml")
            if d.is_dir() and meta is not None:
                yield d.name, meta

    @staticmethod
    def _load(path: Path) -> dict[str, Any] | None:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            return None
        return data if isinstance(data, dict) else None

    def _check_capacity(self, extra: int = 1) -> None:
        n = sum(1 for _ in self._bundles("notebooks")) + sum(1 for _ in self._bundles("_proposed"))
        if n + extra > self.max_notebooks:
            raise LimitExceeded(
                f"max_notebooks ({self.max_notebooks}) reached: {n} active or proposed"
            )

    def _check_pending(self, author: str) -> None:
        n = sum(
            1 for it in self._pending_all() if it.author == author
        )
        if n >= PENDING_LIMIT:
            raise LimitExceeded(
                f"{author} already has {n} pending proposals (limit {PENDING_LIMIT})"
            )

    def _similar(
        self, slug: str, name: str, description: str, scope: str, actor: Actor
    ) -> list[dict[str, Any]]:
        out = []
        for status, sub in (("active", "notebooks"), ("proposed", "_proposed")):
            for s, m in self._bundles(sub):
                reasons = []
                if _oneline(str(m.get("name", ""))).lower() == _oneline(name).lower():
                    reasons.append("same name")
                elif _jaccard(str(m.get("name", "")), name) >= 0.6:
                    reasons.append("similar name")
                if _jaccard(str(m.get("description", "")), description) >= 0.5:
                    reasons.append("similar description")
                if _jaccard(str(m.get("scope", "")), scope) >= 0.5:
                    reasons.append("similar scope")
                if reasons and status == "proposed" and not self._may_see(actor, m):
                    # story 15: someone else's pending proposal is not described to others
                    out.append({"status": status, "reasons": reasons})
                elif reasons:
                    out.append(
                        {
                            "slug": s,
                            "name": str(m.get("name", s)),
                            "description": str(m.get("description", "")),
                            "scope": str(m.get("scope", "")),
                            "status": status,
                            "reasons": reasons,
                        }
                    )
        return out

    @staticmethod
    def _may_see(actor: Actor, meta: dict[str, Any]) -> bool:
        created = meta.get("created")
        by = created.get("by") if isinstance(created, dict) else None
        return actor.name in ("human", by)

    # -- assembly --------------------------------------------------------
    def _assemble_and_publish(
        self,
        dest: Path,
        meta: dict[str, Any],
        specs: Sequence[TypeSpec],
        actor: str,
        log_line: str,
        before_publish: Callable[[Path], None] | None = None,
    ) -> None:
        tmp_root = self.root / ".tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        tmp = tmp_root / uuid.uuid4().hex
        try:
            (tmp / ".okf" / "templates").mkdir(parents=True)
            (tmp / ".okf" / "okf-base.yaml").write_text(
                _dump({"okf_version": OKF_VERSION, "reserved_files": ["index.md", "log.md"]}),
                encoding="utf-8",
            )
            (tmp / ".okf" / "notebook.yaml").write_text(_dump(meta), encoding="utf-8")
            for t in specs:
                (tmp / (t.dir or default_type_dir(t.name))).mkdir(exist_ok=True)
                self._write_template(tmp, t)
            self._write_index(tmp, meta)
            (tmp / "log.md").write_text(
                f"# Log\n\n- {utc_now_iso()} {actor} {log_line}\n", encoding="utf-8"
            )
            if before_publish:
                before_publish(tmp)
            self._make_metadata_public(tmp)
            errors = [v for v in self.validate_bundle(tmp) if v.level == "error"]
            if errors:
                raise Invalid("; ".join(map(str, errors)), errors)
            if dest.exists():
                raise Invalid(f"{dest.relative_to(self.root)} already exists")
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.rename(tmp, dest)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

    @staticmethod
    def _make_metadata_public(bundle: Path) -> None:
        """index.md, log.md and everything under .okf/ end at PUBLIC_MODE whatever the umask or source."""
        for p in (bundle / "index.md", bundle / "log.md", *(bundle / ".okf").rglob("*")):
            if p.is_file() and not p.is_symlink():
                p.chmod(PUBLIC_MODE)

    @staticmethod
    def _write_template(bundle: Path, t: TypeSpec) -> None:
        keys = list(dict.fromkeys([*(t.fields or CORE_PRESET.types[0].fields[:4]), *t.required]))
        fm = _dump({k: "" for k in keys}) if keys else ""
        atomic_write(
            bundle / ".okf" / "templates" / f"{t.name}.md", f"---\n{fm}---\n", mode=PUBLIC_MODE
        )

    @staticmethod
    def _write_index(bundle: Path, meta: dict[str, Any]) -> None:
        text = f'---\nokf_version: "{OKF_VERSION}"\n---\n# {meta["name"]}\n'
        if meta.get("description"):
            text += f"\n{meta['description']}\n"
        atomic_write(bundle / "index.md", text, mode=PUBLIC_MODE)

    # == bundle validation ====================================================
    def validate_bundle(self, bundle: Path, *, audit: bool = False) -> list[Violation]:
        """Structure of a bundle plus every concept file in it."""
        v: list[Violation] = []
        meta = self._load(bundle / ".okf" / "notebook.yaml")
        if meta is None:
            return [Violation("notebook", "error", ".okf/notebook.yaml is missing or invalid")]
        for rel in ("index.md", "log.md"):
            if not (bundle / rel).is_file():
                v.append(Violation("bundle", "error", f"{rel} is missing"))
        types = self.registry.types(bundle)
        specs = self.registry._types(meta)
        if not specs:
            v.append(Violation("types", "error", "notebook declares no types"))
        dirs: dict[str, str] = {}
        for t in specs:
            if t.stale_after is not None and not stale_after_ok(t.stale_after):
                v.append(_bad_stale_after(t.name, t.stale_after))
            d = (t.dir or default_type_dir(t.name)).lower()
            if d in dirs:
                v.append(
                    Violation("types", "error", f"types {dirs[d]!r} and {t.name!r} share a directory")
                )
            dirs[d] = t.name
        for d in sorted(bundle.iterdir()):
            if d.name.startswith(".") or not d.is_dir():
                continue
            if d.is_symlink():
                v.append(Violation("bundle", "error", f"{d.name} is a symlink"))
                continue
            for f in sorted(d.glob("*.md")):
                if f.is_symlink() or not f.is_file():
                    v.append(Violation("bundle", "error", f"{d.name}/{f.name} is not a regular file"))
                    continue
                cid = f"/{d.name}/{f.stem}"
                ctx = Context(bundle, cid, types, self.store.max_concept_bytes, audit)
                for x in validate_file(f.read_bytes(), ctx):
                    v.append(Violation(x.rule, x.level, f"{cid}: {x.message}"))
        return v

    def validate(
        self, notebook: str | None = None, *, only_cid: str | None = None, run_okflint: bool = True
    ) -> ValidationReport:
        """Audit mode over every file (also hand edits); active and proposed, or one slug.

        With `only_cid`, only the findings about that concept are kept."""
        if notebook:
            targets = [(notebook, self.registry.bundle_of(notebook)[0])]
        else:
            targets = [
                (s, self.root / sub / s)
                for sub in ("notebooks", "_proposed")
                for s, _ in self._bundles(sub)
            ]
        findings: list[Finding] = []
        for slug, bundle in targets:
            for x in self.validate_bundle(bundle, audit=True):
                cid, _, msg = x.message.partition(": ")
                if cid.startswith("/"):
                    findings.append(Finding(slug, cid, Violation(x.rule, x.level, msg)))
                else:
                    findings.append(Finding(slug, "", x))
        if only_cid is not None:
            findings = [f for f in findings if f.cid == only_cid]
        out, ok = None, True
        exe = shutil.which("okflint") if run_okflint else None
        if exe:
            chunks = []
            for slug, bundle in targets:
                r = subprocess.run(
                    [exe, str(bundle)], capture_output=True, text=True, check=False, timeout=120
                )
                ok = ok and r.returncode == 0
                chunks.append(f"[{slug}] exit {r.returncode}\n{(r.stdout + r.stderr).strip()}")
            out = "\n".join(chunks)
        return ValidationReport(findings, [s for s, _ in targets], out, ok)

    # == pending / approve / reject ===========================================
    def _pending_all(self) -> list[PendingItem]:
        items = []
        for slug, m in self._bundles("_proposed"):
            c = m.get("created") if isinstance(m.get("created"), dict) else {}
            items.append(
                PendingItem(
                    "notebook", slug, str(m.get("name", slug)), str(m.get("description", "")),
                    str(c.get("by", "")), str(m.get("rationale", "")), str(c.get("at", "")),
                    bool(m.get("confirm_distinct")),
                )
            )  # fmt: skip
        base = self.root / "_proposed"
        for f in sorted(base.glob("*.type-*.yaml")) if base.is_dir() else ():
            d = self._load(f)
            if d and isinstance(d.get("type"), dict):
                items.append(
                    PendingItem(
                        "type", str(d.get("notebook", "")), str(d["type"].get("name", "")),
                        str(d["type"].get("description", "")), str(d.get("by", "")),
                        str(d.get("rationale", "")), str(d.get("at", "")),
                    )
                )  # fmt: skip
        return items

    def pending(self, author: str | None = None) -> list[PendingItem]:
        return [i for i in self._pending_all() if author is None or i.author == author]

    def _proposed_dir(self, slug: str) -> Path:
        d = self.root / "_proposed" / slug
        if not is_slug(slug) or not (
            d / ".okf" / "notebook.yaml"
        ).is_file():
            raise NotebookNotFound(f"no pending proposal {slug!r}")
        return d

    def _log(self, bundle: Path, actor: str, line: str) -> None:
        log = bundle / "log.md"
        old = log.read_text(encoding="utf-8") if log.exists() else "# Log\n\n"
        atomic_write(log, old + f"- {utc_now_iso()} {actor} {line}\n", mode=PUBLIC_MODE)

    def _edit_meta(self, bundle: Path, fn: Callable[[dict[str, Any]], None]) -> None:
        path = bundle / ".okf" / "notebook.yaml"
        meta = self._load(path) or {}
        fn(meta)
        atomic_write(path, _dump(meta), mode=PUBLIC_MODE)

    def approve(self, slug: str) -> CreateResult:
        # the notebook lock keeps an author's in-flight write from landing in a moved bundle
        with self._registry_lock(), self.store.lock(f"{slug}.lock"):
            src = self._proposed_dir(slug)
            dest = self.root / "notebooks" / slug
            if dest.exists():
                raise Invalid(f"notebooks/{slug} already exists")
            self._check_active_capacity()
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.rename(src, dest)
            self._edit_meta(
                dest,
                lambda m: m.update(status="active", approved={"by": "human", "at": utc_now_iso()}),
            )
            self._log(dest, "human", f"approve {slug}")
            self._refresh_index(dest)
            warnings = self.store.commit_paths([src, dest], "human", f"notebook({slug}): approve")
        self._sync_search_index()
        return CreateResult("created", slug, f"notebooks/{slug}", warnings)

    def _refresh_index(self, bundle: Path) -> None:
        """Regenerate a bundle's index.md (after the move or vocabulary change)."""
        atomic_write(
            bundle / "index.md",
            render_index(self.registry, bundle.name, bundle),
            mode=PUBLIC_MODE,
        )

    def _sync_search_index(self) -> None:
        """Reconcile the search cache with the files; it is a cache, so never fatal."""
        try:
            self.store.index.sync()
        except (sqlite3.Error, OSError):
            pass

    def _check_active_capacity(self) -> None:
        n = sum(1 for _ in self._bundles("notebooks")) + sum(1 for _ in self._bundles("_proposed"))
        # a proposal is already counted; restore/adopt use _check_capacity(1)
        if n > self.max_notebooks:
            raise LimitExceeded(f"max_notebooks ({self.max_notebooks}) exceeded")

    def reject(self, slug: str, reason: str) -> CreateResult:
        if not (reason or "").strip():
            raise Invalid("a reason is required", [Violation("reason", "error", "reason is required")])
        with self._registry_lock(), self.store.lock(f"{slug}.lock"):
            src = self._proposed_dir(slug)
            dest = self.root / "_archive" / f"{slug}-{_today()}"
            if dest.exists():
                raise Invalid(f"{dest.name} already exists in _archive")
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.rename(src, dest)
            at = utc_now_iso()
            reason = _oneline(reason)
            self._edit_meta(
                dest,
                lambda m: m.update(
                    status="archived", rejected={"reason": reason, "by": "human", "at": at}
                ),
            )
            self._log(dest, "human", f"reject {slug} reason: {reason}")
            warnings = self.store.commit_paths(
                [src, dest], "human", f"notebook({slug}): reject proposal"
            )
        self._sync_search_index()
        return CreateResult("rejected", slug, f"_archive/{dest.name}", warnings)

    # == archive / restore =====================================================
    def archive(self, slug: str) -> CreateResult:
        if not is_slug(slug):
            raise NotebookNotFound(f"active notebook {slug!r} not found")
        # the notebook lock keeps an in-flight write from landing in a moved bundle
        with self._registry_lock(), self.store.lock(f"{slug}.lock"):
            src = self.root / "notebooks" / slug
            if not (src / ".okf" / "notebook.yaml").is_file():
                raise NotebookNotFound(f"active notebook {slug!r} not found")
            dest = self.root / "_archive" / f"{slug}-{_today()}"
            if dest.exists():
                raise Invalid(f"{dest.name} already exists in _archive")
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.rename(src, dest)
            self._edit_meta(
                dest, lambda m: m.update(status="archived", archived={"by": "human", "at": utc_now_iso()})
            )
            self._log(dest, "human", f"archive {slug}")
            warnings = self.store.commit_paths([src, dest], "human", f"notebook({slug}): archive")
        self._sync_search_index()
        return CreateResult("archived", slug, f"_archive/{dest.name}", warnings)

    def restore(self, slug: str) -> CreateResult:
        if not is_slug(slug):
            raise NotebookNotFound(f"archived notebook {slug!r} not found")
        with self._registry_lock(), self.store.lock(f"{slug}.lock"):
            try:
                src, status = self.registry.bundle_of(slug)
            except NotebookNotFound:
                raise NotebookNotFound(f"archived notebook {slug!r} not found") from None
            if status == "rejected":
                raise Invalid(f"{slug!r} is a rejected proposal; submit a new one or adopt a bundle")
            if status != "archived":
                raise Invalid(f"{slug!r} is {status}, not archived")
            self._check_capacity()
            dest = self.root / "notebooks" / slug
            if dest.exists():
                raise Invalid(f"notebooks/{slug} already exists")
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.rename(src, dest)

            def fn(m: dict[str, Any]) -> None:
                m["status"] = "active"
                m.pop("archived", None)
                m["restored"] = {"by": "human", "at": utc_now_iso()}

            self._edit_meta(dest, fn)
            self._log(dest, "human", f"restore {slug}")
            self._refresh_index(dest)
            warnings = self.store.commit_paths([src, dest], "human", f"notebook({slug}): restore")
        return CreateResult("created", slug, f"notebooks/{slug}", warnings)

    # == adopt =================================================================
    def adopt(self, path: Path | str, slug: str | None = None) -> CreateResult:
        """Copy an existing OKF bundle under management; adds notebook.yaml if absent."""
        src = Path(path)
        if not src.is_dir():
            raise Invalid(f"{src} is not a directory")
        slug = slug or re.sub(r"[^a-z0-9-]+", "-", src.resolve().name.lower()).strip("-")
        errs: list[Violation] = []
        if not self.slug_re.fullmatch(slug):
            errs.append(Violation("slug", "error", f"slug must match {self.slug_re.pattern}"))
        elif slug in self.reserved:
            errs.append(Violation("slug", "error", f"slug {slug!r} is reserved"))
        for p in src.rglob("*"):
            if p.is_symlink():
                errs.append(Violation("bundle", "error", f"symlink in bundle: {p.relative_to(src)}"))
        with self._registry_lock():
            if (state := self.registry.status_of(slug)) is not None:
                errs.append(Violation("slug", "error", f"slug {slug!r} is already taken ({state})"))
            if errs:
                raise Invalid("; ".join(map(str, errs)), errs)
            self._check_capacity()
            tmp_root = self.root / ".tmp"
            tmp_root.mkdir(parents=True, exist_ok=True)
            tmp = tmp_root / uuid.uuid4().hex
            dest = self.root / "notebooks" / slug
            try:
                shutil.copytree(src, tmp, ignore=shutil.ignore_patterns(".git", ".obsidian"))
                self._prepare_adopted(tmp, slug, src)
                self._make_metadata_public(tmp)
                errors = [v for v in self.validate_bundle(tmp, audit=True) if v.level == "error"]
                if errors:
                    raise Invalid("; ".join(map(str, errors)), errors)
                if dest.exists():
                    raise Invalid(f"notebooks/{slug} already exists")
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.rename(tmp, dest)
            except BaseException:
                shutil.rmtree(tmp, ignore_errors=True)
                raise
            warnings = self.store.commit_paths([dest], "human", f"notebook({slug}): adopt bundle")
        return CreateResult("created", slug, f"notebooks/{slug}", warnings)

    def _prepare_adopted(self, tmp: Path, slug: str, src: Path) -> None:
        (tmp / ".okf").mkdir(exist_ok=True)
        wy = tmp / ".okf" / "notebook.yaml"
        meta = self._load(wy) if wy.is_file() else None
        if meta is None:
            found: dict[str, str] = {}  # type -> dir
            for d in sorted(tmp.iterdir()):
                if d.name.startswith(".") or not d.is_dir():
                    continue
                for f in sorted(d.glob("*.md")):
                    t = read_frontmatter(f).get("type")
                    if isinstance(t, str) and t:
                        found.setdefault(t, d.name)
            title = slug_title(slug)
            meta = {
                "name": title,
                "description": f"Adopted OKF bundle {slug}",
                "scope": "Adopted bundle; scope not described yet",
                "types": [{"name": t, "dir": d} for t, d in found.items()],
            }
        meta["status"] = "active"
        meta["adopted"] = {"by": "human", "at": utc_now_iso(), "from": src.name}
        meta.setdefault("created", {"by": "human", "at": utc_now_iso()})
        wy.write_text(_dump(meta), encoding="utf-8")
        if not (tmp / ".okf" / "okf-base.yaml").is_file():
            (tmp / ".okf" / "okf-base.yaml").write_text(
                _dump({"okf_version": OKF_VERSION, "reserved_files": ["index.md", "log.md"]}),
                encoding="utf-8",
            )
        if not (tmp / "index.md").is_file():
            self._write_index(tmp, meta)
        if not (tmp / "log.md").is_file():
            (tmp / "log.md").write_text("# Log\n\n", encoding="utf-8")
        self._log(tmp, "human", f"adopt {slug} from {src.name}")

    # == types ==================================================================
    def define_type(
        self,
        actor: Actor,
        notebook: str,
        *,
        name: str,
        description: str,
        fields: Sequence[str] = (),
        required: Sequence[str] = (),
        stale_after: str | None = None,
        rationale: str = "",
    ) -> TypeResult:
        """Add a Type under the creation policy: direct applies, proposal files a request."""
        if not actor.can("notebook_creation"):
            raise Forbidden(f"actor {actor.name!r} may not define types")
        direct = actor.notebook_creation == "direct"
        errs: list[Violation] = []
        spec = self._parse_types(
            [
                {
                    "name": name,
                    "description": description,
                    "fields": list(fields),
                    "required": list(required),
                    "stale_after": stale_after,
                }
            ],
            errs,
        )
        if not direct and not (rationale or "").strip():
            errs.append(Violation("rationale", "error", "rationale is required for a proposal"))
        with self._registry_lock():
            bundle, status = self.registry.bundle_of(notebook)
            if status != "active":
                raise Invalid(f"notebook {notebook!r} is {status}; types change only in active ones")
            if spec:
                errs += self._type_conflicts(bundle, spec[0])
            if errs:  # the violations carry the (clipped) details; do not echo them twice
                raise Invalid(f"type definition is invalid ({len(errs)} violation(s))", errs)
            t = spec[0]
            if direct:
                with self.store.lock(f"{notebook}.lock"):
                    self._add_type(bundle, t)
                    self._log(bundle, _who(actor), f"type-define {t.name}")
                warnings = self.store.commit_paths(
                    [bundle], actor.name, f"notebook({notebook}): define type {t.name}" + _tag(actor)
                )
                return TypeResult("defined", notebook, t.name, warnings)
            self._check_pending(actor.name)
            f = self.root / "_proposed" / f"{notebook}.type-{t.name}.yaml"
            if f.exists():
                raise Invalid(f"a proposal for type {t.name!r} in {notebook!r} already exists")
            f.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(
                f,
                _dump(
                    {
                        "notebook": notebook,
                        "type": self._type_entry(t),
                        "rationale": rationale.strip(),
                        "by": actor.name,
                        "at": utc_now_iso(),
                    }
                ),
                mode=PUBLIC_MODE,
            )
            warnings = self.store.commit_paths(
                [f], actor.name, f"notebook({notebook}): propose type {t.name}" + _tag(actor)
            )
        return TypeResult("proposed", notebook, t.name, warnings)

    def _type_conflicts(self, bundle: Path, t: TypeSpec) -> list[Violation]:
        meta = self._load(bundle / ".okf" / "notebook.yaml") or {}
        out = []
        d = t.dir or default_type_dir(t.name)
        for e in self.registry._types(meta):
            if e.name.lower() == t.name.lower():
                out.append(Violation("types", "error", f"type {e.name!r} already exists"))
            if (e.dir or default_type_dir(e.name)).lower() == d.lower():
                out.append(Violation("types", "error", f"directory {d!r} is used by {e.name!r}"))
        return out

    def _add_type(self, bundle: Path, t: TypeSpec) -> None:
        def fn(m: dict[str, Any]) -> None:
            types = m.get("types")
            if isinstance(types, dict):
                m["types"] = [{"name": k, **(v if isinstance(v, dict) else {})} for k, v in types.items()]
            m.setdefault("types", [])
            m["types"].append(self._type_entry(t))

        self._edit_meta(bundle, fn)
        (bundle / (t.dir or default_type_dir(t.name))).mkdir(exist_ok=True)
        self._write_template(bundle, t)
        self._refresh_index(bundle)

    def _type_request(self, slug: str, name: str) -> tuple[Path, dict[str, Any]]:
        f = self.root / "_proposed" / f"{slug}.type-{name}.yaml"
        d = self._load(f) if _NAME_RE.fullmatch(name or "") else None
        if d is None or not isinstance(d.get("type"), dict):
            raise NotebookNotFound(f"no pending type proposal {name!r} for {slug!r}")
        return f, d

    def approve_type(self, slug: str, name: str) -> TypeResult:
        with self._registry_lock():
            f, d = self._type_request(slug, name)
            bundle, status = self.registry.bundle_of(slug)
            if status != "active":
                raise Invalid(f"notebook {slug!r} is {status}")
            e = d["type"]
            t = TypeSpec(
                e["name"], e.get("description", ""), e.get("dir"),
                tuple(e.get("fields") or ()), tuple(e.get("required") or ()), e.get("stale_after"),
            )  # fmt: skip
            errs = self._type_conflicts(bundle, t)
            if errs:
                raise Invalid("; ".join(map(str, errs)), errs)
            with self.store.lock(f"{slug}.lock"):
                self._add_type(bundle, t)
                self._log(bundle, "human", f"type-approve {t.name} (proposed by {d.get('by')})")
            f.unlink()
            warnings = self.store.commit_paths(
                [bundle, f], "human", f"notebook({slug}): approve type {t.name}"
            )
        return TypeResult("defined", slug, t.name, warnings)

    def reject_type(self, slug: str, name: str, reason: str) -> TypeResult:
        if not (reason or "").strip():
            raise Invalid("a reason is required", [Violation("reason", "error", "reason is required")])
        with self._registry_lock():
            f, d = self._type_request(slug, name)
            d["rejected"] = {"reason": _oneline(reason), "by": "human", "at": utc_now_iso()}
            dest = self.root / "_archive" / f"{slug}.type-{name}.rejected-{_today()}.yaml"
            dest.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(dest, _dump(d), mode=PUBLIC_MODE)
            f.unlink()
            warnings = self.store.commit_paths(
                [f, dest], "human", f"notebook({slug}): reject type {name}"
            )
        return TypeResult("rejected", slug, name, warnings)

    def _count_notes(self, bundle: Path, type_name: str) -> int:
        n = 0
        for d in bundle.iterdir():
            if d.name.startswith(".") or d.is_symlink() or not d.is_dir():
                continue
            for f in d.glob("*.md"):
                t = read_frontmatter(f).get("type")
                if isinstance(t, str) and t.lower() == type_name.lower():
                    n += 1
        return n

    def _type_entries(self, meta: dict[str, Any], bundle: Path) -> list[dict[str, Any]]:
        return [self._type_entry(t) for t in self.registry._types(meta)]

    def _change_type(
        self, notebook: str, name: str, new: str | None
    ) -> tuple[Path, TypeSpec]:
        bundle, status = self.registry.bundle_of(notebook)
        if status not in ("active", "proposed"):
            raise Invalid(f"notebook {notebook!r} is {status}")
        meta = self._load(bundle / ".okf" / "notebook.yaml") or {}
        specs = self.registry._types(meta)
        cur = next((t for t in specs if t.name.lower() == name.lower()), None)
        if cur is None:
            raise Invalid(
                f"type {clip_name(name)} is not declared in {notebook!r}",
                [Violation("types", "error", f"unknown type {clip_name(name)}")],
            )
        n = self._count_notes(bundle, cur.name)
        if n:
            raise Invalid(
                f"{n} concept(s) of type {cur.name!r} exist; move or delete them first",
                [Violation("types", "error", f"{n} concept(s) of type {cur.name!r} exist")],
            )
        if new is not None:
            errs: list[Violation] = []
            if not _NAME_RE.fullmatch(new):
                errs.append(Violation("types", "error", f"invalid type name {clip_name(new)}"))
            elif any(t.name.lower() == new.lower() for t in specs if t is not cur):
                errs.append(Violation("types", "error", f"type {clip_name(new)} already exists"))
            if errs:
                raise Invalid("; ".join(map(str, errs)), errs)
        return bundle, cur

    def delete_type(self, notebook: str, name: str) -> TypeResult:
        with self._registry_lock(), self.store.lock(f"{notebook}.lock"):
            bundle, cur = self._change_type(notebook, name, None)

            def fn(m: dict[str, Any]) -> None:
                m["types"] = [
                    e for e in self._type_entries(m, bundle) if e["name"].lower() != cur.name.lower()
                ]

            self._edit_meta(bundle, fn)
            (bundle / ".okf" / "templates" / f"{cur.name}.md").unlink(missing_ok=True)
            d = bundle / (cur.dir or default_type_dir(cur.name))
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
            self._log(bundle, "human", f"type-delete {cur.name}")
            self._refresh_index(bundle)
            warnings = self.store.commit_paths([bundle], "human", f"notebook({notebook}): delete type {cur.name}")
        return TypeResult("deleted", notebook, cur.name, warnings)

    def rename_type(self, notebook: str, name: str, new: str) -> TypeResult:
        with self._registry_lock(), self.store.lock(f"{notebook}.lock"):
            bundle, cur = self._change_type(notebook, name, new)

            def fn(m: dict[str, Any]) -> None:
                entries = self._type_entries(m, bundle)  # materialised: dir stays fixed
                for e in entries:
                    if e["name"].lower() == cur.name.lower():
                        e["name"] = new
                m["types"] = entries

            self._edit_meta(bundle, fn)
            tpl = bundle / ".okf" / "templates"
            if (tpl / f"{cur.name}.md").is_file():
                os.replace(tpl / f"{cur.name}.md", tpl / f"{new}.md")
            self._log(bundle, "human", f"type-rename {cur.name} -> {new}")
            self._refresh_index(bundle)
            warnings = self.store.commit_paths([bundle], "human", f"notebook({notebook}): rename type {cur.name} to {new}")
        return TypeResult("renamed", notebook, new, warnings)

    # == human marking of concepts ===============================================
    def mark_concept(
        self, notebook: str, cid: str, *, status: str | None = None, verify: bool = False
    ) -> list[str]:
        """Human-only: set status stable/deprecated/draft and/or `verified` (story 26)."""
        if status is None and not verify:
            raise Invalid("nothing to do: pass a status and/or verify")
        if status is not None and status not in _STATUSES:
            raise Invalid(f"status must be one of {', '.join(_STATUSES)}")
        cur = self.store.read_concept(notebook, cid)
        fm = dict(cur.frontmatter)
        if status is not None:
            fm["status"] = status
        if verify:
            fm["verified"] = _today()
        return self.store.update_concept(
            notebook, cid, base_etag=cur.etag, actor="human", frontmatter=fm,
            keep_generated=True,
        ).warnings


__all__ = [
    "PENDING_LIMIT",
    "CreateResult",
    "Finding",
    "Forbidden",
    "Lifecycle",
    "LimitExceeded",
    "PendingItem",
    "SimilarExists",
    "TypeResult",
    "ValidationReport",
    "cleanup_tmp",
    "human_actor",
]
