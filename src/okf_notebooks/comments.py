"""comments: Threads and Comments on Concepts, kept outside the notebooks (ADR 0002).

A Thread is a discussion on a quoted passage of one Concept; it never touches the Concept
and creates no Revision. Unlike the FTS index this database is NOT a cache: it is never
deleted or rebuilt, and its schema changes are migrations in place. Its directory carries
its own `.gitignore`, so a `git add -A` of the notebooks root cannot pick it up.

Visibility (GLOSSARY, Mention): a Thread is addressed to the Agent actors its Comments
mention; with no Mention at all it is addressed to every Agent actor.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from okf_notebooks.fsutil import utc_now_iso
from okf_notebooks.store import Invalid, NotFound

SCHEMA_VERSION = 1
MAX_BODY = 4000
MAX_QUOTE = 2000
MAX_CONTEXT = 200
STATES = ("open", "resolved")
HUMAN = "human"
# `@claude-code`, not the `@` inside an e-mail address or a word.
_MENTION_RE = re.compile(r"(?<![\w@.])@([A-Za-z][\w-]*)")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notebook TEXT NOT NULL,
    concept TEXT NOT NULL,
    quote TEXT NOT NULL,
    prefix TEXT NOT NULL DEFAULT '',
    suffix TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'resolved')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS threads_concept ON threads (notebook, concept);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES threads (id) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES comments (id) ON DELETE CASCADE,
    author TEXT NOT NULL,
    body TEXT NOT NULL,
    mentions TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS comments_thread ON comments (thread_id);
"""


def parse_mentions(body: str) -> list[str]:
    """Actor names mentioned in a Comment, in order of first appearance."""
    seen: list[str] = []
    for name in _MENTION_RE.findall(body):
        if name not in seen:
            seen.append(name)
    return seen


def _split(mentions: str) -> list[str]:
    return [m for m in mentions.split(",") if m]


class Comments:
    """The comments database. Cheap to construct: the file is created on first use."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._ready = False

    # -- connection ---------------------------------------------------------------
    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        if not self._ready:
            self._init()
        con = sqlite3.connect(self.path, timeout=15)
        try:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys = ON")
            with con:
                yield con
        finally:
            con.close()

    def _init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ignore = self.path.parent / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n")
        con = sqlite3.connect(self.path, timeout=15)
        try:
            con.execute("PRAGMA journal_mode = WAL")
            version = con.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"{self.path} has schema version {version}, newer than this server's "
                    f"{SCHEMA_VERSION}; upgrade okf-notebooks (the database is never rebuilt)"
                )
            with con:
                con.executescript(_SCHEMA)
                con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        finally:
            con.close()
        self._ready = True

    # -- shaping -----------------------------------------------------------------
    @staticmethod
    def _comment(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "parent_id": row["parent_id"],
            "author": row["author"],
            "body": row["body"],
            "mentions": _split(row["mentions"]),
            "created_at": row["created_at"],
        }

    def _thread(self, con: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        comments = [
            self._comment(c)
            for c in con.execute(
                "SELECT * FROM comments WHERE thread_id = ? ORDER BY id", (row["id"],)
            )
        ]
        mentions: list[str] = []
        for c in comments:
            mentions += [m for m in c["mentions"] if m not in mentions]
        return {
            "id": row["id"],
            "notebook": row["notebook"],
            "concept": row["concept"],
            "quote": row["quote"],
            "prefix": row["prefix"],
            "suffix": row["suffix"],
            "state": row["state"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "mentions": mentions,
            "comments": comments,
        }

    @staticmethod
    def addressed_to(thread: dict[str, Any], actor: str) -> bool:
        """Visibility rule: no Mention in the Thread, or the Actor among them."""
        return not thread["mentions"] or actor in thread["mentions"]

    # -- validation --------------------------------------------------------------
    @staticmethod
    def _body(body: str, mentionable: Iterable[str]) -> tuple[str, list[str]]:
        text = body.strip() if isinstance(body, str) else ""
        if not text:
            raise Invalid("comment text must not be empty")
        if len(text) > MAX_BODY:
            raise Invalid(f"comment text is longer than {MAX_BODY} characters")
        allowed = set(mentionable)
        mentions = parse_mentions(text)
        unknown = [m for m in mentions if m not in allowed]
        if unknown:
            names = ", ".join("@" + m for m in unknown)
            raise Invalid(
                f"cannot mention {names}: only actors with the comments permission can be "
                f"mentioned ({', '.join('@' + a for a in sorted(allowed)) or 'none'})"
            )
        return text, mentions

    # -- writes ------------------------------------------------------------------
    def create_thread(
        self,
        notebook: str,
        concept: str,
        *,
        quote: str,
        prefix: str = "",
        suffix: str = "",
        body: str,
        author: str,
        mentionable: Iterable[str],
    ) -> dict[str, Any]:
        quote = quote.strip() if isinstance(quote, str) else ""
        if not quote:
            raise Invalid("quote must not be empty")
        if len(quote) > MAX_QUOTE:
            raise Invalid(f"quote is longer than {MAX_QUOTE} characters")
        text, mentions = self._body(body, mentionable)
        now = utc_now_iso()
        with self._db() as con:
            cur = con.execute(
                "INSERT INTO threads (notebook, concept, quote, prefix, suffix, state, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'open', ?, ?)",
                (notebook, concept, quote, prefix[-MAX_CONTEXT:], suffix[:MAX_CONTEXT], now, now),
            )
            tid = cur.lastrowid
            con.execute(
                "INSERT INTO comments (thread_id, parent_id, author, body, mentions, created_at) "
                "VALUES (?, NULL, ?, ?, ?, ?)",
                (tid, author, text, ",".join(mentions), now),
            )
            return self._thread(con, self._row(con, tid))

    def reply(
        self,
        thread_id: int,
        *,
        body: str,
        author: str,
        parent_id: int | None = None,
        mentionable: Iterable[str],
    ) -> dict[str, Any]:
        """Add a Comment. A reply by the Human reopens a resolved Thread; an Agent's does not."""
        text, mentions = self._body(body, mentionable)
        now = utc_now_iso()
        with self._db() as con:
            self._row(con, thread_id)
            if parent_id is None:
                # Reply to the last Comment: the tree stays a chain unless the writer picks a branch.
                last = con.execute(
                    "SELECT id FROM comments WHERE thread_id = ? ORDER BY id DESC LIMIT 1",
                    (thread_id,),
                ).fetchone()
                parent_id = last["id"] if last else None
            elif not con.execute(
                "SELECT 1 FROM comments WHERE id = ? AND thread_id = ?", (parent_id, thread_id)
            ).fetchone():
                raise NotFound(f"comment {parent_id} not found in thread {thread_id}")
            con.execute(
                "INSERT INTO comments (thread_id, parent_id, author, body, mentions, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (thread_id, parent_id, author, text, ",".join(mentions), now),
            )
            if author == HUMAN:
                con.execute(
                    "UPDATE threads SET state = 'open', updated_at = ? WHERE id = ?",
                    (now, thread_id),
                )
            else:
                con.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id))
            return self._thread(con, self._row(con, thread_id))

    def set_state(self, thread_id: int, state: str) -> dict[str, Any]:
        if state not in STATES:
            raise Invalid(f"state must be one of {', '.join(STATES)}")
        with self._db() as con:
            self._row(con, thread_id)
            con.execute(
                "UPDATE threads SET state = ?, updated_at = ? WHERE id = ?",
                (state, utc_now_iso(), thread_id),
            )
            return self._thread(con, self._row(con, thread_id))

    def delete_thread(self, thread_id: int) -> None:
        with self._db() as con:
            self._row(con, thread_id)
            con.execute("DELETE FROM threads WHERE id = ?", (thread_id,))

    # -- reads -------------------------------------------------------------------
    @staticmethod
    def _row(con: sqlite3.Connection, thread_id: int) -> sqlite3.Row:
        row = con.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        if row is None:
            raise NotFound(f"thread {thread_id} not found")
        return row

    def get(self, thread_id: int) -> dict[str, Any]:
        with self._db() as con:
            return self._thread(con, self._row(con, thread_id))

    def list(
        self,
        *,
        notebook: str | None = None,
        concept: str | None = None,
        state: str = "all",
        actor: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Threads, newest activity first. With `actor`, only those addressed to that Actor."""
        if state not in (*STATES, "all"):
            raise Invalid("state must be open, resolved or all")
        where, args = [], []
        for col, val in (("notebook", notebook), ("concept", concept)):
            if val is not None:
                where.append(f"{col} = ?")
                args.append(val)
        if state != "all":
            where.append("state = ?")
            args.append(state)
        sql = "SELECT * FROM threads"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC, id DESC"
        with self._db() as con:
            out = []
            for row in con.execute(sql, args):
                t = self._thread(con, row)
                if actor is None or self.addressed_to(t, actor):
                    out.append(t)
                    if len(out) >= limit:
                        break
            return out
