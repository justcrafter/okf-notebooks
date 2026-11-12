"""Small shared filesystem and time helpers (no dependencies on the rest of the package)."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

# File mode of bundle metadata (log.md, index.md, .okf/*). Files only: directories keep their
# umask-derived modes, so another uid reads a bundle only if the operator sets the umask
# (022) or the volume permissions accordingly (docs/deploy.md).
PUBLIC_MODE = 0o644


def atomic_write(
    path: Path,
    data: bytes | str,
    *,
    mode: int | None = None,
    tmp_dir: Path | None = None,
) -> None:
    """Write `data` to `path` so readers see the old or the new content, never a mix.

    The temporary file lives on the same volume (`tmp_dir`, default: next to `path`), is
    fsynced before `os.replace`, and the directory is fsynced afterwards, so a completed
    call survives a crash. Files are private (0600) unless `mode` says otherwise.
    """
    raw = data.encode("utf-8") if isinstance(data, str) else data
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = tmp_dir or path.parent
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=tmp_dir, prefix=f".{path.name}.", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            if mode is not None:
                os.fchmod(f.fileno(), mode)
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def utc_iso(moment: datetime) -> str:
    """`2026-01-31T12:00:00Z`: the one timestamp format of logs, metadata and frontmatter."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now_iso() -> str:
    return utc_iso(datetime.now(UTC))
