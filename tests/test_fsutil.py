"""fsutil.atomic_write observed through the filesystem."""

import os
import stat

import pytest

from okf_notebooks import fsutil
from okf_notebooks.fsutil import atomic_write


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def test_default_mode_is_private(tmp_path):
    p = tmp_path / "a.txt"
    atomic_write(p, "hi")
    assert p.read_text() == "hi" and mode(p) == 0o600


@pytest.mark.parametrize("m", [0o644, 0o640, 0o600])
def test_mode_argument_is_applied(tmp_path, m):
    p = tmp_path / "a.txt"
    atomic_write(p, b"hi", mode=m)
    assert p.read_bytes() == b"hi" and mode(p) == m


def test_replaces_existing_content_and_creates_parents(tmp_path):
    p = tmp_path / "deep" / "er" / "a.txt"
    atomic_write(p, "one")
    atomic_write(p, "two")
    assert p.read_text() == "two"
    assert [x.name for x in p.parent.iterdir()] == ["a.txt"]


def test_str_is_written_as_utf8(tmp_path):
    p = tmp_path / "a.txt"
    atomic_write(p, "привет")
    assert p.read_bytes() == "привет".encode()


def test_failed_write_leaves_old_file_and_no_part_files(tmp_path, monkeypatch):
    p = tmp_path / "a.txt"
    atomic_write(p, "old")

    def boom(fd):
        raise OSError("disk full")

    monkeypatch.setattr(fsutil.os, "fsync", boom)
    with pytest.raises(OSError, match="disk full"):
        atomic_write(p, "new")
    assert p.read_text() == "old"
    assert [x.name for x in tmp_path.iterdir()] == ["a.txt"]


def test_failed_first_write_leaves_no_partial_file(tmp_path, monkeypatch):
    p = tmp_path / "a.txt"
    monkeypatch.setattr(fsutil.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(OSError):
        atomic_write(p, "new")
    assert list(tmp_path.iterdir()) == []


def test_separate_tmp_dir_is_used_and_cleaned_on_failure(tmp_path, monkeypatch):
    tmp = tmp_path / "tmp"
    p = tmp_path / "out" / "a.txt"
    atomic_write(p, "ok", tmp_dir=tmp)
    assert p.read_text() == "ok" and list(tmp.iterdir()) == []
    monkeypatch.setattr(fsutil.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(OSError):
        atomic_write(p, "again", tmp_dir=tmp)
    assert list(tmp.iterdir()) == [] and p.read_text() == "ok"


def test_symlink_target_is_replaced_not_followed(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    link = tmp_path / "link.txt"
    link.symlink_to(victim)
    atomic_write(link, "new")
    assert victim.read_text() == "precious"
    assert not link.is_symlink() and link.read_text() == "new"


def test_directory_is_fsynced_after_the_file(tmp_path, monkeypatch):
    p = tmp_path / "a.txt"
    synced = []
    real = os.fsync

    def spy(fd):
        synced.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        real(fd)

    monkeypatch.setattr(fsutil.os, "fsync", spy)
    atomic_write(p, "x")
    assert synced == [False, True]  # file first, then its directory
