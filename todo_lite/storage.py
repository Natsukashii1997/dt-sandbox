"""todo-lite 的 JSON 文件存储。

文件格式：{"todos": [{"text": "...", "done": false}, ...]}，列表顺序即新增顺序。
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_DB = "todo.json"


def load(path: str | Path) -> list[dict]:
    """读取待办列表；文件不存在时视为空清单。"""
    p = Path(path)
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get("todos", []))


def save(path: str | Path, todos: list[dict]) -> None:
    """写入待办列表（原子写入留给 stage4）。"""
    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        json.dump({"todos": todos}, f, ensure_ascii=False, indent=2)
        f.write("\n")
