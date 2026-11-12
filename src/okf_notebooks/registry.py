"""registry: discovery of Notebooks, Presets and the Type -> directory mapping.

Public surface: `Registry`, the result dataclasses and `NotebookNotFound`.

Everything is read from disk on every call (no cache), so edits made by hand, by
another process or to `presets_dir` are picked up without restarting the server.

Seam with `store`: the registry owns which directory a declared Type lives in
(`Registry.declared_type_dir`). `Store` asks it first and falls back to its own
pluralising slug rule for types a notebook has not declared (ticket 03's
validator is where an undeclared type becomes an error).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from okf_notebooks.fsutil import utc_iso
from okf_notebooks.validator import TypeSpec as ValidatorTypeSpec
from okf_notebooks.validator import stale_after_ok

log = logging.getLogger("okf_notebooks.registry")

SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*$")  # the one shape every notebook slug has


def is_slug(value: object) -> bool:
    return isinstance(value, str) and SLUG_RE.fullmatch(value) is not None


def slug_title(slug: str) -> str:
    """A readable default notebook name for a slug (`kube-platform` -> `Kube Platform`)."""
    return slug.replace("-", " ").title()
_DATE_SUFFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_TOP_TAGS = 10


class NotebookNotFound(Exception):
    code = "not_found"


@dataclass(frozen=True)
class TypeSpec:
    name: str
    description: str = ""
    dir: str | None = None
    fields: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    stale_after: str | None = None


@dataclass(frozen=True)
class Preset:
    name: str
    description: str
    types: tuple[TypeSpec, ...]

    def type(self, name: str) -> TypeSpec | None:
        for t in self.types:
            if t.name.lower() == name.lower():
                return t
        return None


@dataclass(frozen=True)
class TypeInfo:
    name: str
    dir: str
    description: str
    fields: list[str]
    count: int


@dataclass(frozen=True)
class NotebookSummary:
    slug: str
    name: str
    description: str
    scope: str
    types: list[str]
    note_count: int
    last_modified: str | None  # ISO-8601 UTC, None when the notebook has no notes


@dataclass(frozen=True)
class NotebookDetail:
    slug: str
    name: str
    description: str
    scope: str
    status: str  # active | proposed | archived | rejected
    preset: str | None
    types: list[TypeInfo]
    top_tags: list[dict[str, Any]]  # [{"tag": ..., "count": ...}], most used first
    index_md: str
    note_count: int
    last_modified: str | None
    rejection_reason: str | None = None
    created: dict[str, Any] | None = None


_CORE_FIELDS = ("description", "tags", "sources", "stale_after")
CORE_PRESET = Preset(
    "core",
    "General-purpose notes: projects, decisions, playbooks and terms. Use when no more specific preset fits.",
    (
        TypeSpec(
            "Project",
            "A project or repository: what it is, its goals and boundaries",
            "projects",
            (*_CORE_FIELDS, "repo"),
        ),
        TypeSpec(
            "Decision",
            "A decision taken, with the context and the alternatives considered",
            "decisions",
            (*_CORE_FIELDS, "decided"),
        ),
        TypeSpec(
            "Playbook",
            "A repeatable procedure: steps to reach a result",
            "playbooks",
            _CORE_FIELDS,
        ),
        TypeSpec(
            "Term",
            "A term or abbreviation and what it means in this context",
            "terms",
            _CORE_FIELDS,
        ),
    ),
)


def default_type_dir(type_name: str) -> str:
    """Directory name for a type nobody declared a directory for: slug, plural."""
    s = re.sub(r"[^\w]+", "-", type_name.strip().lower(), flags=re.UNICODE)
    s = re.sub(r"[-_]+", "-", s).strip("-_")
    return s if s.endswith("s") else s + "s"


def read_frontmatter(path: Path) -> dict[str, Any]:
    """Frontmatter of a Markdown file; {} when absent or unreadable."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 3)
    if end == -1:
        return {}
    try:
        fm = yaml.safe_load(text[4 : end + 1])
    except yaml.YAMLError:
        return {}
    return fm if isinstance(fm, dict) else {}


def _load_yaml(path: Path) -> dict[str, Any] | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def _type_spec(raw: Any, name: str | None = None) -> TypeSpec | None:
    """A TypeSpec from a `types:` entry: a name, or a mapping (optionally keyed by name)."""
    if isinstance(raw, str) and name is None:
        return TypeSpec(raw)
    if name is None:
        name = raw.get("name") if isinstance(raw, dict) else None
    if not isinstance(name, str):
        return None
    d = raw if isinstance(raw, dict) else {}
    tpl = d.get("template")
    tpl = tpl if isinstance(tpl, dict) else {}
    req = d.get("required", tpl.get("required")) or ()
    stale = d.get("stale_after", tpl.get("stale_after"))
    return TypeSpec(
        name,
        str(d.get("description") or ""),
        d.get("dir") or None,
        tuple(str(f) for f in d.get("fields") or ()),
        tuple(str(r) for r in req),
        None if stale is None else str(stale),
    )


def _type_specs(decl: Any) -> list[TypeSpec]:
    """Entries of a `types:` value: a list (names or mappings) or a name -> mapping."""
    if isinstance(decl, dict):
        items = [_type_spec(v, str(k)) for k, v in decl.items()]
    else:
        items = [_type_spec(raw) for raw in decl or []]
    return [t for t in items if t]


def _iso(ts: float) -> str:
    return utc_iso(datetime.fromtimestamp(ts, UTC))


@dataclass
class _Scan:
    counts: dict[str, int] = field(default_factory=dict)  # dir -> notes
    tags: Counter = field(default_factory=Counter)
    last: float | None = None

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def last_iso(self) -> str | None:
        return None if self.last is None else _iso(self.last)


class Registry:
    def __init__(self, root: Path | str, presets_dir: Path | str | None = None):
        self.root = Path(root)
        self.presets_dir = Path(presets_dir) if presets_dir else None

    # -- presets ---------------------------------------------------------
    def presets(self) -> dict[str, Preset]:
        """Builtin `core` plus every valid `*.yaml` in presets_dir (re-read each call).

        A malformed preset file is skipped so one bad file cannot break discovery;
        the builtin `core` cannot be overridden.
        """
        found: dict[str, Preset] = {}
        if self.presets_dir and self.presets_dir.is_dir():
            for p in sorted(self.presets_dir.glob("*.y*ml")):
                data = _load_yaml(p)
                if data is None or not isinstance(data.get("types"), list):
                    continue
                types = tuple(_type_specs(data["types"]))
                if (bad := next((t for t in types if t.stale_after is not None
                                 and not stale_after_ok(t.stale_after)), None)):
                    log.warning(
                        "preset %s skipped: type %s has an invalid stale_after", p.name, bad.name
                    )
                    continue
                name = str(data.get("name") or p.stem)
                found[name] = Preset(name, str(data.get("description") or ""), types)
        found["core"] = CORE_PRESET
        return found

    def preset(self, name: str) -> Preset | None:
        return self.presets().get(name)

    # -- type -> directory -------------------------------------------------
    def declared_type_dir(self, notebook: str, type_name: str) -> str | None:
        """Directory of a type the notebook declares, else None."""
        meta = self._meta(self._find(notebook)[0])
        for t in self._types(meta):
            if t.name.lower() == type_name.strip().lower():
                return t.dir or default_type_dir(t.name)
        return None

    def types(self, bundle: Path) -> Mapping[str, ValidatorTypeSpec]:
        """Validator `TypeSource`: the Type vocabulary of a bundle (preset-resolved)."""
        return {
            t.name: ValidatorTypeSpec(t.name, t.required, t.stale_after)
            for t in self._types(self._meta(bundle))
        }

    def bundle_of(self, slug: str) -> tuple[Path, str]:
        """(directory, status) of a notebook in any state; raises NotebookNotFound."""
        return self._find(slug)

    def status_of(self, slug: str) -> str | None:
        """active | proposed | archived | rejected, or None when the slug is free."""
        try:
            return self._find(slug)[1]
        except NotebookNotFound:
            return None

    def author_of(self, slug: str) -> str | None:
        """Actor that created the notebook (proposal), from `created.by` in notebook.yaml."""
        created = self._meta(self._find(slug)[0]).get("created")
        by = created.get("by") if isinstance(created, dict) else None
        return str(by) if by else None

    # -- discovery ---------------------------------------------------------
    def list_notebooks(self) -> list[NotebookSummary]:
        out = []
        base = self.root / "notebooks"
        if not base.is_dir():
            return out
        for d in sorted(base.iterdir()):
            if not d.is_dir() or not is_slug(d.name):
                continue
            meta = _load_yaml(d / ".okf" / "notebook.yaml")
            if meta is None:
                continue
            scan = self._scan(d)
            out.append(
                NotebookSummary(
                    slug=d.name,
                    name=str(meta.get("name") or d.name),
                    description=str(meta.get("description") or ""),
                    scope=str(meta.get("scope") or ""),
                    types=[t.name for t in self._types(meta)],
                    note_count=scan.total,
                    last_modified=scan.last_iso,
                )
            )
        return out

    def describe(self, slug: str) -> NotebookDetail:
        bundle, status = self._find(slug)
        meta = self._meta(bundle)
        scan = self._scan(bundle)
        templates = bundle / ".okf" / "templates"
        types = []
        for t in self._types(meta):
            fields = list(t.fields)
            tpl = templates / f"{t.name}.md"
            if tpl.is_file():
                fields = list(read_frontmatter(tpl))
            d = t.dir or default_type_dir(t.name)
            types.append(
                TypeInfo(t.name, d, t.description, fields, scan.counts.get(d, 0))
            )
        rej = meta.get("rejected")
        try:
            index_md = (bundle / "index.md").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            index_md = ""
        created = meta.get("created")
        return NotebookDetail(
            slug=slug,
            name=str(meta.get("name") or slug),
            description=str(meta.get("description") or ""),
            scope=str(meta.get("scope") or ""),
            status=status,
            preset=meta.get("preset"),
            types=types,
            top_tags=[
                {"tag": t, "count": c} for t, c in scan.tags.most_common(_TOP_TAGS)
            ],
            index_md=index_md,
            note_count=scan.total,
            last_modified=scan.last_iso,
            rejection_reason=rej.get("reason") if isinstance(rej, dict) else None,
            created=created if isinstance(created, dict) else None,
        )

    def summary(self, slug: str) -> tuple[NotebookSummary, str]:
        """(list row, status) of a notebook in any state, e.g. a pending proposal."""
        d = self.describe(slug)
        row = NotebookSummary(
            d.slug, d.name, d.description, d.scope, [t.name for t in d.types],
            d.note_count, d.last_modified,
        )  # fmt: skip
        return row, d.status

    def notebook_title(self, slug: str) -> tuple[str, str]:
        """(name, description) of an active notebook, for index.md."""
        meta = self._meta(self._find(slug)[0])
        return str(meta.get("name") or slug), str(meta.get("description") or "")

    def declared_types(self, slug: str) -> list[TypeInfo]:
        """Declared types of a notebook in declaration order (count left at 0)."""
        meta = self._meta(self._find(slug)[0])
        return [
            TypeInfo(
                t.name,
                t.dir or default_type_dir(t.name),
                t.description,
                list(t.fields),
                0,
            )
            for t in self._types(meta)
        ]

    # -- internals -----------------------------------------------------------
    def _find(self, slug: str) -> tuple[Path, str]:
        if not is_slug(slug):
            raise NotebookNotFound(f"notebook {slug!r} not found")
        for sub, status in (("notebooks", "active"), ("_proposed", "proposed")):
            d = self.root / sub / slug
            if (d / ".okf" / "notebook.yaml").is_file():
                return d, status
        arch = self.root / "_archive"
        if arch.is_dir():
            for d in sorted(arch.iterdir(), reverse=True):
                rest = d.name[len(slug) + 1 :]
                if (
                    d.name.startswith(slug + "-")
                    and _DATE_SUFFIX_RE.match(rest)
                    and (d / ".okf" / "notebook.yaml").is_file()
                ):
                    meta = _load_yaml(d / ".okf" / "notebook.yaml") or {}
                    return d, "rejected" if "rejected" in meta else "archived"
        raise NotebookNotFound(f"notebook {slug!r} not found")

    @staticmethod
    def _meta(bundle: Path) -> dict[str, Any]:
        return _load_yaml(bundle / ".okf" / "notebook.yaml") or {}

    def _types(self, meta: dict[str, Any]) -> list[TypeSpec]:
        preset = self.preset(str(meta.get("preset") or "core"))
        out = []
        for spec in _type_specs(meta.get("types")):
            base = preset.type(spec.name) if preset else None
            if base is not None:
                spec = TypeSpec(
                    spec.name,
                    spec.description or base.description,
                    spec.dir or base.dir,
                    spec.fields or base.fields,
                    spec.required or base.required,
                    spec.stale_after or base.stale_after,
                )
            out.append(spec)
        return out

    @staticmethod
    def _scan(bundle: Path) -> _Scan:
        scan = _Scan()
        for d in sorted(bundle.iterdir()):
            if d.name.startswith(".") or d.is_symlink() or not d.is_dir():
                continue
            n = 0
            for f in sorted(d.glob("*.md")):
                if f.is_symlink() or not f.is_file():
                    continue
                n += 1
                mt = f.stat().st_mtime
                scan.last = mt if scan.last is None else max(scan.last, mt)
                tags = read_frontmatter(f).get("tags")
                if isinstance(tags, list):
                    scan.tags.update(str(t) for t in tags)
            if n:
                scan.counts[d.name] = n
        return scan
