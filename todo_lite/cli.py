"""todo-lite 命令行入口。"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from todo_lite import __version__, storage

EXIT_OK = 0
EXIT_USAGE = 2


def _add_db_option(parser: argparse.ArgumentParser, default: object) -> None:
    parser.add_argument(
        "--db",
        default=default,
        help=f"待办数据 JSON 文件路径（默认 ./{storage.DEFAULT_DB}）",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="todo_lite", description="极简命令行待办清单")
    parser.add_argument("--version", action="version", version=__version__)
    _add_db_option(parser, storage.DEFAULT_DB)

    sub = parser.add_subparsers(dest="command")

    p_add = sub.add_parser("add", help="新增一条待办")
    p_add.add_argument("text", help="待办文字")
    # 子命令里也接受 --db；用 SUPPRESS 避免覆盖写在子命令前面的 --db。
    _add_db_option(p_add, argparse.SUPPRESS)

    p_list = sub.add_parser("list", help="按新增顺序列出待办")
    _add_db_option(p_list, argparse.SUPPRESS)

    p_done = sub.add_parser("done", help="把指定序号的待办标记为完成")
    p_done.add_argument("index", help="待办序号（list 中显示的数字，从 1 开始）")
    _add_db_option(p_done, argparse.SUPPRESS)

    p_remove = sub.add_parser("remove", help="删除指定序号的待办，其后序号依次前移")
    p_remove.add_argument("index", help="待办序号（list 中显示的数字，从 1 开始）")
    _add_db_option(p_remove, argparse.SUPPRESS)

    return parser


def _resolve_index(raw: str, todos: list[dict]) -> int | None:
    """把用户输入的 1 起序号转换成列表下标；序号无效或不存在时打印错误并返回 None。"""
    try:
        n = int(raw.strip())
    except ValueError:
        print(f"错误：序号必须是正整数：{raw}", file=sys.stderr)
        return None
    if not 1 <= n <= len(todos):
        print(f"错误：序号 {n} 不存在（当前共 {len(todos)} 条）", file=sys.stderr)
        return None
    return n - 1


def _cmd_add(args: argparse.Namespace) -> int:
    text = args.text.strip()
    if not text:
        print("错误：待办文字不能为空", file=sys.stderr)
        return EXIT_USAGE
    todos = storage.load(args.db)
    todos.append({"text": text, "done": False})
    storage.save(args.db, todos)
    print(f"已新增 #{len(todos)}：{text}")
    return EXIT_OK


def _cmd_list(args: argparse.Namespace) -> int:
    todos = storage.load(args.db)
    if not todos:
        print("暂无待办")
        return EXIT_OK
    for i, item in enumerate(todos, start=1):
        mark = "[x]" if item.get("done") else "[ ]"
        print(f"{i}. {mark} {item['text']}")
    return EXIT_OK


def _cmd_done(args: argparse.Namespace) -> int:
    todos = storage.load(args.db)
    idx = _resolve_index(args.index, todos)
    if idx is None:
        return EXIT_USAGE
    item = todos[idx]
    if not item.get("done"):
        item["done"] = True
        storage.save(args.db, todos)
    print(f"已完成 #{idx + 1}：{item['text']}")
    return EXIT_OK


def _cmd_remove(args: argparse.Namespace) -> int:
    todos = storage.load(args.db)
    idx = _resolve_index(args.index, todos)
    if idx is None:
        return EXIT_USAGE
    item = todos.pop(idx)
    storage.save(args.db, todos)
    print(f"已删除 #{idx + 1}：{item['text']}")
    return EXIT_OK


_COMMANDS = {
    "add": _cmd_add,
    "list": _cmd_list,
    "done": _cmd_done,
    "remove": _cmd_remove,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _COMMANDS.get(args.command)
    if handler is not None:
        return handler(args)
    parser.print_help()
    return EXIT_OK
