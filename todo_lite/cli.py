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

    return parser


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "add":
        return _cmd_add(args)
    if args.command == "list":
        return _cmd_list(args)
    parser.print_help()
    return EXIT_OK
