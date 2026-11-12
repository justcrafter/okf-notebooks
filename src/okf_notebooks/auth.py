"""Identity: Bearer tokens -> Actor. Actor and rights come ONLY from the token."""

from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from filelock import FileLock

from okf_notebooks.config import Config
from okf_notebooks.fsutil import atomic_write

# Actors that can hold a token. `human` acts only through the CLI.
TOKEN_ACTORS = ("claude-code", "opencode", "external-harness")
ALL_ACTORS = (*TOKEN_ACTORS, "human")
PERMISSIONS = ("read", "write", "notebook_creation", "comments", "verify", "archive")
# Granted to a token actor unless config `actors.<name>.allow` says otherwise:
# claude-code and opencode read and write; external-harness is read-only for now. Comments are
# open to every actor unless an explicit `allow` leaves them out.
_READ_WRITE = frozenset({"read", "write", "comments"})
DEFAULT_PERMISSIONS: dict[str, frozenset[str]] = {
    "claude-code": _READ_WRITE,
    "opencode": _READ_WRITE,
    "external-harness": frozenset({"read", "comments"}),
}
HUMAN_ONLY_PERMISSIONS = frozenset({"verify", "archive"})
MAX_TOKEN_LEN = 512


class AuthError(Exception):
    """Token administration error (bad actor, unknown id, ...)."""


@dataclass(frozen=True)
class Actor:
    """Resolved identity of a request. Built by the middleware, never by a tool."""

    name: str
    label: str
    token_id: str
    permissions: frozenset[str]
    notebook_creation: str  # "off" | "proposal" | "direct"
    client_version: str | None = None

    def can(self, permission: str) -> bool:
        if permission == "notebook_creation":
            # The policy (`off`/`proposal`/`direct`) decides *how*; the right to create at
            # all comes with `write` (or an explicit `notebook_creation` grant).
            may = "write" in self.permissions or "notebook_creation" in self.permissions
            return may and self.notebook_creation != "off"
        return permission in self.permissions

    @property
    def generated_by(self) -> str:
        """Value for frontmatter `generated.by`: `<actor>/<client version>`."""
        return f"{self.name}/{self.client_version or 'unknown'}"


_current_actor: contextvars.ContextVar[Actor | None] = contextvars.ContextVar(
    "okf_notebooks_actor", default=None
)


def current_actor() -> Actor | None:
    """The Actor of the request being handled, or None outside an authenticated request."""
    return _current_actor.get()


def require_actor() -> Actor:
    actor = _current_actor.get()
    if actor is None:
        raise RuntimeError("no authenticated actor in this context")
    return actor


def set_current_actor(actor: Actor | None) -> contextvars.Token:
    return _current_actor.set(actor)


def reset_current_actor(token: contextvars.Token) -> None:
    _current_actor.reset(token)


def permissions_for(config: Config, name: str) -> frozenset[str]:
    """Rights of a token actor: its config `allow`, else the defaults."""
    ac = config.actors.get(name)
    if ac is None or ac.allow is None:
        return DEFAULT_PERMISSIONS.get(name, frozenset({"read"}))
    return frozenset(ac.allow)


def mentionable_actors(config: Config) -> frozenset[str]:
    """Names that `@` can address in a Comment: the token actors allowed to use comments."""
    return frozenset(n for n in TOKEN_ACTORS if "comments" in permissions_for(config, n))


def actor_for_token(config: Config, record: dict[str, Any]) -> Actor:
    name = record["actor"]
    ac = config.actors.get(name)
    allow = permissions_for(config, name)
    wc = (ac.notebook_creation if ac and ac.notebook_creation else None) or (
        config.notebook_creation.default
    )
    return Actor(
        name=name,
        label=record["label"],
        token_id=record["id"],
        permissions=allow,
        notebook_creation=wc,
    )


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_path(config: Config) -> Path:
    p = config.auth.tokens_file
    return p if p.is_absolute() else config.root / p


class TokenStore:
    """`.auth/tokens.json`: only SHA-256 digests are stored."""

    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))["tokens"]
        except FileNotFoundError:
            return []
        except (ValueError, KeyError, TypeError) as e:
            raise AuthError(f"corrupt token store {self.path}: {e}") from e

    def _write(self, tokens: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write(self.path, json.dumps({"tokens": tokens}, indent=2), mode=0o600)

    def _lock(self) -> FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        return FileLock(str(self.path.parent / "tokens.lock"))

    def create(self, actor: str, label: str) -> tuple[str, str]:
        """Issue a token; returns (id, plaintext). The plaintext is never stored."""
        if actor == "human":
            raise AuthError("actor 'human' cannot hold a token (CLI only)")
        if actor not in TOKEN_ACTORS:
            raise AuthError(f"unknown actor '{actor}' (expected one of {', '.join(TOKEN_ACTORS)})")
        if not label.strip():
            raise AuthError("label must not be empty")
        token = "okf_" + secrets.token_urlsafe(32)
        tid = "t-" + secrets.token_hex(4)
        with self._lock():
            tokens = self._read()
            tokens.append(
                {
                    "id": tid,
                    "actor": actor,
                    "label": label.strip(),
                    "sha256": hash_token(token),
                    "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "revoked_at": None,
                }
            )
            self._write(tokens)
        return tid, token

    def list(self) -> list[dict[str, Any]]:
        """Records without digests."""
        return [{k: v for k, v in t.items() if k != "sha256"} for t in self._read()]

    def revoke(self, token_id: str) -> bool:
        """Returns False if it was already revoked; raises AuthError if unknown."""
        with self._lock():
            tokens = self._read()
            for t in tokens:
                if t["id"] == token_id:
                    if t["revoked_at"]:
                        return False
                    t["revoked_at"] = datetime.now(UTC).isoformat(timespec="seconds")
                    self._write(tokens)
                    return True
        raise AuthError(f"unknown token id '{token_id}'")

    def verify(self, presented: str) -> dict[str, Any] | None:
        """Constant-time lookup. Returns the active record, or None."""
        if not presented or len(presented) > MAX_TOKEN_LEN:
            return None
        try:
            tokens = self._read()
        except AuthError:
            return None
        digest = hash_token(presented)
        match: dict[str, Any] | None = None
        for t in tokens:  # no early exit: every record is compared
            if hmac.compare_digest(digest, str(t.get("sha256", ""))) and match is None:
                match = t
        if match is None or match.get("revoked_at") or match.get("actor") not in TOKEN_ACTORS:
            return None
        return match
