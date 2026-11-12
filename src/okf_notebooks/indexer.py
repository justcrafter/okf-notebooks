"""indexer: index.md generation and the FTS5 search index.

`render_index` is a pure read of the bundle's files: nothing is cached, so a hand
edit of index.md is simply overwritten by the next write.

`Index` is a disposable cache (`<root>/.index/fts.sqlite`) of every Concept of every
active Notebook. Files stay the source of truth: `sync()` reconciles the cache with
them (stat first, content hash only for files whose stat changed), `upsert()` is the
point update used by writes, and every `search`/`list` re-syncs first so hand edits
and other processes' writes are seen without a watcher. A missing, corrupt or
older-schema database is deleted and rebuilt from the files.

Public surface of the FTS part: `Index`, `Hit`, `Group`, `SearchResults`, `ListItem`,
`ListPage`, `check_fts5`, `FTS5Unavailable`, `BadCursor`.
"""

from __future__ import annotations

import base64
import contextlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from okf_notebooks.registry import Registry, is_slug, read_frontmatter
from okf_notebooks.validator import STALE_AFTER_RE

OKF_VERSION = "0.2"


def _title_of(path: Path, fm: dict) -> str:
    t = fm.get("title")
    return str(t) if t else path.stem


def render_index(registry: Registry, slug: str, bundle: Path) -> str:
    """index.md text: heading from notebook.yaml, then per-type link lists."""
    name, description = registry.notebook_title(slug)
    dirs: dict[str, str] = {}  # dir -> heading; declared types first, in order
    for t in registry.declared_types(slug):
        dirs.setdefault(t.dir, t.name)
    for d in sorted(bundle.iterdir()):
        if d.is_dir() and not d.is_symlink() and not d.name.startswith("."):
            dirs.setdefault(d.name, d.name)

    lines = [f'---\nokf_version: "{OKF_VERSION}"\n---', f"# {name}", ""]
    if description:
        lines += [description, ""]
    for d, heading in dirs.items():
        entries = []
        folder = bundle / d
        for f in folder.glob("*.md") if folder.is_dir() else ():
            if f.is_symlink() or not f.is_file():
                continue
            fm = read_frontmatter(f)
            desc = str(fm.get("description") or "").replace("\n", " ").strip()
            line = f"- [{_title_of(f, fm)}](/{d}/{f.name})"
            entries.append(
                (
                    _title_of(f, fm).lower(),
                    f.name,
                    line + (f" — {desc}" if desc else ""),
                )
            )
        if not entries:
            continue
        lines += [f"## {heading}", ""]
        lines += [e[2] for e in sorted(entries)]
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


# ---------------------------------------------------------------------------
# FTS5 index
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "2"
SNIPPET_MAX = 200
_TOKENIZE = "unicode61 remove_diacritics 2"  # no stemming, ru + en
_WEIGHTS = (10.0, 5.0, 3.0, 1.0)  # title > tags > description > body
_INACTIVE = {"proposed", "archived", "rejected"}
_STALE_DAYS = {"d": 1, "w": 7, "m": 30, "y": 365}


class FTS5Unavailable(RuntimeError):
    """The running SQLite was built without FTS5."""


class BadCursor(ValueError):
    code = "invalid"


def check_fts5() -> None:
    """Raise `FTS5Unavailable` with a clear message unless SQLite has FTS5."""
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE VIRTUAL TABLE t USING fts5(a)")
    except sqlite3.Error as e:
        raise FTS5Unavailable(
            f"this SQLite ({sqlite3.sqlite_version}) lacks FTS5 support ({e}); "
            "okf-notebooks needs a Python/SQLite build with FTS5 enabled"
        ) from None
    finally:
        con.close()


@dataclass(frozen=True)
class Hit:
    notebook: str
    id: str
    title: str
    type: str
    description: str
    snippet: str
    status: str
    stale: bool


@dataclass(frozen=True)
class Group:
    notebook: str
    results: list[Hit]


@dataclass(frozen=True)
class SearchResults:
    """Hits grouped by notebook, best-ranked group first."""

    groups: list[Group] = field(default_factory=list)

    @property
    def hits(self) -> list[Hit]:
        return [h for g in self.groups for h in g.results]


@dataclass(frozen=True)
class ListItem:
    notebook: str
    id: str
    title: str
    type: str
    description: str
    status: str
    stale: bool


@dataclass(frozen=True)
class ListPage:
    items: list[ListItem]
    next_cursor: str | None


@dataclass(frozen=True)
class _Doc:
    notebook: str
    id: str
    type: str
    title: str
    description: str
    tags: list[str]
    body: str
    status: str
    mtime: int
    size: int
    content_hash: str
    updated: str  # ISO UTC: generated.at, else file mtime
    stale_after: str
    proposed: bool = False


def _split(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    rest = text[4:]
    if rest.startswith("---\n"):
        return {}, rest[4:]
    end = rest.find("\n---\n")
    if end == -1:
        return {}, text
    try:
        fm = yaml.safe_load(rest[: end + 1])
    except yaml.YAMLError:
        fm = None
    return (fm if isinstance(fm, dict) else {}), rest[end + 5 :]


def _tags(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(t).strip() for t in value if str(t).strip()]


def _stale(updated: str, stale_after: str, now: datetime) -> bool:
    m = STALE_AFTER_RE.fullmatch(stale_after or "")
    if not m or not updated:
        return False
    try:
        at = datetime.fromisoformat(updated)
    except ValueError:
        return False
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    try:
        days = int(m.group(1)) * _STALE_DAYS[m.group(2).lower()]
        return now - at > timedelta(days=days)
    except (OverflowError, ValueError):  # absurd horizon: it never comes
        return False


def _fts_query(q: str) -> str | None:
    words = re.findall(r"\w+", q, flags=re.UNICODE)
    if not words:
        return None
    return " ".join(f'"{w}"*' for w in words)


class Index:
    def __init__(self, root: Path | str, path: Path | str | None = None):
        check_fts5()
        self.root = Path(root)
        self.path = Path(path) if path else self.root / ".index" / "fts.sqlite"
        self._ready = False

    # -- public --------------------------------------------------------
    def sync(self) -> None:
        """Reconcile the cache with the files (also builds it from scratch)."""
        with self._connect() as con:
            self._sync(con)

    def upsert(self, notebook: str, cid: str, *, proposed: bool = False) -> None:
        """Point update after a write; a missing file removes the entry."""
        with self._connect(sync=False) as con:
            base = "_proposed" if proposed else "notebooks"
            path = self.root / base / notebook / (cid.lstrip("/") + ".md")
            con.execute("BEGIN IMMEDIATE")
            try:
                doc = self._read(notebook, path, proposed)
                if doc is None:
                    self._delete(con, notebook, cid)
                else:
                    self._put(con, doc)
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise

    def search(
        self,
        query: str,
        *,
        notebook: str | None = None,
        types: list[str] | None = None,
        tags: list[str] | None = None,
        status: list[str] | None = None,
        limit: int = 10,
    ) -> SearchResults:
        match = _fts_query(query)
        if match is None:
            return SearchResults()
        where, args = self._filters(notebook, types, tags, status)
        w = ", ".join(str(x) for x in _WEIGHTS)
        sql = (
            "SELECT d.notebook, d.id, d.title, d.type, d.description, d.status,"
            " d.updated, d.stale_after,"
            " snippet(fts, -1, '', '', '…', 32) AS snip"
            " FROM fts JOIN docs d ON d.rowid = fts.rowid"
            f" WHERE fts MATCH ?{where}"
            f" ORDER BY bm25(fts, {w}), d.notebook, d.id LIMIT ?"
        )
        now = datetime.now(UTC)
        with self._connect() as con:
            rows = con.execute(sql, [match, *args, max(1, limit)]).fetchall()
        groups: dict[str, list[Hit]] = {}
        for r in rows:
            groups.setdefault(r["notebook"], []).append(
                Hit(
                    r["notebook"],
                    r["id"],
                    r["title"],
                    r["type"],
                    r["description"],
                    _clip(r["snip"]),
                    r["status"],
                    _stale(r["updated"], r["stale_after"], now),
                )
            )
        return SearchResults([Group(k, v) for k, v in groups.items()])

    def list(
        self,
        *,
        notebook: str | None = None,
        types: list[str] | None = None,
        tags: list[str] | None = None,
        status: list[str] | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ListPage:
        where, args = self._filters(notebook, types, tags, status)
        if cursor:
            where += " AND (d.notebook, d.id) > (?, ?)"
            args += list(_decode_cursor(cursor))
        limit = max(1, limit)
        sql = (
            "SELECT d.notebook, d.id, d.title, d.type, d.description, d.status,"
            " d.updated, d.stale_after FROM docs d WHERE 1=1"
            f"{where} ORDER BY d.notebook, d.id LIMIT ?"
        )
        now = datetime.now(UTC)
        with self._connect() as con:
            rows = con.execute(sql, [*args, limit + 1]).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        items = [
            ListItem(
                r["notebook"],
                r["id"],
                r["title"],
                r["type"],
                r["description"],
                r["status"],
                _stale(r["updated"], r["stale_after"], now),
            )
            for r in rows
        ]
        nxt = _encode_cursor(items[-1].notebook, items[-1].id) if more else None
        return ListPage(items, nxt)

    # -- filters -------------------------------------------------------
    @staticmethod
    def _filters(notebook, types, tags, status) -> tuple[str, list[Any]]:
        where, args = "", []
        if notebook:
            where += " AND d.notebook = ?"
            args.append(notebook)
        else:  # proposed notes show up only when their notebook is asked for by name
            where += " AND d.proposed = 0"
        if types:
            where += f" AND lower(d.type) IN ({','.join('?' * len(types))})"
            args += [t.lower() for t in types]
        for tag in tags or []:
            where += (
                " AND EXISTS (SELECT 1 FROM tags g WHERE g.doc = d.rowid AND g.tag = ?)"
            )
            args.append(tag.lower())
        if status:
            where += f" AND d.status IN ({','.join('?' * len(status))})"
            args += list(status)
        else:
            where += " AND d.status != 'deprecated'"
        return where, args

    # -- db lifecycle --------------------------------------------------
    @contextlib.contextmanager
    def _connect(self, sync: bool = True):
        fresh = not self.path.exists()
        con = self._open()
        try:
            if fresh or not self._ready:
                self._sync(con)
                self._ready = True
            elif sync:
                self._sync(con)
            yield con
        finally:
            con.close()

    def _open(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in (0, 1):
            con = sqlite3.connect(self.path, timeout=15, isolation_level=None)
            con.row_factory = sqlite3.Row
            try:
                con.execute("PRAGMA journal_mode=WAL")
                if self._schema_ok(con):
                    return con
                con.close()
            except sqlite3.DatabaseError:
                con.close()
            if attempt:
                break
            self._wipe()
        raise sqlite3.DatabaseError(f"cannot create index at {self.path}")

    def _wipe(self) -> None:
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)
        self._ready = False

    @staticmethod
    def _schema_ok(con: sqlite3.Connection) -> bool:
        has_meta = con.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'meta'"
        ).fetchone()
        if has_meta:
            row = con.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
            if row and row[0] == SCHEMA_VERSION:
                con.execute("SELECT count(*) FROM fts").fetchone()  # detects damage
                return True
            return False
        if con.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]:
            return False  # some foreign / half-built database
        con.executescript(
            f"""
            BEGIN;
            CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE docs(
                notebook TEXT NOT NULL, id TEXT NOT NULL, type TEXT, title TEXT,
                description TEXT, status TEXT, mtime INTEGER, size INTEGER,
                content_hash TEXT, updated TEXT, stale_after TEXT,
                proposed INTEGER NOT NULL DEFAULT 0,
                UNIQUE(notebook, id));
            CREATE TABLE tags(doc INTEGER NOT NULL, tag TEXT NOT NULL);
            CREATE INDEX tags_by_tag ON tags(tag, doc);
            CREATE INDEX tags_by_doc ON tags(doc);
            CREATE VIRTUAL TABLE fts USING fts5(
                title, tags, description, body,
                tokenize = '{_TOKENIZE}', prefix = '2 3 4');
            INSERT INTO meta VALUES ('schema_version', '{SCHEMA_VERSION}');
            COMMIT;
            """
        )
        return True

    # -- sync ----------------------------------------------------------
    def _sync(self, con: sqlite3.Connection) -> None:
        seen: set[tuple[str, str]] = set()
        todo: list[tuple[str, Path, bool]] = []
        known = {
            (r["notebook"], r["id"]): (r["mtime"], r["size"], r["proposed"])
            for r in con.execute("SELECT notebook, id, mtime, size, proposed FROM docs")
        }
        for ws, path, proposed in self._walk():
            cid = "/" + path.parent.name + "/" + path.stem
            try:
                st = path.stat()
            except OSError:
                continue
            seen.add((ws, cid))
            if known.get((ws, cid)) != (st.st_mtime_ns, st.st_size, int(proposed)):
                todo.append((ws, path, proposed))
        gone = [k for k in known if k not in seen]
        if not todo and not gone:
            return
        con.execute("BEGIN IMMEDIATE")
        try:
            for ws, cid in gone:
                self._delete(con, ws, cid)
            for ws, path, proposed in todo:
                doc = self._read(ws, path, proposed)
                if doc is not None:
                    self._put(con, doc)
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise

    def _walk(self):
        """(notebook, file, proposed) of every Concept file under `notebooks/` and `_proposed/`."""
        for sub in ("notebooks", "_proposed"):
            base = self.root / sub
            if not base.is_dir():
                continue
            for ws in sorted(base.iterdir()):
                if ws.is_symlink() or not ws.is_dir() or not is_slug(ws.name):
                    continue
                meta = ws / ".okf" / "notebook.yaml"
                if not meta.is_file():
                    continue
                try:
                    status = (yaml.safe_load(meta.read_text("utf-8")) or {}).get("status")
                except (OSError, yaml.YAMLError, AttributeError):
                    status = None
                if status in _INACTIVE and not (sub == "_proposed" and status == "proposed"):
                    continue
                for d in sorted(ws.iterdir()):
                    if d.is_symlink() or not d.is_dir() or d.name.startswith("."):
                        continue
                    for f in sorted(d.glob("*.md")):
                        if f.is_file() and not f.is_symlink():
                            yield ws.name, f, sub == "_proposed"

    def _read(self, notebook: str, path: Path, proposed: bool = False) -> _Doc | None:
        try:
            st = path.stat()
            data = path.read_bytes()
        except OSError:
            return None
        import hashlib

        fm, body = _split(data.decode("utf-8", errors="replace"))
        gen = fm.get("generated")
        at = gen.get("at") if isinstance(gen, dict) else None
        updated = (
            str(at) if at else datetime.fromtimestamp(st.st_mtime, UTC).isoformat()
        )
        return _Doc(
            notebook=notebook,
            id="/" + path.parent.name + "/" + path.stem,
            type=str(fm.get("type") or path.parent.name),
            title=str(fm.get("title") or path.stem),
            description=str(fm.get("description") or ""),
            tags=_tags(fm.get("tags")),
            body=body,
            status=str(fm.get("status") or "draft"),
            mtime=st.st_mtime_ns,
            size=st.st_size,
            content_hash=hashlib.sha256(data).hexdigest(),
            updated=updated,
            stale_after=str(fm.get("stale_after") or ""),
            proposed=proposed,
        )

    @staticmethod
    def _delete(con: sqlite3.Connection, notebook: str, cid: str) -> None:
        row = con.execute(
            "SELECT rowid FROM docs WHERE notebook = ? AND id = ?", (notebook, cid)
        ).fetchone()
        if row:
            rid = row[0]
            con.execute("DELETE FROM fts WHERE rowid = ?", (rid,))
            con.execute("DELETE FROM tags WHERE doc = ?", (rid,))
            con.execute("DELETE FROM docs WHERE rowid = ?", (rid,))

    def _put(self, con: sqlite3.Connection, d: _Doc) -> None:
        old = con.execute(
            "SELECT rowid, content_hash FROM docs WHERE notebook = ? AND id = ?",
            (d.notebook, d.id),
        ).fetchone()
        if old and old["content_hash"] == d.content_hash:
            con.execute(
                "UPDATE docs SET mtime = ?, size = ?, proposed = ? WHERE rowid = ?",
                (d.mtime, d.size, int(d.proposed), old["rowid"]),
            )
            return
        self._delete(con, d.notebook, d.id)
        cur = con.execute(
            "INSERT INTO docs(notebook, id, type, title, description, status,"
            " mtime, size, content_hash, updated, stale_after, proposed)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                d.notebook, d.id, d.type, d.title, d.description, d.status,
                d.mtime, d.size, d.content_hash, d.updated, d.stale_after,
                int(d.proposed),
            ),
        )  # fmt: skip
        rid = cur.lastrowid
        con.execute(
            "INSERT INTO fts(rowid, title, tags, description, body) VALUES (?,?,?,?,?)",
            (rid, d.title, " ".join(d.tags), d.description, d.body),
        )
        con.executemany(
            "INSERT INTO tags(doc, tag) VALUES (?, ?)",
            [(rid, t.lower()) for t in set(d.tags)],
        )


def _clip(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= SNIPPET_MAX else text[: SNIPPET_MAX - 1] + "…"


def _encode_cursor(notebook: str, cid: str) -> str:
    raw = json.dumps([notebook, cid]).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        ws, cid = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        if isinstance(ws, str) and isinstance(cid, str):
            return ws, cid
    except (ValueError, TypeError):
        pass
    raise BadCursor("bad cursor")
