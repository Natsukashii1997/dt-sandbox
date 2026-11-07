"""Independent failure injection against the stage4 storage contract."""

import errno
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from todo_lite import storage


@pytest.mark.parametrize("existing", [False, True], ids=["new-db", "existing-db"])
@pytest.mark.parametrize("failure", ["before-replace", "half-write"])
def test_failed_save_preserves_database(tmp_path, monkeypatch, existing, failure):
    db = tmp_path / "todo.json"
    original = b'{"todos": [{"text": "original", "done": false}]}\n'
    if existing:
        db.write_bytes(original)
    todos = [{"text": "新内容" * 100, "done": False}]
    payload = (json.dumps({"todos": todos}, ensure_ascii=False, indent=2) + "\n").encode()
    real_write = os.write
    hits = []

    def fail_replace(src, dst):
        staged = Path(src)
        assert staged.parent == db.parent
        assert staged != db and Path(dst) == db
        assert staged.read_bytes() == payload
        hits.append("before-replace")
        raise OSError(errno.EIO, "injected before replace")

    def half_write(fd, data):
        if not hits:
            count = real_write(fd, data[: len(data) // 2])
            assert 0 < count < len(data)
            hits.append(count)
            return count
        staged = [p for p in tmp_path.iterdir() if p != db]
        assert len(staged) == 1
        assert staged[0].read_bytes() == payload[: hits[0]]
        hits.append("disk-full")
        raise OSError(errno.ENOSPC, "injected disk full after partial write")

    monkeypatch.setattr(storage.os, "replace", fail_replace)
    if failure == "half-write":
        monkeypatch.setattr(storage.os, "write", half_write)
    with pytest.raises(OSError) as exc:
        storage.save(db, todos)
    assert exc.value.errno == (errno.EIO if failure == "before-replace" else errno.ENOSPC)
    assert hits == (["before-replace"] if failure == "before-replace" else [len(payload) // 2, "disk-full"])
    if existing:
        assert db.read_bytes() == original
        assert storage.load(db) == [{"text": "original", "done": False}]
    else:
        assert not db.exists()
    assert set(tmp_path.iterdir()) == ({db} if existing else set())


@pytest.mark.parametrize("damage", ["empty", "truncated-json", "truncated-utf8"])
@pytest.mark.parametrize("command", [["add", "new"], ["list"], ["done", "1"], ["remove", "1"]])
def test_damaged_database_rejected_without_rewrite(tmp_path, damage, command):
    db = tmp_path / "todo.json"
    valid = '{"todos": [{"text": "待办", "done": false}]}'.encode()
    db.write_bytes(valid)
    cut = {"empty": 0, "truncated-json": len(valid) - 2,
           "truncated-utf8": valid.index("待".encode()) + 1}[damage]
    with db.open("r+b") as stream:
        stream.truncate(cut)
    damaged = db.read_bytes()
    before = db.stat()
    with pytest.raises(storage.CorruptDBError):
        storage.load(db)
    result = subprocess.run(
        [sys.executable, "-m", "todo_lite", "--db", str(db), *command],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 3
    assert result.stdout == ""
    assert "损坏" in result.stderr and str(db) in result.stderr
    assert db.read_bytes() == damaged
    assert db.stat().st_mtime_ns == before.st_mtime_ns
    assert set(tmp_path.iterdir()) == {db}
