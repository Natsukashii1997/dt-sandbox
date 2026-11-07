"""todo-lite 的 JSON 文件存储。

文件格式：{"todos": [{"text": "...", "done": false}, ...]}，列表顺序即新增顺序。

写入是原子的：先写到同目录的临时文件并 fsync，再用 os.replace 替换目标文件，
所以任何时刻目标文件要么是旧的完整内容，要么是新的完整内容，不会出现半截文件。
读到损坏的文件时抛出 CorruptDBError，调用方不得再写回该文件。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

DEFAULT_DB = "todo.json"


class CorruptDBError(Exception):
    """数据文件存在但内容不是合法的待办 JSON。"""

    def __init__(self, path: str | Path, reason: str) -> None:
        self.path = str(path)
        self.reason = reason
        super().__init__(f"数据文件已损坏：{self.path}（{reason}）")


def _validate(path: Path, data: object) -> list[dict]:
    if not isinstance(data, dict):
        raise CorruptDBError(path, "顶层不是 JSON 对象")
    todos = data.get("todos", [])
    if not isinstance(todos, list):
        raise CorruptDBError(path, "todos 不是列表")
    for i, item in enumerate(todos, start=1):
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise CorruptDBError(path, f"第 {i} 条待办格式不对")
    return list(todos)


def load(path: str | Path) -> list[dict]:
    """读取待办列表；文件不存在时视为空清单，内容损坏时抛 CorruptDBError。

    空文件（0 字节）也按损坏处理：它不是合法 JSON，而且多半是被截断的结果，
    不应被当成空清单再覆盖掉。
    """
    p = Path(path)
    try:
        raw = p.read_bytes()
    except FileNotFoundError:
        return []
    try:
        data = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as e:
        raise CorruptDBError(p, f"不是 UTF-8 编码：{e.reason}") from e
    except json.JSONDecodeError as e:
        raise CorruptDBError(p, f"JSON 解析失败：{e.msg}，第 {e.lineno} 行第 {e.colno} 列") from e
    return _validate(p, data)


def _target_mode(p: Path) -> int:
    """新文件沿用旧文件的权限位；旧文件不存在时按普通 open() 的规则（0o666 & ~umask）。"""
    try:
        return p.stat().st_mode & 0o777
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        return 0o666 & ~umask


def _fsync_dir(directory: Path) -> None:
    """尽力 fsync 目录，让 rename 本身也落盘；不支持的平台（如 Windows）直接跳过。"""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def save(path: str | Path, todos: list[dict]) -> None:
    """原子写入待办列表：同目录临时文件 + fsync + os.replace。

    写入过程中任何异常都会删除临时文件并原样抛出，目标文件保持写入前的内容。
    """
    p = Path(path)
    directory = p.parent if str(p.parent) else Path(".")
    payload = json.dumps({"todos": todos}, ensure_ascii=False, indent=2) + "\n"
    mode = _target_mode(p)

    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, p)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    _fsync_dir(directory)
