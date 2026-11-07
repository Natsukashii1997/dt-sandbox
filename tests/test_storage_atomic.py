import errno
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from todo_lite import storage
from todo_lite.cli import main

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def db(tmp_path):
    return tmp_path / "todo.json"


def _leftovers(directory: Path, db: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p != db)


# ---- 原子写入 ----

def test_save_writes_expected_json_and_no_temp_files(db):
    storage.save(db, [{"text": "买牛奶", "done": False}])
    assert json.loads(db.read_text(encoding="utf-8")) == {
        "todos": [{"text": "买牛奶", "done": False}]
    }
    assert _leftovers(db.parent, db) == []


def test_save_uses_tempfile_in_same_dir_fsync_and_replace(db, monkeypatch):
    calls = []
    real_fsync, real_replace = os.fsync, os.replace

    def spy_fsync(fd):
        calls.append(("fsync", fd))
        return real_fsync(fd)

    def spy_replace(src, dst):
        calls.append(("replace", Path(src), Path(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(storage.os, "fsync", spy_fsync)
    monkeypatch.setattr(storage.os, "replace", spy_replace)

    storage.save(db, [{"text": "a", "done": False}])

    names = [c[0] for c in calls]
    assert "replace" in names
    # 数据文件的 fsync 必须发生在 replace 之前
    assert names.index("fsync") < names.index("replace")
    _, src, dst = calls[names.index("replace")]
    assert src.parent == db.parent  # 同目录临时文件
    assert src != db
    assert dst == db


@pytest.mark.parametrize("fail_at", ["write", "fchmod", "fsync", "replace"])
def test_exception_mid_write_keeps_old_file_and_no_partial(db, monkeypatch, fail_at):
    storage.save(db, [{"text": "旧内容", "done": False}])
    before = db.read_bytes()
    opened, closed = [], []
    real_open, real_close = os.open, os.close

    def spy_open(*a, **k):
        fd = real_open(*a, **k)
        opened.append(fd)
        return fd

    def spy_close(fd):
        closed.append(fd)
        return real_close(fd)

    monkeypatch.setattr(storage.os, "open", spy_open)
    monkeypatch.setattr(storage.os, "close", spy_close)

    def boom(*a, **k):
        raise OSError(f"模拟 {fail_at} 失败")

    if fail_at == "write":
        real_write = os.write

        # 模拟磁盘写到一半：真实写入一半字节后抛异常
        def half_write(fd, data):
            real_write(fd, bytes(data[: len(data) // 2]))
            raise OSError("模拟磁盘写到一半失败")

        monkeypatch.setattr(storage.os, "write", half_write)
    else:
        monkeypatch.setattr(storage.os, fail_at, boom)

    with pytest.raises(OSError):
        storage.save(db, [{"text": "新内容" * 1000, "done": False}])

    assert db.read_bytes() == before
    assert _leftovers(db.parent, db) == []
    assert opened and set(opened) <= set(closed)  # 临时文件 fd 已关闭


@pytest.mark.parametrize("stage", ["write", "fchmod", "fsync", "replace"])
def test_keyboard_interrupt_at_each_stage_cleans_temp(db, monkeypatch, stage):
    storage.save(db, [{"text": "旧内容", "done": False}])
    before = db.read_bytes()

    def interrupt(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(storage.os, stage, interrupt)
    with pytest.raises(KeyboardInterrupt):
        storage.save(db, [{"text": "新内容", "done": False}])
    assert db.read_bytes() == before
    assert _leftovers(db.parent, db) == []


def test_temp_open_failure_leaves_nothing(db, monkeypatch):
    storage.save(db, [{"text": "旧内容", "done": False}])
    before = db.read_bytes()

    def deny(*a, **k):
        raise PermissionError("模拟无法创建临时文件")

    monkeypatch.setattr(storage.os, "open", deny)
    with pytest.raises(PermissionError):
        storage.save(db, [{"text": "新内容", "done": False}])
    assert db.read_bytes() == before
    assert _leftovers(db.parent, db) == []


def test_temp_name_collision_retries(db, monkeypatch):
    (db.parent / ".todo.json.aaaaaaaaaaaa.tmp").write_text("别人的文件")
    tokens = iter(["aaaaaaaaaaaa", "bbbbbbbbbbbb"])
    monkeypatch.setattr(storage.secrets, "token_hex", lambda n: next(tokens))
    storage.save(db, [{"text": "a", "done": False}])
    assert storage.load(db) == [{"text": "a", "done": False}]
    assert (db.parent / ".todo.json.aaaaaaaaaaaa.tmp").read_text() == "别人的文件"
    assert _leftovers(db.parent, db) == [".todo.json.aaaaaaaaaaaa.tmp"]


def test_exception_mid_first_write_leaves_no_file(db, monkeypatch):
    def boom(*a, **k):
        raise OSError("模拟 replace 失败")

    monkeypatch.setattr(storage.os, "replace", boom)
    with pytest.raises(OSError):
        storage.save(db, [{"text": "a", "done": False}])
    assert not db.exists()
    assert list(db.parent.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="权限位只在 POSIX 上有意义")
def test_save_preserves_existing_file_mode(db):
    storage.save(db, [])
    os.chmod(db, 0o640)
    storage.save(db, [{"text": "a", "done": False}])
    assert stat.S_IMODE(db.stat().st_mode) == 0o640


@pytest.mark.skipif(os.name != "posix", reason="权限位只在 POSIX 上有意义")
def test_new_file_mode_follows_umask_not_mkstemp_0600(db):
    old = os.umask(0o022)
    try:
        storage.save(db, [])
    finally:
        os.umask(old)
    assert stat.S_IMODE(db.stat().st_mode) == 0o644


@pytest.mark.skipif(os.name != "posix", reason="权限位只在 POSIX 上有意义")
def test_save_never_touches_process_umask(db, monkeypatch):
    """P1-02：save 不得读取或修改进程全局 umask；新文件权限仍由 umask 决定。"""

    def forbidden(*a, **k):
        raise AssertionError("save 不应调用 os.umask")

    old = os.umask(0o027)
    try:
        monkeypatch.setattr(storage.os, "umask", forbidden)
        storage.save(db, [])
        monkeypatch.undo()
        assert os.umask(0o027) == 0o027  # umask 未被改动
    finally:
        os.umask(old)
    assert stat.S_IMODE(db.stat().st_mode) == 0o640


@pytest.mark.skipif(os.name != "posix", reason="fchmod 只在 POSIX 上有")
def test_existing_mode_set_via_fchmod_before_fsync(db, monkeypatch):
    storage.save(db, [])
    os.chmod(db, 0o600)
    calls = []
    real_fchmod, real_fsync, real_chmod = os.fchmod, os.fsync, os.chmod
    monkeypatch.setattr(storage.os, "fchmod", lambda fd, m: (calls.append(("fchmod", m)), real_fchmod(fd, m))[1])
    monkeypatch.setattr(storage.os, "fsync", lambda fd: (calls.append(("fsync",)), real_fsync(fd))[1])
    monkeypatch.setattr(storage.os, "chmod", lambda *a, **k: calls.append(("chmod",)) or real_chmod(*a, **k))
    storage.save(db, [{"text": "a", "done": False}])
    names = [c[0] for c in calls]
    assert ("fchmod", 0o600) in calls
    assert "chmod" not in names  # 不按路径 chmod
    assert names.index("fchmod") < names.index("fsync")
    assert stat.S_IMODE(db.stat().st_mode) == 0o600


# ---- 目录 fsync ----

@pytest.mark.skipif(os.name != "posix", reason="目录 fsync 只在 POSIX 上执行")
def test_dir_fsync_happens_after_replace(db, monkeypatch):
    events = []
    real_fsync, real_replace = os.fsync, os.replace

    def spy_fsync(fd):
        events.append(("fsync", stat.S_ISDIR(os.fstat(fd).st_mode)))
        return real_fsync(fd)

    monkeypatch.setattr(storage.os, "fsync", spy_fsync)
    monkeypatch.setattr(storage.os, "replace", lambda a, b: events.append(("replace",)) or real_replace(a, b))
    storage.save(db, [])
    assert events == [("fsync", False), ("replace",), ("fsync", True)]


@pytest.mark.skipif(os.name != "posix", reason="目录 fsync 只在 POSIX 上执行")
@pytest.mark.parametrize("err", [errno.EINVAL, errno.ENOTSUP])
def test_dir_fsync_unsupported_is_silent(db, monkeypatch, capsys, err):
    real_fsync = os.fsync

    def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(err, os.strerror(err))
        return real_fsync(fd)

    monkeypatch.setattr(storage.os, "fsync", fsync)
    storage.save(db, [{"text": "a", "done": False}])
    assert capsys.readouterr().err == ""
    assert storage.load(db) == [{"text": "a", "done": False}]


@pytest.mark.skipif(os.name != "posix", reason="目录 fsync 只在 POSIX 上执行")
def test_dir_fsync_io_error_warns_on_stderr(db, monkeypatch, capsys):
    real_fsync = os.fsync

    def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        return real_fsync(fd)

    monkeypatch.setattr(storage.os, "fsync", fsync)
    storage.save(db, [{"text": "a", "done": False}])
    err = capsys.readouterr().err
    assert "警告" in err and "fsync" in err
    assert storage.load(db) == [{"text": "a", "done": False}]
    assert _leftovers(db.parent, db) == []


def test_load_accepts_missing_done(db):
    db.write_text('{"todos": [{"text": "a"}]}', encoding="utf-8")
    assert storage.load(db) == [{"text": "a"}]


def test_save_relative_path_in_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    storage.save("todo.json", [{"text": "a", "done": False}])
    assert storage.load("todo.json") == [{"text": "a", "done": False}]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["todo.json"]


# ---- 损坏文件：退出码 3，且不改写 ----

CORRUPT_CONTENTS = [
    pytest.param(b"", id="empty"),
    pytest.param(b'{"todos": [{"text": "a", "do', id="truncated"),
    pytest.param(b"not json", id="garbage"),
    pytest.param(b"\xff\xfe\x00bad", id="not-utf8"),
    pytest.param(b"[1, 2, 3]", id="top-level-list"),
    pytest.param(b'{"todos": "oops"}', id="todos-not-list"),
    pytest.param(b'{"todos": [42]}', id="item-not-object"),
    pytest.param(b'{"todos": [{"done": false}]}', id="item-missing-text"),
    pytest.param(b"{}", id="todos-missing"),
    pytest.param('{"tasks": [{"text": "原有待办", "done": false}]}'.encode(), id="todos-renamed"),
    pytest.param(b'{"todo": [{"text": "a", "done": false}]}', id="todos-misspelled"),
    pytest.param(b'{"todos": [{"text": "a", "done": "false"}]}', id="done-is-string"),
    pytest.param(b'{"todos": [{"text": "a", "done": 1}]}', id="done-is-int"),
    pytest.param(b'{"todos": [{"text": "a", "done": null}]}', id="done-is-null"),
]


@pytest.mark.parametrize("content", CORRUPT_CONTENTS)
def test_load_corrupt_raises(db, content):
    db.write_bytes(content)
    with pytest.raises(storage.CorruptDBError):
        storage.load(db)


@pytest.mark.parametrize("content", CORRUPT_CONTENTS)
@pytest.mark.parametrize(
    "argv",
    [["add", "新待办"], ["list"], ["done", "1"], ["remove", "1"]],
    ids=["add", "list", "done", "remove"],
)
def test_cli_corrupt_db_exits_3_and_does_not_rewrite(db, capsys, content, argv):
    db.write_bytes(content)
    mtime = db.stat().st_mtime_ns

    assert main(["--db", str(db), *argv]) == 3

    err = capsys.readouterr().err
    assert "损坏" in err and str(db) in err
    assert db.read_bytes() == content
    assert db.stat().st_mtime_ns == mtime
    assert _leftovers(db.parent, db) == []


def test_python_m_corrupt_db_exits_3(tmp_path):
    db = tmp_path / "todo.json"
    db.write_bytes(b"{broken")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(REPO_ROOT)}
    r = subprocess.run(
        [sys.executable, "-m", "todo_lite", "add", "x"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert r.returncode == 3
    assert "损坏" in r.stderr
    assert r.stdout == ""
    assert db.read_bytes() == b"{broken"


# ---- 返修 2：目录 fsync 各阶段出错不影响已提交的 save；os.write 无进展 ----

def _is_dir_fd(fd):
    try:
        return stat.S_ISDIR(os.fstat(fd).st_mode)
    except OSError:
        return False


@pytest.mark.skipif(os.name != "posix", reason="目录 fsync 只在 POSIX 上执行")
def test_dir_close_error_does_not_fail_committed_save(db, monkeypatch, capsys):
    storage.save(db, [{"text": "旧内容", "done": False}])
    real_close = os.close
    hit = []

    def close(fd):
        if _is_dir_fd(fd):
            real_close(fd)  # 真正关掉，避免泄漏，再模拟报错
            hit.append(fd)
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        return real_close(fd)

    monkeypatch.setattr(storage.os, "close", close)
    storage.save(db, [{"text": "新内容", "done": False}])  # 不得抛异常
    assert hit
    assert storage.load(db) == [{"text": "新内容", "done": False}]
    err = capsys.readouterr().err
    assert "警告" in err and "关闭" in err
    assert _leftovers(db.parent, db) == []


@pytest.mark.skipif(os.name != "posix", reason="目录 fsync 只在 POSIX 上执行")
def test_dir_open_eio_only_warns(db, monkeypatch, capsys):
    storage.save(db, [{"text": "旧内容", "done": False}])
    real_open = os.open

    def open_(path, flags, *a, **k):
        if Path(path) == db.parent:
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(storage.os, "open", open_)
    storage.save(db, [{"text": "新内容", "done": False}])
    assert storage.load(db) == [{"text": "新内容", "done": False}]
    err = capsys.readouterr().err
    assert "警告" in err and "打开" in err
    assert _leftovers(db.parent, db) == []


@pytest.mark.skipif(os.name != "posix", reason="目录 fsync 只在 POSIX 上执行")
def test_dir_open_unsupported_is_silent(db, monkeypatch, capsys):
    real_open = os.open

    def open_(path, flags, *a, **k):
        if Path(path) == db.parent:
            raise OSError(errno.EINVAL, os.strerror(errno.EINVAL))
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(storage.os, "open", open_)
    storage.save(db, [{"text": "a", "done": False}])
    assert capsys.readouterr().err == ""
    assert storage.load(db) == [{"text": "a", "done": False}]


def test_write_no_progress_raises_eio_and_cleans_up(db, monkeypatch):
    storage.save(db, [{"text": "旧内容", "done": False}])
    before = db.read_bytes()
    monkeypatch.setattr(storage.os, "write", lambda fd, data: 0)
    with pytest.raises(OSError) as exc:
        storage.save(db, [{"text": "新内容", "done": False}])
    assert exc.value.errno == errno.EIO
    assert "未取得进展" in str(exc.value)
    assert db.read_bytes() == before
    assert _leftovers(db.parent, db) == []


def test_short_writes_are_completed(db, monkeypatch):
    real_write = os.write
    sizes = []

    def short_write(fd, data):
        n = real_write(fd, bytes(data[:7]))  # 每次只写一小段
        sizes.append(n)
        return n

    monkeypatch.setattr(storage.os, "write", short_write)
    todos = [{"text": "买牛奶" * 20, "done": False}, {"text": "写周报", "done": True}]
    storage.save(db, todos)
    assert len(sizes) > 1 and all(0 < n <= 7 for n in sizes)
    assert storage.load(db) == todos
    assert json.loads(db.read_text(encoding="utf-8")) == {"todos": todos}
