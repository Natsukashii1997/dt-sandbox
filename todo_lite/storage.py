"""todo-lite 的 JSON 文件存储。

文件格式：{"todos": [{"text": "...", "done": false}, ...]}，列表顺序即新增顺序。

写入保证（save）：
- 原子替换：先写同目录的临时文件并 fsync，再用 os.replace 替换目标文件。
  在 os.replace 提交之前发生的任何失败（含 KeyboardInterrupt）都不会改变目标文件，
  临时文件会被清理；os.replace 成功之后目标文件即为新内容。
- 掉电持久性是尽力保证：文件内容与权限在 replace 前 fsync；replace 之后再 fsync 目录。
  平台不支持目录 fsync 时静默跳过；支持但实际失败时向 stderr 打印告警，不改变返回结果。
- 只保留普通的 rwx 权限位（0o777），不保留 setuid/setgid/sticky 等特殊位。
- 不提供多写者事务隔离：并发的 load→修改→save 仍可能丢失更新。

读取保证（load）：文件不存在视为空清单；文件存在但内容不是合法的待办 JSON
（含空文件、缺少 todos 字段、条目结构不对）时抛 CorruptDBError，调用方不得写回。
"""

from __future__ import annotations

import errno
import json
import os
import secrets
import sys
from pathlib import Path

DEFAULT_DB = "todo.json"

# 目录 fsync 时表示“该文件系统/平台不支持”的 errno；其余 errno 视为真实 I/O 失败。
_DIR_FSYNC_UNSUPPORTED = {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EBADF}


class CorruptDBError(Exception):
    """数据文件存在但内容不是合法的待办 JSON。"""

    def __init__(self, path: str | Path, reason: str) -> None:
        self.path = str(path)
        self.reason = reason
        super().__init__(f"数据文件已损坏：{self.path}（{reason}）")


def _validate(path: Path, data: object) -> list[dict]:
    if not isinstance(data, dict):
        raise CorruptDBError(path, "顶层不是 JSON 对象")
    if "todos" not in data:
        raise CorruptDBError(path, "缺少 todos 字段")
    todos = data["todos"]
    if not isinstance(todos, list):
        raise CorruptDBError(path, "todos 不是列表")
    for i, item in enumerate(todos, start=1):
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise CorruptDBError(path, f"第 {i} 条待办缺少字符串 text")
        if "done" in item and not isinstance(item["done"], bool):
            raise CorruptDBError(path, f"第 {i} 条待办的 done 不是布尔值")
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


def _fsync_dir(directory: Path) -> None:
    """replace 之后 fsync 目录，让改名本身落盘（尽力保证）。

    非 POSIX 平台（如 Windows）不支持，直接跳过；POSIX 上不支持的 errno 静默跳过，
    其他 OSError 视为真实 I/O 失败，向 stderr 告警（数据已替换，不回滚也不抛出）。
    """
    if os.name != "posix":
        return
    try:
        fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError as e:
        print(f"警告：无法打开目录 {directory} 以执行 fsync：{e}", file=sys.stderr)
        return
    try:
        os.fsync(fd)
    except OSError as e:
        if e.errno not in _DIR_FSYNC_UNSUPPORTED:
            print(f"警告：目录 {directory} fsync 失败，掉电后改动可能丢失：{e}", file=sys.stderr)
    finally:
        os.close(fd)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        view = view[n:]


def save(path: str | Path, todos: list[dict]) -> None:
    """原子写入待办列表：同目录临时文件 → 写入 → 设权限 → fsync → 关闭 → os.replace。

    os.replace 之前的任何失败都会关闭 fd、删除临时文件并原样抛出，目标文件保持原内容。

    权限：临时文件以 0o666 创建，由内核按当前 umask 收紧（与普通 open() 新建文件一致），
    不读取也不修改进程全局 umask；目标文件已存在时在 fd 上 fchmod 成其原有 rwx 位。
    """
    p = Path(path)
    directory = p.parent if str(p.parent) else Path(".")
    payload = (json.dumps({"todos": todos}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    try:
        keep_mode: int | None = p.stat().st_mode & 0o777
    except FileNotFoundError:
        keep_mode = None

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd: int | None = None
    tmp: Path | None = None
    try:
        # 与 mkstemp 同样的 O_EXCL 随机名重试，但用 0o666 让 umask 自然生效。
        for _ in range(100):
            candidate = directory / f".{p.name}.{secrets.token_hex(6)}.tmp"
            try:
                fd = os.open(candidate, flags, 0o666)
            except FileExistsError:
                continue
            tmp = candidate
            break
        else:
            raise FileExistsError(errno.EEXIST, "无法创建唯一的临时文件", str(directory))

        _write_all(fd, payload)
        if keep_mode is not None:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, keep_mode)
            else:  # Windows：没有 fchmod，退回按路径 chmod（仍在 replace 之前）
                os.chmod(tmp, keep_mode)
        os.fsync(fd)
        os.close(fd)
        fd = None
        os.replace(tmp, p)
        tmp = None
    except BaseException:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp is not None:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
        raise
    _fsync_dir(directory)
