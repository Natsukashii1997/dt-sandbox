"""todo-lite 命令行入口。"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Sequence

from todo_lite import __version__, storage

EXIT_OK = 0
EXIT_IO = 1
EXIT_USAGE = 2
EXIT_CORRUPT_DB = 3

LIST_STATUSES = ("open", "done", "all")


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
    p_list.add_argument("--search", default=None, help="只显示文字包含该关键词的待办（不区分大小写）")
    p_list.add_argument(
        "--status",
        choices=LIST_STATUSES,
        default="all",
        help="按状态筛选：open 未完成 / done 已完成 / all 全部（默认 all）",
    )
    _add_db_option(p_list, argparse.SUPPRESS)

    p_done = sub.add_parser("done", help="把指定序号的待办标记为完成")
    p_done.add_argument("index", help="待办序号（list 中显示的数字，从 1 开始）")
    _add_db_option(p_done, argparse.SUPPRESS)

    p_remove = sub.add_parser("remove", help="删除指定序号的待办，其后序号依次前移")
    p_remove.add_argument("index", help="待办序号（list 中显示的数字，从 1 开始）")
    _add_db_option(p_remove, argparse.SUPPRESS)

    p_export = sub.add_parser("export", help="按 list 的顺序导出全部待办（JSON 或 CSV）")
    # 不用 choices / required：缺省和不合法都由 _cmd_export 给出中文错误，退出码 2。
    p_export.add_argument("--format", dest="fmt", default=None, help="导出格式：json 或 csv（必填）")
    p_export.add_argument("--output", default=None, help="写入该文件（原子写入）；不给则打印到标准输出")
    _add_db_option(p_export, argparse.SUPPRESS)

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


def _list_match(item: dict, needle: str | None, status: str) -> bool:
    """判断一条待办是否满足 list 的筛选条件；needle 已 casefold，None 表示不按文字筛。"""
    done = bool(item.get("done"))
    if status == "open" and done:
        return False
    if status == "done" and not done:
        return False
    return needle is None or needle in item["text"].casefold()


def _cmd_list(args: argparse.Namespace) -> int:
    todos = storage.load(args.db)
    needle = args.search.casefold() if args.search is not None else None
    filtering = needle is not None or args.status != "all"
    if not todos and not filtering:
        print("暂无待办")
        return EXIT_OK
    # 序号始终是原清单中的位置，筛选后不重新编号，done / remove 可直接使用。
    shown = [
        (i, item)
        for i, item in enumerate(todos, start=1)
        if _list_match(item, needle, args.status)
    ]
    if not shown:
        print("没有符合条件的待办")
        return EXIT_OK
    for i, item in shown:
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


EXPORT_FORMATS = ("json", "csv")


def _export_rows(todos: list[dict]) -> list[dict]:
    return [
        {"id": i, "text": item["text"], "done": bool(item.get("done"))}
        for i, item in enumerate(todos, start=1)
    ]


def render_json(todos: list[dict]) -> str:
    """JSON 数组，每项 {"id", "text", "done"}；中文原样输出。空清单为 []。"""
    return json.dumps(_export_rows(todos), ensure_ascii=False, indent=2) + "\n"


def _csv_line(fields: list) -> str:
    # Python 3.11 的 csv.writer 只在字段含 lineterminator 里的字符时才加引号；
    # 用 "\r\n" 作行尾，才能让独立的 \r 和 \n 都触发加引号（SBX-28 P1）。
    # 写完再把行尾统一换回 "\n"，保持原有输出格式不变。
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerow(fields)
    return buf.getvalue().removesuffix("\r\n") + "\n"


def render_csv(todos: list[dict]) -> str:
    """表头 id,text,done；done 写 true/false；逗号、引号、回车（含独立 CR）、换行按 CSV 规则加引号转义。"""
    lines = [_csv_line(["id", "text", "done"])]
    for row in _export_rows(todos):
        lines.append(_csv_line([row["id"], row["text"], "true" if row["done"] else "false"]))
    return "".join(lines)


_RENDERERS = {"json": render_json, "csv": render_csv}


def _cmd_export(args: argparse.Namespace) -> int:
    fmt = args.fmt
    if fmt is None:
        print("错误：缺少 --format（可选：json、csv）", file=sys.stderr)
        return EXIT_USAGE
    if fmt not in EXPORT_FORMATS:
        print(f"错误：不支持的导出格式：{fmt}（可选：json、csv）", file=sys.stderr)
        return EXIT_USAGE
    if args.output is not None:
        if not args.output.strip():
            print("错误：--output 不能为空", file=sys.stderr)
            return EXIT_USAGE
        out = Path(args.output)
        if out.resolve() == Path(args.db).resolve():
            print(f"错误：--output 不能与数据文件相同：{args.output}", file=sys.stderr)
            return EXIT_USAGE

    todos = storage.load(args.db)
    content = _RENDERERS[fmt](todos)

    if args.output is None:
        sys.stdout.write(content)
        return EXIT_OK
    try:
        storage.write_atomic(args.output, content.encode("utf-8"))
    except OSError as e:
        print(f"错误：无法写入导出文件 {args.output}：{e}", file=sys.stderr)
        return EXIT_IO
    print(f"已导出 {len(todos)} 条待办到 {args.output}（{fmt}）")
    return EXIT_OK


_COMMANDS = {
    "add": _cmd_add,
    "list": _cmd_list,
    "done": _cmd_done,
    "remove": _cmd_remove,
    "export": _cmd_export,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _COMMANDS.get(args.command)
    if handler is not None:
        try:
            return handler(args)
        except storage.CorruptDBError as e:
            # 损坏的数据文件一律不写回，保留原样交给用户处理。
            print(f"错误：{e}，未做任何修改，请手动修复或移走该文件", file=sys.stderr)
            return EXIT_CORRUPT_DB
    parser.print_help()
    return EXIT_OK
