"""Server configuration: one strict YAML file, read once at startup."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from okf_notebooks.gitremote import check_remote_url


class ConfigError(Exception):
    """Raised when the config file is missing, malformed or invalid."""


_RATE_UNITS = {"s": 1, "sec": 1, "min": 60, "h": 3600, "hour": 3600}


def parse_rate(spec: str) -> tuple[int, int]:
    """'120/min' -> (120, 60): at most 120 requests per 60 seconds."""
    count, sep, unit = spec.partition("/")
    if not sep or not count.strip().isdigit() or unit.strip() not in _RATE_UNITS:
        raise ValueError(f"invalid rate '{spec}' (expected N/sec, N/min or N/hour)")
    n = int(count)
    if n < 1:
        raise ValueError(f"invalid rate '{spec}': count must be >= 1")
    return n, _RATE_UNITS[unit.strip()]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServerConfig(_Strict):
    transport: Literal["streamable-http", "stdio"] = "streamable-http"
    host: str = "0.0.0.0"
    port: int = Field(8765, ge=1, le=65535)
    path: str = "/mcp"
    allowed_hosts: list[str] = []
    allowed_origins: list[str] = []
    max_body_bytes: int = Field(262144, ge=1)
    rate_limit_per_token: str = "120/min"

    @field_validator("rate_limit_per_token")
    @classmethod
    def _rate_ok(cls, v: str) -> str:
        parse_rate(v)
        return v


class AuthConfig(_Strict):
    tokens_file: Path = Path(".auth/tokens.json")


class LimitsConfig(_Strict):
    max_notebooks: int = 30
    max_concept_bytes: int = 65536
    max_search_results: int = 50


def _yaml_off(v: object) -> object:
    """YAML 1.1 reads a bare `off` as False; the policy is spelled `off` in the config."""
    return "off" if v is False else v


class NotebookCreationConfig(_Strict):
    default: Literal["off", "proposal", "direct"] = "proposal"
    _off = field_validator("default", mode="before")(_yaml_off)
    slug_pattern: str = "^[a-z][a-z0-9-]{1,38}[a-z0-9]$"
    reserved_slugs: list[str] = ["admin", "tmp", "archive", "proposed"]

    @field_validator("slug_pattern")
    @classmethod
    def _pattern_compiles(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"invalid slug_pattern: {e}") from e
        return v


class GitConfig(_Strict):
    enabled: bool = True
    commit_per_write: bool = True
    # URL of the PRIVATE notebooks repository (never the public code repository).
    remote: str | None = None
    # Extra URLs that `remote` must not equal (the public code repo is also
    # rejected by name: okf-notebooks / mcp-okf-notebooks).
    public_code_repos: list[str] = []

    @field_validator("remote")
    @classmethod
    def _strip_remote(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else None

    @model_validator(mode="after")
    def _remote_is_private(self) -> GitConfig:
        if self.remote is not None:
            check_remote_url(self.remote, self.public_code_repos)
        return self


class IndexConfig(_Strict):
    path: Path = Path(".index/fts.sqlite")


class CommentsConfig(_Strict):
    # Threads and Comments (ADR 0002): not a cache, never rebuilt; keep it in the backups.
    path: Path = Path(".comments/threads.sqlite")


_PERMISSIONS = {"read", "write", "notebook_creation", "comments"}
_TOKEN_ACTORS = {"claude-code", "opencode", "external-harness"}


class ActorConfig(_Strict):
    # None -> default (read, write). verify/archive are human-only (CLI) and not grantable.
    allow: list[str] | None = None
    notebook_creation: Literal["off", "proposal", "direct"] | None = None
    _off = field_validator("notebook_creation", mode="before")(_yaml_off)

    @field_validator("allow")
    @classmethod
    def _allow_ok(cls, v: list[str] | None) -> list[str] | None:
        bad = [p for p in v or [] if p not in _PERMISSIONS]
        if bad:
            raise ValueError(
                f"unknown or non-grantable permission(s) {bad}; allowed: {sorted(_PERMISSIONS)}"
            )
        return v


class Config(_Strict):
    root: Path
    server: ServerConfig = ServerConfig()
    auth: AuthConfig = AuthConfig()
    limits: LimitsConfig = LimitsConfig()
    notebook_creation: NotebookCreationConfig = NotebookCreationConfig()
    git: GitConfig = GitConfig()
    index: IndexConfig = IndexConfig()
    comments: CommentsConfig = CommentsConfig()
    presets_dir: Path | None = None
    actors: dict[str, ActorConfig] = {}

    @model_validator(mode="after")
    def _actors_known(self) -> Config:
        bad = sorted(set(self.actors) - _TOKEN_ACTORS)
        if bad:
            raise ValueError(
                f"actors: unknown or tokenless actor(s) {bad}; allowed: {sorted(_TOKEN_ACTORS)}"
            )
        return self


def load_config(path: str | Path) -> Config:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise ConfigError(f"cannot read config {path}: {e}") from e
    try:
        return Config.model_validate(raw)
    except ValidationError as e:
        # Not `str(e)`: it echoes `input_value`, and with it URLs that embed credentials.
        lines = [
            f"{'.'.join(str(p) for p in d['loc']) or 'config'}: {d['msg']}"
            for d in e.errors(include_input=False, include_url=False, include_context=False)
        ]
        raise ConfigError(f"invalid config {path}:\n" + "\n".join(lines)) from None
