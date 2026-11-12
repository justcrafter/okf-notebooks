"""validator: write rules, secrets scanner, server-set frontmatter fields.

Public surface: `Violation`, `TypeSpec`, `TypeSource`, `NotebookYamlTypes`,
`Context`, `validate_file`, `finalize_frontmatter`, `scan_secrets`.

The type vocabulary is read through the small `TypeSource` interface so the
notebook registry can supply it later; `NotebookYamlTypes` is the minimal
default that reads the `types:` mapping of `.okf/notebook.yaml`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Literal, Protocol

import yaml

from okf_notebooks.fsutil import utc_iso

Level = Literal["error", "warning"]

MAX_TAGS = 10
MIN_BODY_CHARS = 20
MAX_TITLE_CHARS = 200
HUMAN = "human"
# Set by the server; an agent may echo the current value but never change it.
PROTECTED_FIELDS = ("status", "generated", "type", "verified")


@dataclass(frozen=True)
class Violation:
    rule: str
    level: Level
    message: str

    def __str__(self) -> str:
        return f"{self.rule}: {self.message}"


@dataclass(frozen=True)
class TypeSpec:
    name: str
    required: tuple[str, ...] = ()
    stale_after: str | None = None


class TypeSource(Protocol):
    def types(self, bundle: Path) -> Mapping[str, TypeSpec]: ...


class NotebookYamlTypes:
    """Minimal reader of `types:` in `<bundle>/.okf/notebook.yaml`.

    Shape: `types: {Decision: {required: [owner], stale_after: 180d}}`; the
    two keys may also sit under a `template:` sub-mapping.
    """

    def types(self, bundle: Path) -> Mapping[str, TypeSpec]:
        try:
            raw = yaml.safe_load(
                (bundle / ".okf" / "notebook.yaml").read_text("utf-8")
            )
        except (OSError, yaml.YAMLError, UnicodeDecodeError):
            return {}
        decl = raw.get("types") if isinstance(raw, dict) else None
        out: dict[str, TypeSpec] = {}
        if isinstance(decl, list):  # registry shape: strings or {name: ..., ...}
            items = [
                (e["name"], e) if isinstance(e, dict) and "name" in e else (e, {})
                for e in decl
            ]
        else:
            items = list((decl or {}).items())
        for name, spec in items:
            spec = spec if isinstance(spec, dict) else {}
            tpl = spec.get("template")
            tpl = tpl if isinstance(tpl, dict) else {}
            req = spec.get("required", tpl.get("required")) or []
            stale = spec.get("stale_after", tpl.get("stale_after"))
            out[str(name)] = TypeSpec(
                str(name),
                tuple(str(r) for r in req),
                None if stale is None else str(stale),
            )
        return out


@dataclass(frozen=True)
class Context:
    bundle: Path
    cid: str
    types: Mapping[str, TypeSpec]
    max_concept_bytes: int
    audit: bool = False  # audit: broken links are warnings, not errors


# -- secrets -----------------------------------------------------------------
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (n, re.compile(p))
    for n, p in [
        ("private key", r"-----BEGIN [A-Z ]*PRIVATE KEY"),
        ("AWS access key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        (
            "GitHub token",
            r"\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}",
        ),
        ("Slack token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
        ("API key (sk-)", r"\bsk-[A-Za-z0-9_-]{20,}"),
        ("Google API key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
        ("JWT", r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+"),
        (
            "credential assignment",
            r"(?i)\b(?:api[_-]?key|secret|token|passw(?:or)?d|auth)\b[\"']?\s*[:=]\s*"
            + r"[\"']?[A-Za-z0-9/+_\-.=]{16,}",
        ),
    ]
)


STALE_AFTER_RE = re.compile(r"\s*(\d{1,4})\s*([dwmyDWMY])\s*")  # the one grammar


def stale_after_ok(value: object) -> bool:
    """True for a usable `stale_after` (`180d`, `26w`, `6m`, `2y`; at most 4 digits)."""
    return isinstance(value, str) and STALE_AFTER_RE.fullmatch(value) is not None


def clip_name(value: object, limit: int = 64) -> str:
    """repr() of a caller-supplied name, truncated so errors never echo megabytes."""
    text = str(value)
    return repr(text[:limit] + "…" if len(text) > limit else text)


def scan_secrets(text: str) -> list[Violation]:
    """Secret-looking strings; messages name the kind and line, never the value."""
    out = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for kind, pat in _SECRET_PATTERNS:
            if pat.search(line):
                out.append(
                    Violation(
                        "secret", "error", f"line {lineno} looks like a secret ({kind})"
                    )
                )
                break
    return out


# -- parsing -----------------------------------------------------------------
def _split(text: str) -> tuple[str | None, str]:
    if not text.startswith("---\n"):
        return None, text
    rest = text[4:]
    if rest.startswith("---\n"):
        return "", rest[4:]
    end = rest.find("\n---\n")
    if end == -1:
        return None, text
    return rest[: end + 1], rest[end + 5 :]


_LINK_RE = re.compile(r"(?<![\w/:.])(/[^\s)\]\"'<>]*\.md)(?![\w])")
_TAG_RE = re.compile(r"^[^\W_]+(-[^\W_]+)*$")


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def extract_links(body: str, frontmatter: Mapping[str, Any]) -> list[str]:
    """In-bundle links (`/type/slug`, no `.md`) found in the body and frontmatter, in order."""
    seen: dict[str, None] = {}
    for s in [body, *_strings(frontmatter)]:
        for link in _LINK_RE.findall(s):
            seen.setdefault(link.removesuffix(".md"))
    return list(seen)


def _link_ok(bundle: Path, link: str, cid: str) -> bool:
    if ".." in link.split("/"):
        return False
    if link.removesuffix(".md") == cid:
        return True
    target = bundle / link.lstrip("/")
    return target.is_file() and not target.is_symlink()


def _same_title(other: Path, title: str) -> bool:
    try:
        head, _ = _split(other.read_text("utf-8"))
        fm = yaml.safe_load(head) if head else None
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return False
    return isinstance(fm, dict) and fm.get("title") == title


def validate_file(data: bytes, ctx: Context) -> list[Violation]:
    """Validate a concept file as it will exist on disk. Returns all violations."""
    v: list[Violation] = []
    if len(data) > ctx.max_concept_bytes:
        v.append(
            Violation(
                "size",
                "error",
                f"{len(data)} bytes exceeds max_concept_bytes "
                f"({ctx.max_concept_bytes})",
            )
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [*v, Violation("utf8", "error", "file is not valid UTF-8")]

    head, body = _split(text)
    fm: dict[str, Any] = {}
    if head is None:
        v.append(
            Violation("yaml", "error", "frontmatter block delimited by --- is missing")
        )
    else:
        try:
            loaded = yaml.safe_load(head) if head else {}
        except yaml.YAMLError as e:
            v.append(Violation("yaml", "error", f"invalid YAML frontmatter: {e}"))
            loaded = {}
        if loaded is None:
            loaded = {}
        if isinstance(loaded, dict):
            fm = loaded
        else:
            v.append(Violation("yaml", "error", "frontmatter must be a YAML mapping"))

    if head is not None:
        v += _check_fields(fm, body, ctx)
    v += scan_secrets(text)
    return v


def _check_fields(fm: dict[str, Any], body: str, ctx: Context) -> list[Violation]:
    v: list[Violation] = []
    type_ = fm.get("type")
    spec = ctx.types.get(type_) if isinstance(type_, str) else None
    if not isinstance(type_, str) or not type_:
        v.append(Violation("type", "error", "`type` is required"))
    elif spec is None:
        known = ", ".join(sorted(ctx.types)) or "none"
        v.append(
            Violation(
                "type",
                "error",
                f"type {clip_name(type_)} is not in the notebook vocabulary (known: {known})",
            )
        )
    for key in ("title", "description"):
        val = fm.get(key)
        if not isinstance(val, str) or not val.strip():
            v.append(
                Violation(key, "error", f"`{key}` is required and must be non-empty")
            )
    title = fm.get("title")
    if isinstance(title, str) and len(title.strip()) > MAX_TITLE_CHARS:
        v.append(
            Violation(
                "title", "error", f"`title` is at most {MAX_TITLE_CHARS} characters"
            )
        )
    if spec:
        for key in spec.required:
            if fm.get(key) in (None, "", [], {}):
                v.append(
                    Violation(
                        "required-field",
                        "error",
                        f"field `{key}` is required by type {spec.name}",
                    )
                )

    stale = fm.get("stale_after")
    if stale not in (None, "") and not stale_after_ok(stale):
        v.append(
            Violation(
                "stale-after",
                "warning" if ctx.audit else "error",  # audit: foreign bundles use other formats
                "`stale_after` must be a number of days/weeks/months/years such as 180d "
                "(at most 4 digits)",
            )
        )

    tags = fm.get("tags")
    if tags is not None:
        if not isinstance(tags, list) or not all(
            isinstance(t, str) and _TAG_RE.match(t) and t == t.lower() for t in tags
        ):
            v.append(
                Violation("tags", "error", "`tags` must be a list of slug strings")
            )
        elif len(tags) > MAX_TAGS:
            v.append(
                Violation("tags", "error", f"at most {MAX_TAGS} tags, got {len(tags)}")
            )

    link_level: Level = "warning" if ctx.audit else "error"
    seen: set[str] = set()
    for s in [body, *_strings(fm)]:
        for link in _LINK_RE.findall(s):
            if link not in seen and not _link_ok(ctx.bundle, link, ctx.cid):
                v.append(
                    Violation(
                        "link",
                        link_level,
                        f"link {link} does not point to a file in this bundle",
                    )
                )
            seen.add(link)

    title = fm.get("title")
    if isinstance(title, str) and isinstance(type_, str):
        tdir = (ctx.bundle / ctx.cid.lstrip("/")).parent
        me = ctx.bundle / (ctx.cid.lstrip("/") + ".md")
        if tdir.is_dir() and any(
            p != me and _same_title(p, title) for p in tdir.glob("*.md")
        ):
            v.append(
                Violation(
                    "duplicate-title",
                    "warning",
                    f"another {type_} already has the title {title!r}",
                )
            )
    if len(body.strip()) < MIN_BODY_CHARS:
        v.append(
            Violation(
                "short-body",
                "warning",
                f"body is shorter than {MIN_BODY_CHARS} characters",
            )
        )
    return v


# -- server-set fields -------------------------------------------------------
def _version() -> str:
    try:
        return metadata.version("okf-notebooks")
    except metadata.PackageNotFoundError:
        return "0"


def finalize_frontmatter(
    *,
    current: Mapping[str, Any] | None,
    proposed: Mapping[str, Any],
    type_: str,
    title: str | None,
    spec: TypeSpec | None,
    actor: str,
    generated_by: str | None = None,
    keep_generated: bool = False,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[dict[str, Any], list[Violation]]:
    """Apply server-owned fields and agent restrictions.

    `proposed` is what the caller wants the agent-owned frontmatter to be;
    `current` is the stored frontmatter (None on create). Returns the final
    frontmatter plus forbidden-field errors and the verified-reset warning.
    """
    v: list[Violation] = []
    cur = dict(current or {})
    fm = dict(proposed)
    human = actor == HUMAN

    for field in ("type", "generated"):  # nobody edits these, human included
        if field in fm and fm[field] != (type_ if field == "type" else cur.get(field)):
            v.append(
                Violation("forbidden-field", "error", f"`{field}` is set by the server")
            )
    if not human:
        for field in ("status", "verified"):
            if field in fm and fm[field] != cur.get(field):
                v.append(
                    Violation(
                        "forbidden-field",
                        "error",
                        f"`{field}` can only be set by a human via the CLI",
                    )
                )

    fm.pop("type", None)
    fm.pop("generated", None)
    if not human:
        fm.pop("status", None)
        fm.pop("verified", None)
        for field in ("status", "verified"):
            if field in cur:
                fm[field] = cur[field]
    else:
        for field in ("status", "verified"):
            if field not in fm and field in cur:
                fm[field] = cur[field]

    if title is not None:
        fm["title"] = title
    fm["type"] = type_
    fm.setdefault("status", "draft")
    if not human and fm.get("verified") not in (None, ""):
        if fm["status"] == "deprecated":  # deprecation is a human decision
            outcome = "cleared `verified`; status stays deprecated"
        else:
            fm["status"] = "draft"
            outcome = "reset it to draft and cleared `verified`"
        del fm["verified"]
        v.append(
            Violation(
                "verified-reset",
                "warning",
                f"concept was verified; agent edit {outcome}",
            )
        )
    elif not human and current is not None and fm["status"] == "stable":
        fm["status"] = "draft"
        v.append(
            Violation(
                "status-reset",
                "warning",
                "concept was stable; agent edit reset it to draft (a human re-verifies)",
            )
        )
    stamp = utc_iso(now())
    if keep_generated and isinstance(cur.get("generated"), dict):
        fm["generated"] = cur["generated"]
    else:
        fm["generated"] = {"by": generated_by or f"{actor}/{_version()}", "at": stamp}
    if "stale_after" not in fm and spec and spec.stale_after:
        if stale_after_ok(spec.stale_after):
            fm["stale_after"] = spec.stale_after
        else:  # a hand-edited template must not make every write of the type fail
            v.append(
                Violation(
                    "stale-after",
                    "warning",
                    f"the template of type {clip_name(spec.name)} has an invalid stale_after "
                    f"({clip_name(spec.stale_after, 24)}); ignored, fix notebook.yaml",
                )
            )

    order = ["type", "title", "description"]
    ordered = {k: fm[k] for k in order if k in fm}
    ordered.update({k: x for k, x in fm.items() if k not in ordered})
    return ordered, v
