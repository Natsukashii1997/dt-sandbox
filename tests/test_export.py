"""export 命令：JSON / CSV 导出（SBX-22）。"""

import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from todo_lite import storage
from todo_lite.cli import main

REPO_ROOT = Path(__file__).resolve().parent.parent

TRICKY = [
    {"text": "买牛奶", "done": False},
    {"text": "写周报, 第 3 版", "done": True},
    {"text": 'say "hi"', "done": False},
    {"text": "第一行\n第二行", "done": True},
    {"text": "回车\r\n换行, 还有\"引号\"", "done": False},
    {"text": "Ünïcödé — emoji 🎉", "done": True},
]


@pytest.fixture
def db(tmp_path):
    return tmp_path / "todo.json"


def _seed(db, todos):
    storage.save(db, todos)


def _run(db, *argv):
    return main(["--db", str(db), "export", *argv])


def _expected_rows(todos):
    return [{"id": i, "text": t["text"], "done": t["done"]} for i, t in enumerate(todos, start=1)]


# ---- 1) JSON ----


def test_json_stdout_shape_and_order(db, capsys):
    _seed(db, TRICKY)
    assert _run(db, "--format", "json") == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, list)
    assert data == _expected_rows(TRICKY)
    for item in data:
        assert list(item) == ["id", "text", "done"]
        assert isinstance(item["id"], int) and isinstance(item["done"], bool)


def test_json_keeps_chinese_unescaped(db, capsys):
    _seed(db, [{"text": "买牛奶", "done": False}])
    assert _run(db, "--format", "json") == 0
    out = capsys.readouterr().out
    assert "买牛奶" in out
    assert "\\u" not in out


def test_json_missing_done_field_exports_false(db, capsys):
    db.write_text('{"todos": [{"text": "旧数据"}]}', encoding="utf-8")
    assert _run(db, "--format", "json") == 0
    assert json.loads(capsys.readouterr().out) == [{"id": 1, "text": "旧数据", "done": False}]


def test_export_follows_list_numbering_after_remove(db, capsys):
    _seed(db, [{"text": "a", "done": False}, {"text": "b", "done": False}, {"text": "c", "done": True}])
    assert main(["--db", str(db), "remove", "1"]) == 0
    capsys.readouterr()
    assert _run(db, "--format", "json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data == [{"id": 1, "text": "b", "done": False}, {"id": 2, "text": "c", "done": True}]
    assert main(["--db", str(db), "list"]) == 0
    assert capsys.readouterr().out == "1. [ ] b\n2. [x] c\n"


# ---- 2) CSV ----


def test_csv_header_and_true_false(db, capsys):
    _seed(db, [{"text": "a", "done": False}, {"text": "b", "done": True}])
    assert _run(db, "--format", "csv") == 0
    assert capsys.readouterr().out == "id,text,done\n1,a,false\n2,b,true\n"


def test_csv_round_trips_commas_quotes_newlines(db, capsys):
    _seed(db, TRICKY)
    assert _run(db, "--format", "csv") == 0
    out = capsys.readouterr().out
    rows = list(csv.reader(io.StringIO(out, newline="")))
    assert rows[0] == ["id", "text", "done"]
    assert rows[1:] == [
        [str(i), t["text"], "true" if t["done"] else "false"] for i, t in enumerate(TRICKY, start=1)
    ]
    assert '"say ""hi"""' in out  # 引号按 CSV 规则加倍


def test_csv_file_round_trips_via_dictreader(db, tmp_path, capsys):
    _seed(db, TRICKY)
    out = tmp_path / "out.csv"
    assert _run(db, "--format", "csv", "--output", str(out)) == 0
    with out.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows == [
        {"id": str(i), "text": t["text"], "done": "true" if t["done"] else "false"}
        for i, t in enumerate(TRICKY, start=1)
    ]


# ---- 3) 空清单 ----


@pytest.mark.parametrize("create_file", [False, True])
def test_empty_json_is_empty_array(db, capsys, create_file):
    if create_file:
        _seed(db, [])
    assert _run(db, "--format", "json") == 0
    out = capsys.readouterr().out
    assert out.strip() == "[]"
    assert json.loads(out) == []


@pytest.mark.parametrize("create_file", [False, True])
def test_empty_csv_is_header_only(db, capsys, create_file):
    if create_file:
        _seed(db, [])
    assert _run(db, "--format", "csv") == 0
    assert capsys.readouterr().out == "id,text,done\n"


def test_export_missing_db_does_not_create_it(db, capsys):
    assert _run(db, "--format", "json") == 0
    assert not db.exists()


# ---- 4) 参数错误与原子写入 ----


@pytest.mark.parametrize("argv", [[], ["--format", "xml"], ["--format", ""], ["--format", "JSON"]])
def test_bad_or_missing_format_exits_2(db, capsys, argv):
    _seed(db, [{"text": "a", "done": False}])
    assert _run(db, *argv) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("错误：")
    assert "json、csv" in captured.err


def test_bad_format_does_not_create_output(db, tmp_path, capsys):
    out = tmp_path / "out.json"
    assert _run(db, "--format", "yaml", "--output", str(out)) == 2
    assert not out.exists()


@pytest.mark.parametrize("argv", [[], ["--format", "xml"]])
def test_bad_format_exit_2_via_python_m(tmp_path, argv):
    result = subprocess.run(
        [sys.executable, "-m", "todo_lite", "--db", str(tmp_path / "t.json"), "export", *argv],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "错误" in result.stderr


def test_python_m_json_stdout_utf8(tmp_path):
    db = tmp_path / "t.json"
    _seed(db, [{"text": "买牛奶", "done": True}])
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "todo_lite", "export", "--db", str(db), "--format", "json"],
        cwd=REPO_ROOT,
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    assert "买牛奶".encode("utf-8") in result.stdout
    assert json.loads(result.stdout.decode("utf-8")) == [{"id": 1, "text": "买牛奶", "done": True}]


@pytest.mark.parametrize("fmt", ["json", "csv"])
def test_output_writes_file_and_not_stdout_content(db, tmp_path, capsys, fmt):
    _seed(db, TRICKY)
    out = tmp_path / f"out.{fmt}"
    assert _run(db, "--format", fmt, "--output", str(out)) == 0
    stdout = capsys.readouterr().out
    assert "已导出 6 条" in stdout
    # 文件内容与打印到 stdout 的完全一致
    assert _run(db, "--format", fmt) == 0
    assert out.read_bytes().decode("utf-8") == capsys.readouterr().out


def test_output_uses_storage_write_atomic(db, tmp_path, monkeypatch):
    _seed(db, [{"text": "a", "done": False}])
    calls = []
    real = storage.write_atomic
    monkeypatch.setattr(storage, "write_atomic", lambda p, data: (calls.append((str(p), data)), real(p, data))[1])
    out = tmp_path / "out.json"
    assert _run(db, "--format", "json", "--output", str(out)) == 0
    assert calls == [(str(out), out.read_bytes())]


def test_output_failure_before_replace_keeps_old_file(db, tmp_path, monkeypatch, capsys):
    _seed(db, [{"text": "新内容", "done": False}])
    out = tmp_path / "out.json"
    out.write_text("旧导出\n", encoding="utf-8")

    def boom(*a, **k):
        raise OSError(5, "模拟 I/O 错误")

    monkeypatch.setattr(storage.os, "replace", boom)
    assert _run(db, "--format", "json", "--output", str(out)) == 1
    assert out.read_text(encoding="utf-8") == "旧导出\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.json", "todo.json"]
    assert "无法写入导出文件" in capsys.readouterr().err


def test_output_into_missing_directory_exits_1(db, tmp_path, capsys):
    _seed(db, [{"text": "a", "done": False}])
    assert _run(db, "--format", "csv", "--output", str(tmp_path / "nope" / "x.csv")) == 1
    assert "无法写入导出文件" in capsys.readouterr().err


def test_output_same_as_db_is_refused(db, capsys):
    _seed(db, [{"text": "a", "done": False}])
    before = db.read_bytes()
    assert _run(db, "--format", "json", "--output", str(db)) == 2
    assert db.read_bytes() == before
    assert "不能与数据文件相同" in capsys.readouterr().err


def test_corrupt_db_exits_3_and_writes_nothing(db, tmp_path, capsys):
    db.write_text('{"todos": [', encoding="utf-8")
    out = tmp_path / "out.json"
    assert _run(db, "--format", "json", "--output", str(out)) == 3
    assert not out.exists()
    assert "数据文件已损坏" in capsys.readouterr().err


def test_export_does_not_modify_db(db, tmp_path, capsys):
    _seed(db, TRICKY)
    before = db.read_bytes()
    assert _run(db, "--format", "csv", "--output", str(tmp_path / "o.csv")) == 0
    assert _run(db, "--format", "json") == 0
    assert db.read_bytes() == before


def test_db_option_after_subcommand(db, capsys):
    _seed(db, [{"text": "a", "done": True}])
    assert main(["export", "--format", "json", "--db", str(db)]) == 0
    assert json.loads(capsys.readouterr().out) == [{"id": 1, "text": "a", "done": True}]


# ---- SBX-29：独立回车 \r 也必须加引号（SBX-28 P1） ----

CR_TEXTS = ["\rb", "a\rb", "a\r", "a\r\rb", "x,\ry", '"\r"']


@pytest.mark.parametrize("text", CR_TEXTS)
def test_csv_bare_cr_round_trips_stdout(db, capsys, text):
    _seed(db, [{"text": text, "done": False}])
    assert _run(db, "--format", "csv") == 0
    out = capsys.readouterr().out
    assert list(csv.reader(io.StringIO(out, newline=""))) == [
        ["id", "text", "done"],
        ["1", text, "false"],
    ]


@pytest.mark.parametrize("text", CR_TEXTS)
def test_csv_bare_cr_round_trips_output_file(db, tmp_path, capsys, text):
    _seed(db, [{"text": text, "done": True}, {"text": "next", "done": False}])
    out = tmp_path / "out.csv"
    assert _run(db, "--format", "csv", "--output", str(out)) == 0
    with out.open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    assert rows == [["id", "text", "done"], ["1", text, "true"], ["2", "next", "false"]]


def test_csv_bare_cr_field_is_quoted_and_line_endings_stay_lf(db, capsys):
    _seed(db, [{"text": "a\rb", "done": False}])
    assert _run(db, "--format", "csv") == 0
    assert capsys.readouterr().out == 'id,text,done\n1,"a\rb",false\n'
