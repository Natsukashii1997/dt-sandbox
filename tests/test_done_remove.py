import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from todo_lite.cli import main

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "todo.json")


def _seed(db, *texts):
    for t in texts:
        assert main(["--db", db, "add", t]) == 0


def _list(db, capsys):
    capsys.readouterr()
    assert main(["--db", db, "list"]) == 0
    return capsys.readouterr().out


# ---- done ----

def test_done_marks_item_completed_in_list(db, capsys):
    _seed(db, "买牛奶", "写周报")
    capsys.readouterr()
    assert main(["--db", db, "done", "2"]) == 0
    assert capsys.readouterr().out == "已完成 #2：写周报\n"
    assert _list(db, capsys) == "1. [ ] 买牛奶\n2. [x] 写周报\n"


def test_done_persists_json(db):
    _seed(db, "买牛奶")
    main(["--db", db, "done", "1"])
    data = json.loads(Path(db).read_text(encoding="utf-8"))
    assert data == {"todos": [{"text": "买牛奶", "done": True}]}


def test_done_twice_is_idempotent(db, capsys):
    _seed(db, "买牛奶")
    assert main(["--db", db, "done", "1"]) == 0
    assert main(["--db", db, "done", "1"]) == 0
    assert _list(db, capsys) == "1. [x] 买牛奶\n"


@pytest.mark.parametrize("index", ["0", "3", "-1", "abc", "1.5", ""])
def test_done_missing_index_exits_2_and_keeps_file(db, capsys, index):
    _seed(db, "买牛奶", "写周报")
    before = Path(db).read_bytes()
    capsys.readouterr()
    assert main(["--db", db, "done", index]) == 2
    assert "错误" in capsys.readouterr().err
    assert Path(db).read_bytes() == before


def test_done_on_empty_list_exits_2(db, capsys):
    assert main(["--db", db, "done", "1"]) == 2
    assert "不存在" in capsys.readouterr().err
    assert not Path(db).exists()


# ---- remove ----

def test_remove_renumbers_remaining_items(db, capsys):
    _seed(db, "买牛奶", "写周报", "交房租")
    assert main(["--db", db, "done", "3"]) == 0
    capsys.readouterr()
    assert main(["--db", db, "remove", "1"]) == 0
    assert capsys.readouterr().out == "已删除 #1：买牛奶\n"
    assert _list(db, capsys) == "1. [ ] 写周报\n2. [x] 交房租\n"


def test_remove_last_item_leaves_empty_list(db, capsys):
    _seed(db, "买牛奶")
    assert main(["--db", db, "remove", "1"]) == 0
    assert _list(db, capsys) == "暂无待办\n"


@pytest.mark.parametrize("index", ["0", "3", "-1", "abc", ""])
def test_remove_missing_index_exits_2_and_keeps_file(db, capsys, index):
    _seed(db, "买牛奶", "写周报")
    before = Path(db).read_bytes()
    capsys.readouterr()
    assert main(["--db", db, "remove", index]) == 2
    assert "错误" in capsys.readouterr().err
    assert Path(db).read_bytes() == before


def test_remove_on_empty_list_exits_2(db, capsys):
    assert main(["--db", db, "remove", "1"]) == 2
    assert "不存在" in capsys.readouterr().err
    assert not Path(db).exists()


@pytest.mark.parametrize("cmd", ["done", "remove"])
def test_missing_index_argument_exits_2(db, cmd):
    with pytest.raises(SystemExit) as exc:
        main(["--db", db, cmd])
    assert exc.value.code == 2


@pytest.mark.parametrize("cmd", ["done", "remove"])
def test_db_option_after_subcommand(db, capsys, cmd):
    _seed(db, "买牛奶")
    assert main([cmd, "--db", db, "1"]) == 0


# ---- end to end via python -m ----

def _run(*args, cwd):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(REPO_ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "todo_lite", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_python_m_done_remove_end_to_end(tmp_path):
    assert _run("add", "买牛奶", cwd=tmp_path).returncode == 0
    assert _run("add", "写周报", cwd=tmp_path).returncode == 0

    r = _run("done", "1", cwd=tmp_path)
    assert r.returncode == 0
    assert _run("list", cwd=tmp_path).stdout == "1. [x] 买牛奶\n2. [ ] 写周报\n"

    r = _run("remove", "1", cwd=tmp_path)
    assert r.returncode == 0
    assert _run("list", cwd=tmp_path).stdout == "1. [ ] 写周报\n"

    assert _run("done", "5", cwd=tmp_path).returncode == 2
    assert _run("remove", "5", cwd=tmp_path).returncode == 2
