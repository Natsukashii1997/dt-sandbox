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


def test_list_empty_shows_placeholder(db, capsys):
    assert main(["--db", db, "list"]) == 0
    assert capsys.readouterr().out == "暂无待办\n"


def test_add_then_list_shows_items_in_order(db, capsys):
    assert main(["--db", db, "add", "买牛奶"]) == 0
    assert main(["--db", db, "add", "写周报"]) == 0
    capsys.readouterr()

    assert main(["--db", db, "list"]) == 0
    assert capsys.readouterr().out == "1. [ ] 买牛奶\n2. [ ] 写周报\n"


def test_add_persists_json(db):
    main(["--db", db, "add", "买牛奶"])
    data = json.loads(Path(db).read_text(encoding="utf-8"))
    assert data == {"todos": [{"text": "买牛奶", "done": False}]}


def test_db_option_after_subcommand(db, capsys):
    assert main(["add", "--db", db, "买牛奶"]) == 0
    capsys.readouterr()
    assert main(["list", "--db", db]) == 0
    assert capsys.readouterr().out == "1. [ ] 买牛奶\n"


@pytest.mark.parametrize("text", ["", "   "])
def test_add_empty_text_exits_2(db, capsys, text):
    assert main(["--db", db, "add", text]) == 2
    assert "不能为空" in capsys.readouterr().err
    assert not Path(db).exists()


def test_add_missing_text_exits_2(db):
    with pytest.raises(SystemExit) as exc:
        main(["--db", db, "add"])
    assert exc.value.code == 2


def test_default_db_is_cwd_todo_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["add", "买牛奶"]) == 0
    assert (tmp_path / "todo.json").exists()


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


def test_python_m_add_list_end_to_end(tmp_path):
    r = _run("list", cwd=tmp_path)
    assert r.returncode == 0
    assert r.stdout == "暂无待办\n"

    r = _run("add", "买牛奶", cwd=tmp_path)
    assert r.returncode == 0

    r = _run("list", cwd=tmp_path)
    assert r.returncode == 0
    assert r.stdout == "1. [ ] 买牛奶\n"

    r = _run("add", "", cwd=tmp_path)
    assert r.returncode == 2
