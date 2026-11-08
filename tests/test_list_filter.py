"""list --search / --status 筛选（SBX-23）。"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from todo_lite.cli import main

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def db(tmp_path):
    """种子清单：1 买牛奶(未完成) 2 写周报(已完成) 3 回 Email(未完成) 4 周报复盘(未完成)。"""
    path = str(tmp_path / "todo.json")
    for text in ["买牛奶", "写周报", "回 Email", "周报复盘"]:
        assert main(["--db", path, "add", text]) == 0
    assert main(["--db", path, "done", "2"]) == 0
    return path


def _list(db, capsys, *extra):
    capsys.readouterr()
    code = main(["--db", db, "list", *extra])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_list_without_filters_unchanged(db, capsys):
    code, out, _ = _list(db, capsys)
    assert code == 0
    assert out == "1. [ ] 买牛奶\n2. [x] 写周报\n3. [ ] 回 Email\n4. [ ] 周报复盘\n"


def test_status_all_is_default(db, capsys):
    _, default_out, _ = _list(db, capsys)
    code, out, _ = _list(db, capsys, "--status", "all")
    assert code == 0
    assert out == default_out


def test_status_open_keeps_original_index(db, capsys):
    code, out, _ = _list(db, capsys, "--status", "open")
    assert code == 0
    assert out == "1. [ ] 买牛奶\n3. [ ] 回 Email\n4. [ ] 周报复盘\n"


def test_status_done_keeps_original_index(db, capsys):
    code, out, _ = _list(db, capsys, "--status", "done")
    assert code == 0
    assert out == "2. [x] 写周报\n"


def test_search_substring_keeps_original_index(db, capsys):
    code, out, _ = _list(db, capsys, "--search", "周报")
    assert code == 0
    assert out == "2. [x] 写周报\n4. [ ] 周报复盘\n"


@pytest.mark.parametrize("needle", ["email", "EMAIL", "eMaIl", "mai"])
def test_search_is_case_insensitive(db, capsys, needle):
    code, out, _ = _list(db, capsys, "--search", needle)
    assert code == 0
    assert out == "3. [ ] 回 Email\n"


def test_search_and_status_combined(db, capsys):
    code, out, _ = _list(db, capsys, "--search", "周报", "--status", "open")
    assert code == 0
    assert out == "4. [ ] 周报复盘\n"
    code, out, _ = _list(db, capsys, "--status", "done", "--search", "周报")
    assert code == 0
    assert out == "2. [x] 写周报\n"


@pytest.mark.parametrize(
    "extra",
    [
        ["--search", "不存在"],
        ["--search", "买牛奶", "--status", "done"],
        ["--search", "写周报", "--status", "open"],
    ],
)
def test_no_match_message_exit_0(db, capsys, extra):
    code, out, err = _list(db, capsys, *extra)
    assert code == 0
    assert out == "没有符合条件的待办\n"
    assert err == ""


def test_status_done_with_nothing_done(tmp_path, capsys):
    path = str(tmp_path / "todo.json")
    assert main(["--db", path, "add", "买牛奶"]) == 0
    code, out, _ = _list(path, capsys, "--status", "done")
    assert code == 0
    assert out == "没有符合条件的待办\n"


def test_empty_db_without_filter_still_placeholder(tmp_path, capsys):
    path = str(tmp_path / "todo.json")
    code, out, _ = _list(path, capsys)
    assert code == 0
    assert out == "暂无待办\n"


def test_empty_db_with_filter_reports_no_match(tmp_path, capsys):
    path = str(tmp_path / "todo.json")
    code, out, _ = _list(path, capsys, "--search", "x")
    assert code == 0
    assert out == "没有符合条件的待办\n"


def test_search_special_characters_are_literal(tmp_path, capsys):
    path = str(tmp_path / "todo.json")
    for text in ["a.b", "axb", "100%", "[x] 方括号"]:
        assert main(["--db", path, "add", text]) == 0
    _, out, _ = _list(path, capsys, "--search", ".")
    assert out == "1. [ ] a.b\n"
    _, out, _ = _list(path, capsys, "--search", "%")
    assert out == "3. [ ] 100%\n"
    _, out, _ = _list(path, capsys, "--search", "[x]")
    assert out == "4. [ ] [x] 方括号\n"


def test_filtered_index_works_with_done_and_remove(db, capsys):
    code, out, _ = _list(db, capsys, "--search", "复盘")
    assert out == "4. [ ] 周报复盘\n"
    index = out.split(".", 1)[0]
    assert main(["--db", db, "done", index]) == 0
    _, out, _ = _list(db, capsys, "--status", "done")
    assert out == "2. [x] 写周报\n4. [x] 周报复盘\n"

    _, out, _ = _list(db, capsys, "--search", "email")
    index = out.split(".", 1)[0]
    assert main(["--db", db, "remove", index]) == 0
    _, out, _ = _list(db, capsys)
    assert out == "1. [ ] 买牛奶\n2. [x] 写周报\n3. [x] 周报复盘\n"


@pytest.mark.parametrize("bad", ["closed", "OPEN", "", "todo"])
def test_invalid_status_exits_2(db, capsys, bad):
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(["--db", db, "list", "--status", bad])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--status" in captured.err


def test_filter_options_with_db_after_subcommand(db, capsys):
    capsys.readouterr()
    assert main(["list", "--status", "done", "--db", db]) == 0
    assert capsys.readouterr().out == "2. [x] 写周报\n"


def test_filter_does_not_modify_db(db, capsys):
    before = Path(db).read_bytes()
    _list(db, capsys, "--search", "周报", "--status", "open")
    _list(db, capsys, "--search", "不存在")
    assert Path(db).read_bytes() == before


def test_corrupt_db_with_filter_exits_3(tmp_path, capsys):
    path = tmp_path / "todo.json"
    path.write_text('{"todos": [', encoding="utf-8")
    assert main(["--db", str(path), "list", "--search", "x"]) == 3
    assert path.read_text(encoding="utf-8") == '{"todos": ['


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


def test_python_m_list_filter_end_to_end(tmp_path):
    for text in ["买牛奶", "写周报", "回邮件"]:
        assert _run("add", text, cwd=tmp_path).returncode == 0
    assert _run("done", "2", cwd=tmp_path).returncode == 0

    r = _run("list", "--status", "open", cwd=tmp_path)
    assert (r.returncode, r.stdout) == (0, "1. [ ] 买牛奶\n3. [ ] 回邮件\n")

    r = _run("list", "--search", "周报", "--status", "done", cwd=tmp_path)
    assert (r.returncode, r.stdout) == (0, "2. [x] 写周报\n")

    r = _run("list", "--search", "周报", "--status", "open", cwd=tmp_path)
    assert (r.returncode, r.stdout) == (0, "没有符合条件的待办\n")

    r = _run("list", "--status", "closed", cwd=tmp_path)
    assert r.returncode == 2
    assert r.stdout == ""
    assert "invalid choice" in r.stderr
